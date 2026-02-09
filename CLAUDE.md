# CVAT Multiview Workspace - Development Notes

## Project Overview

CVAT(Computer Vision Annotation Tool)에 **1-10개 카메라 동기화 라벨링**을 위한 Multiview Workspace를 추가한 프로젝트.

### 주요 기능
- 1-10개 비디오 뷰 동시 표시 및 동기화 재생
- 뷰별 독립적인 어노테이션 (`viewId`로 필터링)
- 오디오 스펙트로그램 시각화 (오디오 믹싱)
- 스펙트로그램 클릭으로 프레임 네비게이션
- 재생 속도 조절 (0.25x ~ 2x)
- Draw 모드 진입 시 비디오 자동 일시정지
- 뷰별 마우스 스크롤 줌 인/아웃 (1x~5x, bbox 정렬 유지)

---

## Architecture

### 주요 컴포넌트

```
cvat-ui/src/components/annotation-page/multiview-workspace/
├── multiview-workspace.tsx      # 메인 워크스페이스 (비디오 재생 제어)
├── multiview-video-grid.tsx     # 비디오 뷰 그리드 레이아웃
├── video-canvas.tsx             # 개별 비디오 + 캔버스 오버레이
├── multiview-canvas-wrapper.tsx # Canvas 이벤트 핸들링 및 어노테이션 관리
├── spectrogram-panel.tsx        # 오디오 스펙트로그램 시각화
├── audio-engine.ts              # Web Audio API + FFT 구현
├── multiview-objects-list.tsx   # 어노테이션 목록 (뷰별 필터링)
├── types.ts                     # 타입 정의
└── styles.scss                  # 스타일

cvat-ui/src/utils/
├── canvas-utils.ts              # Canvas 상태 관리 유틸리티
└── multiview-hooks.ts           # Multiview 전용 훅

cvat-ui/src/contexts/
└── MultiviewContext.tsx          # Multiview Context API (prop drilling 제거)

cvat-ui/src/components/create-task-page/
└── multiview-file-upload.tsx    # Multiview Task 생성 UI (1-10개 뷰)
```

### 데이터 흐름

1. **비디오 재생**: `multiview-workspace.tsx` → 모든 `video-canvas.tsx` 동시 제어
2. **어노테이션 생성**: `video-canvas.tsx` → `multiview-canvas-wrapper.tsx` → Redux
3. **스펙트로그램**: `spectrogram-panel.tsx` ↔ `audio-engine.ts` (FFT)
4. **프레임 동기화**: Redux `frameNumber` ↔ 비디오 `currentTime`

### viewId 시스템

- 각 어노테이션은 `viewId`로 생성 뷰를 기록
- 캔버스 설정 시 해당 viewId 어노테이션만 필터링
- viewId가 null/undefined인 어노테이션은 모든 뷰에서 표시

### Backend 모델

```python
class MultiviewData(models.Model):
    data = models.OneToOneField(Data, ...)
    view_count = models.PositiveSmallIntegerField(default=5)
    video_view1~10 = models.ForeignKey(Video, ...)  # 10개 ForeignKey
    session_id = models.CharField(max_length=64)
    part_number = models.IntegerField()
    original_files = models.JSONField(default=dict)  # 원본 파일명 메타데이터
```

API: `POST /api/tasks/create_multiview/`

### 좌표 시스템

- Canvas 공간: 1920 × 1440 (비디오 4:3 비율에 맞춤)
- Task 공간: 1920 × 1080 (백엔드 저장)
- Y 스케일: canvas→task = 0.75 (1080/1440)

---

## Known Issues & Solutions

| 문제 | 해결 | 파일 |
|------|------|------|
| "Canvas is busy" 에러 | `defaultData`에 `mode: Mode.IDLE` 확인 | `canvasModel.ts` |
| 어노테이션이 다른 뷰에 표시 | viewId 필터링 확인 | `multiview-canvas-wrapper.tsx` |
| 오디오 안 나옴 | `engine.initialize()` 호출 제거 | `multiview-workspace.tsx` |
| 삭제한 어노테이션 캔버스에 남음 | `OBJECTS_UPDATED` 알림 조건: `image \|\| objectsChanged` | `canvasModel.ts` |
| Play/Pause 후 Draw 안됨 | Pause 시 `updateActiveControlAction(CURSOR)` | `multiview-workspace.tsx` |
| Draw 시 하얀색 오버레이 | `.cvat_canvas_shape_drawing { fill: transparent !important }` | `styles.scss` |
| Draw 중 Play하면 의도치 않은 Shape 생성 | Draw 모드 진입 시 자동 일시정지 | `multiview-workspace.tsx` |
| 좌표 불일치 | `fitCanvas()`에 `setupCalled` 플래그 가드 추가 | `canvasModel.ts` |
| Export 포맷 "No data" | multiview dimension에서 2D 포맷 허용 | `export-dataset-modal.tsx` |
| Export TypeError (overlap=None) | `overlap = overlap or 0` | `annotation.py` |
| Export에 view_id 누락 | DB 쿼리에 `view_id` 필드 추가 | `task.py` |
| Export 키프레임만 출력 | `keyframe` 필터링 추가 | `cvat.py` |
| view_id KeyError | `.get()` 사용 | `serializers.py` |
| 마우스 휠로 Canvas zoom 방지 | wheel 이벤트 capture + `preventDefault()` | `multiview-canvas-wrapper.tsx` |
| 좌클릭으로 Canvas pan 방지 | mousedown capture에서 배경 좌클릭 시 `stopPropagation()` | `multiview-canvas-wrapper.tsx` |
| Rectangle 드래그 후 위치 안 저장 | `canvas.edited` 이벤트 + Redux 원본 ObjectState로 업데이트 | `multiview-canvas-wrapper.tsx` |
| Shape 편집 후 새 Shape 그리면 복구됨 | Redux 원본 ObjectState를 clientID로 찾아 업데이트 | `multiview-canvas-wrapper.tsx` |
| Shape 클릭해도 선택 안됨 | `activateObject` dispatch + `canvasInstance.activate()` | `multiview-canvas-wrapper.tsx` |
| 프레임 떨림 (oscillation) | `top-bar.tsx` Multiview 예외 처리 + `playingRef` + throttling | `multiview-workspace.tsx`, `top-bar.tsx` |
| Multi-class 모드에서 Sound 라벨 잔존 | DELETE `/api/labels/{id}` 사용 | `insert_bbox_annotations.py` |
| Pre-annotation 편집 시 다른 annotation 영향 | `cloneObjectStateForDisplay()` (non-enumerable 속성 명시적 복사) | `multiview-canvas-wrapper.tsx` |
| Shape 뷰 경계 드래그 시 축소 | videoElement 실제 치수 우선 + `clampPointsToCanvasBounds()` | `multiview-canvas-wrapper.tsx` |
| 작은 Shape 드래그 시 크기 축소 | `enforceMinimumShapeDimensions()` (resize handle 겹침 보정) | `multiview-canvas-wrapper.tsx` |
| 반복 리사이즈 시 Shape 사라짐 | `normalizeAndEnforceTaskSpaceDimensions()` (최소 치수 2px 강제) | `multiview-canvas-wrapper.tsx` |

---

## Export/Import

### Export 파이프라인

- 포맷: CVAT for video 1.1 (키프레임만 출력)
- view_id 속성 포함 (`task.py` DB 쿼리에 `view_id` 추가)
- 원본 파일명: `original_files` JSONField + `video.path` fallback

### 캐시 무효화

```bash
docker exec cvat_server bash -c "rm -rf /home/django/data/cache/export/job-{JOB_ID}-*"
docker compose restart cvat_worker_export
```

---

## Docker Commands

```bash
# UI 빌드 및 재시작
docker compose build cvat_ui && docker compose up -d cvat_ui

# 전체 재시작
docker compose down && docker compose up -d

# 로그 확인
docker compose logs -f cvat_ui
```

로컬 dist 마운트 시 (`docker-compose.override.yml`):
```bash
cd cvat-ui && npm run build
```

---

## Docker 배포 구조

### 이미지 저장소

- **메인 저장소**: `kuielab/cvat-multiview` (GitHub)
- **컨테이너 레지스트리**: `ghcr.io/kuielab/cvat-multiview-server`, `ghcr.io/kuielab/cvat-multiview-ui`

### 실행 환경별 설정

| 환경 | 명령어 | 설명 |
|------|--------|------|
| **로컬 개발** | `docker compose up -d --build` | override 적용, 소스 마운트, localhost만 허용 |
| **EC2/프로덕션** | `docker compose -f docker-compose.yml up -d` | override 미적용, ghcr.io 이미지 사용 |
| **EC2 (호스트 설정)** | `CVAT_HOST=<ip> docker compose up -d` | 외부 IP/도메인으로 접근 허용 |

### 배포 관련 이슈

| 문제 | 해결 |
|------|------|
| EC2에서 404 오류 | override 제거 또는 `CVAT_HOST` 환경변수 사용 |
| datumaro 빌드 실패 (edition2024) | Dockerfile에서 rustup으로 최신 Rust 설치 |
| ghcr.io 이미지 pull 실패 | kuielab 저장소에서 Actions 실행 후 패키지 공개 설정 |

### kuielab 저장소 설정

1. **GitHub Actions 권한**: Settings → Actions → General → "Read and write permissions"
2. **패키지 공개 설정** (첫 빌드 후): https://github.com/orgs/kuielab/packages → Public
3. **Secrets**: 불필요 (GITHUB_TOKEN 자동 제공)

---

## Init Scripts (Pre-annotation)

`scripts/init/` 폴더:

| 스크립트 | 설명 |
|---------|------|
| `insert_bbox_annotations.py` | Pre-annotation bbox 삽입 |
| `insert_prelabels.sh` | Shell wrapper |

### 사용법

```bash
# Dry-run (이진분류)
python scripts/init/insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /path/to/dataset \
    --datasets multisensor_home1 \
    --dry-run --limit 5

# 실제 삽입
python scripts/init/insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /path/to/dataset \
    --datasets multisensor_home1 multisensor_home2 mmoffice \
    --bbox-size 300 --divisions 3

# 다중 클래스 모드
python scripts/init/insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /path/to/dataset \
    --datasets multisensor_home1 \
    --use-dataset-labels

# 데이터 분할 (test만)
python scripts/init/insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /path/to/dataset \
    --split test --use-dataset-labels
```

### 옵션

| 옵션 | 값 | 설명 |
|------|-----|------|
| `--label` | `Sound` (기본) | 이진분류: 단일 라벨 |
| `--use-dataset-labels` | | 다중 클래스: 실제 라벨 사용 |
| `--split` | `test`/`train`/`all` | 데이터 분할 선택 |
| `--divisions` | `2`/`3`/`5` | 구간 분할 수 (기본: 3) |
| `--bbox-size` | `300` (기본) | Bbox 크기 (px) |

---

## Test Scripts

`scripts/test/` 폴더:

| 스크립트 | 설명 |
|---------|------|
| `setup_test_task.py` | 테스트 Task 생성 (합성 비디오 + Pre-annotation) |
| `test_preannotation_edit.py` | Pre-annotation 편집 53개 테스트 케이스 |

```bash
# 테스트 Task 생성
python scripts/test/setup_test_task.py --user admin --password admin123

# 테스트 실행
python scripts/test/test_preannotation_edit.py --user admin --password admin123
```

---

## Test URL

```
http://127.0.0.1:8080/tasks/{task_id}/jobs/{job_id}
```
