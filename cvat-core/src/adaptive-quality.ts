// Copyright (C) 2026 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { ChunkQuality } from 'cvat-data';

const MAX_DOWNLOAD_RATIO = 0.7; // download must finish within 70% of chunk play time
const PROBE_INTERVAL = 5; // try ORIGINAL every N chunks after downgrade

/**
 * Adaptive quality tracker for multiview chunk downloads.
 *
 * Starts with ORIGINAL quality. If a chunk download takes longer than
 * 70% of the chunk's playback duration, switches to COMPRESSED.
 * Periodically probes ORIGINAL to detect network recovery.
 *
 * Call `getQuality()` (read-only) to check current quality level.
 * Call `onChunkRequested()` from the primary fetch path only to advance the probe counter.
 * Call `recordDownload()` after each fetch to feed timing data.
 */
export class AdaptiveQualityTracker {
    private currentQuality: ChunkQuality = ChunkQuality.ORIGINAL;
    private chunksSinceProbe = 0;
    private isProbing = false;
    private chunkPlayDurationMs: number;

    constructor(chunkPlayDurationMs: number) {
        this.chunkPlayDurationMs = chunkPlayDurationMs;
    }

    /**
     * Read-only: returns the current quality level without side effects.
     */
    getQuality(): ChunkQuality {
        if (this.currentQuality === ChunkQuality.ORIGINAL) {
            return ChunkQuality.ORIGINAL;
        }

        if (this.chunksSinceProbe >= PROBE_INTERVAL) {
            return ChunkQuality.ORIGINAL;
        }

        return ChunkQuality.COMPRESSED;
    }

    /**
     * Advance the probe counter. Call ONLY from the primary fetch path
     * (getMultiviewFrame), not from prefetch or warmCache.
     */
    onChunkRequested(): void {
        if (this.currentQuality === ChunkQuality.COMPRESSED) {
            this.chunksSinceProbe += 1;
            if (this.chunksSinceProbe >= PROBE_INTERVAL) {
                this.isProbing = true;
            }
        }
    }

    recordDownload(durationMs: number, quality: ChunkQuality): void {
        const threshold = this.chunkPlayDurationMs * MAX_DOWNLOAD_RATIO;

        if (quality === ChunkQuality.ORIGINAL) {
            if (durationMs > threshold) {
                // ORIGINAL too slow — downgrade
                this.currentQuality = ChunkQuality.COMPRESSED;
                this.chunksSinceProbe = 0;
                this.isProbing = false;
            } else if (this.isProbing) {
                // Probe succeeded — upgrade back to ORIGINAL
                this.currentQuality = ChunkQuality.ORIGINAL;
                this.chunksSinceProbe = 0;
                this.isProbing = false;
            }
        }
    }

    reset(): void {
        this.currentQuality = ChunkQuality.ORIGINAL;
        this.chunksSinceProbe = 0;
        this.isProbing = false;
    }
}

let tracker: AdaptiveQualityTracker | null = null;

/**
 * Get the singleton adaptive quality tracker.
 * @param chunkPlayDurationMs - chunk playback duration in ms (chunkSize / fps * 1000).
 *   Only used on first call to initialize; ignored on subsequent calls.
 *   Defaults to 3600ms (36 frames at 10fps).
 */
export function getAdaptiveQualityTracker(chunkPlayDurationMs?: number): AdaptiveQualityTracker {
    if (!tracker) {
        const duration = chunkPlayDurationMs ?? 3600;
        tracker = new AdaptiveQualityTracker(duration);
    }
    return tracker;
}

export function resetAdaptiveQuality(): void {
    if (tracker) {
        tracker.reset();
    }
}
