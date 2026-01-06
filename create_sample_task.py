#!/usr/bin/env python3
"""
Create a sample multiview task using the MultiTSF dataset
"""
import os
import requests
import sys

# Configuration
CVAT_HOST = "http://localhost:8080"
API_TOKEN = None  # Will be fetched from Django
DATASET_PATH = r"C:\Users\kimsehun\Desktop\proj\ielab\dataset\multitsf\01"

# Sample videos (Session 01, Part 1)
VIDEO_FILES = {
    'video_view1': '00-View1-Part1.mp4',
    'video_view2': '00-View2-Part1.mp4',
    'video_view3': '00-View3-Part1.mp4',
    'video_view4': '00-View4-Part1.mp4',
    'video_view5': '00-View5-Part1.mp4',
}

def get_api_token():
    """Get API token from Django"""
    import subprocess

    cmd = [
        'docker', 'compose', 'exec', '-T', 'cvat_server',
        'python', 'manage.py', 'shell', '-c',
        "from django.contrib.auth.models import User; "
        "from rest_framework.authtoken.models import Token; "
        "u=User.objects.get(username='admin'); "
        "t,_=Token.objects.get_or_create(user=u); "
        "print(t.key)"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
    token = result.stdout.strip().split('\n')[-1]
    return token

def create_multiview_task(token, task_name, session_id, part_number):
    """Create a multiview task via API"""
    url = f"{CVAT_HOST}/api/tasks/create_multiview"

    headers = {
        'Authorization': f'Token {token}',
    }

    # Prepare form data
    data = {
        'name': task_name,
        'session_id': session_id,
        'part_number': str(part_number),
    }

    # Prepare files
    files = {}
    for view_key, filename in VIDEO_FILES.items():
        filepath = os.path.join(DATASET_PATH, filename)
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}")
            return None
        files[view_key] = open(filepath, 'rb')

    try:
        print(f"Creating task: {task_name}")
        print(f"  Session: {session_id}, Part: {part_number}")
        print(f"  Videos: {list(VIDEO_FILES.values())}")
        print()
        print("Uploading... (this may take a minute)")

        response = requests.post(url, headers=headers, data=data, files=files)

        if response.status_code == 201:
            task_data = response.json()
            print(f"\n[SUCCESS] Task created successfully!")
            print(f"  Task ID: {task_data.get('id')}")
            print(f"  Task Name: {task_data.get('name')}")
            print(f"  Dimension: {task_data.get('dimension')}")
            print(f"  URL: {CVAT_HOST}/tasks/{task_data.get('id')}")
            return task_data
        else:
            print(f"\n[ERROR] Failed to create task")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.text}")
            return None

    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        return None

    finally:
        # Close all files
        for f in files.values():
            f.close()

def main():
    print("=" * 60)
    print("CVAT Multiview - Sample Task Creator")
    print("=" * 60)
    print()

    # Check if dataset exists
    if not os.path.exists(DATASET_PATH):
        print(f"ERROR: Dataset not found at {DATASET_PATH}")
        print("Please download the MultiTSF dataset first.")
        sys.exit(1)

    # Check if all video files exist
    missing_files = []
    for filename in VIDEO_FILES.values():
        filepath = os.path.join(DATASET_PATH, filename)
        if not os.path.exists(filepath):
            missing_files.append(filename)

    if missing_files:
        print("ERROR: Missing video files:")
        for f in missing_files:
            print(f"  - {f}")
        sys.exit(1)

    print("Dataset check: OK")
    print()

    # Get API token
    print("Getting API token...")
    token = get_api_token()
    if not token:
        print("ERROR: Failed to get API token")
        sys.exit(1)
    print(f"Token: {token}")
    print()

    # Create task
    task = create_multiview_task(
        token=token,
        task_name="MultiTSF-Session01-Part1-Sample",
        session_id="01",
        part_number=1
    )

    if task:
        print()
        print("=" * 60)
        print("Next steps:")
        print("  1. Open your browser: http://localhost:8080")
        print("  2. Login with: admin / admin123")
        print(f"  3. Click on task: {task.get('name')}")
        print("  4. Start annotating!")
        print("=" * 60)
    else:
        print()
        print("Failed to create task. Please check the error messages above.")
        sys.exit(1)

if __name__ == '__main__':
    main()
