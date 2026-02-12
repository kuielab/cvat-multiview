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

    # Single job (direct Python):
    python migrate_v1.py input.xml output.xml --job-id 7 --user admin --password admin123 --upload
"""

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from http.cookiejar import MozillaCookieJar


def _load_cookies_with_httponly(path: str) -> MozillaCookieJar:
    """Load cookies.txt handling #HttpOnly_ lines that Python ignores."""
    cookie_jar = MozillaCookieJar()

    # Read file and fix #HttpOnly_ lines so MozillaCookieJar can parse them
    with open(path, 'r') as f:
        lines = f.readlines()

    import tempfile
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
        # Update CSRF token from login response cookies
        for cookie in cookie_jar:
            if cookie.name == 'csrftoken':
                csrf_token = cookie.value

    return opener, csrf_token


def fetch_job_dimensions(server_url: str, job_id: int,
                         opener, csrf_token: str | None) -> tuple[int, int]:
    """Fetch actual video dimensions from CVAT API for a multiview job."""
    # Get job info to find task_id
    req = urllib.request.Request(f'{server_url}/api/jobs/{job_id}')
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        job_data = json.loads(resp.read())

    task_id = job_data['task_id']

    # Get data meta for frame dimensions
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
    # First, delete existing annotations
    print(f'Deleting existing annotations from job {job_id}...')
    req = urllib.request.Request(
        f'{server_url}/api/jobs/{job_id}/annotations/',
        method='DELETE',
    )
    if csrf_token:
        req.add_header('X-CSRFToken', csrf_token)
    with opener.open(req) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f'DELETE failed: {resp.status}')
    print('  Deleted.')

    # Upload new annotations
    print(f'Uploading {xml_path}...')
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
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

    # Poll for completion
    print(f'  Upload started (rq_id={rq_id}), waiting...')
    for _ in range(60):
        time.sleep(1)
        req = urllib.request.Request(f'{server_url}/api/requests/{rq_id}')
        if csrf_token:
            req.add_header('X-CSRFToken', csrf_token)
        with opener.open(req) as resp:
            status_data = json.loads(resp.read())
        state = status_data.get('status', '')
        if state == 'finished':
            print('  Upload complete.')
            return
        if state == 'failed':
            raise RuntimeError(f'Upload failed: {status_data}')

    raise RuntimeError('Upload timed out after 60 seconds')


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

    # <original_size> matches target, but coordinates might be in a larger space
    # (e.g. task recreated with refactor but annotations imported from master)
    max_x, max_y = 0.0, 0.0
    for box in root.iter('box'):
        xbr = float(box.get('xbr', '0'))
        ybr = float(box.get('ybr', '0'))
        if xbr > max_x:
            max_x = xbr
        if ybr > max_y:
            max_y = ybr

    if max_x <= target_w and max_y <= target_h:
        # All coordinates within target bounds — no conversion needed
        return target_w, target_h

    # Coordinates exceed target bounds — infer source dimensions
    # Master used 1920x1080 as fallback, so try that first
    if max_x > target_w or max_y > target_h:
        # Round up to common resolutions
        candidates = [
            (1920, 1080), (1280, 720), (640, 480),
            (3840, 2160), (2560, 1440),
        ]
        for cw, ch in candidates:
            if max_x <= cw and max_y <= ch:
                return cw, ch
        # Fallback: use max coordinate bounds rounded up
        return int(math.ceil(max_x)), int(math.ceil(max_y))

    return target_w, target_h


def convert_annotations(input_path: str, output_path: str,
                        target_w: int, target_h: int) -> dict:
    tree = ET.parse(input_path)
    root = tree.getroot()

    src_w, src_h = _detect_source_dimensions(root, target_w, target_h)

    if src_w == target_w and src_h == target_h:
        print(f'  No conversion needed (coordinates within {target_w}x{target_h})')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return {
            'tracks': 0, 'boxes': 0,
            'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}',
        }

    scale_x = target_w / src_w
    scale_y = target_h / src_h

    print(f'  Source space: {src_w}x{src_h}')
    print(f'  Target space: {target_w}x{target_h}')
    print(f'  Scale: x={scale_x:.6f}, y={scale_y:.6f}')

    if abs(scale_x - scale_y) > 0.001:
        print(f'  Hybrid scaling: center=non-uniform, size=uniform (geometric mean)')

    # Update <original_size>
    orig_size = root.find('.//original_size')
    if orig_size is not None:
        orig_size.find('width').text = str(target_w)
        orig_size.find('height').text = str(target_h)

    # Update <multiview><views><view> dimensions
    for view_el in root.findall('.//multiview/views/view'):
        w_el = view_el.find('width')
        h_el = view_el.find('height')
        if w_el is not None:
            w_el.text = str(target_w)
        if h_el is not None:
            h_el.text = str(target_h)

    # Uniform scale for bbox dimensions (geometric mean) to preserve aspect ratio
    uniform_scale = math.sqrt(scale_x * scale_y)

    def convert_box(box_el):
        """Convert a single box: center via non-uniform, size via uniform scale."""
        xtl = float(box_el.get('xtl'))
        ytl = float(box_el.get('ytl'))
        xbr = float(box_el.get('xbr'))
        ybr = float(box_el.get('ybr'))

        cx = (xtl + xbr) / 2 * scale_x
        cy = (ytl + ybr) / 2 * scale_y

        w = (xbr - xtl) * uniform_scale
        h = (ybr - ytl) * uniform_scale

        new_xtl = max(0, cx - w / 2)
        new_ytl = max(0, cy - h / 2)
        new_xbr = min(target_w, cx + w / 2)
        new_ybr = min(target_h, cy + h / 2)

        box_el.set('xtl', f'{new_xtl:.2f}')
        box_el.set('ytl', f'{new_ytl:.2f}')
        box_el.set('xbr', f'{new_xbr:.2f}')
        box_el.set('ybr', f'{new_ybr:.2f}')

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

    stats = {
        'tracks': track_count,
        'boxes': box_count + shape_count,
        'src': f'{src_w}x{src_h}',
        'dst': f'{target_w}x{target_h}',
    }
    print(f'  Converted {track_count} tracks, {box_count + shape_count} boxes')
    return stats


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


def run_batch(args) -> int:
    """Batch mode: iterate all jobs, export -> convert -> upload."""
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

    results = {'converted': [], 'skipped': [], 'failed': []}

    for job in all_jobs:
        job_id = job['id']
        task_id = job.get('task_id', '?')
        task_name = ''

        try:
            req = urllib.request.Request(f'{args.server}/api/tasks/{task_id}')
            if csrf_token:
                req.add_header('X-CSRFToken', csrf_token)
            with opener.open(req) as resp:
                task_data = json.loads(resp.read())
            task_name = task_data.get('name', '')
        except Exception:
            pass

        print(f'\n{"="*60}')
        print(f'Job {job_id} (Task {task_id}: {task_name})')
        print(f'{"="*60}')

        try:
            target_w, target_h = fetch_job_dimensions(
                args.server, job_id, opener, csrf_token,
            )
            print(f'  Video dimensions: {target_w}x{target_h}')

            with tempfile.TemporaryDirectory() as tmpdir:
                export_path = os.path.join(tmpdir, f'job_{job_id}_export.xml')
                print(f'  Exporting annotations...')
                export_job_annotations(
                    args.server, job_id, export_path, opener, csrf_token,
                )

                # Handle ZIP format
                with open(export_path, 'rb') as f:
                    is_zip = f.read(4) == b'PK\x03\x04'
                if is_zip:
                    xml_path = extract_xml_from_zip(export_path, tmpdir)
                else:
                    xml_path = export_path

                file_size = os.path.getsize(xml_path)
                if file_size < 50:
                    print(f'  Skipping: empty annotations ({file_size} bytes)')
                    results['skipped'].append({
                        'job_id': job_id, 'task': task_name,
                        'reason': 'empty annotations',
                    })
                    continue

                converted_path = os.path.join(tmpdir, f'job_{job_id}_converted.xml')
                stats = convert_annotations(xml_path, converted_path, target_w, target_h)

                if stats['src'] == stats['dst']:
                    print(f'  Skipping: dimensions already match ({stats["src"]})')
                    results['skipped'].append({
                        'job_id': job_id, 'task': task_name,
                        'reason': f'already {stats["src"]}',
                    })
                    continue

                if stats['boxes'] == 0:
                    print(f'  Skipping: no boxes to convert')
                    results['skipped'].append({
                        'job_id': job_id, 'task': task_name,
                        'reason': 'no boxes',
                    })
                    continue

                if args.dry_run:
                    print(f'  [DRY-RUN] Would convert {stats["boxes"]} boxes '
                          f'from {stats["src"]} -> {stats["dst"]}')
                    results['converted'].append({
                        'job_id': job_id, 'task': task_name,
                        'stats': stats, 'dry_run': True,
                    })
                else:
                    print(f'  Uploading converted annotations...')
                    upload_annotations(
                        args.server, job_id, converted_path, opener, csrf_token,
                    )
                    print(f'  Done: {stats["boxes"]} boxes '
                          f'from {stats["src"]} -> {stats["dst"]}')
                    results['converted'].append({
                        'job_id': job_id, 'task': task_name,
                        'stats': stats,
                    })

        except Exception as e:
            print(f'  ERROR: {e}')
            results['failed'].append({
                'job_id': job_id, 'task': task_name,
                'error': str(e),
            })

    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
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


def main():
    parser = argparse.ArgumentParser(
        description='Convert annotation coordinates from master to refactor resolution',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch: convert ALL jobs (dry-run):
  %(prog)s --all-jobs --user admin --password admin123 --dry-run

  # Batch: convert ALL jobs (actual):
  %(prog)s --all-jobs --user admin --password admin123

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
