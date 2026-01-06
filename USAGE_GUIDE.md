# CVAT Multiview Labeling Tool - 사용 가이드

## 목차

1. [시작하기](#시작하기)
2. [Multiview 태스크 생성](#multiview-태스크-생성)
3. [Annotation 작업](#annotation-작업)
4. [저장 및 Export](#저장-및-export)
5. [명령어 정리](#명령어-정리)
6. [문제 해결](#문제-해결)

---

## 시작하기

### 요구사항

- **Docker Desktop** (Windows/Mac) 또는 **Docker Engine** (Linux)
- **RAM**: 8 GB 최소, 16 GB 권장
- **Disk**: 10 GB (Docker images) + 데이터셋 용량

### 1. Docker 설치

**Windows / Mac**:
[Docker Desktop](https://www.docker.com/products/docker-desktop/) 다운로드 및 설치

**Linux**:
```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl start docker
sudo usermod -aG docker $USER
# 로그아웃 후 다시 로그인
```

### 2. CVAT 시작

**Windows** (관리자 권한 PowerShell):
```powershell
cd C:\path\to\cvat
.\quickstart.bat
```

**Linux / Mac**:
```bash
cd /path/to/cvat
./quickstart.sh
```

**첫 실행**: 10-15분 소요 (Docker 이미지 다운로드)
**이후 실행**: 2-3분 소요

### 3. 로그인

- **URL**: http://localhost:8080
- **Username**: `admin`
- **Password**: `admin123`

---

## Multiview 태스크 생성

### 방법 1: Python 스크립트 (권장)

```bash
cd /path/to/cvat
python create_sample_task.py
```

- Session 01, Part 1의 5개 비디오로 태스크 자동 생성
- "Sound" label 자동 추가

### 방법 2: 웹 인터페이스

1. http://localhost:8080/tasks/create-multiview 접속
2. 폼 작성:
   - **Task Name**: 예) `Session-01-Part-1`
   - **Session ID**: 예) `01`
   - **Part Number**: 예) `1`
   - **Videos**: 5개 비디오 파일 업로드 (View1-5)
3. **Create Task** 클릭

### 방법 3: API

```bash
# API 토큰 확인
TOKEN=$(docker compose exec -T cvat_server python manage.py shell -c \
  "from django.contrib.auth.models import User; \
   from rest_framework.authtoken.models import Token; \
   u=User.objects.get(username='admin'); \
   t,_=Token.objects.get_or_create(user=u); \
   print(t.key)" | tail -1)

# 태스크 생성
curl -X POST http://localhost:8080/api/tasks/create_multiview \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "name=My-Multiview-Task" \
  -F "session_id=01" \
  -F "part_number=1" \
  -F "video_view1=@/path/to/00-View1-Part1.mp4" \
  -F "video_view2=@/path/to/00-View2-Part1.mp4" \
  -F "video_view3=@/path/to/00-View3-Part1.mp4" \
  -F "video_view4=@/path/to/00-View4-Part1.mp4" \
  -F "video_view5=@/path/to/00-View5-Part1.mp4"
```

---

## Annotation 작업

### Workspace 구성

```
┌─────────────────────────────────────────────────────────────┐
│  [Controls]  │                                   │ [Objects] │
│              │         5-Camera Grid             │  List     │
│   Sidebar    │  ┌─────┬─────┬─────┬─────┬─────┐ │           │
│              │  │View1│View2│View3│View4│View5│ │           │
│              │  └─────┴─────┴─────┴─────┴─────┘ │           │
│              │                                   │           │
│              │     Spectrogram (Audio Viz)       │           │
│              │  ═══════════════════════════════  │           │
│              │         ^- Current Time           │           │
└─────────────────────────────────────────────────────────────┘
```

### Annotation 생성

1. **왼쪽 Controls Sidebar**에서 **Rectangle 도구** 선택
2. 원하는 **카메라 뷰**에서 드래그하여 Bounding Box 그리기
3. **오른쪽 Objects List**에서 속성 설정:
   - **Description**: 특이사항 메모 (예: "2명이 동시에 말함")
   - **Needs Review**: 재검토 필요시 체크

### Keyboard Shortcuts

| 키 | 기능 |
|---|---|
| `Space` | 재생/일시정지 |
| `←` `→` | 이전/다음 프레임 |
| `N` | Rectangle 도구 선택 |
| `Esc` | 도구 선택 해제 |
| `Ctrl+S` | 저장 |

---

## 저장 및 Export

### 저장

- **자동 저장**: 변경사항 자동 저장
- **수동 저장**: `Ctrl + S`

### Export

1. 태스크 페이지 → **Actions** → **Export task dataset**
2. Format 선택: CVAT XML, COCO, YOLO 등
3. 다운로드

**Export 예시 (JSON)**:
```json
{
  "annotations": [
    {
      "label": "Sound",
      "frame": 10,
      "bbox": [100, 200, 200, 200],
      "view_id": 1,
      "description": "2명이 동시에 말함",
      "needs_review": true
    }
  ]
}
```

---

## 명령어 정리

```bash
# CVAT 시작
docker compose up -d

# CVAT 종료
docker compose down

# 로그 확인
docker compose logs -f cvat_server

# 재시작
docker compose restart

# 컨테이너 상태 확인
docker compose ps
```

---

## 문제 해결

### CVAT이 시작되지 않음

```bash
docker compose ps              # 상태 확인
docker compose logs cvat_server --tail=50  # 로그 확인
docker compose down && docker compose up -d  # 재시작
```

### Port 8080 already in use

```bash
# Windows
netstat -ano | findstr :8080

# Linux/Mac
lsof -ti:8080 | xargs kill

# 재시작
docker compose down && docker compose up -d
```

### Multiview workspace가 안 열림

태스크의 dimension이 `multiview`인지 확인:
```bash
docker compose exec -T cvat_server python manage.py shell -c \
  "from cvat.apps.engine.models import Task; \
   t=Task.objects.get(id=YOUR_TASK_ID); \
   print(f'Dimension: {t.dimension}')"
```

---

**버전**: 1.0
**최종 업데이트**: 2025-01-06
