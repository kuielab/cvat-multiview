#!/usr/bin/env python3
"""
Batch migration: convert ALL jobs' annotation coordinates.

Iterates every job in CVAT, exports annotations as CVAT 1.1 XML,
runs hybrid-scaling coordinate conversion, and re-uploads.
Jobs whose XML <original_size> already matches the actual video
dimensions are skipped automatically.

Usage (local):
    python scripts/migration/migrate_all.py --user admin --password admin123

Usage (EC2 — inside cvat_server container):
    docker exec -it cvat_server python /home/django/scripts/migration/migrate_all.py \
        --user admin --password admin123 --server http://localhost:8080

Dry-run (no upload, just show what would be converted):
    python scripts/migration/migrate_all.py --user admin --password admin123 --dry-run
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse

# Import the single-job converter
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from convert_annotation_coords import (
    get_cvat_session,
    fetch_job_dimensions,
    convert_annotations,
    upload_annotations,
)


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
    """Export annotations from a CVAT job as CVAT 1.1 XML.

    Uses the new dataset export API:
      POST /api/jobs/{id}/dataset/export?save_images=False&format=...
    """
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

    # Poll for completion
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


def is_zip_file(path: str) -> bool:
    """Check if file starts with ZIP magic bytes."""
    with open(path, 'rb') as f:
        return f.read(4) == b'PK\x03\x04'


def extract_xml_from_zip(zip_path: str, output_dir: str) -> str:
    """Extract the first XML file from a ZIP archive."""
    import zipfile
    with zipfile.ZipFile(zip_path, 'r') as zf:
        xml_files = [n for n in zf.namelist() if n.endswith('.xml')]
        if not xml_files:
            raise RuntimeError(f'No XML files found in ZIP: {zip_path}')
        xml_name = xml_files[0]
        zf.extract(xml_name, output_dir)
        return os.path.join(output_dir, xml_name)


def main():
    parser = argparse.ArgumentParser(
        description='Batch migrate ALL jobs annotation coordinates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--server', default='http://localhost:8080',
                        help='CVAT server URL (default: http://localhost:8080)')
    parser.add_argument('--user', required=True, help='CVAT username')
    parser.add_argument('--password', required=True, help='CVAT password')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be converted without uploading')
    parser.add_argument('--job-ids', type=str, default=None,
                        help='Comma-separated job IDs to process (default: all)')
    args = parser.parse_args()

    opener, csrf_token = get_cvat_session(
        args.server, None, args.user, args.password,
    )

    # Get all jobs
    print('Fetching all jobs...')
    all_jobs = list_all_jobs(args.server, opener, csrf_token)
    print(f'Found {len(all_jobs)} jobs total')

    # Filter if specific job IDs requested
    if args.job_ids:
        target_ids = set(int(x.strip()) for x in args.job_ids.split(','))
        all_jobs = [j for j in all_jobs if j['id'] in target_ids]
        print(f'Filtered to {len(all_jobs)} jobs: {sorted(target_ids)}')

    results = {'converted': [], 'skipped': [], 'failed': []}

    for job in all_jobs:
        job_id = job['id']
        task_id = job.get('task_id', '?')
        task_name = ''

        # Fetch task name
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
            # Get actual video dimensions
            target_w, target_h = fetch_job_dimensions(
                args.server, job_id, opener, csrf_token,
            )
            print(f'  Actual video dimensions: {target_w}x{target_h}')

            # Export annotations
            with tempfile.TemporaryDirectory() as tmpdir:
                export_path = os.path.join(tmpdir, f'job_{job_id}_export.xml')
                print(f'  Exporting annotations...')
                export_job_annotations(
                    args.server, job_id, export_path, opener, csrf_token,
                )

                # Handle ZIP format (CVAT exports as ZIP)
                if is_zip_file(export_path):
                    xml_path = extract_xml_from_zip(export_path, tmpdir)
                else:
                    xml_path = export_path

                # Check file size
                file_size = os.path.getsize(xml_path)
                if file_size < 50:
                    print(f'  Skipping: exported file too small ({file_size} bytes, likely empty)')
                    results['skipped'].append({
                        'job_id': job_id, 'task': task_name,
                        'reason': 'empty annotations',
                    })
                    continue

                # Convert
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
                          f'from {stats["src"]} → {stats["dst"]}')
                    results['converted'].append({
                        'job_id': job_id, 'task': task_name,
                        'stats': stats, 'dry_run': True,
                    })
                else:
                    # Upload converted annotations
                    print(f'  Uploading converted annotations...')
                    upload_annotations(
                        args.server, job_id, converted_path, opener, csrf_token,
                    )
                    print(f'  Done: {stats["boxes"]} boxes '
                          f'from {stats["src"]} → {stats["dst"]}')
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

    # Summary
    print(f'\n{"="*60}')
    print('MIGRATION SUMMARY')
    print(f'{"="*60}')
    print(f'Converted: {len(results["converted"])} jobs')
    for r in results['converted']:
        dry = ' [DRY-RUN]' if r.get('dry_run') else ''
        print(f'  Job {r["job_id"]} ({r["task"]}): '
              f'{r["stats"]["boxes"]} boxes {r["stats"]["src"]} → {r["stats"]["dst"]}{dry}')
    print(f'Skipped:   {len(results["skipped"])} jobs')
    for r in results['skipped']:
        print(f'  Job {r["job_id"]} ({r["task"]}): {r["reason"]}')
    if results['failed']:
        print(f'Failed:    {len(results["failed"])} jobs')
        for r in results['failed']:
            print(f'  Job {r["job_id"]} ({r["task"]}): {r["error"]}')

    return 0 if not results['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
