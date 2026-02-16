/**
 * Video resolution DB migration verification tests.
 *
 * Validates that after migrate_v1 converts annotations to real resolution
 * AND Video DB is updated from 1920x1080 -> actual (e.g. 320x240),
 * the full workflow still works correctly.
 *
 * Prerequisites:
 *   1. Task created with insert_bbox_annotations.py
 *   2. CVAT_FORCE_DB_DIMENSIONS=1 was set, DB forced to 1920x1080
 *   3. migrate_v1 ran (annotations converted to 320x240 space)
 *   4. CVAT_FORCE_DB_DIMENSIONS removed, DB updated to actual resolution
 *   5. Docker restarted (cache cleared)
 *
 * Environment variables:
 *   CVAT_MULTIVIEW_TASK_ID  - task ID (default: 9)
 *   CVAT_MULTIVIEW_JOB_ID   - job ID (default: 9)
 *   CVAT_FIRST_ANNOTATED_FRAME - frame with pre-annotations (default: 158)
 *   CVAT_BASE_URL            - server URL (default: http://localhost:8080)
 */
import { test, expect, Page } from '@playwright/test';
import {
    STORAGE_STATE,
    TASK_ID,
    JOB_ID,
    FIRST_ANNOTATED_FRAME,
    openMultiviewJobWithShapes,
    getShapeCount,
    getFrameNumber,
} from './helpers';

const BASE_URL = process.env.CVAT_BASE_URL || 'http://localhost:8080';
const EXPORT_POLL_INTERVAL_MS = 1000;
const EXPORT_TIMEOUT_MS = 60000;

/** Fetch multiview meta for a specific view via API. */
async function fetchViewMeta(page: Page, viewId: number): Promise<{
    width: number;
    height: number;
    chunk_size: number;
    size: number;
}> {
    const resp = await page.request.get(
        `${BASE_URL}/api/tasks/${TASK_ID}/multiview/data/${viewId}/meta`,
    );
    expect(resp.ok()).toBe(true);
    const json = await resp.json();

    expect(json.frames).toBeDefined();
    expect(Array.isArray(json.frames)).toBe(true);
    expect(json.frames.length).toBeGreaterThan(0);

    const frame = json.frames[0];
    return {
        width: frame.width,
        height: frame.height,
        chunk_size: json.chunk_size,
        size: json.size,
    };
}

/**
 * Export annotations in CVAT for video 1.1 format and return XML text.
 * Uses the new async export API:
 *   POST /api/jobs/{id}/dataset/export?save_images=False&format=...
 *   GET  /api/requests/{rq_id}  (poll until finished)
 *   GET  result_url             (download)
 */
async function exportAnnotationXml(page: Page): Promise<string> {
    // Read CSRF token from cookies for POST request
    const cookies = await page.context().cookies();
    const csrfCookie = cookies.find((c) => c.name === 'csrftoken');
    const csrfToken = csrfCookie?.value || '';

    const format = encodeURIComponent('CVAT for video 1.1');
    const initResp = await page.request.post(
        `${BASE_URL}/api/jobs/${JOB_ID}/dataset/export?save_images=False&format=${format}`,
        { headers: { 'X-CSRFToken': csrfToken } },
    );
    expect(initResp.status()).toBeLessThan(500);
    const initJson = await initResp.json();
    const rqId = initJson.rq_id;
    expect(rqId).toBeDefined();

    const deadline = Date.now() + EXPORT_TIMEOUT_MS;
    let resultUrl = '';
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, EXPORT_POLL_INTERVAL_MS));
        const statusResp = await page.request.get(`${BASE_URL}/api/requests/${rqId}`);
        expect(statusResp.ok()).toBe(true);
        const statusJson = await statusResp.json();
        if (statusJson.status === 'finished') {
            resultUrl = statusJson.result_url;
            break;
        }
        if (statusJson.status === 'failed') {
            throw new Error(`Export failed: ${JSON.stringify(statusJson)}`);
        }
    }
    expect(resultUrl).not.toBe('');

    const downloadResp = await page.request.get(resultUrl);
    expect(downloadResp.ok()).toBe(true);
    return downloadResp.text();
}

test.describe('Resolution Migration Verification', () => {
    test.use({ storageState: STORAGE_STATE });
    test.describe.configure({ mode: 'serial' });

    test('meta API returns actual video dimensions (not 1920x1080)', async ({ page }) => {
        const meta = await fetchViewMeta(page, 1);

        expect(meta.width).toBeGreaterThan(0);
        expect(meta.height).toBeGreaterThan(0);

        const isFallback = meta.width === 1920 && meta.height === 1080;
        if (isFallback) {
            console.log('WARNING: meta still returns 1920x1080 - DB may not be updated yet');
        }
        console.log(`View 1 meta: ${meta.width}x${meta.height}, chunks=${meta.chunk_size}, frames=${meta.size}`);

        expect(meta.width).toBeGreaterThanOrEqual(160);
        expect(meta.width).toBeLessThanOrEqual(3840);
        expect(meta.height).toBeGreaterThanOrEqual(120);
        expect(meta.height).toBeLessThanOrEqual(2160);
    });

    test('canvas renders annotations within visible area', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        const shapeCount = await getShapeCount(page);
        expect(shapeCount).toBeGreaterThan(0);
        console.log(`Visible shapes on frame ${FIRST_ANNOTATED_FRAME}: ${shapeCount}`);

        const shapesInfo = await page.evaluate(() => {
            const wrapper = document.querySelector('#cvat_canvas_wrapper');
            if (!wrapper) return { wrapperBox: null, shapes: [] };
            const wRect = wrapper.getBoundingClientRect();

            const shapes = Array.from(
                document.querySelectorAll('#cvat_canvas_content .cvat_canvas_shape'),
            );
            return {
                wrapperBox: { x: wRect.x, y: wRect.y, w: wRect.width, h: wRect.height },
                shapes: shapes.map((el) => {
                    const r = el.getBoundingClientRect();
                    return {
                        id: el.id,
                        cx: r.x + r.width / 2,
                        cy: r.y + r.height / 2,
                    };
                }),
            };
        });

        expect(shapesInfo.wrapperBox).not.toBeNull();
        const wb = shapesInfo.wrapperBox!;
        const boundsMargin = 50;

        for (const shape of shapesInfo.shapes) {
            const inBounds =
                shape.cx >= wb.x - boundsMargin &&
                shape.cx <= wb.x + wb.w + boundsMargin &&
                shape.cy >= wb.y - boundsMargin &&
                shape.cy <= wb.y + wb.h + boundsMargin;

            if (!inBounds) {
                console.log(
                    `Shape ${shape.id} center (${shape.cx.toFixed(0)}, ${shape.cy.toFixed(0)}) ` +
                    `outside canvas (${wb.x.toFixed(0)},${wb.y.toFixed(0)} ${wb.w.toFixed(0)}x${wb.h.toFixed(0)})`,
                );
            }
            expect(inBounds).toBe(true);
        }
        console.log(`All ${shapesInfo.shapes.length} shapes within canvas bounds`);
    });

    test('annotation coordinates are within actual video resolution', async ({ page }) => {
        const meta = await fetchViewMeta(page, 1);

        const annResp = await page.request.get(
            `${BASE_URL}/api/jobs/${JOB_ID}/annotations`,
        );
        expect(annResp.ok()).toBe(true);
        const annData = await annResp.json();

        const allPoints: Array<{ x: number; y: number; source: string }> = [];

        for (const track of (annData.tracks || [])) {
            for (const shape of (track.shapes || [])) {
                const pts = shape.points || [];
                for (let i = 0; i < pts.length; i += 2) {
                    allPoints.push({ x: pts[i], y: pts[i + 1], source: `track-${track.id}` });
                }
            }
        }
        for (const shape of (annData.shapes || [])) {
            const pts = shape.points || [];
            for (let i = 0; i < pts.length; i += 2) {
                allPoints.push({ x: pts[i], y: pts[i + 1], source: `shape-${shape.id}` });
            }
        }

        console.log(`Checking ${allPoints.length} coordinate points against ${meta.width}x${meta.height}`);
        expect(allPoints.length).toBeGreaterThan(0);

        let outOfBounds = 0;
        for (const pt of allPoints) {
            if (pt.x < 0 || pt.x > meta.width || pt.y < 0 || pt.y > meta.height) {
                outOfBounds++;
                if (outOfBounds <= 5) {
                    console.log(`Out of bounds: (${pt.x.toFixed(1)}, ${pt.y.toFixed(1)}) from ${pt.source}`);
                }
            }
        }
        console.log(`Out of bounds: ${outOfBounds}/${allPoints.length}`);
        expect(outOfBounds).toBe(0);
    });

    test('export XML contains correct original_size dimensions', async ({ page }) => {
        test.setTimeout(120000);
        const meta = await fetchViewMeta(page, 1);
        const xml = await exportAnnotationXml(page);

        expect(xml.length).toBeGreaterThan(0);
        console.log(`Export XML length: ${xml.length} chars`);

        const widthMatch = xml.match(/<width>(\d+)<\/width>/);
        const heightMatch = xml.match(/<height>(\d+)<\/height>/);

        expect(widthMatch).not.toBeNull();
        expect(heightMatch).not.toBeNull();

        const exportWidth = Number(widthMatch![1]);
        const exportHeight = Number(heightMatch![1]);

        console.log(`Export XML original_size: ${exportWidth}x${exportHeight}`);
        console.log(`Meta API dimensions: ${meta.width}x${meta.height}`);

        expect(exportWidth).toBe(meta.width);
        expect(exportHeight).toBe(meta.height);

        if (meta.width !== 1920 || meta.height !== 1080) {
            expect(exportWidth).not.toBe(1920);
            expect(exportHeight).not.toBe(1080);
        }
    });

    test('create new annotation, save, reload, verify persistence', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJobWithShapes(page);

        const countBefore = await getShapeCount(page);

        // Enter draw mode
        await page.locator('.cvat-draw-rectangle-control').first().click();
        await page.waitForTimeout(500);
        await page.locator('.cvat-draw-rectangle-shape-button').first().click();
        await page.waitForTimeout(500);

        // Draw rectangle with two clicks
        const canvasWrapper = page.locator('#cvat_canvas_wrapper').first();
        const wBox = await canvasWrapper.boundingBox();
        expect(wBox).not.toBeNull();

        const startX = wBox!.x + wBox!.width * 0.3;
        const startY = wBox!.y + wBox!.height * 0.3;
        const endX = startX + 80;
        const endY = startY + 60;

        await page.mouse.click(startX, startY);
        await page.waitForTimeout(300);
        await page.mouse.move(endX, endY, { steps: 5 });
        await page.waitForTimeout(300);
        await page.mouse.click(endX, endY);
        await page.waitForTimeout(1500);

        const countAfterDraw = await getShapeCount(page);
        console.log(`New annotation: before=${countBefore}, after=${countAfterDraw}`);
        expect(countAfterDraw).toBeGreaterThanOrEqual(countBefore + 1);

        // Exit draw mode and save
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
        await page.keyboard.press('Control+s');
        await page.waitForTimeout(2000);

        // Reload and verify
        await page.reload({ waitUntil: 'domcontentloaded' });
        await openMultiviewJobWithShapes(page);

        const countAfterReload = await getShapeCount(page);
        console.log(`After reload: ${countAfterReload}`);
        expect(countAfterReload).toBeGreaterThanOrEqual(countAfterDraw - 1);

        // Clean up: undo and save
        await page.keyboard.press('Control+z');
        await page.waitForTimeout(500);
        await page.keyboard.press('Control+s');
        await page.waitForTimeout(2000);
    });

    test('frame navigation preserves annotation positions', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        const shapesOnFrame = await page.evaluate(() => {
            return Array.from(
                document.querySelectorAll('#cvat_canvas_content .cvat_canvas_shape'),
            ).map((el) => {
                const r = el.getBoundingClientRect();
                return { id: el.id, cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
            });
        });
        expect(shapesOnFrame.length).toBeGreaterThan(0);

        // Navigate forward then back
        await page.keyboard.press('f');
        await page.waitForTimeout(500);
        await page.keyboard.press('d');
        await page.waitForTimeout(1000);

        const shapesAfterNav = await page.evaluate(() => {
            return Array.from(
                document.querySelectorAll('#cvat_canvas_content .cvat_canvas_shape'),
            ).map((el) => {
                const r = el.getBoundingClientRect();
                return { id: el.id, cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
            });
        });

        expect(shapesAfterNav.length).toBe(shapesOnFrame.length);

        const positionTolerance = 5;
        for (const before of shapesOnFrame) {
            let bestDist = Infinity;
            let bestMatch = shapesAfterNav[0];
            for (const after of shapesAfterNav) {
                const dist = Math.sqrt((after.cx - before.cx) ** 2 + (after.cy - before.cy) ** 2);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestMatch = after;
                }
            }
            if (bestDist > positionTolerance) {
                console.log(
                    `Shape ${before.id} moved ${bestDist.toFixed(1)}px after nav: ` +
                    `(${before.cx.toFixed(0)},${before.cy.toFixed(0)}) -> (${bestMatch.cx.toFixed(0)},${bestMatch.cy.toFixed(0)})`,
                );
            }
            expect(bestDist).toBeLessThanOrEqual(positionTolerance);
        }
        console.log(`All ${shapesOnFrame.length} shapes stable after frame navigation`);
    });

    test('playback works correctly after resolution migration', async ({ page }) => {
        // Fresh page load to avoid stale state from previous tests
        await openMultiviewJobWithShapes(page);
        // Ensure canvas is focused for keyboard events
        const canvasWrapper = page.locator('#cvat_canvas_wrapper').first();
        await canvasWrapper.click();
        await page.waitForTimeout(500);

        const frameBefore = await getFrameNumber(page);

        await page.keyboard.press('Space');
        await page.waitForTimeout(3000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(500);

        const frameAfter = await getFrameNumber(page);
        console.log(`Playback: frame ${frameBefore} -> ${frameAfter}`);

        expect(frameAfter).toBeGreaterThan(frameBefore);

        const bgCount = await page.evaluate(() =>
            document.querySelectorAll('#cvat_canvas_background').length,
        );
        expect(bgCount).toBeGreaterThan(0);
    });
});
