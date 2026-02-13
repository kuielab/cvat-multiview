#!/bin/bash
# 단순 재시작 (빌드 없음). 코드 변경 없이 컨테이너만 재시작할 때.
set -e
cd "$(dirname "$0")/../.."
HOST="${CVAT_HOST:-${1:-localhost}}"
echo "[restart] CVAT_HOST=$HOST"
CVAT_HOST="$HOST" docker compose up -d --force-recreate
echo "[restart] done"
