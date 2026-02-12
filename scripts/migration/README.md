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

### 왜 동시에 완벽할 수 없는가

종횡비가 다른 두 프레임 사이에서는 **코너 위치 비율**과 **bbox 비율**을 동시에 보존할 수 없습니다:

- 4개 코너의 % 위치가 고정되면 → width/height가 결정됨 → bbox 비율이 자동 결정
- bbox 비율을 유지하면 → 코너 위치가 달라짐 (중심은 정확)

이 스크립트는 **bbox 비율 보존**을 우선합니다 (어노테이터의 의도 존중).

### 변환 필요 여부 판단

`<original_size>`가 아니라 **bbox 좌표 범위**로 판단합니다.
(EC2에서 가져온 annotation은 1920x1080 좌표인데 task DB는 이미 320x240일 수 있음)

- bbox 좌표가 target(320x240)을 초과하면 → 1920x1080 공간으로 감지 → 변환
- bbox 좌표가 target 범위 안이면 → 이미 변환됨 → skip (멱등)

### Segment 자동 수정

Master의 fallback `frame_count: 3000`이나 PyAV의 `int(duration*fps)` 반올림 오차로
annotation이 segment 범위 밖 프레임을 참조하면 export가 실패합니다
(`ValueError: Unknown internal frame id`).

스크립트는 Django ORM으로 annotation의 최대 frame 번호를 조회하고,
segment 범위를 초과하면 자동으로 `Segment.stop_frame`과 `Data.size`를 수정합니다.
PyAV로 실제 비디오 프레임 수도 확인하여 더 큰 값을 적용합니다.

## 파일 구성

| 파일 | 설명 |
|------|------|
| `migrate_v1.sh` | **Shell wrapper** — Docker 컨테이너 안에서 batch 실행 |
| `migrate_v1.py` | **핵심 로직** — batch(`--all-jobs`) + 단일 XML 모드 |
| `README.md` | 이 문서 |

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

---

## History

### 2026-02-12: 문제 발견 및 분석

**증상**: Master에서 export한 annotation을 Refactor task(job 7)에 import했으나,
bbox가 캔버스에 표시되지 않음.

**조사 과정**:
1. 브라우저에서 `http://localhost:8080/tasks/7/jobs/7` 확인
   - Redux에 annotation 데이터는 로드됨 (sidebar "Items: 1" 표시)
   - 하지만 캔버스에 bbox 안 보임
2. 원본 annotation 좌표 확인: `xtl=839.34, ytl=715.73` (1920x1080 공간)
   - 320x240 캔버스 밖에 위치 → 당연히 안 보임
3. Master/Refactor 양쪽에서 동일 증상 확인
   - Master: 71개 console error + bbox 안 보임
   - Refactor: 1개 console error + bbox 안 보임
4. DB 해상도 확인:
   - Task 1,2 (Master 생성): DB=1920x1080, 실제=320x240 → **불일치**
   - Task 5,6,7 (Refactor 생성): DB=320x240, 실제=320x240 → **일치**

**근본 원인**: Docker에 ffprobe 미설치 → `_extract_video_metadata()` fallback → 1920x1080 저장

**해결 선택지 분석**:
| 방안 | 장점 | 단점 |
|------|------|------|
| Master + ffprobe 설치 | 코드 변경 최소 | 기존 task 미해결, 71개 에러, 성능 문제 |
| **Refactor 유지 + 변환 스크립트** | 근본 해결, 성능/안정성 개선 | 기존 annotation 1회 변환 필요 |

→ **Refactor 유지** 결정

### 2026-02-12: migrate_v1 개발 과정

1. **단순 비균등 스케일링**
   - X÷6, Y÷4.5 (각 축 독립) 스케일링
   - `<original_size>`, `<multiview><views>`, 모든 `<box>` 좌표 변환
   - Job 7에 테스트: 92 tracks, 184 boxes 변환 완료
   - **문제 발견**: bbox 비율이 변함 (정사각형 → 세로로 긴 직사각형)
     - Master bbox 비율 0.99:1 → 변환 후 0.75:1
     - 어노테이터가 stretched 화면에서 그린 비율이 보존되지 않음

2. **API 자동화 추가**
   - CVAT API 자동 해상도 감지 (`--job-id`) 추가
   - 로그인 인증 (`--user`, `--password`) 추가
   - 자동 업로드 (`--upload`: DELETE + POST) 추가
   - Shell wrapper 작성

3. **Hybrid Scaling + batch 모드 + 병렬 처리**
   - **변환 알고리즘 변경**: 비균등 → Hybrid Scaling
     - 중심점: 비균등 스케일링 (위치 정확)
     - Bbox 크기: 균등 스케일링 (기하평균, 비율 보존)
   - `<original_size>` 비교 대신 **bbox 좌표 범위**로 변환 필요 여부 판단
   - batch 모드 (`--all-jobs`) 추가: 모든 job 자동 export → convert → upload
   - **Segment 자동 수정**: Django ORM으로 annotation max frame 조회 → segment 범위 확장
   - **병렬 처리**: `ThreadPoolExecutor` (기본 16 workers)
     - Thread-local HTTP 세션 (opener/cookie jar 독립)
     - Django ORM 1회 초기화 (double-checked locking)
   - 멱등성 보장: 이미 변환된 job은 자동 skip
   - Job 8, 9에 적용 완료:
     - Job 8 (`multisensor_home2_09-247-Part1`): 27 tracks, 54 boxes
     - Job 9 (`multisensor_home1_05-129-Part2`): 92 tracks, 184 boxes

4. **2-Phase Architecture + sys.path 수정**
   - `/home/django`가 Python path에 없어 Django ORM 초기화 실패
     - `sys.path.insert(0, '/home/django')` 추가로 해결
   - **2-Phase 아키텍처**로 변경:
     - Phase 1: 모든 segment를 순차적으로 수정 (Django ORM)
     - Phase 2: 병렬 export + convert + upload (HTTP API)
   - 재시도 시 segment repair 재실행
   - `--repair-only` 플래그 추가

5. **HTTP 409 처리 + Export Semaphore**
   - CVAT가 이미 queued/running인 export에 409 반환 → rq_id 추출 후 polling
   - `--export-concurrency` 플래그 추가 (기본 4): RQ 큐 과부하 방지
   - 기본 workers 16→4로 축소 (RQ worker 1-2개에 맞춤)

6. **코드 리팩토링 (924줄 → 657줄, -29%)**
   - `_api_get`/`_api_post`/`_api_delete` 3개 → `_api_call` 1개로 통합
   - 1회 호출 헬퍼 인라인화
   - 섹션 구분 주석, 과도한 docstring 제거

7. **Direct DB 전환 (657줄 → 431줄, -35%)**
   - HTTP export/import 파이프라인 전체 제거
   - `TrackedShape.points`, `LabeledShape.points`를 Django ORM으로 직접 UPDATE
   - PyAV로 실제 비디오 해상도 확인 (DB의 Video.width/height 대신)
   - RQ 큐 강제 비움 (`django_rq.get_queue('export').empty()`) 추가
   - 제거된 의존성: urllib, cookies, threading, semaphore, JSON, zipfile, tempfile
   - 제거된 옵션: `--user`, `--password`, `--server`, `--workers`, `--export-concurrency`, `--repair-only`, `--upload`, `--cookies`
   - EC2 1140 jobs: HTTP 방식 수십 분 → Direct DB 수초
