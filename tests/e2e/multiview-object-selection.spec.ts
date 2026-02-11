import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob } from './helpers';

test.describe('7. Object Selection', () => {
    test.use({ storageState: STORAGE_STATE });

    test('clicking a shape activates it', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        await expect(shape).toBeVisible();

        const box = await shape.boundingBox();
        expect(box).not.toBeNull();

        await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
        await page.waitForTimeout(500);

        const selectedShape = await page.evaluate(() => !!document.querySelector('.cvat_canvas_shape_activated'));
        console.log(`Shape selected: ${selectedShape}`);
        expect(selectedShape).toBe(true);
    });

    test('clicking different shapes changes activation', async ({ page }) => {
        await openMultiviewJob(page);

        const shapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
        const count = await shapes.count();
        expect(count).toBeGreaterThanOrEqual(2);

        // Click first shape
        const box1 = await shapes.nth(0).boundingBox();
        await page.mouse.click(box1!.x + box1!.width / 2, box1!.y + box1!.height / 2);
        await page.waitForTimeout(300);
        const first = await page.evaluate(() => document.querySelector('.cvat_canvas_shape_activated')?.id);

        // Click second shape
        const box2 = await shapes.nth(1).boundingBox();
        await page.mouse.click(box2!.x + box2!.width / 2, box2!.y + box2!.height / 2);
        await page.waitForTimeout(300);
        const second = await page.evaluate(() => document.querySelector('.cvat_canvas_shape_activated')?.id);

        console.log(`Selection change: first=${first}, second=${second}`);
        expect(first).toBeTruthy();
        expect(second).toBeTruthy();
        expect(second).not.toBe(first);
    });
});
