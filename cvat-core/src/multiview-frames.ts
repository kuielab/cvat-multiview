// Copyright (C) 2026 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { range } from 'lodash';
import {
    FrameDecoder,
    BlockType,
    DimensionType,
    ChunkQuality,
    RequestOutdatedError,
} from 'cvat-data';
import { FramesMetaData } from './frames';
import serverProxy from './server-proxy';
import { SerializedFramesMetaData } from './server-response-types';

type CacheKey = string;

function makeKey(taskId: number, viewId: number): CacheKey {
    return `${taskId}:${viewId}`;
}

const multiviewFrameMetaCache: Record<CacheKey, Promise<FramesMetaData>> = {};

const multiviewFrameDataCache: Record<CacheKey, {
    metaFetchedTimestamp: number;
    chunkSize: number;
    jobStartFrame: number;
    decodeForward: boolean;
    forwardStep: number;
    latestFrameDecodeRequest: number | null;
    provider: FrameDecoder;
    decodedBlocksCacheSize: number;
    activeChunkRequest: Promise<void> | null;
    prefetchingChunkIndex: number | null;
    segmentFrameNumbers: number[];
    getChunk: (chunkIndex: number, quality: ChunkQuality) => Promise<ArrayBuffer>;
    getMeta: () => Promise<FramesMetaData>;
}> = {};

async function fetchMultiviewMeta(taskId: number, viewId: number): Promise<FramesMetaData> {
    const serialized: SerializedFramesMetaData = await serverProxy.multiview.getMeta(taskId, viewId);
    return new FramesMetaData({
        ...serialized,
        deleted_frames: Object.fromEntries(serialized.deleted_frames.map((_frame) => [_frame, true])),
    });
}

export function getMultiviewFramesMeta(taskId: number, viewId: number): Promise<FramesMetaData> {
    const key = makeKey(taskId, viewId);
    if (!multiviewFrameMetaCache[key]) {
        multiviewFrameMetaCache[key] = fetchMultiviewMeta(taskId, viewId);
    }
    return multiviewFrameMetaCache[key];
}

/**
 * Prefetch upcoming chunks in the background during forward playback.
 * Prefetches up to 2 chunks ahead to eliminate stalls at chunk boundaries on slow networks (EC2).
 */
function maybePrefetchChunks(
    cache: typeof multiviewFrameDataCache[CacheKey],
    frameNumber: number,
    chunkIndex: number,
): void {
    const totalChunks = Math.ceil(cache.segmentFrameNumbers.length / cache.chunkSize);

    // Prefetch up to 2 chunks ahead
    for (let offset = 1; offset <= 2; offset++) {
        const targetChunkIndex = chunkIndex + offset;
        if (targetChunkIndex >= totalChunks) break;

        // For the first next chunk, start prefetch at 30% into current chunk
        // For the second, start at 60%
        const posInChunk = frameNumber - chunkIndex * cache.chunkSize;
        const threshold = Math.floor(cache.chunkSize * 0.3 * offset);
        if (posInChunk < threshold) break;

        // Skip if already prefetching or already cached
        if (cache.prefetchingChunkIndex === targetChunkIndex) continue;
        const firstFrame = cache.segmentFrameNumbers[targetChunkIndex * cache.chunkSize];
        if (firstFrame === undefined) continue;
        if (cache.provider.frame(firstFrame) !== null) continue;

        cache.prefetchingChunkIndex = targetChunkIndex;

        // Fire-and-forget: fetch chunk from server and decode in background
        cache.getChunk(targetChunkIndex, ChunkQuality.COMPRESSED).then((chunk: ArrayBuffer) => {
            // Guard: if getMultiviewFrame started a decode while HTTP was in-flight, bail out
            // to avoid requestDecodeBlock callback conflicts
            if (cache.activeChunkRequest !== null) {
                cache.prefetchingChunkIndex = null;
                return;
            }
            cache.provider.requestDecodeBlock(
                chunk,
                targetChunkIndex,
                cache.segmentFrameNumbers.slice(
                    targetChunkIndex * cache.chunkSize,
                    (targetChunkIndex + 1) * cache.chunkSize,
                ),
                () => { /* onDecode per frame - no-op for prefetch */ },
                () => { cache.prefetchingChunkIndex = null; },
                () => { cache.prefetchingChunkIndex = null; },
            );
        }).catch(() => {
            cache.prefetchingChunkIndex = null;
        });

        // Only one prefetch at a time (limited by prefetchingChunkIndex)
        break;
    }
}

export async function getMultiviewFrame(params: {
    taskId: number;
    viewId: number;
    frameNumber: number;
    jobStartFrame: number;
    isPlaying: boolean;
    step: number;
}): Promise<{ renderWidth: number; renderHeight: number; imageData: ImageBitmap | Blob }> {
    const {
        taskId,
        viewId,
        frameNumber,
        jobStartFrame,
        isPlaying,
        step,
    } = params;

    const key = makeKey(taskId, viewId);
    const dataCacheExists = key in multiviewFrameDataCache;

    if (!dataCacheExists) {
        const meta = await getMultiviewFramesMeta(taskId, viewId);
        const mean = meta.frames.reduce((a, b) => a + b.width * b.height, 0) / meta.frames.length;
        const stdDev = Math.sqrt(
            meta.frames.map((x) => (x.width * x.height - mean) ** 2).reduce((a, b) => a + b) /
            meta.frames.length,
        );

        const decodedBlocksCacheSize = Math.min(
            Math.floor((2048 * 1024 * 1024) / ((mean + stdDev) * 4 * meta.chunkSize)) || 1, 10,
        );

        const dataFrameNumberGetter = (frame: number): number => (
            meta.getDataFrameNumber(frame - jobStartFrame)
        );

        multiviewFrameDataCache[key] = {
            metaFetchedTimestamp: Date.now(),
            chunkSize: meta.chunkSize,
            jobStartFrame,
            decodeForward: isPlaying,
            forwardStep: step,
            latestFrameDecodeRequest: null,
            provider: new FrameDecoder(
                BlockType.MP4VIDEO,
                decodedBlocksCacheSize,
                (frame: number): number => (
                    meta.getFrameChunkIndex(dataFrameNumberGetter(frame))
                ),
                DimensionType.DIM_2D,
            ),
            decodedBlocksCacheSize,
            activeChunkRequest: null,
            prefetchingChunkIndex: null,
            segmentFrameNumbers: meta.getSegmentFrameNumbers(jobStartFrame),
            getChunk: (chunkIndex, quality) => serverProxy.multiview.getData(taskId, viewId, chunkIndex, quality),
            getMeta: () => getMultiviewFramesMeta(taskId, viewId),
        };
    }

    const cache = multiviewFrameDataCache[key];

    // Update decode strategy per request: during playback wait for full block (faster sequential),
    // when paused resolve per-frame (faster seeking to specific frame)
    cache.decodeForward = isPlaying;
    cache.forwardStep = step;

    const meta = await cache.getMeta();
    const dataFrameNumber = meta.getDataFrameNumber(frameNumber - jobStartFrame);
    const chunkIndex = meta.getFrameChunkIndex(dataFrameNumber);

    // Set render size so FrameDecoder's cropImage uses correct dimensions
    // (MP4VIDEO decoder may downscale, needs original dimensions to crop correctly)
    const frameMeta = meta.frames[0];
    cache.provider.setRenderSize(frameMeta.width, frameMeta.height);

    const cachedFrame = cache.provider.frame(frameNumber);
    if (cachedFrame) {
        // Cache hit: start prefetching upcoming chunks in the background
        maybePrefetchChunks(cache, frameNumber, chunkIndex);
        console.debug(`[MV] f${frameNumber} cache-hit`);

        return {
            renderWidth: meta.frames[0].width,
            renderHeight: meta.frames[0].height,
            imageData: cachedFrame,
        };
    }

    const requestId = Date.now();
    cache.latestFrameDecodeRequest = requestId;

    return new Promise((resolve, reject) => {
        // A: per-frame resolve — resolve as soon as requested frame is decoded,
        // regardless of decodeForward. Prevents blocking until entire chunk completes.
        let resolved = false;

        (cache.activeChunkRequest || Promise.resolve()).finally(() => {
            if (cache.latestFrameDecodeRequest !== requestId) {
                reject(frameNumber);
                return;
            }

            const currentFrame = cache.provider.frame(frameNumber);
            if (currentFrame) {
                resolved = true;
                console.debug(`[MV] f${frameNumber} cached-after-wait ${Date.now() - requestId}ms`);
                resolve({
                    renderWidth: meta.frames[0].width,
                    renderHeight: meta.frames[0].height,
                    imageData: currentFrame,
                });
                return;
            }

            cache.activeChunkRequest = new Promise<void>((resolveLoad) => {
                const fetchStart = Date.now();
                cache.getChunk(chunkIndex, ChunkQuality.COMPRESSED).then((chunk: ArrayBuffer) => {
                    const fetchTime = Date.now() - fetchStart;
                    try {
                        cache.provider.requestDecodeBlock(
                            chunk,
                            chunkIndex,
                            cache.segmentFrameNumbers.slice(
                                chunkIndex * cache.chunkSize,
                                (chunkIndex + 1) * cache.chunkSize,
                            ),
                            (_frame: number, bitmap: ImageBitmap | Blob) => {
                                // Resolve immediately when requested frame is decoded
                                if (resolved) return;
                                if (cache.latestFrameDecodeRequest === requestId && _frame === frameNumber) {
                                    resolved = true;
                                    console.debug(
                                        `[MV] f${frameNumber} per-frame ${Date.now() - requestId}ms ` +
                                        `(fetch=${fetchTime}ms) chunk#${chunkIndex}`,
                                    );
                                    resolve({
                                        renderWidth: meta.frames[0].width,
                                        renderHeight: meta.frames[0].height,
                                        imageData: bitmap,
                                    });
                                }
                            },
                            () => {
                                cache.activeChunkRequest = null;
                                resolveLoad();
                                // Fallback: if per-frame callback didn't fire for this frame
                                if (resolved) return;
                                const decodedFrame = cache.provider.frame(frameNumber);
                                if (decodedFrame) {
                                    resolved = true;
                                    console.debug(
                                        `[MV] f${frameNumber} block-done ${Date.now() - requestId}ms ` +
                                        `(fetch=${fetchTime}ms) chunk#${chunkIndex}`,
                                    );
                                    resolve({
                                        renderWidth: meta.frames[0].width,
                                        renderHeight: meta.frames[0].height,
                                        imageData: decodedFrame,
                                    });
                                } else {
                                    reject(frameNumber);
                                }
                            },
                            (error: Error | RequestOutdatedError) => {
                                cache.activeChunkRequest = null;
                                resolveLoad();
                                if (error instanceof RequestOutdatedError) {
                                    reject(frameNumber);
                                } else {
                                    reject(error);
                                }
                            },
                        );
                    } catch (error) {
                        reject(error);
                    }
                }).catch((error) => {
                    reject(error);
                    resolveLoad();
                });
            });
        });
    });
}

/**
 * Track which chunk is being warmed per view (prevents duplicate warm requests).
 * null = idle, number = chunk index being fetched+decoded.
 */
const warmingChunks: Record<CacheKey, number | null> = {};

/**
 * Pre-decode the chunk containing `frameNumber` in the background during playback.
 * Broadway.js runs in a Web Worker, so this does NOT block the main thread.
 * When the user pauses, getMultiviewFrame() will find the frame already cached
 * and return instantly — eliminating the freeze.
 *
 * Fire-and-forget: returns synchronously, decode happens in background.
 */
export function warmCacheForFrame(params: {
    taskId: number;
    viewId: number;
    frameNumber: number;
    jobStartFrame: number;
}): void {
    const {
        taskId, viewId, frameNumber, jobStartFrame,
    } = params;
    const key = makeKey(taskId, viewId);
    const cache = multiviewFrameDataCache[key];

    // Skip if cache not initialized (first canvas setup() will handle it)
    if (!cache) return;

    // Already decoded — nothing to do
    if (cache.provider.frame(frameNumber) !== null) return;

    // Already warming a chunk for this view — avoid duplicate requests
    if (key in warmingChunks && warmingChunks[key] !== null) return;

    // Skip if getMultiviewFrame() is actively decoding — avoid FrameDecoder
    // requestDecodeBlock callback replacement race condition
    if (cache.activeChunkRequest !== null) return;

    // Async chain: resolve meta → compute chunk → fetch → decode (all background)
    cache.getMeta().then((meta) => {
        const dataFrameNumber = meta.getDataFrameNumber(frameNumber - jobStartFrame);
        const chunkIndex = meta.getFrameChunkIndex(dataFrameNumber);

        // Double-check after async: frame might have been decoded while awaiting meta
        if (cache.provider.frame(frameNumber) !== null) return;

        // Skip if getMultiviewFrame started a decode while we awaited meta
        if (cache.activeChunkRequest !== null) return;

        // Skip if maybePrefetchChunks is already fetching this chunk
        if (cache.prefetchingChunkIndex === chunkIndex) return;

        warmingChunks[key] = chunkIndex;
        cache.provider.setRenderSize(meta.frames[0].width, meta.frames[0].height);

        cache.getChunk(chunkIndex, ChunkQuality.COMPRESSED).then((chunk: ArrayBuffer) => {
            // Final guard: if getMultiviewFrame started between fetch and decode, bail out
            if (cache.activeChunkRequest !== null) {
                warmingChunks[key] = null;
                return;
            }
            cache.provider.requestDecodeBlock(
                chunk,
                chunkIndex,
                cache.segmentFrameNumbers.slice(
                    chunkIndex * cache.chunkSize,
                    (chunkIndex + 1) * cache.chunkSize,
                ),
                () => { /* per-frame decode callback — no-op for background warm */ },
                () => { warmingChunks[key] = null; },
                (_error: Error) => { warmingChunks[key] = null; },
            );
        }).catch(() => {
            warmingChunks[key] = null;
        });
    }).catch((error) => {
        console.debug('[MV] warmCache: meta fetch failed, will retry:', error?.message || error);
    });
}

export function clearMultiviewFramesCache(taskId?: number, viewId?: number): void {
    if (typeof taskId === 'number' && typeof viewId === 'number') {
        const key = makeKey(taskId, viewId);
        delete multiviewFrameMetaCache[key];
        delete multiviewFrameDataCache[key];
        delete warmingChunks[key];
        return;
    }

    Object.keys(multiviewFrameMetaCache).forEach((key) => delete multiviewFrameMetaCache[key]);
    Object.keys(multiviewFrameDataCache).forEach((key) => delete multiviewFrameDataCache[key]);
    Object.keys(warmingChunks).forEach((key) => delete warmingChunks[key]);
}

export function getMultiviewSegmentFrameNumbers(
    taskId: number,
    viewId: number,
): Promise<number[]> {
    return getMultiviewFramesMeta(taskId, viewId).then((meta) => range(meta.startFrame, meta.stopFrame + 1, meta.frameStep));
}
