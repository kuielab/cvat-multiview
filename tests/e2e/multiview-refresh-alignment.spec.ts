import { test, expect, Page } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJobWithShapes, seekToFrame, FIRST_ANNOTATED_FRAME } from './helpers';

/** Get the center position of the first shape in the active canvas overlay */
async function getFirstShapeCenter(page: Page): Promise<{ x: number; y: number } | null> {
    const shape = page.locator('.annotation-canvas-overlay.active-canvas .cvat_canvas_shape').first();
    const box = await shape.boundingBox();
    if (!box) return null;
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test.describe('1. Refresh Alignment', () => {
    test.use({ storageState: STORAGE_STATE });

    test('bbox center stays within 2px after multiple page refreshes', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        // Record initial bbox center
        const initial = await getFirstShapeCenter(page);
        expect(initial).not.toBeNull();
        console.log(`Initial bbox center: (${initial!.x.toFixed(2)}, ${initial!.y.toFixed(2)})`);

        const REFRESH_COUNT = 5;
        let maxDx = 0;
        let maxDy = 0;

        for (let i = 1; i <= REFRESH_COUNT; i++) {
            await page.reload({ waitUntil: 'domcontentloaded' });
            await page.waitForSelector('.cvat-multiview-workspace', { state: 'visible', timeout: 30000 });
            await seekToFrame(page, FIRST_ANNOTATED_FRAME);
            await page.waitForSelector('#cvat_canvas_content .cvat_canvas_shape', { state: 'attached', timeout: 15000 });
            await page.waitForTimeout(1000);

            const current = await getFirstShapeCenter(page);
            expect(current).not.toBeNull();

            const dx = Math.abs(current!.x - initial!.x);
            const dy = Math.abs(current!.y - initial!.y);
            maxDx = Math.max(maxDx, dx);
            maxDy = Math.max(maxDy, dy);
            console.log(`Refresh ${i}: center=(${current!.x.toFixed(2)}, ${current!.y.toFixed(2)}), dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        }

        console.log(`Max drift: dx=${maxDx.toFixed(2)}, dy=${maxDy.toFixed(2)}`);
        expect(maxDx).toBeLessThanOrEqual(2);
        expect(maxDy).toBeLessThanOrEqual(2);
    });

    test('bbox dimensions stay consistent after refresh', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        const shape = page.locator('.annotation-canvas-overlay.active-canvas .cvat_canvas_shape').first();
        const initial = await shape.boundingBox();
        expect(initial).not.toBeNull();
        console.log(`Initial bbox: ${initial!.width.toFixed(2)}x${initial!.height.toFixed(2)}`);

        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.waitForSelector('.cvat-multiview-workspace', { state: 'visible', timeout: 30000 });
        await seekToFrame(page, FIRST_ANNOTATED_FRAME);
        await page.waitForSelector('#cvat_canvas_content .cvat_canvas_shape', { state: 'attached', timeout: 15000 });
        await page.waitForTimeout(1000);

        const after = await shape.boundingBox();
        expect(after).not.toBeNull();

        const dw = Math.abs(after!.width - initial!.width);
        const dh = Math.abs(after!.height - initial!.height);
        console.log(`After refresh: ${after!.width.toFixed(2)}x${after!.height.toFixed(2)}, dw=${dw.toFixed(2)}, dh=${dh.toFixed(2)}`);

        expect(dw).toBeLessThanOrEqual(2);
        expect(dh).toBeLessThanOrEqual(2);
    });
});
