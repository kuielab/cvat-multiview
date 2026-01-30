#!/usr/bin/env python3
"""
Create Multisensor Tasks - Batch Script for Multiview Dataset

Multisensor 데이터셋에서 multiview task를 배치로 생성하는 스크립트입니다.

데이터 구조:
    /mnt/data/
      ├── multisensor_home1/
      │   ├── 01/
      │   │   ├── 00-View1-Part1.mp4, 00-View2-Part1.mp4, ... 00-View5-Part1.mp4
      │   │   └── ...
      │   └── ...
      └── multisensor_home2/
          └── ...

파일 명명 규칙: [SESSION_ID]-View[VIEW_ID]-Part[PART_NUM].mp4
Task 이름 규칙: multisensor_home1_[SUBDIR]-[SESSION_ID]-Part[PART_NUM]

사용법:
    # 모든 세트 자동 탐지
    python create_multisensor_home_tasks.py \\
        --user admin --password admin123 \\
        --data-dir /mnt/data

    # 특정 데이터셋만
    python create_multisensor_home_tasks.py \\
        --user admin --password admin123 \\
        --data-dir /mnt/data \\
        --datasets multisensor_home1

    # dry-run으로 미리보기
    python create_multisensor_home_tasks.py \\
        --user admin --password admin123 \\
        --data-dir /mnt/data \\
        --dry-run
"""

import argparse
import requests
import os
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict
from dataclasses import dataclass


# 기본 설정
DEFAULT_HOST = "http://localhost:8080"
DEFAULT_VIEW_COUNT = 5
DEFAULT_DATASETS = ["multisensor_home1", "multisensor_home2"]


@dataclass
class VideoSet:
    """비디오 세트 정보"""
    dataset: str     # 예: "multisensor_home1"
    subdir: str      # 예: "01"
    session_id: str  # 예: "00"
    part: int        # 예: 1
    views: List[Path]  # View1부터 View5까지의 파일 경로

    @property
    def task_name(self) -> str:
        """Task 이름 생성"""
        return f"{self.dataset}_{self.subdir}-{self.session_id}-Part{self.part}"


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


def discover_subdirs(dataset_dir: Path) -> List[str]:
    """
    데이터셋 디렉토리 내의 하위 폴더(01, 02, 03...) 자동 탐지
    숫자로 이루어진 폴더만 반환
    """
    subdirs = []
    if not dataset_dir.exists():
        return subdirs

    for item in sorted(dataset_dir.iterdir()):
        if item.is_dir() and item.name.isdigit():
            subdirs.append(item.name)

    return subdirs


def discover_video_sets(
    data_dir: Path,
    datasets: List[str],
    subdirs: Optional[List[str]] = None,
    view_count: int = DEFAULT_VIEW_COUNT
) -> List[VideoSet]:
    """
    디렉토리에서 비디오 세트 자동 탐지

    파일 명명 규칙: [SESSION_ID]-View[VIEW_ID]-Part[PART_NUM].mp4
    """
    video_sets = []
    pattern = re.compile(r'^(\d+)-View(\d+)-Part(\d+)\.mp4$', re.IGNORECASE)

    for dataset in datasets:
        dataset_dir = data_dir / dataset
        if not dataset_dir.exists():
            print(f"  [SKIP] Dataset not found: {dataset_dir}")
            continue

        # 하위 폴더 탐지
        target_subdirs = subdirs if subdirs else discover_subdirs(dataset_dir)
        if not target_subdirs:
            print(f"  [SKIP] No subdirs found in: {dataset_dir}")
            continue

        print(f"\n  Dataset: {dataset}")
        print(f"  Subdirs: {', '.join(target_subdirs)}")

        for subdir in target_subdirs:
            subdir_path = dataset_dir / subdir
            if not subdir_path.exists():
                print(f"    [SKIP] Subdir not found: {subdir_path}")
                continue

            # 모든 mp4 파일 스캔
            all_files = list(subdir_path.glob("*.mp4"))
            if not all_files:
                print(f"    [SKIP] No mp4 files in: {subdir_path}")
                continue

            # (session_id, part) 조합 추출
            combinations: Set[Tuple[str, int]] = set()
            for f in all_files:
                match = pattern.match(f.name)
                if match:
                    session_id = match.group(1)
                    part = int(match.group(3))
                    combinations.add((session_id, part))

            # 각 조합에 대해 VideoSet 생성
            subdir_sets = 0
            for session_id, part in sorted(combinations):
                views = []
                valid = True

                for view_num in range(1, view_count + 1):
                    filename = f"{session_id}-View{view_num}-Part{part}.mp4"
                    filepath = subdir_path / filename

                    if filepath.exists():
                        views.append(filepath)
                    else:
                        valid = False
                        break

                if valid and len(views) == view_count:
                    video_sets.append(VideoSet(
                        dataset=dataset,
                        subdir=subdir,
                        session_id=session_id,
                        part=part,
                        views=views
                    ))
                    subdir_sets += 1

            print(f"    {subdir}: {subdir_sets} sets found")

    return video_sets


def create_multiview_task(
    host: str,
    session: requests.Session,
    video_set: VideoSet,
    labels: List[dict] = None
) -> Optional[dict]:
    """
    Multiview task 생성
    """
    api_url = f"{host}/api/tasks/create_multiview"
    task_name = video_set.task_name

    # 기본 라벨
    if labels is None:
        labels = [{"name": "object", "attributes": [], "type": "any"}]

    print(f"\n{'='*60}")
    print(f"Creating Task: {task_name}")
    print(f"{'='*60}")
    print(f"Dataset: {video_set.dataset}")
    print(f"Subdir: {video_set.subdir}")
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
            'view_count': str(len(video_set.views)),
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
        description='Create multiview tasks from multisensor dataset in CVAT',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 로컬 테스트 (모든 세트 자동 탐지)
  python create_multisensor_tasks.py \\
      --user admin --password admin123 \\
      --data-dir "C:\\Users\\Administrator\\Desktop\\proj\\IE_lab\\dataset"

  # 서버 사용 (특정 데이터셋만)
  python create_multisensor_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data \\
      --datasets multisensor_home1

  # 특정 하위 폴더만 처리
  python create_multisensor_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data \\
      --subdirs 01 02

  # dry-run으로 미리보기
  python create_multisensor_tasks.py \\
      --user admin --password admin123 \\
      --data-dir "C:\\Users\\Administrator\\Desktop\\proj\\IE_lab\\dataset" \\
      --dry-run

  # 생성할 task 수 제한
  python create_multisensor_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data \\
      --limit 10
        """
    )

    # 인증
    parser.add_argument('--user', '-u', required=True, help='CVAT username')
    parser.add_argument('--password', '-p', required=True, help='CVAT password')
    parser.add_argument('--host', default=DEFAULT_HOST, help=f'CVAT host (default: {DEFAULT_HOST})')

    # 데이터 경로
    parser.add_argument('--data-dir', '-d', required=True,
                        help='Dataset root path (contains multisensor_home1, multisensor_home2)')

    # 데이터셋 선택
    parser.add_argument('--datasets', nargs='+', default=DEFAULT_DATASETS,
                        help=f'Datasets to process (default: {" ".join(DEFAULT_DATASETS)})')
    parser.add_argument('--subdirs', nargs='+',
                        help='Specific subdirs to process (e.g., 01 02 03). Default: auto-detect')

    # 옵션
    parser.add_argument('--view-count', type=int, default=DEFAULT_VIEW_COUNT,
                        help=f'Number of views per set (default: {DEFAULT_VIEW_COUNT})')
    parser.add_argument('--limit', type=int, help='Limit number of tasks to create')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be created without actually creating')

    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    # 비디오 세트 탐지
    print(f"\nScanning for video sets in: {data_dir}")
    print(f"Datasets: {', '.join(args.datasets)}")

    video_sets = discover_video_sets(
        data_dir=data_dir,
        datasets=args.datasets,
        subdirs=args.subdirs,
        view_count=args.view_count
    )

    if not video_sets:
        print("\nNo valid video sets found!")
        sys.exit(1)

    # 제한 적용
    if args.limit and len(video_sets) > args.limit:
        video_sets = video_sets[:args.limit]
        print(f"\nLimited to {args.limit} tasks")

    # 요약 출력
    print(f"\n{'='*60}")
    print(f"Tasks to create: {len(video_sets)}")
    print(f"{'='*60}")

    # 데이터셋별 그룹핑
    by_dataset: Dict[str, List[VideoSet]] = {}
    for vs in video_sets:
        key = f"{vs.dataset}/{vs.subdir}"
        if key not in by_dataset:
            by_dataset[key] = []
        by_dataset[key].append(vs)

    for key in sorted(by_dataset.keys()):
        sets = by_dataset[key]
        print(f"\n{key}:")
        for vs in sets:
            print(f"  - {vs.task_name}")

    if args.dry_run:
        print(f"\n{'='*60}")
        print("[DRY RUN] No tasks created.")
        print(f"{'='*60}")
        sys.exit(0)

    # 세션 기반 인증
    print(f"\nConnecting to {args.host}...")
    session = get_auth_session(args.host, args.user, args.password)
    if not session:
        print("Authentication failed!")
        sys.exit(1)

    # Task 생성
    created = 0
    failed = 0

    for vs in video_sets:
        result = create_multiview_task(
            host=args.host,
            session=session,
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
