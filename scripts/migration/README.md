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
| **Bbox 크기** | 균등 (기하평균 √(sx×sy)) | 어노테이터의 의도한 bbox 비율 보존 |

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

### 왜 동시에 완벽할 수 없는가

종횡비가 다른 두 프레임 사이에서는 **코너 위치 비율**과 **bbox 비율**을 동시에 보존할 수 없습니다:

- 4개 코너의 % 위치가 고정되면 → width/height가 결정됨 → bbox 비율이 자동 결정
- bbox 비율을 유지하면 → 코너 위치가 달라짐 (중심은 정확)

이 스크립트는 **bbox 비율 보존**을 우선합니다 (어노테이터의 의도 존중).

## 파일 구성

| 파일 | 설명 |
|------|------|
| `migrate_all.sh` | **EC2 실행용 Shell wrapper** — 스크립트 복사 + 실행 + 정리 자동화 |
| `migrate_all.py` | **일괄 마이그레이션** — 모든 job 자동 처리 |
| `convert_annotation_coords.py` | 단일 job 좌표 변환 Python 스크립트 (핵심 로직) |
| `convert_annotations.sh` | 단일 job Shell wrapper (기본 출력 경로 자동 생성) |
| `README.md` | 이 문서 |

## 사용법

### 권장: 전체 일괄 마이그레이션

모든 job의 annotation을 한 번에 변환합니다.
XML의 `<original_size>`가 실제 비디오 해상도와 다른 job만 자동 변환하고,
이미 일치하는 job은 스킵합니다.

```bash
# Dry-run (변환 대상 확인만, 업로드 안 함)
python scripts/migration/migrate_all.py \
    --user admin --password admin123 --dry-run

# 실제 마이그레이션 실행
python scripts/migration/migrate_all.py \
    --user admin --password admin123

# 특정 job만 마이그레이션
python scripts/migration/migrate_all.py \
    --user admin --password admin123 --job-ids 7,8,9
```

#### EC2에서 실행 (권장: Shell wrapper)

`migrate_all.sh`가 스크립트 복사 → 실행 → 정리를 자동으로 처리합니다.

```bash
# Dry-run (확인만)
bash scripts/migration/migrate_all.sh --user admin --password <비밀번호> --dry-run

# 실제 마이그레이션
bash scripts/migration/migrate_all.sh --user admin --password <비밀번호>

# 특정 job만
bash scripts/migration/migrate_all.sh --user admin --password <비밀번호> --job-ids 7,8,9
```

내부 동작:
1. `scripts/migration/` 폴더를 `cvat_server` 컨테이너로 복사
2. 컨테이너 안에서 `migrate_all.py` 실행 (`--server http://localhost:8080` 자동 설정)
3. 완료 후 복사한 파일 정리

#### EC2에서 수동 실행 (Shell wrapper 없이)

```bash
# 호스트에서 스크립트를 컨테이너로 복사 후 실행
docker cp scripts/migration cvat_server:/tmp/migration
docker exec cvat_server python \
    /tmp/migration/migrate_all.py \
    --user admin --password <비밀번호> \
    --server http://localhost:8080

# 정리
docker exec -u root cvat_server rm -rf /tmp/migration
```

> **참고**: 무조건 1920x1080에서 변환하는 것이 아닙니다.
> XML의 `<original_size>` 해상도와 CVAT API에서 감지한 실제 비디오 해상도가 다를 때만 변환합니다.
> 예: Master에서 생성된 task (1920x1080 → 320x240), 이미 올바른 해상도면 스킵.

### 단일 job 변환

```bash
python scripts/migration/convert_annotation_coords.py \
    input.xml output.xml \
    --job-id 7 --user admin --password admin123 --upload
```

이 한 줄로:
1. CVAT API에서 job의 실제 비디오 해상도 자동 감지
2. Hybrid Scaling으로 XML 좌표 변환
3. 기존 annotation 삭제 + 변환된 annotation 업로드

### Shell wrapper

```bash
bash scripts/migration/convert_annotations.sh \
    input.xml \
    --job-id 7 --user admin --password admin123 --upload
```

출력 파일을 지정하지 않으면 `input_converted.xml`로 자동 생성됩니다.

### 수동 해상도 지정

```bash
python scripts/migration/convert_annotation_coords.py \
    input.xml output.xml \
    --target-w 320 --target-h 240
```

### 옵션 목록

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `input` | 입력 annotation XML (CVAT 1.1 형식) | 필수 |
| `output` | 출력 annotation XML | 필수 |
| `--job-id ID` | CVAT job ID (해상도 자동 감지) | - |
| `--target-w W` | 대상 너비 | API 자동 감지 |
| `--target-h H` | 대상 높이 | API 자동 감지 |
| `--user` | CVAT 사용자명 | - |
| `--password` | CVAT 비밀번호 | - |
| `--server URL` | CVAT 서버 주소 | `http://localhost:8080` |
| `--cookies FILE` | cookies.txt 경로 | 자동 탐색 |
| `--upload` | 변환 후 자동 업로드 | false |

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

### 2026-02-12: v1 - 단순 좌표 변환

1. `convert_annotation_coords.py` 작성
   - 비균등 스케일링: X÷6, Y÷4.5 (각 축 독립)
   - `<original_size>`, `<multiview><views>`, 모든 `<box>` 좌표 변환
2. Job 7에 테스트: 92 tracks, 184 boxes 변환 완료
3. **문제 발견**: bbox 비율이 변함 (정사각형 → 세로로 긴 직사각형)
   - Master bbox 비율 0.99:1 → 변환 후 0.75:1
   - 어노테이터가 stretched 화면에서 그린 비율이 보존되지 않음

### 2026-02-12: v2 - API 자동화 추가

- CVAT API 자동 해상도 감지 (`--job-id`) 추가
- 로그인 인증 (`--user`, `--password`) 추가
- 자동 업로드 (`--upload`: DELETE + POST) 추가
- Shell wrapper 작성
- `scripts/migration/` 디렉토리로 이동
- 변환 로직은 v1과 동일 (비균등 스케일링)

### 2026-02-12: v3 - Hybrid Scaling (현재)

- **변환 알고리즘 변경**: 비균등 → Hybrid Scaling
  - 중심점: 비균등 스케일링 (위치 정확)
  - Bbox 크기: 균등 스케일링 (기하평균, 비율 보존)
- 어노테이터의 의도한 bbox 비율을 보존하는 것이 목적
- Job 8, 9에 적용 완료:
  - Job 8 (`multisensor_home2_09-247-Part1`): 27 tracks, 54 boxes
  - Job 9 (`multisensor_home1_05-129-Part2`): 92 tracks, 184 boxes
