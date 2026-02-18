# CVAT Multiview Workspace - Changelog

CVAT에 1-10개 카메라 동기화 라벨링을 위한 Multiview Workspace를 구현하며 진행한 전체 개발 내역.

---

## 2026-01-06: Initial Multiview Workspace

최초 Multiview Workspace 구현. 5개 카메라 뷰 동시 표시 및 동기화 재생.

### 주요 구현

- **Multiview Workspace 컴포넌트** (`multiview-workspace.tsx`, `multiview-video-grid.tsx`, `video-canvas.tsx`)
  - 5개 비디오 뷰 그리드 레이아웃
  - 동기화 재생/일시정지 (모든 뷰 동시 제어)
  - 재생 속도 조절 (0.25x ~ 2x)
- **스펙트로그램 시각화** (`spectrogram-panel.tsx`, `audio-engine.ts`)
  - Web Audio API + FFT 기반 오디오 스펙트로그램
  - 5개 뷰 오디오 믹싱
  - 스펙트로그램 클릭으로 프레임 네비게이션
- **viewId 기반 어노테이션 시스템**
  - `view_id` 필드로 뷰별 독립 어노테이션
  - Canvas/Shape 클래스에 `setViewId()` 메서드 추가
  - 뷰별 어노테이션 필터링

### 커밋

| 커밋 | 설명 |
|------|------|
| `307ffbe` | 5-camera synchronized annotation workspace |
| `092a2d4` | Pre-computed spectrogram for audio visualization |
| `f18ccdd` | Synchronized video playback, spectrogram click navigation |
| `a914463` | view_id field for multiview annotations |
| `10b32aa` | viewId support in Canvas and Shape classes |

---

## 2026-01-06 ~ 01-08: 초기 버그 수정

### 수정 내역

- **Canvas is busy 에러** — `defaultData`에 `mode: Mode.IDLE` 확인, 이벤트 핸들러 초기화 (`6b4a70c`)
- **어노테이션 생성 실패** — attribute 유효성 검사, imageSize 초기화 (`7a8013f`)
- **삭제한 어노테이션 캔버스에 잔존** — image 없이도 `OBJECTS_UPDATED` 알림 발송 (`a61fa36`)
- **오디오 안 나옴** — Web Audio API `createMediaElementSource()` 호출 제거 (`1910279`)
- **스펙트로그램 재생 중 seek** — 일시정지→seek→재개 로직 추가 (`62b26b4`)
- **view_id 직렬화 KeyError** — `.get()` 사용으로 안전한 접근 (`0fe6bf0`)

---

## 2026-01-11 ~ 01-13: UI/UX 개선 및 Export/Import

### 기능 추가

- **Delete 키 단축키** — Multiview에서 annotation 삭제 지원 (`ce2864c`, `e243591`)
- **캔버스 인터랙션** — shape 클릭, 비활성화, 커서 이동, 편집 완료 이벤트 핸들러 (`dd824ac`)
- **키프레임만 Export** — CVAT for video 포맷에서 keyframe=True만 출력 (`0d10df5`)
- **1-10개 뷰 가변 지원** — 고정 5뷰 → 동적 1-10뷰, Add/Remove 버튼 UI (`537d613`)
- **view_id Import 파싱** — annotation import 시 view_id 필드 인식 (`63fbfeb`)
- **Objects 사이드바 갱신** — SHAPE 타입 프레임 변경 시 목록 갱신 (`5c4c2a9`)

### 수정 내역

- **viewId 필터링** — viewId 없는 어노테이션은 View 1에만 표시 (`a5f428c`)
- **Draw 모드 유지** — canvas wrapper가 active draw를 cancel() 하지 않도록 (`8770864`)
- **사이드바 프로퍼티 패널 제거** — 미사용 MultiviewProperties 컴포넌트 정리 (`8d7d8d6`)

---

## 2026-01-14 ~ 01-29: 좌표 시스템 안정화 및 Shape 편집

### 좌표 시스템

- **좌표 변환 유틸리티** — canvas 공간(1920x1440, 4:3) ↔ task 공간(1920x1080, 16:9) 변환 (`eb433fc`, `d9c925f`)
- **fitCanvas() 이후 setup() 호출 순서 보장** — `setupCalled` 플래그로 조기 fitCanvas 방지 (`0e25d4d`)
- **Drawing 시 흰색 오버레이** — `.cvat_canvas_shape_drawing { fill: transparent !important }` (`9fdb064`)
- **캔버스 렌더링 안 됨** — async `frameData.data()` 전에 동기적 `OBJECTS_UPDATED` 알림 추가 (`95cbec2`)
- **뷰 전환 후 Drawing 안 됨** — `fitCanvas()`에 optional width/height 파라미터 추가 (`4bbef1f`, `d7a4ae4`)
- **View 4에서 50% 축소** — fitCanvas()를 setup() 이후 호출하도록 순서 보장 (`0a6b9c2`)

### Shape 인터랙션

- **Shape 클릭 선택** — `activateObject` dispatch + `canvasInstance.activate()` (`bc94fc1`)
- **Shape 편집 후 위치 저장** — `canvas.edited` 이벤트 + Redux 원본 ObjectState로 업데이트 (`01864b5`)
- **original_files 메타데이터** — Export에 원본 파일명 포함 (`0e25d4d`)

### 스펙트로그램

- **60fps playhead** — overlay canvas + requestAnimationFrame으로 부드러운 플레이헤드 (`944fdf2`)

---

## 2026-01-29 ~ 01-30: Export UI, 재생 안정화, 배포

### 기능 추가

- **Export/Download 버튼** — Jobs, Tasks, Requests 페이지에 Export 버튼 추가 (`27ebfde`, `fabcbd2`)
- **Multiview 사용자 가이드** — 전체 워크플로우 문서화 (`dccfd3c`)
- **PostgreSQL 백업** — Google Drive 백업 스크립트 (pg_dump + rclone) (`aa5894a`)

### 재생 안정화

- **프레임 떨림(flickering) 해결** — standard player frame sync 비활성화, `playingRef` + `pendingDispatch` throttling (`f0cc9af`)

### Docker / CI/CD

- **auto-build** — `docker compose up` 시 cvat_ui 자동 빌드 (`2556d14`)
- **docker-compose.override.yml 정리** — 로컬/EC2 환경 분리, `CVAT_HOST` 환경변수 (`bc7fd6d`)
- **GitHub Actions** — ghcr.io 이미지 빌드 및 푸시 (`0446882`, `c56212e`)
- **Rust 빌드 수정** — datumaro edition2024 대응, rustup으로 최신 Rust 설치 (`dc1a508`)
- **LF 줄바꿈 강제** — `.gitattributes` 추가 (Windows Docker 충돌 방지) (`213e26c`)

---

## 2026-01-31: 조직/사용자 관리

### 기능 추가

- **Organization 지원** — `create_multiview` API에 org 필드, `X-Organization` 헤더 (`3892f03`, `130ede5`)
- **setup_cvat.sh** — 초기 설정 스크립트 (superuser, organization 생성) (`5862bb0`, `dba4711`)
- **조직별 Task 배정** — `assign_tasks_to_orgs.sh`, `--sessions`/`--split-ids` 필터 (`3a0cd15`)

---

## 2026-02-03 ~ 02-04: Pre-annotation 스크립트

### 기능 추가

- **Pre-annotation bbox 삽입** — `insert_bbox_annotations.py`, 구간 분할(2/3/5), bbox 크기 설정 (`9a24519`)
- **다중 클래스 지원** — `--use-dataset-labels` 옵션, 동적 라벨 생성 (`ac045fd`)
- **데이터 분할** — `--split test/train/all` 옵션 (`3063f6b`)
- **Sound 라벨 잔존 수정** — DELETE `/api/labels/{id}` API 사용 (`41d6a58`)

---

## 2026-02-05 ~ 02-09: Shape 안정성 및 줌 기능

### 좌표 변환

- **백엔드 메타데이터 기반 변환** — VideoSerializer에 width/height 추가, 일관된 좌표 변환 (`cda7769`)

### Shape 안정성

- **뷰 경계 드래그 시 축소 방지** — `clampPointsToCanvasBounds()` (치수 보존, 위치만 이동) (`46b77f1`)
- **클릭 시 미세 좌표 이동 방지** — `MIN_DRAG_THRESHOLD` (5px) 적용 (`af05f14`)
- **반복 리사이즈 시 사라짐 방지** — `normalizeAndEnforceTaskSpaceDimensions()` (최소 2px 강제) (`14f6300`)
- **어노테이션/비디오 로딩 레이스 컨디션** — videoElement 치수 가드 추가 (`8b01b95`)

### 줌 기능

- **뷰별 마우스 스크롤 줌** — 1x~5x, bbox 정렬 유지 (`4ac757b`)

---

## 2026-02-10 ~ 02-12: Canvas 안정화 및 Pan/Resize 수정

### Canvas Setup 안정화

- **Canvas setup 리팩토링** — timeout fallback 제거, 메타데이터 기반 치수 적용 (`c18164b`)
- **ResizeObserver 가드** — setup 완료 전 resize 방지 (`71d2b46`)
- **우클릭 pan + resize bbox jump 수정** — `zoomStateRef`, fit() 항상 호출 (`81b5790`)

### Pan 제어

- **좌클릭 pan 제거** — Drawing/shape 인터랙션 방해 방지, 우클릭/중클릭/Alt+좌클릭만 pan (`1988397`)

### Delete/Draw 수정

- **Delete 키 이중 실행** — `removeObjectAsync` 직접 사용 + `stopImmediatePropagation()` (`2adf013`)
- **Draw 모드 종료 시 크로스헤어 잔존** — `draw({ enabled: false })` 호출 (`71a06bf`)
- **X+Y 좌표 변환 통합** — 양 축 모두 변환, 메타데이터 우선, jitter 억제 (`db6dc88`)

### Canvas 인스턴스 관리

- **뷰별 Canvas 인스턴스** — `canvasInstancesRef`, unmount 시 cleanup, dblclick focus/fit 차단 (`a25fe3c`)
- **커스텀 drag/shape threshold 제거** — 원본 CVAT 동작 복원 (`742b4a6`)

---

## 2026-02-12: Major Refactor — Video Overlay에서 Canvas-Only로

`836f494` (squashed from refactor branch) — 52 files changed, +5,536 / -1,106

### Before — Video Overlay 방식의 근본적 문제

리팩토링 이전 아키텍처는 **Video Overlay** 방식이었다.
화면에 HTML `<video>` 요소로 영상을 보여주고, 그 위에 Canvas(SVG)를 오버레이해서 bbox 등 어노테이션을 그리는 구조.

```
[Video Overlay 구조]

┌─── video-canvas-container ────────────┐
│  ┌─── <video> element ─────────────┐  │  ← 비디오 프레임 표시 (브라우저 네이티브)
│  │    videoWidth × videoHeight      │  │
│  └──────────────────────────────────┘  │
│  ┌─── Canvas SVG overlay ──────────┐  │  ← annotation 그리기 (CVAT Canvas)
│  │    canvasWidth × canvasHeight    │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

문제는 **`<video>` 요소와 Canvas가 서로 다른 좌표계**를 가진다는 것이다.
`<video>`의 실제 렌더 크기는 컨테이너 크기, CSS `object-fit`, 브라우저 렌더링 엔진에 따라 결정된다.
Canvas의 좌표계는 `canvasInstance.setup()` 호출 시 전달된 이미지 크기를 기준으로 한다.
이 두 좌표계를 완벽히 일치시키려면 `<video>`가 실제로 화면에 몇 픽셀로 그려졌는지를 정확히 알아야 하는데,
`videoElement.videoWidth/Height`는 세션마다, 뷰마다, 심지어 같은 브라우저에서 새로고침할 때마다 미세하게 달라질 수 있다.

그 결과:
- **새로고침할 때마다 bbox가 1-5px씩 이동** (coordinate drift)
- `loadedmetadata` 이벤트에서 `videoWidth`를 읽으면 0이 반환되는 경우 (첫 프레임 디코딩 전)
- CSS zoom과 Canvas 내부 zoom이 서로 충돌 (2개의 독립적인 transform 레이어)
- `use-stable-video-dims.ts`에서 228줄에 걸쳐 videoElement 치수를 샘플링/안정화하는 코드가 필요했음

Standard CVAT는 이 문제가 없다. Standard CVAT는 처음부터 Canvas-Only 방식을 사용한다:
서버가 제공하는 `frameData`가 유일한 좌표 기준이고, 브라우저의 `<video>` 렌더링에 의존하지 않는다.
Multiview도 이 방식을 따르기로 했다.

### After — Canvas-Only 렌더링

Canvas-Only는 `<video>` 요소를 사용하지 않고, **비디오 프레임을 직접 디코딩해서 Canvas의 배경 이미지로 그리는** 방식이다.
어노테이션(bbox)도 같은 Canvas 위에 SVG로 그리기 때문에, 좌표계가 하나로 통일된다.

```
[Canvas-Only 구조]

┌─── canvas-container ──────────────────┐
│  ┌─── Canvas ──────────────────────┐  │
│  │  background: ImageBitmap (프레임) │  │  ← 직접 디코딩한 프레임 이미지
│  │  SVG overlay: bbox, polygon...   │  │  ← 같은 좌표계에서 annotation
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

좌표 기준이 백엔드 메타데이터(width, height)로 고정되므로,
HTMLVideoElement의 렌더링 크기에 의존하지 않는다.
새로고침해도, 뷰를 전환해도, 줌을 해도 좌표가 안정적이다.

### Chunk이란 — 프레임 로딩 방식

Canvas-Only에서는 `<video>`가 없으므로 비디오 프레임을 직접 가져와야 한다.
CVAT는 비디오를 **chunk** 단위로 분할해서 제공한다.

**Chunk = 비디오를 N프레임씩 잘라놓은 MP4 조각.**

예를 들어 3000프레임 비디오를 chunkSize=36으로 자르면 약 84개의 chunk가 된다.
클라이언트가 100번 프레임을 요청하면:

1. 100번 프레임이 속한 chunk 인덱스를 계산 (100 ÷ 36 = chunk #2)
2. 서버에 `GET /api/tasks/{id}/multiview/data/{viewId}?type=chunk&index=2` 요청
3. 서버가 PyAV로 원본 비디오에서 해당 구간을 추출해 MP4로 반환
4. 클라이언트에서 **Broadway.js**(JavaScript H.264 소프트웨어 디코더)로 chunk의 모든 프레임을 디코딩
5. 디코딩된 각 프레임은 **ImageBitmap**으로 LRU 캐시에 저장
6. 요청한 100번 프레임의 ImageBitmap을 Canvas 배경에 그림

한번 디코딩된 chunk의 프레임들은 메모리 캐시에 남아있으므로,
같은 프레임을 다시 요청하면 서버 통신 없이 즉시 반환된다.

```
[프레임 로딩 파이프라인]

서버                                    클라이언트

/multiview/data/{viewId}?type=chunk     multiview-frames.ts
  → MP4 chunk (N프레임 묶음)              → Broadway.js (H.264 소프트웨어 디코딩)
  → PyAV로 원본 비디오에서 추출             → ImageBitmap으로 변환
                                          → LRU 캐시에 저장

/multiview/meta/{viewId}                canvasModel.ts setup()
  → chunkSize, fps, width, height         → frameData.data() 호출
  → 프레임 인덱스 매핑                       → 캐시 히트: 즉시 반환
                                            → 캐시 미스: chunk fetch → decode → 반환
                                          → IMAGE_CHANGED 알림 → Canvas 배경에 렌더링
```

### `<video>` vs Chunk — 왜 둘 다 쓰나

| | HTML `<video>` | Chunk + Broadway.js |
|---|---|---|
| **디코딩** | 브라우저 네이티브 (GPU 하드웨어 가속) | JavaScript 소프트웨어 디코딩 (CPU) |
| **버퍼링** | 브라우저가 HTTP Range 요청으로 자동 관리 | 직접 chunk 단위로 fetch + 캐시 관리 |
| **성능** | 매우 빠름 (HW 가속, 자동 선읽기) | 느림 (SW 디코딩, 명시적 fetch) |
| **프레임 정확도** | **부정확** — `currentTime` seek은 가장 가까운 keyframe으로 이동 | **정확** — 정확히 N번 프레임 접근 가능 |
| **어노테이션 작업** | 프레임이 1-2프레임 어긋날 수 있음 | 정확한 프레임에 bbox를 그릴 수 있음 |

Active 뷰(어노테이션 작업 뷰)는 **프레임 정확도가 필수**이므로 Chunk 방식을 사용한다.
어노테이터가 "이 프레임에 bbox를 그렸다"고 할 때, 실제로 그 정확한 프레임이어야 한다.
`<video>.currentTime = frameNumber / fps`로 seek하면, 브라우저가 가장 가까운 keyframe으로 이동하기 때문에
의도한 프레임과 1-2프레임 차이가 날 수 있다.

반면 Preview 뷰(나머지 비활성 뷰)는 어노테이션 편집을 하지 않으므로 정확한 프레임이 아니어도 된다.
그래서 브라우저의 `<video>` 네이티브 재생(하드웨어 가속, 자동 버퍼링)을 사용해서 성능을 확보한다.

정리하면:

| 뷰 | 렌더링 방식 | 이유 |
|---|---|---|
| **Active 뷰** (1개) | Canvas + Chunk + Broadway.js | 프레임 정확, bbox 좌표 일치 |
| **Preview 뷰** (나머지) | HTML `<video>` + SVG bbox 오버레이 | 성능 우선, HW 가속 |

### 파일별 변경 상세

#### 신규 모듈

| 파일 | 줄 수 | 설명 |
|------|-------|------|
| `cvat-core/src/multiview-frames.ts` | 278 | Chunk 기반 프레임 디코더. FrameDecoder 래퍼, LRU 캐시, chunk 프리페치, 메타데이터 관리 |
| `multiview-frame-provider.ts` | 44 | cvat-core multiviewFrames API를 UI 컴포넌트에 연결하는 브릿지 |
| `multiview-video-preview.tsx` | 129 | Preview 뷰 컴포넌트. `<video>` 네이티브 재생 + SVG rect bbox 오버레이. 재생 중 free-run, 정지 시 currentTime seek |
| `multiview-canvas-preview.tsx` | 157 | Canvas 기반 preview (fallback). 재생 중 1000ms throttle로 2fps 업데이트 |
| `multiview-canvas-setup.ts` | 70 | setup 파이프라인 분리. `runSetupPipeline()`: setViewId → setup → fitCanvas → fit → lockViewport |
| `multiview-canvas-events.ts` | 85 | 이벤트 핸들러 바인딩/해제. stable ref wrapper로 re-mount 없이 콜백 교체 |

#### 주요 수정 모듈

| 파일 | 변경 | 설명 |
|------|------|------|
| `multiview-workspace.tsx` | -310줄 | `<video>` 요소 관리 전체 제거. Canvas clock 기반 재생 루프만 유지 |
| `video-canvas.tsx` | -229줄 → 175줄 | `<video>` DOM 렌더링 제거. Active: Canvas overlay, Preview: `<video>` 컴포넌트 |
| `multiview-canvas-wrapper.tsx` | 286줄 리팩토링 | `createFrameDataFromMultiview()` Proxy로 frameData.data() 오버라이드 |
| `canvasModel.ts` | +64줄 | `setViewId()` — viewId 변경 시 이미지 무효화 (같은 프레임이라도 다른 뷰 이미지 로드) |
| `views.py` (backend) | +471줄 | chunk endpoint 구현. PyAV로 비디오에서 chunk 추출, 메타데이터 endpoint |
| `server-proxy.ts` | +59줄 | `multiview.getData()`, `multiview.getMeta()` API 클라이언트 |

#### 제거된 모듈

| 파일 | 줄 수 | 이유 |
|------|-------|------|
| `use-stable-video-dims.ts` | 228 | HTMLVideoElement 치수 샘플링 — Canvas-Only에서 불필요 |
| `multiview-canvas-utils.ts` (일부) | 95 | 좌표 변환 로직 `multiview-canvas-wrapper.tsx`로 통합 |

### 해결된 핵심 문제

| 문제 | 원인 (Video Overlay) | 해결 (Canvas-Only) |
|------|-------------|-------------|
| 새로고침 시 bbox drift (1-5px) | `<video>` 렌더 크기가 세션마다 변동 | 백엔드 메타데이터 고정 좌표 (videoWidth에 비의존) |
| Black screen | CSS `display: none !important`가 canvas background 숨김 | `display: none` 제거 (이제 canvas background에 프레임을 그림) |
| 뷰 전환 시 이전 뷰 이미지 표시 | `setup()` early-return (같은 frameNumber면 스킵) | `setViewId()`에서 imageID 무효화 → 강제 재로드 |
| CSS zoom과 Canvas zoom 충돌 | `<video>` CSS transform + Canvas 내부 transform 이중 적용 | Canvas 내장 zoom만 사용 (단일 transform 레이어) |
| Preview 캔버스 재생 성능 | 4개 preview 모두 Canvas + Broadway.js 디코딩 | Preview는 `<video>` 네이티브 재생 (HW 가속) |

### Backend API 확장

| Endpoint | 설명 |
|----------|------|
| `GET /api/tasks/{id}/multiview/data/{view_id}?type=chunk&index=N&quality=compressed` | MP4 chunk 반환. PyAV로 비디오에서 N프레임 구간 추출 |
| `GET /api/tasks/{id}/multiview/meta/{view_id}` | 뷰별 메타데이터: chunkSize, fps, width, height, startFrame, stopFrame |

### E2E 테스트 (Playwright)

36개 테스트 케이스, 4 workers 병렬 실행:

| 테스트 파일 | 케이스 | 검증 내용 |
|------------|--------|----------|
| `multiview-annotation-crud.spec.ts` | 5 | bbox 생성/수정/삭제, 뷰별 필터링, 프레임 간 유지 |
| `multiview-playback.spec.ts` | 3 | 동기화 재생, 속도 변경, 프레임 번호 진행 확인 |
| `multiview-spectrogram.spec.ts` | 5 | 스펙트로그램 생성, 클릭 seek, 플레이헤드 위치 |
| `multiview-frame-navigation.spec.ts` | 4 | 프레임 탐색, 키프레임 점프, 시작/끝 프레임 |
| `multiview-view-switching.spec.ts` | 3 | 뷰 전환 시 canvas 상태, draw 모드 유지, zoom 리셋 |
| `multiview-zoom-pan.spec.ts` | 3 | 스크롤 줌, 팬 드래그, 더블클릭 리셋 |
| `multiview-object-selection.spec.ts` | 2 | shape 클릭 활성화, 사이드바 동기화 |
| `multiview-resize-layout.spec.ts` | 2 | 그리드 레이아웃 반응성, 사이드바 토글 |
| `multiview-regression.spec.ts` | 7 | canvas busy, 삭제 후 잔존, 뷰 전환 좌표, draw 중단 등 |
| `multiview-refresh-alignment.spec.ts` | 2 | 새로고침 후 bbox 중심 drift ≤ 2px |
| `multiview-canvas-only.spec.ts` | 3 | DOM에 `<video>` 요소 없음 확인, canvas background 존재 확인 |

### 기존 기능 유지 (Feature Parity)

모든 기존 Multiview 기능이 Canvas-Only에서도 동일하게 동작:

- 1-10개 뷰 동기화 재생 및 프레임 정확 seek
- Draw 모드 진입 시 자동 일시정지
- 뷰별 어노테이션 필터링 (viewId 시스템)
- 스펙트로그램 생성 및 클릭 네비게이션
- 줌/팬 (1x-5x, 우클릭/중클릭/Alt+좌클릭 팬)
- 재생 속도 조절 (0.25x-2x)
- Shape 드래그/리사이즈 후 좌표 저장

---

## 2026-02-13: Migration Script — 좌표 변환 도구

Master → Refactor 전환 시 기존 annotation 좌표를 변환하는 도구.

### 왜 필요했나

Master 브랜치의 Docker 이미지에 **ffprobe가 설치되어 있지 않았다.**
비디오 업로드 시 `_extract_video_metadata()` 함수가 ffprobe를 호출하지만 실패하면서,
실제 해상도와 무관하게 **1920x1080으로 fallback 저장**되었다.

```python
# cvat/apps/engine/views.py (Master)
def _extract_video_metadata(video_path):
    try:
        result = subprocess.run(['ffprobe', ...])  # ffprobe NOT installed → 실패
        ...
    except Exception:
        return {
            'width': 1920, 'height': 1080,    # ← 항상 여기로 빠짐
            'fps': 30.0, 'frame_count': 3000, 'duration': 100.0
        }
```

실제 비디오는 320x240(4:3)인데 DB에는 1920x1080(16:9)으로 저장.
Master에서 어노테이터가 그린 bbox 좌표도 이 가짜 1920x1080 좌표 공간에 기록되었다.
Refactor에서는 PyAV로 정확한 해상도를 읽어서 320x240으로 저장하므로,
기존 annotation을 그대로 가져오면 bbox가 캔버스 밖에 위치하게 된다.

| | 실제 비디오 | Master DB | Refactor DB |
|---|---|---|---|
| 해상도 | 320x240 (4:3) | 1920x1080 (16:9) | 320x240 (4:3) |
| Annotation 좌표 공간 | - | 1920x1080 | 320x240 |

### Hybrid Scaling — 왜 단순 스케일링이 안 되나

16:9 → 4:3로 변환할 때 X와 Y의 스케일이 다르다:
- X 스케일: 320 / 1920 = **0.1667** (÷6)
- Y 스케일: 240 / 1080 = **0.2222** (÷4.5)

단순히 X, Y를 각각 다른 비율로 줄이면(비균등 스케일링) bbox의 **위치는 정확하지만 형태가 변한다.**
정사각형으로 그린 bbox가 세로로 긴 직사각형이 되는 식이다 (0.99:1 → 0.75:1).
어노테이터가 stretched된 16:9 화면에서 의도적으로 그 비율로 그렸으므로 이를 깨뜨리면 안 된다.

그래서 **Hybrid Scaling**을 사용한다:
- **중심점 위치**: 비균등 스케일링 (X, Y 독립) — 비디오 좌표에 정확히 매핑
- **Bbox 크기**: 균등 스케일링 (기하평균 `√(0.1667 × 0.2222) = 0.1925`) — bbox 비율 보존

```
uniform_scale = √(scale_x × scale_y) = √(0.1667 × 0.2222) = 0.1925

변환 과정 (각 bbox):
  1. center = ((xtl+xbr)/2, (ytl+ybr)/2)
  2. center_new = (center_x × scale_x, center_y × scale_y)   ← 위치: 비균등
  3. width_new  = width × uniform_scale                       ← 크기: 균등
  4. height_new = height × uniform_scale                      ← 크기: 균등
  5. corners = center_new ± size_new/2                        ← 재구성
  6. clamp to [0, target_w] × [0, target_h]                   ← 경계 처리
```

**멱등성**: `<original_size>`가 아니라 **bbox 좌표 범위**로 변환 필요 여부를 판단한다.
좌표가 타겟 해상도를 초과하면 변환, 범위 내이면 이미 변환된 것으로 간주하고 skip.
따라서 같은 스크립트를 여러 번 돌려도 안전하다.

### 개발 과정 (7단계 진화)

1. **단순 비균등 스케일링** → bbox 비율 왜곡 발견 (0.99:1 → 0.75:1)
2. **API 자동화** — CVAT API 해상도 감지, 로그인 인증, 자동 업로드
3. **Hybrid Scaling + 병렬 처리** — `ThreadPoolExecutor`, Thread-local HTTP 세션
4. **2-Phase Architecture** — Phase 1: Segment repair (Django ORM), Phase 2: Export → Convert → Upload (HTTP)
5. **HTTP 409 처리** — Export Semaphore, RQ 큐 과부하 방지
6. **코드 리팩토링** — 924줄 → 657줄 (-29%)
7. **Direct DB 전환** — HTTP 파이프라인 전체 제거, Django ORM으로 `TrackedShape.points` 직접 UPDATE
   - 657줄 → 431줄 (-35%)
   - EC2 1140 jobs: HTTP 방식 수십 분 → Direct DB 수초

### 파일

- `scripts/migration/migrate_v1.py` — 핵심 로직 (batch + 단일 XML 모드)
- `scripts/migration/migrate_v1.sh` — Docker 컨테이너 실행 wrapper
- `scripts/migration/README.md` — 상세 문서 (알고리즘, 수학, 개발 과정, 사용법)

### 커밋

| 커밋 | 설명 |
|------|------|
| `19f1450` | 마이그레이션 스크립트 통합 |
| `0d4c3dc` | 병렬 batch + thread-safe 아키텍처 |
| `c008668` | 2-Phase 아키텍처 + sys.path 수정 |
| `3f0a14f` | HTTP 409 처리 + Export Semaphore |
| `ab8ef65` | 코드 리팩토링 924→657줄 (-29%) |
| `5eebb53` | Direct DB 전환 657→431줄 (-35%) |

---

## 2026-02-13: Active View 재생/탐색 성능 최적화

EC2 환경에서 Active 뷰(포커스된 뷰)만 재생 시 버벅거리는 문제 수정.

### 증상

- **재생 시**: Active 뷰만 영상이 멈추거나 버벅거림. 나머지 Preview 뷰는 정상 재생.
- **화살표 키 탐색 시**: Active 뷰만 bbox는 업데이트되는데 영상은 이전 프레임에 멈춰있음.
- **로컬에서는 정상**, EC2에서만 발생.
- **영상을 끝까지 한 번 재생하면** 해당 뷰의 버벅거림이 사라짐.

### 왜 이런 일이 생기나

Canvas-Only 리팩토링 이후 Active 뷰와 Preview 뷰의 프레임 로딩 방식이 다르다:

- **Active 뷰**: 매 프레임마다 `changeFrameAsync()` → 서버에서 chunk fetch → Broadway.js 디코딩 → Canvas에 그림
- **Preview 뷰**: HTML `<video>` 네이티브 재생 → 브라우저가 HTTP Range 요청으로 자동 버퍼링 + HW 가속

로컬에서는 서버가 localhost이므로 chunk fetch가 거의 즉시 완료된다.
EC2에서는 네트워크 지연이 있어서, 프레임마다 발생하는 서버 요청이 병목이 된다:

```
[프레임당 비용 — EC2 Active 뷰]

changeFrameAsync(frame N)
  ├── fetchAnnotations(N)        → 서버 왕복 50-200ms (annotation 조회)
  └── canvas.setup(frameData)
       └── frameData.data()      → 서버 왕복 100-500ms (chunk가 캐시에 없으면)
           └── Broadway.js 디코딩  → 10-50ms (CPU)

합계: 프레임당 최대 750ms → 10fps 재생에서 100ms 예산 초과
```

**"끝까지 재생하면 고쳐지는"** 이유:
chunk는 메모리 LRU 캐시에 저장된다. 한 번 재생하면서 모든 chunk를 fetch + 디코딩하면,
이후 요청은 전부 캐시 히트 → 서버 통신 없이 즉시 반환 → 부드러운 재생.
Preview 뷰는 처음부터 부드러운데, 브라우저의 `<video>`가 자체적으로 ahead-of-time 버퍼링을 하기 때문.

### 수정 내역

**1. 재생 중 fetchAnnotations skip** (`annotation-actions.ts`)

`changeFrameAsync()`는 매 프레임마다 서버에 annotation을 조회한다.
Multiview에서 재생 중에는 annotation이 변하지 않는다 (draw 모드 진입 시 자동 일시정지되므로).
재생 중에는 서버 조회를 건너뛰고 Redux에 이미 있는 annotation 상태를 재사용한다.
→ 프레임당 50-200ms 네트워크 왕복 제거.

**2. decodeForward 동적 업데이트** (`multiview-frames.ts`)

Broadway.js 디코더에는 두 가지 디코딩 모드가 있다:
- `decodeForward = true` (재생 모드): chunk 전체를 디코딩한 뒤에 resolve (순차 재생에 최적)
- `decodeForward = false` (탐색 모드): 요청한 프레임이 디코딩되는 즉시 resolve (seek에 최적)

기존에는 캐시가 처음 생성될 때의 `isPlaying` 값으로 고정되어 있었다.
재생 중에 캐시가 생성되면 `decodeForward = true`로 고정되고,
이후 일시정지해서 화살표 키로 탐색해도 여전히 전체 블록 디코딩을 기다림 → 느린 seek.
이제 매 요청마다 `isPlaying` 상태에 따라 동적으로 전환한다.

**3. Chunk 프리페치 강화** (`multiview-frames.ts`)

기존: 현재 chunk의 50% 지점에서 다음 chunk 1개만 미리 가져옴.
수정: 30% 지점부터 최대 2개 chunk를 미리 가져옴.
→ chunk 경계에서의 끊김 감소. EC2처럼 네트워크가 느린 환경에서 효과 큼.

### 커밋

| 커밋 | 설명 |
|------|------|
| `9323c4d` | active view 재생/탐색 성능 최적화 |

---

## 2026-02-13: Active View 오디오 재생 복원

Canvas-Only 리팩토링 이후 끊겼던 오디오 재생을 복원.

### 구현

- 숨겨진 `<video>` 요소로 active view의 오디오를 재생
- 뷰 전환 시 해당 뷰의 오디오로 자동 교체
- 3초 주기 드리프트 보정으로 영상-음성 싱크 유지

### 커밋

| 커밋 | 설명 |
|------|------|
| `2ad3845` | active view 오디오 재생 기능 추가 |

---

## 2026-02-13: 재생 성능 개선 (per-frame resolve, 뷰 전환 안정화)

### Per-frame chunk resolve (`361b157`)

재생 중 chunk 전체 디코드 완료를 기다리지 않고, 요청한 프레임이 디코드되는 즉시 resolve.
`decodeForward` 조건 제거, `resolved` 플래그로 중복 resolve 방지.
측정 결과: seek 레이턴시 avg 232ms (fetch 89ms + decode 143ms).

### 재생 중 뷰 전환 첫 프레임 수정 (`f1cfcd8`)

재생 중 뷰 전환 시 재생 루프가 100ms마다 새 프레임을 dispatch하여 각 `setup()`의 비동기
chunk fetch 결과가 imageID 불일치로 폐기되는 race condition 발생.
`viewTransitionRef` 게이트로 뷰 전환 시 800ms간 frame dispatch 차단.

### 뷰 전환 게이트 제거 (`d057832`)

800ms 게이트가 canvas freeze와 ~800ms sync desync를 유발. per-frame chunk resolve가
`setup()` race condition을 자연스럽게 해결하므로 게이트 제거.

### 커밋

| 커밋 | 설명 |
|------|------|
| `361b157` | per-frame chunk resolve로 디코딩 레이턴시 감소 |
| `f1cfcd8` | 재생 중 뷰 전환 시 첫 프레임 표시 문제 수정 |
| `d057832` | view transition gate 제거 (freeze/desync 유발) |

---

## 2026-02-14: Hybrid Rendering — `<video>` + Canvas 이중 렌더링

Active 뷰에 `<video>`와 Canvas를 동시에 렌더링하는 하이브리드 방식 도입.
재생 중에는 Canvas를 숨기고 네이티브 `<video>`로 렌더링 (HW 가속, Broadway.js freeze 제거).
정지 시 Canvas 오버레이를 표시하여 어노테이션 인터랙션.

### 주요 변경

- **`video-canvas.tsx`**: 항상 `MultiviewVideoPreview`를 렌더링 (뷰 전환 시 remount blink 방지). CSS로 Canvas 가시성 토글
- **`multiview-canvas-wrapper.tsx`**: 재생 중 `setup()` 스킵. `justPaused` 플래그로 play→pause 전환 시 강제 setup
- **`multiview-workspace.tsx`**: Draw 모드 auto-pause 강화 (모든 draw 시나리오에서 재생 차단)
- **`multiview-video-preview.tsx`**: `onError` 핸들러 (최대 3회 자동 재시도), `onCanPlay` 가드, `ended` 이벤트에서 near-end seek
- **Mac 지원**: `Backspace` (Mac ⌫) 키도 Delete로 인식

### Dead code 정리 (`ea8a944`)

- `multiview-canvas-preview.tsx` 삭제 (157줄, 미사용)
- 재생 루프의 `console.log`, 미사용 ref, dead `isPlaying` 파라미터 제거
- orphaned CSS 블록 제거 (`.annotation-canvas-preview`, `.zoom-indicator`)

### 커밋

| 커밋 | 설명 |
|------|------|
| `cfd02a2` | hybrid rendering — `<video>` during playback, Canvas when paused |
| `58446e3` | preview video error recovery (최대 3회 재시도) |
| `693290e` | Mac Delete key + video ended black screen 방지 |
| `ea8a944` | dead code 정리 (hybrid rendering migration) |

---

## 2026-02-15: 재생 Auto-stop, Frame Count 정확도, Warm Cache

### 재생 Auto-stop (`559f04a`)

Multiview rAF 루프에 auto-stop 로직 추가.
`targetFrame >= job.stopFrame`일 때 `switchPlay(false)` 디스패치 후 rAF 스케줄링 중단.
기존에는 `stopFrame` 도달 후에도 재생 상태가 유지되어 프레임 카운터가 비디오 끝 이후로 계속 올라갔음.

### Frame count 정확도 (`559f04a`)

`_extract_video_metadata()` 개선:
- **PyAV 경로**: `video_stream.frames` (정확한 값) 우선, 없으면 `round(duration * fps)` (int 절삭 → 반올림)
- **ffprobe 경로**: `nb_frames` 스트림 메타데이터 우선, 없으면 `round(duration * fps)`
- **Fallback**: `frame_count: 3000` → `0`으로 변경 + 호출부에서 `ValueError` raise (잘못된 task 생성 방지)

### FrameDecoder onDecodeAll race condition (`4230426`)

`requestDecodeBlock()`에서 같은 chunk가 재요청될 때 `onDecode`/`onReject`만 교체하고 `onDecodeAll`은
이전 호출자의 것이 남아있던 버그. Prefetch가 먼저 decode를 시작하면 `getMultiviewFrame`의 `resolveLoad()`가
영원히 호출되지 않아 `activeChunkRequest`가 hang → active view 영구 freeze.

수정:
- `requestedChunkToDecode`와 `chunkIsBeingDecoded` 양쪽에서 `onDecodeAll` 콜백을 compose
- `maybePrefetchChunks`에 `activeChunkRequest !== null` 가드 추가 (defense-in-depth)

### Warm cache API (`4230426`)

재생 중 현재 프레임의 chunk를 백그라운드에서 미리 디코딩하는 `warmCacheForFrame()` API 추가.
Broadway.js가 Web Worker에서 실행되므로 메인 스레드 차단 없이 디코딩.
사용자가 일시정지하면 이미 디코딩된 ImageBitmap이 캐시에 있어 즉시 Canvas 렌더링.

### --label-type 옵션 (`926a7f6`)

`insert_bbox_annotations.py`에 `--label-type` 인자 추가.
CVAT 사이드바에 표시할 드로잉 도구 제어:
- `rectangle` (기본): Rectangle 도구만
- `any`: 전체 도구 (Rectangle, Polygon, Polyline, Points, Ellipse, Cuboid, Mask, Skeleton)

### 커밋

| 커밋 | 설명 |
|------|------|
| `559f04a` | multiview auto-stop + frame_count 정확도 개선 |
| `4230426` | FrameDecoder onDecodeAll race fix + warm cache API |
| `926a7f6` | --label-type 옵션 (사이드바 도구 제어) |

---

## 2026-02-16 ~ 02-18: Export ValueError 수정, Spectrogram Duration, Auto-heal Annotation 정리

### Export `ValueError: Unknown internal frame id` 수정

EC2에서 download 시 `ValueError: Unknown internal frame id 2297` 에러 발생.

**근본 원인**:
- Master의 ffprobe fallback으로 `stop_frame=2999`(3000 프레임)이 DB에 저장됨
- 작업자가 실제 비디오 프레임 수(예: 2297) 이후의 프레임에 annotation을 생성
- `fix_frame_count.sh` 또는 auto-heal로 `stop_frame`을 실제 값으로 수정
- 하지만 **초과 annotation이 DB에 남아있는 상태**에서 export 시도
- Export worker가 `_init_shapes_from_db()`에서 frame 필터 없이 모든 annotation 로드
- `abs_frame_id(frame)` 호출 시 `frame not in rel_range` → **ValueError**

**수정**: `fix_frame_count.sh`와 `views.py` auto-heal 양쪽에서 stop_frame 수정 전에
실제 프레임 수 초과 annotation(`TrackedShape`, `LabeledShape`)을 먼저 삭제하도록 변경.

### Spectrogram Duration Off-by-one 수정

스펙트로그램 타임라인 길이가 실제 영상보다 1프레임 분량 짧았음.

```diff
- const duration = job ? (job.stopFrame - job.startFrame) / fps : 0;
+ const duration = job ? (job.stopFrame - job.startFrame + 1) / fps : 0;
```

`stopFrame`이 inclusive 인덱스이므로 `+1`이 필요. playhead 위치, 클릭 seek, 시간 라벨에 영향.

### Auto-heal Export Worker 주의사항

Auto-heal은 multiview meta API endpoint(`views.py`)에서만 동작.
**Export worker는 meta endpoint를 거치지 않으므로**, 페이지 접속 없이 바로 export하면
auto-heal이 실행되지 않음. EC2에서는 `fix_frame_count.sh`를 먼저 실행하는 것을 권장.

### 변경 파일

| 파일 | 변경 |
|------|------|
| `spectrogram-panel.tsx` | duration `(stopFrame - startFrame)` → `(stopFrame - startFrame + 1)` |
| `views.py` | auto-heal에 annotation 삭제 로직 추가 (`TrackedShape`, `LabeledShape`) |
| `fix_frame_count.sh` | batch 스크립트에 annotation 삭제 로직 추가 |
| `scripts/migration/README.md` | annotation 정리 동작, export worker 주의사항 문서화 |
