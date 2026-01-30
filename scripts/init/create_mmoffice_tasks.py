#!/usr/bin/env python3
"""
Create MMOffice Tasks - Batch Script for Multiview Dataset

MMOffice 데이터셋에서 multiview task를 배치로 생성하는 스크립트입니다.

데이터 구조:
    /mnt/data/mmoffice/video/
      ├── test/
      │   └── split8_id00_s01_recid008.mp4, split8_id01_s01_recid008.mp4, ...
      └── train/
          └── split0_id00_s01_recid000_0.mp4, split0_id01_s01_recid000_0.mp4, ...

파일 명명 규칙:
    - Test: split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID].mp4
    - Train: split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID]_[PART].mp4

세트 정의:
    - 동일한 SPLIT_ID, SESSION_ID, REC_ID를 가진 파일들이 하나의 세트
    - VIEW_ID는 세트 내에서 각 뷰를 구분 (00, 01, 02, 03)
    - Train의 경우 PART(0, 1)별로 별도의 세트로 처리

Task 이름 규칙:
    - Test: mmoffice_test_split[SPLIT_ID]_s[SESSION_ID]_recid[REC_ID]
    - Train: mmoffice_train_split[SPLIT_ID]_s[SESSION_ID]_recid[REC_ID]_part[PART]

사용법:
    # 모든 세트 자동 탐지
    python create_mmoffice_tasks.py \\
        --user admin --password admin123 \\
        --data-dir /mnt/data

    # 특정 split만
    python create_mmoffice_tasks.py \\
        --user admin --password admin123 \\
        --data-dir /mnt/data \\
        --splits test

    # dry-run으로 미리보기
    python create_mmoffice_tasks.py \\
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
from dataclasses import dataclass, field


# 기본 설정
DEFAULT_HOST = "http://localhost:8080"
DEFAULT_SPLITS = ["test", "train"]


@dataclass
class VideoSet:
    """비디오 세트 정보"""
    split: str           # "test" or "train"
    split_id: str        # 예: "8", "0"
    session_id: str      # 예: "01"
    rec_id: str          # 예: "008"
    part: Optional[str]  # 예: "0", "1" (train만 해당)
    views: List[Path] = field(default_factory=list)  # 뷰 파일들 (VIEW_ID 순으로 정렬)

    @property
    def task_name(self) -> str:
        """Task 이름 생성"""
        base = f"mmoffice_{self.split}_split{self.split_id}_s{self.session_id}_recid{self.rec_id}"
        if self.part is not None:
            base += f"_part{self.part}"
        return base


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


def discover_video_sets(
    data_dir: Path,
    splits: List[str],
    min_views: int = 1
) -> List[VideoSet]:
    """
    디렉토리에서 비디오 세트 자동 탐지

    파일 명명 규칙:
    - Test: split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID].mp4
    - Train: split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID]_[PART].mp4

    세트 정의: SPLIT_ID + SESSION_ID + REC_ID가 동일한 파일들
    """
    video_sets = []

    # Test pattern: split8_id00_s01_recid008.mp4
    # Groups: (1)SPLIT_ID, (2)VIEW_ID, (3)SESSION_ID, (4)REC_ID
    test_pattern = re.compile(
        r'^split(\d+)_id(\d+)_s(\d+)_recid(\d+)\.mp4$',
        re.IGNORECASE
    )

    # Train pattern: split0_id00_s01_recid000_0.mp4
    # Groups: (1)SPLIT_ID, (2)VIEW_ID, (3)SESSION_ID, (4)REC_ID, (5)PART
    train_pattern = re.compile(
        r'^split(\d+)_id(\d+)_s(\d+)_recid(\d+)_(\d+)\.mp4$',
        re.IGNORECASE
    )

    mmoffice_dir = data_dir / "mmoffice" / "video"
    if not mmoffice_dir.exists():
        print(f"  [SKIP] MMOffice video dir not found: {mmoffice_dir}")
        return video_sets

    for split in splits:
        split_dir = mmoffice_dir / split
        if not split_dir.exists():
            print(f"  [SKIP] Split not found: {split_dir}")
            continue

        # 모든 mp4 파일 스캔
        all_files = list(split_dir.glob("*.mp4"))
        if not all_files:
            print(f"  [SKIP] No mp4 files in: {split_dir}")
            continue

        print(f"\n  Split: {split}")
        print(f"  Total files: {len(all_files)}")

        # 파일을 세트 키로 그룹핑
        # key = (split_id, session_id, rec_id, part)
        groups: Dict[Tuple[str, str, str, Optional[str]], List[Tuple[str, Path]]] = {}

        for f in all_files:
            if split == "test":
                match = test_pattern.match(f.name)
                if match:
                    split_id = match.group(1)
                    view_id = match.group(2)
                    session_id = match.group(3)
                    rec_id = match.group(4)
                    part = None
                    key = (split_id, session_id, rec_id, part)
                    if key not in groups:
                        groups[key] = []
                    groups[key].append((view_id, f))
            else:  # train
                match = train_pattern.match(f.name)
                if match:
                    split_id = match.group(1)
                    view_id = match.group(2)
                    session_id = match.group(3)
                    rec_id = match.group(4)
                    part = match.group(5)  # 0 or 1
                    key = (split_id, session_id, rec_id, part)
                    if key not in groups:
                        groups[key] = []
                    groups[key].append((view_id, f))

        # 각 그룹에서 VideoSet 생성
        valid_sets = 0
        for (split_id, session_id, rec_id, part), view_files in sorted(groups.items()):
            if len(view_files) >= min_views:
                # VIEW_ID 순으로 정렬
                sorted_views = sorted(view_files, key=lambda x: x[0])
                sorted_files = [f for (vid, f) in sorted_views]
                video_sets.append(VideoSet(
                    split=split,
                    split_id=split_id,
                    session_id=session_id,
                    rec_id=rec_id,
                    part=part,
                    views=sorted_files
                ))
                valid_sets += 1

        print(f"  Valid sets: {valid_sets}")

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
    print(f"Split: {video_set.split}")
    print(f"Split ID: {video_set.split_id}")
    print(f"Session ID: {video_set.session_id}")
    print(f"Rec ID: {video_set.rec_id}")
    if video_set.part is not None:
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
            'part_number': video_set.part or '0',
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
        description='Create multiview tasks from MMOffice dataset in CVAT',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 모든 세트 자동 탐지
  python create_mmoffice_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data

  # 특정 split만
  python create_mmoffice_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data \\
      --splits test

  # dry-run으로 미리보기
  python create_mmoffice_tasks.py \\
      --user admin --password admin123 \\
      --data-dir /mnt/data \\
      --dry-run

  # 생성할 task 수 제한
  python create_mmoffice_tasks.py \\
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
                        help='Dataset root path (contains mmoffice/video)')

    # split 선택
    parser.add_argument('--splits', nargs='+', default=DEFAULT_SPLITS,
                        help=f'Splits to process (default: {" ".join(DEFAULT_SPLITS)})')

    # 옵션
    parser.add_argument('--min-views', type=int, default=1,
                        help='Minimum number of views per set (default: 1)')
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
    print(f"Splits: {', '.join(args.splits)}")

    video_sets = discover_video_sets(
        data_dir=data_dir,
        splits=args.splits,
        min_views=args.min_views
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

    # Split별 그룹핑
    by_split: Dict[str, List[VideoSet]] = {}
    for vs in video_sets:
        key = vs.split
        if key not in by_split:
            by_split[key] = []
        by_split[key].append(vs)

    for key in sorted(by_split.keys()):
        sets = by_split[key]
        print(f"\n{key}: ({len(sets)} tasks)")
        for vs in sets[:10]:  # 처음 10개만 표시
            print(f"  - {vs.task_name} ({len(vs.views)} views)")
        if len(sets) > 10:
            print(f"  ... and {len(sets) - 10} more")

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
