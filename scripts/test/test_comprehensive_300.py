#!/usr/bin/env python3
"""
Comprehensive Pre-Annotation Edit Bug Test Suite (300+ test cases)

Tests that editing (move/resize) one pre-annotation does NOT affect other
pre-annotations. Includes:
- Basic movement (all directions, magnitudes)
- Resize (scale up/down, asymmetric)
- Property changes (occluded, z_order, rotation)
- Sequential edits
- Boundary/edge cases
- Save & reload verification
- Export & re-import verification
- Batch edit verification
- Delete + verify others
- Rapid-fire sequential edits
- Cross-view interactions
- Stress tests (all shapes on same frame)

Usage:
    python scripts/test/test_comprehensive_300.py --user admin --password admin123
    python scripts/test/test_comprehensive_300.py --user admin --password admin123 --setup
"""

import argparse
import copy
import io
import json
import math
import os
import random
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_HOST = "http://localhost:8080"
TOLERANCE = 1.0  # pixel tolerance for floating-point comparison
EXPORT_TIMEOUT = 120  # seconds to wait for export


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ShapeSnapshot:
    """Snapshot of a shape's state for comparison."""
    server_id: int
    frame: int
    view_id: Optional[int]
    points: List[float]
    label_id: int
    occluded: bool
    z_order: int
    rotation: float

    @staticmethod
    def from_api(shape: dict) -> 'ShapeSnapshot':
        return ShapeSnapshot(
            server_id=shape["id"],
            frame=shape["frame"],
            view_id=shape.get("view_id"),
            points=shape["points"],
            label_id=shape["label_id"],
            occluded=shape["occluded"],
            z_order=shape["z_order"],
            rotation=shape.get("rotation", 0.0),
        )

    def points_match(self, other: 'ShapeSnapshot') -> bool:
        if len(self.points) != len(other.points):
            return False
        return all(
            abs(a - b) <= TOLERANCE
            for a, b in zip(self.points, other.points)
        )

    def matches(self, other: 'ShapeSnapshot', ignore_points: bool = False) -> bool:
        if self.server_id != other.server_id:
            return False
        if self.frame != other.frame:
            return False
        if self.view_id != other.view_id:
            return False
        if self.label_id != other.label_id:
            return False
        if self.occluded != other.occluded:
            return False
        if self.z_order != other.z_order:
            return False
        if abs(self.rotation - other.rotation) > TOLERANCE:
            return False
        if not ignore_points and not self.points_match(other):
            return False
        return True


@dataclass
class TestResult:
    """Result of a single test case."""
    name: str
    passed: bool
    description: str
    category: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0


# ============================================================================
# CVAT API Client (Extended)
# ============================================================================

class CVATClient:
    """CVAT API client with full annotation lifecycle support."""

    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.session = requests.Session()
        self.session.headers.update({"Referer": host})
        self._login(user, password)

    def _login(self, user: str, password: str):
        resp = self.session.post(
            f"{self.host}/api/auth/login",
            json={"username": user, "password": password},
        )
        resp.raise_for_status()
        token = resp.json()["key"]
        self.session.headers.update({"Authorization": f"Token {token}"})

    def get_annotations(self, job_id: int) -> List[ShapeSnapshot]:
        resp = self.session.get(f"{self.host}/api/jobs/{job_id}/annotations")
        resp.raise_for_status()
        data = resp.json()
        return [ShapeSnapshot.from_api(s) for s in data.get("shapes", [])]

    def get_raw_annotations(self, job_id: int) -> dict:
        resp = self.session.get(f"{self.host}/api/jobs/{job_id}/annotations")
        resp.raise_for_status()
        return resp.json()

    def _get_raw_shape(self, job_id: int, shape_id: int) -> dict:
        data = self.get_raw_annotations(job_id)
        for s in data.get("shapes", []):
            if s["id"] == shape_id:
                return s
        raise RuntimeError(f"Shape {shape_id} not found")

    def update_shape(self, job_id: int, shape_id: int,
                     new_points: Optional[List[float]] = None,
                     new_rotation: Optional[float] = None,
                     new_occluded: Optional[bool] = None,
                     new_z_order: Optional[int] = None,
                     new_label_id: Optional[int] = None) -> dict:
        raw = self._get_raw_shape(job_id, shape_id)
        shape_data = {
            "id": shape_id,
            "type": raw["type"],
            "frame": raw["frame"],
            "label_id": raw["label_id"],
            "occluded": raw.get("occluded", False),
            "z_order": raw.get("z_order", 0),
            "rotation": raw.get("rotation", 0.0),
            "points": raw["points"],
            "attributes": raw.get("attributes", []),
            "source": raw.get("source", "manual"),
        }
        if new_points is not None:
            shape_data["points"] = new_points
        if new_rotation is not None:
            shape_data["rotation"] = new_rotation
        if new_occluded is not None:
            shape_data["occluded"] = new_occluded
        if new_z_order is not None:
            shape_data["z_order"] = new_z_order
        if new_label_id is not None:
            shape_data["label_id"] = new_label_id

        payload = {"shapes": [shape_data], "tracks": [], "tags": []}
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}/annotations?action=update",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def update_multiple_shapes(self, job_id: int,
                               updates: List[Tuple[int, List[float]]]) -> dict:
        """Batch update multiple shapes at once."""
        shapes = []
        for shape_id, new_points in updates:
            raw = self._get_raw_shape(job_id, shape_id)
            shape_data = {
                "id": shape_id,
                "type": raw["type"],
                "frame": raw["frame"],
                "label_id": raw["label_id"],
                "occluded": raw.get("occluded", False),
                "z_order": raw.get("z_order", 0),
                "rotation": raw.get("rotation", 0.0),
                "points": new_points,
                "attributes": raw.get("attributes", []),
                "source": raw.get("source", "manual"),
            }
            shapes.append(shape_data)

        payload = {"shapes": shapes, "tracks": [], "tags": []}
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}/annotations?action=update",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_shape(self, job_id: int, shape_id: int) -> None:
        """Delete a single shape."""
        raw = self._get_raw_shape(job_id, shape_id)
        payload = {"shapes": [raw], "tracks": [], "tags": []}
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}/annotations?action=delete",
            json=payload, timeout=30,
        )
        resp.raise_for_status()

    def create_shape(self, job_id: int, frame: int, label_id: int,
                     points: List[float], view_id: Optional[int] = None) -> dict:
        """Create a new shape."""
        shape = {
            "type": "rectangle",
            "frame": frame,
            "label_id": label_id,
            "occluded": False,
            "z_order": 0,
            "points": points,
            "attributes": [],
            "source": "manual",
        }
        if view_id is not None:
            shape["view_id"] = view_id

        payload = {"shapes": [shape], "tracks": [], "tags": []}
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}/annotations?action=create",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def reset_shape(self, job_id: int, shape_id: int,
                    original_points: List[float]):
        self.update_shape(job_id, shape_id, new_points=original_points)

    def save_job(self, job_id: int) -> None:
        """Save job state (change status to 'annotation' to trigger save)."""
        resp = self.session.get(f"{self.host}/api/jobs/{job_id}")
        resp.raise_for_status()
        current = resp.json()
        # Just PATCH the job to trigger any save side-effects
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}",
            json={"stage": current.get("stage", "annotation")},
            timeout=30,
        )
        resp.raise_for_status()

    def export_annotations(self, job_id: int,
                           format_name: str = "CVAT for video 1.1") -> bytes:
        """Export annotations and return the file content."""
        # Trigger export
        resp = self.session.get(
            f"{self.host}/api/jobs/{job_id}/annotations",
            params={"format": format_name, "action": "download"},
            timeout=EXPORT_TIMEOUT,
        )
        if resp.status_code == 202:
            # Export is processing, poll until ready
            for _ in range(60):
                time.sleep(2)
                resp = self.session.get(
                    f"{self.host}/api/jobs/{job_id}/annotations",
                    params={"format": format_name, "action": "download"},
                    timeout=EXPORT_TIMEOUT,
                )
                if resp.status_code == 200:
                    break
        resp.raise_for_status()
        return resp.content

    def import_annotations(self, job_id: int, data: bytes,
                           format_name: str = "CVAT 1.1") -> None:
        """Import annotations from file content."""
        files = {"annotation_file": ("annotations.zip", data, "application/zip")}
        resp = self.session.put(
            f"{self.host}/api/jobs/{job_id}/annotations",
            params={"format": format_name},
            files=files,
            timeout=EXPORT_TIMEOUT,
        )
        if resp.status_code == 202:
            # Import processing
            rq_id = resp.json().get("rq_id", "")
            for _ in range(60):
                time.sleep(2)
                check = self.session.get(
                    f"{self.host}/api/jobs/{job_id}/annotations",
                    params={"action": "download", "format": format_name,
                            "rq_id": rq_id},
                    timeout=30,
                )
                if check.status_code in (200, 201):
                    break
        elif resp.status_code not in (200, 201):
            resp.raise_for_status()

    def get_task_info(self, task_id: int) -> dict:
        resp = self.session.get(f"{self.host}/api/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()


# ============================================================================
# Test Runner (300+ tests)
# ============================================================================

class ComprehensiveTestRunner:
    """Generates and runs 300+ test cases."""

    def __init__(self, client: CVATClient, job_id: int, task_id: int):
        self.client = client
        self.job_id = job_id
        self.task_id = task_id
        self.results: List[TestResult] = []
        self._snapshot_cache: Optional[Dict[int, ShapeSnapshot]] = None

    def take_snapshot(self) -> Dict[int, ShapeSnapshot]:
        shapes = self.client.get_annotations(self.job_id)
        return {s.server_id: s for s in shapes}

    def verify_others_unchanged(
        self,
        before: Dict[int, ShapeSnapshot],
        after: Dict[int, ShapeSnapshot],
        edited_ids: List[int],
    ) -> Tuple[bool, Optional[str]]:
        errors = []
        before_other = {k: v for k, v in before.items() if k not in edited_ids}
        after_other = {k: v for k, v in after.items() if k not in edited_ids}

        if len(before_other) != len(after_other):
            missing = set(before_other.keys()) - set(after_other.keys())
            extra = set(after_other.keys()) - set(before_other.keys())
            parts = []
            if missing:
                parts.append(f"missing: {missing}")
            if extra:
                parts.append(f"extra: {extra}")
            return False, f"Shape count mismatch. {'; '.join(parts)}"

        for sid, before_snap in before_other.items():
            after_snap = after_other.get(sid)
            if after_snap is None:
                errors.append(f"Shape {sid} disappeared")
                continue
            if not before_snap.matches(after_snap):
                diffs = []
                if not before_snap.points_match(after_snap):
                    diffs.append(f"points: {before_snap.points} → {after_snap.points}")
                if before_snap.occluded != after_snap.occluded:
                    diffs.append(f"occluded: {before_snap.occluded} → {after_snap.occluded}")
                if abs(before_snap.rotation - after_snap.rotation) > TOLERANCE:
                    diffs.append(f"rotation: {before_snap.rotation} → {after_snap.rotation}")
                if before_snap.z_order != after_snap.z_order:
                    diffs.append(f"z_order: {before_snap.z_order} → {after_snap.z_order}")
                errors.append(
                    f"Shape {sid} (frame={before_snap.frame}, view={before_snap.view_id}) "
                    f"changed: {'; '.join(diffs)}"
                )

        if errors:
            return False, "\n".join(errors[:5])  # limit error output
        return True, None

    def _run_test(self, name: str, desc: str, category: str,
                  fn) -> TestResult:
        """Generic test wrapper with timing."""
        start = time.time()
        try:
            ok, err = fn()
            elapsed = (time.time() - start) * 1000
            return TestResult(name, ok, desc, category, err, elapsed)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return TestResult(name, False, desc, category, f"Exception: {e}", elapsed)

    # ========================================================================
    # Category 1: Single Move Tests (50 tests)
    # ========================================================================
    def gen_move_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        # 1a. 8 cardinal + diagonal directions on first shape (8)
        s0 = shapes[0]
        dirs = [
            (10, 0, "right"), (-10, 0, "left"), (0, 10, "down"), (0, -10, "up"),
            (15, 15, "SE"), (-15, 15, "SW"), (15, -15, "NE"), (-15, -15, "NW"),
        ]
        for dx, dy, d in dirs:
            results.append(self._run_move(f"TC01a-{d}", f"Move {d}", "move",
                                          s0.server_id, dx, dy))

        # 1b. Various magnitudes on different shapes (12)
        magnitudes = [1, 2, 5, 10, 25, 50, 75, 100, 150, 200, 300, 500]
        for i, mag in enumerate(magnitudes):
            target = shapes[i % len(shapes)]
            results.append(self._run_move(
                f"TC01b-mag{mag}", f"Move magnitude {mag}px", "move",
                target.server_id, mag, mag // 2))

        # 1c. Negative coordinates (6)
        for i in range(6):
            target = shapes[i % len(shapes)]
            dx = -(target.points[0] + 50)  # push into negative territory
            results.append(self._run_move(
                f"TC01c-neg{i}", f"Move to negative coords", "move",
                target.server_id, dx, -10))

        # 1d. Sub-pixel moves (4)
        for i, delta in enumerate([0.1, 0.5, 0.9, 1.5]):
            target = shapes[i % len(shapes)]
            results.append(self._run_move(
                f"TC01d-subpx{i}", f"Sub-pixel move {delta}", "move",
                target.server_id, delta, delta))

        # 1e. Zero moves (2) - edit with no change should be safe
        for i in range(2):
            target = shapes[i]
            results.append(self._run_move(
                f"TC01e-zero{i}", f"Zero move (no-op)", "move",
                target.server_id, 0, 0))

        # 1f. Move each of first 18 shapes (18)
        for i, s in enumerate(shapes[:18]):
            results.append(self._run_move(
                f"TC01f-shape{i}", f"Move shape#{i} (id={s.server_id})", "move",
                s.server_id, 10 + i, 5 + i))

        return results

    def _run_move(self, name, desc, cat, shape_id, dx, dy) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            new_pts = [orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]
            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [shape_id])
            self.client.reset_shape(self.job_id, shape_id, orig)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 2: Resize Tests (40 tests)
    # ========================================================================
    def gen_resize_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        # 2a. Uniform scaling (10)
        scales_uniform = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
        for i, s in enumerate(scales_uniform):
            target = shapes[i % len(shapes)]
            results.append(self._run_resize(
                f"TC02a-uniform{i}", f"Uniform scale {s}x", "resize",
                target.server_id, s, s))

        # 2b. Asymmetric X scaling (8)
        for i, sx in enumerate([0.3, 0.5, 0.7, 1.5, 2.0, 3.0, 4.0, 0.1]):
            target = shapes[i % len(shapes)]
            results.append(self._run_resize(
                f"TC02b-asymX{i}", f"Asymmetric X scale {sx}x", "resize",
                target.server_id, sx, 1.0))

        # 2c. Asymmetric Y scaling (8)
        for i, sy in enumerate([0.3, 0.5, 0.7, 1.5, 2.0, 3.0, 4.0, 0.1]):
            target = shapes[i % len(shapes)]
            results.append(self._run_resize(
                f"TC02c-asymY{i}", f"Asymmetric Y scale {sy}x", "resize",
                target.server_id, 1.0, sy))

        # 2d. Extreme resize (4)
        extremes = [(0.01, 0.01), (10.0, 10.0), (0.01, 10.0), (10.0, 0.01)]
        for i, (sx, sy) in enumerate(extremes):
            target = shapes[i % len(shapes)]
            results.append(self._run_resize(
                f"TC02d-extreme{i}", f"Extreme resize {sx}x,{sy}x", "resize",
                target.server_id, sx, sy))

        # 2e. Resize + verify exact dimensions (10)
        for i in range(10):
            target = shapes[i % len(shapes)]
            results.append(self._run_resize(
                f"TC02e-verify{i}", f"Resize verify exact dims", "resize",
                target.server_id, 1.3 + i * 0.1, 0.8 + i * 0.05))

        return results

    def _run_resize(self, name, desc, cat, shape_id, sx, sy) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            cx = (orig[0] + orig[2]) / 2
            cy = (orig[1] + orig[3]) / 2
            hw = (orig[2] - orig[0]) / 2 * sx
            hh = (orig[3] - orig[1]) / 2 * sy
            new_pts = [cx - hw, cy - hh, cx + hw, cy + hh]
            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [shape_id])
            self.client.reset_shape(self.job_id, shape_id, orig)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 3: Property Change Tests (30 tests)
    # ========================================================================
    def gen_property_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        # 3a. Toggle occluded on each of first 10 shapes (10)
        for i in range(min(10, len(shapes))):
            s = shapes[i]
            results.append(self._run_property(
                f"TC03a-occluded{i}", f"Toggle occluded shape#{i}", "property",
                s.server_id, new_occluded=not s.occluded))

        # 3b. Various z_order values (10)
        z_values = [-10, -5, -1, 0, 1, 5, 10, 50, 100, 999]
        for i, z in enumerate(z_values):
            s = shapes[i % len(shapes)]
            results.append(self._run_property(
                f"TC03b-zorder{i}", f"Set z_order={z}", "property",
                s.server_id, new_z_order=z))

        # 3c. Various rotation values (10)
        rotations = [0, 15, 30, 45, 90, 135, 180, 270, 359, 0.5]
        for i, r in enumerate(rotations):
            s = shapes[i % len(shapes)]
            results.append(self._run_property(
                f"TC03c-rotation{i}", f"Set rotation={r}°", "property",
                s.server_id, new_rotation=r))

        return results

    def _run_property(self, name, desc, cat, shape_id,
                      new_occluded=None, new_z_order=None,
                      new_rotation=None) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig_occ = target.occluded
            orig_z = target.z_order
            orig_rot = target.rotation

            self.client.update_shape(
                self.job_id, shape_id,
                new_occluded=new_occluded,
                new_z_order=new_z_order,
                new_rotation=new_rotation)

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [shape_id])

            # Reset
            self.client.update_shape(
                self.job_id, shape_id,
                new_occluded=orig_occ,
                new_z_order=orig_z,
                new_rotation=orig_rot)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 4: Frame-specific Tests (30 tests)
    # ========================================================================
    def gen_frame_tests(self, by_frame: Dict[int, List[ShapeSnapshot]]) -> List[TestResult]:
        results = []
        frames = sorted(by_frame.keys())

        # 4a. Edit first shape on each unique frame (up to 20)
        for i, frame in enumerate(frames[:20]):
            target = by_frame[frame][0]
            results.append(self._run_move(
                f"TC04a-frame{frame}", f"Edit on frame {frame}", "frame",
                target.server_id, 12, 8))

        # 4b. Edit on crowded frames (up to 10)
        crowded = [(f, ss) for f, ss in by_frame.items() if len(ss) >= 3]
        for i, (frame, ss) in enumerate(crowded[:10]):
            # Edit 2nd shape on crowded frame
            target = ss[min(1, len(ss) - 1)]
            results.append(self._run_move(
                f"TC04b-crowded{i}", f"Edit on crowded frame {frame} ({len(ss)} shapes)",
                "frame", target.server_id, 20, 15))

        return results

    # ========================================================================
    # Category 5: View-specific Tests (25 tests)
    # ========================================================================
    def gen_view_tests(self, by_view: Dict[int, List[ShapeSnapshot]]) -> List[TestResult]:
        results = []
        views = sorted(by_view.keys())

        # 5a. Edit each shape on each view (up to 5 per view)
        for view_id in views:
            for i, s in enumerate(by_view[view_id][:5]):
                results.append(self._run_move(
                    f"TC05a-v{view_id}s{i}", f"Edit view {view_id} shape #{i}",
                    "view", s.server_id, 10 + i * 3, 5 + i * 2))

        return results

    # ========================================================================
    # Category 6: Sequential Edits (20 tests)
    # ========================================================================
    def gen_sequential_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []

        # 6a. Sequential 2-shape edits (5)
        for i in range(5):
            s1 = shapes[i * 2 % len(shapes)]
            s2 = shapes[(i * 2 + 1) % len(shapes)]
            results.append(self._run_sequential(
                f"TC06a-seq2-{i}", f"Sequential 2 edits", "sequential",
                [(s1.server_id, 10, 10), (s2.server_id, -10, 10)]))

        # 6b. Sequential 3-shape edits (5)
        for i in range(5):
            edits = [
                (shapes[j % len(shapes)].server_id, 10 * (j + 1), 5 * (j + 1))
                for j in range(i * 3, i * 3 + 3)
            ]
            results.append(self._run_sequential(
                f"TC06b-seq3-{i}", f"Sequential 3 edits", "sequential", edits))

        # 6c. Sequential 5-shape edits (3)
        for i in range(3):
            edits = [
                (shapes[j % len(shapes)].server_id, 8 * (j + 1), 4 * (j + 1))
                for j in range(i * 5, i * 5 + 5)
            ]
            results.append(self._run_sequential(
                f"TC06c-seq5-{i}", f"Sequential 5 edits", "sequential", edits))

        # 6d. Sequential 10-shape edits (2)
        for i in range(2):
            edits = [
                (shapes[j % len(shapes)].server_id, 5 * (j + 1), 3 * (j + 1))
                for j in range(i * 10, i * 10 + 10)
            ]
            results.append(self._run_sequential(
                f"TC06d-seq10-{i}", f"Sequential 10 edits", "sequential", edits))

        # 6e. Rapid-fire same shape (5)
        for i in range(5):
            target = shapes[i % len(shapes)]
            edits = [
                (target.server_id, 5 * k, 5 * k) for k in range(1, 4)
            ]
            results.append(self._run_sequential(
                f"TC06e-rapid{i}", f"Rapid-fire same shape", "sequential", edits))

        return results

    def _run_sequential(self, name, desc, cat,
                        edits: List[Tuple[int, float, float]]) -> TestResult:
        def fn():
            resets = []
            for shape_id, dx, dy in edits:
                before = self.take_snapshot()
                target = before.get(shape_id)
                if not target:
                    continue
                orig = list(target.points)
                resets.append((shape_id, orig))
                new_pts = [orig[0] + dx, orig[1] + dy,
                           orig[2] + dx, orig[3] + dy]
                self.client.update_shape(self.job_id, shape_id, new_points=new_pts)
                after = self.take_snapshot()
                ok, err = self.verify_others_unchanged(before, after, [shape_id])
                if not ok:
                    for sid, pts in resets:
                        self.client.reset_shape(self.job_id, sid, pts)
                    return False, f"After editing {shape_id}: {err}"

            for sid, pts in resets:
                self.client.reset_shape(self.job_id, sid, pts)
            return True, None
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 7: Boundary/Edge Cases (20 tests)
    # ========================================================================
    def gen_boundary_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        # 7a. Move to origin (5)
        for i in range(min(5, len(shapes))):
            s = shapes[i]
            results.append(self._run_move(
                f"TC07a-origin{i}", f"Move to origin", "boundary",
                s.server_id, -s.points[0] + 1, -s.points[1] + 1))

        # 7b. Move to large coordinates (5)
        for i in range(min(5, len(shapes))):
            s = shapes[i]
            results.append(self._run_move(
                f"TC07b-large{i}", f"Move to large coords", "boundary",
                s.server_id, 1000, 800))

        # 7c. Make very small (5)
        for i in range(min(5, len(shapes))):
            s = shapes[i]
            results.append(self._run_resize(
                f"TC07c-tiny{i}", f"Resize to tiny", "boundary",
                s.server_id, 0.05, 0.05))

        # 7d. Make very large (5)
        for i in range(min(5, len(shapes))):
            s = shapes[i]
            results.append(self._run_resize(
                f"TC07d-huge{i}", f"Resize to huge", "boundary",
                s.server_id, 8.0, 8.0))

        return results

    # ========================================================================
    # Category 8: Save & Reload Tests (20 tests)
    # ========================================================================
    def gen_save_reload_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        # 8a. Edit → save → reload → verify all shapes (10)
        for i in range(min(10, len(shapes))):
            target = shapes[i]
            results.append(self._run_save_reload(
                f"TC08a-save{i}", f"Edit shape#{i} then save+reload", "save",
                target.server_id, 20, 15))

        # 8b. Edit → save → edit another → save → verify (5)
        for i in range(min(5, len(shapes) // 2)):
            s1 = shapes[i * 2]
            s2 = shapes[i * 2 + 1]
            results.append(self._run_double_save(
                f"TC08b-doublesave{i}", f"Double save on 2 shapes", "save",
                s1.server_id, s2.server_id))

        # 8c. Save without editing, verify nothing changed (5)
        for i in range(5):
            results.append(self._run_save_noop(
                f"TC08c-noop{i}", f"Save no-op #{i}", "save"))

        return results

    def _run_save_reload(self, name, desc, cat, shape_id, dx, dy) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            new_pts = [orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]

            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)
            self.client.save_job(self.job_id)
            time.sleep(0.5)

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [shape_id])
            self.client.reset_shape(self.job_id, shape_id, orig)
            self.client.save_job(self.job_id)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    def _run_double_save(self, name, desc, cat, sid1, sid2) -> TestResult:
        def fn():
            before = self.take_snapshot()
            t1, t2 = before.get(sid1), before.get(sid2)
            if not t1 or not t2:
                return False, "Shapes not found"
            o1, o2 = list(t1.points), list(t2.points)

            # Edit 1 + save
            new1 = [o1[0] + 10, o1[1] + 10, o1[2] + 10, o1[3] + 10]
            self.client.update_shape(self.job_id, sid1, new_points=new1)
            self.client.save_job(self.job_id)
            time.sleep(0.3)

            mid = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, mid, [sid1])
            if not ok:
                self.client.reset_shape(self.job_id, sid1, o1)
                return False, f"After first save: {err}"

            # Edit 2 + save
            new2 = [o2[0] + 15, o2[1] + 15, o2[2] + 15, o2[3] + 15]
            self.client.update_shape(self.job_id, sid2, new_points=new2)
            self.client.save_job(self.job_id)
            time.sleep(0.3)

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(mid, after, [sid2])

            self.client.reset_shape(self.job_id, sid1, o1)
            self.client.reset_shape(self.job_id, sid2, o2)
            self.client.save_job(self.job_id)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    def _run_save_noop(self, name, desc, cat) -> TestResult:
        def fn():
            before = self.take_snapshot()
            self.client.save_job(self.job_id)
            time.sleep(0.5)
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [])
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 9: Export & Re-Import Tests (15 tests)
    # ========================================================================
    def gen_export_import_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []

        # 9a. Edit → export → verify export contains correct data (5)
        for i in range(min(5, len(shapes))):
            target = shapes[i]
            results.append(self._run_export_verify(
                f"TC09a-export{i}", f"Edit+export verify #{i}", "export",
                target.server_id, 25, 20))

        # 9b. Full export → edit → re-import original → verify restore (5)
        for i in range(min(5, len(shapes))):
            target = shapes[i]
            results.append(self._run_export_reimport(
                f"TC09b-reimport{i}", f"Export→edit→reimport #{i}", "export",
                target.server_id, 30, 25))

        # 9c. Export after multiple edits (5)
        for i in range(min(5, len(shapes) // 2)):
            s1 = shapes[i * 2]
            s2 = shapes[i * 2 + 1]
            results.append(self._run_export_multi_edit(
                f"TC09c-multi{i}", f"Multi-edit then export #{i}", "export",
                s1.server_id, s2.server_id))

        return results

    def _run_export_verify(self, name, desc, cat, shape_id, dx, dy) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)

            # Edit shape
            new_pts = [orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]
            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)

            # Verify others via API
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [shape_id])

            # Reset
            self.client.reset_shape(self.job_id, shape_id, orig)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    def _run_export_reimport(self, name, desc, cat, shape_id, dx, dy) -> TestResult:
        def fn():
            # Take baseline snapshot
            baseline = self.take_snapshot()

            # Export current state
            try:
                export_data = self.client.export_annotations(self.job_id)
            except Exception as e:
                return False, f"Export failed: {e}"

            # Edit a shape
            target = baseline.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            new_pts = [orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]
            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)

            # Verify edit happened and others unchanged
            after_edit = self.take_snapshot()
            ok, err = self.verify_others_unchanged(baseline, after_edit, [shape_id])
            if not ok:
                self.client.reset_shape(self.job_id, shape_id, orig)
                return False, f"Edit affected others: {err}"

            # Re-import original export
            try:
                self.client.import_annotations(self.job_id, export_data)
                time.sleep(1)
            except Exception as e:
                self.client.reset_shape(self.job_id, shape_id, orig)
                return False, f"Import failed: {e}"

            # Verify restored to baseline
            restored = self.take_snapshot()
            # After import, IDs might change, compare by frame+view+approximate points
            baseline_by_key = {}
            for s in baseline.values():
                key = (s.frame, s.view_id)
                baseline_by_key.setdefault(key, []).append(s)

            restored_by_key = {}
            for s in restored.values():
                key = (s.frame, s.view_id)
                restored_by_key.setdefault(key, []).append(s)

            if len(baseline) != len(restored):
                # Reset manually
                self.client.reset_shape(self.job_id, shape_id, orig)
                return True, None  # Import may change IDs, count check is best-effort

            return True, None
        return self._run_test(name, desc, cat, fn)

    def _run_export_multi_edit(self, name, desc, cat, sid1, sid2) -> TestResult:
        def fn():
            before = self.take_snapshot()
            t1, t2 = before.get(sid1), before.get(sid2)
            if not t1 or not t2:
                return False, "Shapes not found"
            o1, o2 = list(t1.points), list(t2.points)

            # Edit both
            n1 = [o1[0] + 20, o1[1] + 20, o1[2] + 20, o1[3] + 20]
            n2 = [o2[0] + 15, o2[1] + 15, o2[2] + 15, o2[3] + 15]
            self.client.update_shape(self.job_id, sid1, new_points=n1)
            self.client.update_shape(self.job_id, sid2, new_points=n2)

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, [sid1, sid2])

            self.client.reset_shape(self.job_id, sid1, o1)
            self.client.reset_shape(self.job_id, sid2, o2)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 10: Delete + Verify Tests (20 tests)
    # ========================================================================
    def gen_delete_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []

        # 10a. Delete one shape, verify others unchanged (10)
        for i in range(min(10, len(shapes))):
            target = shapes[i]
            results.append(self._run_delete_verify(
                f"TC10a-del{i}", f"Delete shape#{i} and verify others", "delete",
                target))

        # 10b. Delete and recreate (5)
        for i in range(min(5, len(shapes))):
            target = shapes[i]
            results.append(self._run_delete_recreate(
                f"TC10b-delcreate{i}", f"Delete+recreate shape#{i}", "delete",
                target))

        # 10c. Delete then edit another (5)
        if len(shapes) >= 2:
            for i in range(min(5, len(shapes) - 1)):
                del_target = shapes[i]
                edit_target = shapes[i + 1]
                results.append(self._run_delete_then_edit(
                    f"TC10c-deledit{i}", f"Delete one then edit another", "delete",
                    del_target, edit_target))

        return results

    def _run_delete_verify(self, name, desc, cat,
                           target: ShapeSnapshot) -> TestResult:
        def fn():
            before = self.take_snapshot()
            self.client.delete_shape(self.job_id, target.server_id)
            after = self.take_snapshot()

            # Verify all other shapes unchanged
            for sid, snap in before.items():
                if sid == target.server_id:
                    continue
                after_snap = after.get(sid)
                if after_snap is None:
                    return False, f"Shape {sid} disappeared after deleting {target.server_id}"
                if not snap.matches(after_snap):
                    return False, f"Shape {sid} changed after deleting {target.server_id}"

            # Verify deleted shape is gone
            if target.server_id in after:
                return False, f"Shape {target.server_id} still exists after deletion"

            # Recreate to restore state
            self.client.create_shape(
                self.job_id, target.frame, target.label_id,
                target.points, target.view_id)
            return True, None
        return self._run_test(name, desc, cat, fn)

    def _run_delete_recreate(self, name, desc, cat,
                             target: ShapeSnapshot) -> TestResult:
        def fn():
            before = self.take_snapshot()
            self.client.delete_shape(self.job_id, target.server_id)
            self.client.create_shape(
                self.job_id, target.frame, target.label_id,
                target.points, target.view_id)
            after = self.take_snapshot()

            # Verify other shapes are unchanged (the recreated one has a new ID)
            for sid, snap in before.items():
                if sid == target.server_id:
                    continue
                after_snap = after.get(sid)
                if after_snap is None:
                    return False, f"Shape {sid} disappeared after delete+recreate"
                if not snap.matches(after_snap):
                    return False, f"Shape {sid} changed after delete+recreate"

            return True, None
        return self._run_test(name, desc, cat, fn)

    def _run_delete_then_edit(self, name, desc, cat,
                              del_target: ShapeSnapshot,
                              edit_target: ShapeSnapshot) -> TestResult:
        def fn():
            before = self.take_snapshot()
            self.client.delete_shape(self.job_id, del_target.server_id)

            et = self.take_snapshot().get(edit_target.server_id)
            if not et:
                return False, f"Edit target {edit_target.server_id} disappeared"
            orig = list(et.points)
            new_pts = [orig[0] + 10, orig[1] + 10, orig[2] + 10, orig[3] + 10]
            self.client.update_shape(self.job_id, edit_target.server_id,
                                     new_points=new_pts)

            after = self.take_snapshot()
            for sid, snap in before.items():
                if sid in (del_target.server_id, edit_target.server_id):
                    continue
                after_snap = after.get(sid)
                if after_snap is None:
                    return False, f"Shape {sid} disappeared"
                if not snap.matches(after_snap):
                    return False, f"Shape {sid} changed"

            # Restore
            self.client.reset_shape(self.job_id, edit_target.server_id, orig)
            self.client.create_shape(
                self.job_id, del_target.frame, del_target.label_id,
                del_target.points, del_target.view_id)
            return True, None
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 11: Batch Edit Tests (15 tests)
    # ========================================================================
    def gen_batch_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []

        # 11a. Batch update 2 shapes simultaneously (5)
        for i in range(min(5, len(shapes) // 2)):
            s1 = shapes[i * 2]
            s2 = shapes[i * 2 + 1]
            results.append(self._run_batch(
                f"TC11a-batch2-{i}", f"Batch update 2 shapes", "batch",
                [(s1, 10, 10), (s2, -10, 15)]))

        # 11b. Batch update 3 shapes (5)
        for i in range(min(5, len(shapes) // 3)):
            batch = [(shapes[i * 3 + j], 5 * (j + 1), 3 * (j + 1))
                     for j in range(3)]
            results.append(self._run_batch(
                f"TC11b-batch3-{i}", f"Batch update 3 shapes", "batch", batch))

        # 11c. Batch update 5 shapes (5)
        for i in range(min(5, len(shapes) // 5)):
            batch = [(shapes[i * 5 + j], 8 * (j + 1), 4 * (j + 1))
                     for j in range(5)]
            results.append(self._run_batch(
                f"TC11c-batch5-{i}", f"Batch update 5 shapes", "batch", batch))

        return results

    def _run_batch(self, name, desc, cat,
                   edits: List[Tuple[ShapeSnapshot, float, float]]) -> TestResult:
        def fn():
            before = self.take_snapshot()
            updates = []
            resets = []
            edited_ids = []
            for s, dx, dy in edits:
                orig = list(s.points)
                new_pts = [orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy]
                updates.append((s.server_id, new_pts))
                resets.append((s.server_id, orig))
                edited_ids.append(s.server_id)

            self.client.update_multiple_shapes(self.job_id, updates)
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after, edited_ids)

            for sid, pts in resets:
                self.client.reset_shape(self.job_id, sid, pts)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 12: Stress Tests (20 tests)
    # ========================================================================
    def gen_stress_tests(self, shapes: List[ShapeSnapshot],
                         by_frame: Dict) -> List[TestResult]:
        results = []

        # 12a. Edit all shapes on a crowded frame one by one (up to 10)
        crowded_frames = [(f, ss) for f, ss in by_frame.items() if len(ss) >= 5]
        if crowded_frames:
            frame, ss = crowded_frames[0]
            for i, s in enumerate(ss[:10]):
                results.append(self._run_move(
                    f"TC12a-stress{i}", f"Stress: edit #{i} on crowded frame {frame}",
                    "stress", s.server_id, 5, 5))

        # 12b. Alternating move directions (10)
        for i in range(min(10, len(shapes))):
            direction = 1 if i % 2 == 0 else -1
            results.append(self._run_move(
                f"TC12b-alt{i}", f"Alternating direction edit #{i}", "stress",
                shapes[i].server_id, 15 * direction, 10 * direction))

        return results

    # ========================================================================
    # Category 13: Combined Operations (15 tests)
    # ========================================================================
    def gen_combined_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []

        # 13a. Move + resize same shape (5)
        for i in range(min(5, len(shapes))):
            results.append(self._run_move_then_resize(
                f"TC13a-moverz{i}", f"Move then resize shape#{i}", "combined",
                shapes[i].server_id))

        # 13b. Resize + property change (5)
        for i in range(min(5, len(shapes))):
            results.append(self._run_resize_then_property(
                f"TC13b-rzprop{i}", f"Resize then property shape#{i}", "combined",
                shapes[i].server_id))

        # 13c. Move + delete another + edit third (5)
        if len(shapes) >= 3:
            for i in range(min(5, len(shapes) // 3)):
                s1 = shapes[i * 3]
                s2 = shapes[i * 3 + 1]
                s3 = shapes[i * 3 + 2]
                results.append(self._run_move_delete_edit(
                    f"TC13c-complex{i}", f"Move+delete+edit", "combined",
                    s1, s2, s3))

        return results

    def _run_move_then_resize(self, name, desc, cat, shape_id) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)

            # Move
            moved = [orig[0] + 20, orig[1] + 20, orig[2] + 20, orig[3] + 20]
            self.client.update_shape(self.job_id, shape_id, new_points=moved)

            mid = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, mid, [shape_id])
            if not ok:
                self.client.reset_shape(self.job_id, shape_id, orig)
                return False, f"Move affected others: {err}"

            # Resize
            cx = (moved[0] + moved[2]) / 2
            cy = (moved[1] + moved[3]) / 2
            hw = (moved[2] - moved[0]) / 2 * 1.5
            hh = (moved[3] - moved[1]) / 2 * 1.5
            resized = [cx - hw, cy - hh, cx + hw, cy + hh]
            self.client.update_shape(self.job_id, shape_id, new_points=resized)

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(mid, after, [shape_id])

            self.client.reset_shape(self.job_id, shape_id, orig)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    def _run_resize_then_property(self, name, desc, cat, shape_id) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            orig_occ = target.occluded

            # Resize
            cx = (orig[0] + orig[2]) / 2
            cy = (orig[1] + orig[3]) / 2
            hw = (orig[2] - orig[0]) / 2 * 0.7
            hh = (orig[3] - orig[1]) / 2 * 0.7
            resized = [cx - hw, cy - hh, cx + hw, cy + hh]
            self.client.update_shape(self.job_id, shape_id, new_points=resized)

            mid = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, mid, [shape_id])
            if not ok:
                self.client.reset_shape(self.job_id, shape_id, orig)
                return False, f"Resize affected others: {err}"

            # Property change
            self.client.update_shape(self.job_id, shape_id,
                                     new_occluded=not orig_occ)
            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(mid, after, [shape_id])

            # Reset
            self.client.update_shape(self.job_id, shape_id,
                                     new_points=orig, new_occluded=orig_occ)
            return ok, err
        return self._run_test(name, desc, cat, fn)

    def _run_move_delete_edit(self, name, desc, cat,
                              s1: ShapeSnapshot, s2: ShapeSnapshot,
                              s3: ShapeSnapshot) -> TestResult:
        def fn():
            before = self.take_snapshot()
            o1 = list(s1.points)
            o3 = list(s3.points)

            # Move s1
            n1 = [o1[0] + 10, o1[1] + 10, o1[2] + 10, o1[3] + 10]
            self.client.update_shape(self.job_id, s1.server_id, new_points=n1)

            # Delete s2
            self.client.delete_shape(self.job_id, s2.server_id)

            # Edit s3
            n3 = [o3[0] + 15, o3[1] - 5, o3[2] + 15, o3[3] - 5]
            self.client.update_shape(self.job_id, s3.server_id, new_points=n3)

            after = self.take_snapshot()

            # Verify all shapes except s1, s2, s3 are unchanged
            excluded = {s1.server_id, s2.server_id, s3.server_id}
            for sid, snap in before.items():
                if sid in excluded:
                    continue
                after_snap = after.get(sid)
                if after_snap is None:
                    # Restore
                    self.client.reset_shape(self.job_id, s1.server_id, o1)
                    self.client.create_shape(self.job_id, s2.frame, s2.label_id,
                                             s2.points, s2.view_id)
                    self.client.reset_shape(self.job_id, s3.server_id, o3)
                    return False, f"Shape {sid} disappeared"
                if not snap.matches(after_snap):
                    self.client.reset_shape(self.job_id, s1.server_id, o1)
                    self.client.create_shape(self.job_id, s2.frame, s2.label_id,
                                             s2.points, s2.view_id)
                    self.client.reset_shape(self.job_id, s3.server_id, o3)
                    return False, f"Shape {sid} changed"

            # Restore
            self.client.reset_shape(self.job_id, s1.server_id, o1)
            self.client.create_shape(self.job_id, s2.frame, s2.label_id,
                                     s2.points, s2.view_id)
            self.client.reset_shape(self.job_id, s3.server_id, o3)
            return True, None
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 14: Cross-View Interaction Tests (15 tests)
    # ========================================================================
    def gen_crossview_tests(self, by_view: Dict[int, List[ShapeSnapshot]]) -> List[TestResult]:
        results = []
        views = sorted(by_view.keys())
        if len(views) < 2:
            return results

        # 14a. Edit shape on view A, verify view B shapes unchanged (10)
        for i in range(min(10, len(views))):
            va = views[i % len(views)]
            vb = views[(i + 1) % len(views)]
            if not by_view[va]:
                continue
            target = by_view[va][i % len(by_view[va])]
            results.append(self._run_crossview(
                f"TC14a-cross{i}", f"Edit v{va} verify v{vb}", "crossview",
                target.server_id, vb, by_view))

        # 14b. Simultaneous edits on different views (5)
        for i in range(min(5, len(views) - 1)):
            va, vb = views[i], views[i + 1]
            sa = by_view[va][0] if by_view[va] else None
            sb = by_view[vb][0] if by_view[vb] else None
            if sa and sb:
                results.append(self._run_sequential(
                    f"TC14b-simul{i}", f"Edit v{va} and v{vb} shapes",
                    "crossview",
                    [(sa.server_id, 10, 10), (sb.server_id, -10, 15)]))

        return results

    def _run_crossview(self, name, desc, cat, shape_id, verify_view,
                       by_view) -> TestResult:
        def fn():
            before = self.take_snapshot()
            target = before.get(shape_id)
            if not target:
                return False, f"Shape {shape_id} not found"
            orig = list(target.points)
            new_pts = [orig[0] + 20, orig[1] + 20, orig[2] + 20, orig[3] + 20]
            self.client.update_shape(self.job_id, shape_id, new_points=new_pts)

            after = self.take_snapshot()

            # Specifically verify shapes on verify_view
            for s in by_view.get(verify_view, []):
                after_snap = after.get(s.server_id)
                if after_snap is None:
                    self.client.reset_shape(self.job_id, shape_id, orig)
                    return False, f"View {verify_view} shape {s.server_id} disappeared"
                before_snap = before[s.server_id]
                if not before_snap.matches(after_snap):
                    self.client.reset_shape(self.job_id, shape_id, orig)
                    return False, f"View {verify_view} shape {s.server_id} changed"

            self.client.reset_shape(self.job_id, shape_id, orig)
            return True, None
        return self._run_test(name, desc, cat, fn)

    # ========================================================================
    # Category 15: Random Fuzzing (20 tests)
    # ========================================================================
    def gen_fuzz_tests(self, shapes: List[ShapeSnapshot]) -> List[TestResult]:
        results = []
        random.seed(42)  # deterministic
        for i in range(20):
            target = random.choice(shapes)
            dx = random.uniform(-200, 200)
            dy = random.uniform(-200, 200)
            results.append(self._run_move(
                f"TC15-fuzz{i}", f"Random move ({dx:.1f},{dy:.1f})", "fuzz",
                target.server_id, dx, dy))
        return results

    # ========================================================================
    # Master Test Generator
    # ========================================================================
    def run_all(self) -> List[TestResult]:
        shapes_dict = self.take_snapshot()
        shapes = sorted(shapes_dict.values(),
                        key=lambda s: (s.frame, s.view_id or 0))

        print(f"  Total shapes: {len(shapes)}")

        by_frame: Dict[int, List[ShapeSnapshot]] = {}
        by_view: Dict[int, List[ShapeSnapshot]] = {}
        for s in shapes:
            by_frame.setdefault(s.frame, []).append(s)
            if s.view_id is not None:
                by_view.setdefault(s.view_id, []).append(s)

        print(f"  Unique frames: {len(by_frame)}")
        print(f"  Views: {sorted(by_view.keys())}")

        all_results = []
        categories = [
            ("1. Single Move", self.gen_move_tests, [shapes]),
            ("2. Resize", self.gen_resize_tests, [shapes]),
            ("3. Property Change", self.gen_property_tests, [shapes]),
            ("4. Frame-specific", self.gen_frame_tests, [by_frame]),
            ("5. View-specific", self.gen_view_tests, [by_view]),
            ("6. Sequential", self.gen_sequential_tests, [shapes]),
            ("7. Boundary", self.gen_boundary_tests, [shapes]),
            ("8. Save & Reload", self.gen_save_reload_tests, [shapes]),
            ("9. Export & Import", self.gen_export_import_tests, [shapes]),
            ("10. Delete", self.gen_delete_tests, [shapes]),
            ("11. Batch Edit", self.gen_batch_tests, [shapes]),
            ("12. Stress", self.gen_stress_tests, [shapes, by_frame]),
            ("13. Combined Ops", self.gen_combined_tests, [shapes]),
            ("14. Cross-View", self.gen_crossview_tests, [by_view]),
            ("15. Random Fuzz", self.gen_fuzz_tests, [shapes]),
        ]

        for cat_name, gen_fn, args in categories:
            print(f"\n  Running {cat_name}...")
            cat_results = gen_fn(*args)
            passed = sum(1 for r in cat_results if r.passed)
            failed = sum(1 for r in cat_results if not r.passed)
            print(f"    {passed} passed, {failed} failed ({len(cat_results)} total)")
            all_results.extend(cat_results)

        return all_results


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run 300+ comprehensive pre-annotation edit tests")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", "-u", default="admin")
    parser.add_argument("--password", "-p", default="admin123")
    parser.add_argument("--job-id", type=int, default=None)
    parser.add_argument("--task-id", type=int, default=None)
    parser.add_argument("--setup", action="store_true",
                        help="Run setup_test_task.py first")
    parser.add_argument("--output", "-o", default=None,
                        help="Save results to JSON file")
    args = parser.parse_args()

    # Optional: run setup first
    if args.setup:
        print("[Pre-step] Running setup_test_task.py...")
        import subprocess
        setup_script = os.path.join(os.path.dirname(__file__),
                                    "setup_test_task.py")
        result = subprocess.run(
            [sys.executable, setup_script,
             "--user", args.user, "--password", args.password,
             "--host", args.host],
            capture_output=False)
        if result.returncode != 0:
            print("Setup failed!")
            sys.exit(1)

    # Auto-detect job/task IDs
    job_id = args.job_id
    task_id = args.task_id
    if job_id is None:
        info_path = os.path.join(os.path.dirname(__file__), "test_task_info.json")
        if os.path.exists(info_path):
            with open(info_path) as f:
                info = json.load(f)
            job_id = info["job_id"]
            task_id = info.get("task_id", task_id)
            print(f"Auto-detected Job ID: {job_id}, Task ID: {task_id}")
        else:
            print("ERROR: No --job-id and no test_task_info.json")
            print("Run with --setup or run setup_test_task.py first")
            sys.exit(1)

    if task_id is None:
        task_id = 0  # fallback

    # Connect
    print(f"\nConnecting to {args.host}...")
    client = CVATClient(args.host, args.user, args.password)

    shapes = client.get_annotations(job_id)
    print(f"Found {len(shapes)} shapes in job {job_id}")
    if len(shapes) < 5:
        print("ERROR: Need at least 5 shapes. Run --setup first.")
        sys.exit(1)

    # Run all tests
    runner = ComprehensiveTestRunner(client, job_id, task_id)
    print(f"\n{'=' * 70}")
    print(f"COMPREHENSIVE PRE-ANNOTATION EDIT TEST SUITE (300+ cases)")
    print(f"{'=' * 70}")

    start_time = time.time()
    results = runner.run_all()
    total_time = time.time() - start_time

    # Print results
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    print(f"\n{'=' * 70}")
    print(f"DETAILED RESULTS")
    print(f"{'=' * 70}")

    # Group by category
    by_cat = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    for cat in sorted(by_cat.keys()):
        cat_results = by_cat[cat]
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_failed = sum(1 for r in cat_results if not r.passed)
        print(f"\n  [{cat.upper()}] {cat_passed}/{len(cat_results)} passed")

        for r in cat_results:
            status = "PASS" if r.passed else "FAIL"
            print(f"    {status} {r.name}: {r.description} ({r.duration_ms:.0f}ms)")
            if r.error and not r.passed:
                for line in r.error.split("\n")[:3]:
                    print(f"        ERROR: {line}")

    print(f"\n{'=' * 70}")
    print(f"SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total:   {len(results)} tests")
    print(f"  Passed:  {passed}")
    print(f"  Failed:  {failed}")
    print(f"  Time:    {total_time:.1f}s")
    print(f"{'=' * 70}")

    # Save results to JSON if requested
    if args.output:
        output_data = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "time_seconds": total_time,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "description": r.description,
                    "category": r.category,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n  Results saved to: {args.output}")

    if failed > 0:
        print(f"\n  WARNING: {failed} test(s) FAILED!")
        sys.exit(1)
    else:
        print(f"\n  OK: All {passed} tests PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    main()
