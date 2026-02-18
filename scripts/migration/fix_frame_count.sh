#!/bin/bash
#
# fix_frame_count: Update Data.size, Data.stop_frame, Segment.stop_frame
#                  to actual video frame count (via PyAV)
#
# Master branch had no ffprobe installed, so frame_count fell back to 3000.
# This script reads actual frame count from video files and updates the DB.
#
# Usage:
#   # Dry-run (show current vs actual, no changes):
#   bash scripts/migration/fix_frame_count.sh --dry-run
#
#   # Actual update (all multiview tasks):
#   bash scripts/migration/fix_frame_count.sh
#
#   # Specific task IDs only:
#   bash scripts/migration/fix_frame_count.sh --task-ids 1,2,3
#

set -euo pipefail

CONTAINER="cvat_server"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
TASK_IDS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)  DRY_RUN=true; shift ;;
        --task-ids) TASK_IDS="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: bash $0 [--dry-run] [--task-ids ID1,ID2,...]"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would change without updating DB"
            echo "  --task-ids IDs     Only process specific task IDs (comma-separated)"
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

echo -e "${GREEN}Reading frame counts from video files and DB...${NC}"
echo ""

MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" python -c "
import sys, os
sys.path.insert(0, '/home/django')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cvat.settings.production')

import django
django.setup()

import av
from cvat.apps.engine.models import Task, Data, Segment, Video

dry_run = '${DRY_RUN}' == 'true'
task_ids_str = '${TASK_IDS}'

tasks = Task.objects.filter(dimension='multiview')
if task_ids_str:
    ids = [int(x.strip()) for x in task_ids_str.split(',')]
    tasks = tasks.filter(id__in=ids)

if not tasks.exists():
    print('No multiview tasks found.')
    sys.exit(0)

updated = 0
skipped = 0
errors = 0

for task in tasks.order_by('id'):
    data = task.data
    db_size = data.size
    db_stop = data.stop_frame

    # Read actual frame count from first view's video
    videos = Video.objects.filter(data_id=task.data_id).order_by('id')
    if not videos.exists():
        print(f'Task {task.id}: {task.name} — no videos found')
        errors += 1
        continue

    first_video = videos.first()
    actual_fc = 0
    try:
        container = av.open(first_video.path)
        vs = container.streams.video[0]
        actual_fc = vs.frames
        if actual_fc <= 0:
            dur = float(vs.duration * vs.time_base) if vs.duration else 0
            avg_rate = float(vs.average_rate) if vs.average_rate else 0
            actual_fc = round(dur * avg_rate) if dur > 0 and avg_rate > 0 else 0
        container.close()
    except Exception as e:
        print(f'Task {task.id}: {task.name} — WARNING: Cannot read {first_video.path}: {e}')
        errors += 1
        continue

    if actual_fc <= 0:
        print(f'Task {task.id}: {task.name} — WARNING: Could not determine frame count')
        errors += 1
        continue

    # Check for annotations beyond actual frame count
    from cvat.apps.engine.models import Job as JobModel
    from cvat.apps.engine.models import TrackedShape, LabeledShape
    job_ids = JobModel.objects.filter(segment__task=task).values_list('id', flat=True)
    last_valid = actual_fc - 1

    excess_tracked = TrackedShape.objects.filter(
        track__job_id__in=job_ids, frame__gt=last_valid,
    ).count()
    excess_shapes = LabeledShape.objects.filter(
        job_id__in=job_ids, frame__gt=last_valid,
    ).count()

    segments = Segment.objects.filter(task=task)
    seg_stops = list(segments.values_list('stop_frame', flat=True))

    print(f'Task {task.id}: {task.name}')
    print(f'  DB: size={db_size}, stop_frame={db_stop}, segment_stops={seg_stops}')
    print(f'  Actual: frame_count={actual_fc}')
    if excess_tracked or excess_shapes:
        print(f'  WARNING: {excess_tracked} tracked shapes, {excess_shapes} shapes beyond frame {last_valid}')

    if db_size == actual_fc and db_stop == last_valid:
        all_seg_ok = all(s == last_valid for s in seg_stops)
        if all_seg_ok and not excess_tracked and not excess_shapes:
            print(f'  OK — already correct')
            skipped += 1
            continue

    tag = 'DRY-RUN' if dry_run else 'UPDATE'
    print(f'  [{tag}] size: {db_size} -> {actual_fc}, stop_frame: {db_stop} -> {last_valid}')

    if not dry_run:
        # Remove annotations beyond actual frame count
        if excess_tracked or excess_shapes:
            del_t = TrackedShape.objects.filter(
                track__job_id__in=job_ids, frame__gt=last_valid,
            ).delete()[0]
            del_s = LabeledShape.objects.filter(
                job_id__in=job_ids, frame__gt=last_valid,
            ).delete()[0]
            print(f'  [{tag}] Removed {del_t} tracked shapes, {del_s} shapes beyond frame {last_valid}')

        data.size = actual_fc
        data.stop_frame = last_valid
        data.save(update_fields=['size', 'stop_frame'])

        segments.update(stop_frame=last_valid)
        print(f'  [{tag}] Updated {segments.count()} segment(s)')

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
