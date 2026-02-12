import { defineConfig } from '@playwright/test';

const baseURL = process.env.CVAT_BASE_URL || 'http://localhost:8080';

export default defineConfig({
    testDir: './e2e',
    timeout: 120_000,
    expect: {
        timeout: 15_000,
    },
    workers: 4,
    use: {
        baseURL,
        headless: true,
        viewport: { width: 1440, height: 900 },
        ignoreHTTPSErrors: true,
        actionTimeout: 15_000,
    },
    reporter: [['list']],
});
