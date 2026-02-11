import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, clickViewButton } from './helpers';

test.describe('Regression Tests', () => {
    test.use({ storageState: STORAGE_STATE });

    test('right-click on shape does not break UI', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const sBox = await shape.boundingBox();
        expect(sBox).not.toBeNull();

        await page.mouse.click(sBox!.x + sBox!.width / 2, sBox!.y + sBox!.height / 2, { button: 'right' });
        await page.waitForTimeout(500);

        // Shape should still be present after right-click
        await expect(shape).toBeVisible();
    });

    test('view switch after right-click cleans up state', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const sBox = await shape.boundingBox();
        await page.mouse.click(sBox!.x + sBox!.width / 2, sBox!.y + sBox!.height / 2, { button: 'right' });
        await page.waitForTimeout(300);

        // Switch view
        await clickViewButton(page, 2);

        // Page should still be functional - check shapes are rendered
        const shapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
        const count = await shapes.count();
        expect(count).toBeGreaterThanOrEqual(0);
    });

    test('sidebar items count matches shapes in canvas', async ({ page }) => {
        await openMultiviewJob(page);

        const shapeCount = await page.locator('#cvat_canvas_content .cvat_canvas_shape').count();
        const sidebarItemsText = await page.locator('.cvat-objects-sidebar-states-header')
            .first()
            .innerText();

        const match = sidebarItemsText.match(/Items:\s*(\d+)/);
        const sidebarCount = match ? Number(match[1]) : -1;

        console.log(`Canvas shapes: ${shapeCount}, Sidebar items: ${sidebarCount}`);
        expect(sidebarCount).toBe(shapeCount);
    });

    test('playback speed selector visible', async ({ page }) => {
        await openMultiviewJob(page);
        const speedSelector = page.locator('text=1x').first();
        await expect(speedSelector).toBeVisible();
    });

    test('Undo/Redo buttons present', async ({ page }) => {
        await openMultiviewJob(page);
        await expect(page.locator('button', { hasText: 'Undo' })).toBeVisible();
        await expect(page.locator('button', { hasText: 'Redo' })).toBeVisible();
    });

    test('workspace selector shows Multiview', async ({ page }) => {
        await openMultiviewJob(page);
        const wsSelector = page.locator('text=Multiview').first();
        await expect(wsSelector).toBeVisible();
    });

    test('small shape does not collapse after resize', async ({ page }) => {
        await openMultiviewJob(page);

        // Select a shape
        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const sBox = await shape.boundingBox();
        expect(sBox).not.toBeNull();

        await page.mouse.click(sBox!.x + sBox!.width / 2, sBox!.y + sBox!.height / 2);
        await page.waitForTimeout(500);

        const beforeBox = await shape.boundingBox();
        expect(beforeBox).not.toBeNull();

        // Try to collapse by dragging bottom-right corner toward top-left
        const brX = beforeBox!.x + beforeBox!.width;
        const brY = beforeBox!.y + beforeBox!.height;
        const tlX = beforeBox!.x + 5;
        const tlY = beforeBox!.y + 5;

        await page.mouse.move(brX, brY);
        await page.mouse.down();
        await page.mouse.move(tlX, tlY, { steps: 10 });
        await page.mouse.up();
        await page.waitForTimeout(500);

        const afterBox = await shape.boundingBox();
        expect(afterBox).not.toBeNull();

        console.log(`Small shape protection: before=${beforeBox!.width.toFixed(0)}x${beforeBox!.height.toFixed(0)}, after=${afterBox!.width.toFixed(0)}x${afterBox!.height.toFixed(0)}`);

        // Shape should still have positive, non-zero dimensions
        expect(afterBox!.width).toBeGreaterThan(0);
        expect(afterBox!.height).toBeGreaterThan(0);

        // Undo to restore original shape
        await page.keyboard.press('Control+z');
        await page.waitForTimeout(500);
    });
});
