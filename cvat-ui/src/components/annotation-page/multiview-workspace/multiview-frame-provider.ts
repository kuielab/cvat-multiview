// Copyright (C) 2026 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

type MultiviewFrameResult = {
    renderWidth: number;
    renderHeight: number;
    imageData: ImageBitmap;
};

const MAX_CACHE_ENTRIES = 200;
const cache = new Map<string, MultiviewFrameResult>();
const inflight = new Map<string, Promise<MultiviewFrameResult>>();

function makeCacheKey(taskId: number, viewId: number, frameNumber: number, quality: 'compressed' | 'original'): string {
    return `${taskId}:${viewId}:${frameNumber}:${quality}`;
}

function touchCacheEntry(key: string, entry: MultiviewFrameResult): void {
    if (cache.has(key)) {
        cache.delete(key);
    }
    cache.set(key, entry);
}

function evictIfNeeded(): void {
    while (cache.size > MAX_CACHE_ENTRIES) {
        const oldestKey = cache.keys().next().value as string | undefined;
        if (!oldestKey) break;
        const entry = cache.get(oldestKey);
        if (entry?.imageData && typeof entry.imageData.close === 'function') {
            entry.imageData.close();
        }
        cache.delete(oldestKey);
    }
}

export async function fetchMultiviewFrameImage(params: {
    taskId: number;
    viewId: number;
    frameNumber: number;
    quality?: 'compressed' | 'original';
    renderWidthFallback?: number;
    renderHeightFallback?: number;
}): Promise<MultiviewFrameResult> {
    const {
        taskId,
        viewId,
        frameNumber,
        quality = 'compressed',
        renderWidthFallback = 0,
        renderHeightFallback = 0,
    } = params;

    const key = makeCacheKey(taskId, viewId, frameNumber, quality);
    const cached = cache.get(key);
    if (cached) {
        touchCacheEntry(key, cached);
        return cached;
    }

    const pending = inflight.get(key);
    if (pending) {
        return pending;
    }

    const request = (async (): Promise<MultiviewFrameResult> => {
        const url = `/api/tasks/${taskId}/multiview/frame/${viewId}?number=${frameNumber}&quality=${quality}`;
        const response = await fetch(url, { credentials: 'same-origin' });
        if (!response.ok) {
            throw new Error(`Failed to fetch multiview frame: ${response.status}`);
        }
        const blob = await response.blob();
        const imageData = await createImageBitmap(blob);
        const renderWidth = imageData.width || renderWidthFallback;
        const renderHeight = imageData.height || renderHeightFallback;
        return { renderWidth, renderHeight, imageData };
    })();

    inflight.set(key, request);
    try {
        const result = await request;
        touchCacheEntry(key, result);
        evictIfNeeded();
        return result;
    } finally {
        inflight.delete(key);
    }
}

export function clearMultiviewFrameCache(): void {
    cache.forEach((entry) => {
        if (entry?.imageData && typeof entry.imageData.close === 'function') {
            entry.imageData.close();
        }
    });
    cache.clear();
    inflight.clear();
}
