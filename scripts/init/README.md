# CVAT Multiview Init Scripts

Multiview Task 생성 및 테스트를 위한 유틸리티 스크립트 모음입니다.

## 파일 위치

```
scripts/init/
├── create_all_tasks.sh           # 통합 실행 스크립트
├── create_multisensor_home_tasks.py
├── create_mmoffice_tasks.py
├── create_multiview_task.py
├── create_multiview_tasks.py
├── check_environment.py
├── quick_test.py
└── README.md
```

## 빠른 시작

### create_all_tasks.sh

**모든 데이터셋의 Multiview Task를 한 번에 생성하는 통합 스크립트입니다.**

Multisensor Home과 MMOffice 데이터셋을 자동으로 탐지하여 task를 생성합니다.
Python 및 의존성 패키지 설치 여부를 자동으로 확인하고, 필요시 설치합니다.

```bash
# scripts/init 디렉토리에서 실행
cd /path/to/cvat-multiview/scripts/init

# 기본 실행 (모든 데이터셋)
./create_all_tasks.sh --user admin --password admin123

# dry-run으로 미리보기
./create_all_tasks.sh --user admin --password admin123 --dry-run

# 커스텀 데이터 경로
./create_all_tasks.sh --user admin --password admin123 --data-dir /mnt/data

# task 수 제한
./create_all_tasks.sh --user admin --password admin123 --limit 10
```

**옵션:**
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--user`, `-u` | CVAT 사용자명 | (필수) |
| `--password`, `-p` | CVAT 비밀번호 | (필수) |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | `/mnt/data` |
| `--host` | CVAT 서버 URL | `http://localhost:8080` |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

**자동 처리 항목:**
- Python 3.8+ 자동 탐지
- `requests` 패키지 자동 설치
- CVAT 서버 연결 확인
- 데이터셋 존재 여부 확인

---

## 개별 스크립트 목록

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

### create_multisensor_home_tasks.py

Multisensor Home 데이터셋에서 Multiview Task를 배치로 생성하는 스크립트입니다.

**데이터 구조:**
```
/mnt/data/
├── multisensor_home1/
│   ├── 01/
│   │   ├── 00-View1-Part1.mp4, 00-View2-Part1.mp4, ... 00-View5-Part1.mp4
│   │   └── ...
│   ├── 02/
│   └── 03/
└── multisensor_home2/
    ├── 01/
    ├── 02/
    └── 03/
```

**파일 명명 규칙:** `[SESSION_ID]-View[VIEW_ID]-Part[PART_NUM].mp4`

**Task 이름 규칙:** `multisensor_home1_[SUBDIR]-[SESSION_ID]-Part[PART_NUM]`

```bash
# 모든 세트 자동 탐지
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data

# 특정 데이터셋만
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1

# 특정 하위 폴더만 처리
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --subdirs 01 02

# dry-run으로 미리보기
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --dry-run

# 생성할 task 수 제한
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --limit 10
```

**옵션:**
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--user`, `-u` | CVAT 사용자명 | (필수) |
| `--password`, `-p` | CVAT 비밀번호 | (필수) |
| `--host` | CVAT 서버 URL | `http://localhost:8080` |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | (필수) |
| `--datasets` | 처리할 데이터셋 | `multisensor_home1 multisensor_home2` |
| `--subdirs` | 처리할 하위 폴더 | 자동 탐지 |
| `--view-count` | 뷰 개수 | `5` |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

### create_mmoffice_tasks.py

MMOffice 데이터셋에서 Multiview Task를 배치로 생성하는 스크립트입니다.

**데이터 구조:**
```
/mnt/data/mmoffice/video/
├── test/
│   └── split8_id00_s01_recid008.mp4, split8_id01_s01_recid008.mp4, ...
└── train/
    └── split0_id00_s01_recid000_0.mp4, split0_id01_s01_recid000_0.mp4, ...
```

**파일 명명 규칙:**
- Test: `split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID].mp4`
- Train: `split[SPLIT_ID]_id[VIEW_ID]_s[SESSION_ID]_recid[REC_ID]_[PART].mp4`

**세트 정의:**
- 동일한 SPLIT_ID, SESSION_ID, REC_ID를 가진 파일들이 하나의 세트
- VIEW_ID는 세트 내에서 각 뷰를 구분 (00, 01, 02, 03)
- Train의 경우 PART(0, 1)별로 별도의 세트로 처리

**Task 이름 규칙:**
- Test: `mmoffice_test_split[SPLIT_ID]_s[SESSION_ID]_recid[REC_ID]`
- Train: `mmoffice_train_split[SPLIT_ID]_s[SESSION_ID]_recid[REC_ID]_part[PART]`

```bash
# 모든 세트 자동 탐지
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data

# 특정 split만
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --splits test

# dry-run으로 미리보기
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --dry-run

# 생성할 task 수 제한
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --limit 10
```

**옵션:**
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--user`, `-u` | CVAT 사용자명 | (필수) |
| `--password`, `-p` | CVAT 비밀번호 | (필수) |
| `--host` | CVAT 서버 URL | `http://localhost:8080` |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | (필수) |
| `--splits` | 처리할 split | `test train` |
| `--min-views` | 최소 뷰 개수 | `1` |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

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

## 데이터셋 요약

| 데이터셋 | 스크립트 | 세트 수 | 뷰 수 |
|----------|----------|---------|-------|
| Multisensor Home1 | `create_multisensor_home_tasks.py` | 168 | 5 views |
| Multisensor Home2 | `create_multisensor_home_tasks.py` | 198 | 5 views |
| MMOffice Test | `create_mmoffice_tasks.py` | 88 | 4 views |
| MMOffice Train | `create_mmoffice_tasks.py` | 720 | 4 views |
