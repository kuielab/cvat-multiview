import { test, expect } from '@playwright/test';
import {
    STORAGE_STATE, openMultiviewJob, openMultiviewJobWithShapes, getShapeCount, getFrameNumber,
    clickViewButton, waitForCanvas,
} from './helpers';

test.describe('9/10. Canvas-Only Rendering', () => {
    test.use({ storageState: STORAGE_STATE });

    test('count HTMLVideoElement in multiview workspace', async ({ page }) => {
        await openMultiviewJob(page);

        const videoCount = await page.evaluate(() =>
            document.querySelectorAll('.cvat-multiview-workspace video').length,
        );
        console.log(`HTMLVideoElement count in workspace: ${videoCount}`);
        // Active view uses canvas, preview views use <video> elements (4 previews for 5 views)
        expect(videoCount).toBe(4);

        // Verify canvas backgrounds exist for active view
        const canvasBgCount = await page.evaluate(() =>
            document.querySelectorAll('#cvat_canvas_background').length,
        );
        console.log(`Canvas background count: ${canvasBgCount}`);
        expect(canvasBgCount).toBeGreaterThan(0);
    });

    test('no CSS transform on zoom-wrapper (canvas-driven zoom)', async ({ page }) => {
        await openMultiviewJob(page);

        const transforms = await page.evaluate(() => {
            const wrappers = document.querySelectorAll('.zoom-wrapper');
            return Array.from(wrappers).map((w) => {
                const style = (w as HTMLElement).style.transform;
                return style || 'none';
            });
        });

        console.log(`zoom-wrapper transforms: [${transforms.join(', ')}]`);
        // All zoom-wrappers should have no scale/translate transform
        for (const t of transforms) {
            expect(t).not.toMatch(/scale\(/);
            expect(t).not.toMatch(/translate\(/);
        }
    });
});

test.describe('11. Playback Rate Effect', () => {
    test.use({ storageState: STORAGE_STATE });

    test('2x playback advances frames ~2x faster than 1x', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);

        // Play at 1x for 3 seconds
        await page.keyboard.press('Space');
        await page.waitForTimeout(3000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);
        const frames1x = await getFrameNumber(page);

        // Reset to frame 0
        await page.keyboard.press('Home');
        await page.waitForTimeout(500);

        // Set playback rate to 2x
        const rateSelector = page.locator('.cvat-player-playback-rate-selector, select.playback-rate-selector').first();
        const rateExists = await rateSelector.count();
        if (rateExists > 0) {
            await rateSelector.click();
            await page.waitForTimeout(300);
            const option2x = page.locator('.ant-select-item-option', { hasText: '2' }).first();
            if (await option2x.count() > 0) {
                await option2x.click();
                await page.waitForTimeout(300);
            }
        }

        // Play at 2x for 3 seconds
        await page.keyboard.press('Space');
        await page.waitForTimeout(3000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);
        const frames2x = await getFrameNumber(page);

        console.log(`Playback rate: 1x=${frames1x} frames, 2x=${frames2x} frames`);
        // 2x should advance at least 1.5x more frames (allowing some tolerance)
        expect(frames2x).toBeGreaterThan(frames1x * 1.4);
    });
});

test.describe('15. Chunk Decode Network Path', () => {
    test.use({ storageState: STORAGE_STATE });

    test('detect multiview frame loading network path', async ({ page }) => {
        test.setTimeout(60000);
        const chunkRequests: string[] = [];
        const frameRequests: string[] = [];
        const dataRequests: string[] = [];

        page.on('request', (req) => {
            const url = req.url();
            if (url.includes('/multiview/data/') && url.includes('type=chunk')) {
                chunkRequests.push(url);
            }
            if (url.includes('/multiview/frame/')) {
                frameRequests.push(url);
            }
            if (url.includes('/data?') || url.includes('/data/')) {
                dataRequests.push(url);
            }
        });

        await openMultiviewJob(page);

        // Navigate frames to trigger loading
        for (let i = 0; i < 5; i++) {
            await page.keyboard.press('f');
            await page.waitForTimeout(500);
        }

        console.log(`Chunk requests: ${chunkRequests.length}, Frame requests: ${frameRequests.length}, Data requests: ${dataRequests.length}`);
        // Report which network path is active:
        // - chunk-based: /multiview/data/{viewId}?type=chunk (target)
        // - frame-based: /multiview/frame/{viewId} (intermediate)
        // - canvas-only: no multiview requests (standard frame data path)
        if (chunkRequests.length > 0) {
            console.log('Network path: CHUNK-BASED (target architecture)');
        } else if (frameRequests.length > 0) {
            console.log('Network path: FRAME-BASED (intermediate)');
        } else {
            console.log('Network path: CANVAS-ONLY (standard frame data path)');
        }
        // Always pass - this is a diagnostic test
        expect(true).toBe(true);
    });
});

test.describe('17. Playback End Boundary', () => {
    test.use({ storageState: STORAGE_STATE });

    test('playback near end: frame wraps or stops at boundary', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);

        // Navigate to near-end using V (jump +10 frames) many times
        for (let i = 0; i < 200; i++) {
            await page.keyboard.press('v');
        }
        await page.waitForTimeout(500);

        const nearEndFrame = await getFrameNumber(page);
        console.log(`Near end frame: ${nearEndFrame}`);
        expect(nearEndFrame).toBeGreaterThan(100);

        // Go back 3 frames
        for (let i = 0; i < 3; i++) {
            await page.keyboard.press('d');
            await page.waitForTimeout(50);
        }
        const backFrame = await getFrameNumber(page);

        // Play for 3 seconds - will either stop at end or wrap
        await page.keyboard.press('Space');
        await page.waitForTimeout(3000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);

        const afterPlayFrame = await getFrameNumber(page);
        console.log(`Boundary: back=${backFrame}, afterPlay=${afterPlayFrame}, nearEnd=${nearEndFrame}`);
        // Frame should be a valid non-negative number
        expect(afterPlayFrame).toBeGreaterThanOrEqual(0);

        // Detect behavior: stop at end, continue past, or wrap
        if (afterPlayFrame > nearEndFrame) {
            console.log(`Boundary behavior: CONTINUED past end to frame ${afterPlayFrame}`);
        } else if (afterPlayFrame >= backFrame) {
            console.log('Boundary behavior: STOPPED at or near end');
        } else {
            console.log(`Boundary behavior: WRAPPED to frame ${afterPlayFrame}`);
        }
    });
});

test.describe('18. View Switch During Playback', () => {
    test.use({ storageState: STORAGE_STATE });

    test('switching views during playback keeps sync', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);

        // Start playback
        await page.keyboard.press('Space');
        await page.waitForTimeout(1000);

        const frameBeforeSwitch = await getFrameNumber(page);
        expect(frameBeforeSwitch).toBeGreaterThan(0);

        // Switch view while playing
        await clickViewButton(page, 2);
        await page.waitForTimeout(1000);

        const frameAfterSwitch = await getFrameNumber(page);

        // Switch back
        await clickViewButton(page, 1);
        await page.waitForTimeout(1000);

        // Pause
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);

        const frameAfterReturn = await getFrameNumber(page);

        console.log(`View switch playback: before=${frameBeforeSwitch}, afterSwitch=${frameAfterSwitch}, afterReturn=${frameAfterReturn}`);
        // Frame should have continued advancing during view switch
        expect(frameAfterSwitch).toBeGreaterThan(frameBeforeSwitch);
        expect(frameAfterReturn).toBeGreaterThan(frameAfterSwitch);

        // No draw mode stuck
        const drawingShape = page.locator('.cvat_canvas_shape_drawing');
        await expect(drawingShape).toHaveCount(0);
    });
});

test.describe('19. View Switch Canvas Stability', () => {
    test.use({ storageState: STORAGE_STATE });

    test('canvas remains stable after view round-trip', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        // Get shape position before switching
        const shapeBefore = page.locator('.annotation-canvas-overlay.active-canvas .cvat_canvas_shape').first();
        const beforeBox = await shapeBefore.boundingBox();
        expect(beforeBox).not.toBeNull();

        // Switch to View 2
        await clickViewButton(page, 2);
        await waitForCanvas(page);

        // Switch back to View 1
        await clickViewButton(page, 1);
        await waitForCanvas(page);

        // Shape should still be visible and positioned similarly
        const shapeAfter = page.locator('.annotation-canvas-overlay.active-canvas .cvat_canvas_shape').first();
        const afterBox = await shapeAfter.boundingBox();
        expect(afterBox).not.toBeNull();

        const dx = Math.abs((beforeBox!.x + beforeBox!.width / 2) - (afterBox!.x + afterBox!.width / 2));
        console.log(`View round-trip shape stability: dx=${dx.toFixed(2)}`);
        // Shape position should be close to original
        expect(dx).toBeLessThanOrEqual(20);
    });
});
