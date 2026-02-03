#!/usr/bin/env python3
"""
Insert Bbox Annotations from all_labels.json

Reads pre-labeled data and inserts bbox annotations at start, middle, and end
times of each labeled segment into corresponding CVAT tasks.

데이터셋별 파일 형식:
    - multisensor_home1/2: all_labels.json (시간 단위: 초)
    - mmoffice: label/testlabel/recidXXX.csv (시간 단위: 프레임)

사용법:
    # Dry-run으로 미리보기
    python insert_bbox_annotations.py \\
        --user admin --password admin123 \\
        --data-dir /path/to/dataset \\
        --datasets multisensor_home1 \\
        --dry-run --limit 5

    # 실제 삽입
    python insert_bbox_annotations.py \\
        --user admin --password admin123 \\
        --data-dir /path/to/dataset \\
        --datasets multisensor_home1 multisensor_home2 mmoffice \\
        --fps 30 --bbox-size 100 --divisions 3
"""

import argparse
import csv
import getpass
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_HOST = "http://localhost:8080"
DEFAULT_FPS = 30
DEFAULT_BBOX_SIZE = 100
DEFAULT_DIVISIONS = 3
DEFAULT_VIEW_COUNT = 5
DEFAULT_DATASETS = ["multisensor_home1", "multisensor_home2", "mmoffice"]
DEFAULT_LABEL_NAME = "Sound"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Segment:
    """A labeled segment with start/end times"""
    start: float  # seconds (multisensor) or frames (mmoffice)
    end: float
    labels: List[str]
    is_frame_based: bool = False  # True if start/end are frame numbers


@dataclass
class LabelEntry:
    """A single entry from all_labels.json or CSV"""
    task_name: str
    segments: List[Segment]


@dataclass
class BboxShape:
    """A single bbox shape to insert"""
    frame: int
    points: List[float]  # [x1, y1, x2, y2]


# ============================================================================
# Authentication
# ============================================================================

def get_auth_session(host: str, username: str, password: str) -> Optional[requests.Session]:
    """Session-based authentication"""
    session = requests.Session()

    try:
        # Get CSRF token
        session.get(f"{host}/api/auth/login", timeout=30)
        csrf_token = session.cookies.get('csrftoken')

        # Login
        login_data = {"username": username, "password": password}
        headers = {}
        if csrf_token:
            headers['X-CSRFToken'] = csrf_token

        response = session.post(
            f"{host}/api/auth/login",
            json=login_data,
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            print(f"[OK] Logged in as {username}")
            return session
        else:
            print(f"[ERROR] Login failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"[ERROR] Login error: {e}")
        return None


def get_headers(session: requests.Session, org: Optional[str] = None) -> Dict[str, str]:
    """Get request headers with CSRF token and optional org"""
    headers = {}
    csrf_token = session.cookies.get('csrftoken')
    if csrf_token:
        headers['X-CSRFToken'] = csrf_token
    if org:
        headers['X-Organization'] = org
    return headers


# ============================================================================
# Frame Calculation
# ============================================================================

def calculate_frame_positions(
    start: float,
    end: float,
    divisions: int,
    fps: float,
    is_frame_based: bool = False
) -> List[int]:
    """
    Calculate frame positions for bbox insertion.

    Args:
        start: Start time (seconds) or frame number
        end: End time (seconds) or frame number
        divisions: Number of positions (2=start/end, 3=start/mid/end, etc.)
                   Values < 2 are clamped to 2.
        fps: Frames per second
        is_frame_based: If True, start/end are already frame numbers

    Returns:
        List of frame numbers
    """
    divisions = max(2, divisions)  # Ensure at least 2 divisions

    if is_frame_based:
        start_frame = int(start)
        end_frame = int(end)
    else:
        start_frame = round(start * fps)
        end_frame = round(end * fps)

    if start_frame == end_frame:
        return [start_frame]

    frames = []
    for i in range(divisions):
        ratio = i / (divisions - 1)  # 0.0 ~ 1.0
        frame = start_frame + round((end_frame - start_frame) * ratio)
        frames.append(frame)

    return frames


def create_centered_bbox(
    cx: float,
    cy: float,
    size: int
) -> List[float]:
    """Create a centered bbox with given size"""
    half = size / 2
    return [cx - half, cy - half, cx + half, cy + half]


# ============================================================================
# Multisensor JSON Parsing
# ============================================================================

def parse_multisensor_json(
    json_path: Path,
    dataset_name: str
) -> List[LabelEntry]:
    """
    Parse all_labels.json for multisensor datasets.

    Structure:
    [
        {
            "video_url_1": "01/00-View1-Part1.mp4",
            ...
            "tricks": [
                {"start": 3.24, "end": 6.13, "labels": ["Sitdown"]},
                ...
            ]
        },
        ...
    ]

    Task name pattern: {dataset}_{subdir}-{session_id}-Part{part}
    """
    entries = []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] Invalid JSON in {json_path}: {e}")
        return entries
    except IOError as e:
        print(f"  [ERROR] Cannot read {json_path}: {e}")
        return entries

    if not isinstance(data, list):
        print(f"  [ERROR] Expected list in {json_path}, got {type(data).__name__}")
        return entries

    # Pattern to parse video_url: "01/00-View1-Part1.mp4"
    # Groups: (1)subdir, (2)session_id, (3)view_num, (4)part
    pattern = re.compile(r'^(\d+)/(\d+)-View(\d+)-Part(\d+)\.mp4$', re.IGNORECASE)

    for item in data:
        video_url = item.get('video_url_1', '')
        tricks = item.get('tricks', [])

        if not video_url or not tricks:
            continue

        match = pattern.match(video_url)
        if not match:
            continue

        subdir = match.group(1)
        session_id = match.group(2)
        part = match.group(4)

        task_name = f"{dataset_name}_{subdir}-{session_id}-Part{part}"

        segments = []
        for trick in tricks:
            try:
                start = float(trick.get('start', 0))
                end = float(trick.get('end', 0))
            except (TypeError, ValueError):
                continue
            labels = trick.get('labels', [])

            if start < end and labels:
                segments.append(Segment(
                    start=start,
                    end=end,
                    labels=labels,
                    is_frame_based=False
                ))

        if segments:
            entries.append(LabelEntry(task_name=task_name, segments=segments))

    return entries


# ============================================================================
# MMOffice CSV Parsing
# ============================================================================

def parse_mmoffice_csv(
    csv_path: Path,
    tasks: List[Dict]
) -> List[LabelEntry]:
    """
    Parse recidXXX.csv files for mmoffice dataset.

    CSV Structure:
        index,eventclass,starttime,endtime
        0,8,6,14
        1,11,20,35

    Note: starttime and endtime are FRAME numbers, not seconds.

    Args:
        csv_path: Path to the CSV file
        tasks: List of task dictionaries from CVAT API

    Returns:
        List of LabelEntry objects for matching tasks
    """
    entries = []

    # Extract recid from filename: recid008.csv -> "008"
    filename = csv_path.stem
    match = re.match(r'^recid(\d+)$', filename, re.IGNORECASE)
    if not match:
        return entries

    recid = match.group(1)

    # Find all tasks containing this recid
    matching_tasks = []
    for task in tasks:
        task_name = task.get('name', '')
        # Task name pattern: mmoffice_{split}_split{split_id}_s{session}_recid{recid}...
        if f'recid{recid}' in task_name:
            matching_tasks.append(task_name)

    if not matching_tasks:
        return entries

    # Parse CSV
    segments = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                start_frame = int(row.get('starttime', 0))
                end_frame = int(row.get('endtime', 0))
                event_class = row.get('eventclass', '')

                if start_frame < end_frame:
                    segments.append(Segment(
                        start=float(start_frame),
                        end=float(end_frame),
                        labels=[f"class_{event_class}"],
                        is_frame_based=True
                    ))
            except (ValueError, TypeError):
                continue

    # Create entry for each matching task
    for task_name in matching_tasks:
        if segments:
            entries.append(LabelEntry(task_name=task_name, segments=segments.copy()))

    return entries


# ============================================================================
# CVAT API Functions
# ============================================================================

def find_task_by_name(
    host: str,
    session: requests.Session,
    task_name: str,
    org: Optional[str] = None
) -> Optional[Dict]:
    """Find a task by exact name"""
    headers = get_headers(session, org)

    try:
        response = session.get(
            f"{host}/api/tasks",
            params={"name": task_name, "page_size": 10},
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])

            # Find exact match
            for task in results:
                if task.get('name') == task_name:
                    return task

        return None
    except Exception as e:
        print(f"    [ERROR] Find task: {e}")
        return None


def get_task_jobs(
    host: str,
    session: requests.Session,
    task_id: int,
    org: Optional[str] = None
) -> List[Dict]:
    """Get jobs for a task"""
    headers = get_headers(session, org)

    try:
        response = session.get(
            f"{host}/api/jobs",
            params={"task_id": task_id},
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return data.get('results', [])

        return []
    except Exception as e:
        print(f"    [ERROR] Get jobs: {e}")
        return []


def get_task_data_meta(
    host: str,
    session: requests.Session,
    task_id: int,
    org: Optional[str] = None
) -> Optional[Dict]:
    """Get task data metadata (dimensions, FPS, etc.)"""
    headers = get_headers(session, org)

    try:
        response = session.get(
            f"{host}/api/tasks/{task_id}/data/meta",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()

        return None
    except Exception as e:
        print(f"    [ERROR] Get meta: {e}")
        return None


def get_task_labels(
    host: str,
    session: requests.Session,
    task_id: int,
    org: Optional[str] = None
) -> List[Dict]:
    """Get labels for a task"""
    headers = get_headers(session, org)

    try:
        response = session.get(
            f"{host}/api/labels",
            params={"task_id": task_id},
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return data.get('results', [])

        return []
    except Exception as e:
        print(f"    [ERROR] Get labels: {e}")
        return []


def find_label_id(
    labels: List[Dict],
    label_name: str
) -> Optional[int]:
    """Find label ID by name"""
    for label in labels:
        if label.get('name') == label_name:
            return label.get('id')
    return None


def insert_annotations(
    host: str,
    session: requests.Session,
    job_id: int,
    shapes: List[Dict],
    org: Optional[str] = None
) -> bool:
    """Insert annotations into a job"""
    headers = get_headers(session, org)
    headers['Content-Type'] = 'application/json'

    payload = {
        "version": 0,
        "tags": [],
        "shapes": shapes,
        "tracks": []
    }

    try:
        response = session.patch(
            f"{host}/api/jobs/{job_id}/annotations",
            params={"action": "create"},
            json=payload,
            headers=headers,
            timeout=60
        )

        if response.status_code in [200, 201]:
            return True
        else:
            print(f"    [ERROR] Insert annotations: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        print(f"    [ERROR] Insert annotations: {e}")
        return False


def get_all_tasks(
    host: str,
    session: requests.Session,
    org: Optional[str] = None,
    name_contains: Optional[str] = None
) -> List[Dict]:
    """Get all tasks, optionally filtered by name pattern"""
    headers = get_headers(session, org)
    all_tasks = []
    page = 1
    page_size = 100

    while True:
        params = {"page": page, "page_size": page_size}
        if name_contains:
            params["search"] = name_contains

        try:
            response = session.get(
                f"{host}/api/tasks",
                params=params,
                headers=headers,
                timeout=60
            )

            if response.status_code != 200:
                break

            data = response.json()
            results = data.get('results', [])
            all_tasks.extend(results)

            if not data.get('next'):
                break

            page += 1
        except Exception as e:
            print(f"[ERROR] Get all tasks: {e}")
            break

    return all_tasks


# ============================================================================
# Main Processing
# ============================================================================

def process_multisensor_dataset(
    host: str,
    session: requests.Session,
    data_dir: Path,
    dataset_name: str,
    fps: float,
    bbox_size: int,
    divisions: int,
    view_count: int,
    label_name: str,
    org: Optional[str],
    dry_run: bool,
    limit: Optional[int]
) -> Tuple[int, int, int]:
    """
    Process a multisensor dataset.

    Returns:
        (tasks_processed, shapes_created, tasks_skipped)
    """
    json_path = data_dir / dataset_name / "all_labels.json"

    if not json_path.exists():
        print(f"  [SKIP] all_labels.json not found: {json_path}")
        return (0, 0, 0)

    print(f"  Loading all_labels.json...")
    entries = parse_multisensor_json(json_path, dataset_name)
    print(f"  Found {len(entries)} entries")

    if limit and len(entries) > limit:
        entries = entries[:limit]
        print(f"  Limited to {limit} entries")

    tasks_processed = 0
    shapes_created = 0
    tasks_skipped = 0

    for i, entry in enumerate(entries, 1):
        print(f"\n  [{i}/{len(entries)}] {entry.task_name}")

        # Find task
        task = find_task_by_name(host, session, entry.task_name, org)
        if not task:
            print(f"    [SKIP] Task not found")
            tasks_skipped += 1
            continue

        task_id = task['id']
        print(f"    Task ID: {task_id}")

        # Get job
        jobs = get_task_jobs(host, session, task_id, org)
        if not jobs:
            print(f"    [SKIP] No jobs found")
            tasks_skipped += 1
            continue

        job_id = jobs[0]['id']
        job_stop_frame = jobs[0].get('stop_frame', 0)
        print(f"    Job ID: {job_id}, Frames: 0-{job_stop_frame}")

        # Get dimensions
        meta = get_task_data_meta(host, session, task_id, org)
        if not meta:
            print(f"    [SKIP] Could not get metadata")
            tasks_skipped += 1
            continue

        # Get frame dimensions from first frame
        frames = meta.get('frames', [])
        if frames:
            width = frames[0].get('width', 1920)
            height = frames[0].get('height', 1080)
        else:
            width, height = 1920, 1080

        cx, cy = width / 2, height / 2
        print(f"    Dimensions: {width}x{height}")

        # Get label
        labels = get_task_labels(host, session, task_id, org)
        label_id = find_label_id(labels, label_name)

        if not label_id:
            print(f"    [SKIP] Label '{label_name}' not found")
            tasks_skipped += 1
            continue

        print(f"    Label ID: {label_id}")

        # Build shapes (one per view per frame)
        shapes = []
        seen_frames: Set[int] = set()

        for segment in entry.segments:
            frame_positions = calculate_frame_positions(
                segment.start,
                segment.end,
                divisions,
                fps,
                segment.is_frame_based
            )

            for frame in frame_positions:
                # Clamp frame to job range
                frame = max(0, min(frame, job_stop_frame))

                if frame not in seen_frames:
                    seen_frames.add(frame)
                    bbox = create_centered_bbox(cx, cy, bbox_size)
                    # Create one shape for each view
                    for view_id in range(view_count):
                        shapes.append({
                            "type": "rectangle",
                            "frame": frame,
                            "label_id": label_id,
                            "points": bbox,
                            "occluded": False,
                            "z_order": 0,
                            "rotation": 0.0,
                            "view_id": view_id,
                            "attributes": []
                        })

        print(f"    Segments: {len(entry.segments)} → {len(shapes)} shapes ({len(seen_frames)} frames × {view_count} views)")
        print(f"    Frames: {sorted(seen_frames)[:10]}{'...' if len(seen_frames) > 10 else ''}")

        if dry_run:
            print(f"    [DRY RUN] Would create {len(shapes)} shapes")
            shapes_created += len(shapes)
        else:
            if shapes:
                success = insert_annotations(host, session, job_id, shapes, org)
                if success:
                    print(f"    [OK] Created {len(shapes)} shapes")
                    shapes_created += len(shapes)
                else:
                    tasks_skipped += 1
                    continue

        tasks_processed += 1

    return (tasks_processed, shapes_created, tasks_skipped)


def process_mmoffice_dataset(
    host: str,
    session: requests.Session,
    data_dir: Path,
    fps: float,
    bbox_size: int,
    divisions: int,
    view_count: int,
    label_name: str,
    org: Optional[str],
    dry_run: bool,
    limit: Optional[int]
) -> Tuple[int, int, int]:
    """
    Process mmoffice dataset.

    Returns:
        (tasks_processed, shapes_created, tasks_skipped)
    """
    label_dir = data_dir / "mmoffice" / "label" / "testlabel"

    if not label_dir.exists():
        print(f"  [SKIP] Label directory not found: {label_dir}")
        return (0, 0, 0)

    # Get all mmoffice tasks
    print(f"  Loading mmoffice tasks from CVAT...")
    all_tasks = get_all_tasks(host, session, org, "mmoffice")
    print(f"  Found {len(all_tasks)} mmoffice tasks")

    # Find CSV files
    csv_files = sorted(label_dir.glob("recid*.csv"))
    csv_files = [f for f in csv_files if 'checkpoint' not in str(f)]
    print(f"  Found {len(csv_files)} CSV files")

    if limit and len(csv_files) > limit:
        csv_files = csv_files[:limit]
        print(f"  Limited to {limit} CSV files")

    tasks_processed = 0
    shapes_created = 0
    tasks_skipped = 0

    for i, csv_path in enumerate(csv_files, 1):
        print(f"\n  [{i}/{len(csv_files)}] {csv_path.name}")

        entries = parse_mmoffice_csv(csv_path, all_tasks)

        if not entries:
            print(f"    [SKIP] No matching tasks")
            tasks_skipped += 1
            continue

        for entry in entries:
            print(f"    Processing: {entry.task_name}")

            # Find task
            task = find_task_by_name(host, session, entry.task_name, org)
            if not task:
                print(f"      [SKIP] Task not found")
                tasks_skipped += 1
                continue

            task_id = task['id']

            # Get job
            jobs = get_task_jobs(host, session, task_id, org)
            if not jobs:
                print(f"      [SKIP] No jobs found")
                tasks_skipped += 1
                continue

            job_id = jobs[0]['id']
            job_stop_frame = jobs[0].get('stop_frame', 0)

            # Get dimensions
            meta = get_task_data_meta(host, session, task_id, org)
            if not meta:
                print(f"      [SKIP] Could not get metadata")
                tasks_skipped += 1
                continue

            frames = meta.get('frames', [])
            if frames:
                width = frames[0].get('width', 1920)
                height = frames[0].get('height', 1080)
            else:
                width, height = 1920, 1080

            cx, cy = width / 2, height / 2

            # Get label
            labels = get_task_labels(host, session, task_id, org)
            label_id = find_label_id(labels, label_name)

            if not label_id:
                print(f"      [SKIP] Label '{label_name}' not found")
                tasks_skipped += 1
                continue

            # Build shapes (one per view per frame)
            shapes = []
            seen_frames: Set[int] = set()

            for segment in entry.segments:
                frame_positions = calculate_frame_positions(
                    segment.start,
                    segment.end,
                    divisions,
                    fps,
                    segment.is_frame_based
                )

                for frame in frame_positions:
                    frame = max(0, min(frame, job_stop_frame))

                    if frame not in seen_frames:
                        seen_frames.add(frame)
                        bbox = create_centered_bbox(cx, cy, bbox_size)
                        # Create one shape for each view
                        for view_id in range(view_count):
                            shapes.append({
                                "type": "rectangle",
                                "frame": frame,
                                "label_id": label_id,
                                "points": bbox,
                                "occluded": False,
                                "z_order": 0,
                                "rotation": 0.0,
                                "view_id": view_id,
                                "attributes": []
                            })

            print(f"      Segments: {len(entry.segments)} → {len(shapes)} shapes ({len(seen_frames)} frames × {view_count} views)")

            if dry_run:
                print(f"      [DRY RUN] Would create {len(shapes)} shapes")
                shapes_created += len(shapes)
            else:
                if shapes:
                    success = insert_annotations(host, session, job_id, shapes, org)
                    if success:
                        print(f"      [OK] Created {len(shapes)} shapes")
                        shapes_created += len(shapes)
                    else:
                        tasks_skipped += 1
                        continue

            tasks_processed += 1

    return (tasks_processed, shapes_created, tasks_skipped)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Insert bbox annotations from all_labels.json into CVAT tasks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run test
  python insert_bbox_annotations.py \\
      --user admin --password admin123 \\
      --data-dir /path/to/dataset \\
      --datasets multisensor_home1 \\
      --dry-run --limit 5

  # Single task test
  python insert_bbox_annotations.py \\
      --user admin --password admin123 \\
      --data-dir /path/to/dataset \\
      --datasets multisensor_home1 \\
      --limit 1

  # Full run with 5 divisions (0%, 25%, 50%, 75%, 100%)
  python insert_bbox_annotations.py \\
      --user admin --password admin123 \\
      --data-dir /path/to/dataset \\
      --datasets multisensor_home1 multisensor_home2 \\
      --divisions 5

  # MMOffice dataset
  python insert_bbox_annotations.py \\
      --user admin --password admin123 \\
      --data-dir /path/to/dataset \\
      --datasets mmoffice
        """
    )

    # Authentication
    parser.add_argument('--user', '-u', required=True, help='CVAT username')
    parser.add_argument('--password', '-p',
                        help='CVAT password (or set CVAT_PASSWORD env var)')
    parser.add_argument('--host', default=DEFAULT_HOST,
                        help=f'CVAT host (default: {DEFAULT_HOST})')
    parser.add_argument('--org', help='Organization slug')

    # Data paths
    parser.add_argument('--data-dir', '-d', required=True,
                        help='Dataset root path')
    parser.add_argument('--datasets', nargs='+', default=DEFAULT_DATASETS,
                        help=f'Datasets to process (default: {" ".join(DEFAULT_DATASETS)})')

    # Annotation settings
    parser.add_argument('--fps', type=float, default=DEFAULT_FPS,
                        help=f'Video FPS for time→frame conversion (default: {DEFAULT_FPS})')
    parser.add_argument('--bbox-size', type=int, default=DEFAULT_BBOX_SIZE,
                        help=f'Bbox width/height in pixels (default: {DEFAULT_BBOX_SIZE})')
    parser.add_argument('--divisions', type=int, default=DEFAULT_DIVISIONS,
                        help=f'Bbox count per segment (2=start/end, 3=start/mid/end, etc.) (default: {DEFAULT_DIVISIONS})')
    parser.add_argument('--view-count', type=int, default=DEFAULT_VIEW_COUNT,
                        help=f'Number of views to create shapes for (default: {DEFAULT_VIEW_COUNT})')
    parser.add_argument('--label', default=DEFAULT_LABEL_NAME,
                        help=f'Label name to use (default: {DEFAULT_LABEL_NAME})')

    # Options
    parser.add_argument('--limit', type=int,
                        help='Limit number of tasks/files to process')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without creating annotations')

    args = parser.parse_args()

    # Get password from arg, env var, or prompt
    password = args.password or os.environ.get('CVAT_PASSWORD')
    if not password:
        password = getpass.getpass('CVAT password: ')

    # Validate data directory
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    # Print header
    print("=" * 60)
    print("  Insert Bbox Annotations from all_labels.json")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"Data directory: {data_dir}")
    print(f"Datasets: {', '.join(args.datasets)}")
    print(f"FPS: {args.fps}")
    print(f"Bbox size: {args.bbox_size}x{args.bbox_size}")
    print(f"Divisions: {args.divisions}")
    print(f"View count: {args.view_count}")
    print(f"Label: {args.label}")
    if args.dry_run:
        print("[DRY RUN MODE]")
    print("=" * 60)

    # Authenticate
    print(f"\nConnecting to {args.host}...")
    session = get_auth_session(args.host, args.user, password)
    if not session:
        print("Authentication failed!")
        sys.exit(1)

    # Process each dataset
    total_tasks = 0
    total_shapes = 0
    total_skipped = 0

    for dataset in args.datasets:
        print(f"\n{'=' * 60}")
        print(f"Processing: {dataset}")
        print("=" * 60)

        if dataset.startswith("multisensor"):
            tasks, shapes, skipped = process_multisensor_dataset(
                host=args.host,
                session=session,
                data_dir=data_dir,
                dataset_name=dataset,
                fps=args.fps,
                bbox_size=args.bbox_size,
                divisions=args.divisions,
                view_count=args.view_count,
                label_name=args.label,
                org=args.org,
                dry_run=args.dry_run,
                limit=args.limit
            )
        elif dataset == "mmoffice":
            tasks, shapes, skipped = process_mmoffice_dataset(
                host=args.host,
                session=session,
                data_dir=data_dir,
                fps=args.fps,
                bbox_size=args.bbox_size,
                divisions=args.divisions,
                view_count=args.view_count,
                label_name=args.label,
                org=args.org,
                dry_run=args.dry_run,
                limit=args.limit
            )
        else:
            print(f"  [SKIP] Unknown dataset type: {dataset}")
            continue

        total_tasks += tasks
        total_shapes += shapes
        total_skipped += skipped

        print(f"\n  Dataset summary: {tasks} tasks, {shapes} shapes, {skipped} skipped")

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"FINAL SUMMARY")
    print("=" * 60)
    print(f"Tasks processed: {total_tasks}")
    print(f"Shapes created: {total_shapes}")
    print(f"Tasks skipped: {total_skipped}")
    if args.dry_run:
        print("\n[DRY RUN] No annotations were actually created.")
    print("=" * 60)

    # Exit code: 0 if any work was done successfully, 1 only if complete failure
    # Skipped tasks are expected (e.g., mmoffice_train has no labels)
    if total_tasks == 0 and total_skipped > 0:
        # All tasks were skipped - this might indicate a problem
        print("\n[WARNING] All tasks were skipped. Check dataset paths and task names.")
        sys.exit(1)
    elif total_tasks == 0 and total_skipped == 0:
        # No tasks found at all
        print("\n[WARNING] No tasks found to process.")
        sys.exit(1)
    else:
        # Some work was done successfully
        sys.exit(0)


if __name__ == '__main__':
    main()
