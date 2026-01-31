#!/bin/bash
#
# CVAT Multiview 초기 설정 스크립트
#
# 이 스크립트는 다음을 순서대로 수행합니다:
#   1. Superuser 계정 생성
#   2. Organization 생성 (여러 개 가능)
#   3. 일반 유저 생성 (여러 명 가능)
#   4. 유저를 Organization에 초대
#
# Task 생성은 별도로 create_all_tasks.sh를 사용하세요.
#
# 사용법:
#   ./setup_cvat.sh
#   ./setup_cvat.sh --skip-superuser  # superuser 이미 있는 경우
#
# 환경변수로 설정 가능:
#   CVAT_HOST
#

set -e

# 기본값 설정
CVAT_HOST="${CVAT_HOST:-http://localhost:8080}"
SKIP_SUPERUSER=false

# 저장된 superuser 정보
SUPERUSER_NAME=""
SUPERUSER_PASSWORD=""

# 생성된 조직 목록
declare -a CREATED_ORGS=()

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 로그 함수
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}============================================================${NC}\n"
}

# 사용법 출력
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

CVAT Multiview 초기 설정 스크립트

이 스크립트는 다음을 순서대로 수행합니다:
  1. Superuser 계정 생성 (Docker 명령 사용)
  2. Organization 생성 (여러 개 가능)
  3. 일반 유저 생성 (여러 명 가능)
  4. 유저를 Organization에 초대

Task 생성은 별도로 create_all_tasks.sh를 사용하세요.

옵션:
  --skip-superuser    Superuser 생성 단계 건너뛰기 (이미 있는 경우)
  --help, -h          도움말 출력

환경변수:
  CVAT_HOST           CVAT 서버 URL (기본값: http://localhost:8080)

예시:
  # 대화형으로 모든 정보 입력
  $0

  # Superuser 이미 있는 경우
  $0 --skip-superuser

  # EC2에서 실행
  CVAT_HOST=http://3.36.160.76:8080 $0
EOF
    exit 1
}

# 인자 파싱
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-superuser)
            SKIP_SUPERUSER=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# 시스템 의존성 확인
check_system_dependencies() {
    log_info "시스템 의존성 확인 중..."

    local missing_deps=()

    # curl 확인
    if ! command -v curl &> /dev/null; then
        missing_deps+=("curl")
    fi

    # grep 확인
    if ! command -v grep &> /dev/null; then
        missing_deps+=("grep")
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "다음 패키지가 설치되지 않았습니다: ${missing_deps[*]}"
        log_info "설치 방법:"
        log_info "  Ubuntu/Debian: sudo apt-get install ${missing_deps[*]}"
        log_info "  CentOS/RHEL:   sudo yum install ${missing_deps[*]}"
        log_info "  macOS:         brew install ${missing_deps[*]}"
        exit 1
    fi

    log_info "시스템 의존성 확인 완료"
}

# Docker 확인
check_docker() {
    log_info "Docker 확인 중..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker가 설치되지 않았습니다."
        log_info "Docker 설치: https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! docker compose version &> /dev/null && ! docker-compose version &> /dev/null; then
        log_error "Docker Compose가 설치되지 않았습니다."
        log_info "Docker Compose 설치: https://docs.docker.com/compose/install/"
        exit 1
    fi

    if ! docker compose ps &> /dev/null; then
        log_error "Docker Compose를 실행할 수 없습니다."
        log_error "CVAT 디렉토리에서 실행하거나, docker compose가 실행 중인지 확인하세요."
        exit 1
    fi

    # cvat_server 컨테이너 확인
    if ! docker compose ps | grep -q "cvat_server.*Up"; then
        log_error "cvat_server 컨테이너가 실행 중이 아닙니다."
        log_error "먼저 'docker compose up -d'를 실행하세요."
        exit 1
    fi

    log_info "Docker 확인 완료"
}

# CVAT 서버 연결 확인
check_cvat_server() {
    log_info "CVAT 서버 연결 확인 중... ($CVAT_HOST)"

    local max_retries=5
    local retry=0

    while [[ $retry -lt $max_retries ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "$CVAT_HOST/api/server/about" 2>/dev/null | grep -qE "200|401|403"; then
            log_info "CVAT 서버 연결 성공"
            return 0
        fi

        retry=$((retry + 1))
        log_warn "연결 재시도 중... ($retry/$max_retries)"
        sleep 2
    done

    log_error "CVAT 서버에 연결할 수 없습니다: $CVAT_HOST"
    exit 1
}

# API 로그인 및 쿠키 파일 생성
api_login() {
    local username="$1"
    local password="$2"
    local cookie_file="$3"

    # CSRF 토큰 획득
    curl -s -c "$cookie_file" "$CVAT_HOST/api/auth/login" > /dev/null
    local csrf_token=$(grep csrftoken "$cookie_file" 2>/dev/null | awk '{print $NF}')

    # 로그인
    local login_response=$(curl -s -b "$cookie_file" -c "$cookie_file" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $csrf_token" \
        -d "{\"username\": \"$username\", \"password\": \"$password\"}" \
        "$CVAT_HOST/api/auth/login")

    if echo "$login_response" | grep -q "key\|token"; then
        return 0
    else
        return 1
    fi
}

# Step 1: Superuser 생성
create_superuser() {
    log_step "Step 1: Superuser 계정 생성"

    if [[ "$SKIP_SUPERUSER" == true ]]; then
        log_info "Superuser 생성 건너뛰기 (--skip-superuser)"
        echo ""
        read -p "기존 Superuser 사용자명: " SUPERUSER_NAME
        read -s -p "기존 Superuser 비밀번호: " SUPERUSER_PASSWORD
        echo ""

        # 로그인 테스트
        local cookie_file=$(mktemp)
        if api_login "$SUPERUSER_NAME" "$SUPERUSER_PASSWORD" "$cookie_file"; then
            log_info "Superuser 로그인 확인 완료"
            rm -f "$cookie_file"
        else
            log_error "Superuser 로그인 실패. 사용자명/비밀번호를 확인하세요."
            rm -f "$cookie_file"
            exit 1
        fi
        return 0
    fi

    log_info "Superuser 계정을 생성합니다."
    log_info "아래 프롬프트에서 사용자명, 이메일, 비밀번호를 입력하세요."
    echo ""

    # Interactive하게 createsuperuser 실행
    docker compose exec cvat_server python manage.py createsuperuser

    if [[ $? -eq 0 ]]; then
        log_info "Superuser 생성 완료"
        echo ""
        read -p "방금 생성한 Superuser 사용자명: " SUPERUSER_NAME
        read -s -p "방금 생성한 Superuser 비밀번호: " SUPERUSER_PASSWORD
        echo ""
    else
        log_warn "Superuser 생성 실패 또는 이미 존재합니다."
        echo ""
        read -p "기존 Superuser 사용자명: " SUPERUSER_NAME
        read -s -p "기존 Superuser 비밀번호: " SUPERUSER_PASSWORD
        echo ""
    fi
}

# Step 2: Organization 생성 (여러 개)
create_organizations() {
    log_step "Step 2: Organization 생성"

    local cookie_file=$(mktemp)

    if ! api_login "$SUPERUSER_NAME" "$SUPERUSER_PASSWORD" "$cookie_file"; then
        log_error "Superuser 로그인 실패"
        rm -f "$cookie_file"
        exit 1
    fi

    local csrf_token=$(grep csrftoken "$cookie_file" | awk '{print $NF}')

    while true; do
        echo ""
        read -p "생성할 Organization 이름 (slug, 예: ielab): " org_slug

        if [[ -z "$org_slug" ]]; then
            log_warn "Organization 이름이 비어있습니다. 건너뜁니다."
        else
            # Organization 생성
            local org_response=$(curl -s -b "$cookie_file" \
                -H "Content-Type: application/json" \
                -H "X-CSRFToken: $csrf_token" \
                -d "{\"slug\": \"$org_slug\", \"name\": \"$org_slug\"}" \
                "$CVAT_HOST/api/organizations")

            if echo "$org_response" | grep -q "\"slug\":\"$org_slug\""; then
                log_info "Organization '$org_slug' 생성 완료"
                CREATED_ORGS+=("$org_slug")
            elif echo "$org_response" | grep -q "already exists\|unique"; then
                log_warn "Organization '$org_slug'가 이미 존재합니다."
                CREATED_ORGS+=("$org_slug")
            else
                log_error "Organization 생성 실패: $org_response"
            fi
        fi

        echo ""
        read -p "Organization을 더 생성하시겠습니까? (y/N): " more_orgs
        if [[ "$more_orgs" != "y" && "$more_orgs" != "Y" ]]; then
            break
        fi
    done

    rm -f "$cookie_file"

    echo ""
    log_info "생성된 Organization 목록: ${CREATED_ORGS[*]:-없음}"
}

# Step 3: 일반 유저 생성 (여러 명)
create_users() {
    log_step "Step 3: 일반 유저 생성"

    echo ""
    read -p "일반 유저를 생성하시겠습니까? (y/N): " create_users_confirm
    if [[ "$create_users_confirm" != "y" && "$create_users_confirm" != "Y" ]]; then
        log_info "유저 생성을 건너뜁니다."
        return 0
    fi

    local cookie_file=$(mktemp)

    while true; do
        echo ""
        echo -e "${CYAN}--- 새 유저 정보 입력 ---${NC}"
        read -p "사용자명: " username

        if [[ -z "$username" ]]; then
            log_warn "사용자명이 비어있습니다. 건너뜁니다."
        else
            read -p "이메일: " email
            read -s -p "비밀번호 (대문자, 소문자, 숫자 포함 8자 이상): " password
            echo ""
            read -p "이름 (First name, 선택사항): " first_name
            read -p "성 (Last name, 선택사항): " last_name

            # 유저 등록 API 호출
            local register_data="{\"username\": \"$username\", \"email\": \"$email\", \"password1\": \"$password\", \"password2\": \"$password\""
            if [[ -n "$first_name" ]]; then
                register_data="${register_data}, \"first_name\": \"$first_name\""
            fi
            if [[ -n "$last_name" ]]; then
                register_data="${register_data}, \"last_name\": \"$last_name\""
            fi
            register_data="${register_data}}"

            local register_response=$(curl -s \
                -H "Content-Type: application/json" \
                -d "$register_data" \
                "$CVAT_HOST/api/auth/register")

            if echo "$register_response" | grep -q "key\|token"; then
                log_info "유저 '$username' 생성 완료"

                # Organization에 초대
                if [[ ${#CREATED_ORGS[@]} -gt 0 ]]; then
                    echo ""
                    echo "이 유저를 Organization에 초대하시겠습니까?"
                    echo "사용 가능한 Organization:"
                    for i in "${!CREATED_ORGS[@]}"; do
                        echo "  $((i+1)). ${CREATED_ORGS[$i]}"
                    done
                    echo "  0. 초대 안 함"
                    echo ""
                    read -p "선택 (번호, 여러 개는 쉼표로 구분, 예: 1,2): " org_choices

                    if [[ "$org_choices" != "0" && -n "$org_choices" ]]; then
                        # 역할 선택
                        echo ""
                        echo "멤버 역할을 선택하세요:"
                        echo "  1. worker     - 자신에게 할당된 task만 볼 수 있음"
                        echo "  2. supervisor - 자신에게 할당된 task만 볼 수 있음"
                        echo "  3. maintainer - Organization의 모든 task를 볼 수 있음 (권장)"
                        echo ""
                        read -p "역할 선택 (1-3, 기본값: 3): " role_choice
                        local selected_role="maintainer"
                        case "$role_choice" in
                            1) selected_role="worker" ;;
                            2) selected_role="supervisor" ;;
                            *) selected_role="maintainer" ;;
                        esac

                        IFS=',' read -ra CHOICES <<< "$org_choices"
                        for choice in "${CHOICES[@]}"; do
                            choice=$(echo "$choice" | tr -d ' ')
                            if [[ "$choice" =~ ^[0-9]+$ ]] && [[ $choice -ge 1 ]] && [[ $choice -le ${#CREATED_ORGS[@]} ]]; then
                                local org_slug="${CREATED_ORGS[$((choice-1))]}"

                                # Docker shell로 멤버십 직접 추가 (email backend 불필요)
                                log_info "유저 '$username'을 '$org_slug'에 '$selected_role' 역할로 추가 중..."
                                docker compose exec -T cvat_server python manage.py shell << PYEOF
from django.contrib.auth.models import User
from cvat.apps.organizations.models import Organization, Membership, Invitation

try:
    user = User.objects.get(username='$username')
    org = Organization.objects.get(slug='$org_slug')
    Invitation.objects.filter(membership__user=user, membership__organization=org).delete()
    membership, created = Membership.objects.get_or_create(
        user=user, organization=org,
        defaults={'role': '$selected_role', 'is_active': True}
    )
    if not created:
        membership.role = '$selected_role'
        membership.is_active = True
        membership.save()
    Invitation.objects.filter(membership=membership).delete()
    print('[OK] $username added to $org_slug as $selected_role')
except Exception as e:
    print(f'[ERROR] {e}')
PYEOF
                            fi
                        done
                    fi
                fi
            elif echo "$register_response" | grep -q "already exists\|username.*exists"; then
                log_warn "유저 '$username'이 이미 존재합니다."
            else
                log_error "유저 생성 실패: $register_response"
            fi
        fi

        echo ""
        read -p "유저를 더 생성하시겠습니까? (y/N): " more_users
        if [[ "$more_users" != "y" && "$more_users" != "Y" ]]; then
            break
        fi
    done

    rm -f "$cookie_file"
}

# 메인 실행
main() {
    echo -e "${CYAN}"
    echo "============================================================"
    echo "  CVAT Multiview 초기 설정"
    echo "============================================================"
    echo -e "${NC}"
    echo ""
    echo "이 스크립트는 다음을 수행합니다:"
    echo "  1. Superuser 계정 생성"
    echo "  2. Organization 생성 (여러 개 가능)"
    echo "  3. 일반 유저 생성 (여러 명 가능)"
    echo "  4. 유저를 Organization에 초대"
    echo ""

    # 시스템 의존성 확인
    check_system_dependencies

    # Docker 확인
    check_docker

    # CVAT 서버 확인
    check_cvat_server

    # 확인
    read -p "진행하시겠습니까? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "취소되었습니다."
        exit 0
    fi

    # Step 1: Superuser 생성
    create_superuser

    # Step 2: Organization 생성
    create_organizations

    # Step 3: 일반 유저 생성
    create_users

    echo ""
    log_step "설정 완료"
    echo ""
    log_info "CVAT 접속 URL: $CVAT_HOST"
    log_info "  (다른 서버인 경우: http://<IP or Domain>:8080)"
    echo ""

    if [[ ${#CREATED_ORGS[@]} -gt 0 ]]; then
        log_info "생성된 Organization: ${CREATED_ORGS[*]}"
        echo ""
        log_info "Task 생성 예시:"
        for org in "${CREATED_ORGS[@]}"; do
            echo "  ./create_all_tasks.sh --user $SUPERUSER_NAME --password <PASSWORD> --org $org --host <CVAT_HOST>"
        done
    fi
}

# 실행
main
