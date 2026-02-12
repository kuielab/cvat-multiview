# Migration: Master → Refactor Annotation Coordinate Converter

## 왜 필요한가

Master 브랜치의 Docker 이미지에 `ffprobe`가 설치되어 있지 않았습니다.
비디오 업로드 시 `_extract_video_metadata()` 함수가 ffprobe를 호출하지만 실패하여,
**실제 해상도와 무관하게 1920x1080으로 fallback** 저장되었습니다.

```python
# cvat/apps/engine/views.py (Master)
def _extract_video_metadata(video_path):
    try:
        result = subprocess.run(['ffprobe', ...])  # ffprobe NOT installed
        ...
    except Exception:
        return {
            'width': 1920, 'height': 1080,    # <-- 항상 여기로 빠짐
            'fps': 30.0, 'frame_count': 3000, 'duration': 100.0
        }
```

그 결과:

| 항목 | Master (실제) | Master (DB 저장) | Refactor (DB 저장) |
|------|--------------|------------------|-------------------|
| 비디오 해상도 | 320x240 (4:3) | **1920x1080 (16:9)** | 320x240 (4:3) |
| Canvas 표시 | 16:9 왜곡 | - | 4:3 정상 |
| Annotation 좌표 | 1920x1080 공간 | - | 320x240 공간 |

Master에서 생성한 annotation은 **가짜 1920x1080 좌표 공간**에 저장되어 있어서,
Refactor 환경(실제 320x240)에서 그대로 사용하면 bbox가 캔버스 밖에 위치하게 됩니다.

## 변환 알고리즘 (Hybrid Scaling)

Master(16:9)와 Refactor(4:3)의 종횡비가 다르기 때문에, X/Y 스케일이 다릅니다:

- X 스케일: 320 / 1920 = **0.1667** (÷6)
- Y 스케일: 240 / 1080 = **0.2222** (÷4.5)

단순 비균등 스케일링을 적용하면 bbox의 위치는 정확하지만 **형태가 변합니다.**
어노테이터가 stretched된 화면에서 의도한 bbox 비율이 깨지게 됩니다.

이 스크립트는 **Hybrid Scaling** 방식을 사용합니다:

| 요소 | 스케일링 방식 | 이유 |
|------|-------------|------|
| **중심점 위치** | 비균등 (X, Y 독립) | 실제 비디오 좌표에 정확히 매핑 |
| **Bbox 크기** | 균등 (기하평균 sqrt(sx*sy)) | 어노테이터의 의도한 bbox 비율 보존 |

```
uniform_scale = sqrt(scale_x * scale_y) = sqrt(0.1667 * 0.2222) = 0.1925

변환 과정 (각 bbox):
  1. center = ((xtl+xbr)/2, (ytl+ybr)/2)
  2. center_new = (center_x * scale_x, center_y * scale_y)   <- 위치: 비균등
  3. width_new  = width * uniform_scale                       <- 크기: 균등
  4. height_new = height * uniform_scale                      <- 크기: 균등
  5. corners = center_new +/- size_new/2                      <- 재구성
  6. clamp to [0, target_w] x [0, target_h]                   <- 경계 처리
```

### 변환 필요 여부 판단

`<original_size>`가 아니라 **bbox 좌표 범위**로 판단합니다.
(EC2에서 가져온 annotation은 1920x1080 좌표인데 task DB는 이미 320x240일 수 있음)

- bbox 좌표가 target(320x240)을 초과하면 → 1920x1080 공간으로 감지 → 변환
- bbox 좌표가 target 범위 안이면 → 이미 변환됨 → skip (멱등)

## 파일 구성

| 파일 | 설명 |
|------|------|
| `migrate_v1.sh` | **Shell wrapper** — Docker 컨테이너 안에서 batch 실행 |
| `migrate_v1.py` | **핵심 로직** — batch(`--all-jobs`) + 단일 job 모드 |
| `README.md` | 이 문서 |

## 사용법

### 전체 일괄 마이그레이션 (권장)

```bash
# Dry-run (변환 대상 확인만, 업로드 안 함)
bash scripts/migration/migrate_v1.sh --user admin --password admin123 --dry-run

# 실제 마이그레이션 실행
bash scripts/migration/migrate_v1.sh --user admin --password admin123

# 특정 job만 마이그레이션
bash scripts/migration/migrate_v1.sh --user admin --password admin123 --job-ids 7,8,9
```

내부 동작:
1. `migrate_v1.py`를 `cvat_server` 컨테이너로 복사
2. 컨테이너 안에서 `--all-jobs` 모드로 실행
3. 각 job: annotation export → 좌표 변환 → 기존 삭제 → 변환된 XML 업로드
4. 완료 후 복사한 파일 정리

> **멱등성**: 이미 변환된 job은 자동 skip됩니다. 여러 번 실행해도 안전합니다.

### 단일 job 변환 (직접 Python 실행)

```bash
python scripts/migration/migrate_v1.py \
    input.xml output.xml \
    --job-id 7 --user admin --password admin123 --upload
```

### 옵션 목록

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--all-jobs` | 모든 job 일괄 변환 (batch 모드) | - |
| `--job-ids IDs` | 특정 job만 변환 (쉼표 구분) | 전체 |
| `--dry-run` | 변환 대상 확인만 (업로드 안 함) | false |
| `--user` | CVAT 사용자명 | 필수 |
| `--password` | CVAT 비밀번호 | 필수 |
| `--server URL` | CVAT 서버 주소 | `http://localhost:8080` |
| `input` / `output` | XML 파일 경로 (단일 모드) | batch 시 불필요 |
| `--job-id ID` | 단일 job 해상도 자동 감지 | - |
| `--target-w` / `--target-h` | 수동 해상도 지정 | API 자동 감지 |
| `--upload` | 변환 후 자동 업로드 (단일 모드) | false |

---

## History

### 문제 발견 및 분석

**증상**: Master에서 export한 annotation을 Refactor task에 import했으나,
bbox가 캔버스에 표시되지 않음 (1920x1080 좌표가 320x240 캔버스 밖에 위치).

**근본 원인**: Docker에 ffprobe 미설치 → `_extract_video_metadata()` fallback → 1920x1080 저장

### 개발 과정

1. **단순 비균등 스케일링**: X÷6, Y÷4.5 독립 스케일링
   - 문제: bbox 비율 변함 (정사각형 → 세로로 긴 직사각형)
2. **API 자동화 추가**: CVAT API 해상도 자동 감지, 로그인 인증, 자동 업로드
3. **Hybrid Scaling (현재 v1)**: 중심점은 비균등, bbox 크기는 기하평균 균등 스케일링
   - bbox 좌표 범위로 변환 필요 여부 자동 판단 (멱등성)
   - batch 모드 (`--all-jobs`) + Docker shell wrapper 통합
