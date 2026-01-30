#!/bin/bash
#
# Assign Multiview Tasks to Organizations
#
# 특정 범위의 Task를 특정 Organization에 할당하여 생성하는 스크립트입니다.
# Multisensor Home과 MMOffice 데이터셋 모두 지원합니다.
#
# 사용법:
#   # 단일 할당 (Home)
#   ./assign_tasks_to_orgs.sh --user admin --password admin123 \
#       --dataset home --sessions 00-10 --org team1
#
#   # 단일 할당 (MMOffice with split-ids)
#   ./assign_tasks_to_orgs.sh --user admin --password admin123 \
#       --dataset mmoffice --sessions 01-04 --split-ids 5-6 --org team1
#
#   # 설정 파일로 일괄 할당
#   ./assign_tasks_to_orgs.sh --user admin --password admin123 --config assignments.txt
#
# 설정 파일 형식 (assignments.txt):
#   # 주석 (# 또는 빈 줄은 무시)
#   # 형식: dataset:sessions:org[:옵션]
#   # 옵션: subdirs=01,02 또는 split-ids=5,6,7 또는 datasets=home1,home2
#
#   # Home 예시
#   home:00-10:team1
#   home:11-20:team2:subdirs=01
#   home:21-30:team3:datasets=multisensor_home1
#
#   # MMOffice 예시
#   mmoffice:01-04:team1:split-ids=5,6
#   mmoffice:05-08:team2:split-ids=7
#   mmoffice:09-12:team3
#

set -e

# 기본값 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="/mnt/data"
HOST="http://localhost:8080"
DRY_RUN=""
USER=""
PASSWORD=""
DATASET=""
SESSIONS=""
ORG=""
CONFIG_FILE=""
SUBDIRS=""
SPLIT_IDS=""
DATASETS_FILTER=""

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
Usage: $0 --user USERNAME --password PASSWORD [OPTIONS]

특정 범위의 Multiview Task를 특정 Organization에 할당하여 생성합니다.

필수 옵션:
  --user, -u        CVAT 사용자명
  --password, -p    CVAT 비밀번호

할당 방법 1: 단일 할당
  --dataset         데이터셋 타입 (home 또는 mmoffice)
  --sessions        세션 범위 (예: 00-10, 또는 "00 01 02")
  --org             Organization slug

  Home 전용:
    --subdirs       서브디렉토리 필터 (예: "01 02")
    --datasets      데이터셋 필터 (예: "multisensor_home1")

  MMOffice 전용:
    --split-ids     Split ID 필터 (예: 5-7, 또는 "5 6 7")

할당 방법 2: 설정 파일
  --config          설정 파일 경로

공통 옵션:
  --data-dir, -d    데이터셋 루트 경로 (기본값: /mnt/data)
  --host            CVAT 서버 URL (기본값: http://localhost:8080)
  --dry-run         실제 생성 없이 미리보기
  --help, -h        도움말 출력

예시:
  # Home 데이터셋의 세션 00-10을 team1에 할당
  $0 --user admin --password admin123 \\
      --dataset home --sessions 00-10 --org team1

  # Home의 특정 subdir만
  $0 --user admin --password admin123 \\
      --dataset home --sessions 00-10 --subdirs "01" --org team1

  # MMOffice의 특정 split-ids만
  $0 --user admin --password admin123 \\
      --dataset mmoffice --sessions 01-04 --split-ids 5-6 --org team1

  # 설정 파일로 일괄 할당
  $0 --user admin --password admin123 --config assignments.txt

설정 파일 형식 (assignments.txt):
  # 주석 (# 또는 빈 줄은 무시)
  # 형식: dataset:sessions:org[:옵션]
  #
  # 옵션 형식 (쉼표로 여러 개 지정):
  #   subdirs=01,02
  #   datasets=multisensor_home1
  #   split-ids=5,6,7
  #
  # Home 예시
  home:00-10:team1
  home:11-20:team2:subdirs=01
  home:21-30:team3:datasets=multisensor_home1
  #
  # MMOffice 예시
  mmoffice:01-04:team1:split-ids=5,6
  mmoffice:05-08:team2:split-ids=7
  mmoffice:09-12:team3

필터링 기준 요약:
  Home:     datasets (home1/home2), subdirs (01/02), sessions (00-58)
  MMOffice: splits (test/train), split-ids (2-7), sessions (01-12)
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
        --dataset)
            DATASET="$2"
            shift 2
            ;;
        --sessions)
            SESSIONS="$2"
            shift 2
            ;;
        --org)
            ORG="$2"
            shift 2
            ;;
        --subdirs)
            SUBDIRS="$2"
            shift 2
            ;;
        --split-ids)
            SPLIT_IDS="$2"
            shift 2
            ;;
        --datasets)
            DATASETS_FILTER="$2"
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
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

# 할당 방법 확인
if [[ -z "$CONFIG_FILE" && (-z "$DATASET" || -z "$SESSIONS" || -z "$ORG") ]]; then
    log_error "할당 정보가 필요합니다."
    log_error "  방법 1: --dataset, --sessions, --org 모두 지정"
    log_error "  방법 2: --config 파일 지정"
    usage
fi

# Python 찾기
find_python() {
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
    )

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

# pip 찾기
find_pip() {
    local python="$1"

    # pip 모듈로 실행 시도
    if $python -m pip --version &> /dev/null; then
        echo "$python -m pip"
        return 0
    fi

    # pip3, pip 명령어 시도
    local pip_paths=("pip3" "pip")
    for pip in "${pip_paths[@]}"; do
        if command -v "$pip" &> /dev/null; then
            echo "$pip"
            return 0
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

        local pip_cmd
        pip_cmd=$(find_pip "$python")
        if [[ -z "$pip_cmd" ]]; then
            log_error "pip를 찾을 수 없습니다."
            log_error "수동으로 설치해주세요: pip install requests"
            exit 1
        fi

        if $pip_cmd install requests --quiet 2>/dev/null || $pip_cmd install requests 2>/dev/null; then
            log_info "requests 설치 완료"
        else
            log_error "requests 설치 실패. 수동으로 설치해주세요: pip install requests"
            exit 1
        fi
    fi
}

# CVAT 서버 연결 확인
check_cvat_server() {
    log_info "CVAT 서버 연결 확인 중... ($HOST)"

    # curl 확인 및 설치 안내
    if ! command -v curl &> /dev/null; then
        log_warn "curl이 설치되어 있지 않습니다. 서버 연결 확인을 건너뜁니다."
        return 0
    fi

    local max_retries=3
    local retry=0

    while [[ $retry -lt $max_retries ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "$HOST/api/server/about" 2>/dev/null | grep -qE "200|401|403"; then
            log_info "CVAT 서버 연결 성공"
            return 0
        fi

        retry=$((retry + 1))
        if [[ $retry -lt $max_retries ]]; then
            log_warn "연결 재시도 중... ($retry/$max_retries)"
            sleep 2
        fi
    done

    log_error "CVAT 서버에 연결할 수 없습니다: $HOST"
    log_error "서버가 실행 중인지 확인해주세요."
    exit 1
}

# 단일 할당 실행
run_assignment() {
    local dataset="$1"
    local sessions="$2"
    local org="$3"
    local extra_opts="$4"

    log_step "할당: $dataset / sessions=$sessions / org=$org${extra_opts:+ / $extra_opts}"

    # 세션 인자 변환 (공백 구분 → 여러 인자)
    local session_args=""
    for s in $sessions; do
        session_args="$session_args $s"
    done

    # 추가 옵션 파싱
    local subdirs_arg=""
    local split_ids_arg=""
    local datasets_arg=""

    if [[ -n "$extra_opts" ]]; then
        # subdirs 파싱
        if [[ "$extra_opts" =~ subdirs=([^:]+) ]]; then
            local subdirs_val="${BASH_REMATCH[1]}"
            subdirs_arg="--subdirs ${subdirs_val//,/ }"
        fi
        # split-ids 파싱
        if [[ "$extra_opts" =~ split-ids=([^:]+) ]]; then
            local split_ids_val="${BASH_REMATCH[1]}"
            split_ids_arg="--split-ids ${split_ids_val//,/ }"
        fi
        # datasets 파싱
        if [[ "$extra_opts" =~ datasets=([^:]+) ]]; then
            local datasets_val="${BASH_REMATCH[1]}"
            datasets_arg="--datasets ${datasets_val//,/ }"
        fi
    fi

    case "$dataset" in
        home|multisensor_home|multisensor)
            log_info "Multisensor Home 데이터셋 처리 중..."
            $PYTHON "$SCRIPT_DIR/create_multisensor_home_tasks.py" \
                --user "$USER" --password "$PASSWORD" \
                --host "$HOST" --data-dir "$DATA_DIR" \
                --org "$org" --sessions $session_args \
                $subdirs_arg $datasets_arg $DRY_RUN
            ;;
        mmoffice|office)
            log_info "MMOffice 데이터셋 처리 중..."
            $PYTHON "$SCRIPT_DIR/create_mmoffice_tasks.py" \
                --user "$USER" --password "$PASSWORD" \
                --host "$HOST" --data-dir "$DATA_DIR" \
                --org "$org" --sessions $session_args \
                $split_ids_arg $DRY_RUN
            ;;
        *)
            log_error "Unknown dataset: $dataset"
            log_error "지원되는 데이터셋: home, mmoffice"
            return 1
            ;;
    esac
}

# 설정 파일에서 할당 실행
run_assignments_from_config() {
    local config_file="$1"

    if [[ ! -f "$config_file" ]]; then
        log_error "설정 파일을 찾을 수 없습니다: $config_file"
        exit 1
    fi

    log_info "설정 파일에서 할당 정보 읽는 중: $config_file"
    echo ""

    local line_num=0
    local assignment_count=0

    # 먼저 미리보기
    while IFS= read -r line || [[ -n "$line" ]]; do
        line_num=$((line_num + 1))

        # 주석 및 빈 줄 스킵
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # 형식: dataset:sessions:org[:options]
        IFS=':' read -r dataset sessions org options <<< "$line"

        if [[ -z "$dataset" || -z "$sessions" || -z "$org" ]]; then
            log_warn "Line $line_num: 잘못된 형식 (dataset:sessions:org 형식 필요): $line"
            continue
        fi

        assignment_count=$((assignment_count + 1))
        echo -e "${CYAN}[$assignment_count] $dataset / sessions=$sessions → $org${options:+ ($options)}${NC}"
    done < "$config_file"

    echo ""
    log_info "총 $assignment_count 개의 할당이 실행됩니다."
    echo ""

    # 확인
    if [[ -z "$DRY_RUN" ]]; then
        read -p "진행하시겠습니까? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log_info "취소되었습니다."
            exit 0
        fi
    fi

    # 실제 실행
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        IFS=':' read -r dataset sessions org options <<< "$line"
        [[ -z "$dataset" || -z "$sessions" || -z "$org" ]] && continue

        run_assignment "$dataset" "$sessions" "$org" "$options"
    done < "$config_file"
}

# 메인 실행
main() {
    echo -e "${CYAN}"
    echo "============================================================"
    echo "  Assign Multiview Tasks to Organizations"
    echo "============================================================"
    echo -e "${NC}"

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

    echo ""

    if [[ -n "$CONFIG_FILE" ]]; then
        # 설정 파일 모드
        run_assignments_from_config "$CONFIG_FILE"
    else
        # 단일 할당 모드
        # 추가 옵션 조합
        local extra_opts=""
        [[ -n "$SUBDIRS" ]] && extra_opts="${extra_opts}subdirs=${SUBDIRS// /,}:"
        [[ -n "$SPLIT_IDS" ]] && extra_opts="${extra_opts}split-ids=${SPLIT_IDS// /,}:"
        [[ -n "$DATASETS_FILTER" ]] && extra_opts="${extra_opts}datasets=${DATASETS_FILTER// /,}:"
        extra_opts="${extra_opts%:}"  # 마지막 : 제거

        run_assignment "$DATASET" "$SESSIONS" "$ORG" "$extra_opts"
    fi

    echo ""
    log_step "완료"
}

# 실행
main
