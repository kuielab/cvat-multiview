#!/usr/bin/env python3
"""
Setup Test Task for Pre-Annotation Edit Bug Testing

Creates synthetic test videos with specific aspect ratios (to trigger the
coordinate transform path), uploads them as a multiview task, and inserts
pre-annotations at various frames and views.

The aspect ratio mismatch between video dimensions and task dimensions is
critical - this is what triggers the `cloneObjectStateForDisplay` code path.

Usage:
    python scripts/test/setup_test_task.py --user admin --password admin123
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import requests

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_HOST = "http://localhost:8080"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin123"

# Video config: Use non-standard aspect ratio to trigger coordinate transforms
# Task will store dimensions from first video; other views have different sizes
VIDEO_CONFIGS = {
    "view1": {"width": 640, "height": 480, "fps": 30, "frames": 300},  # 4:3
    "view2": {"width": 720, "height": 480, "fps": 30, "frames": 300},  # 3:2
    "view3": {"width": 640, "height": 360, "fps": 30, "frames": 300},  # 16:9
    "view4": {"width": 800, "height": 600, "fps": 30, "frames": 300},  # 4:3 larger
    "view5": {"width": 640, "height": 480, "fps": 30, "frames": 300},  # 4:3
}

# Pre-annotation layout: (frame, view_id, x, y, width, height, label)
# Spread across frames 0-299, views 1-5, various positions
PRE_ANNOTATIONS = [
    # View 1 - scattered across frames
    (0,   1, 100, 100, 80, 60, "Sound"),
    (10,  1, 200, 150, 80, 60, "Sound"),
    (50,  1, 300, 200, 100, 80, "Sound"),
    (100, 1, 150, 50,  80, 60, "Sound"),
    (150, 1, 400, 300, 80, 60, "Sound"),
    (200, 1, 50,  250, 80, 60, "Sound"),
    (250, 1, 250, 100, 80, 60, "Sound"),
    (299, 1, 350, 200, 80, 60, "Sound"),
    # View 2
    (0,   2, 100, 100, 80, 60, "Sound"),
    (10,  2, 200, 150, 80, 60, "Sound"),
    (50,  2, 300, 200, 100, 80, "Sound"),
    (100, 2, 150, 50,  80, 60, "Sound"),
    (200, 2, 50,  250, 80, 60, "Sound"),
    # View 3
    (0,   3, 100, 100, 80, 60, "Sound"),
    (50,  3, 200, 150, 80, 60, "Sound"),
    (100, 3, 300, 100, 80, 60, "Sound"),
    (200, 3, 150, 200, 80, 60, "Sound"),
    (299, 3, 400, 250, 80, 60, "Sound"),
    # View 4
    (0,   4, 100, 100, 80, 60, "Sound"),
    (100, 4, 200, 200, 80, 60, "Sound"),
    (200, 4, 300, 300, 80, 60, "Sound"),
    # View 5
    (0,   5, 100, 100, 80, 60, "Sound"),
    (50,  5, 200, 150, 80, 60, "Sound"),
    (100, 5, 300, 200, 80, 60, "Sound"),
    (150, 5, 150, 50,  80, 60, "Sound"),
    (200, 5, 400, 300, 80, 60, "Sound"),
    (250, 5, 250, 250, 80, 60, "Sound"),
    (299, 5, 50,  100, 80, 60, "Sound"),
    # Multiple annotations on SAME frame (critical test case for the bug)
    (7, 1, 50,  50,  80, 60, "Sound"),
    (7, 1, 200, 200, 80, 60, "Sound"),
    (7, 1, 400, 100, 80, 60, "Sound"),
    (7, 1, 100, 350, 80, 60, "Sound"),
    (7, 1, 300, 300, 80, 60, "Sound"),
    # Same frame, different views
    (25, 1, 100, 100, 80, 60, "Sound"),
    (25, 2, 100, 100, 80, 60, "Sound"),
    (25, 3, 100, 100, 80, 60, "Sound"),
    (25, 4, 100, 100, 80, 60, "Sound"),
    (25, 5, 100, 100, 80, 60, "Sound"),
    # Dense cluster on frame 75 view 1 (stress test)
    (75, 1, 50,  50,  60, 40, "Sound"),
    (75, 1, 130, 50,  60, 40, "Sound"),
    (75, 1, 210, 50,  60, 40, "Sound"),
    (75, 1, 290, 50,  60, 40, "Sound"),
    (75, 1, 370, 50,  60, 40, "Sound"),
    (75, 1, 50,  110, 60, 40, "Sound"),
    (75, 1, 130, 110, 60, 40, "Sound"),
    (75, 1, 210, 110, 60, 40, "Sound"),
    (75, 1, 290, 110, 60, 40, "Sound"),
    (75, 1, 370, 110, 60, 40, "Sound"),
]


def generate_test_video(output_path: str, width: int, height: int,
                        fps: int, frame_count: int) -> str:
    """Generate a synthetic test video with colored frames and frame numbers."""
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {output_path}")

    for i in range(frame_count):
        # Create frame with gradient background
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Color gradient based on frame number
        hue = int((i / frame_count) * 180)
        frame[:, :] = (hue, 100, 200)  # HSV-like coloring in BGR
        frame = cv2.cvtColor(frame, cv2.COLOR_HSV2BGR)

        # Add frame number text
        text = f"F:{i}"
        cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2)

        # Add resolution text
        res_text = f"{width}x{height}"
        cv2.putText(frame, res_text, (10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        writer.write(frame)

    writer.release()
    return output_path


def create_test_task(host: str, session: requests.Session,
                     video_dir: str) -> dict:
    """Create a multiview task with synthetic test videos."""
    print("\n[Step 2] Creating multiview task...")

    files = {}
    for i in range(1, 6):
        video_path = os.path.join(video_dir, f"view{i}.mp4")
        files[f"video_view{i}"] = (f"view{i}.mp4", open(video_path, "rb"),
                                    "video/mp4")

    data = {
        "name": "PreAnnotation-Edit-BugTest",
        "session_id": "test-bug",
        "part_number": "1",
        "view_count": "5",
    }

    resp = session.post(
        f"{host}/api/tasks/create_multiview",
        files=files,
        data=data,
        timeout=120,
    )

    # Close file handles
    for f in files.values():
        f[1].close()

    if resp.status_code != 201:
        print(f"  ERROR: {resp.status_code} - {resp.text}")
        sys.exit(1)

    task = resp.json()
    print(f"  Task ID: {task['id']}")
    print(f"  Name: {task['name']}")
    return task


def get_job_id(host: str, session: requests.Session, task_id: int) -> int:
    """Get the first job ID for a task."""
    resp = session.get(f"{host}/api/jobs", params={"task_id": task_id})
    resp.raise_for_status()
    jobs = resp.json()["results"]
    if not jobs:
        raise RuntimeError(f"No jobs found for task {task_id}")
    return jobs[0]["id"]


def get_label_id(host: str, session: requests.Session, task_id: int,
                 label_name: str) -> int:
    """Get label ID by name."""
    resp = session.get(f"{host}/api/labels",
                       params={"task_id": task_id})
    resp.raise_for_status()
    for label in resp.json()["results"]:
        if label["name"] == label_name:
            return label["id"]
    raise RuntimeError(f"Label '{label_name}' not found in task {task_id}")


def insert_pre_annotations(host: str, session: requests.Session,
                           job_id: int, label_id: int) -> int:
    """Insert pre-annotations as individual shapes."""
    print(f"\n[Step 3] Inserting {len(PRE_ANNOTATIONS)} pre-annotations...")

    shapes = []
    for frame, view_id, x, y, w, h, label_name in PRE_ANNOTATIONS:
        # CVAT stores rectangles as [x1, y1, x2, y2]
        shape = {
            "type": "rectangle",
            "frame": frame,
            "label_id": label_id,
            "occluded": False,
            "z_order": 0,
            "points": [x, y, x + w, y + h],
            "attributes": [],
            "source": "manual",
            "view_id": view_id,
        }
        shapes.append(shape)

    payload = {
        "shapes": shapes,
        "tracks": [],
        "tags": [],
    }

    resp = session.patch(
        f"{host}/api/jobs/{job_id}/annotations?action=create",
        json=payload,
        timeout=60,
    )

    if resp.status_code not in (200, 201):
        print(f"  ERROR: {resp.status_code} - {resp.text}")
        sys.exit(1)

    result = resp.json()
    inserted = len(result.get("shapes", []))
    print(f"  Inserted {inserted} shapes")
    return inserted


def verify_annotations(host: str, session: requests.Session,
                       job_id: int) -> dict:
    """Verify inserted annotations."""
    print("\n[Step 4] Verifying annotations...")

    resp = session.get(f"{host}/api/jobs/{job_id}/annotations")
    resp.raise_for_status()
    data = resp.json()

    shapes = data.get("shapes", [])
    print(f"  Total shapes in job: {len(shapes)}")

    # Group by frame and view
    by_frame = {}
    by_view = {}
    for s in shapes:
        f = s["frame"]
        v = s.get("view_id")
        by_frame.setdefault(f, []).append(s)
        by_view.setdefault(v, []).append(s)

    print(f"  Unique frames: {len(by_frame)}")
    print(f"  Views: {sorted(by_view.keys())}")

    # Show distribution
    for view_id in sorted(by_view.keys()):
        print(f"    View {view_id}: {len(by_view[view_id])} shapes")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Setup test task for pre-annotation edit bug testing")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", "-u", default=DEFAULT_USER)
    parser.add_argument("--password", "-p", default=DEFAULT_PASSWORD)
    parser.add_argument("--keep-videos", action="store_true",
                        help="Don't delete generated videos after upload")
    args = parser.parse_args()

    # Create session with auth
    session = requests.Session()
    session.headers.update({"Referer": args.host})

    # Login
    print("[Step 0] Logging in...")
    login_resp = session.post(
        f"{args.host}/api/auth/login",
        json={"username": args.user, "password": args.password},
    )
    if login_resp.status_code != 200:
        print(f"  Login failed: {login_resp.status_code} - {login_resp.text}")
        sys.exit(1)

    token = login_resp.json().get("key")
    session.headers.update({"Authorization": f"Token {token}"})
    print(f"  Logged in as {args.user}")

    # Generate synthetic test videos
    print("\n[Step 1] Generating synthetic test videos...")
    video_dir = tempfile.mkdtemp(prefix="cvat_test_videos_")

    for view_name, config in VIDEO_CONFIGS.items():
        output_path = os.path.join(video_dir, f"{view_name}.mp4")
        generate_test_video(
            output_path,
            config["width"],
            config["height"],
            config["fps"],
            config["frames"],
        )
        print(f"  Generated {view_name}: {config['width']}x{config['height']}"
              f" @ {config['fps']}fps, {config['frames']} frames")

    # Create multiview task
    task = create_test_task(args.host, session, video_dir)
    task_id = task["id"]

    # Get job and label IDs
    job_id = get_job_id(args.host, session, task_id)
    label_id = get_label_id(args.host, session, task_id, "Sound")
    print(f"  Job ID: {job_id}, Label ID: {label_id}")

    # Insert pre-annotations
    insert_pre_annotations(args.host, session, job_id, label_id)

    # Verify
    verify_annotations(args.host, session, job_id)

    # Cleanup videos
    if not args.keep_videos:
        import shutil
        shutil.rmtree(video_dir)
        print(f"\n  Cleaned up temp videos: {video_dir}")

    # Output summary
    print(f"\n{'='*60}")
    print(f"TEST TASK READY")
    print(f"{'='*60}")
    print(f"  Task ID:  {task_id}")
    print(f"  Job ID:   {job_id}")
    print(f"  URL:      {args.host}/tasks/{task_id}/jobs/{job_id}")
    print(f"  Shapes:   {len(PRE_ANNOTATIONS)}")
    print(f"  Frames:   0-299")
    print(f"  Views:    1-5")
    print(f"{'='*60}")

    # Write task info to file for test runner
    info_path = os.path.join(os.path.dirname(__file__), "test_task_info.json")
    with open(info_path, "w") as f:
        json.dump({
            "task_id": task_id,
            "job_id": job_id,
            "label_id": label_id,
            "url": f"{args.host}/tasks/{task_id}/jobs/{job_id}",
            "host": args.host,
            "annotations": [
                {
                    "frame": frame,
                    "view_id": view_id,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "label": label,
                }
                for frame, view_id, x, y, w, h, label in PRE_ANNOTATIONS
            ],
        }, f, indent=2)
    print(f"\n  Task info saved to: {info_path}")


if __name__ == "__main__":
    main()
