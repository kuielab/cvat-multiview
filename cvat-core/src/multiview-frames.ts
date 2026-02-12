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
 * Prefetch the next chunk in the background when playback is past 50% of the current chunk.
 * This eliminates stalls at chunk boundaries during sequential playback.
 */
function maybePrefetchNextChunk(
    cache: typeof multiviewFrameDataCache[CacheKey],
    frameNumber: number,
    chunkIndex: number,
): void {
    // Only prefetch during forward playback
    const posInChunk = frameNumber - chunkIndex * cache.chunkSize;
    const halfChunk = Math.floor(cache.chunkSize / 2);
    if (posInChunk < halfChunk) return;

    const nextChunkIndex = chunkIndex + 1;
    const totalChunks = Math.ceil(cache.segmentFrameNumbers.length / cache.chunkSize);
    if (nextChunkIndex >= totalChunks) return;

    // Already prefetching or decoded this chunk
    if (cache.prefetchingChunkIndex === nextChunkIndex) return;
    const nextChunkFirstFrame = cache.segmentFrameNumbers[nextChunkIndex * cache.chunkSize];
    if (nextChunkFirstFrame === undefined) return;
    if (cache.provider.frame(nextChunkFirstFrame) !== null) return;

    cache.prefetchingChunkIndex = nextChunkIndex;

    // Fire-and-forget: fetch chunk from server and decode in background
    cache.getChunk(nextChunkIndex, ChunkQuality.COMPRESSED).then((chunk: ArrayBuffer) => {
        cache.provider.requestDecodeBlock(
            chunk,
            nextChunkIndex,
            cache.segmentFrameNumbers.slice(
                nextChunkIndex * cache.chunkSize,
                (nextChunkIndex + 1) * cache.chunkSize,
            ),
            () => { /* onDecode per frame - no-op for prefetch */ },
            () => { cache.prefetchingChunkIndex = null; },
            () => { cache.prefetchingChunkIndex = null; },
        );
    }).catch(() => {
        cache.prefetchingChunkIndex = null;
    });
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
    const meta = await cache.getMeta();
    const dataFrameNumber = meta.getDataFrameNumber(frameNumber - jobStartFrame);
    const chunkIndex = meta.getFrameChunkIndex(dataFrameNumber);

    // Set render size so FrameDecoder's cropImage uses correct dimensions
    // (MP4VIDEO decoder may downscale, needs original dimensions to crop correctly)
    const frameMeta = meta.frames[0];
    cache.provider.setRenderSize(frameMeta.width, frameMeta.height);

    const cachedFrame = cache.provider.frame(frameNumber);
    if (cachedFrame) {
        // Cache hit: start prefetching next chunk in the background
        maybePrefetchNextChunk(cache, frameNumber, chunkIndex);

        return {
            renderWidth: meta.frames[0].width,
            renderHeight: meta.frames[0].height,
            imageData: cachedFrame,
        };
    }

    const requestId = Date.now();
    cache.latestFrameDecodeRequest = requestId;

    return new Promise((resolve, reject) => {
        (cache.activeChunkRequest || Promise.resolve()).finally(() => {
            if (cache.latestFrameDecodeRequest !== requestId) {
                reject(frameNumber);
                return;
            }

            const currentFrame = cache.provider.frame(frameNumber);
            if (currentFrame) {
                resolve({
                    renderWidth: meta.frames[0].width,
                    renderHeight: meta.frames[0].height,
                    imageData: currentFrame,
                });
                return;
            }

            cache.activeChunkRequest = new Promise<void>((resolveLoad) => {
                cache.getChunk(chunkIndex, ChunkQuality.COMPRESSED).then((chunk: ArrayBuffer) => {
                    try {
                        cache.provider.requestDecodeBlock(
                            chunk,
                            chunkIndex,
                            cache.segmentFrameNumbers.slice(
                                chunkIndex * cache.chunkSize,
                                (chunkIndex + 1) * cache.chunkSize,
                            ),
                            (_frame: number, bitmap: ImageBitmap | Blob) => {
                                if (cache.decodeForward) {
                                    return;
                                }
                                if (cache.latestFrameDecodeRequest === requestId && _frame === frameNumber) {
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
                                const decodedFrame = cache.provider.frame(frameNumber);
                                if (cache.decodeForward) {
                                    resolve({
                                        renderWidth: meta.frames[0].width,
                                        renderHeight: meta.frames[0].height,
                                        imageData: decodedFrame,
                                    });
                                } else if (!decodedFrame) {
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

export function clearMultiviewFramesCache(taskId?: number, viewId?: number): void {
    if (typeof taskId === 'number' && typeof viewId === 'number') {
        const key = makeKey(taskId, viewId);
        delete multiviewFrameMetaCache[key];
        delete multiviewFrameDataCache[key];
        return;
    }

    Object.keys(multiviewFrameMetaCache).forEach((key) => delete multiviewFrameMetaCache[key]);
    Object.keys(multiviewFrameDataCache).forEach((key) => delete multiviewFrameDataCache[key]);
}

export function getMultiviewSegmentFrameNumbers(
    taskId: number,
    viewId: number,
): Promise<number[]> {
    return getMultiviewFramesMeta(taskId, viewId).then((meta) => range(meta.startFrame, meta.stopFrame + 1, meta.frameStep));
}
