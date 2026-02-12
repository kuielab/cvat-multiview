#!/usr/bin/env python3
"""
migrate_v1: Master -> Refactor annotation coordinate converter (direct DB).

Converts annotation coordinates from master's fake 1920x1080 task space
(caused by missing ffprobe) to actual video dimensions using Hybrid Scaling:
  - Center position: non-uniform scaling (X/Y scaled independently)
  - Bbox dimensions: uniform scaling (geometric mean of X/Y scales)

Operates directly on DB via Django ORM — no HTTP export/import, no RQ queues.
"""

import argparse
import glob
import math
import os
import sys
import time
import xml.etree.ElementTree as ET

DJANGO_ROOT = '/home/django'
EXPORT_CACHE_DIR = '/home/django/data/cache/export'
KNOWN_RESOLUTIONS = [
    (1920, 1080), (1280, 720), (640, 480), (3840, 2160), (2560, 1440),
]

_django_initialized = False


def _ensure_django():
    global _django_initialized
    if _django_initialized:
        return True
    try:
        if os.path.isdir(os.path.join(DJANGO_ROOT, 'cvat')):
            if DJANGO_ROOT not in sys.path:
                sys.path.insert(0, DJANGO_ROOT)
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cvat.settings.production')
        django.setup()
        _django_initialized = True
        print('  [Django] ORM initialized')
        return True
    except Exception as e:
        print(f'  [Django] FAILED: {e}', file=sys.stderr)
        return False


def _clear_rq_queues():
    """Clear pending export/import RQ jobs."""
    try:
        import django_rq
        total = 0
        for name in ('export', 'import'):
            try:
                q = django_rq.get_queue(name)
                n = len(q)
                if n > 0:
                    q.empty()
                    total += n
                    print(f'  Cleared {n} jobs from "{name}" queue')
            except Exception:
                pass
        if total == 0:
            print('  No pending RQ jobs')
    except ImportError:
        print('  django_rq not available, skipping')


def _get_video_dimensions(db_data):
    """Get actual video dimensions via PyAV (authoritative)."""
    try:
        import av
        mv = db_data.multiview_data
        video = mv and mv.video_view1
        if video and video.path:
            with av.open(video.path) as c:
                vs = c.streams.video[0]
                return vs.width, vs.height
    except Exception:
        pass
    # Fallback to Video model
    mv = getattr(db_data, 'multiview_data', None)
    if mv and mv.video_view1:
        return mv.video_view1.width, mv.video_view1.height
    video = db_data.videos.first()
    if video:
        return video.width, video.height
    return None


def _detect_source_from_shapes(shapes, target_w, target_h):
    """Detect source coordinate space from shape points."""
    max_x, max_y = 0.0, 0.0
    for s in shapes:
        if s.type == 'rectangle' and len(s.points) >= 4:
            if s.points[2] > max_x: max_x = s.points[2]
            if s.points[3] > max_y: max_y = s.points[3]

    if max_x <= target_w and max_y <= target_h:
        return target_w, target_h

    for cw, ch in KNOWN_RESOLUTIONS:
        if max_x <= cw and max_y <= ch:
            return cw, ch
    return int(math.ceil(max_x)), int(math.ceil(max_y))


def _hybrid_scale_points(pts, sx, sy, us, tw, th):
    """Hybrid scaling for rectangle [xtl, ytl, xbr, ybr]."""
    xtl, ytl, xbr, ybr = pts[0], pts[1], pts[2], pts[3]
    cx, cy = (xtl + xbr) / 2 * sx, (ytl + ybr) / 2 * sy
    w, h = (xbr - xtl) * us, (ybr - ytl) * us
    return [max(0.0, cx - w/2), max(0.0, cy - h/2),
            min(float(tw), cx + w/2), min(float(th), cy + h/2)]


def _repair_segment(job_id, db_job):
    """Fix segment stop_frame if annotations exceed it."""
    from django.db import transaction
    from cvat.apps.engine.models import TrackedShape, LabeledShape

    segment = db_job.segment
    db_data = segment.task.data

    max_track = (TrackedShape.objects.filter(track__job=db_job)
                 .order_by('-frame').values_list('frame', flat=True).first())
    max_shape = (LabeledShape.objects.filter(job=db_job)
                 .order_by('-frame').values_list('frame', flat=True).first())

    max_anno = max(max_track or 0, max_shape or 0)
    if max_anno <= segment.stop_frame:
        return None

    frame_count = max_anno + 1
    try:
        import av
        mv = db_data.multiview_data
        video = mv and mv.video_view1
        if video and video.path:
            with av.open(video.path) as c:
                vs = c.streams.video[0]
                frames = vs.frames
                if not frames:
                    dur = float(c.duration / av.time_base) if c.duration else 0
                    fps = float(vs.average_rate) if vs.average_rate else 30.0
                    frames = int(dur * fps) if dur > 0 else 0
                if frames > frame_count:
                    frame_count = frames
    except Exception:
        pass

    old_stop = segment.stop_frame
    new_stop = frame_count - 1

    with transaction.atomic():
        segment.stop_frame = new_stop
        segment.save(update_fields=['stop_frame'])
        db_data.size = frame_count
        db_data.stop_frame = new_stop
        db_data.save(update_fields=['size', 'stop_frame'])

    removed = 0
    for f in glob.glob(f'{EXPORT_CACHE_DIR}/job-{job_id}-*'):
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass

    msg = f'stop_frame {old_stop} -> {new_stop}'
    if removed:
        msg += f', cleared {removed} cache files'
    return msg


def _convert_job(job_id, db_job, dry_run=False):
    """Convert one job's annotation coordinates directly in DB."""
    from django.db import transaction
    from cvat.apps.engine.models import TrackedShape, LabeledShape

    task_name = db_job.segment.task.name
    db_data = db_job.segment.task.data

    dims = _get_video_dimensions(db_data)
    if not dims:
        return {'type': 'failed', 'job_id': job_id,
                'task': task_name, 'error': 'no video found'}
    tw, th = dims

    tracked = list(TrackedShape.objects.filter(
        track__job=db_job, type='rectangle'))
    labeled = list(LabeledShape.objects.filter(
        job=db_job, type='rectangle'))
    all_shapes = tracked + labeled

    if not all_shapes:
        return {'type': 'skipped', 'job_id': job_id,
                'task': task_name, 'reason': 'no rectangles'}

    sw, sh = _detect_source_from_shapes(all_shapes, tw, th)

    if sw == tw and sh == th:
        return {'type': 'skipped', 'job_id': job_id,
                'task': task_name, 'reason': f'already {sw}x{sh}'}

    sx, sy = tw / sw, th / sh
    us = math.sqrt(sx * sy)
    stats = {'boxes': len(all_shapes),
             'src': f'{sw}x{sh}', 'dst': f'{tw}x{th}'}

    if dry_run:
        return {'type': 'converted', 'job_id': job_id,
                'task': task_name, 'stats': stats, 'dry_run': True}

    with transaction.atomic():
        for shape in all_shapes:
            shape.points = _hybrid_scale_points(
                shape.points, sx, sy, us, tw, th)
            shape.save(update_fields=['points'])

    # Invalidate export cache
    for f in glob.glob(f'{EXPORT_CACHE_DIR}/job-{job_id}-*'):
        try:
            os.remove(f)
        except OSError:
            pass

    return {'type': 'converted', 'job_id': job_id,
            'task': task_name, 'stats': stats}


def run_batch(job_ids=None, dry_run=False):
    if not _ensure_django():
        return 1

    from cvat.apps.engine.models import Job

    print('\n--- Clearing RQ queues ---')
    _clear_rq_queues()

    all_jobs = list(
        Job.objects.select_related('segment', 'segment__task', 'segment__task__data')
        .order_by('id'))
    print(f'\nFound {len(all_jobs)} jobs total')

    if job_ids:
        target = set(int(x.strip()) for x in job_ids.split(','))
        all_jobs = [j for j in all_jobs if j.id in target]
        print(f'Filtered to {len(all_jobs)} jobs: {sorted(target)}')

    if not all_jobs:
        print('No jobs to process.')
        return 0

    # Phase 1: Segment repair
    print(f'\n--- Phase 1: Segment repair ({len(all_jobs)} jobs) ---')
    repaired, errors = 0, 0
    for i, db_job in enumerate(all_jobs, 1):
        try:
            msg = _repair_segment(db_job.id, db_job)
            if msg:
                print(f'  [{i}/{len(all_jobs)}] Job {db_job.id}: {msg}')
                repaired += 1
        except Exception as e:
            errors += 1
            print(f'  [{i}/{len(all_jobs)}] Job {db_job.id}: ERROR - {e}')
    ok = len(all_jobs) - repaired - errors
    print(f'  Repair: {repaired} repaired, {ok} OK, {errors} errors')

    # Phase 2: Convert coordinates
    print(f'\n--- Phase 2: Convert coordinates ({len(all_jobs)} jobs) ---')
    results = {'converted': [], 'skipped': [], 'failed': []}
    t0 = time.monotonic()

    for i, db_job in enumerate(all_jobs, 1):
        try:
            r = _convert_job(db_job.id, db_job, dry_run)
        except Exception as e:
            r = {'type': 'failed', 'job_id': db_job.id,
                 'task': db_job.segment.task.name, 'error': str(e)}

        jid, name = r['job_id'], r.get('task', '')

        if r['type'] == 'converted':
            dry = ' [DRY-RUN]' if r.get('dry_run') else ''
            print(f'  [{i}/{len(all_jobs)}] Job {jid} ({name}): '
                  f'{r["stats"]["boxes"]} boxes '
                  f'{r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
        elif r['type'] == 'skipped':
            print(f'  [{i}/{len(all_jobs)}] Job {jid} ({name}): '
                  f'skip ({r["reason"]})')
        else:
            print(f'  [{i}/{len(all_jobs)}] Job {jid} ({name}): '
                  f'ERROR - {r["error"]}')
        results[r['type']].append(r)

    elapsed = time.monotonic() - t0
    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
    print(f'Time:      {elapsed:.1f}s')
    for label in ('converted', 'skipped', 'failed'):
        items = results[label]
        if not items and label == 'failed':
            continue
        print(f'{label.title():10s} {len(items)} jobs')
        for r in items:
            if label == 'converted':
                dry = ' [DRY-RUN]' if r.get('dry_run') else ''
                print(f'  Job {r["job_id"]} ({r["task"]}): '
                      f'{r["stats"]["boxes"]} boxes '
                      f'{r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
            elif label == 'skipped':
                print(f'  Job {r["job_id"]} ({r["task"]}): {r["reason"]}')
            else:
                print(f'  Job {r["job_id"]} ({r["task"]}): {r["error"]}')

    return 1 if results['failed'] else 0


# ---------------------------------------------------------------------------
# Single-job XML mode (offline conversion, no DB required)
# ---------------------------------------------------------------------------

def _detect_source_dimensions_xml(root, target_w, target_h):
    orig_size = root.find('.//original_size')
    if orig_size is not None:
        xml_w = int(orig_size.find('width').text)
        xml_h = int(orig_size.find('height').text)
        if xml_w != target_w or xml_h != target_h:
            return xml_w, xml_h

    max_x = max((float(b.get('xbr', '0')) for b in root.iter('box')), default=0)
    max_y = max((float(b.get('ybr', '0')) for b in root.iter('box')), default=0)

    if max_x <= target_w and max_y <= target_h:
        return target_w, target_h

    for cw, ch in KNOWN_RESOLUTIONS:
        if max_x <= cw and max_y <= ch:
            return cw, ch
    return int(math.ceil(max_x)), int(math.ceil(max_y))


def convert_xml(input_path, output_path, target_w, target_h):
    """Convert annotation XML coordinates using Hybrid Scaling."""
    tree = ET.parse(input_path)
    root = tree.getroot()

    src_w, src_h = _detect_source_dimensions_xml(root, target_w, target_h)

    if src_w == target_w and src_h == target_h:
        print(f'  No conversion needed (coordinates within {target_w}x{target_h})')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return 0

    sx, sy = target_w / src_w, target_h / src_h
    us = math.sqrt(sx * sy)
    print(f'  {src_w}x{src_h} -> {target_w}x{target_h} '
          f'(sx={sx:.4f} sy={sy:.4f} uniform={us:.4f})')

    orig_size = root.find('.//original_size')
    if orig_size is not None:
        orig_size.find('width').text = str(target_w)
        orig_size.find('height').text = str(target_h)
    for v in root.findall('.//multiview/views/view'):
        w_el, h_el = v.find('width'), v.find('height')
        if w_el is not None: w_el.text = str(target_w)
        if h_el is not None: h_el.text = str(target_h)

    def scale_box(b):
        xtl, ytl = float(b.get('xtl')), float(b.get('ytl'))
        xbr, ybr = float(b.get('xbr')), float(b.get('ybr'))
        cx, cy = (xtl + xbr) / 2 * sx, (ytl + ybr) / 2 * sy
        w, h = (xbr - xtl) * us, (ybr - ytl) * us
        b.set('xtl', f'{max(0, cx - w/2):.2f}')
        b.set('ytl', f'{max(0, cy - h/2):.2f}')
        b.set('xbr', f'{min(target_w, cx + w/2):.2f}')
        b.set('ybr', f'{min(target_h, cy + h/2):.2f}')

    count = 0
    for b in root.iter('box'):
        scale_box(b)
        count += 1

    tree.write(output_path, encoding='unicode', xml_declaration=True)
    print(f'  Converted {count} boxes')
    return count


def main():
    parser = argparse.ArgumentParser(
        description='Convert annotation coordinates from master to refactor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch (direct DB, runs inside cvat_server container):
  %(prog)s --all-jobs --dry-run
  %(prog)s --all-jobs
  %(prog)s --all-jobs --job-ids 7,8,9

  # Single XML file (offline):
  %(prog)s input.xml output.xml --target-w 320 --target-h 240
        """,
    )
    parser.add_argument('input', nargs='?', help='Input XML (single-job mode)')
    parser.add_argument('output', nargs='?', help='Output XML (single-job mode)')
    parser.add_argument('--all-jobs', action='store_true',
                        help='Batch mode: direct DB conversion')
    parser.add_argument('--job-ids', type=str, help='Comma-separated job IDs')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be converted without modifying DB')
    parser.add_argument('--target-w', type=int, help='Target width (single-job)')
    parser.add_argument('--target-h', type=int, help='Target height (single-job)')
    args = parser.parse_args()

    if args.all_jobs:
        return run_batch(job_ids=args.job_ids, dry_run=args.dry_run)

    if not args.input or not args.output:
        parser.error('input and output required (or use --all-jobs)')
    if not args.target_w or not args.target_h:
        parser.error('--target-w and --target-h required for XML mode')

    convert_xml(args.input, args.output, args.target_w, args.target_h)
    return 0


if __name__ == '__main__':
    sys.exit(main())
