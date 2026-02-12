import { Page, expect } from '@playwright/test';
import * as path from 'path';

export const TASK_ID = process.env.CVAT_MULTIVIEW_TASK_ID || '9';
export const JOB_ID = process.env.CVAT_MULTIVIEW_JOB_ID || '9';
export const FIRST_ANNOTATED_FRAME = Number(process.env.CVAT_FIRST_ANNOTATED_FRAME || '158');
export const STORAGE_STATE = process.env.CVAT_STORAGE_STATE
    || path.resolve(__dirname, 'storage-state.json');

/** Open the multiview job page and wait for workspace to be ready (no shape requirement). */
export async function openMultiviewJob(page: Page): Promise<void> {
    await page.goto(`/tasks/${TASK_ID}/jobs/${JOB_ID}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.cvat-multiview-workspace', { state: 'visible', timeout: 30000 });
    await page.waitForFunction(() => {
        const bgs = document.querySelectorAll('#cvat_canvas_background');
        return bgs.length > 0;
    }, { timeout: 30000 });
    await page.waitForSelector('#cvat_canvas_wrapper', { state: 'visible', timeout: 30000 });
    await page.waitForTimeout(1000);
}

/** Open the multiview job and navigate to a frame that has shapes visible. */
export async function openMultiviewJobWithShapes(page: Page, frame?: number): Promise<void> {
    await openMultiviewJob(page);
    const targetFrame = frame ?? FIRST_ANNOTATED_FRAME;
    await seekToFrame(page, targetFrame);
    await page.waitForSelector('#cvat_canvas_content .cvat_canvas_shape', { state: 'attached', timeout: 15000 });
    await page.waitForTimeout(500);
}

/** Navigate to a specific frame number using the frame input field. */
export async function seekToFrame(page: Page, frame: number): Promise<void> {
    const input = page.locator('.cvat-player-frame-selector input[role="spinbutton"]');
    await input.click({ clickCount: 3 });
    await input.fill(String(frame));
    await input.press('Enter');
    await page.waitForTimeout(1000);
}

/** Wait for canvas ready without requiring shapes (e.g. after view switch to empty view) */
export async function waitForCanvas(page: Page): Promise<void> {
    await page.waitForSelector('#cvat_canvas_wrapper', { state: 'visible', timeout: 15000 });
    await page.waitForTimeout(500);
}

export async function getShapeCount(page: Page): Promise<number> {
    return page.locator('#cvat_canvas_content .cvat_canvas_shape').count();
}

export async function getFrameNumber(page: Page): Promise<number> {
    const val = await page.locator('.cvat-player-frame-selector input[role="spinbutton"]').inputValue();
    return Number(val);
}

export async function clickViewButton(page: Page, viewId: number): Promise<void> {
    // View buttons are div.multiview-cell[role="button"] in the grid,
    // or separate button elements in the workspace panel.
    // Use getByRole which matches both <button> and [role="button"]
    const btn = page.getByRole('button', { name: new RegExp(`^View ${viewId}\\b`) });
    await btn.first().click({ timeout: 10000 });
    await page.waitForTimeout(800);
}

export async function getActiveViewText(page: Page): Promise<string> {
    const btn = page.getByRole('button', { name: /Active/ });
    return btn.first().innerText();
}

export function getZoomScale(page: Page): Promise<number> {
    return page.evaluate(() => {
        const wrapper = document.querySelector('.zoom-wrapper') as HTMLElement;
        if (!wrapper) return 1;
        const match = wrapper.style.transform?.match(/scale\(([^)]+)\)/);
        return match ? parseFloat(match[1]) : 1;
    });
}
