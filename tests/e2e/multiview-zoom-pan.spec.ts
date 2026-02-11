import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getZoomScale } from './helpers';

test.describe('6. Zoom & Pan', () => {
    test.use({ storageState: STORAGE_STATE });

    test('mouse wheel zooms in and out', async ({ page }) => {
        await openMultiviewJob(page);

        const container = page.locator('.video-canvas-container').first();
        const box = await container.boundingBox();
        expect(box).not.toBeNull();

        const cx = box!.x + box!.width / 2;
        const cy = box!.y + box!.height / 2;

        const initialScale = await getZoomScale(page);

        // Scroll up to zoom in
        await page.mouse.move(cx, cy);
        await page.mouse.wheel(0, -300);
        await page.waitForTimeout(500);

        const zoomedScale = await getZoomScale(page);
        console.log(`Zoom: initial=${initialScale}, zoomed=${zoomedScale}`);
        expect(zoomedScale).toBeGreaterThan(initialScale);
    });

    test('bbox stays aligned after zoom in and out', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const before = await shape.boundingBox();
        expect(before).not.toBeNull();

        const container = page.locator('.video-canvas-container').first();
        const cBox = await container.boundingBox();
        const cx = cBox!.x + cBox!.width / 2;
        const cy = cBox!.y + cBox!.height / 2;

        // Zoom in
        await page.mouse.move(cx, cy);
        await page.mouse.wheel(0, -300);
        await page.waitForTimeout(500);

        // Zoom back out
        await page.mouse.wheel(0, 300);
        await page.waitForTimeout(500);

        const after = await shape.boundingBox();
        expect(after).not.toBeNull();

        const dx = Math.abs((before!.x + before!.width / 2) - (after!.x + after!.width / 2));
        const dy = Math.abs((before!.y + before!.height / 2) - (after!.y + after!.height / 2));
        console.log(`Zoom round-trip: dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        expect(dx).toBeLessThanOrEqual(5);
        expect(dy).toBeLessThanOrEqual(5);
    });

    test('double-click does not reset zoom (dblclick blocked)', async ({ page }) => {
        await openMultiviewJob(page);

        const container = page.locator('.video-canvas-container').first();
        const cBox = await container.boundingBox();
        const cx = cBox!.x + cBox!.width / 2;
        const cy = cBox!.y + cBox!.height / 2;

        // Zoom in first
        await page.mouse.move(cx, cy);
        await page.mouse.wheel(0, -500);
        await page.waitForTimeout(500);

        const zoomedScale = await getZoomScale(page);
        expect(zoomedScale).toBeGreaterThan(1);

        // Double-click should NOT reset zoom (dblclick is blocked to prevent
        // canvasView.ts focus()/fit() from corrupting SVG geometry)
        await page.mouse.dblclick(cx, cy);
        await page.waitForTimeout(500);

        const afterScale = await getZoomScale(page);
        console.log(`Zoom dblclick blocked: zoomed=${zoomedScale.toFixed(2)}, after dblclick=${afterScale.toFixed(2)}`);
        expect(afterScale).toBe(zoomedScale);
    });
});
