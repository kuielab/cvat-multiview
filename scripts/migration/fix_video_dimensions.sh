#!/bin/bash
#
# fix_video_dimensions: Update engine_video width/height to actual resolution
#
# After migrate_v1 converts annotation coordinates, the Video DB may still
# have stale 1920x1080 fallback values. This script reads actual dimensions
# from video files (via PyAV inside the container) and updates the DB.
#
# Usage:
#   # Dry-run (show current vs actual, no changes):
#   bash scripts/migration/fix_video_dimensions.sh --dry-run
#
#   # Actual update (all multiview tasks):
#   bash scripts/migration/fix_video_dimensions.sh
#
#   # Specific data_ids only:
#   bash scripts/migration/fix_video_dimensions.sh --data-ids 8,9
#

set -euo pipefail

CONTAINER="cvat_server"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
DATA_IDS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)  DRY_RUN=true; shift ;;
        --data-ids) DATA_IDS="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: bash $0 [--dry-run] [--data-ids ID1,ID2,...]"
            echo ""
            echo "Options:"
            echo "  --dry-run         Show what would change without updating DB"
            echo "  --data-ids IDs    Only process specific data IDs (comma-separated)"
            exit 0
            ;;
        *) echo -e "${RED}Unknown option: $1${NC}" >&2; exit 1 ;;
    esac
done

if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: docker not found${NC}" >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo -e "${RED}ERROR: ${CONTAINER} container is not running${NC}" >&2
    echo "Run 'docker compose up -d' first." >&2
    exit 1
fi

echo -e "${GREEN}Reading video dimensions from files and DB...${NC}"
echo ""

MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" python -c "
import sys, os
sys.path.insert(0, '/home/django')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cvat.settings.production')

import django
django.setup()

from cvat.apps.engine.models import Task, Video

dry_run = '${DRY_RUN}' == 'true'
data_ids_str = '${DATA_IDS}'

tasks = Task.objects.filter(dimension='multiview')
if data_ids_str:
    ids = [int(x.strip()) for x in data_ids_str.split(',')]
    tasks = tasks.filter(data_id__in=ids)

if not tasks.exists():
    print('No multiview tasks found.')
    sys.exit(0)

updated = 0
skipped = 0
errors = 0

for task in tasks.order_by('id'):
    videos = Video.objects.filter(data_id=task.data_id).order_by('id')
    print(f'Task {task.id}: {task.name} (data_id={task.data_id}, {videos.count()} videos)')

    for video in videos:
        db_w, db_h = video.width, video.height
        actual_w, actual_h = db_w, db_h

        try:
            import av
            container = av.open(video.path)
            stream = container.streams.video[0]
            actual_w, actual_h = stream.width, stream.height
            container.close()
        except Exception as e:
            print(f'  WARNING: Cannot read {video.path}: {e}')
            errors += 1
            continue

        if db_w == actual_w and db_h == actual_h:
            skipped += 1
            continue

        tag = 'DRY-RUN' if dry_run else 'UPDATE'
        print(f'  [{tag}] Video {video.id}: {db_w}x{db_h} -> {actual_w}x{actual_h}  ({os.path.basename(video.path)})')

        if not dry_run:
            video.width = actual_w
            video.height = actual_h
            video.save(update_fields=['width', 'height'])

        updated += 1

print()
print(f'Summary: {updated} updated, {skipped} already correct, {errors} errors')
if dry_run and updated > 0:
    print('(dry-run mode — no changes were made)')
"

STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo -e "${RED}Script failed (exit code $STATUS)${NC}" >&2
    exit $STATUS
fi

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Dry-run complete. Run without --dry-run to apply changes.${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}Clearing export cache and restarting worker...${NC}"
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -c "rm -rf /home/django/data/cache/export/*"
docker compose restart cvat_worker_export

echo -e "${GREEN}Done!${NC}"
