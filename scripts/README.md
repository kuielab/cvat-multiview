# Scripts

## Directory Structure

```
scripts/
├── README.md
├── SHORTCUTS.md
├── init/                  # Pre-annotation 삽입 스크립트
├── test/                  # 테스트 Task 생성 및 검증 스크립트
├── backup/                # 백업 관련
└── migration/             # Master → Refactor 마이그레이션 도구
    ├── README.md          # 상세 문서
    ├── migrate_v1.sh      # Shell wrapper (Docker 컨테이너에서 batch 실행)
    └── migrate_v1.py      # 핵심 로직 (batch + 단일 job 모드)
```

---

## migration/

Master → Refactor 전환 시 annotation 좌표 변환 도구.

Master에서 ffprobe 미설치로 인해 1920x1080 fallback 저장된 좌표를
Refactor의 실제 비디오 해상도(예: 320x240)로 변환합니다.
Hybrid Scaling 방식으로 bbox 비율을 보존하면서 위치를 정확히 매핑합니다.

bbox 좌표 범위로 변환 필요 여부를 자동 판단하며, 멱등성을 보장합니다.

```bash
# 전체 일괄 마이그레이션 (권장):
bash scripts/migration/migrate_v1.sh --user admin --password admin123

# Dry-run (확인만):
bash scripts/migration/migrate_v1.sh --user admin --password admin123 --dry-run

# 특정 job만:
bash scripts/migration/migrate_v1.sh --user admin --password admin123 --job-ids 7,8,9
```

상세 문서: [`migration/README.md`](migration/README.md)

---

## init/

Pre-annotation bbox 삽입 스크립트. 상세 사용법은 [CLAUDE.md](../CLAUDE.md#init-scripts-pre-annotation) 참조.

```bash
python scripts/init/insert_bbox_annotations.py \
    --user admin --password admin123 \
    --data-dir /path/to/dataset \
    --datasets multisensor_home1
```

---

## test/

테스트 Task 생성 및 검증 스크립트.

```bash
python scripts/test/setup_test_task.py --user admin --password admin123
python scripts/test/test_preannotation_edit.py --user admin --password admin123
```
