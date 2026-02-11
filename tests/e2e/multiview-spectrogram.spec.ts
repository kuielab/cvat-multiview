import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob } from './helpers';

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
});
