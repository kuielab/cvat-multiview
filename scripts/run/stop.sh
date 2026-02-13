#!/bin/bash
# 전체 중지 및 컨테이너 제거. DB 볼륨은 유지됨.
set -e
cd "$(dirname "$0")/../.."
echo "[stop] stopping all containers..."
docker compose down
echo "[stop] done"
