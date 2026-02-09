#!/usr/bin/env python3
"""
Pre-Annotation Edit Bug Test Suite (50+ test cases)

Tests that editing (move/resize) one pre-annotation does NOT affect other
pre-annotations. This was a bug caused by spread operator on ObjectState
objects with non-enumerable properties.

The test strategy:
1. Navigate to the multiview workspace in CVAT
2. For each test case, record all annotation positions via API
3. Perform an edit action (move/resize) on a specific annotation
4. Re-read all annotations via API
5. Verify ONLY the edited annotation changed; all others remain identical

Run after setup_test_task.py has created the test task.

Usage:
    python scripts/test/test_preannotation_edit.py --user admin --password admin123
"""

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_HOST = "http://localhost:8080"
TOLERANCE = 0.5  # pixel tolerance for floating-point comparison


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
        """Check if points match within tolerance."""
        if len(self.points) != len(other.points):
            return False
        return all(
            abs(a - b) <= TOLERANCE
            for a, b in zip(self.points, other.points)
        )

    def matches(self, other: 'ShapeSnapshot', ignore_points: bool = False) -> bool:
        """Check if two snapshots are identical (ignoring points if specified)."""
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
    error: Optional[str] = None
    details: Optional[str] = None


# ============================================================================
# API Helper
# ============================================================================

class CVATClient:
    """CVAT API client for annotation testing."""

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
        """Get all shape annotations for a job."""
        resp = self.session.get(f"{self.host}/api/jobs/{job_id}/annotations")
        resp.raise_for_status()
        data = resp.json()
        return [ShapeSnapshot.from_api(s) for s in data.get("shapes", [])]

    def get_raw_annotations(self, job_id: int) -> dict:
        """Get raw annotation data from API."""
        resp = self.session.get(f"{self.host}/api/jobs/{job_id}/annotations")
        resp.raise_for_status()
        return resp.json()

    def _get_raw_shape(self, job_id: int, shape_id: int) -> dict:
        """Get the full raw shape data from the API by shape ID."""
        data = self.get_raw_annotations(job_id)
        for s in data.get("shapes", []):
            if s["id"] == shape_id:
                return s
        raise RuntimeError(f"Shape {shape_id} not found")

    def update_shape(self, job_id: int, shape_id: int,
                     new_points: Optional[List[float]] = None,
                     new_rotation: Optional[float] = None,
                     new_occluded: Optional[bool] = None,
                     new_z_order: Optional[int] = None) -> dict:
        """Update a single shape's properties.

        CVAT's PATCH action=update requires all required fields (type, frame,
        label_id, etc.), so we fetch the full shape first and modify it.
        """
        raw = self._get_raw_shape(job_id, shape_id)

        # Build full shape data with all required fields
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

        # Apply overrides
        if new_points is not None:
            shape_data["points"] = new_points
        if new_rotation is not None:
            shape_data["rotation"] = new_rotation
        if new_occluded is not None:
            shape_data["occluded"] = new_occluded
        if new_z_order is not None:
            shape_data["z_order"] = new_z_order

        payload = {
            "shapes": [shape_data],
            "tracks": [],
            "tags": [],
        }
        resp = self.session.patch(
            f"{self.host}/api/jobs/{job_id}/annotations?action=update",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def reset_shape(self, job_id: int, shape_id: int,
                    original_points: List[float]):
        """Reset a shape back to its original points."""
        self.update_shape(job_id, shape_id, new_points=original_points)


# ============================================================================
# Test Runner
# ============================================================================

class PreAnnotationTestRunner:
    """Runs 50+ test cases for pre-annotation edit isolation."""

    def __init__(self, client: CVATClient, job_id: int):
        self.client = client
        self.job_id = job_id
        self.results: List[TestResult] = []

    def take_snapshot(self) -> Dict[int, ShapeSnapshot]:
        """Take a snapshot of all annotations, keyed by server_id."""
        shapes = self.client.get_annotations(self.job_id)
        return {s.server_id: s for s in shapes}

    def verify_others_unchanged(
        self,
        before: Dict[int, ShapeSnapshot],
        after: Dict[int, ShapeSnapshot],
        edited_id: int,
    ) -> Tuple[bool, Optional[str]]:
        """Verify all shapes except the edited one remain unchanged."""
        errors = []

        # Check no shapes were added or removed
        if len(before) != len(after):
            return False, f"Shape count changed: {len(before)} → {len(after)}"

        for sid, before_snap in before.items():
            if sid == edited_id:
                continue  # Skip the intentionally edited shape

            after_snap = after.get(sid)
            if after_snap is None:
                errors.append(f"Shape {sid} disappeared after edit!")
                continue

            if not before_snap.matches(after_snap):
                diff_parts = []
                if not before_snap.points_match(after_snap):
                    diff_parts.append(
                        f"points: {before_snap.points} → {after_snap.points}"
                    )
                if before_snap.frame != after_snap.frame:
                    diff_parts.append(
                        f"frame: {before_snap.frame} → {after_snap.frame}"
                    )
                if before_snap.view_id != after_snap.view_id:
                    diff_parts.append(
                        f"view_id: {before_snap.view_id} → {after_snap.view_id}"
                    )
                if before_snap.occluded != after_snap.occluded:
                    diff_parts.append(
                        f"occluded: {before_snap.occluded} → {after_snap.occluded}"
                    )
                if abs(before_snap.rotation - after_snap.rotation) > TOLERANCE:
                    diff_parts.append(
                        f"rotation: {before_snap.rotation} → {after_snap.rotation}"
                    )
                errors.append(
                    f"Shape {sid} (frame={before_snap.frame}, view={before_snap.view_id}) "
                    f"changed: {'; '.join(diff_parts)}"
                )

        if errors:
            return False, "\n".join(errors)
        return True, None

    def run_move_test(self, test_name: str, description: str,
                      target_shape_id: int, dx: float, dy: float) -> TestResult:
        """Run a single move test: move one shape, verify others unchanged."""
        try:
            # Snapshot before
            before = self.take_snapshot()
            target = before.get(target_shape_id)
            if target is None:
                return TestResult(test_name, False, description,
                                  error=f"Shape {target_shape_id} not found")

            original_points = list(target.points)

            # Move: shift all points by (dx, dy)
            new_points = [
                target.points[0] + dx,  # x1
                target.points[1] + dy,  # y1
                target.points[2] + dx,  # x2
                target.points[3] + dy,  # y2
            ]

            # Apply move
            self.client.update_shape(self.job_id, target_shape_id,
                                     new_points=new_points)

            # Snapshot after
            after = self.take_snapshot()

            # Verify the target moved correctly
            after_target = after.get(target_shape_id)
            if after_target is None:
                return TestResult(test_name, False, description,
                                  error="Target shape disappeared after move")

            expected = ShapeSnapshot(
                server_id=target_shape_id,
                frame=target.frame,
                view_id=target.view_id,
                points=new_points,
                label_id=target.label_id,
                occluded=target.occluded,
                z_order=target.z_order,
                rotation=target.rotation,
            )
            if not after_target.points_match(expected):
                return TestResult(
                    test_name, False, description,
                    error=f"Target didn't move correctly: "
                          f"expected {new_points}, got {after_target.points}"
                )

            # Verify others unchanged
            ok, err = self.verify_others_unchanged(before, after,
                                                   target_shape_id)

            # Reset
            self.client.reset_shape(self.job_id, target_shape_id,
                                    original_points)

            if ok:
                return TestResult(test_name, True, description)
            else:
                return TestResult(test_name, False, description, error=err)

        except Exception as e:
            return TestResult(test_name, False, description,
                              error=f"Exception: {e}")

    def run_resize_test(self, test_name: str, description: str,
                        target_shape_id: int, scale_x: float,
                        scale_y: float) -> TestResult:
        """Run a resize test: resize one shape, verify others unchanged."""
        try:
            before = self.take_snapshot()
            target = before.get(target_shape_id)
            if target is None:
                return TestResult(test_name, False, description,
                                  error=f"Shape {target_shape_id} not found")

            original_points = list(target.points)

            # Resize: scale from center
            cx = (target.points[0] + target.points[2]) / 2
            cy = (target.points[1] + target.points[3]) / 2
            half_w = (target.points[2] - target.points[0]) / 2 * scale_x
            half_h = (target.points[3] - target.points[1]) / 2 * scale_y

            new_points = [
                cx - half_w,
                cy - half_h,
                cx + half_w,
                cy + half_h,
            ]

            self.client.update_shape(self.job_id, target_shape_id,
                                     new_points=new_points)

            after = self.take_snapshot()

            # Verify others
            ok, err = self.verify_others_unchanged(before, after,
                                                   target_shape_id)

            # Reset
            self.client.reset_shape(self.job_id, target_shape_id,
                                    original_points)

            if ok:
                return TestResult(test_name, True, description)
            else:
                return TestResult(test_name, False, description, error=err)

        except Exception as e:
            return TestResult(test_name, False, description,
                              error=f"Exception: {e}")

    def run_property_test(self, test_name: str, description: str,
                          target_shape_id: int,
                          new_occluded: Optional[bool] = None,
                          new_z_order: Optional[int] = None,
                          new_rotation: Optional[float] = None) -> TestResult:
        """Test changing a non-position property."""
        try:
            before = self.take_snapshot()
            target = before.get(target_shape_id)
            if target is None:
                return TestResult(test_name, False, description,
                                  error=f"Shape {target_shape_id} not found")

            # Save originals for reset
            orig_occluded = target.occluded
            orig_z_order = target.z_order
            orig_rotation = target.rotation

            self.client.update_shape(
                self.job_id, target_shape_id,
                new_occluded=new_occluded,
                new_z_order=new_z_order,
                new_rotation=new_rotation,
            )

            after = self.take_snapshot()
            ok, err = self.verify_others_unchanged(before, after,
                                                   target_shape_id)

            # Reset
            self.client.update_shape(
                self.job_id, target_shape_id,
                new_occluded=orig_occluded,
                new_z_order=orig_z_order,
                new_rotation=orig_rotation,
            )

            if ok:
                return TestResult(test_name, True, description)
            else:
                return TestResult(test_name, False, description, error=err)

        except Exception as e:
            return TestResult(test_name, False, description,
                              error=f"Exception: {e}")

    def run_sequential_test(self, test_name: str, description: str,
                            edits: List[Tuple[int, float, float]]) -> TestResult:
        """Test multiple sequential edits on different shapes."""
        try:
            initial = self.take_snapshot()
            resets = []  # (shape_id, original_points) for cleanup

            for shape_id, dx, dy in edits:
                before = self.take_snapshot()
                target = before.get(shape_id)
                if target is None:
                    continue

                original_points = list(target.points)
                resets.append((shape_id, original_points))

                new_points = [
                    target.points[0] + dx, target.points[1] + dy,
                    target.points[2] + dx, target.points[3] + dy,
                ]

                self.client.update_shape(self.job_id, shape_id,
                                         new_points=new_points)

                after = self.take_snapshot()
                ok, err = self.verify_others_unchanged(before, after, shape_id)

                if not ok:
                    # Reset all
                    for sid, pts in resets:
                        self.client.reset_shape(self.job_id, sid, pts)
                    return TestResult(
                        test_name, False, description,
                        error=f"After editing shape {shape_id}: {err}"
                    )

            # Reset all
            for sid, pts in resets:
                self.client.reset_shape(self.job_id, sid, pts)

            return TestResult(test_name, True, description)

        except Exception as e:
            return TestResult(test_name, False, description,
                              error=f"Exception: {e}")

    def generate_test_cases(self) -> List[TestResult]:
        """Generate and run 50+ test cases."""
        shapes = self.take_snapshot()
        shape_list = sorted(shapes.values(), key=lambda s: (s.frame, s.view_id or 0))

        if len(shape_list) < 5:
            print(f"ERROR: Need at least 5 shapes, found {len(shape_list)}")
            sys.exit(1)

        # Group shapes by frame and view for targeted testing
        by_frame: Dict[int, List[ShapeSnapshot]] = {}
        by_view: Dict[int, List[ShapeSnapshot]] = {}
        for s in shape_list:
            by_frame.setdefault(s.frame, []).append(s)
            if s.view_id is not None:
                by_view.setdefault(s.view_id, []).append(s)

        results = []

        # === Category 1: Single Shape Move (12 tests) ===
        # Move first shape in various directions
        s0 = shape_list[0]
        directions = [
            (10, 0, "right"), (-10, 0, "left"), (0, 10, "down"), (0, -10, "up"),
            (20, 20, "diagonal-SE"), (-20, -20, "diagonal-NW"),
            (50, 0, "large-right"), (0, 50, "large-down"),
            (1, 0, "tiny-right"), (0, 1, "tiny-down"),
            (100, 100, "very-large-SE"), (-5, 15, "asymmetric"),
        ]
        for dx, dy, dir_name in directions:
            results.append(self.run_move_test(
                f"TC01-move-{dir_name}",
                f"Move shape {s0.server_id} (frame {s0.frame}, view {s0.view_id}) {dir_name} by ({dx},{dy})",
                s0.server_id, dx, dy,
            ))

        # === Category 2: Move shapes on different frames (8 tests) ===
        unique_frames = sorted(by_frame.keys())
        for i, frame in enumerate(unique_frames[:8]):
            target = by_frame[frame][0]
            results.append(self.run_move_test(
                f"TC02-frame{frame}-move",
                f"Move first shape on frame {frame} (view {target.view_id})",
                target.server_id, 15, 15,
            ))

        # === Category 3: Move shapes on different views (5 tests) ===
        for view_id in sorted(by_view.keys())[:5]:
            target = by_view[view_id][0]
            results.append(self.run_move_test(
                f"TC03-view{view_id}-move",
                f"Move first shape on view {view_id} (frame {target.frame})",
                target.server_id, 20, -10,
            ))

        # === Category 4: Resize shapes (6 tests) ===
        resize_targets = shape_list[:6]
        scales = [(1.5, 1.5), (0.5, 0.5), (2.0, 1.0), (1.0, 2.0), (0.3, 0.3), (1.2, 0.8)]
        for i, (target, (sx, sy)) in enumerate(zip(resize_targets, scales)):
            results.append(self.run_resize_test(
                f"TC04-resize-{i}",
                f"Resize shape {target.server_id} (frame {target.frame}) by ({sx}x, {sy}x)",
                target.server_id, sx, sy,
            ))

        # === Category 5: Edit shapes with multiple annotations on same frame (5 tests) ===
        # Frame 7 has 5 shapes on view 1
        if 7 in by_frame and len(by_frame[7]) >= 3:
            crowded = by_frame[7]
            for i, target in enumerate(crowded[:5]):
                results.append(self.run_move_test(
                    f"TC05-sameframe-{i}",
                    f"Move shape {target.server_id} on crowded frame 7 (view {target.view_id})",
                    target.server_id, 10 * (i + 1), 5 * (i + 1),
                ))

        # === Category 6: Edit shapes on frame 75 (dense cluster, 5 tests) ===
        if 75 in by_frame and len(by_frame[75]) >= 5:
            dense = by_frame[75]
            for i, target in enumerate(dense[:5]):
                results.append(self.run_move_test(
                    f"TC06-dense-{i}",
                    f"Move shape {target.server_id} in dense cluster (frame 75)",
                    target.server_id, 5, 5,
                ))

        # === Category 7: Property changes (4 tests) ===
        prop_target = shape_list[0]
        results.append(self.run_property_test(
            "TC07-occluded",
            f"Toggle occluded on shape {prop_target.server_id}",
            prop_target.server_id, new_occluded=True,
        ))
        results.append(self.run_property_test(
            "TC07-zorder",
            f"Change z_order on shape {prop_target.server_id}",
            prop_target.server_id, new_z_order=5,
        ))
        results.append(self.run_property_test(
            "TC07-rotation",
            f"Add rotation to shape {prop_target.server_id}",
            prop_target.server_id, new_rotation=45.0,
        ))
        results.append(self.run_property_test(
            "TC07-multi-prop",
            f"Change multiple properties on shape {prop_target.server_id}",
            prop_target.server_id, new_occluded=True, new_z_order=10,
        ))

        # === Category 8: Sequential edits on different shapes (3 tests) ===
        if len(shape_list) >= 10:
            # Edit 3 shapes sequentially
            results.append(self.run_sequential_test(
                "TC08-seq-3shapes",
                "Edit 3 shapes sequentially on different frames",
                [
                    (shape_list[0].server_id, 10, 10),
                    (shape_list[3].server_id, -10, 15),
                    (shape_list[6].server_id, 20, -5),
                ],
            ))
            # Edit 5 shapes sequentially
            results.append(self.run_sequential_test(
                "TC08-seq-5shapes",
                "Edit 5 shapes sequentially",
                [
                    (shape_list[i].server_id, 10 * (i + 1), 5 * (i + 1))
                    for i in range(5)
                ],
            ))
            # Edit shapes on same frame sequentially
            if 7 in by_frame and len(by_frame[7]) >= 3:
                results.append(self.run_sequential_test(
                    "TC08-seq-sameframe",
                    "Edit 3 shapes on same frame sequentially",
                    [
                        (by_frame[7][i].server_id, 10, 10)
                        for i in range(min(3, len(by_frame[7])))
                    ],
                ))

        # === Category 9: Boundary moves (3 tests) ===
        # Move to edge of canvas
        results.append(self.run_move_test(
            "TC09-boundary-topleft",
            "Move shape near (0,0)",
            shape_list[0].server_id,
            -shape_list[0].points[0] + 5,
            -shape_list[0].points[1] + 5,
        ))
        results.append(self.run_move_test(
            "TC09-boundary-large-x",
            "Move shape to large X coordinate",
            shape_list[1].server_id, 500, 0,
        ))
        results.append(self.run_move_test(
            "TC09-boundary-large-y",
            "Move shape to large Y coordinate",
            shape_list[2].server_id, 0, 400,
        ))

        # === Category 10: Cross-view edits (2 tests) ===
        if len(by_view) >= 2:
            views = sorted(by_view.keys())
            v1_shape = by_view[views[0]][0]
            v2_shape = by_view[views[1]][0]
            results.append(self.run_sequential_test(
                "TC10-crossview-2",
                f"Edit shapes on view {views[0]} then view {views[1]}",
                [
                    (v1_shape.server_id, 15, 15),
                    (v2_shape.server_id, -15, 10),
                ],
            ))
            if len(by_view) >= 3:
                v3_shape = by_view[views[2]][0]
                results.append(self.run_sequential_test(
                    "TC10-crossview-3",
                    f"Edit shapes across views {views[0]},{views[1]},{views[2]}",
                    [
                        (v1_shape.server_id, 10, 10),
                        (v2_shape.server_id, 20, 20),
                        (v3_shape.server_id, 30, 30),
                    ],
                ))

        return results


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run 50+ test cases for pre-annotation edit isolation")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", "-u", default="admin")
    parser.add_argument("--password", "-p", default="admin123")
    parser.add_argument("--job-id", type=int, default=None,
                        help="Job ID (auto-detected from test_task_info.json if not specified)")
    args = parser.parse_args()

    # Auto-detect job ID
    job_id = args.job_id
    if job_id is None:
        info_path = os.path.join(os.path.dirname(__file__), "test_task_info.json")
        if os.path.exists(info_path):
            with open(info_path) as f:
                info = json.load(f)
            job_id = info["job_id"]
            print(f"Auto-detected Job ID: {job_id} (from test_task_info.json)")
        else:
            print("ERROR: No --job-id specified and test_task_info.json not found")
            print("Run setup_test_task.py first")
            sys.exit(1)

    # Connect
    print(f"\nConnecting to {args.host}...")
    client = CVATClient(args.host, args.user, args.password)

    # Verify annotations exist
    shapes = client.get_annotations(job_id)
    print(f"Found {len(shapes)} shapes in job {job_id}")

    if len(shapes) < 5:
        print("ERROR: Need at least 5 shapes for testing")
        sys.exit(1)

    # Run tests
    runner = PreAnnotationTestRunner(client, job_id)
    print(f"\n{'='*70}")
    print(f"RUNNING PRE-ANNOTATION EDIT ISOLATION TESTS")
    print(f"{'='*70}\n")

    results = runner.generate_test_cases()

    # Print results
    passed = 0
    failed = 0
    print(f"\n{'='*70}")
    print(f"TEST RESULTS")
    print(f"{'='*70}\n")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name}: {r.description}")
        if r.error:
            # Indent error lines
            for line in r.error.split("\n"):
                print(f"          ERROR: {line}")
        if r.passed:
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*70}")
    print(f"SUMMARY: {passed} passed, {failed} failed, {len(results)} total")
    print(f"{'='*70}")

    if failed > 0:
        print(f"\n  {failed} test(s) FAILED - pre-annotation edit bug may still exist!")
        sys.exit(1)
    else:
        print(f"\n  All {passed} tests PASSED - pre-annotations are properly isolated!")
        sys.exit(0)


if __name__ == "__main__":
    main()
