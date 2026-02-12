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
    ├── README.md          # 상세 문서 + 히스토리
    ├── convert_annotations.sh         # Shell wrapper
    └── convert_annotation_coords.py   # 좌표 변환 Python 스크립트
```

---

## migration/

Master → Refactor 전환 시 annotation 좌표 변환 도구.

Master에서 ffprobe 미설치로 인해 1920x1080 fallback 저장된 좌표를
Refactor의 실제 비디오 해상도(예: 320x240)로 변환합니다.
Hybrid Scaling 방식으로 bbox 비율을 보존하면서 위치를 정확히 매핑합니다.

```bash
# 권장 사용법 (API 자동 감지 + 업로드):
python scripts/migration/convert_annotation_coords.py \
    input.xml output.xml \
    --job-id 7 --user admin --password admin123 --upload

# Shell wrapper:
bash scripts/migration/convert_annotations.sh \
    input.xml \
    --job-id 7 --user admin --password admin123 --upload
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
