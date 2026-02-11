import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber } from './helpers';

test.describe('3/5. Playback & Draw Auto-Pause', () => {
    test.use({ storageState: STORAGE_STATE });

    test('play advances frame number, pause stops it', async ({ page }) => {
        await openMultiviewJob(page);

        expect(await getFrameNumber(page)).toBe(0);

        // Press Space to play
        await page.keyboard.press('Space');
        await page.waitForTimeout(2000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);

        const frame = await getFrameNumber(page);
        console.log(`Frame after 2s playback: ${frame}`);
        expect(frame).toBeGreaterThan(0);
    });

    test('draw mode auto-pauses playback', async ({ page }) => {
        await openMultiviewJob(page);

        // Start playback
        await page.keyboard.press('Space');
        await page.waitForTimeout(1000);

        // Check playback is running
        const frameBefore = await getFrameNumber(page);
        expect(frameBefore).toBeGreaterThan(0);

        // Press N to enter draw mode - should auto-pause
        await page.keyboard.press('n');
        await page.waitForTimeout(500);
        const frameAtDraw = await getFrameNumber(page);

        // Wait a bit - frame should NOT advance if paused
        await page.waitForTimeout(1000);
        const frameAfterWait = await getFrameNumber(page);

        console.log(`Draw auto-pause: frameBefore=${frameBefore}, atDraw=${frameAtDraw}, afterWait=${frameAfterWait}`);
        expect(frameAfterWait).toBe(frameAtDraw);

        // Cancel draw mode
        await page.keyboard.press('Escape');
    });
});
