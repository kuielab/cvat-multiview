# CVAT Multiview Init Scripts

Multiview Task 생성 및 테스트를 위한 유틸리티 스크립트 모음입니다.

## 파일 위치

```
scripts/init/
├── setup_cvat.sh                     # 초기 설정 (Superuser + Organization + Users)
├── create_all_tasks.sh               # 모든 Task 일괄 생성
├── assign_tasks_to_orgs.sh           # 범위별로 Organization에 Task 할당
├── insert_bbox_annotations.py        # Pre-annotation bbox 삽입 (Python)
├── insert_prelabels.sh               # Pre-annotation 삽입 (Shell wrapper)
├── create_multisensor_home_tasks.py  # Home 데이터셋 Task 생성
├── create_mmoffice_tasks.py          # MMOffice 데이터셋 Task 생성
├── create_multiview_task.py          # 단일 Task 생성
├── create_multiview_tasks.py         # 범용 배치 Task 생성
├── check_environment.py              # 환경 체크
├── quick_test.py                     # 빠른 테스트
└── README.md
```

---

## 데이터셋 구조 및 필터링 기준

### Multisensor Home

```
/mnt/data/
├── multisensor_home1/
│   ├── 01/                    # subdir
│   │   ├── 00-View1-Part1.mp4 # session 00-24
│   │   ├── 00-View2-Part1.mp4
│   │   └── ...
│   └── 02/                    # subdir
│       └── 25-View1-Part1.mp4 # session 25-58
└── multisensor_home2/
    ├── 01/                    # session 00-30
    └── 02/                    # session 31-61
```

| 필터 | 옵션 | 값 | 설명 |
|------|------|-----|------|
| datasets | `--datasets` | `multisensor_home1`, `multisensor_home2` | 데이터셋 선택 |
| subdirs | `--subdirs` | `01`, `02` | 서브디렉토리 선택 |
| sessions | `--sessions` | `00-58` (home1), `00-61` (home2) | 세션 ID 범위 |

### MMOffice

```
/mnt/data/mmoffice/video/
├── test/
│   └── split8_id00_s01_recid008.mp4
└── train/
    └── split5_id00_s01_recid000_0.mp4
         │     │   │    │       └── part (0, 1)
         │     │   │    └── rec_id
         │     │   └── session_id (01-12)
         │     └── view_id (00-03)
         └── split_id (2-7)
```

| 필터 | 옵션 | 값 | 설명 |
|------|------|-----|------|
| splits | `--splits` | `test`, `train` | test/train 선택 |
| split-ids | `--split-ids` | `2-7` | 파일명의 split[N] 필터 |
| sessions | `--sessions` | `01-12` | 세션 ID 범위 |

---

## Shell 스크립트

### 1. setup_cvat.sh - 초기 설정

**CVAT 초기 설정을 수행합니다. (Task 생성 제외)**

```bash
# 대화형 실행
./scripts/init/setup_cvat.sh

# Superuser 이미 있는 경우
./scripts/init/setup_cvat.sh --skip-superuser

# EC2 등 다른 서버
CVAT_HOST=http://3.36.160.76:8080 ./scripts/init/setup_cvat.sh
```

**기능:**
- Superuser 계정 생성 (docker compose exec)
- Organization 생성 (여러 개 가능)
- 일반 유저 생성 (여러 명 가능)
- 유저를 Organization에 추가 (역할 선택 가능)

**역할 선택:**
유저를 Organization에 추가할 때 역할을 선택할 수 있습니다:
- `worker` - 자신에게 할당된 task만 볼 수 있음
- `supervisor` - 자신에게 할당된 task만 볼 수 있음
- `maintainer` - **Organization의 모든 task를 볼 수 있음 (권장)**

**옵션:**
| 옵션 | 설명 |
|------|------|
| `--skip-superuser` | Superuser 생성 단계 건너뛰기 |

**환경변수:**
| 환경변수 | 설명 | 기본값 |
|----------|------|--------|
| `CVAT_HOST` | CVAT 서버 URL | `http://localhost:8080` |

---

### 2. create_all_tasks.sh - 전체 Task 생성

**모든 데이터셋의 Multiview Task를 한 번에 생성합니다.**

```bash
# 기본 실행
./create_all_tasks.sh --user admin --password admin123

# Organization 지정
./create_all_tasks.sh --user admin --password admin123 --org ielab

# dry-run 미리보기
./create_all_tasks.sh --user admin --password admin123 --dry-run

# 커스텀 데이터 경로
./create_all_tasks.sh --user admin --password admin123 \
    --data-dir /mnt/data

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
| `--org` | Organization slug | - |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

---

### 3. assign_tasks_to_orgs.sh - 범위별 Organization 할당

**특정 세션/split 범위의 Task를 특정 Organization에 할당하여 생성합니다.**

#### 단일 할당

```bash
# Home 데이터셋의 세션 00-19를 team1에 할당
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 00-19 --org team1

# Home의 특정 subdir만
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 00-19 --subdirs 01 --org team1

# Home의 특정 datasets만
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 00-19 --datasets multisensor_home1 --org team1

# MMOffice의 세션 01-04를 team1에 할당
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset mmoffice --sessions 01-04 --org team1

# MMOffice의 특정 split-ids만
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset mmoffice --sessions 01-04 --split-ids 5-6 --org team1

# dry-run 미리보기
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 00-19 --org team1 --dry-run
```

#### 설정 파일로 일괄 할당

```bash
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --config assignments.txt
```

**설정 파일 형식 (assignments.txt):**

```
# 주석 (# 또는 빈 줄은 무시)
# 형식: dataset:sessions:org[:옵션]

# Home1 분배 (58개 세션 → 3개 조직)
home:00-19:team1:datasets=multisensor_home1
home:20-39:team2:datasets=multisensor_home1
home:40-58:team3:datasets=multisensor_home1

# Home2 분배 (62개 세션 → 3개 조직)
home:00-20:team1:datasets=multisensor_home2
home:21-40:team2:datasets=multisensor_home2
home:41-61:team3:datasets=multisensor_home2

# MMOffice 분배 (세션 + split-ids 조합)
mmoffice:01-04:team1:split-ids=5,6
mmoffice:05-08:team2:split-ids=5,6
mmoffice:09-12:team3:split-ids=5,6
mmoffice:01-06:team1:split-ids=7
mmoffice:07-12:team2:split-ids=7
```

**옵션:**
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--user`, `-u` | CVAT 사용자명 | (필수) |
| `--password`, `-p` | CVAT 비밀번호 | (필수) |
| `--dataset` | 데이터셋 타입 (`home` 또는 `mmoffice`) | - |
| `--sessions` | 세션 범위 (예: `00-10`) | - |
| `--org` | Organization slug | - |
| `--subdirs` | Home 서브디렉토리 필터 | - |
| `--datasets` | Home 데이터셋 필터 | - |
| `--split-ids` | MMOffice split ID 필터 | - |
| `--config` | 설정 파일 경로 | - |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | `/mnt/data` |
| `--host` | CVAT 서버 URL | `http://localhost:8080` |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

#### Organization 멤버 역할 및 Task 가시성

Organization에 Task를 할당할 때, 멤버의 **역할(role)**에 따라 Task 가시성이 달라집니다.

| 역할 | Task 가시성 | 설명 |
|------|------------|------|
| `worker` | **자신에게 할당된 task만** | 가장 제한적인 권한 |
| `supervisor` | **자신에게 할당된 task만** | worker와 동일한 가시성 |
| `maintainer` | **Organization의 모든 task** ✓ | Task 생성/수정/삭제 가능 |
| `owner` | **Organization의 모든 task** | 전체 관리 권한 |

**중요:** 멤버가 Organization의 **모든 Task를 볼 수 있으려면** `maintainer` 이상의 역할이 필요합니다.

`setup_cvat.sh`나 `setup_ielab_production.sh` 스크립트에서 유저 생성 시 역할을 `maintainer`로 설정해야 합니다.

---

## Python 스크립트

### 1. create_multisensor_home_tasks.py

**Multisensor Home 데이터셋에서 Multiview Task를 생성합니다.**

```bash
# 모든 세트 생성
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data

# Organization 지정
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --org ielab

# 특정 세션 범위만 (새 기능)
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --sessions 00-19

# 특정 세션 개별 지정
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --sessions 00 05 10 15 20

# 특정 데이터셋만
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1

# 특정 서브디렉토리만
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --subdirs 01

# 조합 사용 (home1의 01 subdir에서 세션 00-10만)
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --subdirs 01 \
    --sessions 00-10 \
    --org team1

# dry-run 미리보기
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --dry-run

# task 수 제한
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
| `--org` | Organization slug | - |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | (필수) |
| `--datasets` | 처리할 데이터셋 | `multisensor_home1 multisensor_home2` |
| `--subdirs` | 처리할 서브디렉토리 | 자동 탐지 |
| `--sessions` | 세션 ID 필터 (범위 또는 개별) | 전체 |
| `--view-count` | 뷰 개수 | `5` |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

**세션 범위 형식:**
- 범위: `00-10` (00부터 10까지)
- 개별: `00 05 10` (공백 구분)
- 혼합: `00-05 10 15-20`

---

### 2. create_mmoffice_tasks.py

**MMOffice 데이터셋에서 Multiview Task를 생성합니다.**

```bash
# 모든 세트 생성
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data

# Organization 지정
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --org ielab

# 특정 세션 범위만 (새 기능)
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --sessions 01-04

# 특정 split-ids만 (새 기능)
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --split-ids 5 6

# split-ids 범위 지정
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --split-ids 5-7

# 조합 사용 (split-ids 5,6에서 세션 01-06만)
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --split-ids 5 6 \
    --sessions 01-06 \
    --org team1

# 특정 split만 (test 또는 train)
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --splits train

# dry-run 미리보기
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --dry-run

# task 수 제한
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
| `--org` | Organization slug | - |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | (필수) |
| `--splits` | 처리할 split (test/train) | `test train` |
| `--split-ids` | split ID 필터 (파일명의 split[N]) | 전체 |
| `--sessions` | 세션 ID 필터 | 전체 |
| `--min-views` | 최소 뷰 개수 | `1` |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

---

### 3. check_environment.py

**환경을 체크합니다.**

```bash
python check_environment.py
```

- Python 버전 확인
- Docker 상태 확인
- CVAT 서버 연결 확인
- 필수 패키지 설치 여부 확인

---

### 4. create_multiview_task.py

**단일 Multiview Task를 생성합니다.**

```bash
python create_multiview_task.py --token YOUR_TOKEN --session 00 --part 1
```

---

### 5. create_multiview_tasks.py

**범용 배치 Task 생성 스크립트입니다.**

```bash
# 단일 task 생성
python create_multiview_tasks.py --user admin --password admin123 \
    --session-id 100 --part 1 --data-dir /path/to/videos

# 배치 생성 (여러 세션)
python create_multiview_tasks.py --user admin --password admin123 \
    --session-ids 100 101 102 --parts 1 2 --data-dir /path/to/videos

# 자동 탐지
python create_multiview_tasks.py --user admin --password admin123 \
    --data-dir /path/to/videos --auto-detect
```

---

### 6. quick_test.py

**대화형으로 빠르게 테스트합니다.**

```bash
python quick_test.py
```

---

### 7. insert_bbox_annotations.py (Pre-annotation)

**all_labels.json 또는 CSV 파일에서 Pre-annotation bbox를 삽입합니다.**

각 라벨 세그먼트의 시작/중간/끝 프레임에 bbox를 생성하여 CVAT task에 삽입합니다.

```bash
# Dry-run 미리보기 (이진분류 - 기본)
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --dry-run --limit 5

# 실제 삽입 (이진분류)
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 multisensor_home2 mmoffice

# 다중 클래스 모드 (실제 라벨 사용)
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --use-dataset-labels

# 커스텀 bbox 크기 및 분할 수
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --bbox-size 200 \
    --divisions 5

# 데이터 분할 선택 (test 데이터만)
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --split test

# test + 다중 클래스
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --split test \
    --use-dataset-labels

# 모든 사이드바 도구 활성화 (Polygon, Polyline, Points 등)
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --label-type any

# 다중 클래스 + 모든 도구 활성화
python insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --use-dataset-labels \
    --label-type any
```

**지원 데이터 형식:**

| 데이터셋 | 파일 형식 | 시간 단위 |
|----------|----------|----------|
| multisensor_home1/2 | `all_labels.json` | 초 (seconds) |
| mmoffice (test) | `testlabel/recidXXX.csv` | 프레임 (frames) |

**라벨 모드:**

| 모드 | 옵션 | 설명 |
|------|------|------|
| 이진분류 (기본) | `--label Sound` | 모든 bbox에 단일 "Sound" 라벨 적용 |
| 다중 클래스 | `--use-dataset-labels` | 데이터셋의 실제 클래스 라벨 사용 |

**다중 클래스 모드 (`--use-dataset-labels`):**
- 세그먼트별 모든 라벨에 대해 bbox 생성
- 예: `["Sitdown", "UsePhone"]` + 3 frames = 6 shapes (각 라벨 × 각 프레임)
- Task에 없는 라벨은 자동으로 생성 (PATCH /api/tasks/{id})
- multisensor_home: `Sitdown`, `Standup`, `Eat`, `Drink`, `ReadBook` 등 16개
- mmoffice: `class_1`, `class_2`, ... `class_12` 형태

**옵션:**
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--user`, `-u` | CVAT 사용자명 | (필수) |
| `--password`, `-p` | CVAT 비밀번호 | (필수) |
| `--host` | CVAT 서버 URL | `http://localhost:8080` |
| `--org` | Organization slug | - |
| `--data-dir`, `-d` | 데이터셋 루트 경로 | (필수) |
| `--datasets` | 처리할 데이터셋 | `multisensor_home1 multisensor_home2 mmoffice` |
| `--fps` | FPS (시간→프레임 변환용) | `30` |
| `--bbox-size` | Bbox 크기 (픽셀) | `100` |
| `--divisions` | 세그먼트당 bbox 분할 수 | `3` (start, mid, end) |
| `--view-count` | 뷰 개수 | `5` |
| `--label` | 라벨 이름 (이진분류 시) | `Sound` |
| `--use-dataset-labels` | 다중 클래스 모드 활성화 | `false` |
| `--split` | 데이터 분할: `test`, `train`, `all` | `all` |
| `--label-type` | 라벨 타입 (사이드바 도구 결정) | `rectangle` |
| `--limit` | 최대 처리 task 수 | 무제한 |
| `--dry-run` | 실제 삽입 없이 미리보기 | - |

**label-type 옵션 (사이드바 도구 제어):**

| label-type | 사이드바 도구 | 설명 |
|------------|-------------|------|
| `rectangle` (기본) | Rectangle만 | Bbox 라벨링에 적합 |
| `any` | 전체 (Rectangle, Polygon, Polyline, Points, Ellipse, Cuboid, Mask, Skeleton) | 다양한 Shape 라벨링 필요 시 |
| `polygon` | Polygon만 | 폴리곤 라벨링 전용 |
| `polyline` | Polyline만 | 폴리라인 라벨링 전용 |

**참고:** `--label-type`은 사이드바에 **어떤 도구를 보여줄지**만 결정합니다. 삽입되는 pre-annotation의 실제 형태는 항상 Rectangle(bbox)입니다.

**divisions 옵션:**
| divisions | 분할 비율 | 예시 (start=0s, end=10s, fps=30) |
|-----------|----------|----------------------------------|
| 2 | 0%, 100% | frames: [0, 300] |
| 3 (기본값) | 0%, 50%, 100% | frames: [0, 150, 300] |
| 5 | 0%, 25%, 50%, 75%, 100% | frames: [0, 75, 150, 225, 300] |

---

### 8. insert_prelabels.sh (Shell wrapper)

**insert_bbox_annotations.py의 Shell wrapper입니다.**

```bash
./insert_prelabels.sh --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 multisensor_home2
```

모든 옵션은 Python 스크립트에 그대로 전달됩니다.

---

## Organization (팀 공유 기능)

### Organization 생성 방법

1. **스크립트 사용 (권장):** `setup_cvat.sh` 실행 시 대화형으로 생성
2. **CVAT UI 사용:** 로그인 → 우측 상단 사용자 메뉴 → Organization → Create

### 멤버 초대

1. CVAT 접속 후 로그인
2. 우측 상단 사용자 메뉴 → Organization → [Organization 이름]
3. Members → Invite

### Task를 Organization에 할당

모든 스크립트에서 `--org` 옵션으로 Organization을 지정할 수 있습니다.

```bash
# 전체 Task를 하나의 org에
./create_all_tasks.sh --user admin --password admin123 --org ielab

# 범위별로 다른 org에 할당
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 00-19 --org team1
./assign_tasks_to_orgs.sh --user admin --password admin123 \
    --dataset home --sessions 20-39 --org team2
```

---

## 전제 조건

1. CVAT 서버가 실행 중이어야 함 (`http://localhost:8080`)
2. Python 3.8 이상
3. 필수 패키지: `requests`

```bash
pip install requests
```

---

## 데이터셋 요약

| 데이터셋 | 세션 범위 | 세트 수 | 뷰 수 |
|----------|----------|---------|-------|
| Multisensor Home1/01 | 00-24 | 50 (25 sessions × 2 parts) | 5 |
| Multisensor Home1/02 | 25-58 | 68 (34 sessions × 2 parts) | 5 |
| Multisensor Home2/01 | 00-30 | 62 (31 sessions × 2 parts) | 5 |
| Multisensor Home2/02 | 31-61 | 62 (31 sessions × 2 parts) | 5 |
| MMOffice Train | 01-12 × split2-7 | ~946 | 4 |

---

## 워크플로우 예시

### 1. 초기 설정 + 전체 Task 생성

```bash
# 1. 초기 설정 (Superuser, Organization, Users)
./scripts/init/setup_cvat.sh

# 2. 전체 Task 생성
./scripts/init/create_all_tasks.sh \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --org ielab
```

### 2. 팀별 Task 분배

```bash
# assignments.txt 파일 생성
cat > assignments.txt << 'EOF'
# Team1: Home1 전반부
home:00-29:team1:datasets=multisensor_home1

# Team2: Home1 후반부 + Home2 전반부
home:30-58:team2:datasets=multisensor_home1
home:00-30:team2:datasets=multisensor_home2

# Team3: Home2 후반부
home:31-61:team3:datasets=multisensor_home2

# MMOffice 분배
mmoffice:01-04:team1
mmoffice:05-08:team2
mmoffice:09-12:team3
EOF

# 일괄 할당
./scripts/init/assign_tasks_to_orgs.sh \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --config assignments.txt
```

### 3. 특정 범위만 빠르게 생성

```bash
# Home1의 세션 00-10만 빠르게 테스트
python scripts/init/create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --datasets multisensor_home1 \
    --sessions 00-10 \
    --org ielab
```

---

## 프로덕션 배포 (setup_ielab_production.sh)

EC2 서버 배포를 위한 전용 스크립트입니다.

### 균등 분배 설정

| Organization | 총 Task | Home1 | Home2 | MMOffice |
|--------------|---------|-------|-------|----------|
| worker01 | 524 | 59 | 61 | 404 |
| worker02 | 523 | 58 | 61 | 404 |

### 옵션

| 옵션 | 설명 |
|------|------|
| `--local` | 로컬 테스트 모드 (localhost:8080) |
| `--multi-class` | 다중 클래스 라벨 사용 (기본: 이진분류 Sound) |
| `--split VALUE` | 데이터 분할 선택: `test`, `train`, `all` (기본: all) |
| `--label-type TYPE` | 라벨 타입: `rectangle`, `any` 등 (기본: rectangle). `any` 사용 시 모든 도구 활성화 |

### 데이터 분할 (--split)

| 값 | 설명 | 사용 파일 |
|----|------|----------|
| `test` | test 데이터만 처리 | `test.json`, `testlabel/` |
| `train` | train 데이터만 처리 | `train.json` (mmoffice는 미지원) |
| `all` (기본) | 전체 데이터 처리 | `all_labels.json` |

### 사용법

```bash
# EC2 서버에서 실행
cd /home/ubuntu/cvat-multiview/scripts/init

# 전체 설정 (이진분류 - 기본)
./setup_ielab_production.sh all

# 전체 설정 (다중 클래스)
./setup_ielab_production.sh --multi-class all

# 개별 단계 실행
./setup_ielab_production.sh setup       # Superuser, Org, User 생성
./setup_ielab_production.sh tasks       # Task 생성
./setup_ielab_production.sh prelabels   # Pre-annotation (이진분류)
./setup_ielab_production.sh --multi-class prelabels  # Pre-annotation (다중 클래스)
./setup_ielab_production.sh assign      # Task 조직 할당
./setup_ielab_production.sh verify      # 설정 검증

# 데이터 초기화
./setup_ielab_production.sh reset

# 계정 정보 확인
./setup_ielab_production.sh info

# 로컬 테스트
./setup_ielab_production.sh --local all
./setup_ielab_production.sh --local --multi-class all

# 데이터 분할 옵션 사용
./setup_ielab_production.sh --split test all           # test 데이터만
./setup_ielab_production.sh --split train all          # train 데이터만
./setup_ielab_production.sh --split test --multi-class all  # test + 다중 클래스
./setup_ielab_production.sh --local --split test --multi-class all  # 로컬 test + 다중 클래스
./setup_ielab_production.sh --label-type any all                   # 모든 도구 활성화
./setup_ielab_production.sh --local --label-type any --multi-class all  # 로컬 + 다중 클래스 + 모든 도구
```

### Pre-annotation 라벨 모드

| 모드 | 옵션 | 라벨 예시 |
|------|------|----------|
| 이진분류 (기본) | - | `Sound` |
| 다중 클래스 | `--multi-class` | `Sitdown`, `Standup`, `ReadBook`, `class_1`~`class_12` |

### Phase별 데이터 삽입

test와 train을 **별도 실행**하여 단계적으로 삽입할 수 있습니다.
기존 task가 있으면 자동으로 **스킵**되므로 중복 생성 걱정 없이 추가 삽입 가능합니다.

```bash
# Phase 1: test 데이터만 삽입
./setup_ielab_production.sh --local --split test all

# Phase 2: train 데이터 추가 삽입 (기존 test task는 스킵)
./setup_ielab_production.sh --local --split train all
```

**Phase별 결과 예시:**

| Phase | 명령어 | Tasks | Pre-annotation |
|-------|--------|-------|----------------|
| 1 | `--split test all` | 327 | 7,050 shapes |
| 2 | `--split train all` | +720 | +3,835 shapes |
| **합계** | - | **1,047** | **10,885 shapes** |

**중복 Task 스킵 기능:**
- `create_multisensor_home_tasks.py`와 `create_mmoffice_tasks.py`가 기존 task 존재 여부를 확인
- 동일한 이름의 task가 있으면 `[SKIP] Task already exists: ID xxx` 메시지 출력 후 스킵
- Phase 1의 pre-annotation이 Phase 2 실행 시에도 유지됨
