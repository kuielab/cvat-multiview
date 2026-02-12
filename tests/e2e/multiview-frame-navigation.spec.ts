import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber } from './helpers';

test.describe('4. Frame Navigation', () => {
    test.use({ storageState: STORAGE_STATE });

    test('frame advances with next-frame key (F)', async ({ page }) => {
        await openMultiviewJob(page);

        const startFrame = await getFrameNumber(page);
        expect(startFrame).toBe(0);

        // Press F key to go to next frame
        await page.keyboard.press('f');
        await page.waitForTimeout(300);
        const nextFrame = await getFrameNumber(page);
        expect(nextFrame).toBe(1);
    });

    test('frame goes back with prev-frame key (D)', async ({ page }) => {
        await openMultiviewJob(page);

        // Go forward first
        await page.keyboard.press('f');
        await page.waitForTimeout(300);
        expect(await getFrameNumber(page)).toBe(1);

        // Go back
        await page.keyboard.press('d');
        await page.waitForTimeout(300);
        expect(await getFrameNumber(page)).toBe(0);
    });

    test('forward jump with V key (frameStep=10)', async ({ page }) => {
        await openMultiviewJob(page);

        await page.keyboard.press('v');
        await page.waitForTimeout(500);
        const frame = await getFrameNumber(page);
        expect(frame).toBe(10);
    });

    test('all canvases present after seek', async ({ page }) => {
        await openMultiviewJob(page);

        // Advance several frames
        await page.keyboard.press('v');
        await page.waitForTimeout(500);

        const frameAfterSeek = await getFrameNumber(page);
        expect(frameAfterSeek).toBe(10);

        // Canvas-only mode: verify canvas backgrounds are still rendered
        const canvasCount = await page.evaluate(() =>
            document.querySelectorAll('#cvat_canvas_background').length,
        );
        console.log(`Canvas backgrounds after seek: ${canvasCount}`);
        expect(canvasCount).toBeGreaterThan(0);
    });
});
