#!/usr/bin/env python3
"""
Create Multiview Task - Python Script

간편하게 multiview task를 생성하는 스크립트입니다.

사용법:
    python create_multiview_task.py --token YOUR_TOKEN --session 00 --part 1

전제 조건:
    1. CVAT 서버가 실행 중이어야 함 (http://localhost:8080)
    2. API 토큰이 발급되어 있어야 함
    3. 비디오 파일이 준비되어 있어야 함
"""

import argparse
import requests
import os
import sys
from pathlib import Path

# 기본 설정
DEFAULT_API_URL = "http://localhost:8080/api/tasks/create_multiview"
DEFAULT_DATASET_PATH = r"C:\Users\kimsehun\Desktop\proj\ielab\dataset\multitsf"


def create_multiview_task(
    token: str,
    task_name: str,
    session_id: str,
    part_number: int,
    dataset_path: str,
    video_id: str = None,
    api_url: str = DEFAULT_API_URL
):
    """
    Multiview task 생성

    Args:
        token: CVAT API 토큰
        task_name: Task 이름
        session_id: 세션 ID (디렉토리 이름, 예: "01", "02")
        part_number: 파트 번호 (예: 1, 2)
        dataset_path: 데이터셋 루트 경로
        video_id: 비디오 파일 ID 접두사 (예: "00", "01", "25"), None이면 자동 탐색
        api_url: API 엔드포인트 URL

    Returns:
        dict: 생성된 task 정보 또는 None (실패 시)
    """
    # 세션 디렉토리 경로
    session_dir = Path(dataset_path) / session_id.zfill(2)

    if not session_dir.exists():
        print(f"❌ Error: Session directory not found: {session_dir}")
        return None

    # video_id가 지정되지 않으면 디렉토리에서 첫 번째 유효한 세트 찾기
    if video_id is None:
        print("🔍 Auto-detecting video ID...")
        all_videos = list(session_dir.glob("*-View1-Part*.mp4"))
        if not all_videos:
            print(f"❌ Error: No video files found in {session_dir}")
            return None

        # 첫 번째 비디오에서 ID 추출
        first_video = all_videos[0].name
        video_id = first_video.split('-')[0]
        print(f"   Found video ID: {video_id}")

    # 5개 비디오 파일 경로
    video_files = {}
    for view_id in range(1, 6):
        filename = f"{video_id}-View{view_id}-Part{part_number}.mp4"
        filepath = session_dir / filename

        if not filepath.exists():
            print(f"❌ Error: Video file not found: {filepath}")
            return None

        video_files[f'video_view{view_id}'] = open(filepath, 'rb')

    print(f"\n{'='*60}")
    print(f"Creating Multiview Task")
    print(f"{'='*60}")
    print(f"Task Name: {task_name}")
    print(f"Session ID: {session_id}")
    print(f"Part Number: {part_number}")
    print(f"API URL: {api_url}")
    print(f"\nVideo Files:")
    for key in video_files.keys():
        print(f"  ✓ {key}")
    print(f"{'='*60}\n")

    try:
        # FormData 생성
        data = {
            'name': task_name,
            'session_id': session_id,
            'part_number': str(part_number),
        }

        # API 호출
        headers = {
            'Authorization': f'Token {token}'
        }

        print("Sending request to API...")
        response = requests.post(
            api_url,
            files=video_files,
            data=data,
            headers=headers,
            timeout=300  # 5분 타임아웃
        )

        # 응답 처리
        if response.status_code == 201:
            task = response.json()
            print(f"\n✅ SUCCESS! Task created successfully!")
            print(f"\nTask Details:")
            print(f"  - ID: {task.get('id')}")
            print(f"  - Name: {task.get('name')}")
            print(f"  - Dimension: {task.get('dimension')}")
            print(f"  - Status: {task.get('status')}")
            print(f"\n🌐 Open in browser:")
            print(f"  http://localhost:8080/tasks/{task.get('id')}")
            return task
        else:
            print(f"\n❌ ERROR: Failed to create task")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    except requests.exceptions.ConnectionError:
        print(f"\n❌ ERROR: Cannot connect to CVAT server")
        print(f"Make sure the server is running at {api_url}")
        return None
    except requests.exceptions.Timeout:
        print(f"\n❌ ERROR: Request timed out")
        print(f"The server took too long to respond")
        return None
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        return None
    finally:
        # 파일 닫기
        for f in video_files.values():
            f.close()


def main():
    parser = argparse.ArgumentParser(
        description='Create a multiview task in CVAT',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Session 01, Part 1 (auto-detect video ID)
  python create_multiview_task.py --token abc123 --session 01 --part 1

  # Session 01, Part 1, specify video ID "00"
  python create_multiview_task.py --token abc123 --session 01 --part 1 --video-id 00

  # Session 02, Part 1 with custom name (auto-detect video ID "25")
  python create_multiview_task.py --token abc123 --session 02 --part 1 --name "My Custom Task"

  # Custom dataset path
  python create_multiview_task.py --token abc123 --session 01 --part 1 --dataset /path/to/dataset
        """
    )

    parser.add_argument(
        '--token',
        required=True,
        help='CVAT API token (get from Settings → Access Tokens)'
    )
    parser.add_argument(
        '--session',
        required=True,
        help='Session directory (e.g., "01", "02", "03")'
    )
    parser.add_argument(
        '--part',
        type=int,
        required=True,
        help='Part number (e.g., 1, 2)'
    )
    parser.add_argument(
        '--video-id',
        help='Video file ID prefix (e.g., "00", "01", "25"). Auto-detected if not specified.'
    )
    parser.add_argument(
        '--name',
        help='Task name (default: auto-generated from session and part)'
    )
    parser.add_argument(
        '--dataset',
        default=DEFAULT_DATASET_PATH,
        help=f'Dataset root path (default: {DEFAULT_DATASET_PATH})'
    )
    parser.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
        help=f'API endpoint URL (default: {DEFAULT_API_URL})'
    )

    args = parser.parse_args()

    # Task 이름 생성
    if args.name:
        task_name = args.name
    else:
        task_name = f"Multiview-Session-{args.session}-Part-{args.part}"

    # Task 생성
    result = create_multiview_task(
        token=args.token,
        task_name=task_name,
        session_id=args.session,
        part_number=args.part,
        dataset_path=args.dataset,
        video_id=args.video_id,
        api_url=args.api_url
    )

    # Exit code
    sys.exit(0 if result else 1)


if __name__ == '__main__':
    main()
