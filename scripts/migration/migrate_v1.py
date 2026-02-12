#!/usr/bin/env python3
"""
migrate_v1: Master -> Refactor annotation coordinate converter.

Master stored video dimensions as 1920x1080 (ffprobe fallback) even though
actual videos are smaller (e.g. 320x240). This script converts annotation
coordinates from master's fake 1920x1080 task space to actual video dimensions.

Conversion strategy (Hybrid Scaling):
  - Center position: non-uniform scaling (X/Y scaled independently)
  - Bbox dimensions: uniform scaling (geometric mean of X/Y scales)

Usage:
    # Batch: convert ALL jobs (via shell wrapper):
    bash scripts/migration/migrate_v1.sh --user admin --password admin123

    # Batch: dry-run:
    bash scripts/migration/migrate_v1.sh --user admin --password admin123 --dry-run

    # Batch: specific jobs:
    bash scripts/migration/migrate_v1.sh --user admin --password admin123 --job-ids 7,8,9

    # Batch: 32 parallel workers:
    bash scripts/migration/migrate_v1.sh --user admin --password admin123 --workers 32

    # Single job (direct Python):
    python migrate_v1.py input.xml output.xml --job-id 7 --user admin --password admin123 --upload
"""

import argparse
import glob as _glob_mod
import json
import math
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import MozillaCookieJar


# ---------------------------------------------------------------------------
# Thread-safe infrastructure
# ---------------------------------------------------------------------------

_print_lock = threading.Lock()
_thread_local = threading.local()
_django_initialized = False
_django_init_lock = threading.Lock()


def _safe_print(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs, flush=True)


def _get_thread_session(server_url: str, username: str, password: str):
    """Get or create a per-thread authenticated HTTP session.

    Each thread gets its own opener + cookie jar to avoid race conditions.
    Sessions are cached on thread-local storage so login happens once per thread.
    """
    if not hasattr(_thread_local, 'opener'):
        _thread_local.opener, _thread_local.csrf_token = get_cvat_session(
            server_url, None, username, password,
        )
    return _thread_local.opener, _thread_local.csrf_token


def _ensure_django() -> bool:
    """Initialize Django ORM exactly once (thread-safe)."""
    global _django_initialized
    if _django_initialized:
        return True
    with _django_init_lock:
        if _django_initialized:
            return True
        try:
            import django
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cvat.settings.production')
            django.setup()
            _django_initialized = True
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------

def _load_cookies_with_httponly(path: str) -> MozillaCookieJar:
    """Load cookies.txt handling #HttpOnly_ lines that Python ignores."""
    cookie_jar = MozillaCookieJar()

    with open(path, 'r') as f:
        lines = f.readlines()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
        for line in lines:
            if line.startswith('#HttpOnly_'):
                tmp.write(line[len('#HttpOnly_'):])
            else:
                tmp.write(line)
        tmp_path = tmp.name

    try:
        cookie_jar.load(tmp_path, ignore_discard=True, ignore_expires=True)
    finally:
        os.unlink(tmp_path)

    return cookie_jar


def get_cvat_session(server_url: str, cookies_file: str | None = None,
                     username: str | None = None, password: str | None = None):
    """Create an opener with CVAT authentication.

    Auth priority: cookies_file > username/password > anonymous.
    """
    cookie_jar = MozillaCookieJar()
    csrf_token = None

    if cookies_file and os.path.exists(cookies_file):
        cookie_jar = _load_cookies_with_httponly(cookies_file)
        for cookie in cookie_jar:
            if cookie.name == 'csrftoken':
                csrf_token = cookie.value

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    if username and password:
        login_data = json.dumps({'username': username, 'password': password}).encode()
        req = urllib.request.Request(
            f'{server_url}/api/auth/login',
            data=login_data,
            method='POST',
        )
        req.add_header('Content-Type', 'application/json')
        with opener.open(req) as resp:
            resp.read()
        for cookie in cookie_jar:
            if cookie.name == 'csrftoken':
                csrf_token = cookie.value

    return opener, csrf_token


# ---------------------------------------------------------------------------
# CVAT API helpers
# ---------------------------------------------------------------------------

def fetch_job_dimensions(server_url: str, job_id: int,
                         opener, csrf_token: str | None) -> tuple[int, int]:
    """Fetch actual video dimensions from CVAT API for a multiview job."""
    req = urllib.request.Request(f'{server_url}/api/jobs/{job_id}')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        job_data = json.loads(resp.read())

    task_id = job_data['task_id']

    req = urllib.request.Request(f'{server_url}/api/tasks/{task_id}/data/meta')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        meta = json.loads(resp.read())

    frames = meta.get('frames', [])
    if frames:
        return frames[0]['width'], frames[0]['height']

    raise RuntimeError(f'Could not determine dimensions for job {job_id}')


def upload_annotations(server_url: str, job_id: int, xml_path: str,
                       opener, csrf_token: str | None) -> None:
    """Upload converted annotations to CVAT job."""
    _safe_print(f'  [Job {job_id}] Deleting existing annotations...')
    req = urllib.request.Request(
        f'{server_url}/api/jobs/{job_id}/annotations/',
        method='DELETE',
    )
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f'DELETE failed: {resp.status}')

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
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)

    with opener.open(req) as resp:
        result = json.loads(resp.read())

    rq_id = result.get('rq_id')
    if not rq_id:
        raise RuntimeError(f'Upload failed: {result}')

    for _ in range(120):
        time.sleep(1)
        req = urllib.request.Request(f'{server_url}/api/requests/{rq_id}')
        if csrf_token:
            req.add_header('X-CSRFToken', csrf_token)
        with opener.open(req) as resp:
            status_data = json.loads(resp.read())
        state = status_data.get('status', '')
        if state == 'finished':
            return
        if state == 'failed':
            raise RuntimeError(f'Upload failed: {status_data}')

    raise RuntimeError('Upload timed out after 120 seconds')


def list_all_jobs(server_url: str, opener, csrf_token: str | None) -> list[dict]:
    """Fetch all jobs from CVAT API (paginated)."""
    jobs = []
    page = 1
    while True:
        url = f'{server_url}/api/jobs?page={page}&page_size=100'
        req = urllib.request.Request(url)
        if csrf_token:
            req.add_header('X-CSRFToken', csrf_token)
        with opener.open(req) as resp:
            data = json.loads(resp.read())

        results = data.get('results', [])
        if not results:
            break
        jobs.extend(results)

        if not data.get('next'):
            break
        page += 1

    return jobs


def export_job_annotations(server_url: str, job_id: int, output_path: str,
                           opener, csrf_token: str | None) -> None:
    """Export annotations from a CVAT job as CVAT 1.1 XML."""
    fmt = urllib.parse.quote('CVAT for video 1.1')
    url = (f'{server_url}/api/jobs/{job_id}/dataset/export'
           f'?save_images=False&format={fmt}')

    req = urllib.request.Request(url, method='POST', data=b'')
    req.add_header('Content-Type', 'application/json')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)

    resp = opener.open(req)
    body = json.loads(resp.read())
    rq_id = body.get('rq_id')
    if not rq_id:
        raise RuntimeError(f'Export initiation failed for job {job_id}: {body}')

    encoded_rq = urllib.parse.quote(rq_id, safe='')
    for _ in range(120):
        time.sleep(1)
        req = urllib.request.Request(f'{server_url}/api/requests/{encoded_rq}')
        if csrf_token:
            req.add_header('X-CSRFToken', csrf_token)
        with opener.open(req) as poll_resp:
            status_data = json.loads(poll_resp.read())

        state = status_data.get('status', '')
        if state == 'finished':
            result_url = status_data.get('result_url', '')
            if not result_url:
                raise RuntimeError(f'No result_url for job {job_id}')
            if not result_url.startswith('http'):
                result_url = f'{server_url}{result_url}'
            req2 = urllib.request.Request(result_url)
            if csrf_token:
                req2.add_header('X-CSRFToken', csrf_token)
            with opener.open(req2) as dl_resp:
                with open(output_path, 'wb') as f:
                    f.write(dl_resp.read())
            return
        if state == 'failed':
            raise RuntimeError(f'Export failed for job {job_id}: {status_data}')

    raise RuntimeError(f'Export timed out for job {job_id}')


def extract_xml_from_zip(zip_path: str, output_dir: str) -> str:
    """Extract the first XML file from a ZIP archive."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        xml_files = [n for n in zf.namelist() if n.endswith('.xml')]
        if not xml_files:
            raise RuntimeError(f'No XML files found in ZIP: {zip_path}')
        zf.extract(xml_files[0], output_dir)
        return os.path.join(output_dir, xml_files[0])


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def _detect_source_dimensions(root, target_w: int, target_h: int) -> tuple[int, int]:
    """Detect actual source coordinate space by inspecting bbox coordinates.

    If <original_size> differs from target, use that.
    Otherwise, check if any bbox exceeds target bounds — if so, coordinates
    are in a larger space (e.g. master's fake 1920x1080).
    """
    orig_size = root.find('.//original_size')
    if orig_size is not None:
        xml_w = int(orig_size.find('width').text)
        xml_h = int(orig_size.find('height').text)
        if xml_w != target_w or xml_h != target_h:
            return xml_w, xml_h

    max_x, max_y = 0.0, 0.0
    for box in root.iter('box'):
        xbr = float(box.get('xbr', '0'))
        ybr = float(box.get('ybr', '0'))
        if xbr > max_x:
            max_x = xbr
        if ybr > max_y:
            max_y = ybr

    if max_x <= target_w and max_y <= target_h:
        return target_w, target_h

    if max_x > target_w or max_y > target_h:
        candidates = [
            (1920, 1080), (1280, 720), (640, 480),
            (3840, 2160), (2560, 1440),
        ]
        for cw, ch in candidates:
            if max_x <= cw and max_y <= ch:
                return cw, ch
        return int(math.ceil(max_x)), int(math.ceil(max_y))

    return target_w, target_h


def convert_annotations(input_path: str, output_path: str,
                        target_w: int, target_h: int,
                        job_id: int | None = None) -> dict:
    """Convert annotation coordinates using Hybrid Scaling."""
    tag = f'[Job {job_id}] ' if job_id else ''
    tree = ET.parse(input_path)
    root = tree.getroot()

    src_w, src_h = _detect_source_dimensions(root, target_w, target_h)

    if src_w == target_w and src_h == target_h:
        _safe_print(f'  {tag}No conversion needed (coordinates within {target_w}x{target_h})')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return {
            'tracks': 0, 'boxes': 0,
            'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}',
        }

    scale_x = target_w / src_w
    scale_y = target_h / src_h
    uniform_scale = math.sqrt(scale_x * scale_y)

    _safe_print(f'  {tag}{src_w}x{src_h} -> {target_w}x{target_h} '
                f'(sx={scale_x:.4f} sy={scale_y:.4f} uniform={uniform_scale:.4f})')

    # Update XML metadata
    orig_size = root.find('.//original_size')
    if orig_size is not None:
        orig_size.find('width').text = str(target_w)
        orig_size.find('height').text = str(target_h)

    for view_el in root.findall('.//multiview/views/view'):
        w_el = view_el.find('width')
        h_el = view_el.find('height')
        if w_el is not None:
            w_el.text = str(target_w)
        if h_el is not None:
            h_el.text = str(target_h)

    def convert_box(box_el):
        xtl = float(box_el.get('xtl'))
        ytl = float(box_el.get('ytl'))
        xbr = float(box_el.get('xbr'))
        ybr = float(box_el.get('ybr'))

        cx = (xtl + xbr) / 2 * scale_x
        cy = (ytl + ybr) / 2 * scale_y
        w = (xbr - xtl) * uniform_scale
        h = (ybr - ytl) * uniform_scale

        box_el.set('xtl', f'{max(0, cx - w / 2):.2f}')
        box_el.set('ytl', f'{max(0, cy - h / 2):.2f}')
        box_el.set('xbr', f'{min(target_w, cx + w / 2):.2f}')
        box_el.set('ybr', f'{min(target_h, cy + h / 2):.2f}')

    track_count = 0
    box_count = 0
    for track in root.findall('.//track'):
        track_count += 1
        for box in track.findall('box'):
            box_count += 1
            convert_box(box)

    shape_count = 0
    for shape in root.findall('.//image/box'):
        shape_count += 1
        convert_box(shape)

    tree.write(output_path, encoding='unicode', xml_declaration=True)

    total_boxes = box_count + shape_count
    _safe_print(f'  {tag}Converted {track_count} tracks, {total_boxes} boxes')
    return {
        'tracks': track_count,
        'boxes': total_boxes,
        'src': f'{src_w}x{src_h}',
        'dst': f'{target_w}x{target_h}',
    }


# ---------------------------------------------------------------------------
# Segment repair (Django ORM — runs inside container)
# ---------------------------------------------------------------------------

def _repair_segment_if_needed(job_id: int) -> str | None:
    """Fix segment stop_frame if annotations reference frames beyond it.

    When tasks were created with master code, _extract_video_metadata() fell
    back to frame_count=3000 (ffprobe not installed). If the actual video has
    more frames, annotations may exist beyond the segment boundary. Also,
    PyAV's video_stream.frames can return 0, and int(duration*fps) can
    undercount by 1-2 frames due to rounding.

    Returns a description of the repair, or None if no repair was needed.
    """
    if not _ensure_django():
        return None

    from cvat.apps.engine.models import Job, TrackedShape, LabeledShape

    try:
        db_job = Job.objects.select_related('segment', 'segment__task__data').get(id=job_id)
    except Job.DoesNotExist:
        return None

    segment = db_job.segment
    db_data = segment.task.data

    max_track_frame = (
        TrackedShape.objects
        .filter(track__job=db_job)
        .order_by('-frame')
        .values_list('frame', flat=True)
        .first()
    )
    max_shape_frame = (
        LabeledShape.objects
        .filter(job=db_job)
        .order_by('-frame')
        .values_list('frame', flat=True)
        .first()
    )

    max_anno_frame = max(max_track_frame or 0, max_shape_frame or 0)

    if max_anno_frame <= segment.stop_frame:
        return None

    # Try to get actual video frame count via PyAV
    actual_frame_count = max_anno_frame + 1
    try:
        import av as _av
        multiview_data = db_data.multiview_data
        if multiview_data:
            video = multiview_data.video_view1
            if video and video.path:
                container = _av.open(video.path)
                vs = container.streams.video[0]
                video_frames = vs.frames
                if not video_frames:
                    duration = float(container.duration / _av.time_base) if container.duration else 0
                    fps = float(vs.average_rate) if vs.average_rate else 30.0
                    video_frames = int(duration * fps) if duration > 0 else 0
                container.close()
                if video_frames > actual_frame_count:
                    actual_frame_count = video_frames
    except Exception:
        pass

    old_stop = segment.stop_frame
    new_stop = actual_frame_count - 1

    segment.stop_frame = new_stop
    segment.save(update_fields=['stop_frame'])

    db_data.size = actual_frame_count
    db_data.stop_frame = new_stop
    db_data.save(update_fields=['size', 'stop_frame'])

    # Invalidate export cache
    cache_pattern = f'/home/django/data/cache/export/job-{job_id}-*'
    for cache_file in _glob_mod.glob(cache_pattern):
        try:
            os.remove(cache_file)
        except OSError:
            pass

    return (f'segment repaired: stop_frame {old_stop} -> {new_stop} '
            f'(max_anno={max_anno_frame}, video={actual_frame_count})')


# ---------------------------------------------------------------------------
# Per-job processing
# ---------------------------------------------------------------------------

def _process_single_job(server_url: str, username: str, password: str,
                        job: dict, dry_run: bool) -> dict:
    """Process one job: repair -> export -> convert -> upload.

    Each thread gets its own HTTP session via thread-local storage.
    """
    job_id = job['id']
    task_id = job.get('task_id', '?')
    task_name = ''

    # Get per-thread session
    opener, csrf_token = _get_thread_session(server_url, username, password)

    try:
        req = urllib.request.Request(f'{server_url}/api/tasks/{task_id}')
        if csrf_token:
            req.add_header('X-CSRFToken', csrf_token)
        with opener.open(req) as resp:
            task_data = json.loads(resp.read())
        task_name = task_data.get('name', '')
    except Exception:
        pass

    try:
        # Repair segment if annotations reference out-of-range frames
        repair_msg = _repair_segment_if_needed(job_id)
        if repair_msg:
            _safe_print(f'  [Job {job_id}] {repair_msg}')

        target_w, target_h = fetch_job_dimensions(
            server_url, job_id, opener, csrf_token,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, f'job_{job_id}_export.zip')
            export_job_annotations(
                server_url, job_id, export_path, opener, csrf_token,
            )

            with open(export_path, 'rb') as f:
                is_zip = f.read(4) == b'PK\x03\x04'
            if is_zip:
                xml_path = extract_xml_from_zip(export_path, tmpdir)
            else:
                xml_path = export_path

            file_size = os.path.getsize(xml_path)
            if file_size < 50:
                return {'type': 'skipped', 'job_id': job_id,
                        'task': task_name, 'reason': 'empty annotations'}

            converted_path = os.path.join(tmpdir, f'job_{job_id}_converted.xml')
            stats = convert_annotations(
                xml_path, converted_path, target_w, target_h, job_id=job_id,
            )

            if stats['src'] == stats['dst']:
                return {'type': 'skipped', 'job_id': job_id,
                        'task': task_name, 'reason': f'already {stats["src"]}'}

            if stats['boxes'] == 0:
                return {'type': 'skipped', 'job_id': job_id,
                        'task': task_name, 'reason': 'no boxes'}

            if dry_run:
                return {'type': 'converted', 'job_id': job_id,
                        'task': task_name, 'stats': stats, 'dry_run': True}

            upload_annotations(
                server_url, job_id, converted_path, opener, csrf_token,
            )
            return {'type': 'converted', 'job_id': job_id,
                    'task': task_name, 'stats': stats}

    except Exception as e:
        return {'type': 'failed', 'job_id': job_id,
                'task': task_name, 'error': str(e)}


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(args) -> int:
    """Batch mode: process all jobs with parallel workers."""
    # Use a single session for initial job listing
    opener, csrf_token = get_cvat_session(
        args.server, None, args.user, args.password,
    )

    print('Fetching all jobs...')
    all_jobs = list_all_jobs(args.server, opener, csrf_token)
    print(f'Found {len(all_jobs)} jobs total')

    if args.job_ids:
        target_ids = set(int(x.strip()) for x in args.job_ids.split(','))
        all_jobs = [j for j in all_jobs if j['id'] in target_ids]
        print(f'Filtered to {len(all_jobs)} jobs: {sorted(target_ids)}')

    if not all_jobs:
        print('No jobs to process.')
        return 0

    workers = min(args.workers, len(all_jobs))
    print(f'Processing {len(all_jobs)} jobs with {workers} parallel workers...\n')

    # Pre-initialize Django ORM before spawning threads
    _ensure_django()

    results = {'converted': [], 'skipped': [], 'failed': []}
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_single_job,
                args.server, args.user, args.password,
                job, args.dry_run,
            ): job
            for job in all_jobs
        }

        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            r = future.result()
            job_id = r['job_id']
            task_name = r.get('task', '')
            progress = f'[{done_count}/{len(all_jobs)}]'

            if r['type'] == 'converted':
                dry = ' [DRY-RUN]' if r.get('dry_run') else ''
                _safe_print(f'{progress} Job {job_id} ({task_name}): '
                            f'{r["stats"]["boxes"]} boxes '
                            f'{r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
                results['converted'].append(r)
            elif r['type'] == 'skipped':
                _safe_print(f'{progress} Job {job_id} ({task_name}): '
                            f'skipped ({r["reason"]})')
                results['skipped'].append(r)
            else:
                _safe_print(f'{progress} Job {job_id} ({task_name}): '
                            f'ERROR - {r["error"]}')
                results['failed'].append(r)

    elapsed = time.monotonic() - t_start

    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
    print(f'Workers:   {workers}')
    print(f'Time:      {elapsed:.1f}s')
    print(f'Converted: {len(results["converted"])} jobs')
    for r in results['converted']:
        dry = ' [DRY-RUN]' if r.get('dry_run') else ''
        print(f'  Job {r["job_id"]} ({r["task"]}): '
              f'{r["stats"]["boxes"]} boxes {r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
    print(f'Skipped:   {len(results["skipped"])} jobs')
    for r in results['skipped']:
        print(f'  Job {r["job_id"]} ({r["task"]}): {r["reason"]}')
    if results['failed']:
        print(f'Failed:    {len(results["failed"])} jobs')
        for r in results['failed']:
            print(f'  Job {r["job_id"]} ({r["task"]}): {r["error"]}')

    return 1 if results['failed'] else 0


# ---------------------------------------------------------------------------
# Single-job mode
# ---------------------------------------------------------------------------

def run_single(args) -> int:
    """Single-job mode: convert one XML file."""
    opener, csrf_token = None, None
    if args.job_id:
        opener, csrf_token = get_cvat_session(
            args.server, args.cookies, args.user, args.password,
        )

    if args.target_w and args.target_h:
        target_w, target_h = args.target_w, args.target_h
    elif args.job_id and opener:
        print(f'Fetching dimensions from CVAT job {args.job_id}...')
        target_w, target_h = fetch_job_dimensions(
            args.server, args.job_id, opener, csrf_token,
        )
        print(f'  Detected: {target_w}x{target_h}')
    else:
        print('ERROR: Either --target-w/--target-h or --job-id is required',
              file=sys.stderr)
        return 1

    convert_annotations(args.input, args.output, target_w, target_h)

    if args.upload:
        if not args.job_id:
            print('ERROR: --upload requires --job-id', file=sys.stderr)
            return 1
        upload_annotations(args.server, args.job_id, args.output,
                           opener, csrf_token)
        print(f'Annotations uploaded to job {args.job_id}')

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert annotation coordinates from master to refactor resolution',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch: convert ALL jobs (dry-run):
  %(prog)s --all-jobs --user admin --password admin123 --dry-run

  # Batch: convert ALL jobs (16 workers):
  %(prog)s --all-jobs --user admin --password admin123 --workers 16

  # Batch: 32 parallel workers:
  %(prog)s --all-jobs --user admin --password admin123 --workers 32

  # Batch: specific jobs only:
  %(prog)s --all-jobs --user admin --password admin123 --job-ids 7,8,9

  # Single: auto-detect dimensions + upload:
  %(prog)s input.xml output.xml --job-id 7 --user admin --password admin123 --upload

  # Single: manual dimensions:
  %(prog)s input.xml output.xml --target-w 320 --target-h 240
        """,
    )
    parser.add_argument('input', nargs='?', default=None,
                        help='Input annotation XML file (single-job mode)')
    parser.add_argument('output', nargs='?', default=None,
                        help='Output annotation XML file (single-job mode)')
    parser.add_argument('--all-jobs', action='store_true',
                        help='Batch mode: process all jobs')
    parser.add_argument('--job-ids', type=str, default=None,
                        help='Comma-separated job IDs (batch mode only)')
    parser.add_argument('--workers', type=int, default=16,
                        help='Number of parallel workers (default: 16)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be converted without uploading')
    parser.add_argument('--target-w', type=int, help='Target width (single-job mode)')
    parser.add_argument('--target-h', type=int, help='Target height (single-job mode)')
    parser.add_argument('--job-id', type=int,
                        help='CVAT job ID for auto-detect (single-job mode)')
    parser.add_argument('--server', default='http://localhost:8080',
                        help='CVAT server URL (default: http://localhost:8080)')
    parser.add_argument('--cookies', default=None,
                        help='Path to cookies.txt file for authentication')
    parser.add_argument('--user', default=None, help='CVAT username')
    parser.add_argument('--password', default=None, help='CVAT password')
    parser.add_argument('--upload', action='store_true',
                        help='Upload converted annotations (single-job mode)')
    args = parser.parse_args()

    if args.all_jobs:
        if not args.user or not args.password:
            parser.error('--all-jobs requires --user and --password')
        return run_batch(args)

    if not args.input or not args.output:
        parser.error('input and output are required in single-job mode '
                     '(or use --all-jobs for batch mode)')

    return run_single(args)


if __name__ == '__main__':
    sys.exit(main())
