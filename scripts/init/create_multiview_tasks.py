#!/usr/bin/env python3
"""
Create Multiview Tasks - Batch Script

Multiview task를 배치로 생성하는 스크립트입니다.
파일 명명 규칙: [n]-View[x]-Part[y].mp4
- n: 세션 ID (예: 100, 101, 102)
- x: 뷰 번호 (1-5)
- y: 파트 번호 (1, 2, ...)

사용법:
    # 단일 task 생성
    python create_multiview_tasks.py --user admin --password admin123 \\
        --session-id 100 --part 1 --data-dir C:/path/to/videos

    # 배치 생성 (여러 세션)
    python create_multiview_tasks.py --user admin --password admin123 \\
        --session-ids 100 101 102 --parts 1 2 --data-dir C:/path/to/videos

    # 디렉토리의 모든 세트 자동 탐지
    python create_multiview_tasks.py --user admin --password admin123 \\
        --data-dir C:/path/to/videos --auto-detect

전제 조건:
    1. CVAT 서버가 실행 중이어야 함 (http://localhost:8080)
    2. 비디오 파일이 명명 규칙에 맞게 준비되어 있어야 함
"""

import argparse
import requests
import os
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional, Set
from dataclasses import dataclass


# 기본 설정
DEFAULT_HOST = "http://localhost:8080"
DEFAULT_VIEW_COUNT = 5


@dataclass
class VideoSet:
    """비디오 세트 정보"""
    session_id: str  # 예: "100"
    part: int        # 예: 1
    views: List[Path]  # View1부터 View5까지의 파일 경로


def get_session_token(host: str, username: str, password: str) -> Optional[str]:
    """
    사용자명/비밀번호로 세션 토큰 획득
    """
    try:
        response = requests.post(
            f"{host}/api/auth/login",
            json={"username": username, "password": password},
            timeout=30
        )
        if response.status_code == 200:
            return response.cookies.get('sessionid') or response.cookies.get('csrftoken')
        else:
            print(f"Login failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Login error: {e}")
        return None


def get_auth_session(host: str, username: str, password: str) -> Optional[requests.Session]:
    """
    세션 기반 인증 (로그인 후 세션 쿠키 사용)
    """
    session = requests.Session()

    try:
        # CSRF 토큰 획득
        csrf_response = session.get(f"{host}/api/auth/login", timeout=30)
        csrf_token = session.cookies.get('csrftoken')

        # 로그인
        login_data = {
            "username": username,
            "password": password
        }
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


def discover_video_sets(data_dir: Path, view_count: int = DEFAULT_VIEW_COUNT) -> List[VideoSet]:
    """
    디렉토리에서 비디오 세트 자동 탐지

    파일 명명 규칙: [n]-View[x]-Part[y].mp4
    """
    video_sets = []
    pattern = re.compile(r'^(\d+)-View(\d+)-Part(\d+)\.mp4$', re.IGNORECASE)

    # 모든 mp4 파일 스캔
    all_files = list(data_dir.glob("*.mp4"))

    # (session_id, part) 조합 추출
    combinations: Set[Tuple[str, int]] = set()
    for f in all_files:
        match = pattern.match(f.name)
        if match:
            session_id = match.group(1)
            part = int(match.group(3))
            combinations.add((session_id, part))

    # 각 조합에 대해 VideoSet 생성
    for session_id, part in sorted(combinations):
        views = []
        valid = True

        for view_num in range(1, view_count + 1):
            filename = f"{session_id}-View{view_num}-Part{part}.mp4"
            filepath = data_dir / filename

            if filepath.exists():
                views.append(filepath)
            else:
                print(f"  Warning: Missing {filename}")
                valid = False
                break

        if valid and len(views) == view_count:
            video_sets.append(VideoSet(
                session_id=session_id,
                part=part,
                views=views
            ))

    return video_sets


def create_multiview_task(
    host: str,
    session: requests.Session,
    task_name: str,
    video_set: VideoSet,
    labels: List[dict] = None
) -> Optional[dict]:
    """
    Multiview task 생성
    """
    api_url = f"{host}/api/tasks/create_multiview"

    # 기본 라벨
    if labels is None:
        labels = [{"name": "object", "attributes": [], "type": "any"}]

    print(f"\n{'='*60}")
    print(f"Creating Task: {task_name}")
    print(f"{'='*60}")
    print(f"Session ID: {video_set.session_id}")
    print(f"Part: {video_set.part}")
    print(f"Views: {len(video_set.views)}")
    for i, v in enumerate(video_set.views, 1):
        print(f"  View{i}: {v.name}")
    print(f"{'='*60}")

    try:
        # 파일 열기
        files = {}
        for i, view_path in enumerate(video_set.views, 1):
            files[f'video_view{i}'] = (view_path.name, open(view_path, 'rb'), 'video/mp4')

        # FormData
        data = {
            'name': task_name,
            'session_id': video_set.session_id,
            'part_number': str(video_set.part),
        }

        # CSRF 토큰 추가
        headers = {}
        csrf_token = session.cookies.get('csrftoken')
        if csrf_token:
            headers['X-CSRFToken'] = csrf_token

        print("Sending request...")
        response = session.post(
            api_url,
            files=files,
            data=data,
            headers=headers,
            timeout=600  # 10분 타임아웃
        )

        # 파일 닫기
        for key in files:
            files[key][1].close()

        if response.status_code == 201:
            task = response.json()
            print(f"\n[OK] Task created successfully!")
            print(f"  ID: {task.get('id')}")
            print(f"  URL: {host}/tasks/{task.get('id')}")
            return task
        else:
            print(f"\n[ERROR] Failed to create task")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.text[:500]}")
            return None

    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Create multiview tasks in CVAT (batch supported)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 단일 task 생성
  python create_multiview_tasks.py --user admin --password admin123 \\
      --session-id 100 --part 1 --data-dir ./videos

  # 여러 세션/파트 생성
  python create_multiview_tasks.py --user admin --password admin123 \\
      --session-ids 100 101 --parts 1 2 --data-dir ./videos

  # 자동 탐지 모드
  python create_multiview_tasks.py --user admin --password admin123 \\
      --data-dir ./videos --auto-detect

  # 생성할 task 수 제한
  python create_multiview_tasks.py --user admin --password admin123 \\
      --data-dir ./videos --auto-detect --limit 3
        """
    )

    # 인증
    parser.add_argument('--user', '-u', required=True, help='CVAT username')
    parser.add_argument('--password', '-p', required=True, help='CVAT password')
    parser.add_argument('--host', default=DEFAULT_HOST, help=f'CVAT host (default: {DEFAULT_HOST})')

    # 데이터
    parser.add_argument('--data-dir', '-d', required=True, help='Directory containing video files')
    parser.add_argument('--view-count', type=int, default=DEFAULT_VIEW_COUNT,
                        help=f'Number of views per set (default: {DEFAULT_VIEW_COUNT})')

    # 세션/파트 지정 모드
    parser.add_argument('--session-id', help='Single session ID (e.g., 100)')
    parser.add_argument('--session-ids', nargs='+', help='Multiple session IDs (e.g., 100 101 102)')
    parser.add_argument('--part', type=int, help='Single part number (e.g., 1)')
    parser.add_argument('--parts', nargs='+', type=int, help='Multiple part numbers (e.g., 1 2)')

    # 자동 탐지 모드
    parser.add_argument('--auto-detect', action='store_true',
                        help='Auto-detect all video sets in directory')
    parser.add_argument('--limit', type=int, help='Limit number of tasks to create')

    # Task 설정
    parser.add_argument('--name-prefix', default='Multiview', help='Task name prefix')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be created without actually creating')

    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    # 비디오 세트 결정
    video_sets: List[VideoSet] = []

    if args.auto_detect:
        print(f"Auto-detecting video sets in {data_dir}...")
        video_sets = discover_video_sets(data_dir, args.view_count)
        print(f"Found {len(video_sets)} complete video sets")
    else:
        # 수동 지정 모드
        session_ids = args.session_ids or ([args.session_id] if args.session_id else [])
        parts = args.parts or ([args.part] if args.part else [])

        if not session_ids or not parts:
            print("Error: Specify --session-id/--session-ids and --part/--parts, or use --auto-detect")
            sys.exit(1)

        for sid in session_ids:
            for part in parts:
                views = []
                valid = True
                for view_num in range(1, args.view_count + 1):
                    filename = f"{sid}-View{view_num}-Part{part}.mp4"
                    filepath = data_dir / filename
                    if filepath.exists():
                        views.append(filepath)
                    else:
                        print(f"Warning: Missing {filename}")
                        valid = False
                        break

                if valid:
                    video_sets.append(VideoSet(session_id=sid, part=part, views=views))

    if not video_sets:
        print("No valid video sets found!")
        sys.exit(1)

    # 제한 적용
    if args.limit and len(video_sets) > args.limit:
        video_sets = video_sets[:args.limit]
        print(f"Limited to {args.limit} tasks")

    print(f"\nTasks to create: {len(video_sets)}")
    for vs in video_sets:
        print(f"  - {vs.session_id}-Part{vs.part}")

    if args.dry_run:
        print("\n[DRY RUN] No tasks created.")
        sys.exit(0)

    # 세션 기반 인증
    session = get_auth_session(args.host, args.user, args.password)
    if not session:
        print("Authentication failed!")
        sys.exit(1)

    # Task 생성
    created = 0
    failed = 0

    for vs in video_sets:
        task_name = f"{args.name_prefix}-{vs.session_id}-Part{vs.part}"
        result = create_multiview_task(
            host=args.host,
            session=session,
            task_name=task_name,
            video_set=vs
        )

        if result:
            created += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"Summary: {created} created, {failed} failed")
    print(f"{'='*60}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
