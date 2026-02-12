#!/usr/bin/env python3
"""
migrate_v1: Master -> Refactor annotation coordinate converter.

Converts annotation coordinates from master's fake 1920x1080 task space
(caused by missing ffprobe) to actual video dimensions using Hybrid Scaling:
  - Center position: non-uniform scaling (X/Y scaled independently)
  - Bbox dimensions: uniform scaling (geometric mean of X/Y scales)
"""

import argparse
import glob
import json
import math
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import MozillaCookieJar

DEFAULT_WORKERS = 4
DEFAULT_EXPORT_CONCURRENCY = 4
POLL_TIMEOUT = 600
MIN_ANNOTATION_SIZE = 100
MAX_RETRIES = 3
DJANGO_ROOT = '/home/django'
EXPORT_CACHE_DIR = '/home/django/data/cache/export'
KNOWN_RESOLUTIONS = [
    (1920, 1080), (1280, 720), (640, 480), (3840, 2160), (2560, 1440),
]

_print_lock = threading.Lock()
_thread_local = threading.local()
_django_initialized = False
_django_init_lock = threading.Lock()


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs, flush=True)


def _get_thread_session(server_url, username, password):
    if not hasattr(_thread_local, 'opener'):
        _thread_local.opener, _thread_local.csrf = get_cvat_session(
            server_url, None, username, password)
    return _thread_local.opener, _thread_local.csrf


def _ensure_django():
    global _django_initialized
    if _django_initialized:
        return True
    with _django_init_lock:
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
            _safe_print('  [Django] ORM initialized successfully')
            return True
        except Exception as e:
            _safe_print(f'  [Django] FAILED: {e} (segment repair unavailable)')
            return False


def _api_call(opener, csrf, url, method='GET', data=None, content_type=None):
    """Authenticated CVAT API call. Returns parsed JSON (or None for DELETE)."""
    req = urllib.request.Request(url, method=method, data=data)
    if content_type:
        req.add_header('Content-Type', content_type)
    if csrf:
        req.add_header('X-CSRFToken', csrf)
    with opener.open(req) as resp:
        body = resp.read()
        return json.loads(body) if method != 'DELETE' else None


def _poll_rq(opener, csrf, server_url, rq_id, timeout=POLL_TIMEOUT):
    """Poll an RQ request until finished/failed or timeout."""
    encoded = urllib.parse.quote(rq_id, safe='')
    for _ in range(timeout):
        time.sleep(1)
        data = _api_call(opener, csrf, f'{server_url}/api/requests/{encoded}')
        state = data.get('status', '')
        if state == 'finished':
            return data
        if state == 'failed':
            raise RuntimeError(f'RQ request failed: {data}')
    raise RuntimeError(f'RQ timed out after {timeout}s (rq_id={rq_id})')


def _load_cookies_with_httponly(path):
    cookie_jar = MozillaCookieJar()
    with open(path, 'r') as f:
        lines = f.readlines()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
        for line in lines:
            tmp.write(line[len('#HttpOnly_'):] if line.startswith('#HttpOnly_') else line)
        tmp_path = tmp.name
    try:
        cookie_jar.load(tmp_path, ignore_discard=True, ignore_expires=True)
    finally:
        os.unlink(tmp_path)
    return cookie_jar


def get_cvat_session(server_url, cookies_file=None, username=None, password=None):
    cookie_jar = MozillaCookieJar()
    csrf = None

    if cookies_file and os.path.exists(cookies_file):
        cookie_jar = _load_cookies_with_httponly(cookies_file)
        for c in cookie_jar:
            if c.name == 'csrftoken':
                csrf = c.value

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    if username and password:
        login_data = json.dumps({'username': username, 'password': password}).encode()
        req = urllib.request.Request(
            f'{server_url}/api/auth/login', data=login_data, method='POST')
        req.add_header('Content-Type', 'application/json')
        with opener.open(req) as resp:
            resp.read()
        for c in cookie_jar:
            if c.name == 'csrftoken':
                csrf = c.value

    return opener, csrf


def list_all_jobs(server_url, opener, csrf):
    jobs, page = [], 1
    while True:
        data = _api_call(opener, csrf,
                         f'{server_url}/api/jobs?page={page}&page_size=100')
        results = data.get('results', [])
        if not results:
            break
        jobs.extend(results)
        if not data.get('next'):
            break
        page += 1
    return jobs


def fetch_job_dimensions(server_url, job_id, opener, csrf):
    job_data = _api_call(opener, csrf, f'{server_url}/api/jobs/{job_id}')
    meta = _api_call(opener, csrf,
                     f'{server_url}/api/tasks/{job_data["task_id"]}/data/meta')
    frames = meta.get('frames', [])
    if frames:
        return frames[0]['width'], frames[0]['height']
    raise RuntimeError(f'Could not determine dimensions for job {job_id}')


def export_job_annotations(server_url, job_id, output_path, opener, csrf,
                           export_sem=None, timeout=POLL_TIMEOUT):
    """Export annotations as CVAT 1.1 XML. Semaphore limits concurrent exports.
    Handles 409 (already queued) by polling existing request."""
    fmt = urllib.parse.quote('CVAT for video 1.1')
    url = f'{server_url}/api/jobs/{job_id}/dataset/export?save_images=False&format={fmt}'

    if export_sem:
        export_sem.acquire()
    try:
        try:
            body = _api_call(opener, csrf, url, method='POST',
                             data=b'', content_type='application/json')
        except urllib.error.HTTPError as e:
            if e.code == 409:
                body = json.loads(e.read())
                _safe_print(f'  [Job {job_id}] export already queued (409)')
            else:
                raise
        rq_id = body.get('rq_id')
        if not rq_id:
            raise RuntimeError(f'Export failed for job {job_id}: {body}')
    finally:
        if export_sem:
            export_sem.release()

    result = _poll_rq(opener, csrf, server_url, rq_id, timeout)
    result_url = result.get('result_url', '')
    if not result_url:
        raise RuntimeError(f'No result_url for job {job_id}')
    if not result_url.startswith('http'):
        result_url = f'{server_url}{result_url}'

    req = urllib.request.Request(result_url)
    if csrf:
        req.add_header('X-CSRFToken', csrf)
    with opener.open(req) as dl:
        with open(output_path, 'wb') as f:
            f.write(dl.read())


def upload_annotations(server_url, job_id, xml_path, opener, csrf):
    _safe_print(f'  [Job {job_id}] Deleting existing annotations...')
    _api_call(opener, csrf,
              f'{server_url}/api/jobs/{job_id}/annotations/', method='DELETE')

    _safe_print(f'  [Job {job_id}] Uploading annotations...')
    boundary = f'----FormBoundary{job_id}{int(time.time())}'
    with open(xml_path, 'rb') as f:
        file_data = f.read()

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="annotation_file"; '
        f'filename="{os.path.basename(xml_path)}"\r\n'
        f'Content-Type: text/xml\r\n\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

    url = (f'{server_url}/api/jobs/{job_id}/annotations/'
           f'?format={urllib.parse.quote("CVAT 1.1")}')
    result = _api_call(opener, csrf, url, method='POST', data=body,
                       content_type=f'multipart/form-data; boundary={boundary}')

    rq_id = result.get('rq_id')
    if not rq_id:
        raise RuntimeError(f'Upload failed: {result}')
    _poll_rq(opener, csrf, server_url, rq_id)


def _detect_source_dimensions(root, target_w, target_h):
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


def convert_annotations(input_path, output_path, target_w, target_h, job_id=None):
    """Convert annotation coordinates using Hybrid Scaling."""
    tag = f'[Job {job_id}] ' if job_id else ''
    tree = ET.parse(input_path)
    root = tree.getroot()

    src_w, src_h = _detect_source_dimensions(root, target_w, target_h)

    if src_w == target_w and src_h == target_h:
        _safe_print(f'  {tag}No conversion needed '
                    f'(coordinates within {target_w}x{target_h})')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return {'tracks': 0, 'boxes': 0,
                'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}'}

    sx, sy = target_w / src_w, target_h / src_h
    us = math.sqrt(sx * sy)  # uniform scale
    _safe_print(f'  {tag}{src_w}x{src_h} -> {target_w}x{target_h} '
                f'(sx={sx:.4f} sy={sy:.4f} uniform={us:.4f})')

    orig_size = root.find('.//original_size')
    if orig_size is not None:
        orig_size.find('width').text = str(target_w)
        orig_size.find('height').text = str(target_h)
    for v in root.findall('.//multiview/views/view'):
        w_el, h_el = v.find('width'), v.find('height')
        if w_el is not None: w_el.text = str(target_w)
        if h_el is not None: h_el.text = str(target_h)

    def convert_box(b):
        xtl, ytl = float(b.get('xtl')), float(b.get('ytl'))
        xbr, ybr = float(b.get('xbr')), float(b.get('ybr'))
        cx, cy = (xtl + xbr) / 2 * sx, (ytl + ybr) / 2 * sy
        w, h = (xbr - xtl) * us, (ybr - ytl) * us
        b.set('xtl', f'{max(0, cx - w/2):.2f}')
        b.set('ytl', f'{max(0, cy - h/2):.2f}')
        b.set('xbr', f'{min(target_w, cx + w/2):.2f}')
        b.set('ybr', f'{min(target_h, cy + h/2):.2f}')

    tracks = root.findall('.//track')
    track_boxes = [b for t in tracks for b in t.findall('box')]
    for b in track_boxes:
        convert_box(b)
    shape_boxes = root.findall('.//image/box')
    for b in shape_boxes:
        convert_box(b)

    tree.write(output_path, encoding='unicode', xml_declaration=True)

    total = len(track_boxes) + len(shape_boxes)
    _safe_print(f'  {tag}Converted {len(tracks)} tracks, {total} boxes')
    return {'tracks': len(tracks), 'boxes': total,
            'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}'}


def _repair_segment_if_needed(job_id):
    """Fix segment stop_frame if annotations reference frames beyond it."""
    if not _ensure_django():
        return None

    from django.db import transaction
    from cvat.apps.engine.models import Job, TrackedShape, LabeledShape

    try:
        db_job = (Job.objects.select_related('segment', 'segment__task__data')
                  .get(id=job_id))
    except Job.DoesNotExist:
        _safe_print(f'  [Job {job_id}] WARNING: not found in DB')
        return None

    segment = db_job.segment
    db_data = segment.task.data

    max_track = (TrackedShape.objects.filter(track__job=db_job)
                 .order_by('-frame').values_list('frame', flat=True).first())
    max_shape = (LabeledShape.objects.filter(job=db_job)
                 .order_by('-frame').values_list('frame', flat=True).first())

    max_anno = max(max_track or 0, max_shape or 0)
    if max_anno <= segment.stop_frame:
        return None

    # Get actual frame count from video (best-effort via PyAV)
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

    msg = f'stop_frame {old_stop} -> {new_stop} (max_anno={max_anno})'
    if removed:
        msg += f', cleared {removed} cache files'
    return msg


def _export_and_extract(server_url, job_id, opener, csrf, tmpdir, export_sem):
    """Export annotations ZIP and extract XML. Returns path or None if empty."""
    export_path = os.path.join(tmpdir, f'job_{job_id}_export.zip')
    export_job_annotations(server_url, job_id, export_path,
                           opener, csrf, export_sem)

    with open(export_path, 'rb') as f:
        is_zip = f.read(4) == b'PK\x03\x04'

    if is_zip:
        with zipfile.ZipFile(export_path, 'r') as zf:
            xml_files = [n for n in zf.namelist() if n.endswith('.xml')]
            if not xml_files:
                raise RuntimeError(f'No XML in ZIP: {export_path}')
            zf.extract(xml_files[0], tmpdir)
            xml_path = os.path.join(tmpdir, xml_files[0])
    else:
        xml_path = export_path

    return xml_path if os.path.getsize(xml_path) >= MIN_ANNOTATION_SIZE else None


def _process_single_job(server_url, username, password, job, dry_run,
                        export_sem=None):
    """Process one job: export -> convert -> upload (with retries)."""
    job_id = job['id']
    task_id = job.get('task_id', '?')
    opener, csrf = _get_thread_session(server_url, username, password)

    try:
        task_name = _api_call(opener, csrf,
                              f'{server_url}/api/tasks/{task_id}').get('name', '')
    except Exception:
        task_name = ''

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                msg = _repair_segment_if_needed(job_id)
                if msg:
                    _safe_print(f'  [Job {job_id}] (retry repair) {msg}')

            target_w, target_h = fetch_job_dimensions(
                server_url, job_id, opener, csrf)

            with tempfile.TemporaryDirectory() as tmpdir:
                xml_path = _export_and_extract(
                    server_url, job_id, opener, csrf, tmpdir, export_sem)

                if xml_path is None:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name, 'reason': 'empty annotations'}

                converted = os.path.join(tmpdir, f'job_{job_id}_converted.xml')
                stats = convert_annotations(
                    xml_path, converted, target_w, target_h, job_id=job_id)

                if stats['src'] == stats['dst']:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name, 'reason': f'already {stats["src"]}'}
                if stats['boxes'] == 0:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name, 'reason': 'no boxes'}
                if dry_run:
                    return {'type': 'converted', 'job_id': job_id,
                            'task': task_name, 'stats': stats, 'dry_run': True}

                upload_annotations(server_url, job_id, converted, opener, csrf)
                return {'type': 'converted', 'job_id': job_id,
                        'task': task_name, 'stats': stats}

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = attempt * 5
                hint = ' (will retry with repair)' if 'Unknown internal frame id' in str(e) else ''
                _safe_print(f'  [Job {job_id}] attempt {attempt}/{MAX_RETRIES} '
                            f'failed: {e} (retry in {wait}s){hint}')
                time.sleep(wait)

    return {'type': 'failed', 'job_id': job_id,
            'task': task_name, 'error': str(last_error)}


def _repair_all_segments(job_ids):
    print(f'\n--- Phase 1: Segment repair ({len(job_ids)} jobs) ---')
    if not _ensure_django():
        print('  WARNING: Django unavailable — segment repair skipped')
        return {}

    repaired, errors = {}, 0
    for i, jid in enumerate(job_ids, 1):
        try:
            msg = _repair_segment_if_needed(jid)
            if msg:
                _safe_print(f'  [{i}/{len(job_ids)}] Job {jid}: {msg}')
                repaired[jid] = msg
        except Exception as e:
            errors += 1
            _safe_print(f'  [{i}/{len(job_ids)}] Job {jid}: ERROR - {e}')

    ok = len(job_ids) - len(repaired) - errors
    print(f'  Repair complete: {len(repaired)} repaired, {ok} OK, {errors} errors')
    return repaired


def run_batch(server, user, password, job_ids=None,
              workers=DEFAULT_WORKERS,
              export_concurrency=DEFAULT_EXPORT_CONCURRENCY,
              dry_run=False, repair_only=False):
    opener, csrf = get_cvat_session(server, None, user, password)

    print('Fetching all jobs...')
    all_jobs = list_all_jobs(server, opener, csrf)
    print(f'Found {len(all_jobs)} jobs total')

    if job_ids:
        target = set(int(x.strip()) for x in job_ids.split(','))
        all_jobs = [j for j in all_jobs if j['id'] in target]
        print(f'Filtered to {len(all_jobs)} jobs: {sorted(target)}')

    if not all_jobs:
        print('No jobs to process.')
        return 0

    _repair_all_segments([j['id'] for j in all_jobs])

    if repair_only:
        print('\n--repair-only: stopping after segment repair')
        return 0

    export_sem = threading.Semaphore(export_concurrency)
    workers = min(workers, len(all_jobs))
    print(f'\n--- Phase 2: Export & convert ({len(all_jobs)} jobs, '
          f'{workers} workers, export concurrency={export_concurrency}) ---\n')

    results = {'converted': [], 'skipped': [], 'failed': []}
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_single_job, server, user, password,
                        job, dry_run, export_sem): job
            for job in all_jobs
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            r = future.result()
            jid, name = r['job_id'], r.get('task', '')
            prog = f'[{done}/{len(all_jobs)}]'

            if r['type'] == 'converted':
                dry = ' [DRY-RUN]' if r.get('dry_run') else ''
                _safe_print(f'{prog} Job {jid} ({name}): '
                            f'{r["stats"]["boxes"]} boxes '
                            f'{r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
            elif r['type'] == 'skipped':
                _safe_print(f'{prog} Job {jid} ({name}): skipped ({r["reason"]})')
            else:
                _safe_print(f'{prog} Job {jid} ({name}): ERROR - {r["error"]}')
            results[r['type']].append(r)

    elapsed = time.monotonic() - t0
    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
    print(f'Workers:   {workers} (export concurrency: {export_concurrency})')
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


def run_single(args):
    opener, csrf = None, None
    if args.job_id:
        opener, csrf = get_cvat_session(
            args.server, args.cookies, args.user, args.password)

    if args.target_w and args.target_h:
        target_w, target_h = args.target_w, args.target_h
    elif args.job_id and opener:
        print(f'Fetching dimensions from CVAT job {args.job_id}...')
        target_w, target_h = fetch_job_dimensions(
            args.server, args.job_id, opener, csrf)
        print(f'  Detected: {target_w}x{target_h}')
    else:
        print('ERROR: --target-w/--target-h or --job-id required', file=sys.stderr)
        return 1

    convert_annotations(args.input, args.output, target_w, target_h)

    if args.upload:
        if not args.job_id:
            print('ERROR: --upload requires --job-id', file=sys.stderr)
            return 1
        upload_annotations(args.server, args.job_id, args.output, opener, csrf)
        print(f'Annotations uploaded to job {args.job_id}')

    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Convert annotation coordinates from master to refactor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all-jobs --user admin --password admin123 --dry-run
  %(prog)s --all-jobs --user admin --password admin123
  %(prog)s --all-jobs --user admin --password admin123 --job-ids 7,8,9
  %(prog)s --all-jobs --user admin --password admin123 --workers 8 --export-concurrency 2
  %(prog)s input.xml output.xml --job-id 7 --user admin --password admin123 --upload
  %(prog)s input.xml output.xml --target-w 320 --target-h 240
        """,
    )
    parser.add_argument('input', nargs='?', help='Input XML (single-job mode)')
    parser.add_argument('output', nargs='?', help='Output XML (single-job mode)')
    parser.add_argument('--all-jobs', action='store_true', help='Batch mode')
    parser.add_argument('--job-ids', type=str, help='Comma-separated job IDs')
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS,
                        help=f'Parallel workers (default: {DEFAULT_WORKERS})')
    parser.add_argument('--export-concurrency', type=int,
                        default=DEFAULT_EXPORT_CONCURRENCY,
                        help=f'Max concurrent exports (default: {DEFAULT_EXPORT_CONCURRENCY})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be converted without uploading')
    parser.add_argument('--repair-only', action='store_true',
                        help='Only repair segments (Phase 1)')
    parser.add_argument('--target-w', type=int, help='Target width (single-job)')
    parser.add_argument('--target-h', type=int, help='Target height (single-job)')
    parser.add_argument('--job-id', type=int, help='Job ID for auto-detect')
    parser.add_argument('--server', default='http://localhost:8080')
    parser.add_argument('--cookies', help='Path to cookies.txt')
    parser.add_argument('--user', help='CVAT username')
    parser.add_argument('--password', help='CVAT password')
    parser.add_argument('--upload', action='store_true',
                        help='Upload after conversion (single-job)')
    args = parser.parse_args()

    if args.all_jobs:
        if not args.user or not args.password:
            parser.error('--all-jobs requires --user and --password')
        return run_batch(
            server=args.server, user=args.user, password=args.password,
            job_ids=args.job_ids, workers=args.workers,
            export_concurrency=args.export_concurrency,
            dry_run=args.dry_run, repair_only=args.repair_only)

    if not args.input or not args.output:
        parser.error('input and output required (or use --all-jobs)')

    return run_single(args)


if __name__ == '__main__':
    sys.exit(main())
