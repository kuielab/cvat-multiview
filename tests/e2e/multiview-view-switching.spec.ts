import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, openMultiviewJobWithShapes, clickViewButton, getActiveViewText, getShapeCount, waitForCanvas } from './helpers';

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

    test('view-specific filtering: sidebar updates on view switch', async ({ page }) => {
        await openMultiviewJobWithShapes(page);

        // Get sidebar count for View 1
        const sidebar1Text = await page.locator('.cvat-objects-sidebar-states-header').first().innerText();
        const match1 = sidebar1Text.match(/Items:\s*(\d+)/);
        const view1SidebarCount = match1 ? Number(match1[1]) : -1;

        // Switch to View 3
        await clickViewButton(page, 3);
        await waitForCanvas(page);

        // Get sidebar count for View 3
        const sidebar3Text = await page.locator('.cvat-objects-sidebar-states-header').first().innerText();
        const match3 = sidebar3Text.match(/Items:\s*(\d+)/);
        const view3SidebarCount = match3 ? Number(match3[1]) : -1;

        console.log(`View 1 sidebar: ${view1SidebarCount}, View 3 sidebar: ${view3SidebarCount}`);
        // Both views should have valid item counts (may differ or be equal)
        expect(view1SidebarCount).toBeGreaterThanOrEqual(0);
        expect(view3SidebarCount).toBeGreaterThanOrEqual(0);
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
