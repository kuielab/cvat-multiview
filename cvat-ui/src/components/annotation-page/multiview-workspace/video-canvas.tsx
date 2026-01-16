// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useRef, useEffect, useCallback, useState } from 'react';

interface VideoDisplayArea {
    width: number;
    height: number;
    offsetX: number;
    offsetY: number;
}

interface Props {
    viewId: number;
    frameNumber: number;
    videoUrl: string;
    fps: number;
    isActive: boolean;
    playing: boolean;
    playbackRate?: number;
    onCanvasContainerReady?: (container: HTMLDivElement | null, videoElement: HTMLVideoElement | null) => void;
    onVideoRef?: (viewId: number, video: HTMLVideoElement | null) => void;
}

/**
 * Calculate the actual display area of a video with object-fit: contain
 * This accounts for letterboxing (black bars) when the video aspect ratio
 * doesn't match the container aspect ratio.
 */
function calculateVideoDisplayArea(
    containerWidth: number,
    containerHeight: number,
    videoWidth: number,
    videoHeight: number,
): VideoDisplayArea {
    if (containerWidth <= 0 || containerHeight <= 0 || videoWidth <= 0 || videoHeight <= 0) {
        return { width: containerWidth, height: containerHeight, offsetX: 0, offsetY: 0 };
    }

    const containerAspect = containerWidth / containerHeight;
    const videoAspect = videoWidth / videoHeight;

    let displayWidth: number;
    let displayHeight: number;
    let offsetX: number;
    let offsetY: number;

    if (containerAspect > videoAspect) {
        // Container is wider than video - letterbox on left/right
        displayHeight = containerHeight;
        displayWidth = displayHeight * videoAspect;
        offsetX = (containerWidth - displayWidth) / 2;
        offsetY = 0;
    } else {
        // Container is taller than video - letterbox on top/bottom
        displayWidth = containerWidth;
        displayHeight = displayWidth / videoAspect;
        offsetX = 0;
        offsetY = (containerHeight - displayHeight) / 2;
    }

    return { width: displayWidth, height: displayHeight, offsetX, offsetY };
}

export default function VideoCanvas(props: Props): JSX.Element {
    const {
        viewId, frameNumber, videoUrl, fps, isActive, playing, playbackRate, onCanvasContainerReady, onVideoRef,
    } = props;

    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [videoDisplayArea, setVideoDisplayArea] = useState<VideoDisplayArea | null>(null);

    // Use callback ref to report video element to parent when mounted
    const videoCallbackRef = useCallback((node: HTMLVideoElement | null) => {
        (videoRef as React.MutableRefObject<HTMLVideoElement | null>).current = node;
        if (onVideoRef) {
            onVideoRef(viewId, node);
        }
    }, [viewId, onVideoRef]);

    // Use callback ref to notify parent when DOM element is ready AND video metadata is loaded
    // Fix 3: Wait for video metadata to be loaded before calling callback
    // This ensures videoDimensions will be valid when canvas setup runs
    const canvasContainerCallbackRef = useCallback((node: HTMLDivElement | null) => {
        if (!onCanvasContainerReady) return;

        const video = videoRef.current;

        // If node is null (unmounting) or video is null, call callback immediately
        if (!node || !video) {
            onCanvasContainerReady(node, video);
            return;
        }

        // Check if metadata already loaded
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            // Metadata already loaded - call callback immediately
            onCanvasContainerReady(node, video);
        } else {
            // Wait for metadata to load before calling callback
            const handleMetadataLoaded = (): void => {
                video.removeEventListener('loadedmetadata', handleMetadataLoaded);
                onCanvasContainerReady(node, video);
            };
            video.addEventListener('loadedmetadata', handleMetadataLoaded);
        }
    }, [onCanvasContainerReady, isActive, viewId]);

    // Cleanup when becoming inactive
    useEffect(() => {
        if (!isActive && onCanvasContainerReady) {
            onCanvasContainerReady(null, null);
        }
    }, [isActive, onCanvasContainerReady]);

    /**
     * Calculate video display area when:
     * - Video metadata loads (provides video dimensions)
     * - Container resizes
     * This ensures the canvas overlay exactly matches the video display area,
     * accounting for object-fit: contain letterboxing.
     */
    useEffect(() => {
        const video = videoRef.current;
        const container = containerRef.current;

        if (!video || !container) return;

        const updateDisplayArea = (): void => {
            const containerRect = container.getBoundingClientRect();
            const videoWidth = video.videoWidth;
            const videoHeight = video.videoHeight;

            if (videoWidth > 0 && videoHeight > 0) {
                const displayArea = calculateVideoDisplayArea(
                    containerRect.width,
                    containerRect.height,
                    videoWidth,
                    videoHeight,
                );
                setVideoDisplayArea(displayArea);
            }
        };

        // Update when video metadata loads
        const handleLoadedMetadata = (): void => {
            updateDisplayArea();
        };

        // Update on resize
        const resizeObserver = new ResizeObserver(() => {
            updateDisplayArea();
        });

        video.addEventListener('loadedmetadata', handleLoadedMetadata);
        resizeObserver.observe(container);

        // Initial calculation if video is already loaded
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            updateDisplayArea();
        }

        return () => {
            video.removeEventListener('loadedmetadata', handleLoadedMetadata);
            resizeObserver.disconnect();
        };
    }, [videoUrl]);

    // ALL video control (play/pause/seek) is handled by parent component
    // This component only renders the video element

    // Calculate inline styles for canvas overlay to match video display area
    const canvasOverlayStyle: React.CSSProperties = videoDisplayArea ? {
        position: 'absolute',
        left: `${videoDisplayArea.offsetX}px`,
        top: `${videoDisplayArea.offsetY}px`,
        width: `${videoDisplayArea.width}px`,
        height: `${videoDisplayArea.height}px`,
    } : {
        // Fallback to full container if display area not calculated yet
        position: 'absolute',
        left: 0,
        top: 0,
        width: '100%',
        height: '100%',
    };

    return (
        <div ref={containerRef} className='video-canvas-container'>
            <video
                ref={videoCallbackRef}
                src={videoUrl}
                className='multiview-video'
                playsInline
                crossOrigin="anonymous"
                muted={!isActive}
            />
            {isActive && (
                <div
                    ref={canvasContainerCallbackRef}
                    className='annotation-canvas-overlay active-canvas'
                    style={canvasOverlayStyle}
                />
            )}
            <div className='view-label'>
                View {viewId}
                {isActive && <span className='active-indicator'> (Active)</span>}
            </div>
        </div>
    );
}
