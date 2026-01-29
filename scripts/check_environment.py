#!/usr/bin/env python3
"""
Environment Check Script

CVAT Multiview 프로젝트의 환경을 체크하는 스크립트입니다.

사용법:
    python check_environment.py
"""

import os
import sys
import subprocess
from pathlib import Path
import json

# 색상 코드
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_header(title):
    """헤더 출력"""
    print(f"\n{BLUE}{'='*60}")
    print(f"{title}")
    print(f"{'='*60}{RESET}\n")


def check_mark(condition):
    """체크마크 반환"""
    return f"{GREEN}[OK]{RESET}" if condition else f"{RED}[FAIL]{RESET}"


def check_python():
    """Python 버전 체크"""
    print_header("1. Python Environment")

    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    is_valid = version.major == 3 and version.minor >= 8

    print(f"{check_mark(is_valid)} Python Version: {version_str}")
    if not is_valid:
        print(f"  {YELLOW}[WARNING] Python 3.8 or higher is required{RESET}")

    return is_valid


def check_packages():
    """필수 Python 패키지 체크"""
    print_header("2. Python Packages")

    required_packages = {
        'django': '3.2.0',
        'djangorestframework': '3.12.0',
        'requests': '2.25.0',
        'pillow': '8.0.0',
        'psycopg2': '2.8.0',
    }

    all_installed = True

    for package, min_version in required_packages.items():
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'show', package],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # 버전 추출
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        version = line.split(':')[1].strip()
                        print(f"{check_mark(True)} {package}: {version}")
                        break
            else:
                print(f"{check_mark(False)} {package}: Not installed")
                all_installed = False
        except Exception as e:
            print(f"{check_mark(False)} {package}: Error checking ({e})")
            all_installed = False

    return all_installed


def check_nodejs():
    """Node.js 및 npm 체크"""
    print_header("3. Node.js Environment")

    # Node.js 체크
    try:
        result = subprocess.run(
            ['node', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        node_version = result.stdout.strip()
        node_ok = result.returncode == 0
        print(f"{check_mark(node_ok)} Node.js: {node_version}")
    except Exception:
        node_ok = False
        print(f"{check_mark(False)} Node.js: Not installed")

    # npm 체크
    try:
        result = subprocess.run(
            ['npm', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        npm_version = result.stdout.strip()
        npm_ok = result.returncode == 0
        print(f"{check_mark(npm_ok)} npm: {npm_version}")
    except Exception:
        npm_ok = False
        print(f"{check_mark(False)} npm: Not installed")

    return node_ok and npm_ok


def check_dataset():
    """데이터셋 파일 체크"""
    print_header("4. Dataset Files")

    dataset_path = Path(r"C:\Users\kimsehun\Desktop\proj\ielab\dataset\multitsf")

    # 디렉토리 존재 확인
    if not dataset_path.exists():
        print(f"{check_mark(False)} Dataset directory not found: {dataset_path}")
        return False

    print(f"{check_mark(True)} Dataset directory: {dataset_path}")

    # JSON 파일 확인
    json_files = ['train.json', 'test.json', 'all_labels.json']
    json_ok = True

    for json_file in json_files:
        filepath = dataset_path / json_file
        exists = filepath.exists()
        json_ok = json_ok and exists

        if exists:
            size_kb = filepath.stat().st_size / 1024
            print(f"{check_mark(True)} {json_file}: {size_kb:.1f} KB")
        else:
            print(f"{check_mark(False)} {json_file}: Not found")

    # 세션 디렉토리 확인
    session_dirs = [d for d in dataset_path.iterdir() if d.is_dir() and d.name.isdigit()]

    if session_dirs:
        print(f"\n{check_mark(True)} Session directories found: {len(session_dirs)}")

        # 비디오 파일 카운트
        video_count = 0
        for session_dir in session_dirs:
            videos = list(session_dir.glob('*.mp4'))
            video_count += len(videos)

        print(f"{check_mark(True)} Total video files: {video_count}")
    else:
        print(f"{check_mark(False)} No session directories found")
        return False

    return json_ok and len(session_dirs) > 0


def check_cvat_files():
    """CVAT 파일 수정 확인"""
    print_header("5. CVAT Modified Files")

    cvat_root = Path(r"C:\Users\kimsehun\Desktop\proj\ielab\cvat")

    if not cvat_root.exists():
        print(f"{check_mark(False)} CVAT directory not found: {cvat_root}")
        return False

    print(f"{check_mark(True)} CVAT directory: {cvat_root}")

    # Backend 파일
    backend_files = [
        'cvat/apps/engine/models.py',
        'cvat/apps/engine/serializers.py',
        'cvat/apps/engine/views.py',
    ]

    print(f"\n{BLUE}Backend Files:{RESET}")
    backend_ok = True
    for filepath in backend_files:
        full_path = cvat_root / filepath
        exists = full_path.exists()
        backend_ok = backend_ok and exists
        print(f"  {check_mark(exists)} {filepath}")

    # Frontend 파일
    frontend_files = [
        'cvat-ui/src/reducers/index.ts',
        'cvat-ui/src/reducers/annotation-reducer.ts',
        'cvat-ui/src/components/annotation-page/multiview-workspace/multiview-workspace.tsx',
        'cvat-ui/src/components/annotation-page/multiview-workspace/audio-engine.ts',
        'cvat-ui/src/components/annotation-page/multiview-workspace/spectrogram-panel.tsx',
    ]

    print(f"\n{BLUE}Frontend Files:{RESET}")
    frontend_ok = True
    for filepath in frontend_files:
        full_path = cvat_root / filepath
        exists = full_path.exists()
        frontend_ok = frontend_ok and exists
        print(f"  {check_mark(exists)} {filepath}")

    # 문서 파일
    doc_files = [
        'MULTIVIEW_USAGE.md',
        'TESTING_MANUAL.md',
        'QUICKSTART.md',
        'IMPLEMENTATION_STATUS.md',
        'SETUP_COMPLETE.md',
        'FILE_STRUCTURE.md',
    ]

    print(f"\n{BLUE}Documentation Files:{RESET}")
    doc_ok = True
    for filepath in doc_files:
        full_path = cvat_root / filepath
        exists = full_path.exists()
        doc_ok = doc_ok and exists
        print(f"  {check_mark(exists)} {filepath}")

    return backend_ok and frontend_ok and doc_ok


def check_server():
    """CVAT 서버 연결 체크"""
    print_header("6. CVAT Server")

    try:
        import requests as req
    except ImportError:
        print(f"{check_mark(False)} 'requests' package not installed")
        print(f"  {YELLOW}Install with: pip install requests{RESET}")
        return False

    try:
        response = req.get('http://localhost:8080/api/server/about', timeout=5)

        if response.status_code == 200:
            print(f"{check_mark(True)} Server is running at http://localhost:8080")

            data = response.json()
            print(f"  Version: {data.get('version', 'Unknown')}")
            return True
        else:
            print(f"{check_mark(False)} Server returned status code: {response.status_code}")
            return False
    except req.exceptions.ConnectionError:
        print(f"{check_mark(False)} Server is not running")
        print(f"  {YELLOW}Start with: python manage.py runserver 0.0.0.0:8080{RESET}")
        return False
    except Exception as e:
        print(f"{check_mark(False)} Error: {e}")
        return False


def print_summary(results):
    """결과 요약 출력"""
    print_header("Summary")

    total = len(results)
    passed = sum(results.values())

    print(f"Total Checks: {total}")
    print(f"Passed: {GREEN}{passed}{RESET}")
    print(f"Failed: {RED}{total - passed}{RESET}")

    if passed == total:
        print(f"\n{GREEN}[OK] All checks passed! You're ready to go!{RESET}")
        print(f"\n{BLUE}Next Steps:{RESET}")
        print(f"  1. Run database migrations:")
        print(f"     python manage.py makemigrations engine")
        print(f"     python manage.py migrate engine")
        print(f"  2. Start CVAT server:")
        print(f"     python manage.py runserver 0.0.0.0:8080")
        print(f"  3. Create a multiview task:")
        print(f"     python scripts/create_multiview_task.py --token YOUR_TOKEN --session 00 --part 1")
    else:
        print(f"\n{YELLOW}[WARNING] Some checks failed. Please fix the issues above.{RESET}")


def main():
    print(f"{BLUE}")
    print("=" * 60)
    print("  CVAT Multiview - Environment Check")
    print("=" * 60)
    print(f"{RESET}")

    results = {
        'Python': check_python(),
        'Packages': check_packages(),
        'Node.js': check_nodejs(),
        'Dataset': check_dataset(),
        'CVAT Files': check_cvat_files(),
        'Server': check_server(),
    }

    print_summary(results)

    # Exit code
    sys.exit(0 if all(results.values()) else 1)


if __name__ == '__main__':
    main()
