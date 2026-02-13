#!/bin/bash
# UI만 빌드 후 재시작. cvat-ui/, cvat-core/ TS 변경 시.
set -e
cd "$(dirname "$0")/../.."
HOST="${CVAT_HOST:-${1:-localhost}}"
echo "[build-ui] building cvat_ui..."
docker compose build cvat_ui
echo "[build-ui] restarting with CVAT_HOST=$HOST"
CVAT_HOST="$HOST" docker compose up -d
echo "[build-ui] done"
