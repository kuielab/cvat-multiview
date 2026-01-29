# CVAT Multiview Scripts

Multiview Task 생성 및 테스트를 위한 유틸리티 스크립트 모음입니다.

## 스크립트 목록

### check_environment.py

CVAT Multiview 프로젝트의 환경을 체크하는 스크립트입니다.

```bash
python check_environment.py
```

- Python 버전 확인
- Docker 상태 확인
- CVAT 서버 연결 확인
- 필수 패키지 설치 여부 확인

### create_multiview_task.py

단일 Multiview Task를 생성하는 스크립트입니다.

```bash
python create_multiview_task.py --token YOUR_TOKEN --session 00 --part 1
```

**옵션:**
- `--token`: CVAT API 토큰 (필수)
- `--session`: 세션 ID (예: "00", "01")
- `--part`: 파트 번호 (예: 1, 2)
- `--dataset-path`: 데이터셋 경로

### create_multiview_tasks.py

여러 Multiview Task를 배치로 생성하는 스크립트입니다.

**파일 명명 규칙:** `[n]-View[x]-Part[y].mp4`
- n: 세션 ID (예: 100, 101, 102)
- x: 뷰 번호 (1-5)
- y: 파트 번호 (1, 2, ...)

```bash
# 단일 task 생성
python create_multiview_tasks.py --user admin --password admin123 \
    --session-id 100 --part 1 --data-dir C:/path/to/videos

# 배치 생성 (여러 세션)
python create_multiview_tasks.py --user admin --password admin123 \
    --session-ids 100 101 102 --parts 1 2 --data-dir C:/path/to/videos

# 디렉토리의 모든 세트 자동 탐지
python create_multiview_tasks.py --user admin --password admin123 \
    --data-dir C:/path/to/videos --auto-detect
```

### quick_test.py

대화형으로 Multiview Task를 빠르게 생성하고 테스트하는 스크립트입니다.

```bash
python quick_test.py
```

- 대화형 인터페이스
- 서버 연결 자동 확인
- Task 생성 및 테스트 통합

## 전제 조건

1. CVAT 서버가 실행 중이어야 함 (`http://localhost:8080`)
2. Python 3.8 이상
3. 필수 패키지: `requests`

```bash
pip install requests
```
