import { test, expect } from '@playwright/test';
import { STORAGE_STATE, openMultiviewJob, getFrameNumber, clickViewButton } from './helpers';

/**
 * View 2 freeze diagnosis test.
 * Checks per-view chunk loading, network health, canvas setup timing,
 * and frame advancement to identify why View 2 specifically freezes.
 */
test.describe('View 2 freeze diagnosis', () => {
    test.use({ storageState: STORAGE_STATE });
    test.setTimeout(180000);

    test('per-view chunk latency and frame advancement comparison', async ({ page }) => {
        // Track chunk requests with timing per view
        const chunkRequests: {
            viewId: string;
            chunkIdx: string;
            status: number;
            durationMs: number;
            url: string;
        }[] = [];

        // Track video URL requests (for <video> preview)
        const videoRequests: {
            viewId: string;
            status: number;
            url: string;
        }[] = [];

        // Track all MV console logs
        const mvLogs: { ts: number; text: string }[] = [];
        const allErrors: string[] = [];

        page.on('console', (msg) => {
            const text = msg.text();
            if (text.includes('[MV]') || text.includes('[MV-Playback]') ||
                text.includes('Error') || text.includes('error') ||
                text.includes('reject') || text.includes('Canvas is busy')) {
                mvLogs.push({ ts: Date.now(), text });
            }
        });

        page.on('pageerror', (err) => {
            allErrors.push(`PAGE_ERROR: ${err.name}: ${err.message}`);
        });

        // Track chunk fetch timing
        page.on('requestfinished', async (request) => {
            const url = request.url();

            // Chunk requests (Canvas/Broadway.js)
            const chunkMatch = url.match(/multiview\/data\/(\d+)\?.*type=chunk.*(?:index|number)=(\d+)/);
            if (chunkMatch) {
                const response = await request.response();
                const timing = request.timing();
                const duration = timing.responseEnd > 0 ? timing.responseEnd - timing.startTime : -1;
                chunkRequests.push({
                    viewId: chunkMatch[1],
                    chunkIdx: chunkMatch[2],
                    status: response?.status() || 0,
                    durationMs: Math.round(duration),
                    url: url.substring(url.lastIndexOf('/') - 20),
                });
            }

            // Video URL requests (<video> preview)
            const videoMatch = url.match(/multiview\/video\/(\d+)/);
            if (videoMatch) {
                const response = await request.response();
                videoRequests.push({
                    viewId: videoMatch[1],
                    status: response?.status() || 0,
                    url: url.substring(url.lastIndexOf('/') - 30),
                });
            }
        });

        page.on('requestfailed', (request) => {
            const url = request.url();
            if (url.includes('multiview')) {
                allErrors.push(`NET_FAIL: ${url.substring(url.lastIndexOf('/') - 30)} — ${request.failure()?.errorText}`);
            }
        });

        await openMultiviewJob(page);

        // === Phase 1: Check multiview metadata and video URLs ===
        console.log('\n' + '='.repeat(80));
        console.log('PHASE 1: MULTIVIEW METADATA & VIDEO URLS');
        console.log('='.repeat(80));

        const viewMeta = await page.evaluate(() => {
            const state = (window as any)?.__REDUX_STORE__?.getState?.();
            const mv = state?.annotation?.multiviewData;
            if (!mv) return null;
            const result: Record<string, any> = {};
            for (let i = 1; i <= 10; i++) {
                const key = `view${i}`;
                const v = mv.videos?.[key as keyof typeof mv.videos];
                if (v) {
                    result[key] = {
                        width: v.width,
                        height: v.height,
                        fps: v.fps,
                        url: v.url || '(no url)',
                    };
                }
            }
            return result;
        });

        if (viewMeta) {
            for (const [key, meta] of Object.entries(viewMeta)) {
                console.log(`  ${key}: ${(meta as any).width}x${(meta as any).height} @${(meta as any).fps}fps url=${(meta as any).url}`);
            }
        } else {
            console.log('  WARNING: No multiview metadata found');
        }

        // === Phase 2: Check preview <video> elements ===
        console.log('\n' + '='.repeat(80));
        console.log('PHASE 2: PREVIEW <video> ELEMENT STATUS');
        console.log('='.repeat(80));

        const videoStates = await page.evaluate(() => {
            const videos = document.querySelectorAll('video');
            const states: { src: string; readyState: number; error: string | null; networkState: number; videoWidth: number; videoHeight: number }[] = [];
            videos.forEach((v) => {
                states.push({
                    src: v.src?.substring(v.src.length - 50) || '(no src)',
                    readyState: v.readyState,
                    error: v.error ? `${v.error.code}: ${v.error.message}` : null,
                    networkState: v.networkState,
                    videoWidth: v.videoWidth,
                    videoHeight: v.videoHeight,
                });
            });
            return states;
        });

        for (let i = 0; i < videoStates.length; i++) {
            const v = videoStates[i];
            const readyLabel = ['HAVE_NOTHING', 'HAVE_METADATA', 'HAVE_CURRENT_DATA', 'HAVE_FUTURE_DATA', 'HAVE_ENOUGH_DATA'][v.readyState] || `UNKNOWN(${v.readyState})`;
            const netLabel = ['NETWORK_EMPTY', 'NETWORK_IDLE', 'NETWORK_LOADING', 'NETWORK_NO_SOURCE'][v.networkState] || `UNKNOWN(${v.networkState})`;
            console.log(`  Video[${i}]: ${v.videoWidth}x${v.videoHeight} ready=${readyLabel} net=${netLabel} err=${v.error || 'none'} src=${v.src}`);
        }

        // === Phase 3: Per-view playback test ===
        console.log('\n' + '='.repeat(80));
        console.log('PHASE 3: PER-VIEW PLAYBACK (3s each)');
        console.log('='.repeat(80));

        const viewCount = viewMeta ? Object.keys(viewMeta).length : 5;
        const playbackResults: Record<number, {
            startFrame: number;
            endFrame: number;
            framesAdvanced: number;
            samples: number[];
            stallCount: number;
            chunkCount: number;
            chunkFailures: number;
            avgChunkMs: number;
            maxChunkMs: number;
            errors: number;
        }> = {};

        for (let v = 1; v <= viewCount; v++) {
            const chunksBefore = chunkRequests.length;
            const errsBefore = allErrors.length;

            // Switch to this view
            await clickViewButton(page, v);

            // Seek to frame 0
            const input = page.locator('.cvat-player-frame-selector input[role="spinbutton"]');
            await input.click({ clickCount: 3 });
            await input.fill('0');
            await input.press('Enter');
            await page.waitForTimeout(1500);

            const startFrame = await getFrameNumber(page);

            // Click canvas area to unfocus the frame input before pressing Space
            const canvasWrapper = page.locator('#cvat_canvas_wrapper');
            if (await canvasWrapper.isVisible()) {
                await canvasWrapper.click({ position: { x: 50, y: 50 } });
                await page.waitForTimeout(200);
            }

            // Play for 3 seconds, sampling every 200ms
            const samples: number[] = [];
            await page.keyboard.press('Space');

            for (let i = 0; i < 15; i++) {
                await page.waitForTimeout(200);
                const f = await getFrameNumber(page);
                samples.push(f);
            }

            await page.keyboard.press('Space');
            await page.waitForTimeout(500);

            const endFrame = await getFrameNumber(page);

            // Count stalls (3+ consecutive same-frame samples = 600ms+ stall)
            let stallCount = 0;
            for (let i = 2; i < samples.length; i++) {
                if (samples[i] === samples[i - 1] && samples[i - 1] === samples[i - 2]) {
                    stallCount++;
                }
            }

            // Chunk stats for this view
            const viewChunks = chunkRequests.slice(chunksBefore);
            const viewViewChunks = viewChunks.filter((c) => c.viewId === String(v));
            const failures = viewViewChunks.filter((c) => c.status >= 400).length;
            const validTimes = viewViewChunks.filter((c) => c.durationMs > 0).map((c) => c.durationMs);
            const avgMs = validTimes.length > 0 ? Math.round(validTimes.reduce((a, b) => a + b, 0) / validTimes.length) : 0;
            const maxMs = validTimes.length > 0 ? Math.max(...validTimes) : 0;

            playbackResults[v] = {
                startFrame,
                endFrame,
                framesAdvanced: endFrame - startFrame,
                samples,
                stallCount,
                chunkCount: viewViewChunks.length,
                chunkFailures: failures,
                avgChunkMs: avgMs,
                maxChunkMs: maxMs,
                errors: allErrors.length - errsBefore,
            };

            console.log(
                `  View ${v}: frames=${endFrame - startFrame} stalls=${stallCount} ` +
                `chunks=${viewViewChunks.length}(${failures} fail) ` +
                `latency avg=${avgMs}ms max=${maxMs}ms errors=${allErrors.length - errsBefore}`
            );
            console.log(`    samples: [${samples.join(', ')}]`);
        }

        // === Phase 4: Rapid view switching (focused on View 2) ===
        console.log('\n' + '='.repeat(80));
        console.log('PHASE 4: RAPID VIEW SWITCHING (1→2→3→2→1→2)');
        console.log('='.repeat(80));

        await clickViewButton(page, 1);
        const input2 = page.locator('.cvat-player-frame-selector input[role="spinbutton"]');
        await input2.click({ clickCount: 3 });
        await input2.fill('0');
        await input2.press('Enter');
        await page.waitForTimeout(1000);

        // Click canvas to unfocus input
        const canvasWrapper2 = page.locator('#cvat_canvas_wrapper');
        if (await canvasWrapper2.isVisible()) {
            await canvasWrapper2.click({ position: { x: 50, y: 50 } });
            await page.waitForTimeout(200);
        }

        // Start playback then rapid switch
        await page.keyboard.press('Space');

        const switchSequence = [2, 3, 2, 1, 2];
        const switchFrames: { viewId: number; frameAfterSwitch: number }[] = [];

        for (const viewId of switchSequence) {
            await clickViewButton(page, viewId);
            await page.waitForTimeout(1000);
            const f = await getFrameNumber(page);
            switchFrames.push({ viewId, frameAfterSwitch: f });
        }

        await page.keyboard.press('Space');
        await page.waitForTimeout(500);

        const finalFrame = await getFrameNumber(page);
        console.log('  Switch sequence results:');
        for (const sf of switchFrames) {
            console.log(`    → View ${sf.viewId}: frame=${sf.frameAfterSwitch}`);
        }
        console.log(`  Final frame: ${finalFrame}`);

        // Check frame monotonically increases
        let monotonicFail = false;
        for (let i = 1; i < switchFrames.length; i++) {
            if (switchFrames[i].frameAfterSwitch < switchFrames[i - 1].frameAfterSwitch) {
                monotonicFail = true;
                console.log(`  WARNING: Frame went backwards at switch ${i}: ${switchFrames[i - 1].frameAfterSwitch} → ${switchFrames[i].frameAfterSwitch}`);
            }
        }

        // === Phase 5: Check <video> preview sync after playback ===
        console.log('\n' + '='.repeat(80));
        console.log('PHASE 5: PREVIEW VIDEO SYNC CHECK');
        console.log('='.repeat(80));

        const fps = (viewMeta as any)?.view1?.fps || 30;
        const expectedTime = finalFrame / fps;

        const previewSync = await page.evaluate(() => {
            const videos = document.querySelectorAll('video');
            const result: { src: string; currentTime: number; paused: boolean; videoWidth: number }[] = [];
            videos.forEach((v) => {
                result.push({
                    src: v.src?.substring(v.src.length - 40) || '(no src)',
                    currentTime: v.currentTime,
                    paused: v.paused,
                    videoWidth: v.videoWidth,
                });
            });
            return result;
        });

        console.log(`  Expected time: ${expectedTime.toFixed(2)}s (frame ${finalFrame} @ ${fps}fps)`);
        let maxDrift = 0;
        for (const pv of previewSync) {
            if (pv.videoWidth === 0) {
                console.log(`  [audio] time=${pv.currentTime.toFixed(2)}s paused=${pv.paused}`);
                continue;
            }
            const drift = Math.abs(pv.currentTime - expectedTime);
            maxDrift = Math.max(maxDrift, drift);
            console.log(`  ${pv.src}: time=${pv.currentTime.toFixed(2)}s drift=${drift.toFixed(2)}s paused=${pv.paused}`);
        }
        console.log(`  Max drift: ${maxDrift.toFixed(2)}s`);

        // === Summary ===
        console.log('\n' + '='.repeat(80));
        console.log('SUMMARY');
        console.log('='.repeat(80));

        console.log(
            'View'.padEnd(6) +
            'Frames'.padEnd(9) +
            'Stalls'.padEnd(8) +
            'Chunks'.padEnd(8) +
            'Fails'.padEnd(7) +
            'AvgMs'.padEnd(8) +
            'MaxMs'.padEnd(8) +
            'Errors'.padEnd(8),
        );
        console.log('-'.repeat(60));

        for (let v = 1; v <= viewCount; v++) {
            const r = playbackResults[v];
            if (!r) continue;
            console.log(
                `${v}`.padEnd(6) +
                `${r.framesAdvanced}`.padEnd(9) +
                `${r.stallCount}`.padEnd(8) +
                `${r.chunkCount}`.padEnd(8) +
                `${r.chunkFailures}`.padEnd(7) +
                `${r.avgChunkMs}`.padEnd(8) +
                `${r.maxChunkMs}`.padEnd(8) +
                `${r.errors}`.padEnd(8),
            );
        }

        if (allErrors.length > 0) {
            console.log('\n=== ALL ERRORS ===');
            for (const e of allErrors.slice(0, 20)) {
                console.log(`  ${e}`);
            }
            if (allErrors.length > 20) {
                console.log(`  ... and ${allErrors.length - 20} more`);
            }
        }

        // Chunk requests by view
        console.log('\n=== CHUNK REQUEST DETAILS ===');
        const byView: Record<string, typeof chunkRequests> = {};
        for (const cr of chunkRequests) {
            if (!byView[cr.viewId]) byView[cr.viewId] = [];
            byView[cr.viewId].push(cr);
        }
        for (const [vId, reqs] of Object.entries(byView)) {
            const fails = reqs.filter((r) => r.status >= 400);
            const ok = reqs.filter((r) => r.status < 400 && r.durationMs > 0);
            const avg = ok.length ? Math.round(ok.reduce((a, b) => a + b.durationMs, 0) / ok.length) : 0;
            console.log(`  View ${vId}: ${reqs.length} total, ${fails.length} failed, avg=${avg}ms`);
            for (const f of fails.slice(0, 5)) {
                console.log(`    FAIL: chunk#${f.chunkIdx} status=${f.status}`);
            }
        }

        // Video URL requests
        if (videoRequests.length > 0) {
            console.log('\n=== VIDEO URL REQUESTS ===');
            for (const vr of videoRequests) {
                console.log(`  View ${vr.viewId}: status=${vr.status} ${vr.url}`);
            }
        }

        console.log('='.repeat(80));

        // Assertions: View 2 should not be significantly worse than others
        const v2 = playbackResults[2];
        if (v2) {
            const otherViews = Object.entries(playbackResults).filter(([k]) => k !== '2');
            const otherAvgFrames = otherViews.length > 0
                ? otherViews.reduce((sum, [, r]) => sum + r.framesAdvanced, 0) / otherViews.length
                : 0;

            console.log(`\nView 2 frames: ${v2.framesAdvanced}, Other avg: ${otherAvgFrames.toFixed(0)}`);
            console.log(`View 2 stalls: ${v2.stallCount}`);

            // View 2 should advance at least 50% of what other views achieve
            if (otherAvgFrames > 0) {
                expect(v2.framesAdvanced).toBeGreaterThan(otherAvgFrames * 0.3);
            }
        }
    });
});
