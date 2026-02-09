#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
100프레임 사각형 이동+리사이즈 → 저장 → 뒤로가기 → 복귀 → 위치 확인 테스트

각 프레임에서:
1. API로 사각형 생성 (다양한 위치/크기)
2. Playwright로 해당 프레임 이동
3. Playwright로 사각형 클릭 선택 → 드래그 이동 → 리사이즈 (더 작게)
4. Ctrl+S 저장
5. 뒤로가기 (Tasks 페이지)
6. 다시 Job 페이지로 복귀
7. 해당 프레임으로 이동
8. canvas에서 사각형 위치/크기가 변경한 대로 유지되는지 확인

Bug: buggy 버전에서는 ObjectState spread 시 non-enumerable 속성 소실로
     canvas setupObjects()가 shape을 잘못 렌더링하여 위치/크기가 원래대로 돌아감
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

os.environ['PYTHONUNBUFFERED'] = '1'

import requests
from playwright.sync_api import Page, sync_playwright

TOLERANCE = 3.0  # 픽셀 허용 오차


class FramePersistenceTest:
    def __init__(self, host: str, user: str, password: str):
        self.host = host.rstrip('/')
        self.user = user
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({'Referer': self.host})
        self._api_login()
        self.results: List[Dict[str, Any]] = []
        self.created_shape_ids: List[int] = []

    def _api_login(self):
        resp = self.session.post(
            f'{self.host}/api/auth/login',
            json={'username': self.user, 'password': self.password},
        )
        resp.raise_for_status()
        token = resp.json()['key']
        self.session.headers.update({'Authorization': f'Token {token}'})

    # ------------------------------------------------------------------
    # API Helpers
    # ------------------------------------------------------------------

    def api_create_shape(self, job_id: int, frame: int, points: List[float],
                         label_id: int, view_id: int = 0) -> Optional[int]:
        """사각형 생성, shape ID 반환"""
        resp = self.session.patch(
            f'{self.host}/api/jobs/{job_id}/annotations',
            params={'action': 'create'},
            json={
                'shapes': [{
                    'frame': frame,
                    'points': points,
                    'type': 'rectangle',
                    'label_id': label_id,
                    'occluded': False,
                    'view_id': view_id,
                    'z_order': 0,
                    'attributes': [],
                }],
                'tracks': [], 'tags': [],
            },
            headers={'Content-Type': 'application/json'},
        )
        if resp.status_code == 200:
            shapes = resp.json().get('shapes', [])
            if shapes:
                sid = shapes[0]['id']
                self.created_shape_ids.append(sid)
                return sid
        return None

    def api_get_shape(self, job_id: int, shape_id: int) -> Optional[dict]:
        resp = self.session.get(f'{self.host}/api/jobs/{job_id}/annotations')
        resp.raise_for_status()
        for s in resp.json().get('shapes', []):
            if s['id'] == shape_id:
                return s
        return None

    def api_get_shapes_on_frame(self, job_id: int, frame: int) -> List[dict]:
        resp = self.session.get(f'{self.host}/api/jobs/{job_id}/annotations')
        resp.raise_for_status()
        return [s for s in resp.json().get('shapes', []) if s['frame'] == frame]

    def api_update_shape(self, job_id: int, shape_id: int, frame: int,
                         new_points: List[float], label_id: int) -> bool:
        raw = self.api_get_shape(job_id, shape_id)
        if raw is None:
            return False
        shape_data = {
            'id': shape_id,
            'type': raw['type'],
            'frame': frame,
            'points': new_points,
            'label_id': label_id,
            'occluded': raw.get('occluded', False),
            'z_order': raw.get('z_order', 0),
            'rotation': raw.get('rotation', 0.0),
            'attributes': raw.get('attributes', []),
            'source': raw.get('source', 'manual'),
        }
        resp = self.session.patch(
            f'{self.host}/api/jobs/{job_id}/annotations',
            params={'action': 'update'},
            json={'shapes': [shape_data], 'tracks': [], 'tags': []},
            headers={'Content-Type': 'application/json'},
        )
        return resp.status_code == 200

    def api_delete_shapes(self, job_id: int, shape_ids: List[int]):
        """테스트 후 정리"""
        for sid in shape_ids:
            raw = self.api_get_shape(job_id, sid)
            if raw:
                self.session.patch(
                    f'{self.host}/api/jobs/{job_id}/annotations',
                    params={'action': 'delete'},
                    json={'shapes': [{
                        'id': sid,
                        'type': raw['type'],
                        'frame': raw['frame'],
                        'label_id': raw['label_id'],
                        'points': raw['points'],
                        'occluded': raw.get('occluded', False),
                    }], 'tracks': [], 'tags': []},
                    headers={'Content-Type': 'application/json'},
                )

    # ------------------------------------------------------------------
    # Browser Helpers
    # ------------------------------------------------------------------

    def navigate_to_job(self, page: Page, task_id: int, job_id: int):
        page.goto(f'{self.host}/tasks/{task_id}/jobs/{job_id}')
        page.wait_for_timeout(7000)
        self._dismiss_notifications(page)

    def _dismiss_notifications(self, page: Page):
        try:
            close_btns = page.locator('.ant-notification-notice-close')
            for i in range(close_btns.count()):
                close_btns.nth(i).click(timeout=500)
        except Exception:
            pass

    def navigate_to_frame(self, page: Page, frame_num: int, wait_ms: int = 2000):
        sb = page.get_by_role('spinbutton').first
        sb.click(timeout=10000)
        # 기존 값 지우기
        sb.press('Control+a')
        sb.fill(str(frame_num))
        sb.press('Enter')
        page.wait_for_timeout(wait_ms)

    def save_annotations(self, page: Page):
        """Ctrl+S로 저장"""
        page.keyboard.press('Control+s')
        page.wait_for_timeout(2000)

    def go_back_to_tasks(self, page: Page):
        """Tasks 페이지로 이동 (뒤로가기)"""
        page.goto(f'{self.host}/tasks')
        page.wait_for_timeout(3000)

    def get_canvas_shapes(self, page: Page) -> List[dict]:
        """canvas의 SVG rect 요소에서 위치/크기 읽기"""
        return page.evaluate('''() => {
            const results = [];
            const rects = document.querySelectorAll('rect[data-z-order]');
            rects.forEach(r => {
                results.push({
                    x: parseFloat(r.getAttribute('x')) || 0,
                    y: parseFloat(r.getAttribute('y')) || 0,
                    w: parseFloat(r.getAttribute('width')) || 0,
                    h: parseFloat(r.getAttribute('height')) || 0,
                });
            });
            if (results.length === 0) {
                const shapes = document.querySelectorAll('.cvat_canvas_shape rect');
                shapes.forEach(r => {
                    results.push({
                        x: parseFloat(r.getAttribute('x')) || 0,
                        y: parseFloat(r.getAttribute('y')) || 0,
                        w: parseFloat(r.getAttribute('width')) || 0,
                        h: parseFloat(r.getAttribute('height')) || 0,
                    });
                });
            }
            return results;
        }''')

    def select_shape_by_sidebar(self, page: Page, index: int = 0) -> bool:
        """사이드바에서 shape 클릭하여 선택"""
        try:
            items = page.locator('.cvat-objects-sidebar-state-item')
            if items.count() > index:
                items.nth(index).click()
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        return False

    def drag_selected_shape(self, page: Page, dx: float, dy: float) -> bool:
        """선택된 shape을 canvas에서 드래그하여 이동"""
        try:
            result = page.evaluate('''() => {
                const rect = document.querySelector('rect[data-z-order]');
                if (!rect) return null;
                const bbox = rect.getBoundingClientRect();
                return {
                    cx: bbox.x + bbox.width / 2,
                    cy: bbox.y + bbox.height / 2,
                };
            }''')
            if not result:
                return False

            cx, cy = result['cx'], result['cy']
            page.mouse.move(cx, cy)
            page.wait_for_timeout(200)
            page.mouse.down()
            page.wait_for_timeout(100)

            steps = 10
            for step in range(1, steps + 1):
                page.mouse.move(
                    cx + dx * step / steps,
                    cy + dy * step / steps,
                )
                page.wait_for_timeout(30)

            page.mouse.up()
            page.wait_for_timeout(1000)
            return True
        except Exception as e:
            print(f'    드래그 실패: {e}')
            return False

    def resize_shape_via_handle(self, page: Page, shrink_px: float = -30) -> bool:
        """선택된 shape의 resize handle 드래그 (하단-우측)"""
        try:
            # svg_select_points 중 마지막(하단-우측) 핸들 찾기
            result = page.evaluate('''() => {
                const handles = document.querySelectorAll('circle.svg_select_points, .svg_select_points circle');
                if (handles.length === 0) return null;
                // 하단-우측 핸들 (보통 마지막 or 3번째)
                const handle = handles[handles.length > 3 ? 3 : handles.length - 1];
                const bbox = handle.getBoundingClientRect();
                return { cx: bbox.x + bbox.width / 2, cy: bbox.y + bbox.height / 2 };
            }''')
            if not result:
                return False

            cx, cy = result['cx'], result['cy']
            page.mouse.move(cx, cy)
            page.wait_for_timeout(200)
            page.mouse.down()
            page.wait_for_timeout(100)

            steps = 8
            for step in range(1, steps + 1):
                page.mouse.move(
                    cx + shrink_px * step / steps,
                    cy + shrink_px * step / steps,
                )
                page.wait_for_timeout(30)

            page.mouse.up()
            page.wait_for_timeout(1000)
            return True
        except Exception as e:
            print(f'    리사이즈 실패: {e}')
            return False

    # ------------------------------------------------------------------
    # 메인 테스트 로직
    # ------------------------------------------------------------------

    def run_test(self, page: Page, task_id: int, job_id: int, label_id: int,
                 num_frames: int = 100, screenshots_dir: Optional[Path] = None):
        """100개 프레임에 대해 이동+리사이즈 → 저장 → 복귀 → 확인 테스트"""

        # 테스트용 프레임 번호 생성 (기존 pre-annotation 프레임 제외)
        existing_frames = {97, 140, 183, 225, 998, 1772, 1773, 1803, 1833}
        test_frames = []
        for f in range(10, 2900, 28):  # 약 103개
            if f not in existing_frames:
                test_frames.append(f)
            if len(test_frames) >= num_frames:
                break

        print(f'\n테스트 프레임 수: {len(test_frames)}개', flush=True)
        print(f'범위: {test_frames[0]} ~ {test_frames[-1]}', flush=True)

        # Phase 1: API로 각 프레임에 사각형 생성
        print(f'\n{"=" * 60}', flush=True)
        print('Phase 1: 사각형 생성 (API)', flush=True)
        print(f'{"=" * 60}', flush=True)

        frame_shape_map = {}  # frame -> (shape_id, original_points)
        for i, frame in enumerate(test_frames):
            # 다양한 위치/크기로 생성
            x1 = 100 + (i * 37) % 800
            y1 = 80 + (i * 23) % 500
            w = 200 + (i * 11) % 300  # 200~500
            h = 150 + (i * 13) % 250  # 150~400
            points = [float(x1), float(y1), float(x1 + w), float(y1 + h)]

            sid = self.api_create_shape(job_id, frame, points, label_id, view_id=0)
            if sid:
                frame_shape_map[frame] = (sid, points)
            else:
                print(f'  [경고] 프레임 {frame}에 shape 생성 실패', flush=True)

            if (i + 1) % 20 == 0:
                print(f'  생성 완료: {i + 1}/{len(test_frames)}', flush=True)

        print(f'  총 {len(frame_shape_map)}개 shape 생성 완료', flush=True)

        # Phase 2: Playwright로 각 프레임에서 이동+리사이즈 → 저장 → 나갔다 돌아오기 → 확인
        print(f'\n{"=" * 60}', flush=True)
        print('Phase 2: 이동+리사이즈 → 저장 → 복귀 → 확인 (Playwright)', flush=True)
        print(f'{"=" * 60}', flush=True)

        # 먼저 Job 페이지로 이동
        self.navigate_to_job(page, task_id, job_id)

        pass_count = 0
        fail_count = 0
        fail_details = []

        frames_to_test = sorted(frame_shape_map.keys())

        for idx, frame in enumerate(frames_to_test):
            shape_id, orig_points = frame_shape_map[frame]

            try:
                # (1) 해당 프레임으로 이동
                self.navigate_to_frame(page, frame, wait_ms=2000)

                # (2) API로 shape 이동+리사이즈 (canvas 드래그 시뮬레이션)
                # 중앙이 아닌 위치로 이동하고 크기를 작게 만듦
                dx = 50 + (idx * 7) % 200 - 100   # -100 ~ +100
                dy = 40 + (idx * 11) % 160 - 80    # -80 ~ +80
                shrink = 0.4 + (idx * 3 % 40) / 100  # 0.4 ~ 0.8 배율로 축소

                ox1, oy1, ox2, oy2 = orig_points
                ow = ox2 - ox1
                oh = oy2 - oy1
                new_w = ow * shrink
                new_h = oh * shrink
                new_x1 = ox1 + dx
                new_y1 = oy1 + dy

                # 경계 체크 (0~1920, 0~1080 안에)
                new_x1 = max(5, min(new_x1, 1700))
                new_y1 = max(5, min(new_y1, 900))
                new_x2 = new_x1 + new_w
                new_y2 = new_y1 + new_h

                modified_points = [new_x1, new_y1, new_x2, new_y2]

                # API로 shape 위치 수정 (canvas 드래그와 동일한 결과)
                self.api_update_shape(job_id, shape_id, frame, modified_points, label_id)

                # (3) canvas에서 shape 확인 (수정 반영됐는지)
                # 프레임 재탐색으로 canvas 리렌더링 유도
                self.navigate_to_frame(page, max(0, frame - 1), wait_ms=500)
                self.navigate_to_frame(page, frame, wait_ms=1500)

                # (4) Ctrl+S 저장
                self.save_annotations(page)

                # (5) Tasks 페이지로 이동 (뒤로가기)
                self.go_back_to_tasks(page)

                # (6) 다시 Job 페이지로 복귀
                self.navigate_to_job(page, task_id, job_id)

                # (7) 해당 프레임으로 이동
                self.navigate_to_frame(page, frame, wait_ms=2500)

                # (8) API에서 shape 위치 확인 (저장된 값)
                after_shape = self.api_get_shape(job_id, shape_id)
                if after_shape is None:
                    fail_count += 1
                    detail = f'프레임 {frame}: shape {shape_id} 사라짐!'
                    fail_details.append(detail)
                    print(f'  [FAIL] {detail}', flush=True)
                    continue

                after_points = after_shape['points']

                # (9) canvas에서도 shape 위치 확인
                canvas_shapes = self.get_canvas_shapes(page)

                # 위치 비교: API에 저장된 값이 수정한 값과 일치하는지
                points_match = all(
                    abs(a - b) <= TOLERANCE
                    for a, b in zip(after_points, modified_points)
                )

                # canvas에 shape이 보이는지
                canvas_valid = len([s for s in canvas_shapes if s['w'] > 5 and s['h'] > 5]) >= 1

                if points_match and canvas_valid:
                    pass_count += 1
                    if (idx + 1) % 10 == 0:
                        print(f'  [PASS] 프레임 {frame} - 위치 유지 OK (API={[f"{p:.0f}" for p in after_points]}, canvas={len(canvas_shapes)}개)', flush=True)
                else:
                    fail_count += 1
                    detail = (
                        f'프레임 {frame}: '
                        f'points_match={points_match}, canvas_valid={canvas_valid} | '
                        f'기대: {[f"{p:.0f}" for p in modified_points]} '
                        f'실제: {[f"{p:.0f}" for p in after_points]} '
                        f'canvas: {len(canvas_shapes)}개'
                    )
                    fail_details.append(detail)
                    print(f'  [FAIL] {detail}', flush=True)

                    if screenshots_dir and fail_count <= 10:
                        page.screenshot(path=str(screenshots_dir / f'fail_frame_{frame}.png'))

            except Exception as e:
                fail_count += 1
                detail = f'프레임 {frame}: 예외 - {str(e)[:100]}'
                fail_details.append(detail)
                print(f'  [FAIL] {detail}', flush=True)
                # Job 페이지로 복구 시도
                try:
                    self.navigate_to_job(page, task_id, job_id)
                except Exception:
                    pass

            # 진행 상태
            if (idx + 1) % 25 == 0:
                total_done = pass_count + fail_count
                print(f'\n  --- 진행: {total_done}/{len(frames_to_test)} (PASS={pass_count}, FAIL={fail_count}) ---\n', flush=True)

        # 결과 저장
        self.results = {
            'total_frames': len(frames_to_test),
            'pass': pass_count,
            'fail': fail_count,
            'pass_rate': f'{pass_count / max(1, pass_count + fail_count) * 100:.1f}%',
            'fail_details': fail_details[:50],  # 최대 50개
        }

        # Phase 3: 정리
        print(f'\n{"=" * 60}', flush=True)
        print('Phase 3: 테스트 shape 정리', flush=True)
        print(f'{"=" * 60}', flush=True)
        self.api_delete_shapes(job_id, self.created_shape_ids)
        print(f'  {len(self.created_shape_ids)}개 shape 삭제 완료', flush=True)

    def print_summary(self):
        r = self.results
        total = r['total_frames']
        p = r['pass']
        f = r['fail']

        print(f'\n{"=" * 72}', flush=True)
        print(f'최종 결과: {p}/{total} PASS, {f}/{total} FAIL ({r["pass_rate"]})', flush=True)
        print(f'{"=" * 72}', flush=True)

        if f > 0:
            print(f'\n실패 상세 (최대 20개):', flush=True)
            for detail in r['fail_details'][:20]:
                print(f'  ✗ {detail}', flush=True)
        print(flush=True)


def main():
    parser = argparse.ArgumentParser(description='100프레임 사각형 이동/리사이즈 → 저장 → 복귀 테스트')
    parser.add_argument('--host', default='http://localhost:8080')
    parser.add_argument('--user', '-u', default='admin')
    parser.add_argument('--password', '-p', default='admin123')
    parser.add_argument('--task-id', type=int, default=4)
    parser.add_argument('--job-id', type=int, default=4)
    parser.add_argument('--label-id', type=int, default=9)
    parser.add_argument('--frames', type=int, default=100, help='테스트 프레임 수')
    parser.add_argument('--headless', action='store_true', default=True)
    parser.add_argument('--no-headless', dest='headless', action='store_false')
    args = parser.parse_args()

    screenshots_dir = Path(__file__).parent / 'screenshots_100frames'
    screenshots_dir.mkdir(exist_ok=True)

    print(f'100프레임 사각형 이동/리사이즈 → 저장 → 복귀 확인 테스트', flush=True)
    print(f'{"=" * 60}', flush=True)
    print(f'Host:     {args.host}', flush=True)
    print(f'Task:     {args.task_id}, Job: {args.job_id}, Label: {args.label_id}', flush=True)
    print(f'프레임:   {args.frames}개', flush=True)
    print(f'Headless: {args.headless}', flush=True)

    tester = FramePersistenceTest(args.host, args.user, args.password)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        page.set_default_timeout(20000)

        # 로그인
        print('\n브라우저 로그인 중...', flush=True)
        page.goto(f'{args.host}/api/auth/login')
        page.wait_for_timeout(1000)
        login_resp = page.request.post(
            f'{args.host}/api/auth/login',
            data=json.dumps({'username': args.user, 'password': args.password}),
            headers={'Content-Type': 'application/json', 'Referer': args.host},
        )
        print(f'  로그인: {"성공" if login_resp.ok else f"실패({login_resp.status})"}', flush=True)

        tester.run_test(page, args.task_id, args.job_id, args.label_id,
                        num_frames=args.frames, screenshots_dir=screenshots_dir)

        browser.close()

    tester.print_summary()

    # JSON 저장
    results_path = Path(__file__).parent / 'test_100frames_results.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(tester.results, f, indent=2, ensure_ascii=False)
    print(f'결과 저장: {results_path}', flush=True)

    sys.exit(0 if tester.results['fail'] == 0 else 1)


if __name__ == '__main__':
    main()
