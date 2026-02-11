import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getShapeCount, clickViewButton, waitForCanvas } from './helpers';

test.describe('Annotation CRUD', () => {
    test.use({ storageState: STORAGE_STATE });

    test('create annotation: draw rectangle, save, refresh, verify', async ({ page }) => {
        await openMultiviewJob(page);

        const countBefore = await getShapeCount(page);

        // Click the rectangle draw control icon to open the draw popover
        await page.locator('.cvat-draw-rectangle-control').first().click();
        await page.waitForTimeout(500);

        // Click "Shape" button in the popover to enter draw mode
        await page.locator('.cvat-draw-rectangle-shape-button').first().click();
        await page.waitForTimeout(500);

        // Find the canvas wrapper and draw inside it
        const canvasWrapper = page.locator('#cvat_canvas_wrapper').first();
        const wBox = await canvasWrapper.boundingBox();
        expect(wBox).not.toBeNull();

        // CVAT draws rectangles with TWO CLICKS (not drag):
        // First click = start corner, second click = end corner
        const startX = wBox!.x + wBox!.width * 0.4;
        const startY = wBox!.y + wBox!.height * 0.5;
        const endX = startX + 100;
        const endY = startY + 70;

        // First click - start point
        await page.mouse.click(startX, startY);
        await page.waitForTimeout(300);

        // Move to end point (shows preview)
        await page.mouse.move(endX, endY, { steps: 5 });
        await page.waitForTimeout(300);

        // Second click - complete the rectangle
        await page.mouse.click(endX, endY);
        await page.waitForTimeout(1500);

        const countAfterDraw = await getShapeCount(page);
        console.log(`Create: before=${countBefore}, afterDraw=${countAfterDraw}`);
        expect(countAfterDraw).toBeGreaterThanOrEqual(countBefore + 1);

        // Exit draw mode and save
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
        await page.keyboard.press('Control+s');
        await page.waitForTimeout(2000);

        // Refresh and verify persistence
        await page.reload({ waitUntil: 'domcontentloaded' });
        await openMultiviewJob(page);

        const countAfterRefresh = await getShapeCount(page);
        console.log(`Create persistence: afterRefresh=${countAfterRefresh}`);
        expect(countAfterRefresh).toBe(countAfterDraw);
    });

    test('delete annotation: select, delete key, verify removal', async ({ page }) => {
        await openMultiviewJob(page);

        const countBefore = await getShapeCount(page);
        expect(countBefore).toBeGreaterThan(0);

        // Click a shape to select it
        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const sBox = await shape.boundingBox();
        expect(sBox).not.toBeNull();

        await page.mouse.click(sBox!.x + sBox!.width / 2, sBox!.y + sBox!.height / 2);
        await page.waitForTimeout(500);

        // Delete
        await page.keyboard.press('Delete');
        await page.waitForTimeout(1000);

        const countAfterDelete = await getShapeCount(page);
        console.log(`Delete: before=${countBefore}, after=${countAfterDelete}`);
        expect(countAfterDelete).toBe(countBefore - 1);

        // Undo to restore (Ctrl+Z)
        await page.keyboard.press('Control+z');
        await page.waitForTimeout(1000);

        const countAfterUndo = await getShapeCount(page);
        expect(countAfterUndo).toBe(countBefore);
    });

    test('view-specific filtering: shape in View 1 not visible in View 3', async ({ page }) => {
        await openMultiviewJob(page);

        // Get shape IDs in View 1
        const view1Shapes = await page.evaluate(() =>
            Array.from(document.querySelectorAll('#cvat_canvas_content .cvat_canvas_shape'))
                .map((el) => el.id),
        );

        // Switch to View 3
        await clickViewButton(page, 3);
        await waitForCanvas(page);

        const view3Shapes = await page.evaluate(() =>
            Array.from(document.querySelectorAll('#cvat_canvas_content .cvat_canvas_shape'))
                .map((el) => el.id),
        );

        console.log(`View 1 shapes: [${view1Shapes.join(',')}], View 3 shapes: [${view3Shapes.join(',')}]`);

        // View 1 and View 3 should have completely different shapes
        const overlap = view1Shapes.filter((id) => view3Shapes.includes(id));
        expect(overlap.length).toBe(0);
    });
});
