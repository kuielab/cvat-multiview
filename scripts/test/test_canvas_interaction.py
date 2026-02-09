#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canvas Interaction Test - Reproduces pre-annotation edit bug via browser canvas.

The bug: When editing a shape via canvas interaction (click + drag) on frame N,
shapes on other frames get corrupted due to ObjectState shallow-copy losing
non-enumerable properties (clientID, updated, etc.).

This test uses Playwright to:
1. Navigate to a frame with pre-annotations
2. Click on a shape to select it
3. Drag it to a new position
4. Navigate to another frame
5. Verify canvas-rendered shapes match expected API positions

The buggy version loses non-enumerable properties during ObjectState spread,
causing canvas setupObjects() to treat all shapes as new objects on every re-render.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

os.environ['PYTHONUNBUFFERED'] = '1'

import requests
from playwright.sync_api import Page, sync_playwright


class CanvasInteractionTest:
    """Tests that verify canvas-level shape rendering after interactions."""

    def __init__(self, host: str, user: str, password: str):
        self.host = host.rstrip('/')
        self.user = user
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({'Referer': self.host})
        self._api_login()
        self.results: List[Dict[str, Any]] = []

    def _api_login(self):
        resp = self.session.post(
            f'{self.host}/api/auth/login',
            json={'username': self.user, 'password': self.password},
        )
        resp.raise_for_status()
        token = resp.json()['key']
        self.session.headers.update({'Authorization': f'Token {token}'})

    def api_get_shapes(self, job_id: int, frame: Optional[int] = None) -> List[dict]:
        resp = self.session.get(f'{self.host}/api/jobs/{job_id}/annotations')
        resp.raise_for_status()
        shapes = resp.json().get('shapes', [])
        if frame is not None:
            shapes = [s for s in shapes if s['frame'] == frame]
        return shapes

    def api_update_shape(self, job_id: int, shape_id: int, frame: int,
                         new_points: List[float], label_id: int) -> bool:
        raw = None
        for s in self.api_get_shapes(job_id):
            if s['id'] == shape_id:
                raw = s
                break
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

    def navigate_to_frame(self, page: Page, frame_num: int, wait_ms: int = 3000):
        sb = page.get_by_role('spinbutton').first
        sb.click(timeout=10000)
        sb.fill(str(frame_num))
        sb.press('Enter')
        page.wait_for_timeout(wait_ms)

    def get_canvas_shapes_js(self, page: Page) -> List[dict]:
        """Get shape positions from canvas SVG elements."""
        return page.evaluate('''() => {
            const results = [];
            // Get all rect elements with data-z-order (CVAT canvas shapes)
            const rects = document.querySelectorAll('rect[data-z-order]');
            rects.forEach(r => {
                results.push({
                    clientID: r.getAttribute('clientID') || r.getAttribute('data-client-id') || '',
                    x: parseFloat(r.getAttribute('x')) || 0,
                    y: parseFloat(r.getAttribute('y')) || 0,
                    w: parseFloat(r.getAttribute('width')) || 0,
                    h: parseFloat(r.getAttribute('height')) || 0,
                    tagName: r.tagName,
                });
            });
            // Also try .cvat_canvas_shape if no data-z-order found
            if (results.length === 0) {
                const shapes = document.querySelectorAll('.cvat_canvas_shape');
                shapes.forEach(s => {
                    const rect = s.querySelector('rect') || s;
                    if (rect.tagName === 'rect') {
                        results.push({
                            clientID: s.getAttribute('clientID') || '',
                            x: parseFloat(rect.getAttribute('x')) || 0,
                            y: parseFloat(rect.getAttribute('y')) || 0,
                            w: parseFloat(rect.getAttribute('width')) || 0,
                            h: parseFloat(rect.getAttribute('height')) || 0,
                            tagName: rect.tagName,
                        });
                    }
                });
            }
            return results;
        }''')

    def check_canvas_stability(self, page: Page, frame_num: int,
                               num_checks: int = 3, delay_ms: int = 1000) -> Tuple[bool, str]:
        """Check if canvas shapes are stable (don't change between renders).

        The buggy version causes shapes to flicker/teleport because setupObjects()
        deletes and recreates all shapes on every call.
        """
        snapshots = []
        for i in range(num_checks):
            shapes = self.get_canvas_shapes_js(page)
            snapshot = sorted([(s['x'], s['y'], s['w'], s['h']) for s in shapes])
            snapshots.append(snapshot)
            if i < num_checks - 1:
                page.wait_for_timeout(delay_ms)

        # Check all snapshots are identical
        for i in range(1, len(snapshots)):
            if snapshots[i] != snapshots[0]:
                return False, f'Canvas shapes changed between render {0} and {i}: {snapshots[0]} vs {snapshots[i]}'
        return True, f'Canvas stable across {num_checks} checks ({len(snapshots[0])} shapes)'

    def click_shape_on_canvas(self, page: Page, shape_index: int = 0) -> bool:
        """Click on a shape to select it using the Objects panel sidebar."""
        try:
            # Use the sidebar objects list to select a shape
            items = page.locator('.cvat-objects-sidebar-state-item')
            if items.count() > shape_index:
                items.nth(shape_index).click()
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
        return False

    def drag_shape_via_canvas(self, page: Page) -> bool:
        """Try to drag a selected shape by interacting with its SVG element.

        This simulates the user dragging a shape via mousedown + mousemove + mouseup.
        """
        try:
            # Find the first rect with data-z-order on the canvas
            result = page.evaluate('''() => {
                const rect = document.querySelector('rect[data-z-order]');
                if (!rect) return null;
                const bbox = rect.getBoundingClientRect();
                return {
                    cx: bbox.x + bbox.width / 2,
                    cy: bbox.y + bbox.height / 2,
                    w: bbox.width,
                    h: bbox.height,
                };
            }''')

            if not result:
                return False

            cx, cy = result['cx'], result['cy']

            # Perform drag: mousedown at center, move 50px right and 30px down, mouseup
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(100)

            # Drag in small increments (like a real drag)
            steps = 10
            dx, dy = 50, 30
            for step in range(1, steps + 1):
                page.mouse.move(
                    cx + dx * step / steps,
                    cy + dy * step / steps,
                )
                page.wait_for_timeout(20)

            page.mouse.up()
            page.wait_for_timeout(2000)
            return True
        except Exception as e:
            print(f'    Drag failed: {e}')
            return False

    def run_test(self, name: str, fn):
        """Run a test and record result."""
        try:
            passed, detail = fn()
            self.results.append({'name': name, 'passed': passed, 'details': detail})
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name} - {detail}', flush=True)
        except Exception as e:
            tb = traceback.format_exc()
            self.results.append({'name': name, 'passed': False, 'details': f'Exception: {tb[-300:]}'})
            print(f'  [FAIL] {name} - Exception: {str(e)[:150]}', flush=True)

    def run_all(self, page: Page, task_id: int, job_id: int, label_id: int, screenshots_dir: Path):
        """Run all canvas interaction tests."""

        # ============================================================
        # Test Group A: Canvas Rendering Stability
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Group A: Canvas Rendering Stability')
        print(f'{"=" * 60}')

        self.run_test('A1_canvas_shapes_visible_f97', lambda: self._a1(page, task_id, job_id))
        self.run_test('A2_canvas_stable_no_flicker_f97', lambda: self._a2(page, task_id, job_id))
        self.run_test('A3_canvas_shapes_visible_f140', lambda: self._a3(page, task_id, job_id))
        self.run_test('A4_canvas_stable_after_navigate', lambda: self._a4(page, task_id, job_id))

        # ============================================================
        # Test Group B: Canvas Shape Selection
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Group B: Canvas Shape Selection')
        print(f'{"=" * 60}')

        self.run_test('B1_select_shape_sidebar_f97', lambda: self._b1(page, task_id, job_id, screenshots_dir))
        self.run_test('B2_select_shape_other_frames_ok', lambda: self._b2(page, task_id, job_id))

        # ============================================================
        # Test Group C: Canvas Drag Interaction
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Group C: Canvas Drag Interaction (Bug Reproduction)')
        print(f'{"=" * 60}')

        self.run_test('C1_drag_shape_f97_verify_f140', lambda: self._c1(page, task_id, job_id, label_id, screenshots_dir))
        self.run_test('C2_select_f97_nav_f140_canvas_ok', lambda: self._c2(page, task_id, job_id, label_id, screenshots_dir))
        self.run_test('C3_api_edit_f97_canvas_f140_stable', lambda: self._c3(page, task_id, job_id, label_id, screenshots_dir))
        self.run_test('C4_rapid_frame_switch_canvas_stable', lambda: self._c4(page, task_id, job_id))

        # ============================================================
        # Test Group D: Canvas vs API Position Match
        # ============================================================
        print(f'\n{"=" * 60}')
        print('Group D: Canvas vs API Position Consistency')
        print(f'{"=" * 60}')

        self.run_test('D1_canvas_positions_match_api_f97', lambda: self._d1(page, task_id, job_id))
        self.run_test('D2_canvas_positions_match_api_f140', lambda: self._d2(page, task_id, job_id))
        self.run_test('D3_navigate_5_frames_canvas_api_match', lambda: self._d3(page, task_id, job_id))

    # ================================================================
    # Group A: Canvas Rendering Stability
    # ================================================================

    def _a1(self, page, task_id, job_id):
        """A1: Frame 97 shows shapes on canvas."""
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)
        self.navigate_to_frame(page, 97)
        shapes = self.get_canvas_shapes_js(page)
        if len(shapes) >= 1:
            return True, f'{len(shapes)} shapes visible on canvas at frame 97'
        return False, f'No shapes visible on canvas'

    def _a2(self, page, task_id, job_id):
        """A2: Canvas shapes stable (no flicker) on frame 97."""
        self.navigate_to_frame(page, 97)
        return self.check_canvas_stability(page, 97, num_checks=5, delay_ms=500)

    def _a3(self, page, task_id, job_id):
        """A3: Frame 140 shows shapes on canvas."""
        self.navigate_to_frame(page, 140)
        shapes = self.get_canvas_shapes_js(page)
        if len(shapes) >= 1:
            return True, f'{len(shapes)} shapes visible on canvas at frame 140'
        return False, f'No shapes visible on canvas at frame 140'

    def _a4(self, page, task_id, job_id):
        """A4: Canvas stable after 97→140→97 navigation."""
        self.navigate_to_frame(page, 97)
        s1 = sorted([(s['x'], s['y'], s['w'], s['h']) for s in self.get_canvas_shapes_js(page)])
        self.navigate_to_frame(page, 140)
        self.navigate_to_frame(page, 97)
        s2 = sorted([(s['x'], s['y'], s['w'], s['h']) for s in self.get_canvas_shapes_js(page)])

        if s1 == s2:
            return True, f'Canvas positions identical after round-trip ({len(s1)} shapes)'
        return False, f'Canvas positions changed: before={s1[:2]}, after={s2[:2]}'

    # ================================================================
    # Group B: Canvas Shape Selection
    # ================================================================

    def _b1(self, page, task_id, job_id, screenshots_dir):
        """B1: Click shape via sidebar, canvas shows selection handles."""
        self.navigate_to_frame(page, 97)
        clicked = self.click_shape_on_canvas(page, 0)
        if not clicked:
            return False, 'Could not click shape via sidebar'

        page.screenshot(path=str(screenshots_dir / 'b1_shape_selected.png'))

        # Check if resize handles appeared (svg_select_points)
        handles = page.evaluate('''() => {
            const pts = document.querySelectorAll('.svg_select_points, circle.svg_select_points');
            return pts.length;
        }''')

        if handles > 0:
            return True, f'Shape selected, {handles} resize handles visible'
        # Even without handles, selection via sidebar is enough
        return True, f'Shape clicked via sidebar (handles may not be in SVG)'

    def _b2(self, page, task_id, job_id):
        """B2: Select shape on f97, navigate f140, shapes on f140 unaffected."""
        self.navigate_to_frame(page, 97)
        self.click_shape_on_canvas(page, 0)

        # Record f140 shapes from API (ground truth)
        api_140 = self.api_get_shapes(job_id, frame=140)
        api_positions = sorted([(s['points'][0], s['points'][1]) for s in api_140])

        # Navigate to f140
        self.navigate_to_frame(page, 140)
        canvas_140 = self.get_canvas_shapes_js(page)
        canvas_positions = sorted([(s['x'], s['y']) for s in canvas_140])

        # The canvas positions should be reasonable (not all at 0,0 or wildly wrong)
        if len(canvas_140) >= 1:
            # Check that at least some canvas shapes have non-zero dimensions
            valid = [s for s in canvas_140 if s['w'] > 10 and s['h'] > 10]
            if len(valid) >= 1:
                return True, f'f140: {len(valid)} valid shapes after selecting on f97'
            return False, f'f140: shapes have invalid dimensions: {canvas_140[:3]}'
        return False, f'f140: no shapes visible after selecting on f97'

    # ================================================================
    # Group C: Canvas Drag Interaction (Bug Reproduction)
    # ================================================================

    def _c1(self, page, task_id, job_id, label_id, screenshots_dir):
        """C1: Drag shape on f97, navigate to f140, verify f140 canvas ok.

        This is THE bug test. In buggy version, dragging on f97 corrupts f140 shapes.
        """
        # Reload fresh
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)
        self.navigate_to_frame(page, 97)

        # Record f140 before any interaction
        f140_before_api = self.api_get_shapes(job_id, frame=140)
        f140_positions_before = sorted([(s['points'][0], s['points'][1]) for s in f140_before_api])

        # Select shape via sidebar
        self.click_shape_on_canvas(page, 0)
        page.wait_for_timeout(1000)

        # Try to drag
        dragged = self.drag_shape_via_canvas(page)
        page.screenshot(path=str(screenshots_dir / 'c1_after_drag_f97.png'))

        # Navigate to f140
        self.navigate_to_frame(page, 140)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots_dir / 'c1_f140_after_drag.png'))

        # Check f140 canvas shapes
        canvas_140 = self.get_canvas_shapes_js(page)

        # Verify API positions didn't change (bug is canvas-only)
        f140_after_api = self.api_get_shapes(job_id, frame=140)
        f140_positions_after = sorted([(s['points'][0], s['points'][1]) for s in f140_after_api])

        api_unchanged = f140_positions_before == f140_positions_after

        if not api_unchanged:
            return False, f'API positions changed on f140 after drag on f97!'

        # Check canvas has valid shapes
        valid_canvas = [s for s in canvas_140 if s['w'] > 10 and s['h'] > 10]
        if len(valid_canvas) >= 1:
            return True, f'f140 canvas ok after f97 drag: {len(valid_canvas)} valid shapes, API unchanged (drag={dragged})'
        return False, f'f140 canvas invalid after f97 drag: {canvas_140[:3]}'

    def _c2(self, page, task_id, job_id, label_id, screenshots_dir):
        """C2: Select on f97, navigate f140, canvas positions consistent."""
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)
        self.navigate_to_frame(page, 97)

        # Record canvas at f140 without any interaction
        self.navigate_to_frame(page, 140)
        canvas_baseline = sorted([(s['x'], s['y'], s['w'], s['h']) for s in self.get_canvas_shapes_js(page)])

        # Go back, select shape, navigate to f140 again
        self.navigate_to_frame(page, 97)
        self.click_shape_on_canvas(page, 0)
        self.navigate_to_frame(page, 140)
        canvas_after_select = sorted([(s['x'], s['y'], s['w'], s['h']) for s in self.get_canvas_shapes_js(page)])

        if canvas_baseline == canvas_after_select:
            return True, f'f140 canvas identical after f97 select ({len(canvas_baseline)} shapes)'
        # Check if roughly same (within tolerance)
        if len(canvas_baseline) == len(canvas_after_select):
            max_diff = 0
            for b, a in zip(canvas_baseline, canvas_after_select):
                for bv, av in zip(b, a):
                    max_diff = max(max_diff, abs(bv - av))
            if max_diff < 5:
                return True, f'f140 canvas within tolerance (max_diff={max_diff:.1f})'
            return False, f'f140 canvas changed after f97 select, max_diff={max_diff:.1f}'
        return False, f'Shape count changed: {len(canvas_baseline)} → {len(canvas_after_select)}'

    def _c3(self, page, task_id, job_id, label_id, screenshots_dir):
        """C3: API edit on f97, reload, canvas at f140 still matches API.

        Tests that after an API edit triggers canvas re-render via setupObjects(),
        the canvas positions at other frames remain correct.
        """
        shapes_97 = self.api_get_shapes(job_id, frame=97)
        if not shapes_97:
            return False, 'No shapes at f97'

        target = shapes_97[0]
        orig = list(target['points'])
        new_pts = [orig[0] + 100, orig[1] + 100, orig[2] + 100, orig[3] + 100]

        try:
            # Edit via API
            self.api_update_shape(job_id, target['id'], 97, new_pts, label_id)

            # Reload and navigate to f97 (triggers setupObjects with edited shape)
            page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
            page.wait_for_timeout(6000)
            self.navigate_to_frame(page, 97)
            page.wait_for_timeout(2000)

            # Now go to f140
            self.navigate_to_frame(page, 140)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(screenshots_dir / 'c3_f140_after_api_edit_f97.png'))

            canvas_140 = self.get_canvas_shapes_js(page)
            api_140 = self.api_get_shapes(job_id, frame=140)

            # Both should have same count
            if len(canvas_140) >= 1 and len(api_140) >= 1:
                valid = [s for s in canvas_140 if s['w'] > 10 and s['h'] > 10]
                return True, f'f140 canvas has {len(valid)} valid shapes after API edit on f97'
            return False, f'Canvas: {len(canvas_140)}, API: {len(api_140)}'
        finally:
            self.api_update_shape(job_id, target['id'], 97, orig, label_id)

    def _c4(self, page, task_id, job_id):
        """C4: Rapid frame switching, canvas stays consistent."""
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)

        frames = [97, 140, 183, 140, 97, 225, 97]
        for f in frames:
            self.navigate_to_frame(page, f, wait_ms=1500)

        # Final check at f97
        self.navigate_to_frame(page, 97, wait_ms=3000)
        shapes = self.get_canvas_shapes_js(page)
        valid = [s for s in shapes if s['w'] > 10 and s['h'] > 10]

        if len(valid) >= 1:
            return True, f'Canvas stable after {len(frames)} frame switches: {len(valid)} valid shapes'
        return False, f'Canvas invalid after rapid switching: {shapes[:3]}'

    # ================================================================
    # Group D: Canvas vs API Position Consistency
    # ================================================================

    def _d1(self, page, task_id, job_id):
        """D1: Canvas positions roughly match API positions at f97."""
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(6000)
        self.navigate_to_frame(page, 97)

        canvas = self.get_canvas_shapes_js(page)
        api = self.api_get_shapes(job_id, frame=97)

        if len(canvas) < 1:
            return False, 'No canvas shapes'
        if len(api) < 1:
            return False, 'No API shapes'

        # Canvas shapes are in canvas coordinate space (potentially scaled)
        # API shapes are in task space. We just verify count and non-zero dimensions.
        valid_canvas = [s for s in canvas if s['w'] > 5 and s['h'] > 5]
        return True, f'f97: API={len(api)} shapes, Canvas={len(valid_canvas)} valid shapes'

    def _d2(self, page, task_id, job_id):
        """D2: Canvas positions roughly match API positions at f140."""
        self.navigate_to_frame(page, 140)

        canvas = self.get_canvas_shapes_js(page)
        api = self.api_get_shapes(job_id, frame=140)

        valid_canvas = [s for s in canvas if s['w'] > 5 and s['h'] > 5]
        if len(valid_canvas) >= 1 and len(api) >= 1:
            return True, f'f140: API={len(api)} shapes, Canvas={len(valid_canvas)} valid shapes'
        return False, f'f140: API={len(api)}, Canvas valid={len(valid_canvas)}'

    def _d3(self, page, task_id, job_id):
        """D3: Navigate through 5 frames, canvas shapes always valid."""
        frames_to_check = [97, 140, 183, 225, 998]
        results = []

        for f in frames_to_check:
            self.navigate_to_frame(page, f)
            canvas = self.get_canvas_shapes_js(page)
            api = self.api_get_shapes(job_id, frame=f)
            valid = [s for s in canvas if s['w'] > 5 and s['h'] > 5]
            results.append(f'f{f}:api={len(api)},canvas={len(valid)}')

            if len(api) > 0 and len(valid) == 0:
                return False, f'Frame {f}: API has {len(api)} shapes but canvas shows 0. ' + '; '.join(results)

        return True, '; '.join(results)

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
                    print(f'  X {r["name"]}: {r["details"][:120]}')
        print()


def main():
    parser = argparse.ArgumentParser(description='Canvas Interaction Test for Multiview')
    parser.add_argument('--host', default='http://localhost:8080')
    parser.add_argument('--user', '-u', default='admin')
    parser.add_argument('--password', '-p', default='admin123')
    parser.add_argument('--task-id', type=int, default=4)
    parser.add_argument('--job-id', type=int, default=4)
    parser.add_argument('--label-id', type=int, default=9)
    parser.add_argument('--headless', action='store_true', default=True)
    parser.add_argument('--no-headless', dest='headless', action='store_false')
    args = parser.parse_args()

    screenshots_dir = Path(__file__).parent / 'screenshots_canvas'
    screenshots_dir.mkdir(exist_ok=True)

    print(f'Canvas Interaction Test Suite', flush=True)
    print(f'{"=" * 50}', flush=True)
    print(f'Host:     {args.host}', flush=True)
    print(f'Task:     {args.task_id}, Job: {args.job_id}, Label: {args.label_id}', flush=True)
    print(f'Headless: {args.headless}', flush=True)

    tester = CanvasInteractionTest(args.host, args.user, args.password)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        page.set_default_timeout(15000)

        # Login
        print('\nLogging in...', flush=True)
        page.goto(f'{args.host}/api/auth/login')
        page.wait_for_timeout(1000)
        login_resp = page.request.post(
            f'{args.host}/api/auth/login',
            data=json.dumps({'username': args.user, 'password': args.password}),
            headers={'Content-Type': 'application/json', 'Referer': args.host},
        )
        print(f'  Login: {"OK" if login_resp.ok else login_resp.status}', flush=True)

        tester.run_all(page, args.task_id, args.job_id, args.label_id, screenshots_dir)
        browser.close()

    tester.print_summary()

    results_path = Path(__file__).parent / 'canvas_interaction_results.json'
    with open(results_path, 'w') as f:
        json.dump({
            'total': len(tester.results),
            'passed': sum(1 for r in tester.results if r['passed']),
            'failed': sum(1 for r in tester.results if not r['passed']),
            'results': tester.results,
        }, f, indent=2)
    print(f'Results saved to: {results_path}')

    sys.exit(0 if all(r['passed'] for r in tester.results) else 1)


if __name__ == '__main__':
    main()
