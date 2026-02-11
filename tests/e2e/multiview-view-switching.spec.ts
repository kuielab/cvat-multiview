import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, clickViewButton, getActiveViewText, getShapeCount, waitForCanvas } from './helpers';

test.describe('2. View Switching', () => {
    test.use({ storageState: STORAGE_STATE });

    test('switching views updates active indicator', async ({ page }) => {
        await openMultiviewJob(page);

        for (const viewId of [2, 3, 4, 5, 1]) {
            await clickViewButton(page, viewId);
            const text = await getActiveViewText(page);
            expect(text).toContain(`View ${viewId}`);
        }
    });

    test('view-specific filtering: shapes differ per view', async ({ page }) => {
        await openMultiviewJob(page);

        // View 1 (default) shape count
        const view1Count = await getShapeCount(page);

        // Switch to View 3
        await clickViewButton(page, 3);
        await waitForCanvas(page);
        const view3Count = await getShapeCount(page);

        console.log(`View 1 shapes: ${view1Count}, View 3 shapes: ${view3Count}`);
        expect(view1Count).toBeGreaterThan(view3Count);
    });

    test('rapid view switching does not leave stale draw mode', async ({ page }) => {
        await openMultiviewJob(page);

        for (let i = 0; i < 3; i++) {
            await clickViewButton(page, 2);
            await page.waitForTimeout(200);
            await clickViewButton(page, 1);
            await page.waitForTimeout(200);
        }

        // Should still be in normal mode, not draw mode
        const drawingShape = page.locator('.cvat_canvas_shape_drawing');
        await expect(drawingShape).toHaveCount(0);
    });
});
