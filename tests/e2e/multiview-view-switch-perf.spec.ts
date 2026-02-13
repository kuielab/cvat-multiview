import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber } from './helpers';

/**
 * View-switching performance test at 10 speed levels.
 *
 * Level 1 = 5000ms interval (slowest), Level 10 = 250ms interval (fastest).
 * Each level: 10s playback while cycling views 1→2→3→4→5→1→...
 * Captures [MV] decode logs + [MV-Playback] frame drop stats.
 */

const SPEED_LEVELS: { level: number; intervalMs: number }[] = [
    { level: 1, intervalMs: 5000 },
    { level: 2, intervalMs: 4000 },
    { level: 3, intervalMs: 3000 },
    { level: 4, intervalMs: 2500 },
    { level: 5, intervalMs: 2000 },
    { level: 6, intervalMs: 1500 },
    { level: 7, intervalMs: 1000 },
    { level: 8, intervalMs: 750 },
    { level: 9, intervalMs: 500 },
    { level: 10, intervalMs: 250 },
];

const VIEW_COUNT = 5;
const PLAYBACK_DURATION_MS = 10000;

interface LevelResult {
    level: number;
    intervalMs: number;
    switchCount: number;
    startFrame: number;
    endFrame: number;
    framesAdvanced: number;
    cacheHits: number;
    perFrameResolves: number;
    blockDoneFallbacks: number;
    avgPerFrameMs: number;
    maxPerFrameMs: number;
    avgFetchMs: number;
    totalDispatched: number;
    totalDropped: number;
    dropRate: number;
    cacheHitRate: number;
    freezeDetected: boolean;
    freezeCount: number;
}

test.describe('View-switch performance across 10 speed levels', () => {
    test.use({ storageState: STORAGE_STATE });
    test.setTimeout(300000); // 5 min total

    test('measure all 10 levels', async ({ page }) => {
        await openMultiviewJob(page);

        // Locate view buttons once (they stay in DOM)
        const viewButtons: { viewId: number; selector: string }[] = [];
        for (let v = 1; v <= VIEW_COUNT; v++) {
            viewButtons.push({
                viewId: v,
                selector: `[role="button"]:has-text("View ${v}")`,
            });
        }

        // Verify at least some view buttons exist
        const firstBtn = page.locator(viewButtons[0].selector).first();
        await expect(firstBtn).toBeVisible({ timeout: 10000 });

        const results: LevelResult[] = [];

        for (const { level, intervalMs } of SPEED_LEVELS) {
            // --- Reset for this level ---
            // Pause if playing
            const playBtn = page.locator('.cvat-player-play-button, .cvat-player-pause-button');
            const isPaused = await page.locator('.cvat-player-play-button').count() > 0;
            if (!isPaused) {
                await page.keyboard.press('Space');
                await page.waitForTimeout(300);
            }

            // Seek to frame 0
            const input = page.locator('.cvat-player-frame-selector input[role="spinbutton"]');
            await input.click({ clickCount: 3 });
            await input.fill('0');
            await input.press('Enter');
            await page.waitForTimeout(1500);

            // Click View 1 to start clean
            await page.locator(viewButtons[0].selector).first().click();
            await page.waitForTimeout(500);

            // --- Collect logs for this level ---
            const logs: string[] = [];
            const handler = (msg: any): void => {
                const text = msg.text();
                if (text.includes('[MV]') || text.includes('[MV-Playback]')) {
                    logs.push(text);
                }
            };
            page.on('console', handler);

            // --- Freeze detection: sample frame every 500ms ---
            const frameSamples: { time: number; frame: number }[] = [];
            let freezeCount = 0;
            let sampleRunning = true;

            const sampleInterval = setInterval(async () => {
                if (!sampleRunning) return;
                try {
                    const f = await getFrameNumber(page);
                    frameSamples.push({ time: Date.now(), frame: f });
                } catch {
                    // page may be navigating
                }
            }, 500);

            // --- Start playback ---
            const startFrame = await getFrameNumber(page);
            await page.keyboard.press('Space');

            // --- Switch views at the given interval ---
            let viewIndex = 0;
            let switchCount = 0;
            const switchStart = Date.now();

            while (Date.now() - switchStart < PLAYBACK_DURATION_MS) {
                await page.waitForTimeout(intervalMs);
                viewIndex = (viewIndex + 1) % VIEW_COUNT;
                try {
                    await page.locator(viewButtons[viewIndex].selector).first().click({ timeout: 3000 });
                    switchCount++;
                } catch {
                    // button click timeout — possible freeze
                    freezeCount++;
                }
            }

            // --- Stop playback ---
            await page.keyboard.press('Space');
            await page.waitForTimeout(500);
            sampleRunning = false;
            clearInterval(sampleInterval);

            const endFrame = await getFrameNumber(page);

            // --- Detect freezes from frame samples ---
            // Freeze = frame didn't advance for >= 2 consecutive samples (1+ second)
            for (let i = 2; i < frameSamples.length; i++) {
                if (
                    frameSamples[i].frame === frameSamples[i - 1].frame &&
                    frameSamples[i - 1].frame === frameSamples[i - 2].frame
                ) {
                    freezeCount++;
                }
            }

            // --- Parse logs ---
            let cacheHits = 0;
            const perFrameTimes: number[] = [];
            const blockDoneTimes: number[] = [];
            const fetchTimes: number[] = [];
            let totalDispatched = 0;
            let totalDropped = 0;

            for (const log of logs) {
                if (log.includes('cache-hit')) cacheHits++;
                if (log.includes('per-frame')) {
                    const t = log.match(/per-frame (\d+)ms/);
                    const f = log.match(/fetch=(\d+)ms/);
                    if (t) perFrameTimes.push(Number(t[1]));
                    if (f) fetchTimes.push(Number(f[1]));
                }
                if (log.includes('block-done')) {
                    const t = log.match(/block-done (\d+)ms/);
                    const f = log.match(/fetch=(\d+)ms/);
                    if (t) blockDoneTimes.push(Number(t[1]));
                    if (f) fetchTimes.push(Number(f[1]));
                }
                if (log.includes('[MV-Playback]')) {
                    const d = log.match(/dispatched=(\d+)/);
                    const dr = log.match(/dropped=(\d+)/);
                    if (d) totalDispatched += Number(d[1]);
                    if (dr) totalDropped += Number(dr[1]);
                }
            }

            const totalDecodes = cacheHits + perFrameTimes.length + blockDoneTimes.length;
            const avgPf = perFrameTimes.length > 0
                ? perFrameTimes.reduce((a, b) => a + b, 0) / perFrameTimes.length : 0;
            const maxPf = perFrameTimes.length > 0 ? Math.max(...perFrameTimes) : 0;
            const avgFetch = fetchTimes.length > 0
                ? fetchTimes.reduce((a, b) => a + b, 0) / fetchTimes.length : 0;
            const dropRate = (totalDispatched + totalDropped) > 0
                ? totalDropped / (totalDispatched + totalDropped) * 100 : 0;
            const cacheHitRate = totalDecodes > 0 ? cacheHits / totalDecodes * 100 : 0;

            results.push({
                level,
                intervalMs,
                switchCount,
                startFrame,
                endFrame,
                framesAdvanced: endFrame - startFrame,
                cacheHits,
                perFrameResolves: perFrameTimes.length,
                blockDoneFallbacks: blockDoneTimes.length,
                avgPerFrameMs: Math.round(avgPf),
                maxPerFrameMs: maxPf,
                avgFetchMs: Math.round(avgFetch),
                totalDispatched,
                totalDropped,
                dropRate: Math.round(dropRate * 10) / 10,
                cacheHitRate: Math.round(cacheHitRate * 10) / 10,
                freezeDetected: freezeCount > 0,
                freezeCount,
            });

            // Remove listener for next level
            page.removeListener('console', handler);

            console.log(`Level ${level} (${intervalMs}ms) done: ${switchCount} switches, ${endFrame - startFrame} frames, drop=${dropRate.toFixed(1)}%, cache=${cacheHitRate.toFixed(1)}%, freezes=${freezeCount}`);
        }

        // ========== FINAL SUMMARY ==========
        console.log('\n');
        console.log('='.repeat(130));
        console.log('VIEW-SWITCH PERFORMANCE SUMMARY (10 speed levels)');
        console.log('='.repeat(130));
        console.log(
            'Lv'.padEnd(4) +
            'Interval'.padEnd(10) +
            'Switches'.padEnd(10) +
            'Frames'.padEnd(9) +
            'CacheHit%'.padEnd(11) +
            'Cache'.padEnd(7) +
            'PerFrame'.padEnd(10) +
            'BlkDone'.padEnd(9) +
            'AvgDecode'.padEnd(11) +
            'MaxDecode'.padEnd(11) +
            'AvgFetch'.padEnd(10) +
            'Dispatch'.padEnd(10) +
            'Dropped'.padEnd(9) +
            'Drop%'.padEnd(8) +
            'Freezes'.padEnd(8),
        );
        console.log('-'.repeat(130));

        for (const r of results) {
            console.log(
                String(r.level).padEnd(4) +
                `${r.intervalMs}ms`.padEnd(10) +
                String(r.switchCount).padEnd(10) +
                String(r.framesAdvanced).padEnd(9) +
                `${r.cacheHitRate}%`.padEnd(11) +
                String(r.cacheHits).padEnd(7) +
                String(r.perFrameResolves).padEnd(10) +
                String(r.blockDoneFallbacks).padEnd(9) +
                `${r.avgPerFrameMs}ms`.padEnd(11) +
                `${r.maxPerFrameMs}ms`.padEnd(11) +
                `${r.avgFetchMs}ms`.padEnd(10) +
                String(r.totalDispatched).padEnd(10) +
                String(r.totalDropped).padEnd(9) +
                `${r.dropRate}%`.padEnd(8) +
                String(r.freezeCount).padEnd(8),
            );
        }
        console.log('='.repeat(130));

        // Freeze summary
        const frozenLevels = results.filter((r) => r.freezeDetected);
        if (frozenLevels.length > 0) {
            console.log(`\n⚠ Freeze detected at levels: ${frozenLevels.map((r) => `${r.level}(${r.freezeCount})`).join(', ')}`);
        } else {
            console.log('\nNo freezes detected at any level.');
        }

        // Drop rate trend
        const highDropLevels = results.filter((r) => r.dropRate > 5);
        if (highDropLevels.length > 0) {
            console.log(`High drop rate (>5%) at levels: ${highDropLevels.map((r) => `${r.level}(${r.dropRate}%)`).join(', ')}`);
        }

        console.log('\n');

        // Assertion: all levels should advance at least some frames
        for (const r of results) {
            expect(r.framesAdvanced).toBeGreaterThan(0);
        }
    });
});
