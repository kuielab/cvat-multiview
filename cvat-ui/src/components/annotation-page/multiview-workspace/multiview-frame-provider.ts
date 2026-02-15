// Copyright (C) 2026 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { getCore } from 'cvat-core-wrapper';

type MultiviewFrameResult = {
    renderWidth: number;
    renderHeight: number;
    imageData: ImageBitmap | Blob;
};

const cvat = getCore();

export async function fetchMultiviewFrameImage(params: {
    taskId: number;
    viewId: number;
    frameNumber: number;
    jobStartFrame: number;
    step: number;
}): Promise<MultiviewFrameResult> {
    const {
        taskId,
        viewId,
        frameNumber,
        jobStartFrame,
        step,
    } = params;

    return cvat.multiviewFrames.getFrame({
        taskId,
        viewId,
        frameNumber,
        jobStartFrame,
        isPlaying: false,
        step,
    });
}

export function clearMultiviewFrameCache(taskId?: number, viewId?: number): void {
    cvat.multiviewFrames.clearCache(taskId, viewId);
}

/**
 * Pre-decode the chunk for the given frame in the background (fire-and-forget).
 * Call during playback so the decoded ImageBitmap is ready when the user pauses.
 */
export function warmMultiviewFrameCache(params: {
    taskId: number;
    viewId: number;
    frameNumber: number;
    jobStartFrame: number;
}): void {
    cvat.multiviewFrames.warmCache(params);
}
