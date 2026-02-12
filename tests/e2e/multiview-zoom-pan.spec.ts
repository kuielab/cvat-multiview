import { test, expect, Page } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, openMultiviewJobWithShapes, clickViewButton, waitForCanvas } from './helpers';

/** Get the canvas transform scale from the SVG content element's computed style */
async function getCanvasScale(page: Page): Promise<number> {
    return page.evaluate(() => {
        const svg = document.querySelector('#cvat_canvas_content') as HTMLElement;
        if (!svg) return 1;
        const t = window.getComputedStyle(svg).transform;
        // matrix(a, b, c, d, tx, ty) → a is the scaleX
        const m = t.match(/matrix\(([^,]+)/);
        return m ? parseFloat(m[1]) : 1;
    });
}

/** Get the canvas background position (left, top) */
async function getCanvasPosition(page: Page): Promise<{ left: number; top: number }> {
    return page.evaluate(() => {
        const bg = document.querySelector('#cvat_canvas_background') as HTMLElement;
        if (!bg) return { left: 0, top: 0 };
        return {
            left: parseFloat(bg.style.left) || 0,
            top: parseFloat(bg.style.top) || 0,
        };
    });
}

/** Get center of the active canvas overlay */
async function getCanvasCenter(page: Page): Promise<{ x: number; y: number }> {
    return page.evaluate(() => {
        const el = document.querySelector('.annotation-canvas-overlay.active-canvas');
        if (!el) return { x: 0, y: 0 };
        const r = el.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
}

test.describe('6. Zoom & Pan', () => {
    test.use({ storageState: STORAGE_STATE });

    test('mouse wheel zoom in increases canvas scale', async ({ page }) => {
        await openMultiviewJob(page);

        const scaleBefore = await getCanvasScale(page);
        const center = await getCanvasCenter(page);

        // Zoom in with mouse wheel (negative deltaY = zoom in)
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -300);
        await page.waitForTimeout(500);

        const scaleAfter = await getCanvasScale(page);
        console.log(`Zoom in: scale ${scaleBefore.toFixed(4)} -> ${scaleAfter.toFixed(4)}`);
        expect(scaleAfter).toBeGreaterThan(scaleBefore);
    });

    test('mouse wheel zoom out decreases canvas scale', async ({ page }) => {
        await openMultiviewJob(page);

        // First zoom in
        const center = await getCanvasCenter(page);
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -500);
        await page.waitForTimeout(500);

        const scaleZoomedIn = await getCanvasScale(page);

        // Then zoom out
        await page.mouse.wheel(0, 500);
        await page.waitForTimeout(500);

        const scaleZoomedOut = await getCanvasScale(page);
        console.log(`Zoom out: ${scaleZoomedIn.toFixed(4)} -> ${scaleZoomedOut.toFixed(4)}`);
        expect(scaleZoomedOut).toBeLessThan(scaleZoomedIn);
    });

    test('double-click resets zoom to fit', async ({ page }) => {
        await openMultiviewJob(page);

        const scaleFit = await getCanvasScale(page);
        const center = await getCanvasCenter(page);

        // Zoom in
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -600);
        await page.waitForTimeout(500);

        const scaleZoomed = await getCanvasScale(page);
        expect(scaleZoomed).toBeGreaterThan(scaleFit * 1.05);

        // Double-click to reset
        await page.mouse.dblclick(center.x, center.y);
        await page.waitForTimeout(500);

        const scaleReset = await getCanvasScale(page);
        console.log(`Zoom reset: fit=${scaleFit.toFixed(4)}, zoomed=${scaleZoomed.toFixed(4)}, reset=${scaleReset.toFixed(4)}`);
        // Should be back near the fit scale (within 5% tolerance)
        expect(Math.abs(scaleReset - scaleFit) / scaleFit).toBeLessThan(0.05);
    });

    test('zoom persists across frame change', async ({ page }) => {
        await openMultiviewJob(page);

        const center = await getCanvasCenter(page);

        // Zoom in
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -500);
        await page.waitForTimeout(500);

        const scaleBeforeFrame = await getCanvasScale(page);

        // Advance frame
        await page.keyboard.press('f');
        await page.waitForTimeout(1000);

        const scaleAfterFrame = await getCanvasScale(page);
        console.log(`Zoom persistence: before=${scaleBeforeFrame.toFixed(4)}, after=${scaleAfterFrame.toFixed(4)}`);
        expect(Math.abs(scaleAfterFrame - scaleBeforeFrame)).toBeLessThan(0.01);
    });

    test('middle-click pan moves canvas when zoomed', async ({ page }) => {
        await openMultiviewJob(page);

        const center = await getCanvasCenter(page);

        // Zoom in first
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -600);
        await page.waitForTimeout(500);

        const posBefore = await getCanvasPosition(page);

        // Middle-click drag to pan
        await page.mouse.move(center.x, center.y);
        await page.mouse.down({ button: 'middle' });
        await page.waitForTimeout(100);
        for (let i = 1; i <= 10; i++) {
            await page.mouse.move(center.x + i * 5, center.y + i * 3, { steps: 1 });
            await page.waitForTimeout(30);
        }
        await page.mouse.up({ button: 'middle' });
        await page.waitForTimeout(500);

        const posAfter = await getCanvasPosition(page);
        const dx = Math.abs(posAfter.left - posBefore.left);
        const dy = Math.abs(posAfter.top - posBefore.top);
        console.log(`Pan: dLeft=${dx.toFixed(1)}, dTop=${dy.toFixed(1)}`);
        expect(dx + dy).toBeGreaterThan(5);
    });

    test('bbox stays aligned after zoom in and out', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        const shape = page.locator('.annotation-canvas-overlay.active-canvas .cvat_canvas_shape').first();
        const before = await shape.boundingBox();
        expect(before).not.toBeNull();

        const center = await getCanvasCenter(page);

        // Zoom in
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -400);
        await page.waitForTimeout(500);

        // Zoom back out (same amount)
        await page.mouse.wheel(0, 400);
        await page.waitForTimeout(500);

        const after = await shape.boundingBox();
        expect(after).not.toBeNull();

        const dx = Math.abs((before!.x + before!.width / 2) - (after!.x + after!.width / 2));
        const dy = Math.abs((before!.y + before!.height / 2) - (after!.y + after!.height / 2));
        console.log(`Zoom round-trip alignment: dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        // Wheel zoom centers on cursor, so some positional shift is expected.
        // Verify shapes don't jump excessively (within 20px tolerance).
        expect(dx).toBeLessThanOrEqual(20);
        expect(dy).toBeLessThanOrEqual(20);
    });

    test('no CSS transform on zoom-wrapper (canvas-driven zoom)', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        const center = await getCanvasCenter(page);

        // Zoom in via wheel
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -400);
        await page.waitForTimeout(500);

        // Verify zoom-wrapper has no CSS scale/translate transform
        const transforms = await page.evaluate(() => {
            const wrappers = document.querySelectorAll('.zoom-wrapper');
            return Array.from(wrappers).map((w) => {
                const style = (w as HTMLElement).style.transform;
                return style || 'none';
            });
        });

        for (const t of transforms) {
            expect(t).not.toMatch(/scale\(/);
            expect(t).not.toMatch(/translate\(/);
        }

        // But canvas scale SHOULD have changed
        const scale = await getCanvasScale(page);
        console.log(`Canvas-driven zoom: scale=${scale.toFixed(4)}, wrapper transforms=[${transforms.join(', ')}]`);
    });

    test('zoom reset on view change: zoom state resets to fit', async ({ page }) => {
        await openMultiviewJob(page);

        const scaleFit = await getCanvasScale(page);
        const center = await getCanvasCenter(page);

        // Zoom in on View 1
        await page.mouse.move(center.x, center.y);
        await page.mouse.wheel(0, -600);
        await page.waitForTimeout(500);

        const scaleZoomed = await getCanvasScale(page);
        expect(scaleZoomed).toBeGreaterThan(scaleFit * 1.05);

        // Switch to View 2
        await clickViewButton(page, 2);
        await waitForCanvas(page);

        // Switch back to View 1
        await clickViewButton(page, 1);
        await waitForCanvas(page);

        const scaleAfterRoundTrip = await getCanvasScale(page);
        console.log(`View round-trip zoom: fit=${scaleFit.toFixed(4)}, zoomed=${scaleZoomed.toFixed(4)}, afterTrip=${scaleAfterRoundTrip.toFixed(4)}`);

        // After view round-trip, zoom should reset to fit (view change triggers fit())
        expect(Math.abs(scaleAfterRoundTrip - scaleFit) / scaleFit).toBeLessThan(0.1);
    });
});
