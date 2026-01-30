# CVAT Multiview Init Scripts

Multiview Task 생성 및 테스트를 위한 유틸리티 스크립트 모음입니다.

## 파일 위치

```
scripts/init/
├── setup_and_create_tasks.sh     # 초기 설정 + Task 생성 통합 스크립트 (권장)
├── setup_cvat.sh                 # 초기 설정만 (Superuser + Organization)
├── create_all_tasks.sh           # Task 생성 스크립트
├── create_multisensor_home_tasks.py
├── create_mmoffice_tasks.py
├── create_multiview_task.py
├── create_multiview_tasks.py
├── check_environment.py
├── quick_test.py
└── README.md
```

## 빠른 시작 (권장)

### setup_and_create_tasks.sh

**CVAT 초기 설정부터 Task 생성까지 모든 과정을 자동화하는 통합 스크립트입니다.**

다음 단계를 순서대로 수행합니다:
1. Superuser 계정 생성
2. Organization 생성 (팀원들과 Task 공유를 위해)
3. Multiview Task 일괄 생성

```bash
# CVAT 프로젝트 디렉토리에서 실행
cd /path/to/cvat-multiview

# 대화형 실행 (모든 정보 직접 입력)
./scripts/init/setup_and_create_tasks.sh

# 환경변수로 미리 설정
CVAT_HOST=http://3.36.160.76:8080 \
CVAT_USER=admin \
CVAT_PASSWORD=admin123 \
CVAT_ORG=ielab \
./scripts/init/setup_and_create_tasks.sh

# Superuser 이미 있는 경우
./scripts/init/setup_and_create_tasks.sh --skip-superuser

# dry-run으로 미리보기
./scripts/init/setup_and_create_tasks.sh --dry-run
```

**옵션:**
| 옵션 | 설명 |
|------|------|
| `--skip-superuser` | Superuser 생성 단계 건너뛰기 |
| `--dry-run` | Task 생성 미리보기 (실제 생성 안 함) |

**환경변수:**
| 환경변수 | 설명 | 기본값 |
|----------|------|--------|
| `CVAT_HOST` | CVAT 서버 URL | `http://localhost:8080` |
| `CVAT_USER` | CVAT 사용자명 | (대화형 입력) |
| `CVAT_PASSWORD` | CVAT 비밀번호 | (대화형 입력) |
| `CVAT_ORG` | Organization slug | (대화형 입력) |
| `DATA_DIR` | 데이터셋 루트 경로 | `/mnt/data` |

**실행 흐름:**
```
1. Docker/CVAT 서버 연결 확인
2. 사용자 정보 입력 (user, password, org)
3. [Step 1] Superuser 생성 (docker compose exec)
4. [Step 2] Organization 생성 (API 호출)
5. [Step 3] Task 일괄 생성 (create_all_tasks.sh 호출)
6. 완료 메시지 + 멤버 초대 안내
```

**주의:** Step 1에서 입력하는 superuser 정보와 위에서 입력한 CVAT_USER/CVAT_PASSWORD가 **동일**해야 합니다.

---

### setup_cvat.sh

**초기 설정만 수행하는 스크립트입니다. (Task 생성 제외)**

다음 기능을 대화형으로 수행합니다:
- Superuser 계정 생성
- Organization 생성 (여러 개 가능)
- 일반 유저 생성 (여러 명 가능)
- 유저를 Organization에 초대

Task 생성은 별도로 `create_all_tasks.sh`를 사용하세요.

```bash
# CVAT 프로젝트 디렉토리에서 실행
cd /path/to/cvat-multiview

# 대화형 실행
./scripts/init/setup_cvat.sh

# Superuser 이미 있는 경우
./scripts/init/setup_cvat.sh --skip-superuser

# EC2 등 다른 서버에서 실행
CVAT_HOST=http://3.36.160.76:8080 ./scripts/init/setup_cvat.sh
```

**옵션:**
| 옵션 | 설명 |
|------|------|
| `--skip-superuser` | Superuser 생성 단계 건너뛰기 |

**환경변수:**
| 환경변수 | 설명 | 기본값 |
|----------|------|--------|
| `CVAT_HOST` | CVAT 서버 URL | `http://localhost:8080` |

**실행 흐름:**
```
1. Docker/CVAT 서버 연결 확인
2. [Step 1] Superuser 생성 (docker compose exec)
3. [Step 2] Organization 생성 (여러 개 가능, 반복)
4. [Step 3] 일반 유저 생성 (여러 명 가능, 반복)
   - 각 유저를 Organization에 초대 (선택)
5. 완료 메시지 + Task 생성 명령어 안내
```

**실행 예시:**
```
$ ./scripts/init/setup_cvat.sh

============================================================
  Step 2: Organization 생성
============================================================

생성할 Organization 이름 (slug, 예: ielab): ielab
[INFO] Organization 'ielab' 생성 완료

Organization을 더 생성하시겠습니까? (y/N): y

생성할 Organization 이름: testteam
[INFO] Organization 'testteam' 생성 완료

Organization을 더 생성하시겠습니까? (y/N): n

============================================================
  Step 3: 일반 유저 생성
============================================================

일반 유저를 생성하시겠습니까? (y/N): y

--- 새 유저 정보 입력 ---
사용자명: user1
이메일: user1@test.com
비밀번호: ********
[INFO] 유저 'user1' 생성 완료

이 유저를 Organization에 초대하시겠습니까?
사용 가능한 Organization:
  1. ielab
  2. testteam
  0. 초대 안 함

선택 (번호, 여러 개는 쉼표로 구분, 예: 1,2): 1,2
[INFO] 유저 'user1'을 'ielab'에 초대 완료
[INFO] 유저 'user1'을 'testteam'에 초대 완료
```

---

### create_all_tasks.sh

**모든 데이터셋의 Multiview Task를 한 번에 생성하는 스크립트입니다.**

Multisensor Home과 MMOffice 데이터셋을 자동으로 탐지하여 task를 생성합니다.
Python 및 의존성 패키지 설치 여부를 자동으로 확인하고, 필요시 설치합니다.

```bash
# scripts/init 디렉토리에서 실행
cd /path/to/cvat-multiview/scripts/init

# 기본 실행 (모든 데이터셋)
./create_all_tasks.sh --user admin --password admin123

# Organization 지정 (팀원들과 공유)
./create_all_tasks.sh --user admin --password admin123 --org ielab

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
| `--org` | Organization slug (팀 공유용) | - |
| `--limit` | 최대 생성 task 수 | 무제한 |
| `--dry-run` | 실제 생성 없이 미리보기 | - |

**자동 처리 항목:**
- Python 3.8+ 자동 탐지
- `requests` 패키지 자동 설치
- CVAT 서버 연결 확인
- 데이터셋 존재 여부 확인

---

## Organization (팀 공유 기능)

**Organization을 사용하면 팀원들과 Task를 공유할 수 있습니다.**

### Organization 생성 방법

1. **스크립트 사용 (권장):** `setup_and_create_tasks.sh` 실행 시 자동 생성
2. **CVAT UI 사용:** 로그인 → 우측 상단 사용자 메뉴 → Organization → Create

### 멤버 초대

1. CVAT 접속 후 로그인
2. 우측 상단 사용자 메뉴 → Organization → [Organization 이름]
3. Members → Invite

### Task 생성 시 Organization 지정

모든 Task 생성 스크립트에 `--org` 옵션을 사용하면 해당 Organization에 Task가 생성되어 멤버들과 공유됩니다.

```bash
# Organization에 Task 생성
./create_all_tasks.sh --user admin --password admin123 --org ielab

# 또는 개별 스크립트 사용
python create_multisensor_home_tasks.py --user admin --password admin123 --org ielab --data-dir /mnt/data
```

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

# Organization에 생성 (팀 공유)
python create_multisensor_home_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --org ielab

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
| `--org` | Organization slug | - |
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

# Organization에 생성 (팀 공유)
python create_mmoffice_tasks.py \
    --user admin --password admin123 \
    --data-dir /mnt/data \
    --org ielab

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
| `--org` | Organization slug | - |
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
