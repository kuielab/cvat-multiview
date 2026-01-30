# CVAT PostgreSQL Backup to Google Drive

EC2에서 실행 중인 CVAT PostgreSQL 데이터베이스를 자동으로 백업하고 Google Drive에 업로드하는 시스템입니다.

## 기능

- PostgreSQL hot backup (서비스 중단 없음)
- Google Drive 자동 업로드 (rclone 사용)
- 하루 2회 자동 백업 (KST 06:00, 18:00)
- 로컬 백업 7일 보관
- Google Drive 백업 30일 보관
- 실패 시 이메일 알림 (선택사항)
- 상세 로그 기록

## 파일 구조

```
scripts/backup/
├── backup_to_gdrive.sh   # 메인 백업 스크립트
├── setup_backup.sh       # 설정 및 cron 등록 스크립트
└── README.md             # 이 문서
```

## 빠른 시작

### 1. 설정 스크립트 실행

```bash
cd /path/to/cvat-multiview/scripts/backup
sudo ./setup_backup.sh
```

설정 스크립트가 다음을 수행합니다:
- rclone 설치
- Google Drive 연동 설정
- 필요한 디렉토리 생성
- cron job 등록
- 테스트 백업 실행 (선택)

### 2. Google Drive 인증

setup_backup.sh 실행 중 rclone 설정 단계에서:

1. `n` 입력하여 새 remote 생성
2. 이름: `gdrive`
3. Storage 타입: `drive` (Google Drive) 선택
4. client_id, client_secret: Enter (기본값 사용)
5. scope: `1` (Full access)
6. root_folder_id: Enter (기본값)
7. service_account_file: Enter
8. Advanced config: `n`
9. Auto config: `n` (headless 서버이므로)
10. 표시된 URL을 브라우저에서 열고 Google 계정 인증
11. 인증 코드를 터미널에 붙여넣기
12. Team drive: `n`
13. 확인: `y`
14. 종료: `q`

## 수동 설정

### rclone 설치

```bash
curl https://rclone.org/install.sh | sudo bash
```

### rclone Google Drive 설정

```bash
rclone config
```

### 테스트

```bash
# Google Drive 연결 테스트
rclone lsd gdrive:

# 수동 백업 실행
./backup_to_gdrive.sh

# 백업 파일 확인
rclone ls gdrive:cvat-backup/
```

### Cron 설정

```bash
crontab -e
```

다음 내용 추가:
```cron
# CVAT PostgreSQL Backup to Google Drive
# KST 06:00 (UTC 21:00)
0 21 * * * /path/to/scripts/backup/backup_to_gdrive.sh >> /var/log/cvat-backup/backup.log 2>&1
# KST 18:00 (UTC 09:00)
0 9 * * * /path/to/scripts/backup/backup_to_gdrive.sh >> /var/log/cvat-backup/backup.log 2>&1
```

## 설정 커스터마이징

`backup_to_gdrive.sh` 파일 상단의 Configuration 섹션을 수정합니다:

```bash
# Database settings
DB_CONTAINER="cvat_db"      # Docker 컨테이너 이름
DB_USER="root"              # PostgreSQL 사용자
DB_NAME="cvat"              # 데이터베이스 이름

# Retention settings (days)
LOCAL_RETENTION_DAYS=7      # 로컬 보관 기간
GDRIVE_RETENTION_DAYS=30    # Google Drive 보관 기간

# Email notification (선택사항)
ALERT_EMAIL=""              # 알림 받을 이메일 주소
```

## 이메일 알림 설정

1. mailutils 설치:
```bash
sudo apt-get install mailutils
```

2. backup_to_gdrive.sh에서 ALERT_EMAIL 설정:
```bash
ALERT_EMAIL="your-email@example.com"
```

> 참고: EC2에서 이메일 전송 시 Amazon SES 설정이 없으면 스팸 처리될 수 있습니다.
> 로그 파일 확인을 권장합니다.

## 백업 복원

### 1. 백업 파일 다운로드

```bash
# 최신 백업 확인
rclone ls gdrive:cvat-backup/

# 다운로드
rclone copy gdrive:cvat-backup/cvat_db_YYYYMMDD_HHMMSS.sql.gz /tmp/
```

### 2. 복원 실행

```bash
# 압축 해제 및 복원
gunzip -c /tmp/cvat_db_YYYYMMDD_HHMMSS.sql.gz | docker exec -i cvat_db psql -U root cvat
```

> 주의: 복원은 기존 데이터를 덮어씁니다. 필요시 먼저 백업하세요.

## 로그 확인

```bash
# 실시간 로그 확인
tail -f /var/log/cvat-backup/backup.log

# 최근 로그 확인
tail -50 /var/log/cvat-backup/backup.log

# 에러만 확인
grep ERROR /var/log/cvat-backup/backup.log
```

## 트러블슈팅

### rclone 인증 만료

Google Drive OAuth 토큰이 만료된 경우:
```bash
rclone config reconnect gdrive:
```

### Docker 컨테이너를 찾을 수 없음

컨테이너 이름 확인:
```bash
docker ps --format '{{.Names}}' | grep -i cvat
```

backup_to_gdrive.sh의 DB_CONTAINER 값 수정 필요할 수 있음.

### 디스크 공간 부족

로컬 백업 보관 기간 단축:
```bash
# backup_to_gdrive.sh에서
LOCAL_RETENTION_DAYS=3
```

수동 정리:
```bash
rm -f /tmp/cvat-backup/cvat_db_*.sql.gz
```

### 권한 오류

```bash
# 스크립트 실행 권한
chmod +x backup_to_gdrive.sh setup_backup.sh

# 로그 디렉토리 권한
sudo chmod 755 /var/log/cvat-backup

# rclone 설정 파일 권한
chmod 600 ~/.config/rclone/rclone.conf
```

## 백업 데이터 범위

| 항목 | 포함 여부 | 설명 |
|------|----------|------|
| PostgreSQL (cvat_db) | O | Task, Job, Annotation 메타데이터 |
| cvat_data 볼륨 | X | 용량이 크고 영상 원본은 별도 보관 |
| ClickHouse | X | 분석 데이터, 필수 아님 |

## 보안 고려사항

- rclone 설정 파일 접근 제한 (`chmod 600`)
- Google Drive 폴더 공유 설정 주의 (기본: 비공개)
- 백업 스크립트 실행 권한 관리
- EC2 보안 그룹에서 불필요한 아웃바운드 차단하지 않도록 주의

## 명령어 요약

```bash
# 수동 백업
./backup_to_gdrive.sh

# 로그 확인
tail -f /var/log/cvat-backup/backup.log

# Google Drive 백업 목록
rclone ls gdrive:cvat-backup/

# cron 편집
crontab -e

# cron 확인
crontab -l

# rclone 재설정
rclone config

# 연결 테스트
rclone lsd gdrive:
```
