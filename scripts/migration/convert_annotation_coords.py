#!/usr/bin/env python3
"""
Master -> Refactor annotation coordinate converter.

Master stored video dimensions as 1920x1080 (ffprobe fallback) even though
actual videos are smaller (e.g. 320x240). This script converts annotation
coordinates from master's fake 1920x1080 task space to actual video dimensions.

Conversion strategy:
  - Center position: non-uniform scaling (X/Y scaled independently)
    → Correct spatial mapping to actual video coordinates
  - Bbox dimensions: uniform scaling (geometric mean of X/Y scales)
    → Preserves the annotator's intended bbox aspect ratio

This hybrid approach is necessary because master displayed 4:3 videos as 16:9
(horizontal stretching). Annotators drew bboxes on the stretched view, so their
bbox shapes should be preserved as-is rather than "corrected" for aspect ratio.

Usage:
    # Auto-detect target dimensions from CVAT API:
    python convert_annotation_coords.py <input.xml> <output.xml> --job-id 7

    # Manual target dimensions:
    python convert_annotation_coords.py <input.xml> <output.xml> --target-w 320 --target-h 240

    # Convert and upload in one step:
    python convert_annotation_coords.py <input.xml> <output.xml> --job-id 7 --upload
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
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


def convert_annotations(input_path: str, output_path: str,
                        target_w: int, target_h: int) -> dict:
    tree = ET.parse(input_path)
    root = tree.getroot()

    # Read source dimensions from XML <original_size>
    orig_size = root.find('.//original_size')
    if orig_size is None:
        print('ERROR: <original_size> not found in XML', file=sys.stderr)
        sys.exit(1)

    src_w = int(orig_size.find('width').text)
    src_h = int(orig_size.find('height').text)

    if src_w == target_w and src_h == target_h:
        print(f'Dimensions already match ({src_w}x{src_h}), no conversion needed.')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        return {
            'tracks': 0, 'boxes': 0,
            'src': f'{src_w}x{src_h}', 'dst': f'{target_w}x{target_h}',
        }

    scale_x = target_w / src_w
    scale_y = target_h / src_h

    print(f'Source:  {src_w}x{src_h}')
    print(f'Target:  {target_w}x{target_h}')
    print(f'Scale:   x={scale_x:.6f}, y={scale_y:.6f}')

    if abs(scale_x - scale_y) > 0.001:
        src_ar = src_w / src_h
        tgt_ar = target_w / target_h
        print(f'NOTE: Aspect ratio differs (source={src_ar:.3f}, target={tgt_ar:.3f})')
        print(f'  Using hybrid scaling: center=non-uniform, size=uniform (geometric mean)')
        print(f'  Bbox aspect ratio will be preserved from source.')

    # Update <original_size>
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
    print(f'Uniform scale (geometric mean): {uniform_scale:.6f}')

    def convert_box(box_el):
        """Convert a single box: center via non-uniform, size via uniform scale."""
        xtl = float(box_el.get('xtl'))
        ytl = float(box_el.get('ytl'))
        xbr = float(box_el.get('xbr'))
        ybr = float(box_el.get('ybr'))

        # Center position: non-uniform scaling (correct spatial mapping)
        cx = (xtl + xbr) / 2 * scale_x
        cy = (ytl + ybr) / 2 * scale_y

        # Dimensions: uniform scaling (preserve bbox aspect ratio)
        w = (xbr - xtl) * uniform_scale
        h = (ybr - ytl) * uniform_scale

        # Reconstruct corners from center + size
        new_xtl = max(0, cx - w / 2)
        new_ytl = max(0, cy - h / 2)
        new_xbr = min(target_w, cx + w / 2)
        new_ybr = min(target_h, cy + h / 2)

        box_el.set('xtl', f'{new_xtl:.2f}')
        box_el.set('ytl', f'{new_ytl:.2f}')
        box_el.set('xbr', f'{new_xbr:.2f}')
        box_el.set('ybr', f'{new_ybr:.2f}')

    # Scale all box coordinates in tracks
    track_count = 0
    box_count = 0

    for track in root.findall('.//track'):
        track_count += 1
        for box in track.findall('box'):
            box_count += 1
            convert_box(box)

    # Also handle <shape> elements (for non-track annotations)
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
    print(f'Converted {track_count} tracks, {box_count + shape_count} boxes')
    print(f'Output: {output_path}')
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Convert annotation coordinates between resolution spaces',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect dimensions from CVAT API:
  %(prog)s input.xml output.xml --job-id 7

  # Manual dimensions:
  %(prog)s input.xml output.xml --target-w 320 --target-h 240

  # Convert and upload in one step:
  %(prog)s input.xml output.xml --job-id 7 --upload

  # With custom server URL:
  %(prog)s input.xml output.xml --job-id 7 --server http://my-server:8080
        """,
    )
    parser.add_argument('input', help='Input annotation XML file')
    parser.add_argument('output', help='Output annotation XML file')
    parser.add_argument('--target-w', type=int, help='Target width')
    parser.add_argument('--target-h', type=int, help='Target height')
    parser.add_argument('--job-id', type=int, help='CVAT job ID (auto-detect dimensions)')
    parser.add_argument('--server', default='http://localhost:8080',
                        help='CVAT server URL (default: http://localhost:8080)')
    parser.add_argument('--cookies', default=None,
                        help='Path to cookies.txt file for authentication')
    parser.add_argument('--user', default=None, help='CVAT username')
    parser.add_argument('--password', default=None, help='CVAT password')
    parser.add_argument('--upload', action='store_true',
                        help='Upload converted annotations to the CVAT job')
    args = parser.parse_args()

    # Determine target dimensions
    opener, csrf_token = None, None
    if args.job_id:
        cookies_file = args.cookies
        if not cookies_file:
            # Try to find cookies.txt in common locations
            for candidate in ['cookies.txt', '../cookies.txt']:
                if os.path.exists(candidate):
                    cookies_file = candidate
                    break
        opener, csrf_token = get_cvat_session(
            args.server, cookies_file, args.user, args.password,
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
        parser.error('Either --target-w/--target-h or --job-id is required')

    stats = convert_annotations(args.input, args.output, target_w, target_h)

    if args.upload:
        if not args.job_id:
            parser.error('--upload requires --job-id')
        upload_annotations(args.server, args.job_id, args.output,
                           opener, csrf_token)
        print(f'Annotations uploaded to job {args.job_id}')

    return stats


if __name__ == '__main__':
    main()
