#!/bin/bash
# UI + 서버 모두 빌드 후 재시작. 양쪽 코드 변경 시.
set -e
cd "$(dirname "$0")/../.."
HOST="${CVAT_HOST:-${1:-localhost}}"
echo "[build-all] building cvat_ui + cvat_server..."
docker compose build cvat_ui cvat_server
echo "[build-all] restarting with CVAT_HOST=$HOST"
CVAT_HOST="$HOST" docker compose up -d
echo "[build-all] done"
