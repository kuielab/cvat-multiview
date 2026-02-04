#!/bin/bash
#
# IELAB CVAT Production Setup Script
#
# 전체 프로세스:
#   1. Superuser 생성
#   2. Organization 및 User 생성
#   3. Task 생성 (home1, home2, mmoffice)
#   4. Pre-annotation 삽입 (이진분류 또는 다중 클래스)
#   5. Task를 조직에 정확히 절반씩 할당
#
# ============================================================================
# 옵션 설명
# ============================================================================
#
#   --local          로컬 테스트 모드 (localhost:8080, 기본: EC2 프로덕션)
#   --multi-class    다중 클래스 라벨 사용 (기본: 이진분류 Sound)
#   --split VALUE    데이터 분할 선택: test, train, all (기본: all)
#
# ============================================================================
# 사용 예시
# ============================================================================
#
# [프로덕션 (EC2)]
#
#   # 전체 프로세스 실행
#   ./setup_ielab_production.sh all                              # 이진분류 (기본)
#   ./setup_ielab_production.sh --multi-class all                # 다중 클래스
#   ./setup_ielab_production.sh --split test all                 # test 데이터만
#   ./setup_ielab_production.sh --split test --multi-class all   # test + 다중 클래스
#   ./setup_ielab_production.sh --split train --multi-class all  # train + 다중 클래스
#
#   # 개별 단계 실행
#   ./setup_ielab_production.sh setup                        # Superuser, Org, User 생성
#   ./setup_ielab_production.sh tasks                        # Task 생성
#   ./setup_ielab_production.sh prelabels                    # Pre-annotation (이진분류)
#   ./setup_ielab_production.sh --multi-class prelabels      # Pre-annotation (다중 클래스)
#   ./setup_ielab_production.sh --split test prelabels       # Pre-annotation (test만)
#   ./setup_ielab_production.sh assign                       # Task 조직 할당
#   ./setup_ielab_production.sh verify                       # 설정 검증
#   ./setup_ielab_production.sh info                         # 계정 정보 확인
#
# [로컬 테스트]
#
#   # 전체 프로세스 실행
#   ./setup_ielab_production.sh --local all                              # 이진분류 (기본)
#   ./setup_ielab_production.sh --local --multi-class all                # 다중 클래스
#   ./setup_ielab_production.sh --local --split test all                 # test 데이터만
#   ./setup_ielab_production.sh --local --split test --multi-class all   # test + 다중 클래스
#
#   # 데이터 초기화 후 재설정
#   ./setup_ielab_production.sh --local reset
#   ./setup_ielab_production.sh --local --split test --multi-class all
#
#   # 개별 단계 실행
#   ./setup_ielab_production.sh --local setup
#   ./setup_ielab_production.sh --local tasks
#   ./setup_ielab_production.sh --local --split test --multi-class prelabels
#   ./setup_ielab_production.sh --local assign
#   ./setup_ielab_production.sh --local verify
#
# ============================================================================
# Pre-annotation 옵션 상세
# ============================================================================
#
# [라벨 모드 (--multi-class)]
#   - 이진분류 (기본): 모든 bbox에 단일 "Sound" 라벨 적용
#   - 다중 클래스: 데이터셋의 실제 클래스 라벨 사용
#     - multisensor_home: Sitdown, Standup, Eat, Drink, ReadBook, UseLaptop 등 16개
#     - mmoffice: class_1, class_2, ... class_12
#
# [데이터 분할 (--split)]
#   - test: test 데이터만 처리
#     - multisensor_home: test.json 사용
#     - mmoffice: testlabel/*.csv 사용
#   - train: train 데이터만 처리
#     - multisensor_home: train.json 사용
#     - mmoffice: trainlabel 없음 → 스킵
#   - all (기본): 전체 데이터 처리
#     - multisensor_home: all_labels.json 사용
#     - mmoffice: testlabel/*.csv 사용 (train 라벨 없음)
#
#

set -e

# ============================================================================
# 기본 설정
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 환경 설정 (기본값: 프로덕션)
ENV_MODE="production"

# 프로덕션 설정
PROD_HOST="http://3.36.160.76:8080"
PROD_HOST_IP="3.36.160.76"
PROD_DIR="/home/ubuntu/cvat-multiview"
PROD_DATA_DIR="/mnt/data"

# 로컬 설정
LOCAL_HOST="http://localhost:8080"
LOCAL_HOST_IP="localhost"
LOCAL_DIR="$SCRIPT_DIR/../.."
LOCAL_DATA_DIR="C:/Users/kimsehun/Desktop/proj/ielab/dataset"

# 현재 환경 변수 (스크립트 실행 시 설정됨)
CVAT_HOST=""
CVAT_HOST_IP=""
CVAT_DIR=""
DATA_DIR=""

# Superadmin 계정
SUPERADMIN_USER="superadmin"
SUPERADMIN_PASS="admin1234"
SUPERADMIN_EMAIL="superadmin@ielab.com"

# Organizations
ORG1="worker01"
ORG2="worker02"

# Users
USER1_NAME="worker01"
USER1_PASS="IELab@2026!Lim"
USER1_EMAIL="worker01@ielab.com"
USER1_FIRST="Worker01"
USER1_LAST="Lim"

USER2_NAME="worker02"
USER2_PASS="IELab@2026!Song"
USER2_EMAIL="worker02@ielab.com"
USER2_FIRST="Worker02"
USER2_LAST="Song"

# Pre-annotation 설정
BBOX_SIZE=300
DIVISIONS=3
FPS=30
USE_DATASET_LABELS=false  # true: 다중 클래스, false: 이진분류 (Sound)
DATA_SPLIT="all"          # "test", "train", "all"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}============================================================${NC}\n"
}

# ============================================================================
# 환경 설정 함수
# ============================================================================
set_environment() {
    if [[ "$ENV_MODE" == "local" ]]; then
        CVAT_HOST="$LOCAL_HOST"
        CVAT_HOST_IP="$LOCAL_HOST_IP"
        CVAT_DIR="$LOCAL_DIR"
        DATA_DIR="$LOCAL_DATA_DIR"
        # 로컬에서는 간단한 비밀번호 사용
        SUPERADMIN_PASS="admin1234"
    else
        CVAT_HOST="$PROD_HOST"
        CVAT_HOST_IP="$PROD_HOST_IP"
        CVAT_DIR="$PROD_DIR"
        DATA_DIR="$PROD_DATA_DIR"
        SUPERADMIN_PASS="ielab_master_2026"
    fi

    log_info "환경: $ENV_MODE"
    log_info "CVAT Host: $CVAT_HOST"
    log_info "Data Dir: $DATA_DIR"
}

# ============================================================================
# Python 찾기
# ============================================================================
find_python() {
    local python_paths=("python3" "python" "/usr/bin/python3" "/c/Python311/python.exe")
    for py in "${python_paths[@]}"; do
        if command -v "$py" &> /dev/null; then
            if "$py" -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

# ============================================================================
# Step 1: Superuser 생성
# ============================================================================
create_superuser() {
    log_step "Step 1: Superuser 생성"

    log_info "Docker 컨테이너 확인 중..."

    # 환경에 따라 docker compose 명령 결정
    local DOCKER_CMD="docker compose"
    if [[ "$ENV_MODE" != "local" ]]; then
        # 프로덕션: CVAT_DIR에서 실행
        DOCKER_CMD="docker compose -f $CVAT_DIR/docker-compose.yml"
    fi

    # 컨테이너 상태 확인
    if ! docker ps 2>/dev/null | grep -q "cvat_server"; then
        log_error "cvat_server 컨테이너가 실행 중이 아닙니다."
        exit 1
    fi
    log_info "cvat_server 컨테이너 실행 중"

    log_info "Superuser '$SUPERADMIN_USER' 생성 중..."
    docker exec -i cvat_server python manage.py shell << PYTHON_EOF
from django.contrib.auth.models import User

username = '$SUPERADMIN_USER'
email = '$SUPERADMIN_EMAIL'
password = '$SUPERADMIN_PASS'

try:
    user = User.objects.get(username=username)
    user.set_password(password)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    print(f'[OK] Superuser {username} password reset')
except User.DoesNotExist:
    user = User.objects.create_superuser(username=username, email=email, password=password)
    print(f'[OK] Superuser {username} created')
PYTHON_EOF
}

# ============================================================================
# Superadmin 로그인
# ============================================================================
login_superadmin() {
    # Windows 호환 임시 파일 경로
    if [[ -n "${TEMP:-}" ]]; then
        COOKIE_FILE="${TEMP}/cvat_cookies_$$.txt"
    else
        COOKIE_FILE="/tmp/cvat_cookies_$$.txt"
    fi

    log_info "Superadmin 로그인 중..."
    curl -s -c "$COOKIE_FILE" "$CVAT_HOST/api/auth/login" > /dev/null
    CSRF_TOKEN=$(grep csrftoken "$COOKIE_FILE" 2>/dev/null | awk '{print $NF}')

    LOGIN_RESP=$(curl -s -b "$COOKIE_FILE" -c "$COOKIE_FILE" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $CSRF_TOKEN" \
        -d "{\"username\": \"$SUPERADMIN_USER\", \"password\": \"$SUPERADMIN_PASS\"}" \
        "$CVAT_HOST/api/auth/login")

    if ! echo "$LOGIN_RESP" | grep -q "key"; then
        log_error "Superadmin 로그인 실패: $LOGIN_RESP"
        rm -f "$COOKIE_FILE"
        exit 1
    fi
    log_info "로그인 성공"

    CSRF_TOKEN=$(grep csrftoken "$COOKIE_FILE" | awk '{print $NF}')

    # Windows 경로를 Unix 스타일로 변환 (Python에서 사용)
    COOKIE_FILE_UNIX=$(echo "$COOKIE_FILE" | sed 's|\\|/|g')
}

# ============================================================================
# Step 2: Organization 및 User 생성
# ============================================================================
setup_orgs_and_users() {
    log_step "Step 2: Organization 및 User 생성"

    login_superadmin

    # Organization 생성
    log_info "Organization '$ORG1' 생성 중..."
    curl -s -b "$COOKIE_FILE" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $CSRF_TOKEN" \
        -d "{\"slug\": \"$ORG1\", \"name\": \"$ORG1\"}" \
        "$CVAT_HOST/api/organizations" > /dev/null
    log_info "Organization '$ORG1' 생성 완료"

    log_info "Organization '$ORG2' 생성 중..."
    curl -s -b "$COOKIE_FILE" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $CSRF_TOKEN" \
        -d "{\"slug\": \"$ORG2\", \"name\": \"$ORG2\"}" \
        "$CVAT_HOST/api/organizations" > /dev/null
    log_info "Organization '$ORG2' 생성 완료"

    # User 생성
    log_info "User '$USER1_NAME' 생성 중..."
    curl -s -H "Content-Type: application/json" \
        -d "{\"username\": \"$USER1_NAME\", \"email\": \"$USER1_EMAIL\", \"password1\": \"$USER1_PASS\", \"password2\": \"$USER1_PASS\", \"first_name\": \"$USER1_FIRST\", \"last_name\": \"$USER1_LAST\"}" \
        "$CVAT_HOST/api/auth/register" > /dev/null
    log_info "User '$USER1_NAME' 생성 완료"

    log_info "User '$USER2_NAME' 생성 중..."
    curl -s -H "Content-Type: application/json" \
        -d "{\"username\": \"$USER2_NAME\", \"email\": \"$USER2_EMAIL\", \"password1\": \"$USER2_PASS\", \"password2\": \"$USER2_PASS\", \"first_name\": \"$USER2_FIRST\", \"last_name\": \"$USER2_LAST\"}" \
        "$CVAT_HOST/api/auth/register" > /dev/null
    log_info "User '$USER2_NAME' 생성 완료"

    rm -f "$COOKIE_FILE"

    # Django shell로 멤버십 추가 (docker exec 사용 - 모든 환경에서 동작)
    log_info "User '$USER1_NAME'을 Organization '$ORG1'에 추가 중..."
    docker exec -i cvat_server python manage.py shell << PYTHON_EOF
from django.contrib.auth.models import User
from cvat.apps.organizations.models import Organization, Membership, Invitation

user = User.objects.get(username='$USER1_NAME')
org = Organization.objects.get(slug='$ORG1')
Invitation.objects.filter(membership__user=user, membership__organization=org).delete()
membership, created = Membership.objects.get_or_create(
    user=user, organization=org,
    defaults={'role': 'maintainer', 'is_active': True}
)
if not created:
    membership.is_active = True
    membership.save()
Invitation.objects.filter(membership=membership).delete()
print(f'[OK] {user.username} added to {org.slug} (active)')
PYTHON_EOF

    log_info "User '$USER2_NAME'을 Organization '$ORG2'에 추가 중..."
    docker exec -i cvat_server python manage.py shell << PYTHON_EOF
from django.contrib.auth.models import User
from cvat.apps.organizations.models import Organization, Membership, Invitation

user = User.objects.get(username='$USER2_NAME')
org = Organization.objects.get(slug='$ORG2')
Invitation.objects.filter(membership__user=user, membership__organization=org).delete()
membership, created = Membership.objects.get_or_create(
    user=user, organization=org,
    defaults={'role': 'maintainer', 'is_active': True}
)
if not created:
    membership.is_active = True
    membership.save()
Invitation.objects.filter(membership=membership).delete()
print(f'[OK] {user.username} added to {org.slug} (active)')
PYTHON_EOF

    log_info "멤버 추가 완료"
}

# ============================================================================
# Step 3: Task 생성
# ============================================================================
create_tasks() {
    log_step "Step 3: Task 생성 (home1, home2, mmoffice)"

    PYTHON=$(find_python)
    if [[ -z "$PYTHON" ]]; then
        log_error "Python 3.8 이상이 필요합니다."
        exit 1
    fi
    log_info "Python: $PYTHON"

    COMMON_OPTS="--user $SUPERADMIN_USER --password $SUPERADMIN_PASS --host $CVAT_HOST --data-dir $DATA_DIR"

    # Multisensor Home Tasks
    if [[ -d "$DATA_DIR/multisensor_home1" ]] || [[ -d "$DATA_DIR/multisensor_home2" ]]; then
        log_info "========== Multisensor Home Tasks 생성 =========="
        $PYTHON "$SCRIPT_DIR/create_multisensor_home_tasks.py" $COMMON_OPTS
    fi

    # MMOffice Tasks
    if [[ -d "$DATA_DIR/mmoffice" ]]; then
        log_info "========== MMOffice Tasks 생성 =========="
        # DATA_SPLIT에 따라 --splits 옵션 설정
        local MMOFFICE_SPLITS=""
        case "$DATA_SPLIT" in
            test)  MMOFFICE_SPLITS="--splits test" ;;
            train) MMOFFICE_SPLITS="--splits train" ;;
            all)   MMOFFICE_SPLITS="--splits test train" ;;
        esac
        $PYTHON "$SCRIPT_DIR/create_mmoffice_tasks.py" $COMMON_OPTS $MMOFFICE_SPLITS
    fi

    log_info "Task 생성 완료"
}

# ============================================================================
# Step 4: Pre-annotation 삽입
# ============================================================================
insert_prelabels() {
    local label_mode="Binary (Sound)"
    if [[ "$USE_DATASET_LABELS" == "true" ]]; then
        label_mode="Multi-class (dataset labels)"
    fi
    log_step "Step 4: Pre-annotation 삽입 (bbox-size: ${BBOX_SIZE}, mode: ${label_mode}, split: ${DATA_SPLIT})"

    PYTHON=$(find_python)
    if [[ -z "$PYTHON" ]]; then
        log_error "Python 3.8 이상이 필요합니다."
        exit 1
    fi

    DATASETS_TO_PROCESS=""

    # 존재하는 데이터셋만 처리
    if [[ -d "$DATA_DIR/multisensor_home1" ]]; then
        DATASETS_TO_PROCESS="$DATASETS_TO_PROCESS multisensor_home1"
    fi
    if [[ -d "$DATA_DIR/multisensor_home2" ]]; then
        DATASETS_TO_PROCESS="$DATASETS_TO_PROCESS multisensor_home2"
    fi
    if [[ -d "$DATA_DIR/mmoffice" ]]; then
        DATASETS_TO_PROCESS="$DATASETS_TO_PROCESS mmoffice"
    fi

    if [[ -z "$DATASETS_TO_PROCESS" ]]; then
        log_warn "처리할 데이터셋이 없습니다."
        return
    fi

    log_info "처리할 데이터셋:$DATASETS_TO_PROCESS"

    # 기본 옵션
    PRELABEL_OPTS="--user $SUPERADMIN_USER \
        --password $SUPERADMIN_PASS \
        --host $CVAT_HOST \
        --data-dir $DATA_DIR \
        --datasets $DATASETS_TO_PROCESS \
        --bbox-size $BBOX_SIZE \
        --divisions $DIVISIONS \
        --fps $FPS \
        --split $DATA_SPLIT"

    # 다중 클래스 모드 옵션 추가
    if [[ "$USE_DATASET_LABELS" == "true" ]]; then
        PRELABEL_OPTS="$PRELABEL_OPTS --use-dataset-labels"
    fi

    $PYTHON "$SCRIPT_DIR/insert_bbox_annotations.py" $PRELABEL_OPTS

    log_info "Pre-annotation 삽입 완료"
}

# ============================================================================
# Step 5: Task를 조직에 정확히 절반씩 할당
# ============================================================================
assign_tasks_half() {
    log_step "Step 5: Task를 조직에 정확히 절반씩 할당"

    # Django shell을 통해 직접 할당 (API는 403 에러 발생)
    log_info "Django shell을 통해 Task 할당 중..."

    docker exec -i cvat_server python manage.py shell << PYTHON_EOF
from cvat.apps.engine.models import Task
from cvat.apps.organizations.models import Organization

org1_slug = "$ORG1"
org2_slug = "$ORG2"

# 조직 조회
print("[INFO] 조직 정보 조회 중...")
try:
    org1 = Organization.objects.get(slug=org1_slug)
    org2 = Organization.objects.get(slug=org2_slug)
    print(f"  {org1_slug}: ID={org1.id}")
    print(f"  {org2_slug}: ID={org2.id}")
except Organization.DoesNotExist as e:
    print(f"[ERROR] 조직을 찾을 수 없습니다: {e}")
    exit(1)

# 전체 Task 조회
print("[INFO] 전체 Task 목록 조회 중...")
all_tasks = list(Task.objects.all().order_by('id'))
print(f"  총 Task 수: {len(all_tasks)}")

# 데이터셋별로 분류
home1_tasks = [t for t in all_tasks if 'multisensor_home1' in t.name]
home2_tasks = [t for t in all_tasks if 'multisensor_home2' in t.name]
mmoffice_tasks = [t for t in all_tasks if 'mmoffice' in t.name]

print(f"  - multisensor_home1: {len(home1_tasks)} tasks")
print(f"  - multisensor_home2: {len(home2_tasks)} tasks")
print(f"  - mmoffice: {len(mmoffice_tasks)} tasks")

# 각 데이터셋을 정확히 절반으로 분배
def split_half(tasks):
    """정확히 절반으로 분할 (홀수면 앞쪽에 하나 더)"""
    mid = (len(tasks) + 1) // 2
    return tasks[:mid], tasks[mid:]

home1_org1, home1_org2 = split_half(home1_tasks)
home2_org1, home2_org2 = split_half(home2_tasks)
mmoffice_org1, mmoffice_org2 = split_half(mmoffice_tasks)

org1_tasks = home1_org1 + home2_org1 + mmoffice_org1
org2_tasks = home1_org2 + home2_org2 + mmoffice_org2

print(f"\n[INFO] 할당 계획:")
print(f"  {org1_slug}: {len(org1_tasks)} tasks")
print(f"    - home1: {len(home1_org1)}, home2: {len(home2_org1)}, mmoffice: {len(mmoffice_org1)}")
print(f"  {org2_slug}: {len(org2_tasks)} tasks")
print(f"    - home1: {len(home1_org2)}, home2: {len(home2_org2)}, mmoffice: {len(mmoffice_org2)}")

# 할당 실행
def assign_to_org(tasks, org, org_name):
    success = 0
    for task in tasks:
        try:
            task.organization = org
            task.save()
            success += 1
        except Exception as e:
            print(f"  [ERROR] Task {task.id}: {e}")
    print(f"  [OK] {org_name}: {success}/{len(tasks)} tasks 할당 완료")
    return success

print(f"\n[INFO] {org1_slug}에 Task 할당 중...")
assign_to_org(org1_tasks, org1, org1_slug)

print(f"[INFO] {org2_slug}에 Task 할당 중...")
assign_to_org(org2_tasks, org2, org2_slug)

print("\n[OK] Task 할당 완료!")
print(f"  총 {len(org1_tasks) + len(org2_tasks)} tasks 할당됨")
PYTHON_EOF

    log_info "Task 할당 완료"
}

# ============================================================================
# 데이터 초기화 (기존 tasks 모두 삭제)
# ============================================================================
reset_all_data() {
    log_step "데이터 초기화 (모든 Task 삭제)"

    log_warn "이 작업은 모든 Task와 Annotation을 삭제합니다!"
    read -p "계속하시겠습니까? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "취소되었습니다."
        return
    fi

    PYTHON=$(find_python)

    $PYTHON << PYTHON_EOF
import requests

host = "$CVAT_HOST"
username = "$SUPERADMIN_USER"
password = "$SUPERADMIN_PASS"

# 직접 로그인
session = requests.Session()
session.get(f"{host}/api/auth/login")
csrf_token = session.cookies.get('csrftoken')
headers = {'X-CSRFToken': csrf_token, 'Content-Type': 'application/json'}
resp = session.post(f"{host}/api/auth/login", json={"username": username, "password": password}, headers=headers)
if resp.status_code != 200:
    print(f"[ERROR] 로그인 실패: {resp.text}")
    exit(1)
csrf_token = session.cookies.get('csrftoken')
headers = {'X-CSRFToken': csrf_token}

# 전체 Task 삭제
print("[INFO] 전체 Task 삭제 중...")
page = 1
total_deleted = 0
while True:
    resp = session.get(f"{host}/api/tasks?page=1&page_size=100", headers=headers)
    data = resp.json()
    tasks = data.get('results', [])
    if not tasks:
        break
    for task in tasks:
        del_resp = session.delete(f"{host}/api/tasks/{task['id']}", headers=headers)
        if del_resp.status_code in [200, 204]:
            total_deleted += 1
            print(f"  Deleted: {task['name']}")
        else:
            print(f"  [WARN] Failed to delete {task['id']}: {del_resp.status_code}")

print(f"\n[OK] {total_deleted} tasks 삭제 완료")
PYTHON_EOF

    log_info "데이터 초기화 완료"
}

# ============================================================================
# 검증: 최종 결과 확인
# ============================================================================
verify_setup() {
    log_step "검증: 최종 설정 확인"

    PYTHON=$(find_python)

    $PYTHON << PYTHON_EOF
import requests

host = "$CVAT_HOST"
username = "$SUPERADMIN_USER"
password = "$SUPERADMIN_PASS"
org1 = "$ORG1"
org2 = "$ORG2"

# 직접 로그인
session = requests.Session()
session.get(f"{host}/api/auth/login")
csrf_token = session.cookies.get('csrftoken')
headers = {'X-CSRFToken': csrf_token, 'Content-Type': 'application/json'}
resp = session.post(f"{host}/api/auth/login", json={"username": username, "password": password}, headers=headers)
if resp.status_code != 200:
    print(f"[ERROR] 로그인 실패: {resp.text}")
    exit(1)
csrf_token = session.cookies.get('csrftoken')
headers = {'X-CSRFToken': csrf_token}

print("=" * 60)
print("  IELAB CVAT 설정 검증 결과")
print("=" * 60)

# 1. 조직별 Task 수 확인
print("\n[1] 조직별 Task 수")
orgs_resp = session.get(f"{host}/api/organizations", headers=headers)
orgs = orgs_resp.json().get('results', [])

for org in orgs:
    tasks_resp = session.get(f"{host}/api/tasks?org={org['slug']}&page_size=1000", headers=headers)
    tasks = tasks_resp.json().get('results', [])

    # 데이터셋별 분류
    home1 = len([t for t in tasks if 'multisensor_home1' in t['name']])
    home2 = len([t for t in tasks if 'multisensor_home2' in t['name']])
    mmoffice = len([t for t in tasks if 'mmoffice' in t['name']])

    print(f"  {org['slug']}: {len(tasks)} tasks")
    print(f"    - home1: {home1}, home2: {home2}, mmoffice: {mmoffice}")

# 2. Pre-annotation 확인 (샘플)
print("\n[2] Pre-annotation 확인 (샘플)")
tasks_resp = session.get(f"{host}/api/tasks?page_size=5", headers=headers)
tasks = tasks_resp.json().get('results', [])

total_shapes = 0
for task in tasks[:3]:
    jobs_resp = session.get(f"{host}/api/jobs?task_id={task['id']}", headers=headers)
    jobs = jobs_resp.json().get('results', [])
    if jobs:
        job_id = jobs[0]['id']
        ann_resp = session.get(f"{host}/api/jobs/{job_id}/annotations", headers=headers)
        ann = ann_resp.json()
        shapes = len(ann.get('shapes', []))
        total_shapes += shapes
        print(f"  {task['name']}: {shapes} shapes")

print("\n[3] 요약")
# 전체 Task 수
all_tasks_resp = session.get(f"{host}/api/tasks?page_size=1", headers=headers)
total_tasks = all_tasks_resp.json().get('count', 0)
print(f"  총 Task 수: {total_tasks}")
print(f"  샘플 shapes: {total_shapes} (위 3개 task 합계)")

print("\n" + "=" * 60)
print("  검증 완료")
print("=" * 60)
PYTHON_EOF
}

# ============================================================================
# 사용법
# ============================================================================
usage() {
    cat << EOF
Usage: $0 [OPTIONS] COMMAND

IELAB CVAT Production 설정 스크립트

옵션:
  --local           로컬 테스트 모드 (localhost:8080)
  --multi-class     다중 클래스 라벨 사용 (기본: 이진분류 Sound)
  --split VALUE     데이터 분할 선택: test, train, all (기본: all)
  --help, -h        도움말 출력

Commands:
  all             전체 프로세스 실행 (setup → tasks → prelabels → assign)
  setup           Step 1-2: Superuser, Organization, User 생성
  tasks           Step 3: Task 생성
  prelabels       Step 4: Pre-annotation 삽입
  assign          Step 5: Task 조직 할당 (정확히 절반)
  verify          설정 검증
  reset           모든 데이터 초기화 (주의!)
  info            계정 정보 출력

예시:
  # 로컬 테스트 전체 실행 (이진분류)
  $0 --local all

  # 로컬 테스트 전체 실행 (다중 클래스)
  $0 --local --multi-class all

  # 프로덕션 전체 실행
  $0 all

  # 개별 단계 실행
  $0 --local setup
  $0 --local tasks
  $0 --local prelabels
  $0 --local --multi-class prelabels  # 다중 클래스 pre-annotation
  $0 --local assign
  $0 --local verify

  # 데이터 분할 옵션
  $0 --local --split test all         # test 데이터만 처리
  $0 --local --split train all        # train 데이터만 처리
  $0 --local --split test --multi-class all  # test + 다중 클래스

EOF
    exit 1
}

# ============================================================================
# 계정 정보 출력
# ============================================================================
print_info() {
    log_step "계정 정보"

    echo -e "${CYAN}[환경]${NC}"
    echo "  Mode: $ENV_MODE"
    echo "  CVAT Host: $CVAT_HOST"
    echo "  Data Dir: $DATA_DIR"
    echo ""
    echo -e "${CYAN}[Superadmin]${NC}"
    echo "  ID: $SUPERADMIN_USER"
    echo "  PW: $SUPERADMIN_PASS"
    echo ""
    echo -e "${CYAN}[Organizations]${NC}"
    echo "  - $ORG1"
    echo "  - $ORG2"
    echo ""
    echo -e "${CYAN}[Users]${NC}"
    echo "  - $USER1_NAME / $USER1_PASS → $ORG1"
    echo "  - $USER2_NAME / $USER2_PASS → $ORG2"
    echo ""
    echo -e "${CYAN}[Pre-annotation 설정]${NC}"
    echo "  Bbox Size: ${BBOX_SIZE}x${BBOX_SIZE}"
    echo "  Divisions: $DIVISIONS (start, mid, end)"
    echo "  FPS: $FPS"
    echo "  Data Split: $DATA_SPLIT"
    if [[ "$USE_DATASET_LABELS" == "true" ]]; then
        echo "  Label Mode: Multi-class (dataset labels)"
    else
        echo "  Label Mode: Binary (Sound)"
    fi
}

# ============================================================================
# 메인
# ============================================================================
main() {
    # 옵션 파싱
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --local)
                ENV_MODE="local"
                shift
                ;;
            --multi-class)
                USE_DATASET_LABELS=true
                shift
                ;;
            --split)
                DATA_SPLIT="$2"
                if [[ ! "$DATA_SPLIT" =~ ^(test|train|all)$ ]]; then
                    log_error "Invalid split value: $DATA_SPLIT (must be test, train, or all)"
                    exit 1
                fi
                shift 2
                ;;
            --help|-h)
                usage
                ;;
            *)
                break
                ;;
        esac
    done

    # 환경 설정
    set_environment

    echo -e "${CYAN}"
    echo "============================================================"
    echo "  IELAB CVAT Setup Script"
    echo "  Environment: $ENV_MODE"
    echo "  Server: $CVAT_HOST"
    echo "============================================================"
    echo -e "${NC}"

    case "${1:-}" in
        all)
            create_superuser
            setup_orgs_and_users
            create_tasks
            insert_prelabels
            assign_tasks_half
            verify_setup
            print_info
            ;;
        setup)
            create_superuser
            setup_orgs_and_users
            print_info
            ;;
        tasks)
            create_tasks
            ;;
        prelabels)
            insert_prelabels
            ;;
        assign)
            assign_tasks_half
            ;;
        verify)
            verify_setup
            ;;
        reset)
            reset_all_data
            ;;
        info)
            print_info
            ;;
        *)
            usage
            ;;
    esac

    log_step "완료"
}

main "$@"
