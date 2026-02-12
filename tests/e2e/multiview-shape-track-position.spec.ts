import { test, expect } from '@playwright/test';
import {
    STORAGE_STATE, FIRST_ANNOTATED_FRAME,
    openMultiviewJob, openMultiviewJobWithShapes, seekToFrame,
    getShapeCount, clickViewButton, waitForCanvas,
} from './helpers';

/**
 * Shape mode: draw a new rectangle (shape, not track), save, refresh multiple times,
 * verify position stays within 2px.
 */
test.describe('Shape/Track Position on Refresh', () => {
    test.use({ storageState: STORAGE_STATE });

    test('SHAPE mode: bbox position persists after multiple refreshes', async ({ page }) => {
        test.setTimeout(120000);
        await openMultiviewJobWithShapes(page);

        const beforeCount = await getShapeCount(page);
        console.log(`Before: ${beforeCount} shapes`);

        // Draw a new rectangle via keyboard shortcut
        // Click on active canvas overlay to ensure focus
        const overlay = page.locator('.annotation-canvas-overlay.active-canvas');
        const overlayBox = await overlay.boundingBox();
        expect(overlayBox).not.toBeNull();

        await page.mouse.click(overlayBox!.x + 10, overlayBox!.y + 10);
        await page.waitForTimeout(300);

        // Press N to start drawing
        await page.keyboard.press('n');
        await page.waitForTimeout(500);

        // Draw rectangle at specific position
        const x1 = overlayBox!.x + overlayBox!.width * 0.2;
        const y1 = overlayBox!.y + overlayBox!.height * 0.2;
        const x2 = overlayBox!.x + overlayBox!.width * 0.4;
        const y2 = overlayBox!.y + overlayBox!.height * 0.4;

        await page.mouse.click(x1, y1);
        await page.waitForTimeout(200);
        await page.mouse.click(x2, y2);
        await page.waitForTimeout(500);
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);

        const afterCount = await getShapeCount(page);
        console.log(`After draw: ${afterCount} shapes`);
        expect(afterCount).toBeGreaterThan(beforeCount);

        // Get the new shape's position (last shape)
        const shapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
        const lastShape = shapes.last();
        const bbox0 = await lastShape.boundingBox();
        expect(bbox0).not.toBeNull();
        const cx0 = bbox0!.x + bbox0!.width / 2;
        const cy0 = bbox0!.y + bbox0!.height / 2;
        console.log(`Shape center: (${cx0.toFixed(2)}, ${cy0.toFixed(2)}), size: ${bbox0!.width.toFixed(2)}x${bbox0!.height.toFixed(2)}`);

        // Save
        await page.keyboard.press('Control+s');
        await page.waitForTimeout(2000);

        // Refresh 5 times and check position
        // Use first refresh as baseline (draw→save has coordinate rounding)
        let baseCx = 0;
        let baseCy = 0;
        let maxDx = 0;
        let maxDy = 0;
        let saveDx = 0;
        let saveDy = 0;
        for (let i = 0; i < 5; i++) {
            await page.reload({ waitUntil: 'domcontentloaded' });
            await page.waitForSelector('.cvat-multiview-workspace', { state: 'visible', timeout: 30000 });
            await page.waitForSelector('#cvat_canvas_wrapper', { state: 'visible', timeout: 30000 });
            await page.waitForTimeout(1000);

            await seekToFrame(page, FIRST_ANNOTATED_FRAME);
            await page.waitForSelector('#cvat_canvas_content .cvat_canvas_shape', { state: 'attached', timeout: 15000 });
            await page.waitForTimeout(500);

            // Find closest shape to original position
            const allShapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
            const count = await allShapes.count();
            let bestDist = Infinity;
            let bestCx = 0;
            let bestCy = 0;

            for (let j = 0; j < count; j++) {
                const box = await allShapes.nth(j).boundingBox();
                if (!box) continue;
                const cx = box.x + box.width / 2;
                const cy = box.y + box.height / 2;
                const dist = Math.sqrt((cx - cx0) ** 2 + (cy - cy0) ** 2);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestCx = cx;
                    bestCy = cy;
                }
            }

            if (i === 0) {
                baseCx = bestCx;
                baseCy = bestCy;
                saveDx = Math.abs(bestCx - cx0);
                saveDy = Math.abs(bestCy - cy0);
                console.log(`Refresh ${i + 1} (baseline): center=(${bestCx.toFixed(2)}, ${bestCy.toFixed(2)}), save-offset=${saveDx.toFixed(2)},${saveDy.toFixed(2)}`);
            } else {
                const dx = Math.abs(bestCx - baseCx);
                const dy = Math.abs(bestCy - baseCy);
                maxDx = Math.max(maxDx, dx);
                maxDy = Math.max(maxDy, dy);
                console.log(`Refresh ${i + 1}: center=(${bestCx.toFixed(2)}, ${bestCy.toFixed(2)}), drift=${dx.toFixed(2)},${dy.toFixed(2)}`);
            }
        }

        console.log(`SHAPE MODE: save-offset=${saveDx.toFixed(2)},${saveDy.toFixed(2)} (one-time), refresh drift=${maxDx.toFixed(2)},${maxDy.toFixed(2)}`);
        // Save-offset up to 3px is acceptable (coordinate rounding)
        expect(saveDx).toBeLessThanOrEqual(3);
        expect(saveDy).toBeLessThanOrEqual(3);
        // Refresh-to-refresh drift must be <= 2px
        expect(maxDx).toBeLessThanOrEqual(2);
        expect(maxDy).toBeLessThanOrEqual(2);

        // Cleanup: delete the shape we created
        const shapesToDelete = page.locator('#cvat_canvas_content .cvat_canvas_shape');
        const lastCreated = shapesToDelete.last();
        await lastCreated.click();
        await page.waitForTimeout(500);
        await page.keyboard.press('Delete');
        await page.waitForTimeout(1000);
        await page.keyboard.press('Control+s');
        await page.waitForTimeout(1000);
    });

    test('TRACK mode: existing track bbox position persists after multiple refreshes', async ({ page }) => {
        test.setTimeout(120000);
        await openMultiviewJobWithShapes(page);

        // Get first shape (which is a track) position
        const shapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
        const firstShape = shapes.first();
        const bbox0 = await firstShape.boundingBox();
        expect(bbox0).not.toBeNull();
        const cx0 = bbox0!.x + bbox0!.width / 2;
        const cy0 = bbox0!.y + bbox0!.height / 2;
        console.log(`Track bbox center: (${cx0.toFixed(2)}, ${cy0.toFixed(2)}), size: ${bbox0!.width.toFixed(2)}x${bbox0!.height.toFixed(2)}`);

        // Refresh 5 times
        let maxDx = 0;
        let maxDy = 0;
        for (let i = 0; i < 5; i++) {
            await page.reload({ waitUntil: 'domcontentloaded' });
            await page.waitForSelector('.cvat-multiview-workspace', { state: 'visible', timeout: 30000 });
            await page.waitForSelector('#cvat_canvas_wrapper', { state: 'visible', timeout: 30000 });
            await page.waitForTimeout(1000);

            await seekToFrame(page, FIRST_ANNOTATED_FRAME);
            await page.waitForSelector('#cvat_canvas_content .cvat_canvas_shape', { state: 'attached', timeout: 15000 });
            await page.waitForTimeout(500);

            // Find closest shape to original position
            const allShapes = page.locator('#cvat_canvas_content .cvat_canvas_shape');
            const count = await allShapes.count();
            let bestDist = Infinity;
            let bestCx = 0;
            let bestCy = 0;

            for (let j = 0; j < count; j++) {
                const box = await allShapes.nth(j).boundingBox();
                if (!box) continue;
                const cx = box.x + box.width / 2;
                const cy = box.y + box.height / 2;
                const dist = Math.sqrt((cx - cx0) ** 2 + (cy - cy0) ** 2);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestCx = cx;
                    bestCy = cy;
                }
            }

            const dx = Math.abs(bestCx - cx0);
            const dy = Math.abs(bestCy - cy0);
            maxDx = Math.max(maxDx, dx);
            maxDy = Math.max(maxDy, dy);
            console.log(`Refresh ${i + 1}: center=(${bestCx.toFixed(2)}, ${bestCy.toFixed(2)}), dx=${dx.toFixed(2)}, dy=${dy.toFixed(2)}`);
        }

        console.log(`TRACK MODE max drift: dx=${maxDx.toFixed(2)}, dy=${maxDy.toFixed(2)}`);
        expect(maxDx).toBeLessThanOrEqual(2);
        expect(maxDy).toBeLessThanOrEqual(2);
    });
});
