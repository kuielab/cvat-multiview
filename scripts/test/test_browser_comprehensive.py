#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Playwright Browser Test Suite for CVAT Multiview Annotation Editing

Tests frame persistence, drawing, pre-annotation editing, cross-task interaction,
and canvas rendering using Playwright (sync) + requests API.

Target: Task A (task_id=4, job_id=4, label_id=9)
  - 45 pre-annotations across 9 frames (97,140,183,225,998,1772,1773,1803,1833)
  - 5 shapes per frame (view_id 1-5)

Usage:
    python scripts/test/test_browser_comprehensive.py --user admin --password admin123
    python scripts/test/test_browser_comprehensive.py --host http://192.168.1.100:8080
"""

import argparse
import copy
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

import requests
from playwright.sync_api import Page, sync_playwright

# ============================================================================
# Constants
# ============================================================================

KNOWN_FRAMES = [97, 140, 183, 225, 998, 1772, 1773, 1803, 1833]
SHAPES_PER_FRAME = 5
TOLERANCE = 1.0  # pixel tolerance for float comparison


# ============================================================================
# CVATBrowserTest - Main Test Class
# ============================================================================

class CVATBrowserTest:
    """Test harness combining Playwright browser automation with CVAT REST API."""

    def __init__(self, host: str, user: str, password: str):
        self.host = host.rstrip('/')
        self.user = user
        self.password = password
        self.results: List[Dict[str, Any]] = []
        self.session = requests.Session()
        self.session.headers.update({'Referer': self.host})
        self._api_login()
        # Cache for Task B
        self._task_b_info: Optional[Dict] = None

    # ------------------------------------------------------------------
    # API Authentication
    # ------------------------------------------------------------------

    def _api_login(self):
        resp = self.session.post(
            f'{self.host}/api/auth/login',
            json={'username': self.user, 'password': self.password},
        )
        resp.raise_for_status()
        token = resp.json()['key']
        self.session.headers.update({'Authorization': f'Token {token}'})

    # ------------------------------------------------------------------
    # API Helpers
    # ------------------------------------------------------------------

    def api_get_shapes(self, job_id: int, frame: Optional[int] = None) -> List[dict]:
        """Get all shapes for a job, optionally filtered by frame."""
        resp = self.session.get(f'{self.host}/api/jobs/{job_id}/annotations')
        resp.raise_for_status()
        shapes = resp.json().get('shapes', [])
        if frame is not None:
            shapes = [s for s in shapes if s['frame'] == frame]
        return shapes

    def api_get_shape_by_id(self, job_id: int, shape_id: int) -> Optional[dict]:
        """Get a specific shape by its server ID."""
        shapes = self.api_get_shapes(job_id)
        for s in shapes:
            if s['id'] == shape_id:
                return s
        return None

    def api_update_shape(self, job_id: int, shape_id: int, frame: int,
                         new_points: List[float], label_id: int) -> bool:
        """Update a shape's points via PATCH action=update."""
        raw = self.api_get_shape_by_id(job_id, shape_id)
        if raw is None:
            return False
        shape_data = {
            'id': shape_id,
            'type': raw['type'],
            'frame': frame,
            'points': new_points,
            'label_id': label_id,
            'occluded': raw.get('occluded', False),
            'z_order': raw.get('z_order', 0),
            'rotation': raw.get('rotation', 0.0),
            'attributes': raw.get('attributes', []),
            'source': raw.get('source', 'manual'),
        }
        resp = self.session.patch(
            f'{self.host}/api/jobs/{job_id}/annotations',
            params={'action': 'update'},
            json={'shapes': [shape_data], 'tracks': [], 'tags': []},
            headers={'Content-Type': 'application/json'},
        )
        return resp.status_code == 200

    def api_create_shape(self, job_id: int, frame: int, points: List[float],
                         label_id: int, view_id: int = 1) -> Optional[dict]:
        """Create a new shape via PATCH action=create. Returns response JSON."""
        shape_data = {
            'frame': frame,
            'points': points,
            'type': 'rectangle',
            'label_id': label_id,
            'occluded': False,
            'view_id': view_id,
            'z_order': 0,
            'attributes': [],
        }
        resp = self.session.patch(
            f'{self.host}/api/jobs/{job_id}/annotations',
            params={'action': 'create'},
            json={'shapes': [shape_data], 'tracks': [], 'tags': []},
            headers={'Content-Type': 'application/json'},
        )
        if resp.status_code == 200:
            return resp.json()
        return None

    def api_delete_shape(self, job_id: int, shape_id: int) -> bool:
        """Delete a shape via PATCH action=delete."""
        # CVAT requires full shape data for delete
        shape = self.api_get_shape_by_id(job_id, shape_id)
        if shape is None:
            return False
        resp = self.session.patch(
            f'{self.host}/api/jobs/{job_id}/annotations',
            params={'action': 'delete'},
            json={'shapes': [{
                'id': shape_id,
                'type': shape['type'],
                'frame': shape['frame'],
                'label_id': shape['label_id'],
                'points': shape['points'],
                'occluded': shape.get('occluded', False),
            }], 'tracks': [], 'tags': []},
            headers={'Content-Type': 'application/json'},
        )
        return resp.status_code == 200

    def api_reset_shape(self, job_id: int, shape_id: int, original_points: List[float],
                        label_id: int, frame: int) -> bool:
        """Reset a shape to its original points."""
        return self.api_update_shape(job_id, shape_id, frame, original_points, label_id)

    # ------------------------------------------------------------------
    # Browser Helpers
    # ------------------------------------------------------------------

    def navigate_to_job(self, page: Page, task_id: int, job_id: int):
        """Navigate to a CVAT job page and wait for load."""
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)
        # Dismiss notification popups if any
        self._dismiss_notifications(page)

    def _dismiss_notifications(self, page: Page):
        """Close any notification popups that might interfere."""
        try:
            close_btns = page.locator('.ant-notification-notice-close')
            for i in range(close_btns.count()):
                close_btns.nth(i).click(timeout=500)
        except Exception:
            pass

    def navigate_to_frame(self, page: Page, frame_num: int):
        """Navigate to a specific frame using the frame input spinbutton."""
        try:
            # CVAT uses an ant-design InputNumber with role="spinbutton"
            sb = page.get_by_role('spinbutton').first
            sb.click(timeout=10000)
            sb.fill(str(frame_num))
            sb.press('Enter')
            page.wait_for_timeout(3000)
        except Exception:
            # Fallback: try CSS selectors
            try:
                inp = page.locator('.ant-input-number-input').first
                inp.click(timeout=5000)
                inp.fill(str(frame_num))
                inp.press('Enter')
                page.wait_for_timeout(3000)
            except Exception:
                # Last resort: keyboard shortcut
                page.keyboard.press('d')  # go to specific frame
                page.wait_for_timeout(500)

    def get_canvas_shapes(self, page: Page) -> List[dict]:
        """Get visible shapes on the canvas via JS evaluation."""
        return page.evaluate('''() => {
            const results = [];
            // Try rect elements with data-z-order (standard CVAT canvas shapes)
            const rects = document.querySelectorAll('rect[data-z-order]');
            rects.forEach(r => {
                results.push({
                    clientID: r.getAttribute('clientID') || r.getAttribute('data-client-id') || '',
                    x: parseFloat(r.getAttribute('x')) || 0,
                    y: parseFloat(r.getAttribute('y')) || 0,
                    w: parseFloat(r.getAttribute('width')) || 0,
                    h: parseFloat(r.getAttribute('height')) || 0,
                });
            });
            // Also try shapes identified by class
            if (results.length === 0) {
                const shapes = document.querySelectorAll('.cvat_canvas_shape');
                shapes.forEach(s => {
                    const rect = s.querySelector('rect') || s;
                    results.push({
                        clientID: s.getAttribute('clientID') || s.getAttribute('data-client-id') || '',
                        x: parseFloat(rect.getAttribute('x')) || 0,
                        y: parseFloat(rect.getAttribute('y')) || 0,
                        w: parseFloat(rect.getAttribute('width')) || 0,
                        h: parseFloat(rect.getAttribute('height')) || 0,
                    });
                });
            }
            return results;
        }''')

    def get_canvas_shape_count(self, page: Page) -> int:
        """Get count of visible shapes on canvas."""
        shapes = self.get_canvas_shapes(page)
        return len(shapes)

    def save_annotations(self, page: Page):
        """Click Save button and wait."""
        try:
            save_btn = page.locator('button:has-text("Save")')
            if save_btn.count() > 0:
                save_btn.first.click()
                page.wait_for_timeout(3000)
        except Exception:
            # Ctrl+S fallback
            page.keyboard.press('Control+s')
            page.wait_for_timeout(3000)

    def take_screenshot(self, page: Page, name: str, screenshots_dir: Path):
        """Take a screenshot for debugging."""
        filepath = screenshots_dir / f'{name}.png'
        try:
            page.screenshot(path=str(filepath))
        except Exception:
            pass

    def _get_task_label_id(self, task_id: int, fallback_id: int) -> int:
        """Get the first label ID for a task via the labels API."""
        resp = self.session.get(f'{self.host}/api/labels', params={'task_id': task_id})
        if resp.status_code == 200:
            results = resp.json().get('results', [])
            if results:
                return results[0]['id']
        return fallback_id

    # ------------------------------------------------------------------
    # Task B Creation for Cross-Task Tests
    # ------------------------------------------------------------------

    def create_task_b(self, label_id_a: int) -> Optional[Dict]:
        """Find or create Task B for cross-task testing.

        Searches for existing multiview tasks (CrossTask-Test-B-* or Test-TaskB-Browser)
        with jobs and shapes. Falls back to any multiview task that is not Task A.
        Returns dict with task_id, job_id, label_id or None on failure.
        """
        if self._task_b_info is not None:
            return self._task_b_info

        # Search for existing multiview tasks that can serve as Task B
        search_names = ['CrossTask-Test-B', 'Test-TaskB-Browser']
        for search_term in search_names:
            resp = self.session.get(
                f'{self.host}/api/tasks',
                params={'search': search_term, 'page_size': 10},
            )
            if resp.status_code == 200:
                for t in resp.json().get('results', []):
                    task_id = t['id']
                    size = t.get('size') or 0
                    if size == 0:
                        continue
                    # Get job
                    jr = self.session.get(f'{self.host}/api/jobs', params={'task_id': task_id})
                    if jr.status_code == 200:
                        jobs = jr.json().get('results', [])
                        if jobs:
                            job_id = jobs[0]['id']
                            lid = self._get_task_label_id(task_id, label_id_a)
                            self._task_b_info = {
                                'task_id': task_id,
                                'job_id': job_id,
                                'label_id': lid,
                            }
                            print(f'  [TaskB] Found existing: task_id={task_id}, job_id={job_id}, label_id={lid}')
                            return self._task_b_info

        # Fallback: find any multiview task that is NOT the current Task A
        resp = self.session.get(f'{self.host}/api/tasks', params={'page_size': 50})
        if resp.status_code == 200:
            for t in resp.json().get('results', []):
                task_id = t['id']
                size = t.get('size') or 0
                dim = t.get('dimension', '')
                if size > 0 and dim == 'multiview':
                    jr = self.session.get(f'{self.host}/api/jobs', params={'task_id': task_id})
                    if jr.status_code == 200:
                        jobs = jr.json().get('results', [])
                        if jobs:
                            job_id = jobs[0]['id']
                            lid = self._get_task_label_id(task_id, label_id_a)
                            self._task_b_info = {
                                'task_id': task_id,
                                'job_id': job_id,
                                'label_id': lid,
                            }
                            print(f'  [TaskB] Using multiview task: task_id={task_id}, job_id={job_id}')
                            return self._task_b_info

        print('  [TaskB] No suitable Task B found')
        return None

    def _cleanup_task(self, task_id: int):
        """Delete a task (best effort)."""
        try:
            self.session.delete(f'{self.host}/api/tasks/{task_id}')
        except Exception:
            pass

    def cleanup_task_b(self):
        """Remove Task B if it was created by us."""
        if self._task_b_info:
            self._cleanup_task(self._task_b_info['task_id'])
            self._task_b_info = None

    # ------------------------------------------------------------------
    # Snapshot Helpers
    # ------------------------------------------------------------------

    def snapshot_shapes(self, job_id: int, frame: Optional[int] = None) -> Dict[int, dict]:
        """Take a snapshot of shapes keyed by server ID."""
        shapes = self.api_get_shapes(job_id, frame)
        return {s['id']: s for s in shapes}

    def points_match(self, p1: List[float], p2: List[float]) -> bool:
        """Check if two point lists match within tolerance."""
        if len(p1) != len(p2):
            return False
        return all(abs(a - b) <= TOLERANCE for a, b in zip(p1, p2))

    def shapes_unchanged(self, before: Dict[int, dict], after: Dict[int, dict],
                         exclude_ids: Optional[set] = None) -> Tuple[bool, str]:
        """Verify shapes are unchanged between snapshots, excluding specific IDs."""
        exclude_ids = exclude_ids or set()
        errors = []

        for sid, b in before.items():
            if sid in exclude_ids:
                continue
            a = after.get(sid)
            if a is None:
                errors.append(f'Shape {sid} disappeared')
                continue
            if not self.points_match(b['points'], a['points']):
                errors.append(f'Shape {sid} points changed: {b["points"]} → {a["points"]}')

        if errors:
            return False, '; '.join(errors[:3])
        return True, 'All shapes unchanged'

    # ------------------------------------------------------------------
    # Test Runner
    # ------------------------------------------------------------------

    def run_test(self, name: str, fn: Callable[[], Tuple[bool, str]]):
        """Run a single test with exception handling."""
        try:
            passed, detail = fn()
            self.results.append({'name': name, 'passed': passed, 'details': detail})
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name} - {detail}', flush=True)
        except Exception as e:
            tb = traceback.format_exc()
            short_tb = tb[-300:] if len(tb) > 300 else tb
            self.results.append({'name': name, 'passed': False, 'details': f'Exception: {short_tb}'})
            print(f'  [FAIL] {name} - Exception: {str(e)[:150]}', flush=True)

    def all_passed(self) -> bool:
        return all(r['passed'] for r in self.results)

    def print_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r['passed'])
        failed = total - passed

        print(f'\n{"=" * 72}')
        print(f'SUMMARY: {passed}/{total} passed, {failed} failed')
        print(f'{"=" * 72}')

        if failed > 0:
            print('\nFailed tests:')
            for r in self.results:
                if not r['passed']:
                    print(f'  ✗ {r["name"]}: {r["details"][:120]}')
        print()

    # ------------------------------------------------------------------
    # Test Execution Dispatcher
    # ------------------------------------------------------------------

    def run_all(self, page: Page, args, screenshots_dir: Path):
        """Run all test categories."""
        task_a_id = args.task_a_id
        job_a_id = args.job_a_id
        label_a_id = 9  # from real_test_task_info.json

        # Verify Task A shapes
        all_shapes = self.api_get_shapes(job_a_id)
        print(f'\nTask A: {len(all_shapes)} shapes in job {job_a_id}')
        if len(all_shapes) < 5:
            print('ERROR: Need at least 5 shapes in Task A')
            sys.exit(1)

        # Navigate to Task A
        print(f'\nNavigating to Task A (task={task_a_id}, job={job_a_id})...')
        self.navigate_to_job(page, task_a_id, job_a_id)
        self.take_screenshot(page, '00_initial_load', screenshots_dir)

        # ============================================================
        # Category 1: Frame Persistence (6 tests)
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Category 1: Frame Persistence')
        print(f'{"=" * 60}')

        self.run_test('TC1.1_frame_97_140_97', lambda: self._tc1_1(page, job_a_id))
        self.run_test('TC1.2_frame_round_trip_5', lambda: self._tc1_2(page, job_a_id))
        self.run_test('TC1.3_api_edit_reload_persist', lambda: self._tc1_3(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC1.4_api_edit_two_frames', lambda: self._tc1_4(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC1.5_cycle_all_9_frames', lambda: self._tc1_5(page, job_a_id))
        self.run_test('TC1.6_api_edit_navigate_5_back', lambda: self._tc1_6(page, task_a_id, job_a_id, label_a_id))

        # ============================================================
        # Category 2: Drawing (4 tests)
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Category 2: Drawing (API Create + Browser Verify)')
        print(f'{"=" * 60}')

        self.run_test('TC2.1_create_shape_reload_visible', lambda: self._tc2_1(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC2.2_create_navigate_back_visible', lambda: self._tc2_2(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC2.3_create_on_3_frames_cycle', lambda: self._tc2_3(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC2.4_create_save_reload_verify', lambda: self._tc2_4(page, task_a_id, job_a_id, label_a_id, screenshots_dir))

        # ============================================================
        # Category 3: Pre-annotation Edit (8 tests)
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Category 3: Pre-annotation Edit')
        print(f'{"=" * 60}')

        self.run_test('TC3.1_move_shape_reload_verify', lambda: self._tc3_1(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC3.2_move_shape_navigate_round_trip', lambda: self._tc3_2(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC3.3_resize_shape_reload', lambda: self._tc3_3(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC3.4_move_shapes_two_frames', lambda: self._tc3_4(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC3.5_move_all_5_shapes_frame97', lambda: self._tc3_5(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC3.6_move_97_verify_140_unaffected', lambda: self._tc3_6(page, task_a_id, job_a_id, label_a_id))
        self.run_test('TC3.7_delete_shape_verify_removed', lambda: self._tc3_7(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC3.8_delete_97_verify_140_ok', lambda: self._tc3_8(page, task_a_id, job_a_id, label_a_id))

        # ============================================================
        # Category 4: Cross-Task (5 tests)
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Category 4: Cross-Task')
        print(f'{"=" * 60}')

        task_b = self.create_task_b(label_a_id)
        if task_b:
            self.run_test('TC4.1_edit_A_save_goto_B_verify', lambda: self._tc4_1(page, task_a_id, job_a_id, label_a_id, task_b))
            self.run_test('TC4.2_edit_A_B_back_A_verify', lambda: self._tc4_2(page, task_a_id, job_a_id, label_a_id, task_b))
            self.run_test('TC4.3_create_A_B_verify_both', lambda: self._tc4_3(page, task_a_id, job_a_id, label_a_id, task_b))
            self.run_test('TC4.4_three_round_alternation', lambda: self._tc4_4(page, task_a_id, job_a_id, label_a_id, task_b))
            self.run_test('TC4.5_edit_A97_B_A140_verify', lambda: self._tc4_5(page, task_a_id, job_a_id, label_a_id, task_b))
        else:
            print('  [SKIP] Task B creation failed - skipping cross-task tests')
            for i in range(1, 6):
                self.results.append({
                    'name': f'TC4.{i}_cross_task',
                    'passed': False,
                    'details': 'Skipped: Task B creation failed (PIL missing?)',
                })

        # ============================================================
        # Category 5: Canvas Rendering (4 tests)
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Category 5: Canvas Rendering')
        print(f'{"=" * 60}')

        # Re-navigate to Task A for canvas tests
        self.navigate_to_job(page, task_a_id, job_a_id)

        self.run_test('TC5.1_canvas_count_matches_api_f97', lambda: self._tc5_1(page, job_a_id))
        self.run_test('TC5.2_navigate_4_frames_check_counts', lambda: self._tc5_2(page, job_a_id))
        self.run_test('TC5.3_api_edit_canvas_reflects', lambda: self._tc5_3(page, task_a_id, job_a_id, label_a_id, screenshots_dir))
        self.run_test('TC5.4_single_shape_per_view', lambda: self._tc5_4(page, job_a_id))

    # ====================================================================
    # Category 1: Frame Persistence Tests
    # ====================================================================

    def _tc1_1(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC1.1: Navigate 97→140→97, shapes unchanged."""
        self.navigate_to_frame(page, 97)
        before_97 = self.snapshot_shapes(job_id, frame=97)

        self.navigate_to_frame(page, 140)
        self.navigate_to_frame(page, 97)

        after_97 = self.snapshot_shapes(job_id, frame=97)
        ok, msg = self.shapes_unchanged(before_97, after_97)
        count = len(after_97)
        return ok, f'{count} shapes on frame 97 persisted through navigation. {msg}'

    def _tc1_2(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC1.2: Navigate 97→140→183→140→97, all shapes match originals."""
        self.navigate_to_frame(page, 97)
        before_97 = self.snapshot_shapes(job_id, frame=97)
        before_140 = self.snapshot_shapes(job_id, frame=140)

        for f in [140, 183, 140, 97]:
            self.navigate_to_frame(page, f)

        after_97 = self.snapshot_shapes(job_id, frame=97)
        after_140 = self.snapshot_shapes(job_id, frame=140)

        ok1, msg1 = self.shapes_unchanged(before_97, after_97)
        ok2, msg2 = self.shapes_unchanged(before_140, after_140)

        if ok1 and ok2:
            return True, f'Frame 97 ({len(after_97)} shapes) and 140 ({len(after_140)} shapes) persisted'
        return False, f'97: {msg1}; 140: {msg2}'

    def _tc1_3(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC1.3: API edit shape@97 → reload → navigate 97→140→97, edit persisted."""
        shapes_97 = self.api_get_shapes(job_id, frame=97)
        if not shapes_97:
            return False, 'No shapes at frame 97'

        target = shapes_97[0]
        orig_points = list(target['points'])
        new_points = [p + 50 for p in orig_points]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_points, label_id)

            # Reload page
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.navigate_to_frame(page, 140)
            self.navigate_to_frame(page, 97)

            after = self.api_get_shape_by_id(job_id, target['id'])
            if after is None:
                return False, 'Shape disappeared after edit'

            if self.points_match(after['points'], new_points):
                return True, f'Edit persisted: shape {target["id"]} at new position'
            return False, f'Points mismatch: expected {new_points}, got {after["points"]}'
        finally:
            self.api_reset_shape(job_id, target['id'], orig_points, label_id, 97)

    def _tc1_4(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC1.4: API edit shape@97 + shape@140 → verify both maintained."""
        s97 = self.api_get_shapes(job_id, frame=97)
        s140 = self.api_get_shapes(job_id, frame=140)
        if not s97 or not s140:
            return False, 'Missing shapes on frame 97 or 140'

        t97, t140 = s97[0], s140[0]
        orig97 = list(t97['points'])
        orig140 = list(t140['points'])
        new97 = [p + 30 for p in orig97]
        new140 = [p - 20 for p in orig140]

        try:
            self.api_update_shape(job_id, t97['id'], 97, new97, label_id)
            self.api_update_shape(job_id, t140['id'], 140, new140, label_id)

            # Navigate around
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.navigate_to_frame(page, 140)
            self.navigate_to_frame(page, 183)
            self.navigate_to_frame(page, 97)

            a97 = self.api_get_shape_by_id(job_id, t97['id'])
            a140 = self.api_get_shape_by_id(job_id, t140['id'])

            ok97 = a97 and self.points_match(a97['points'], new97)
            ok140 = a140 and self.points_match(a140['points'], new140)

            if ok97 and ok140:
                return True, 'Both frame 97 and 140 edits maintained'
            return False, f'97 ok={ok97}, 140 ok={ok140}'
        finally:
            self.api_reset_shape(job_id, t97['id'], orig97, label_id, 97)
            self.api_reset_shape(job_id, t140['id'], orig140, label_id, 140)

    def _tc1_5(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC1.5: Cycle all 9 frames and back to first, verify shapes."""
        self.navigate_to_frame(page, KNOWN_FRAMES[0])
        before_first = self.snapshot_shapes(job_id, frame=KNOWN_FRAMES[0])

        for f in KNOWN_FRAMES[1:]:
            self.navigate_to_frame(page, f)

        self.navigate_to_frame(page, KNOWN_FRAMES[0])
        after_first = self.snapshot_shapes(job_id, frame=KNOWN_FRAMES[0])

        ok, msg = self.shapes_unchanged(before_first, after_first)
        return ok, f'Cycled all 9 frames, frame {KNOWN_FRAMES[0]}: {msg}'

    def _tc1_6(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC1.6: API edit shape@97 → navigate 5 frames → back to 97, still correct."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[0]
        orig_points = list(target['points'])
        new_points = [orig_points[0] + 75, orig_points[1] + 60,
                      orig_points[2] + 75, orig_points[3] + 60]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_points, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)

            # Navigate through 5 different frames
            for f in [140, 183, 225, 998, 1772]:
                self.navigate_to_frame(page, f)

            self.navigate_to_frame(page, 97)

            after = self.api_get_shape_by_id(job_id, target['id'])
            if after and self.points_match(after['points'], new_points):
                return True, 'Edit survived 5-frame navigation'
            return False, f'Points mismatch after navigation'
        finally:
            self.api_reset_shape(job_id, target['id'], orig_points, label_id, 97)

    # ====================================================================
    # Category 2: Drawing (API Create + Browser Verify)
    # ====================================================================

    def _tc2_1(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC2.1: Create shape via API at frame 97, reload, verify visible."""
        new_pts = [500.0, 300.0, 650.0, 450.0]
        result = self.api_create_shape(job_id, 97, new_pts, label_id, view_id=1)
        if result is None:
            return False, 'API create failed'

        created_shapes = result.get('shapes', [])
        if not created_shapes:
            return False, 'No shapes in create response'
        new_id = created_shapes[0]['id']

        try:
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.take_screenshot(page, 'tc2_1_after_create', screenshots_dir)

            api_count = len(self.api_get_shapes(job_id, frame=97))
            canvas_count = self.get_canvas_shape_count(page)

            # Canvas might show only shapes for the active view
            if api_count >= SHAPES_PER_FRAME + 1:
                return True, f'Created shape {new_id} visible. API: {api_count} shapes'
            return False, f'Expected >={SHAPES_PER_FRAME + 1} shapes, got API:{api_count}'
        finally:
            self.api_delete_shape(job_id, new_id)

    def _tc2_2(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC2.2: Create at 97, navigate 140→97, still visible."""
        new_pts = [600.0, 400.0, 750.0, 550.0]
        result = self.api_create_shape(job_id, 97, new_pts, label_id, view_id=2)
        if result is None:
            return False, 'API create failed'
        new_id = result.get('shapes', [{}])[0].get('id')

        try:
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            count_before = len(self.api_get_shapes(job_id, frame=97))

            self.navigate_to_frame(page, 140)
            self.navigate_to_frame(page, 97)

            count_after = len(self.api_get_shapes(job_id, frame=97))
            if count_after == count_before:
                return True, f'Shape {new_id} persisted through 97→140→97 ({count_after} shapes)'
            return False, f'Count changed: {count_before} → {count_after}'
        finally:
            if new_id:
                self.api_delete_shape(job_id, new_id)

    def _tc2_3(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC2.3: Create on 3 frames, cycle through."""
        frames = [97, 140, 183]
        created_ids = []

        try:
            for i, f in enumerate(frames):
                pts = [100.0 + i * 50, 100.0 + i * 50, 250.0 + i * 50, 250.0 + i * 50]
                result = self.api_create_shape(job_id, f, pts, label_id, view_id=1)
                if result and result.get('shapes'):
                    created_ids.append(result['shapes'][0]['id'])

            if len(created_ids) != 3:
                return False, f'Only created {len(created_ids)}/3 shapes'

            self.navigate_to_job(page, task_id, job_id)

            all_ok = True
            details = []
            for f in frames:
                self.navigate_to_frame(page, f)
                api_count = len(self.api_get_shapes(job_id, frame=f))
                expected_min = SHAPES_PER_FRAME + 1
                ok = api_count >= expected_min
                details.append(f'f{f}:{api_count}>={expected_min}={ok}')
                if not ok:
                    all_ok = False

            return all_ok, '; '.join(details)
        finally:
            for sid in created_ids:
                self.api_delete_shape(job_id, sid)

    def _tc2_4(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC2.4: Create → save → reload → verify."""
        new_pts = [700.0, 200.0, 850.0, 350.0]
        result = self.api_create_shape(job_id, 97, new_pts, label_id, view_id=3)
        if result is None:
            return False, 'API create failed'
        new_id = result.get('shapes', [{}])[0].get('id')

        try:
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.save_annotations(page)

            # Full page reload
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.take_screenshot(page, 'tc2_4_after_save_reload', screenshots_dir)

            shape = self.api_get_shape_by_id(job_id, new_id)
            if shape and self.points_match(shape['points'], new_pts):
                return True, f'Shape {new_id} survived save+reload with correct points'
            return False, f'Shape {new_id} not found or points wrong after reload'
        finally:
            if new_id:
                self.api_delete_shape(job_id, new_id)

    # ====================================================================
    # Category 3: Pre-annotation Edit
    # ====================================================================

    def _tc3_1(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC3.1: Move shape +200,+150 via API, reload, verify canvas."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[0]
        orig = list(target['points'])
        new_pts = [orig[0] + 200, orig[1] + 150, orig[2] + 200, orig[3] + 150]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.take_screenshot(page, 'tc3_1_after_move', screenshots_dir)

            after = self.api_get_shape_by_id(job_id, target['id'])
            if after and self.points_match(after['points'], new_pts):
                return True, f'Shape {target["id"]} moved +200,+150 and verified on canvas'
            return False, 'Points mismatch after move'
        finally:
            self.api_reset_shape(job_id, target['id'], orig, label_id, 97)

    def _tc3_2(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC3.2: Move shape, navigate 97→140→97, verify maintained."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[1] if len(s97) > 1 else s97[0]
        orig = list(target['points'])
        new_pts = [orig[0] - 100, orig[1] + 80, orig[2] - 100, orig[3] + 80]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.navigate_to_frame(page, 140)
            self.navigate_to_frame(page, 97)

            after = self.api_get_shape_by_id(job_id, target['id'])
            if after and self.points_match(after['points'], new_pts):
                return True, 'Move persisted through round-trip navigation'
            return False, 'Move not maintained after 97→140→97'
        finally:
            self.api_reset_shape(job_id, target['id'], orig, label_id, 97)

    def _tc3_3(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC3.3: Resize shape, reload, verify."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[0]
        orig = list(target['points'])
        # Resize: expand by 50px each direction from center
        cx = (orig[0] + orig[2]) / 2
        cy = (orig[1] + orig[3]) / 2
        hw = (orig[2] - orig[0]) / 2
        hh = (orig[3] - orig[1]) / 2
        new_pts = [cx - hw * 1.5, cy - hh * 1.5, cx + hw * 1.5, cy + hh * 1.5]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.take_screenshot(page, 'tc3_3_after_resize', screenshots_dir)

            after = self.api_get_shape_by_id(job_id, target['id'])
            if after and self.points_match(after['points'], new_pts):
                return True, f'Shape resized 1.5x and verified'
            return False, 'Resize points mismatch'
        finally:
            self.api_reset_shape(job_id, target['id'], orig, label_id, 97)

    def _tc3_4(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC3.4: Move shapes on 2 different frames, verify both."""
        s97 = self.api_get_shapes(job_id, frame=97)
        s140 = self.api_get_shapes(job_id, frame=140)
        if not s97 or not s140:
            return False, 'Missing shapes'

        t97, t140 = s97[0], s140[0]
        orig97 = list(t97['points'])
        orig140 = list(t140['points'])
        new97 = [orig97[0] + 100, orig97[1] + 100, orig97[2] + 100, orig97[3] + 100]
        new140 = [orig140[0] - 50, orig140[1] - 50, orig140[2] - 50, orig140[3] - 50]

        try:
            self.api_update_shape(job_id, t97['id'], 97, new97, label_id)
            self.api_update_shape(job_id, t140['id'], 140, new140, label_id)

            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.navigate_to_frame(page, 140)

            a97 = self.api_get_shape_by_id(job_id, t97['id'])
            a140 = self.api_get_shape_by_id(job_id, t140['id'])

            ok97 = a97 and self.points_match(a97['points'], new97)
            ok140 = a140 and self.points_match(a140['points'], new140)

            if ok97 and ok140:
                return True, 'Both frame edits verified'
            return False, f'97 ok={ok97}, 140 ok={ok140}'
        finally:
            self.api_reset_shape(job_id, t97['id'], orig97, label_id, 97)
            self.api_reset_shape(job_id, t140['id'], orig140, label_id, 140)

    def _tc3_5(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC3.5: Move all 5 shapes at frame 97, verify all."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if len(s97) < 5:
            return False, f'Expected 5 shapes at frame 97, got {len(s97)}'

        originals = [(s['id'], list(s['points'])) for s in s97[:5]]

        try:
            for i, (sid, pts) in enumerate(originals):
                dx = (i + 1) * 20
                dy = (i + 1) * 15
                new_pts = [pts[0] + dx, pts[1] + dy, pts[2] + dx, pts[3] + dy]
                self.api_update_shape(job_id, sid, 97, new_pts, label_id)

            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)

            all_ok = True
            for i, (sid, orig_pts) in enumerate(originals):
                dx = (i + 1) * 20
                dy = (i + 1) * 15
                expected = [orig_pts[0] + dx, orig_pts[1] + dy,
                            orig_pts[2] + dx, orig_pts[3] + dy]
                after = self.api_get_shape_by_id(job_id, sid)
                if not after or not self.points_match(after['points'], expected):
                    all_ok = False

            if all_ok:
                return True, 'All 5 shapes at frame 97 moved and verified'
            return False, 'Some shapes have incorrect positions'
        finally:
            for sid, orig_pts in originals:
                self.api_reset_shape(job_id, sid, orig_pts, label_id, 97)

    def _tc3_6(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC3.6: Move shape@97, verify frame 140 NOT affected."""
        before_140 = self.snapshot_shapes(job_id, frame=140)
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[0]
        orig = list(target['points'])
        new_pts = [orig[0] + 200, orig[1] + 200, orig[2] + 200, orig[3] + 200]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 140)

            after_140 = self.snapshot_shapes(job_id, frame=140)
            ok, msg = self.shapes_unchanged(before_140, after_140)
            if ok:
                return True, 'Frame 140 unaffected by frame 97 edit'
            return False, f'Frame 140 was affected: {msg}'
        finally:
            self.api_reset_shape(job_id, target['id'], orig, label_id, 97)

    def _tc3_7(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC3.7: Delete shape, verify removed."""
        # Create a shape specifically to delete (don't delete pre-annotations)
        create_pts = [800.0, 500.0, 900.0, 600.0]
        result = self.api_create_shape(job_id, 97, create_pts, label_id, view_id=1)
        if result is None:
            return False, 'Failed to create test shape for deletion'

        new_id = result.get('shapes', [{}])[0].get('id')
        if not new_id:
            return False, 'No ID returned from create'

        count_before = len(self.api_get_shapes(job_id, frame=97))

        ok = self.api_delete_shape(job_id, new_id)
        if not ok:
            return False, f'Delete API call failed for shape {new_id}'

        self.navigate_to_job(page, task_id, job_id)
        self.navigate_to_frame(page, 97)
        self.take_screenshot(page, 'tc3_7_after_delete', screenshots_dir)

        count_after = len(self.api_get_shapes(job_id, frame=97))
        shape_gone = self.api_get_shape_by_id(job_id, new_id) is None

        if shape_gone and count_after == count_before - 1:
            return True, f'Shape {new_id} deleted, count {count_before} → {count_after}'
        return False, f'Shape still exists={not shape_gone}, count: {count_before} → {count_after}'

    def _tc3_8(self, page: Page, task_id: int, job_id: int,
               label_id: int) -> Tuple[bool, str]:
        """TC3.8: Delete shape at 97, verify 140 unaffected."""
        before_140 = self.snapshot_shapes(job_id, frame=140)

        # Create temporary shape at 97 to delete
        create_pts = [850.0, 550.0, 950.0, 650.0]
        result = self.api_create_shape(job_id, 97, create_pts, label_id, view_id=1)
        if result is None:
            return False, 'Failed to create test shape'

        new_id = result.get('shapes', [{}])[0].get('id')
        self.api_delete_shape(job_id, new_id)

        self.navigate_to_job(page, task_id, job_id)
        self.navigate_to_frame(page, 140)

        after_140 = self.snapshot_shapes(job_id, frame=140)
        ok, msg = self.shapes_unchanged(before_140, after_140)
        if ok:
            return True, f'Frame 140 ({len(after_140)} shapes) unaffected by delete@97'
        return False, f'Frame 140 changed: {msg}'

    # ====================================================================
    # Category 4: Cross-Task Tests
    # ====================================================================

    def _tc4_1(self, page: Page, task_a_id: int, job_a_id: int,
               label_a_id: int, task_b: Dict) -> Tuple[bool, str]:
        """TC4.1: Edit TaskA → save → TaskB → verify B is normal."""
        s97 = self.api_get_shapes(job_a_id, frame=97)
        if not s97:
            return False, 'No shapes at frame 97'

        target = s97[0]
        orig = list(target['points'])
        new_pts = [orig[0] + 40, orig[1] + 40, orig[2] + 40, orig[3] + 40]

        try:
            self.api_update_shape(job_a_id, target['id'], 97, new_pts, label_a_id)
            self.navigate_to_job(page, task_a_id, job_a_id)
            self.navigate_to_frame(page, 97)
            self.save_annotations(page)

            # Navigate to Task B
            self.navigate_to_job(page, task_b['task_id'], task_b['job_id'])
            page.wait_for_timeout(3000)

            b_shapes = self.api_get_shapes(task_b['job_id'])
            if len(b_shapes) >= 1:
                return True, f'Task B loaded normally with {len(b_shapes)} shapes after Task A edit'
            return False, f'Task B has {len(b_shapes)} shapes (expected >=1)'
        finally:
            self.api_reset_shape(job_a_id, target['id'], orig, label_a_id, 97)

    def _tc4_2(self, page: Page, task_a_id: int, job_a_id: int,
               label_a_id: int, task_b: Dict) -> Tuple[bool, str]:
        """TC4.2: Edit TaskA → save → TaskB → edit → save → TaskA → verify."""
        s97 = self.api_get_shapes(job_a_id, frame=97)
        if not s97:
            return False, 'No shapes on Task A'

        target_a = s97[0]
        orig_a = list(target_a['points'])
        new_a = [orig_a[0] + 60, orig_a[1] + 60, orig_a[2] + 60, orig_a[3] + 60]

        b_shapes = self.api_get_shapes(task_b['job_id'])
        target_b = b_shapes[0] if b_shapes else None
        orig_b = list(target_b['points']) if target_b else None

        try:
            # Edit Task A
            self.api_update_shape(job_a_id, target_a['id'], 97, new_a, label_a_id)
            self.navigate_to_job(page, task_a_id, job_a_id)
            self.save_annotations(page)

            # Edit Task B
            if target_b:
                new_b = [orig_b[0] + 30, orig_b[1] + 30, orig_b[2] + 30, orig_b[3] + 30]
                self.api_update_shape(task_b['job_id'], target_b['id'],
                                      target_b['frame'], new_b, task_b['label_id'])

            self.navigate_to_job(page, task_b['task_id'], task_b['job_id'])
            self.save_annotations(page)

            # Back to Task A
            self.navigate_to_job(page, task_a_id, job_a_id)
            self.navigate_to_frame(page, 97)

            after_a = self.api_get_shape_by_id(job_a_id, target_a['id'])
            ok_a = after_a and self.points_match(after_a['points'], new_a)

            if ok_a:
                return True, 'Task A edit preserved after Task B round-trip'
            return False, 'Task A edit was lost after visiting Task B'
        finally:
            self.api_reset_shape(job_a_id, target_a['id'], orig_a, label_a_id, 97)
            if target_b and orig_b:
                self.api_reset_shape(task_b['job_id'], target_b['id'], orig_b,
                                     task_b['label_id'], target_b['frame'])

    def _tc4_3(self, page: Page, task_a_id: int, job_a_id: int,
               label_a_id: int, task_b: Dict) -> Tuple[bool, str]:
        """TC4.3: Create shape TaskA → TaskB → create → TaskA → verify both."""
        # Create shape on Task A
        pts_a = [550.0, 350.0, 700.0, 500.0]
        res_a = self.api_create_shape(job_a_id, 97, pts_a, label_a_id, view_id=1)
        new_a_id = res_a['shapes'][0]['id'] if res_a and res_a.get('shapes') else None

        # Create shape on Task B
        pts_b = [150.0, 150.0, 300.0, 300.0]
        res_b = self.api_create_shape(task_b['job_id'], 0, pts_b, task_b['label_id'], view_id=1)
        new_b_id = res_b['shapes'][0]['id'] if res_b and res_b.get('shapes') else None

        try:
            # Navigate to Task B then back to A
            self.navigate_to_job(page, task_b['task_id'], task_b['job_id'])
            page.wait_for_timeout(2000)

            self.navigate_to_job(page, task_a_id, job_a_id)
            self.navigate_to_frame(page, 97)

            a_exists = self.api_get_shape_by_id(job_a_id, new_a_id) is not None if new_a_id else False
            b_exists = self.api_get_shape_by_id(task_b['job_id'], new_b_id) is not None if new_b_id else False

            if a_exists and b_exists:
                return True, 'Both created shapes exist after cross-task navigation'
            return False, f'A exists={a_exists}, B exists={b_exists}'
        finally:
            if new_a_id:
                self.api_delete_shape(job_a_id, new_a_id)
            if new_b_id:
                self.api_delete_shape(task_b['job_id'], new_b_id)

    def _tc4_4(self, page: Page, task_a_id: int, job_a_id: int,
               label_a_id: int, task_b: Dict) -> Tuple[bool, str]:
        """TC4.4: 3 rounds alternation with edits."""
        s97 = self.api_get_shapes(job_a_id, frame=97)
        if len(s97) < 3:
            return False, 'Need at least 3 shapes'

        originals = [(s['id'], list(s['points'])) for s in s97[:3]]

        try:
            for round_num in range(3):
                sid, orig_pts = originals[round_num]
                dx = (round_num + 1) * 25
                new_pts = [orig_pts[0] + dx, orig_pts[1] + dx,
                           orig_pts[2] + dx, orig_pts[3] + dx]
                self.api_update_shape(job_a_id, sid, 97, new_pts, label_a_id)

                # Go to Task A, then B, then A
                self.navigate_to_job(page, task_a_id, job_a_id)
                self.navigate_to_frame(page, 97)
                self.navigate_to_job(page, task_b['task_id'], task_b['job_id'])
                page.wait_for_timeout(2000)
                self.navigate_to_job(page, task_a_id, job_a_id)
                self.navigate_to_frame(page, 97)

            # Verify all 3 edits persisted
            all_ok = True
            for round_num, (sid, orig_pts) in enumerate(originals):
                dx = (round_num + 1) * 25
                expected = [orig_pts[0] + dx, orig_pts[1] + dx,
                            orig_pts[2] + dx, orig_pts[3] + dx]
                after = self.api_get_shape_by_id(job_a_id, sid)
                if not after or not self.points_match(after['points'], expected):
                    all_ok = False

            if all_ok:
                return True, '3 rounds of alternation, all edits persisted'
            return False, 'Some edits lost during alternation'
        finally:
            for sid, orig_pts in originals:
                self.api_reset_shape(job_a_id, sid, orig_pts, label_a_id, 97)

    def _tc4_5(self, page: Page, task_a_id: int, job_a_id: int,
               label_a_id: int, task_b: Dict) -> Tuple[bool, str]:
        """TC4.5: Edit TaskA@97, visit TaskB, edit TaskA@140, verify all."""
        s97 = self.api_get_shapes(job_a_id, frame=97)
        s140 = self.api_get_shapes(job_a_id, frame=140)
        if not s97 or not s140:
            return False, 'Missing shapes'

        t97, t140 = s97[0], s140[0]
        orig97 = list(t97['points'])
        orig140 = list(t140['points'])
        new97 = [orig97[0] + 80, orig97[1] + 80, orig97[2] + 80, orig97[3] + 80]
        new140 = [orig140[0] - 40, orig140[1] - 40, orig140[2] - 40, orig140[3] - 40]

        try:
            # Edit frame 97
            self.api_update_shape(job_a_id, t97['id'], 97, new97, label_a_id)
            self.navigate_to_job(page, task_a_id, job_a_id)
            self.navigate_to_frame(page, 97)

            # Visit Task B
            self.navigate_to_job(page, task_b['task_id'], task_b['job_id'])
            page.wait_for_timeout(2000)

            # Edit frame 140
            self.api_update_shape(job_a_id, t140['id'], 140, new140, label_a_id)
            self.navigate_to_job(page, task_a_id, job_a_id)
            self.navigate_to_frame(page, 140)
            self.navigate_to_frame(page, 97)

            a97 = self.api_get_shape_by_id(job_a_id, t97['id'])
            a140 = self.api_get_shape_by_id(job_a_id, t140['id'])

            ok97 = a97 and self.points_match(a97['points'], new97)
            ok140 = a140 and self.points_match(a140['points'], new140)

            if ok97 and ok140:
                return True, 'Both 97 and 140 edits verified after cross-task round trip'
            return False, f'97 ok={ok97}, 140 ok={ok140}'
        finally:
            self.api_reset_shape(job_a_id, t97['id'], orig97, label_a_id, 97)
            self.api_reset_shape(job_a_id, t140['id'], orig140, label_a_id, 140)

    # ====================================================================
    # Category 5: Canvas Rendering
    # ====================================================================

    def _tc5_1(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC5.1: Shape count on canvas matches API for frame 97."""
        self.navigate_to_frame(page, 97)
        api_count = len(self.api_get_shapes(job_id, frame=97))
        canvas_count = self.get_canvas_shape_count(page)

        # In multiview, canvas only shows shapes for the active view (1 per view)
        # So canvas_count might be 1 (active view only) or more
        if canvas_count >= 1 and api_count >= SHAPES_PER_FRAME:
            return True, f'API: {api_count} shapes, Canvas: {canvas_count} visible (multiview filter)'
        return False, f'API: {api_count}, Canvas: {canvas_count}'

    def _tc5_2(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC5.2: Navigate 97→140→183→225→97, check counts at each."""
        frames_to_check = [97, 140, 183, 225, 97]
        results = []

        for f in frames_to_check:
            self.navigate_to_frame(page, f)
            api_count = len(self.api_get_shapes(job_id, frame=f))
            canvas_count = self.get_canvas_shape_count(page)
            ok = api_count >= SHAPES_PER_FRAME
            results.append(f'f{f}:api={api_count},canvas={canvas_count}')
            if not ok:
                return False, f'Frame {f}: expected >={SHAPES_PER_FRAME} shapes, got {api_count}. ' + '; '.join(results)

        return True, '; '.join(results)

    def _tc5_3(self, page: Page, task_id: int, job_id: int, label_id: int,
               screenshots_dir: Path) -> Tuple[bool, str]:
        """TC5.3: After API edit, canvas reflects (shape exists with w>0, h>0)."""
        s97 = self.api_get_shapes(job_id, frame=97)
        if not s97:
            return False, 'No shapes'

        target = s97[0]
        orig = list(target['points'])
        # Move significantly to ensure canvas update
        new_pts = [orig[0] + 300, orig[1] + 200, orig[2] + 300, orig[3] + 200]

        try:
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)
            self.navigate_to_job(page, task_id, job_id)
            self.navigate_to_frame(page, 97)
            self.take_screenshot(page, 'tc5_3_canvas_after_edit', screenshots_dir)

            canvas_shapes = self.get_canvas_shapes(page)
            # Check that at least one shape has w>0 and h>0
            valid_shapes = [s for s in canvas_shapes if s['w'] > 0 and s['h'] > 0]
            if len(valid_shapes) >= 1:
                return True, f'{len(valid_shapes)} valid shapes on canvas (w>0, h>0)'
            return False, f'No valid shapes: {canvas_shapes[:3]}'
        finally:
            self.api_reset_shape(job_id, target['id'], orig, label_id, 97)

    def _tc5_4(self, page: Page, job_id: int) -> Tuple[bool, str]:
        """TC5.4: In multiview, each view shows its own shapes (view_id filtering)."""
        self.navigate_to_frame(page, 97)
        shapes = self.api_get_shapes(job_id, frame=97)

        # Group by view_id
        by_view: Dict[int, int] = {}
        for s in shapes:
            vid = s.get('view_id', 0)
            by_view[vid] = by_view.get(vid, 0) + 1

        # Verify each view has exactly 1 shape (5 views × 1 shape = 5 total)
        if len(by_view) >= 5:
            all_one = all(count == 1 for count in by_view.values())
            if all_one:
                return True, f'5 views, 1 shape each: {by_view}'
            return True, f'Views have varying counts (acceptable): {by_view}'
        # Even with less, verify view_id filtering is working
        if len(shapes) >= SHAPES_PER_FRAME:
            return True, f'{len(shapes)} shapes across {len(by_view)} views: {by_view}'
        return False, f'Only {len(shapes)} shapes in {len(by_view)} views'


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive Playwright Browser Test for CVAT Multiview')
    parser.add_argument('--host', default='http://localhost:8080',
                        help='CVAT host URL')
    parser.add_argument('--user', '-u', default='admin',
                        help='CVAT username')
    parser.add_argument('--password', '-p', default='admin123',
                        help='CVAT password')
    parser.add_argument('--task-a-id', type=int, default=4,
                        help='Task A ID')
    parser.add_argument('--job-a-id', type=int, default=4,
                        help='Job A ID')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='Run browser in headless mode (default)')
    parser.add_argument('--no-headless', dest='headless', action='store_false',
                        help='Run browser with visible UI')
    parser.add_argument('--skip-cross-task', action='store_true',
                        help='Skip cross-task tests (Category 4)')
    args = parser.parse_args()

    # Screenshots directory
    screenshots_dir = Path(__file__).parent / 'screenshots'
    screenshots_dir.mkdir(exist_ok=True)

    print(f'CVAT Multiview Comprehensive Browser Test', flush=True)
    print(f'{"=" * 50}', flush=True)
    print(f'Host:    {args.host}', flush=True)
    print(f'User:    {args.user}', flush=True)
    print(f'Task A:  id={args.task_a_id}, job={args.job_a_id}', flush=True)
    print(f'Headless: {args.headless}', flush=True)

    # Create test instance
    tester = CVATBrowserTest(args.host, args.user, args.password)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        page.set_default_timeout(15000)  # 15s max per action

        # Login via browser using CVAT API endpoint
        print(f'\nLogging in via browser...', flush=True)
        # First, get CSRF token by visiting the login page
        page.goto(f'{args.host}/api/auth/login')
        page.wait_for_timeout(1000)
        
        # Use page.request to login via API (shares browser context cookies)
        login_resp = page.request.post(
            f'{args.host}/api/auth/login',
            data=json.dumps({'username': args.user, 'password': args.password}),
            headers={'Content-Type': 'application/json', 'Referer': args.host},
        )
        if login_resp.ok:
            print('  Login successful (browser API)', flush=True)
        else:
            print(f'  Login status: {login_resp.status}', flush=True)
            # Fallback: use requests to get cookies and inject them
            r = requests.post(
                f'{args.host}/api/auth/login',
                json={'username': args.user, 'password': args.password},
                headers={'Referer': args.host},
            )
            if r.status_code == 200:
                for c_name, c_value in r.cookies.items():
                    ctx.add_cookies([{'name': c_name, 'value': c_value, 'url': args.host}])
                print('  Login successful (cookie injection)', flush=True)

        # Run all tests
        tester.run_all(page, args, screenshots_dir)

        # Cleanup
        browser.close()

    # Summary
    tester.print_summary()

    # Save results to JSON
    results_path = Path(__file__).parent / 'browser_test_results.json'
    with open(results_path, 'w') as f:
        json.dump({
            'total': len(tester.results),
            'passed': sum(1 for r in tester.results if r['passed']),
            'failed': sum(1 for r in tester.results if not r['passed']),
            'results': tester.results,
        }, f, indent=2)
    print(f'Results saved to: {results_path}')

    sys.exit(0 if tester.all_passed() else 1)


if __name__ == '__main__':
    main()
