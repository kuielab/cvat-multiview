// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { useCallback, useEffect, useRef, useState } from 'react';

type VideoDimsSource = 'video' | 'metadata' | null;

type StableVideoDimsState = {
    width: number;
    height: number;
    lastSampleWidth: number;
    lastSampleHeight: number;
    stableCount: number;
    viewId: number | null;
    source: VideoDimsSource;
    firstSampleTs: number | null;
};

function getVideoDimensionsFromMetadata(
    multiviewData: { videos: Record<string, { width: number; height: number }> | null } | null,
    activeViewId: number,
): { width: number; height: number } | null {
    if (!multiviewData?.videos) return null;
    const viewKey = `view${activeViewId}`;
    const viewData = multiviewData.videos[viewKey];
    if (viewData && viewData.width > 0 && viewData.height > 0) {
        return { width: viewData.width, height: viewData.height };
    }
    return null;
}

export function useStableVideoDims(params: {
    videoElement: HTMLVideoElement | null;
    activeViewId: number;
    multiviewData: { videos: Record<string, { width: number; height: number }> | null } | null;
    samplesRequired?: number;
    maxWaitMs?: number;
    debug?: boolean;
}): {
    getStableVideoDims: () => { width: number; height: number } | null;
    version: number;
} {
    const {
        videoElement,
        activeViewId,
        multiviewData,
        samplesRequired = 2,
        maxWaitMs = 800,
        debug = false,
    } = params;

    const stableVideoDimsRef = useRef<StableVideoDimsState>({
        width: 0,
        height: 0,
        lastSampleWidth: 0,
        lastSampleHeight: 0,
        stableCount: 0,
        viewId: null,
        source: null,
        firstSampleTs: null,
    });

    const [version, setVersion] = useState(0);

    const resetStableVideoDims = useCallback((viewId: number): void => {
        stableVideoDimsRef.current = {
            width: 0,
            height: 0,
            lastSampleWidth: 0,
            lastSampleHeight: 0,
            stableCount: 0,
            viewId,
            source: null,
            firstSampleTs: null,
        };
    }, []);

    useEffect(() => {
        resetStableVideoDims(activeViewId);
    }, [activeViewId, videoElement, resetStableVideoDims]);

    useEffect(() => {
        if (!videoElement) return;

        const handleVideoDimsChange = (): void => {
            setVersion((v) => v + 1);
        };

        videoElement.addEventListener('loadedmetadata', handleVideoDimsChange);
        videoElement.addEventListener('loadeddata', handleVideoDimsChange);
        videoElement.addEventListener('resize', handleVideoDimsChange);

        return () => {
            videoElement.removeEventListener('loadedmetadata', handleVideoDimsChange);
            videoElement.removeEventListener('loadeddata', handleVideoDimsChange);
            videoElement.removeEventListener('resize', handleVideoDimsChange);
        };
    }, [videoElement]);

    const getStableVideoDims = useCallback((): { width: number; height: number } | null => {
        const ref = stableVideoDimsRef.current;
        if (ref.viewId !== activeViewId) {
            resetStableVideoDims(activeViewId);
        }

        const now = Date.now();

        if (videoElement && videoElement.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
            const sampleWidth = videoElement.videoWidth;
            const sampleHeight = videoElement.videoHeight;

            if (sampleWidth > 0 && sampleHeight > 0) {
                if (ref.firstSampleTs === null) {
                    ref.firstSampleTs = now;
                }

                if (ref.width === sampleWidth && ref.height === sampleHeight && ref.source === 'video') {
                    return { width: ref.width, height: ref.height };
                }

                if (ref.lastSampleWidth === sampleWidth && ref.lastSampleHeight === sampleHeight) {
                    ref.stableCount += 1;
                } else {
                    ref.lastSampleWidth = sampleWidth;
                    ref.lastSampleHeight = sampleHeight;
                    ref.stableCount = 1;
                }

                if (ref.stableCount >= samplesRequired) {
                    ref.width = sampleWidth;
                    ref.height = sampleHeight;
                    ref.source = 'video';
                    if (debug) {
                        // eslint-disable-next-line no-console
                        console.debug('[MultiviewCanvas] Using stable video dims', ref.width, ref.height);
                    }
                    return { width: ref.width, height: ref.height };
                }

                if (ref.firstSampleTs !== null && now - ref.firstSampleTs >= maxWaitMs) {
                    ref.width = sampleWidth;
                    ref.height = sampleHeight;
                    ref.source = 'video';
                    if (debug) {
                        // eslint-disable-next-line no-console
                        console.debug('[MultiviewCanvas] Timeout fallback to current video dims', ref.width, ref.height);
                    }
                    return { width: ref.width, height: ref.height };
                }

                return null;
            }
        }

        if (!videoElement) {
            const metadataDims = getVideoDimensionsFromMetadata(multiviewData, activeViewId);
            if (metadataDims) {
                ref.width = metadataDims.width;
                ref.height = metadataDims.height;
                ref.source = 'metadata';
                if (debug) {
                    // eslint-disable-next-line no-console
                    console.debug('[MultiviewCanvas] Using metadata dims (no video element)', ref.width, ref.height);
                }
                return metadataDims;
            }
        }

        if (ref.width > 0 && ref.height > 0) {
            return { width: ref.width, height: ref.height };
        }

        return null;
    }, [activeViewId, videoElement, multiviewData, resetStableVideoDims, samplesRequired, maxWaitMs]);

    return { getStableVideoDims, version };
}
