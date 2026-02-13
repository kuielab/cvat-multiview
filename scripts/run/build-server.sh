#!/bin/bash
# 서버만 빌드 후 재시작. cvat/apps/ Python 변경 시.
set -e
cd "$(dirname "$0")/../.."
HOST="${CVAT_HOST:-${1:-localhost}}"
echo "[build-server] building cvat_server..."
docker compose build cvat_server
echo "[build-server] restarting with CVAT_HOST=$HOST"
CVAT_HOST="$HOST" docker compose up -d
echo "[build-server] done"
