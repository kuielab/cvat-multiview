import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber } from './helpers';

test.describe('Performance: A/B improvements measurement', () => {
    test.use({ storageState: STORAGE_STATE });
    test.setTimeout(120000);

    test('measure chunk decode timing and frame drop rate during 15s playback', async ({ page }) => {
        const consoleLogs: string[] = [];

        // Capture all console messages containing [MV] or [MV-Playback]
        page.on('console', (msg) => {
            const text = msg.text();
            if (text.includes('[MV]') || text.includes('[MV-Playback]')) {
                consoleLogs.push(text);
            }
        });

        await openMultiviewJob(page);

        const startFrame = await getFrameNumber(page);
        console.log(`Start frame: ${startFrame}`);

        // Play for 15 seconds
        await page.keyboard.press('Space');
        await page.waitForTimeout(15000);
        await page.keyboard.press('Space');
        await page.waitForTimeout(500);

        const endFrame = await getFrameNumber(page);
        console.log(`End frame: ${endFrame}`);
        console.log(`Frames advanced: ${endFrame - startFrame}`);

        // Parse console logs
        const cacheHits: number[] = [];
        const perFrameTimes: number[] = [];
        const blockDoneTimes: number[] = [];
        const fetchTimes: number[] = [];
        const playbackStats: string[] = [];

        for (const log of consoleLogs) {
            // [MV] f123 cache-hit
            if (log.includes('cache-hit')) {
                const match = log.match(/f(\d+)/);
                if (match) cacheHits.push(Number(match[1]));
            }
            // [MV] f123 per-frame 45ms (fetch=30ms) chunk#2
            if (log.includes('per-frame')) {
                const totalMatch = log.match(/per-frame (\d+)ms/);
                const fetchMatch = log.match(/fetch=(\d+)ms/);
                if (totalMatch) perFrameTimes.push(Number(totalMatch[1]));
                if (fetchMatch) fetchTimes.push(Number(fetchMatch[1]));
            }
            // [MV] f123 block-done 120ms (fetch=80ms) chunk#2
            if (log.includes('block-done')) {
                const totalMatch = log.match(/block-done (\d+)ms/);
                const fetchMatch = log.match(/fetch=(\d+)ms/);
                if (totalMatch) blockDoneTimes.push(Number(totalMatch[1]));
                if (fetchMatch) fetchTimes.push(Number(fetchMatch[1]));
            }
            // [MV-Playback] 3.0s: dispatched=28 (9.3fps) dropped=2
            if (log.includes('[MV-Playback]')) {
                playbackStats.push(log);
            }
        }

        // Report results
        console.log('\n========== PERFORMANCE RESULTS ==========');
        console.log(`Total console logs captured: ${consoleLogs.length}`);
        console.log(`Cache hits: ${cacheHits.length}`);
        console.log(`Per-frame resolves: ${perFrameTimes.length}`);
        console.log(`Block-done fallbacks: ${blockDoneTimes.length}`);

        if (perFrameTimes.length > 0) {
            const avg = perFrameTimes.reduce((a, b) => a + b, 0) / perFrameTimes.length;
            const max = Math.max(...perFrameTimes);
            const min = Math.min(...perFrameTimes);
            console.log(`\nPer-frame resolve time (ms): avg=${avg.toFixed(1)}, min=${min}, max=${max}`);
        }

        if (blockDoneTimes.length > 0) {
            const avg = blockDoneTimes.reduce((a, b) => a + b, 0) / blockDoneTimes.length;
            const max = Math.max(...blockDoneTimes);
            const min = Math.min(...blockDoneTimes);
            console.log(`Block-done fallback time (ms): avg=${avg.toFixed(1)}, min=${min}, max=${max}`);
        }

        if (fetchTimes.length > 0) {
            const avg = fetchTimes.reduce((a, b) => a + b, 0) / fetchTimes.length;
            const max = Math.max(...fetchTimes);
            const min = Math.min(...fetchTimes);
            console.log(`Chunk fetch time (ms): avg=${avg.toFixed(1)}, min=${min}, max=${max}`);
        }

        console.log('\nPlayback stats (frame drops):');
        for (const stat of playbackStats) {
            console.log(`  ${stat}`);
        }

        // Parse total dispatched/dropped from playback stats
        let totalDispatched = 0;
        let totalDropped = 0;
        for (const stat of playbackStats) {
            const dMatch = stat.match(/dispatched=(\d+)/);
            const drMatch = stat.match(/dropped=(\d+)/);
            if (dMatch) totalDispatched += Number(dMatch[1]);
            if (drMatch) totalDropped += Number(drMatch[1]);
        }
        const dropRate = totalDispatched > 0 ? (totalDropped / (totalDispatched + totalDropped) * 100) : 0;
        console.log(`\nTotal dispatched: ${totalDispatched}, dropped: ${totalDropped}, drop rate: ${dropRate.toFixed(1)}%`);

        const totalDecodes = cacheHits.length + perFrameTimes.length + blockDoneTimes.length;
        const cacheHitRate = totalDecodes > 0 ? (cacheHits.length / totalDecodes * 100) : 0;
        console.log(`Cache hit rate: ${cacheHitRate.toFixed(1)}% (${cacheHits.length}/${totalDecodes})`);
        console.log('==========================================\n');

        // Basic assertions: playback should have advanced frames
        expect(endFrame - startFrame).toBeGreaterThan(50);
    });

    test('measure seek latency (frame-accurate single frame)', async ({ page }) => {
        const consoleLogs: string[] = [];

        page.on('console', (msg) => {
            const text = msg.text();
            if (text.includes('[MV]')) {
                consoleLogs.push(text);
            }
        });

        await openMultiviewJob(page);

        // Seek to various frames and measure decode time
        const seekTargets = [0, 50, 100, 150, 200, 300, 500];
        const seekTimes: { frame: number; logs: string[] }[] = [];

        for (const target of seekTargets) {
            const beforeCount = consoleLogs.length;

            const input = page.locator('.cvat-player-frame-selector input[role="spinbutton"]');
            await input.click({ clickCount: 3 });
            await input.fill(String(target));
            await input.press('Enter');
            await page.waitForTimeout(2000);

            const afterCount = consoleLogs.length;
            const newLogs = consoleLogs.slice(beforeCount, afterCount);
            seekTimes.push({ frame: target, logs: newLogs });
        }

        console.log('\n========== SEEK LATENCY RESULTS ==========');
        for (const { frame, logs } of seekTimes) {
            const perFrame = logs.find((l) => l.includes('per-frame'));
            const blockDone = logs.find((l) => l.includes('block-done'));
            const cacheHit = logs.find((l) => l.includes('cache-hit'));
            if (perFrame) {
                console.log(`Frame ${frame}: ${perFrame}`);
            } else if (blockDone) {
                console.log(`Frame ${frame}: ${blockDone}`);
            } else if (cacheHit) {
                console.log(`Frame ${frame}: cache-hit`);
            } else {
                console.log(`Frame ${frame}: no MV log (${logs.length} logs total)`);
            }
        }
        console.log('==========================================\n');

        expect(seekTimes.length).toBe(seekTargets.length);
    });
});
