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
| Draw 중 Play하면 의도치 않은 Shape 생성 | Draw 모드 **진입** 시 자동 일시정지 (`prevActiveControlRef`로 전이 감지) | `multiview-workspace.tsx` |
| 좌표 불일치 | `fitCanvas()`에 `setupCalled` 플래그 가드 추가 | `canvasModel.ts` |
| Export 포맷 "No data" | multiview dimension에서 2D 포맷 허용 | `export-dataset-modal.tsx` |
| Export TypeError (overlap=None) | `overlap = overlap or 0` | `annotation.py` |
| Export에 view_id 누락 | DB 쿼리에 `view_id` 필드 추가 | `task.py` |
| Export 키프레임만 출력 | `keyframe` 필터링 추가 | `cvat.py` |
| view_id KeyError | `.get()` 사용 | `serializers.py` |
| 마우스 휠로 Canvas zoom | wheel 이벤트 capture + `preventDefault()` | `multiview-canvas-wrapper.tsx` |
| 좌클릭으로 Canvas pan | mousedown capture 단계에서 배경 좌클릭 시 `stopPropagation()` | `multiview-canvas-wrapper.tsx` |
| Rectangle 드래그 후 위치 안 저장 | `canvas.editdone` → `canvas.edited` 이벤트명 + Redux에서 원본 ObjectState 찾기 | `multiview-canvas-wrapper.tsx` |
| Shape 이동/크기 변경 후 새 Shape 그리면 원래대로 복구됨 | `onCanvasEditDone`에서 Redux 원본 ObjectState를 clientID로 찾아 업데이트 (shallow copy는 `save()` 메서드 없음) | `multiview-canvas-wrapper.tsx` |
| Shape 클릭해도 선택 안됨 (resize handles 안 나타남) | `onCanvasShapeClicked`에서 `activateObject` dispatch + `useEffect`로 `canvasInstance.activate()` 호출 | `multiview-canvas-wrapper.tsx` |
| 동영상 재생 시 프레임 떨림 (29→30→29 oscillation) | `top-bar.tsx`에서 Multiview workspace 예외 처리 + `playingRef` 동기 상태 + throttling | `multiview-workspace.tsx`, `top-bar.tsx` |
| 슬라이더 이동 후 재생 시 첫 프레임으로 점프 | 위와 동일 (경쟁하는 프레임 소스 제거) | `top-bar.tsx` |

---

## Commit History (요약)

| Commit | 내용 |
|--------|------|
| `307ffbe` | 초기 Multiview workspace 구현 (5개 뷰, 스펙트로그램) |
| `092a2d4` | 사전 계산 스펙트로그램 (FFT) |
| `f18ccdd` | 동기화 재생 및 스펙트로그램 클릭 네비게이션 |
| `6b4a70c` | Canvas is busy 에러 수정, MultiviewCanvasWrapper 추가 |
| `a914463` | viewId 필드 도입 (description 대체) |
| `10b32aa` | Canvas/Shape 클래스 viewId 지원 |
| `7a8013f` | 어노테이션 생성 에러 수정 (attribute id, release 순서 등) |
| `a61fa36` | 삭제 시 캔버스 업데이트 수정 |
| `1910279` | 오디오 재생 수정 (Web Audio API 하이재킹 제거) |
| `62b26b4` | 재생 중 스펙트로그램 시크 지원 |
| `0fe6bf0` | view_id 직렬화 호환성 |
| `ec4bb6c` | 캔버스 클릭 선택 지원 |
| `accce20` | viewId 필터링 수정 |
| `9043a72` | Draw 모드 완료 후 CURSOR 리셋 |
| `3f05db1` | Delete 키 어노테이션 삭제 |
| `ed72498` | 미사용 Multiview Properties 패널 제거 |
| `d63ea6c` | 리팩토링: 유틸리티 추출, Context API, 타입 정의 |
| `4bec801` | Play/Pause 후 Draw 모드 수정, 좌표 불일치 수정 |
| `a6942eb` | Draw 시 하얀색 오버레이 수정 |
| `0e25d4d` | 좌표 불일치 예방 가드, Export 원본 파일명 fallback |

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

### Export → Import 사이클

CVAT for video 1.1로 Export → CVAT 1.1로 Import: 정상 작동 확인 (트랙, 라벨, 좌표, view_id 유지)

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

### GitHub Actions CI/CD

`.github/workflows/docker-publish.yml`:
- **트리거**: `master` 브랜치 push (소스 코드 변경 시에만)
- **조건**: `kuielab/cvat-multiview` 저장소에서만 실행 (fork는 스킵)
- **빌드 대상**: `Dockerfile` (server), `Dockerfile.ui` (UI)
- **캐시**: GitHub Actions 캐시 사용 (`type=gha`)

**빌드 트리거 파일** (이 파일들이 변경될 때만 빌드):
```yaml
paths:
  # Server
  - 'Dockerfile'
  - 'cvat/**'
  - 'supervisord/**'
  - 'utils/**'
  - 'backend_entrypoint.sh'
  - 'manage.py'
  # UI
  - 'Dockerfile.ui'
  - 'cvat-ui/**'
  - 'cvat-core/**'
  - 'cvat-canvas/**'
  - 'cvat-canvas3d/**'
  - 'cvat-data/**'
  - 'package.json'
  - 'yarn.lock'
  - '.yarnrc.yml'
  # Workflow
  - '.github/workflows/docker-publish.yml'
```

**빌드 스킵**: 위 paths에 포함되지 않은 파일들 (문서, 설정 등)은 자동으로 빌드를 트리거하지 않음

### 실행 환경별 설정

| 환경 | 명령어 | 설명 |
|------|--------|------|
| **로컬 개발** | `docker compose up -d --build` | override 적용, 소스 마운트, localhost만 허용 |
| **EC2/프로덕션** | `docker compose -f docker-compose.yml up -d` | override 미적용, ghcr.io 이미지 사용 |
| **EC2 (호스트 설정)** | `CVAT_HOST=<ip> docker compose up -d` | 외부 IP/도메인으로 접근 허용 |

### docker-compose.override.yml (로컬 전용, gitignore됨)

```yaml
services:
  cvat_db:
    ports:
      - '127.0.0.1:5433:5432'  # 로컬 PostgreSQL 충돌 방지

  cvat_server:
    labels:
      traefik.http.routers.cvat.rule: (Host(`localhost`) || Host(`127.0.0.1`)) && ...
    volumes:
      - ./cvat:/home/django/cvat  # 소스 코드 실시간 반영

  cvat_ui:
    build:
      context: .
      dockerfile: Dockerfile.ui
    pull_policy: build
    labels:
      traefik.http.routers.cvat-ui.rule: Host(`localhost`) || Host(`127.0.0.1`)
```

**주의**: override 파일은 `.gitignore`에 포함되어 git에 올라가지 않음

---

## 배포 관련 이슈 & 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| EC2에서 404 오류 | override의 Traefik Host 규칙이 localhost 하드코딩 | override 제거 또는 CVAT_HOST 환경변수 사용 |
| datumaro 빌드 실패 (edition2024) | Ubuntu apt의 Cargo 1.75.0이 오래됨 | Dockerfile에서 rustup으로 최신 Rust 설치 |
| ghcr.io 이미지 pull 실패 (denied) | 이미지가 private 또는 미존재 | kuielab 저장소에서 Actions 실행 후 패키지 공개 설정 |
| 불필요한 파일 변경 시 빌드 실행 | paths 필터 미설정 | workflow에 paths/paths-ignore 추가 |

### Rust 버전 수정 (Dockerfile)

```dockerfile
# 이전: apt cargo (1.75.0) - edition2024 미지원
RUN apt-get install ... cargo ...

# 수정: rustup으로 최신 Rust 설치
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
```

### kuielab 저장소 설정 체크리스트

1. **GitHub Actions 권한**: Settings → Actions → General → "Read and write permissions" ✅
2. **패키지 공개 설정** (첫 빌드 후): https://github.com/orgs/kuielab/packages → Package settings → Public
3. **Secrets**: 불필요 (GITHUB_TOKEN 자동 제공)

---

## Test URL

```
http://127.0.0.1:8080/tasks/{task_id}/jobs/{job_id}
```

### Playwright MCP 테스트

- 다운로드 경로: `.playwright-mcp/` 폴더
- 알림 방해 시: Close 버튼 먼저 클릭
- 페이지 변경 후: `browser_snapshot`으로 새 ref 확인

---

## 대화 기록 관리 규칙

> **중요**: 모든 중요한 대화 내용, 문제 해결 과정, 수정 사항은 반드시 이 CLAUDE.md 파일에 저장해야 합니다.
> 대화를 요약하거나 저장할 때 이 규칙 자체도 CLAUDE.md에 포함되어야 합니다.

---

## Last Updated

2026-01-30 (Docker 배포 구조 정리 - v8)

### 최근 변경 사항 (2026-01-30) - v8

**수정된 파일**: `Dockerfile`, `docker-compose.yml`, `.github/workflows/docker-publish.yml`, `.gitignore`

#### Docker 배포 구조 개선

1. **GitHub Actions CI/CD 구성**
   - kuielab/cvat-multiview 저장소에서만 빌드 실행
   - ghcr.io에 이미지 자동 push
   - paths 필터로 불필요한 빌드 방지 (문서, 설정 파일 변경 시 스킵)

2. **docker-compose.yml 수정**
   - 이미지 참조: `cvat/*` → `ghcr.io/kuielab/cvat-multiview-*`
   - build 설정 추가 (로컬 빌드 지원)
   - CVAT_HOST 환경변수로 호스트 설정

3. **Dockerfile Rust 버전 수정**
   - apt cargo (1.75.0) → rustup 최신 Rust
   - datumaro의 wit-bindgen 의존성 빌드 오류 해결

4. **docker-compose.override.yml**
   - 로컬 개발 전용으로 분리
   - .gitignore에 추가 (git에 올라가지 않음)
   - 소스 코드 볼륨 마운트, localhost 전용 Traefik 규칙

**실행 확인**:
- 로컬: `docker compose up -d --build` ✓
- 프로덕션: `docker compose -f docker-compose.yml up -d` ✓
- 모든 컨테이너 정상 실행, Multiview 기능 포함 확인 ✓

### 이전 변경 사항 (2026-01-30) - v7

**수정된 파일**: `multiview-workspace.tsx`, `top-bar.tsx`

#### 버그 수정: 동영상 재생 시 프레임 번호 떨림 (완전 해결)

**문제**: 동영상 재생 중 프레임 번호가 앞뒤로 왔다갔다함 (예: 29 → 30 → 29 → 30), 영상이 떨리는 듯한 느낌

**최종 원인**: 두 개의 독립적인 프레임 소스가 경쟁

1. **Multiview workspace**: `video.currentTime` 기반 rAF 루프로 프레임 계산
2. **Standard player (top-bar.tsx)**: `handlePlayIfNecessary()`가 자체적으로 프레임 업데이트

이 두 소스가 서로 다른 타이밍에 `changeFrameAsync()`를 호출하면서 oscillation 발생.

**해결책**:

1. **top-bar.tsx에서 Multiview workspace 예외 처리** (핵심 수정)
```typescript
private async handlePlayIfNecessary(): Promise<void> {
    const { workspace } = this.props;

    // Skip frame sync for Multiview workspace - it handles its own video-based sync
    if (workspace === Workspace.MULTIVIEW) {
        return;
    }
    // ... standard player frame sync logic
}
```

2. **playingRef로 동기적 상태 추적** (race condition 방지)
```typescript
const playingRef = useRef<boolean>(false);

// Play/pause effect에서 ref를 BEFORE state 변경 전에 업데이트
useEffect(() => {
    if (playing) {
        playingRef.current = true;  // Set BEFORE starting playback
        playAllVideosRef.current();
    } else {
        playingRef.current = false; // Set BEFORE pausing
        pauseAllVideosRef.current();
    }
}, [playing]);

// Seek effect에서 playingRef 사용 (Redux playing 대신)
useEffect(() => {
    if (playingRef.current) return;  // Synchronous check
    // ... seek logic
}, [frameNumber, job, fps]); // playing 제거
```

3. **Throttling + pendingDispatch 플래그** (비동기 완료 순서 보장)
```typescript
const THROTTLE_MS = 100;
let pendingDispatch = false;

const shouldDispatch = newFrame !== lastDispatchedFrame &&
                       (now - lastDispatchTime) >= THROTTLE_MS &&
                       !pendingDispatch;

if (shouldDispatch) {
    pendingDispatch = true;
    Promise.resolve(dispatch(changeFrameAsync(targetFrame))).finally(() => {
        pendingDispatch = false;
    });
}
```

4. **Math.floor → Math.round** (프레임 경계 oscillation 방지)

**검증 결과**:
- Frame 0 → 3 → 6 → 9 → ... → 454 순차 증가 (역행 없음) ✓
- 슬라이더로 프레임 100 이동 후 재생 → Frame 100부터 정상 재생 ✓
- 첫 프레임으로 점프하는 현상 해결 ✓

### 이전 변경 사항 (2026-01-30) - v6

**수정된 파일**: `multiview-workspace.tsx`

#### 버그 수정: 동영상 재생 시 프레임 번호 떨림 (부분 해결)

- `timeupdate` → `requestAnimationFrame` 교체
- `Math.floor` → `Math.round` 변경
- Tolerance 감소: 50ms → 0.5프레임 (fps 기반)

### 이전 변경 사항 (2026-01-29) - v5

**수정된 파일**: `spectrogram-panel.tsx`, `styles.scss`

#### 기능 개선: Spectrogram Playhead 부드러운 60fps 애니메이션

**문제**: 재생 중 playhead가 Redux frameNumber 업데이트에 의존하여 끊기는 듯한 움직임

**해결책**: Overlay Canvas + requestAnimationFrame 접근법

1. **Overlay Canvas 추가**
   - 기존 canvas 위에 투명 canvas 레이어 (`overlayCanvasRef`)
   - 스펙트로그램은 정적 canvas에, playhead만 overlay에 그림
   - 스펙트로그램 리렌더링 없이 playhead만 업데이트

2. **함수 분리**
   - `drawSpectrogram()`: 스펙트로그램 + 라벨만 (정적, 한 번만)
   - `drawPlayheadOnly(time)`: overlay canvas에 playhead만 그림
   - `drawPlayhead()`: paused 상태에서 frameNumber 기반 업데이트

3. **requestAnimationFrame 루프**
   - `playing` 상태일 때만 rAF 루프 활성화
   - 비디오 `currentTime` 직접 참조하여 60fps 부드러운 업데이트
   - paused 상태에서는 기존 frameNumber 기반 업데이트 유지

```typescript
// Smooth playhead animation using requestAnimationFrame during playback
useEffect(() => {
    if (!playing || !spectrogramData) return;

    let animationId: number;
    const primaryVideo = document.querySelector('.multiview-video') as HTMLVideoElement;

    const animate = (): void => {
        if (primaryVideo && !primaryVideo.paused) {
            drawPlayheadOnly(primaryVideo.currentTime);
        }
        animationId = requestAnimationFrame(animate);
    };

    animationId = requestAnimationFrame(animate);

    return () => {
        cancelAnimationFrame(animationId);
    };
}, [playing, spectrogramData, drawPlayheadOnly]);
```

4. **JSX 구조 변경**
```jsx
<div className='spectrogram-canvas-container'>
    <canvas ref={canvasRef} ... />          {/* 스펙트로그램 (정적) */}
    <canvas ref={overlayCanvasRef} ... />   {/* Playhead (동적) */}
</div>
```

**검증 방법**:
- 동영상 재생 → playhead가 떨림 없이 부드럽게 이동 ✓
- 일시정지 → 재생 전환 시 점프 없음 ✓
- 스펙트로그램 클릭 → 해당 시간으로 이동 정상 ✓
- 프레임 네비게이션 (화살표 키) → playhead 위치 정확 ✓

### 이전 변경 사항 (2026-01-29) - v4

**수정된 파일**: `multiview-canvas-wrapper.tsx`

#### 버그 수정: Shape 이동/크기 변경 후 새 Shape 그리면 원래대로 복구됨

**문제**: Rectangle을 선택해서 크기를 바꾸거나 위치를 이동시킨 다음 새로운 rectangle을 그리면, 변경사항이 취소되고 원래 상태로 돌아감

**원인 분석**:
1. 이벤트 리스너가 `canvas.editdone`으로 등록되어 있었으나, canvas는 `canvas.edited` 이벤트를 dispatch
2. `onCanvasEditDone`에서 `updateAnnotationsAsync([state])`를 호출하는데, `state.save()` 메서드가 없어서 `TypeError: e.save is not a function` 발생
3. canvas에 전달되는 annotations가 좌표 변환을 위해 shallow copy(`{ ...ann, points: transformedPoints }`)되면서 ObjectState의 `save()` 메서드가 사라짐

**해결책**:

1. 이벤트 리스너 이름 수정: `canvas.editdone` → `canvas.edited`
2. `onCanvasEditDone` 핸들러에서 Redux의 원본 ObjectState를 clientID로 찾아서 업데이트

```typescript
const onCanvasEditDone = useCallback((event: any): void => {
    const refs = stateRefs.current;
    const { state, points, rotation } = event.detail;

    // Find the original ObjectState from Redux annotations by clientID
    const originalState = refs.annotations.find(
        (ann: ObjectState) => ann.clientID === state.clientID,
    );

    if (!originalState) {
        console.error('[MultiviewCanvas] Could not find original state');
        return;
    }

    // Transform coordinates from canvas space back to task space if needed
    const transformParams = transformParamsRef.current;
    let updatedPoints = points;
    if (transformParams && points && Array.isArray(points)) {
        updatedPoints = transformPointsForStorage(points, ...);
    }

    // Update the original ObjectState (which has the save() method)
    if (originalState.rotation !== rotation) {
        originalState.rotation = rotation;
    } else {
        originalState.points = updatedPoints;
    }

    dispatch(updateAnnotationsAsync([originalState]));
}, [dispatch]);
```

**검증 완료**:
- Shape 이동 → 새 Shape 그리기 → 이동된 위치 유지 ✓
- Save 후 페이지 새로고침 → 위치 유지 ✓

### 이전 변경 사항 (2026-01-29) - v3

**수정된 파일**: `multiview-canvas-wrapper.tsx`

#### 버그 수정: Shape 클릭해도 선택 안됨 (resize handles 미표시)

**문제**: Multiview workspace에서 rectangle을 클릭해도 resize handles가 표시되지 않아 shape을 선택/편집할 수 없음

**원인 분석**:
1. `canvas.clicked` 이벤트는 정상 발생 (SVG.js가 click 이벤트 바인딩)
2. 그러나 `onCanvasShapeClicked` 핸들러가 sidebar 스크롤만 수행하고 `activateObject` dispatch 안 함
3. 또한 Redux의 `activatedStateID` 변경 시 `canvasInstance.activate()` 호출하는 로직이 없음
4. 표준 canvas-wrapper에는 `componentDidUpdate`와 `canvas.setup` 이벤트에서 이 로직이 있음

**해결책**:

1. `activatedAttributeID` selector 추가
2. `onCanvasShapeClicked`에서 `activateObject(clientID, null, null)` dispatch
3. `useEffect` 추가: `activatedStateID` 변경 시 `canvasInstance.activate()` 호출

```typescript
// 1. onCanvasShapeClicked에서 activateObject dispatch
const onCanvasShapeClicked = useCallback((e: any): void => {
    const { clientID, parentID } = e.detail.state;
    dispatch(activateObject(clientID, null, null)); // 추가
    // ... sidebar scroll
}, [dispatch]);

// 2. activatedStateID 변경 시 canvas.activate() 호출
useEffect(() => {
    if (!canvasInstance) return;
    const activatedState = annotations.find(
        (state: ObjectState) => state.clientID === activatedStateID,
    );
    if (activatedStateID === null || (activatedState && activatedState.objectType !== ObjectType.TAG)) {
        canvasInstance.activate(activatedStateID, activatedAttributeID);
    }
}, [canvasInstance, activatedStateID, activatedAttributeID, annotations]);
```

**이벤트 흐름 (수정 후)**:
1. 사용자가 shape 클릭
2. SVG.js click 이벤트 → `canvas.clicked` CustomEvent dispatch
3. `onCanvasShapeClicked` → `dispatch(activateObject(clientID, null, null))`
4. Redux state 업데이트: `activatedStateID = clientID`
5. `useEffect` 트리거 → `canvasInstance.activate(activatedStateID, ...)`
6. Canvas가 shape에 resize handles 표시

### 이전 변경 사항 (2026-01-29) - v2

**수정된 파일**: `multiview-canvas-wrapper.tsx`

#### 버그 수정: Shape 드래그 및 그리기 오류

이전 구현에서 캡처 단계의 `stopPropagation()` 호출이 **shape 요소의 이벤트까지 차단**하여 발생한 버그:
- Rectangle 여러 개 그리면 크기가 작아지거나 화면 모서리로 순간이동
- Rectangle 드래그 시 해당 view의 모든 rectangle이 동시에 이동

**해결책**: Shape 요소 감지 로직 추가

```typescript
// Shape 요소인지 확인 - 이벤트 전파 허용
const isShapeElement =
    // Shape containers
    target.closest('.cvat_canvas_shape') !== null ||
    target.closest('.cvat_canvas_shape_drawing') !== null ||
    // Resize/rotation handles (for activated shapes)
    target.closest('.svg_select_points') !== null ||
    target.closest('.svg_select_points_rot') !== null ||
    // Direct SVG shape elements (including skeleton edges)
    ['rect', 'polygon', 'polyline', 'ellipse', 'path', 'circle', 'line', 'g'].includes(
        target.tagName.toLowerCase(),
    );

if (isShapeElement) {
    return; // SVG.js가 shape 드래그를 처리하도록 허용
}
```

**이벤트 흐름 (수정 후)**:
- 배경 클릭: capture 단계에서 `stopPropagation()` → canvas drag 방지
- Shape 클릭: capture 단계에서 `return` (전파 허용) → SVG.js가 정상 처리

### 동작 변경 요약

| 액션 | 이전 (버그) | 수정 후 |
|------|-------------|---------|
| 빈 영역 좌클릭 드래그 | 아무 동작 없음 ✓ | 아무 동작 없음 ✓ |
| Rectangle 좌클릭 드래그 | 모든 rectangle 이동 ❌ | 해당 rectangle만 이동 ✓ |
| Rectangle 여러 개 그리기 | 크기/위치 오류 ❌ | 정상 크기/위치 ✓ |
| Alt + 좌클릭 드래그 | Canvas pan ✓ | Canvas pan ✓ |
| 마우스 휠 | 아무 동작 없음 ✓ | 아무 동작 없음 ✓ |

### 이전 변경 사항 (2026-01-29) - v1

1. **좌클릭 Canvas Drag (Pan) 비활성화** - FIXED ✓
   - `onCanvasMouseDown` 함수 수정
   - SVG 배경 클릭 시 `e.stopPropagation()` 호출
   - mousedown 이벤트 리스너를 `{ capture: true }` 옵션으로 등록

2. **마우스 휠 Zoom 비활성화** - FIXED ✓
   - `handleWheel` 함수 추가
   - `{ passive: false, capture: true }` 옵션으로 이벤트 리스너 등록

### 이전 변경 사항 (2026-01-28)

- Rectangle 드래그 이벤트: `canvas.editdone` 이벤트 리스너 유지 (부분 해결, 추가 조사 필요)
