import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob } from './helpers';

test.describe('8. Resize & Window Layout', () => {
    test.use({ storageState: STORAGE_STATE });

    test('bbox stays aligned after window resize', async ({ page }) => {
        await openMultiviewJob(page);

        const shape = page.locator('#cvat_canvas_content .cvat_canvas_shape').first();
        const before = await shape.boundingBox();
        expect(before).not.toBeNull();

        // Resize viewport
        await page.setViewportSize({ width: 1200, height: 800 });
        await page.waitForTimeout(1500);

        // Resize back
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.waitForTimeout(1500);

        const after = await shape.boundingBox();
        expect(after).not.toBeNull();

        const dx = Math.abs((before!.x + before!.width / 2) - (after!.x + after!.width / 2));
        const dy = Math.abs((before!.y + before!.height / 2) - (after!.y + after!.height / 2));
        console.log(`Resize round-trip: dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        // Allow some tolerance due to responsive layout recalc
        expect(dx).toBeLessThanOrEqual(10);
        expect(dy).toBeLessThanOrEqual(10);
    });

    test('collapse/expand sidebar keeps shapes visible', async ({ page }) => {
        await openMultiviewJob(page);

        const shapeBefore = await page.locator('#cvat_canvas_content .cvat_canvas_shape').count();
        expect(shapeBefore).toBeGreaterThan(0);

        // Click sidebar collapse button
        const collapseBtn = page.locator('[class*="menu-unfold"], [class*="menu-fold"]').first();
        if (await collapseBtn.isVisible()) {
            await collapseBtn.click();
            await page.waitForTimeout(1000);

            const shapeAfterCollapse = await page.locator('#cvat_canvas_content .cvat_canvas_shape').count();
            expect(shapeAfterCollapse).toBe(shapeBefore);

            // Expand back
            const expandBtn = page.locator('[class*="menu-unfold"], [class*="menu-fold"]').first();
            if (await expandBtn.isVisible()) {
                await expandBtn.click();
                await page.waitForTimeout(1000);
            }

            const shapeAfterExpand = await page.locator('#cvat_canvas_content .cvat_canvas_shape').count();
            expect(shapeAfterExpand).toBe(shapeBefore);
        }
    });
});
