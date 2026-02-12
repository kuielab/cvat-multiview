# Migration: Master → Refactor Annotation Coordinate Converter

## 왜 필요한가

Master 브랜치의 Docker 이미지에 `ffprobe`가 설치되어 있지 않았습니다.
비디오 업로드 시 `_extract_video_metadata()` 함수가 ffprobe를 호출하지만 실패하여,
**실제 해상도와 무관하게 1920x1080으로 fallback** 저장되었습니다.

그 결과, Master에서 생성한 annotation은 **가짜 1920x1080 좌표 공간**에 저장되어 있어서,
Refactor 환경(실제 320x240)에서 그대로 사용하면 bbox가 캔버스 밖에 위치하게 됩니다.

## 변환 알고리즘 (Hybrid Scaling)

| 요소 | 스케일링 방식 | 이유 |
|------|-------------|------|
| **중심점 위치** | 비균등 (X, Y 독립) | 실제 비디오 좌표에 정확히 매핑 |
| **Bbox 크기** | 균등 (기하평균 sqrt(sx*sy)) | 어노테이터의 의도한 bbox 비율 보존 |

```
uniform_scale = sqrt(scale_x * scale_y)

변환 과정 (각 bbox):
  1. center_new = (center_x * scale_x, center_y * scale_y)  ← 비균등
  2. size_new = size * uniform_scale                          ← 균등
  3. clamp to [0, target_w] x [0, target_h]
```

### 변환 필요 여부 판단

bbox 좌표 범위로 자동 판단 (멱등):
- 좌표가 target(320x240)을 초과 → 변환 필요
- 좌표가 target 범위 안 → skip

## 사용법

### 전체 일괄 마이그레이션 (권장)

```bash
# Dry-run (변환 대상 확인만, DB 수정 안 함)
bash scripts/migration/migrate_v1.sh --dry-run

# 실제 마이그레이션 실행
bash scripts/migration/migrate_v1.sh

# 특정 job만 마이그레이션
bash scripts/migration/migrate_v1.sh --job-ids 7,8,9
```

### 동작 방식 (Direct DB)

1. Django ORM 초기화
2. **RQ 큐 정리**: 이전 실행에서 남은 export/import 큐 강제 비움
3. **Phase 1 (Segment repair)**: annotation max frame > stop_frame이면 확장
4. **Phase 2 (좌표 변환)**: `TrackedShape.points`, `LabeledShape.points` 직접 UPDATE
5. Export 캐시 무효화

> HTTP export/import 없음. RQ 큐 병목 없음. 1140 jobs도 수초 내 완료.

### 단일 XML 파일 변환 (오프라인)

```bash
python scripts/migration/migrate_v1.py \
    input.xml output.xml --target-w 320 --target-h 240
```

### 옵션 목록

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--all-jobs` | 모든 job 일괄 변환 (batch 모드) | - |
| `--job-ids IDs` | 특정 job만 변환 (쉼표 구분) | 전체 |
| `--dry-run` | 변환 대상 확인만 (DB 수정 안 함) | false |
| `input` / `output` | XML 파일 경로 (단일 모드) | batch 시 불필요 |
| `--target-w` / `--target-h` | 수동 해상도 지정 (단일 모드) | - |
