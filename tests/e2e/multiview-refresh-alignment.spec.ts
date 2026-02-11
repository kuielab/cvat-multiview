import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob } from './helpers';

test.describe('1. Refresh Alignment', () => {
    test.use({ storageState: STORAGE_STATE });

    test('bbox center stays within 2px after single refresh', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        await expect(shape).toBeVisible();
        const before = await shape.boundingBox();
        expect(before).not.toBeNull();

        await page.reload({ waitUntil: 'domcontentloaded' });
        await openMultiviewJob(page);

        const shapeAfter = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        await expect(shapeAfter).toBeVisible();
        const after = await shapeAfter.boundingBox();
        expect(after).not.toBeNull();

        const dx = Math.abs((before!.x + before!.width / 2) - (after!.x + after!.width / 2));
        const dy = Math.abs((before!.y + before!.height / 2) - (after!.y + after!.height / 2));
        console.log(`Refresh alignment: dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        expect(dx).toBeLessThanOrEqual(2);
        expect(dy).toBeLessThanOrEqual(2);
    });

    test('bbox stable across 5 consecutive refreshes', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const initial = await shape.boundingBox();
        expect(initial).not.toBeNull();

        for (let i = 0; i < 5; i++) {
            await page.reload({ waitUntil: 'domcontentloaded' });
            await openMultiviewJob(page);
            const s = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
            const box = await s.boundingBox();
            expect(box).not.toBeNull();
            const dx = Math.abs((initial!.x + initial!.width / 2) - (box!.x + box!.width / 2));
            const dy = Math.abs((initial!.y + initial!.height / 2) - (box!.y + box!.height / 2));
            expect(dx, `refresh ${i + 1} dx`).toBeLessThanOrEqual(2);
            expect(dy, `refresh ${i + 1} dy`).toBeLessThanOrEqual(2);
        }
    });
});
