# Run Scripts

Docker 실행/재시작 스크립트. 모든 스크립트는 프로젝트 루트 기준으로 동작합니다.

## CVAT_HOST 설정

환경변수 또는 첫 번째 인자로 지정. 미지정 시 `localhost`.

```bash
# 환경변수
export CVAT_HOST=3.36.160.76
bash scripts/run/build-ui.sh

# 또는 인자
bash scripts/run/build-ui.sh 3.36.160.76
```

## 스크립트 목록

| 스크립트 | 용도 | 소요 시간 |
|---------|------|-----------|
| `restart.sh` | 코드 변경 없이 재시작 | ~15초 |
| `build-ui.sh` | UI/cvat-core TS 변경 후 재시작 | ~3분 |
| `build-server.sh` | 서버 Python 변경 후 재시작 | ~2분 |
| `build-all.sh` | UI + 서버 모두 변경 후 재시작 | ~5분 |
| `pull-and-run.sh` | ghcr.io 이미지 pull 후 실행 (빌드 없음) | ~1분 |
| `stop.sh` | 전체 중지 (DB 볼륨 유지) | ~10초 |

## 언제 어떤 스크립트를 쓰나

| 변경 내용 | 스크립트 |
|-----------|---------|
| `cvat-ui/`, `cvat-core/`, `cvat-canvas/` (TS/TSX) | `build-ui.sh` |
| `cvat/apps/` (Python) | `build-server.sh` |
| `docker-compose.yml`, `Dockerfile` | `build-all.sh` |
| 환경변수, 설정만 변경 | `restart.sh` |
| EC2에서 CI 빌드 이미지 사용 | `pull-and-run.sh` |
