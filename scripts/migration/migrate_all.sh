#!/bin/bash
#
# EC2에서 모든 job의 annotation 좌표를 일괄 마이그레이션
#
# 사용법:
#   # Dry-run (확인만)
#   bash scripts/migration/migrate_all.sh --user admin --password admin123 --dry-run
#
#   # 실제 마이그레이션
#   bash scripts/migration/migrate_all.sh --user admin --password admin123
#
#   # 특정 job만
#   bash scripts/migration/migrate_all.sh --user admin --password admin123 --job-ids 7,8,9
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="cvat_server"
REMOTE_DIR="/home/django/migration_tmp"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: docker not found${NC}" >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo -e "${RED}ERROR: ${CONTAINER} container is not running${NC}" >&2
    echo "Run 'docker compose up -d' first." >&2
    exit 1
fi

echo -e "${GREEN}Copying migration scripts to ${CONTAINER}...${NC}"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" rm -rf "$REMOTE_DIR" 2>/dev/null || true
docker cp "$SCRIPT_DIR" "${CONTAINER}:${REMOTE_DIR}"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" chmod -R 777 "$REMOTE_DIR"

echo -e "${GREEN}Running migration...${NC}"
echo ""
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" python \
    "$REMOTE_DIR/migrate_all.py" \
    --server http://localhost:8080 \
    "$@"

echo ""
echo -e "${GREEN}Cleaning up...${NC}"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" rm -rf "$REMOTE_DIR"
echo -e "${GREEN}Done!${NC}"
