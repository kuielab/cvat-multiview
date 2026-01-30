#!/usr/bin/env python3
"""
Quick Test Script

빠르게 multiview task를 생성하고 테스트하는 스크립트입니다.
대화형으로 실행됩니다.

사용법:
    python quick_test.py
"""

import requests
import json
from pathlib import Path
import sys

# 색상 코드
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'


def print_banner():
    """배너 출력"""
    print(f"{CYAN}")
    print("=" * 60)
    print("  CVAT Multiview - Quick Test")
    print("  Interactive Task Creation & Testing")
    print("=" * 60)
    print(f"{RESET}\n")


def check_server():
    """서버 연결 체크"""
    print(f"{BLUE}Checking CVAT server...{RESET}")

    try:
        response = requests.get('http://localhost:8080/api/server/about', timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"{GREEN}[OK] Server is running{RESET}")
            print(f"  Version: {data.get('version', 'Unknown')}")
            return True
        else:
            print(f"{RED}[FAIL] Server returned error: {response.status_code}{RESET}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"{RED}[FAIL] Cannot connect to server{RESET}")
        print(f"{YELLOW}Please start the server with: python manage.py runserver 0.0.0.0:8080{RESET}")
        return False


def get_token():
    """API 토큰 입력"""
    print(f"\n{BLUE}Step 1: API Token{RESET}")
    print(f"Get your token from: {CYAN}http://localhost:8080{RESET}")
    print(f"  → Click username (top right)")
    print(f"  → Settings")
    print(f"  → Access Tokens")
    print(f"  → Create new token\n")

    token = input(f"Enter your API token: ").strip()

    if not token:
        print(f"{RED}[FAIL] Token cannot be empty{RESET}")
        return None

    # 토큰 검증
    try:
        response = requests.get(
            'http://localhost:8080/api/users/self',
            headers={'Authorization': f'Token {token}'},
            timeout=5
        )

        if response.status_code == 200:
            user = response.json()
            print(f"{GREEN}[OK] Token is valid{RESET}")
            print(f"  Logged in as: {user.get('username')}")
            return token
        else:
            print(f"{RED}[FAIL] Invalid token{RESET}")
            return None
    except Exception as e:
        print(f"{RED}[FAIL] Error validating token: {e}{RESET}")
        return None


def check_dataset():
    """데이터셋 체크 및 세션 선택"""
    print(f"\n{BLUE}Step 2: Dataset{RESET}")

    dataset_path = Path(r"C:\Users\kimsehun\Desktop\proj\ielab\dataset\multitsf")

    if not dataset_path.exists():
        print(f"{RED}[FAIL] Dataset not found: {dataset_path}{RESET}")
        return None, None, None

    print(f"{GREEN}[OK] Dataset found: {dataset_path}{RESET}")

    # 세션 디렉토리 찾기
    session_dirs = sorted([d for d in dataset_path.iterdir() if d.is_dir() and d.name.isdigit()])

    if not session_dirs:
        print(f"{RED}[FAIL] No session directories found{RESET}")
        return None, None, None

    print(f"\nAvailable sessions:")
    for i, session_dir in enumerate(session_dirs, 1):
        videos = list(session_dir.glob('*.mp4'))
        print(f"  {i}. Session {session_dir.name} ({len(videos)} videos)")

    # 세션 선택
    while True:
        try:
            choice = input(f"\nSelect session (1-{len(session_dirs)}) or press Enter for Session 01: ").strip()

            if not choice:
                session_id = "01"
                break

            idx = int(choice) - 1
            if 0 <= idx < len(session_dirs):
                session_id = session_dirs[idx].name.zfill(2)
                break
            else:
                print(f"{YELLOW}Invalid choice. Please try again.{RESET}")
        except ValueError:
            print(f"{YELLOW}Please enter a number.{RESET}")

    # 세션 디렉토리에서 사용 가능한 비디오 세트 찾기
    session_dir = dataset_path / session_id

    # 비디오 ID와 파트 조합 찾기
    video_sets = {}  # {video_id: {part_number: [view1, view2, ...]}}

    for video in session_dir.glob('*.mp4'):
        parts = video.stem.split('-')
        if len(parts) >= 3:
            video_id = parts[0]
            view_str = parts[1].replace('View', '')
            part_str = parts[2].replace('Part', '')

            if view_str.isdigit() and part_str.isdigit():
                if video_id not in video_sets:
                    video_sets[video_id] = {}
                part_num = int(part_str)
                if part_num not in video_sets[video_id]:
                    video_sets[video_id][part_num] = []
                video_sets[video_id][part_num].append(int(view_str))

    if not video_sets:
        print(f"{RED}[FAIL] No valid video sets found in {session_dir}{RESET}")
        return None, None, None

    # 완전한 세트만 필터링 (5개 뷰 모두 있는 것)
    complete_sets = []
    for video_id, parts_dict in video_sets.items():
        for part_num, views in parts_dict.items():
            if len(views) == 5 and all(v in views for v in range(1, 6)):
                complete_sets.append((video_id, part_num))

    if not complete_sets:
        print(f"{RED}[FAIL] No complete video sets (all 5 views) found{RESET}")
        return None, None, None

    # 세트 목록 표시
    print(f"\nComplete video sets found in Session {session_id}:")
    for i, (vid_id, part) in enumerate(complete_sets, 1):
        print(f"  {i}. Video ID: {vid_id}, Part: {part}")

    # 세트 선택
    while True:
        try:
            choice = input(f"\nSelect video set (1-{len(complete_sets)}) or press Enter for first: ").strip()

            if not choice:
                selected_idx = 0
                break

            idx = int(choice) - 1
            if 0 <= idx < len(complete_sets):
                selected_idx = idx
                break
            else:
                print(f"{YELLOW}Invalid choice. Please try again.{RESET}")
        except ValueError:
            print(f"{YELLOW}Please enter a number.{RESET}")

    video_id, part_number = complete_sets[selected_idx]
    print(f"\n{GREEN}Selected: Video ID {video_id}, Part {part_number}{RESET}")

    # 비디오 파일 확인
    print(f"\n{BLUE}Checking video files...{RESET}")

    video_files = {}
    all_found = True

    for view_id in range(1, 6):
        filename = f"{video_id}-View{view_id}-Part{part_number}.mp4"
        filepath = session_dir / filename

        if filepath.exists():
            size_mb = filepath.stat().st_size / (1024 * 1024)
            print(f"{GREEN}[OK]{RESET} View {view_id}: {filename} ({size_mb:.1f} MB)")
            video_files[f'video_view{view_id}'] = filepath
        else:
            print(f"{RED}[FAIL]{RESET} View {view_id}: {filename} NOT FOUND")
            all_found = False

    if not all_found:
        print(f"{RED}[FAIL] Missing video files{RESET}")
        return None, None, None

    return session_id, part_number, video_files


def create_task(token, session_id, part_number, video_files):
    """Task 생성"""
    print(f"\n{BLUE}Step 3: Create Task{RESET}")

    task_name = input(f"Task name (press Enter for default): ").strip()

    if not task_name:
        task_name = f"Multiview-Session-{session_id}-Part-{part_number}"

    print(f"\n{BLUE}Creating task...{RESET}")
    print(f"  Name: {task_name}")
    print(f"  Session: {session_id}")
    print(f"  Part: {part_number}")

    # FormData 준비
    files = {key: open(path, 'rb') for key, path in video_files.items()}

    data = {
        'name': task_name,
        'session_id': session_id,
        'part_number': str(part_number),
    }

    headers = {
        'Authorization': f'Token {token}'
    }

    try:
        print(f"\n{YELLOW}Uploading videos... (this may take a while){RESET}")

        response = requests.post(
            'http://localhost:8080/api/tasks/create_multiview',
            files=files,
            data=data,
            headers=headers,
            timeout=300
        )

        if response.status_code == 201:
            task = response.json()

            print(f"\n{GREEN}{'='*60}")
            print(f"✓ SUCCESS! Task created!")
            print(f"{'='*60}{RESET}")
            print(f"\n{CYAN}Task Details:{RESET}")
            print(f"  ID: {task.get('id')}")
            print(f"  Name: {task.get('name')}")
            print(f"  Dimension: {task.get('dimension')}")
            print(f"  Status: {task.get('status')}")

            task_url = f"http://localhost:8080/tasks/{task.get('id')}"
            print(f"\n{GREEN}Open in browser:{RESET}")
            print(f"  {CYAN}{task_url}{RESET}")

            return task
        else:
            print(f"\n{RED}✗ Failed to create task{RESET}")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    except requests.exceptions.Timeout:
        print(f"\n{RED}✗ Request timed out{RESET}")
        return None
    except Exception as e:
        print(f"\n{RED}✗ Error: {e}{RESET}")
        return None
    finally:
        for f in files.values():
            f.close()


def test_multiview_data(token, task_id):
    """Multiview data 조회 테스트"""
    print(f"\n{BLUE}Step 4: Test Multiview Data API{RESET}")

    try:
        response = requests.get(
            f'http://localhost:8080/api/tasks/{task_id}/multiview_data',
            headers={'Authorization': f'Token {token}'},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            print(f"{GREEN}[OK] Multiview data retrieved{RESET}")
            print(f"\n{CYAN}Multiview Data:{RESET}")
            print(json.dumps(data, indent=2))
            return True
        else:
            print(f"{RED}[FAIL] Failed to get multiview data{RESET}")
            print(f"Status: {response.status_code}")
            return False

    except Exception as e:
        print(f"{RED}[FAIL] Error: {e}{RESET}")
        return False


def main():
    print_banner()

    # 1. 서버 체크
    if not check_server():
        print(f"\n{RED}Please start the server and try again.{RESET}")
        sys.exit(1)

    # 2. 토큰 입력
    token = get_token()
    if not token:
        sys.exit(1)

    # 3. 데이터셋 체크 및 선택
    session_id, part_number, video_files = check_dataset()
    if not session_id:
        sys.exit(1)

    # 4. Task 생성
    task = create_task(token, session_id, part_number, video_files)
    if not task:
        sys.exit(1)

    # 5. Multiview data 테스트
    test_multiview_data(token, task['id'])

    # 완료
    print(f"\n{GREEN}{'='*60}")
    print(f"Test completed successfully!")
    print(f"{'='*60}{RESET}")
    print(f"\n{CYAN}Next Steps:{RESET}")
    print(f"  1. Open task in browser")
    print(f"  2. Click 'Open' button to start annotation")
    print(f"  3. Enable audio in spectrogram panel")
    print(f"  4. Select a view and draw annotations")
    print(f"\n{YELLOW}For detailed instructions, see QUICKSTART.md{RESET}\n")


if __name__ == '__main__':
    main()
