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

    # Batch: custom concurrency:
    bash scripts/migration/migrate_v1.sh --user admin --password admin123 --workers 8 --export-concurrency 2

    # Single job (direct Python):
    python migrate_v1.py input.xml output.xml --job-id 7 --user admin --password admin123 --upload
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
from urllib.request import OpenerDirector

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WORKERS = 4
DEFAULT_EXPORT_CONCURRENCY = 4
POLL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 1
MIN_ANNOTATION_FILE_SIZE = 100
MAX_RETRIES = 3
DJANGO_PROJECT_ROOT = '/home/django'
EXPORT_CACHE_DIR = '/home/django/data/cache/export'

# Standard video resolutions for fallback source dimension detection.
# Ordered by likelihood (master used 1920x1080 fake resolution).
KNOWN_VIDEO_RESOLUTIONS = [
    (1920, 1080),
    (1280, 720),
    (640, 480),
    (3840, 2160),
    (2560, 1440),
]


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
    """Get or create a per-thread authenticated HTTP session."""
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
            if os.path.isdir(os.path.join(DJANGO_PROJECT_ROOT, 'cvat')):
                if DJANGO_PROJECT_ROOT not in sys.path:
                    sys.path.insert(0, DJANGO_PROJECT_ROOT)
            import django
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cvat.settings.production')
            django.setup()
            _django_initialized = True
            _safe_print('  [Django] ORM initialized successfully')
            return True
        except Exception as e:
            _safe_print(f'  [Django] FAILED to initialize: {e}')
            _safe_print(f'  [Django] Segment repair will be unavailable')
            return False


# ---------------------------------------------------------------------------
# CVAT API helpers
# ---------------------------------------------------------------------------

def _api_get(opener: OpenerDirector, csrf_token: str | None,
             url: str) -> dict:
    """Make an authenticated GET request and return parsed JSON."""
    req = urllib.request.Request(url)
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        return json.loads(resp.read())


def _api_post(opener: OpenerDirector, csrf_token: str | None,
              url: str, data: bytes = b'',
              content_type: str = 'application/json') -> dict:
    """Make an authenticated POST request and return parsed JSON."""
    req = urllib.request.Request(url, method='POST', data=data)
    req.add_header('Content-Type', content_type)
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        return json.loads(resp.read())


def _api_delete(opener: OpenerDirector, csrf_token: str | None,
                url: str) -> None:
    """Make an authenticated DELETE request."""
    req = urllib.request.Request(url, method='DELETE')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        resp.read()


def _poll_rq_request(opener: OpenerDirector, csrf_token: str | None,
                     server_url: str, rq_id: str,
                     timeout: int = POLL_TIMEOUT_SECONDS) -> dict:
    """Poll an RQ request until finished/failed or timeout."""
    encoded_rq = urllib.parse.quote(rq_id, safe='')
    for _ in range(timeout):
        time.sleep(POLL_INTERVAL_SECONDS)
        status_data = _api_get(opener, csrf_token,
                               f'{server_url}/api/requests/{encoded_rq}')
        state = status_data.get('status', '')
        if state == 'finished':
            return status_data
        if state == 'failed':
            raise RuntimeError(f'RQ request failed: {status_data}')
    raise RuntimeError(f'RQ request timed out after {timeout}s (rq_id={rq_id})')


# ---------------------------------------------------------------------------
# Authentication
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
                     username: str | None = None,
                     password: str | None = None) -> tuple[OpenerDirector, str | None]:
    """Create an opener with CVAT authentication."""
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
# CVAT operations
# ---------------------------------------------------------------------------

def list_all_jobs(server_url: str, opener: OpenerDirector,
                  csrf_token: str | None) -> list[dict]:
    """Fetch all jobs from CVAT API (paginated)."""
    jobs = []
    page = 1
    while True:
        data = _api_get(opener, csrf_token,
                        f'{server_url}/api/jobs?page={page}&page_size=100')
        results = data.get('results', [])
        if not results:
            break
        jobs.extend(results)
        if not data.get('next'):
            break
        page += 1
    return jobs


def fetch_job_dimensions(server_url: str, job_id: int,
                         opener: OpenerDirector,
                         csrf_token: str | None) -> tuple[int, int]:
    """Fetch actual video dimensions from CVAT API for a multiview job."""
    job_data = _api_get(opener, csrf_token, f'{server_url}/api/jobs/{job_id}')
    task_id = job_data['task_id']
    meta = _api_get(opener, csrf_token,
                    f'{server_url}/api/tasks/{task_id}/data/meta')
    frames = meta.get('frames', [])
    if frames:
        return frames[0]['width'], frames[0]['height']
    raise RuntimeError(f'Could not determine dimensions for job {job_id}')


def export_job_annotations(server_url: str, job_id: int, output_path: str,
                           opener: OpenerDirector, csrf_token: str | None,
                           export_semaphore: threading.Semaphore | None = None,
                           timeout: int = POLL_TIMEOUT_SECONDS) -> None:
    """Export annotations from a CVAT job as CVAT 1.1 XML.

    Uses a semaphore to limit concurrent exports (matching server RQ capacity).
    Handles HTTP 409 (export already queued/running) by polling existing request.
    """
    fmt = urllib.parse.quote('CVAT for video 1.1')
    url = (f'{server_url}/api/jobs/{job_id}/dataset/export'
           f'?save_images=False&format={fmt}')

    if export_semaphore:
        export_semaphore.acquire()
    try:
        try:
            body = _api_post(opener, csrf_token, url)
        except urllib.error.HTTPError as e:
            if e.code == 409:
                body = json.loads(e.read())
                _safe_print(f'  [Job {job_id}] export already queued (409), '
                            f'polling existing request')
            else:
                raise
        rq_id = body.get('rq_id')
        if not rq_id:
            raise RuntimeError(f'Export initiation failed for job {job_id}: {body}')
    finally:
        if export_semaphore:
            export_semaphore.release()

    # Poll outside semaphore — multiple polls can run concurrently
    result = _poll_rq_request(opener, csrf_token, server_url, rq_id, timeout)
    result_url = result.get('result_url', '')
    if not result_url:
        raise RuntimeError(f'No result_url for job {job_id}')
    if not result_url.startswith('http'):
        result_url = f'{server_url}{result_url}'

    req = urllib.request.Request(result_url)
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as dl_resp:
        with open(output_path, 'wb') as f:
            f.write(dl_resp.read())


def upload_annotations(server_url: str, job_id: int, xml_path: str,
                       opener: OpenerDirector,
                       csrf_token: str | None) -> None:
    """Upload converted annotations to CVAT job (delete + upload)."""
    _safe_print(f'  [Job {job_id}] Deleting existing annotations...')
    _api_delete(opener, csrf_token,
                f'{server_url}/api/jobs/{job_id}/annotations/')

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

    _poll_rq_request(opener, csrf_token, server_url, rq_id)


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

def _detect_source_dimensions(root, target_w: int,
                              target_h: int) -> tuple[int, int]:
    """Detect source coordinate space by inspecting bbox coordinates."""
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

    # Coordinates exceed target — guess the source resolution
    for cw, ch in KNOWN_VIDEO_RESOLUTIONS:
        if max_x <= cw and max_y <= ch:
            return cw, ch
    return int(math.ceil(max_x)), int(math.ceil(max_y))


def convert_annotations(input_path: str, output_path: str,
                        target_w: int, target_h: int,
                        job_id: int | None = None) -> dict:
    """Convert annotation coordinates using Hybrid Scaling."""
    tag = f'[Job {job_id}] ' if job_id else ''
    tree = ET.parse(input_path)
    root = tree.getroot()

    src_w, src_h = _detect_source_dimensions(root, target_w, target_h)

    if src_w == target_w and src_h == target_h:
        _safe_print(f'  {tag}No conversion needed '
                    f'(coordinates within {target_w}x{target_h})')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return {
            'tracks': 0, 'boxes': 0,
            'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}',
        }

    scale_x = target_w / src_w
    scale_y = target_h / src_h
    uniform_scale = math.sqrt(scale_x * scale_y)

    _safe_print(f'  {tag}{src_w}x{src_h} -> {target_w}x{target_h} '
                f'(sx={scale_x:.4f} sy={scale_y:.4f} '
                f'uniform={uniform_scale:.4f})')

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

def _get_video_frame_count(db_data) -> int | None:
    """Get actual video frame count via PyAV (best-effort)."""
    try:
        import av
        multiview_data = db_data.multiview_data
        if not multiview_data:
            return None
        video = multiview_data.video_view1
        if not video or not video.path:
            return None
        with av.open(video.path) as container:
            vs = container.streams.video[0]
            frames = vs.frames
            if not frames:
                duration = (float(container.duration / av.time_base)
                            if container.duration else 0)
                fps = float(vs.average_rate) if vs.average_rate else 30.0
                frames = int(duration * fps) if duration > 0 else 0
            return frames if frames > 0 else None
    except Exception as e:
        return None


def _repair_segment_if_needed(job_id: int) -> str | None:
    """Fix segment stop_frame if annotations reference frames beyond it.

    Returns a description of the repair, or None if no repair was needed.
    """
    if not _ensure_django():
        _safe_print(f'  [Job {job_id}] WARNING: Django unavailable, '
                    f'skipping segment repair')
        return None

    from django.db import transaction
    from cvat.apps.engine.models import Job, TrackedShape, LabeledShape

    try:
        db_job = (Job.objects
                  .select_related('segment', 'segment__task__data')
                  .get(id=job_id))
    except Job.DoesNotExist:
        _safe_print(f'  [Job {job_id}] WARNING: Job not found in DB')
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

    actual_frame_count = max_anno_frame + 1
    video_frames = _get_video_frame_count(db_data)
    if video_frames and video_frames > actual_frame_count:
        actual_frame_count = video_frames

    old_stop = segment.stop_frame
    new_stop = actual_frame_count - 1

    with transaction.atomic():
        segment.stop_frame = new_stop
        segment.save(update_fields=['stop_frame'])
        db_data.size = actual_frame_count
        db_data.stop_frame = new_stop
        db_data.save(update_fields=['size', 'stop_frame'])

    # Invalidate export cache
    cache_pattern = f'{EXPORT_CACHE_DIR}/job-{job_id}-*'
    removed = 0
    for cache_file in glob.glob(cache_pattern):
        try:
            os.remove(cache_file)
            removed += 1
        except OSError:
            pass

    msg = (f'segment repaired: stop_frame {old_stop} -> {new_stop} '
           f'(max_anno={max_anno_frame}, video={actual_frame_count})')
    if removed:
        msg += f', cleared {removed} cache files'
    return msg


# ---------------------------------------------------------------------------
# Per-job processing
# ---------------------------------------------------------------------------

def _fetch_task_name(server_url: str, task_id, opener: OpenerDirector,
                     csrf_token: str | None) -> str:
    """Best-effort fetch of task name for logging."""
    try:
        data = _api_get(opener, csrf_token,
                        f'{server_url}/api/tasks/{task_id}')
        return data.get('name', '')
    except Exception:
        return ''


def _export_and_extract(server_url: str, job_id: int,
                        opener: OpenerDirector, csrf_token: str | None,
                        tmpdir: str,
                        export_semaphore: threading.Semaphore | None
                        ) -> str | None:
    """Export annotations and return XML path, or None if empty."""
    export_path = os.path.join(tmpdir, f'job_{job_id}_export.zip')
    export_job_annotations(server_url, job_id, export_path,
                           opener, csrf_token, export_semaphore)

    with open(export_path, 'rb') as f:
        is_zip = f.read(4) == b'PK\x03\x04'

    if is_zip:
        xml_path = extract_xml_from_zip(export_path, tmpdir)
    else:
        xml_path = export_path

    if os.path.getsize(xml_path) < MIN_ANNOTATION_FILE_SIZE:
        return None
    return xml_path


def _process_single_job(server_url: str, username: str, password: str,
                        job: dict, dry_run: bool,
                        export_semaphore: threading.Semaphore | None = None
                        ) -> dict:
    """Process one job: export -> convert -> upload.

    Segment repair is done in Phase 1 (before parallel export).
    Retries up to MAX_RETRIES times on transient failures.
    """
    job_id = job['id']
    task_id = job.get('task_id', '?')
    opener, csrf_token = _get_thread_session(server_url, username, password)
    task_name = _fetch_task_name(server_url, task_id, opener, csrf_token)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                repair_msg = _repair_segment_if_needed(job_id)
                if repair_msg:
                    _safe_print(f'  [Job {job_id}] (retry repair) {repair_msg}')

            target_w, target_h = fetch_job_dimensions(
                server_url, job_id, opener, csrf_token)

            with tempfile.TemporaryDirectory() as tmpdir:
                xml_path = _export_and_extract(
                    server_url, job_id, opener, csrf_token,
                    tmpdir, export_semaphore)

                if xml_path is None:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name, 'reason': 'empty annotations'}

                converted_path = os.path.join(
                    tmpdir, f'job_{job_id}_converted.xml')
                stats = convert_annotations(
                    xml_path, converted_path, target_w, target_h,
                    job_id=job_id)

                if stats['src'] == stats['dst']:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name,
                            'reason': f'already {stats["src"]}'}

                if stats['boxes'] == 0:
                    return {'type': 'skipped', 'job_id': job_id,
                            'task': task_name, 'reason': 'no boxes'}

                if dry_run:
                    return {'type': 'converted', 'job_id': job_id,
                            'task': task_name, 'stats': stats,
                            'dry_run': True}

                upload_annotations(
                    server_url, job_id, converted_path, opener, csrf_token)
                return {'type': 'converted', 'job_id': job_id,
                        'task': task_name, 'stats': stats}

        except Exception as e:
            last_error = e
            err_str = str(e)
            is_frame_error = 'Unknown internal frame id' in err_str
            if attempt < MAX_RETRIES:
                wait = attempt * 5
                hint = (' (will retry with segment repair)'
                        if is_frame_error else '')
                _safe_print(
                    f'  [Job {job_id}] attempt {attempt}/{MAX_RETRIES} '
                    f'failed: {e} (retry in {wait}s){hint}')
                time.sleep(wait)

    return {'type': 'failed', 'job_id': job_id,
            'task': task_name, 'error': str(last_error)}


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def _repair_all_segments(job_ids: list[int]) -> dict[int, str]:
    """Phase 1: Repair all segments sequentially before export."""
    print(f'\n--- Phase 1: Segment repair ({len(job_ids)} jobs) ---')

    if not _ensure_django():
        print('  WARNING: Django unavailable — segment repair skipped')
        print('  Jobs with out-of-range annotations WILL fail during export')
        return {}

    repaired = {}
    errors = 0
    for i, job_id in enumerate(job_ids, 1):
        try:
            msg = _repair_segment_if_needed(job_id)
            if msg:
                _safe_print(f'  [{i}/{len(job_ids)}] Job {job_id}: {msg}')
                repaired[job_id] = msg
        except Exception as e:
            errors += 1
            _safe_print(f'  [{i}/{len(job_ids)}] Job {job_id}: '
                        f'REPAIR ERROR - {e}')

    print(f'  Repair complete: {len(repaired)} repaired, '
          f'{len(job_ids) - len(repaired) - errors} OK, {errors} errors')
    return repaired


def _print_summary(results: dict, workers: int, elapsed: float,
                   export_concurrency: int) -> None:
    """Print migration summary."""
    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
    print(f'Workers:   {workers} (export concurrency: {export_concurrency})')
    print(f'Time:      {elapsed:.1f}s')
    print(f'Converted: {len(results["converted"])} jobs')
    for r in results['converted']:
        dry = ' [DRY-RUN]' if r.get('dry_run') else ''
        print(f'  Job {r["job_id"]} ({r["task"]}): '
              f'{r["stats"]["boxes"]} boxes '
              f'{r["stats"]["src"]} -> {r["stats"]["dst"]}{dry}')
    print(f'Skipped:   {len(results["skipped"])} jobs')
    for r in results['skipped']:
        print(f'  Job {r["job_id"]} ({r["task"]}): {r["reason"]}')
    if results['failed']:
        print(f'Failed:    {len(results["failed"])} jobs')
        for r in results['failed']:
            print(f'  Job {r["job_id"]} ({r["task"]}): {r["error"]}')


def run_batch(server: str, user: str, password: str,
              job_ids: str | None = None,
              workers: int = DEFAULT_WORKERS,
              export_concurrency: int = DEFAULT_EXPORT_CONCURRENCY,
              dry_run: bool = False,
              repair_only: bool = False) -> int:
    """Batch mode: process all jobs in two phases.

    Phase 1: Repair all segments (sequential, Django ORM)
    Phase 2: Export, convert, upload (parallel, HTTP API)
    """
    opener, csrf_token = get_cvat_session(server, None, user, password)

    print('Fetching all jobs...')
    all_jobs = list_all_jobs(server, opener, csrf_token)
    print(f'Found {len(all_jobs)} jobs total')

    if job_ids:
        target_ids = set(int(x.strip()) for x in job_ids.split(','))
        all_jobs = [j for j in all_jobs if j['id'] in target_ids]
        print(f'Filtered to {len(all_jobs)} jobs: {sorted(target_ids)}')

    if not all_jobs:
        print('No jobs to process.')
        return 0

    # Phase 1
    all_job_ids = [j['id'] for j in all_jobs]
    _repair_all_segments(all_job_ids)

    if repair_only:
        print('\n--repair-only: stopping after segment repair')
        return 0

    # Phase 2
    export_sem = threading.Semaphore(export_concurrency)
    workers = min(workers, len(all_jobs))
    print(f'\n--- Phase 2: Export & convert ({len(all_jobs)} jobs, '
          f'{workers} workers, export concurrency={export_concurrency}) ---\n')

    results = {'converted': [], 'skipped': [], 'failed': []}
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_single_job,
                server, user, password,
                job, dry_run, export_sem,
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
                            f'{r["stats"]["src"]} -> {r["stats"]["dst"]}'
                            f'{dry}')
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
    _print_summary(results, workers, elapsed, export_concurrency)

    return 1 if results['failed'] else 0


# ---------------------------------------------------------------------------
# Single-job mode
# ---------------------------------------------------------------------------

def run_single(args) -> int:
    """Single-job mode: convert one XML file."""
    opener, csrf_token = None, None
    if args.job_id:
        opener, csrf_token = get_cvat_session(
            args.server, args.cookies, args.user, args.password)

    if args.target_w and args.target_h:
        target_w, target_h = args.target_w, args.target_h
    elif args.job_id and opener:
        print(f'Fetching dimensions from CVAT job {args.job_id}...')
        target_w, target_h = fetch_job_dimensions(
            args.server, args.job_id, opener, csrf_token)
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
        description='Convert annotation coordinates from master '
                    'to refactor resolution',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch: convert ALL jobs (dry-run):
  %(prog)s --all-jobs --user admin --password admin123 --dry-run

  # Batch: convert ALL jobs:
  %(prog)s --all-jobs --user admin --password admin123

  # Batch: specific jobs only:
  %(prog)s --all-jobs --user admin --password admin123 --job-ids 7,8,9

  # Batch: custom concurrency:
  %(prog)s --all-jobs --user admin --password admin123 --workers 8 --export-concurrency 2

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
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS,
                        help=f'Number of parallel workers '
                             f'(default: {DEFAULT_WORKERS})')
    parser.add_argument('--export-concurrency', type=int,
                        default=DEFAULT_EXPORT_CONCURRENCY,
                        help=f'Max concurrent export requests '
                             f'(default: {DEFAULT_EXPORT_CONCURRENCY})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be converted without uploading')
    parser.add_argument('--repair-only', action='store_true',
                        help='Only repair segments (Phase 1), '
                             'skip export/convert')
    parser.add_argument('--target-w', type=int,
                        help='Target width (single-job mode)')
    parser.add_argument('--target-h', type=int,
                        help='Target height (single-job mode)')
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
        return run_batch(
            server=args.server,
            user=args.user,
            password=args.password,
            job_ids=args.job_ids,
            workers=args.workers,
            export_concurrency=args.export_concurrency,
            dry_run=args.dry_run,
            repair_only=args.repair_only,
        )

    if not args.input or not args.output:
        parser.error('input and output are required in single-job mode '
                     '(or use --all-jobs for batch mode)')

    return run_single(args)


if __name__ == '__main__':
    sys.exit(main())
