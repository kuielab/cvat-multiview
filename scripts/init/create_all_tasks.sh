#!/bin/bash
#
# Create All Multiview Tasks
#
# Multisensor Home과 MMOffice 데이터셋의 모든 multiview task를 생성하는 스크립트입니다.
#
# 사용법:
#   ./create_all_tasks.sh --user admin --password admin123
#   ./create_all_tasks.sh --user admin --password admin123 --dry-run
#   ./create_all_tasks.sh --user admin --password admin123 --data-dir /mnt/data
#

set -e

# 기본값 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="/mnt/data"
HOST="http://localhost:8080"
DRY_RUN=""
USER=""
PASSWORD=""
LIMIT=""

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# 사용법 출력
usage() {
    cat << EOF
Usage: $0 --user USERNAME --password PASSWORD [OPTIONS]

필수 옵션:
  --user, -u        CVAT 사용자명
  --password, -p    CVAT 비밀번호

선택 옵션:
  --data-dir, -d    데이터셋 루트 경로 (기본값: /mnt/data)
  --host            CVAT 서버 URL (기본값: http://localhost:8080)
  --limit           생성할 최대 task 수
  --dry-run         실제 생성 없이 미리보기
  --help, -h        도움말 출력

예시:
  $0 --user admin --password admin123
  $0 --user admin --password admin123 --dry-run
  $0 --user admin --password admin123 --data-dir /mnt/data --limit 10
EOF
    exit 1
}

# 인자 파싱
while [[ $# -gt 0 ]]; do
    case $1 in
        --user|-u)
            USER="$2"
            shift 2
            ;;
        --password|-p)
            PASSWORD="$2"
            shift 2
            ;;
        --data-dir|-d)
            DATA_DIR="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --limit)
            LIMIT="--limit $2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
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

# 필수 인자 확인
if [[ -z "$USER" || -z "$PASSWORD" ]]; then
    log_error "사용자명과 비밀번호는 필수입니다."
    usage
fi

# Python 찾기
find_python() {
    # 가능한 Python 경로들 (Windows와 Linux 모두 지원)
    local python_paths=(
        "python3"
        "python"
        "/usr/bin/python3"
        "/usr/bin/python"
        "/usr/local/bin/python3"
        "/usr/local/bin/python"
        "/c/Python/Python311/python.exe"
        "/c/Python/Python310/python.exe"
        "/c/Python/Python312/python.exe"
        "/c/Python/Python39/python.exe"
        "/c/Python311/python.exe"
        "/c/Python310/python.exe"
    )

    for py in "${python_paths[@]}"; do
        if [[ -x "$py" ]] || command -v "$py" &> /dev/null; then
            # Python 버전 확인 (3.8 이상)
            if "$py" -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done

    return 1
}

# 의존성 설치
install_dependencies() {
    local python="$1"

    log_info "의존성 패키지 확인 중..."

    # requests 모듈 확인
    if ! $python -c "import requests" 2>/dev/null; then
        log_warn "requests 모듈이 없습니다. 설치를 시도합니다..."
        if $python -m pip install requests --quiet; then
            log_info "requests 설치 완료"
        else
            log_error "requests 설치 실패. 수동으로 설치해주세요: pip install requests"
            exit 1
        fi
    else
        log_info "requests 모듈 확인 완료"
    fi
}

# CVAT 서버 연결 확인
check_cvat_server() {
    log_info "CVAT 서버 연결 확인 중... ($HOST)"

    if command -v curl &> /dev/null; then
        if curl -s -o /dev/null -w "%{http_code}" "$HOST/api/server/about" | grep -q "200\|401\|403"; then
            log_info "CVAT 서버 연결 성공"
            return 0
        fi
    elif command -v wget &> /dev/null; then
        if wget -q --spider "$HOST/api/server/about" 2>/dev/null; then
            log_info "CVAT 서버 연결 성공"
            return 0
        fi
    fi

    log_error "CVAT 서버에 연결할 수 없습니다: $HOST"
    log_error "서버가 실행 중인지 확인해주세요."
    exit 1
}

# 데이터 디렉토리 확인
check_data_dir() {
    log_info "데이터 디렉토리 확인 중... ($DATA_DIR)"

    if [[ ! -d "$DATA_DIR" ]]; then
        log_error "데이터 디렉토리가 존재하지 않습니다: $DATA_DIR"
        exit 1
    fi

    # multisensor_home 확인
    local has_multisensor=false
    if [[ -d "$DATA_DIR/multisensor_home1" ]] || [[ -d "$DATA_DIR/multisensor_home2" ]]; then
        has_multisensor=true
        log_info "Multisensor Home 데이터셋 발견"
    fi

    # mmoffice 확인
    local has_mmoffice=false
    if [[ -d "$DATA_DIR/mmoffice/video" ]]; then
        has_mmoffice=true
        log_info "MMOffice 데이터셋 발견"
    fi

    if [[ "$has_multisensor" == false && "$has_mmoffice" == false ]]; then
        log_error "데이터셋을 찾을 수 없습니다."
        log_error "다음 경로 중 하나 이상이 존재해야 합니다:"
        log_error "  - $DATA_DIR/multisensor_home1"
        log_error "  - $DATA_DIR/multisensor_home2"
        log_error "  - $DATA_DIR/mmoffice/video"
        exit 1
    fi
}

# 메인 실행
main() {
    echo "============================================================"
    echo "  Create All Multiview Tasks"
    echo "============================================================"
    echo ""

    # Python 찾기
    log_info "Python 확인 중..."
    PYTHON=$(find_python)
    if [[ -z "$PYTHON" ]]; then
        log_error "Python 3.8 이상이 필요합니다."
        log_error "Python을 설치해주세요: https://www.python.org/downloads/"
        exit 1
    fi
    log_info "Python 발견: $PYTHON ($($PYTHON --version))"

    # 의존성 설치
    install_dependencies "$PYTHON"

    # CVAT 서버 확인
    check_cvat_server

    # 데이터 디렉토리 확인
    check_data_dir

    echo ""
    echo "============================================================"
    echo "  Task 생성 시작"
    echo "============================================================"
    echo ""

    # 공통 옵션
    COMMON_OPTS="--user $USER --password $PASSWORD --host $HOST --data-dir $DATA_DIR $LIMIT $DRY_RUN"

    # Multisensor Home Tasks 생성
    if [[ -d "$DATA_DIR/multisensor_home1" ]] || [[ -d "$DATA_DIR/multisensor_home2" ]]; then
        echo ""
        log_info "========== Multisensor Home Tasks 생성 =========="
        if $PYTHON "$SCRIPT_DIR/create_multisensor_home_tasks.py" $COMMON_OPTS; then
            log_info "Multisensor Home Tasks 완료"
        else
            log_error "Multisensor Home Tasks 생성 실패"
        fi
    fi

    # MMOffice Tasks 생성
    if [[ -d "$DATA_DIR/mmoffice/video" ]]; then
        echo ""
        log_info "========== MMOffice Tasks 생성 =========="
        if $PYTHON "$SCRIPT_DIR/create_mmoffice_tasks.py" $COMMON_OPTS; then
            log_info "MMOffice Tasks 완료"
        else
            log_error "MMOffice Tasks 생성 실패"
        fi
    fi

    echo ""
    echo "============================================================"
    echo "  완료"
    echo "============================================================"
}

# 실행
main
