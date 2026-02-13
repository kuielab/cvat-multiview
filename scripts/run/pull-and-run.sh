#!/bin/bash
# ghcr.io 이미지 pull 후 실행. EC2에서 직접 빌드 없이 배포할 때.
set -e
cd "$(dirname "$0")/../.."
HOST="${CVAT_HOST:-${1:-localhost}}"
echo "[pull] pulling images from ghcr.io..."
docker compose -f docker-compose.yml pull
echo "[pull] starting with CVAT_HOST=$HOST"
CVAT_HOST="$HOST" docker compose -f docker-compose.yml up -d
echo "[pull] done"
