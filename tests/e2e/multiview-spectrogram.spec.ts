import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber } from './helpers';

/** Generate spectrogram and wait for canvas to appear. */
async function generateSpectrogram(page: import('@playwright/test').Page): Promise<void> {
    const generateBtn = page.locator('button', { hasText: /Generate Spectrogram|Regenerate/ });
    await generateBtn.click();
    await page.waitForSelector('.spectrogram-canvas-container', { state: 'visible', timeout: 30000 });
    await page.waitForTimeout(500);
}

test.describe('Spectrogram Tests', () => {
    test.use({ storageState: STORAGE_STATE });

    test('spectrogram panel is visible with generate button', async ({ page }) => {
        await openMultiviewJob(page);

        const heading = page.locator('h3', { hasText: 'Audio Spectrogram' });
        await expect(heading).toBeVisible();

        const generateBtn = page.locator('button', { hasText: 'Generate Spectrogram' });
        await expect(generateBtn).toBeVisible();
    });

    test('generate spectrogram completes without error', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);

        const generateBtn = page.locator('button', { hasText: 'Generate Spectrogram' });
        await generateBtn.click();

        // Wait for spectrogram to render (canvas element should appear or button text changes)
        await page.waitForTimeout(5000);

        // Check no error dialogs appeared
        const errorDialog = page.locator('.ant-modal-confirm-error, .ant-notification-error');
        const errorCount = await errorDialog.count();
        expect(errorCount).toBe(0);

        // Check console errors
        const consoleErrors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') {
                consoleErrors.push(msg.text());
            }
        });
        await page.waitForTimeout(1000);
        // Filter out known non-critical errors
        const criticalErrors = consoleErrors.filter(
            (e) => !e.includes('user-agreements') && !e.includes('preview'),
        );
        console.log(`Console errors after spectrogram: ${criticalErrors.length}`);
    });

    test('spectrogram click seeks to target frame while paused', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);

        const frameBefore = await getFrameNumber(page);
        expect(frameBefore).toBe(0);

        await generateSpectrogram(page);

        // Click at ~50% of spectrogram width to seek to midpoint
        const overlay = page.locator('canvas.spectrogram-overlay');
        const box = await overlay.boundingBox();
        expect(box).not.toBeNull();

        await page.mouse.click(box!.x + box!.width * 0.5, box!.y + box!.height / 2);
        await page.waitForTimeout(1000);

        const frameAfter = await getFrameNumber(page);
        console.log(`Spectrogram seek (paused): before=${frameBefore}, after=${frameAfter}`);
        expect(frameAfter).toBeGreaterThan(frameBefore);
    });

    test('spectrogram click during playback seeks and resumes', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);
        await generateSpectrogram(page);

        // Start playback
        await page.keyboard.press('Space');
        await page.waitForTimeout(1500);

        const frameWhilePlaying = await getFrameNumber(page);
        expect(frameWhilePlaying).toBeGreaterThan(0);

        // Click at ~80% of spectrogram to seek forward
        const overlay = page.locator('canvas.spectrogram-overlay');
        const box = await overlay.boundingBox();
        expect(box).not.toBeNull();

        await page.mouse.click(box!.x + box!.width * 0.8, box!.y + box!.height / 2);
        await page.waitForTimeout(1000);

        const frameAfterSeek = await getFrameNumber(page);

        console.log(`Spectrogram seek (playing): playing=${frameWhilePlaying}, afterSeek=${frameAfterSeek}`);
        // Frame should have jumped to a different position
        expect(frameAfterSeek).not.toBe(frameWhilePlaying);
        // Should have seeked to ~80% of total frames (much larger than where we were)
        expect(frameAfterSeek).toBeGreaterThan(frameWhilePlaying);

        // Pause to clean up
        await page.keyboard.press('Space');
    });

    test('playhead position tracks current frame during playback', async ({ page }) => {
        test.setTimeout(60000);
        await openMultiviewJob(page);
        await generateSpectrogram(page);

        const overlay = page.locator('canvas.spectrogram-overlay');
        const box = await overlay.boundingBox();
        expect(box).not.toBeNull();

        // Read playhead X position from overlay canvas pixel data
        const getPlayheadX = async (): Promise<number> => page.evaluate(() => {
            const canvas = document.querySelector('canvas.spectrogram-overlay') as HTMLCanvasElement;
            if (!canvas) return -1;
            const ctx = canvas.getContext('2d');
            if (!ctx) return -1;
            // Scan for red pixel (playhead color #ff4d4d) across middle row
            const y = Math.floor(canvas.height / 2);
            const data = ctx.getImageData(0, y, canvas.width, 1).data;
            for (let x = 0; x < canvas.width; x++) {
                const r = data[x * 4];
                const g = data[x * 4 + 1];
                const b = data[x * 4 + 2];
                const a = data[x * 4 + 3];
                // Match red playhead (R > 200, G < 100, B < 100, visible)
                if (r > 200 && g < 100 && b < 100 && a > 100) return x;
            }
            return -1;
        });

        const x1 = await getPlayheadX();

        // Play for 2 seconds
        await page.keyboard.press('Space');
        await page.waitForTimeout(2000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(300);

        const x2 = await getPlayheadX();
        console.log(`Playhead tracking: x1=${x1}, x2=${x2}`);

        // Playhead should have moved rightward
        expect(x2).toBeGreaterThan(x1);
    });
});
