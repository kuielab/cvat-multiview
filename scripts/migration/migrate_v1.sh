#!/bin/bash
#
# migrate_v1: Master -> Refactor annotation coordinate batch migration
#
# Copies migrate_v1.py into cvat_server container and runs batch conversion
# on ALL jobs. Exports each job's annotations, converts coordinates from
# master's 1920x1080 to actual video dimensions, and uploads back.
#
# Usage:
#   # Dry-run (check what would be converted):
#   bash scripts/migration/migrate_v1.sh --user admin --password admin123 --dry-run
#
#   # Actual migration (all jobs):
#   bash scripts/migration/migrate_v1.sh --user admin --password admin123
#
#   # Specific jobs only:
#   bash scripts/migration/migrate_v1.sh --user admin --password admin123 --job-ids 7,8,9
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

echo -e "${GREEN}Copying migration script to ${CONTAINER}...${NC}"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" rm -rf "$REMOTE_DIR" 2>/dev/null || true
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" mkdir -p "$REMOTE_DIR"
docker cp "$SCRIPT_DIR/migrate_v1.py" "${CONTAINER}:${REMOTE_DIR}/migrate_v1.py"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" chmod 755 "$REMOTE_DIR/migrate_v1.py"

echo -e "${GREEN}Running migrate_v1.py --all-jobs ...${NC}"
echo ""
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" python \
    "$REMOTE_DIR/migrate_v1.py" \
    --all-jobs \
    --server http://localhost:8080 \
    "$@"

STATUS=$?

echo ""
echo -e "${GREEN}Cleaning up...${NC}"
MSYS_NO_PATHCONV=1 docker exec -u root "$CONTAINER" rm -rf "$REMOTE_DIR"

if [ $STATUS -eq 0 ]; then
    echo -e "${GREEN}Done!${NC}"
else
    echo -e "${RED}Migration finished with errors (exit code $STATUS)${NC}" >&2
fi

exit $STATUS
