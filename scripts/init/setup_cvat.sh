#!/bin/bash
#
# CVAT Multiview 초기 설정 스크립트
#
# 이 스크립트는 다음을 순서대로 수행합니다:
#   1. Superuser 계정 생성
#   2. Organization 생성
#
# Task 생성은 별도로 create_all_tasks.sh를 사용하세요.
#
# 사용법:
#   ./setup_cvat.sh
#   ./setup_cvat.sh --skip-superuser  # superuser 이미 있는 경우
#
# 환경변수로 설정 가능:
#   CVAT_USER, CVAT_PASSWORD, CVAT_ORG, CVAT_HOST
#

set -e

# 기본값 설정
CVAT_HOST="${CVAT_HOST:-http://localhost:8080}"
CVAT_USER="${CVAT_USER:-}"
CVAT_PASSWORD="${CVAT_PASSWORD:-}"
CVAT_ORG="${CVAT_ORG:-}"
SKIP_SUPERUSER=false

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
  2. Organization 생성 (CVAT API 사용)

Task 생성은 별도로 create_all_tasks.sh를 사용하세요.

옵션:
  --skip-superuser    Superuser 생성 단계 건너뛰기 (이미 있는 경우)
  --help, -h          도움말 출력

환경변수:
  CVAT_HOST           CVAT 서버 URL (기본값: http://localhost:8080)
  CVAT_USER           CVAT 사용자명
  CVAT_PASSWORD       CVAT 비밀번호
  CVAT_ORG            Organization slug

예시:
  # 대화형으로 모든 정보 입력
  $0

  # 환경변수 사용
  CVAT_USER=admin CVAT_PASSWORD=admin123 CVAT_ORG=ielab $0

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

# Docker 확인
check_docker() {
    log_info "Docker 확인 중..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker가 설치되지 않았습니다."
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

# 사용자 입력 받기
prompt_user_input() {
    log_step "사용자 정보 입력"

    # 사용자명
    if [[ -z "$CVAT_USER" ]]; then
        read -p "CVAT 사용자명 (예: admin): " CVAT_USER
        if [[ -z "$CVAT_USER" ]]; then
            log_error "사용자명은 필수입니다."
            exit 1
        fi
    else
        log_info "사용자명: $CVAT_USER (환경변수에서 로드)"
    fi

    # 비밀번호
    if [[ -z "$CVAT_PASSWORD" ]]; then
        read -s -p "CVAT 비밀번호: " CVAT_PASSWORD
        echo ""
        if [[ -z "$CVAT_PASSWORD" ]]; then
            log_error "비밀번호는 필수입니다."
            exit 1
        fi
    else
        log_info "비밀번호: ******** (환경변수에서 로드)"
    fi

    # Organization slug
    if [[ -z "$CVAT_ORG" ]]; then
        read -p "Organization slug (예: ielab): " CVAT_ORG
        if [[ -z "$CVAT_ORG" ]]; then
            log_error "Organization slug는 필수입니다."
            exit 1
        fi
    else
        log_info "Organization: $CVAT_ORG (환경변수에서 로드)"
    fi

    echo ""
    log_info "설정 확인:"
    log_info "  - Host: $CVAT_HOST"
    log_info "  - User: $CVAT_USER"
    log_info "  - Organization: $CVAT_ORG"
    echo ""
}

# Step 1: Superuser 생성
create_superuser() {
    log_step "Step 1: Superuser 계정 생성"

    if [[ "$SKIP_SUPERUSER" == true ]]; then
        log_info "Superuser 생성 건너뛰기 (--skip-superuser)"
        return 0
    fi

    log_info "Superuser 계정을 생성합니다."
    log_info "아래 프롬프트에서 사용자명, 이메일, 비밀번호를 입력하세요."
    log_warn "위에서 입력한 CVAT_USER/CVAT_PASSWORD와 동일하게 설정하세요!"
    echo ""

    # Interactive하게 createsuperuser 실행
    docker compose exec cvat_server python manage.py createsuperuser

    if [[ $? -eq 0 ]]; then
        log_info "Superuser 생성 완료"
    else
        log_warn "Superuser 생성 실패 또는 이미 존재합니다."
        log_info "이미 계정이 있다면 --skip-superuser 옵션을 사용하세요."
    fi
}

# Step 2: Organization 생성
create_organization() {
    log_step "Step 2: Organization 생성"

    log_info "Organization '$CVAT_ORG' 생성 중..."

    # 로그인하여 세션 쿠키 획득
    local cookie_file=$(mktemp)

    # CSRF 토큰 획득
    curl -s -c "$cookie_file" "$CVAT_HOST/api/auth/login" > /dev/null
    local csrf_token=$(grep csrftoken "$cookie_file" | awk '{print $NF}')

    # 로그인
    local login_response=$(curl -s -b "$cookie_file" -c "$cookie_file" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $csrf_token" \
        -d "{\"username\": \"$CVAT_USER\", \"password\": \"$CVAT_PASSWORD\"}" \
        "$CVAT_HOST/api/auth/login")

    if echo "$login_response" | grep -q "key\|token"; then
        log_info "로그인 성공"
    else
        log_error "로그인 실패: $login_response"
        rm -f "$cookie_file"
        exit 1
    fi

    # CSRF 토큰 다시 획득
    csrf_token=$(grep csrftoken "$cookie_file" | awk '{print $NF}')

    # Organization 생성
    local org_response=$(curl -s -b "$cookie_file" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $csrf_token" \
        -d "{\"slug\": \"$CVAT_ORG\", \"name\": \"$CVAT_ORG\"}" \
        "$CVAT_HOST/api/organizations")

    rm -f "$cookie_file"

    if echo "$org_response" | grep -q "\"slug\":\"$CVAT_ORG\""; then
        log_info "Organization '$CVAT_ORG' 생성 완료"
    elif echo "$org_response" | grep -q "already exists\|unique"; then
        log_warn "Organization '$CVAT_ORG'가 이미 존재합니다."
    else
        log_error "Organization 생성 실패: $org_response"
        exit 1
    fi
}

# 메인 실행
main() {
    echo -e "${CYAN}"
    echo "============================================================"
    echo "  CVAT Multiview 초기 설정"
    echo "============================================================"
    echo -e "${NC}"

    # Docker 확인
    check_docker

    # CVAT 서버 확인
    check_cvat_server

    # 사용자 입력
    prompt_user_input

    # 확인
    read -p "위 설정으로 진행하시겠습니까? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "취소되었습니다."
        exit 0
    fi

    # Step 1: Superuser 생성
    create_superuser

    # Step 2: Organization 생성
    create_organization

    echo ""
    log_step "설정 완료"
    log_info "CVAT에 접속하여 확인하세요: $CVAT_HOST"
    log_info ""
    log_info "다음 단계:"
    log_info "  1. Organization '$CVAT_ORG'에 멤버 초대:"
    log_info "     $CVAT_HOST → Organizations → $CVAT_ORG → Members → Invite"
    log_info ""
    log_info "  2. Task 생성 (선택사항):"
    log_info "     ./create_all_tasks.sh --user $CVAT_USER --password <PASSWORD> --org $CVAT_ORG"
}

# 실행
main
