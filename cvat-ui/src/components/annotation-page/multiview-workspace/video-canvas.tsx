// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useRef, useEffect, useCallback, useState } from 'react';
import { ZoomState } from './multiview-workspace';

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
    zoomState?: ZoomState;
    onPan?: (dx: number, dy: number) => void;
    onZoomReset?: () => void;
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
        viewId, frameNumber, videoUrl, fps, isActive, playing, playbackRate,
        onCanvasContainerReady, onVideoRef, zoomState, onPan, onZoomReset,
    } = props;

    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [videoDisplayArea, setVideoDisplayArea] = useState<VideoDisplayArea | null>(null);

    // Pan state for middle-mouse-button / Alt+left drag
    const isPanningRef = useRef(false);
    const panStartRef = useRef({ x: 0, y: 0 });

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

        // Check if first frame already decoded (stable dimensions)
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0 && video.videoHeight > 0) {
            // First frame already decoded - call callback immediately
            onCanvasContainerReady(node, video);
        } else {
            // Wait for first frame decode ('loadeddata') instead of just metadata.
            // 'loadedmetadata' fires when headers are parsed but dimensions may not
            // be fully stable yet (codec initialization). 'loadeddata' fires after
            // the first frame is actually decoded, guaranteeing stable videoWidth/Height.
            const handleDataLoaded = (): void => {
                video.removeEventListener('loadeddata', handleDataLoaded);
                onCanvasContainerReady(node, video);
            };
            video.addEventListener('loadeddata', handleDataLoaded);
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
     */
    useEffect(() => {
        const video = videoRef.current;
        const container = containerRef.current;

        if (!video || !container) return;

        const updateDisplayArea = (): void => {
            const containerRect = container.getBoundingClientRect();

            // Use actual video dimensions for overlay positioning
            const width = video.videoWidth;
            const height = video.videoHeight;

            if (width > 0 && height > 0) {
                const displayArea = calculateVideoDisplayArea(
                    containerRect.width,
                    containerRect.height,
                    width,
                    height,
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

        // Initial calculation if video metadata already available
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            updateDisplayArea();
        }

        return () => {
            video.removeEventListener('loadedmetadata', handleLoadedMetadata);
            resizeObserver.disconnect();
        };
    }, [videoUrl]);

    /**
     * Middle-mouse-button / Alt+left-click pan support when zoomed in.
     * Listens on the container so pan works over both video and canvas overlay.
     */
    useEffect(() => {
        const container = containerRef.current;
        if (!container || !isActive) return undefined;

        const handleMouseDown = (e: MouseEvent): void => {
            // Middle button (1), Alt+Left (0), or Right button (2) for panning when zoomed
            const isPanTrigger = e.button === 1 || (e.button === 0 && e.altKey) || e.button === 2;
            if (!isPanTrigger) return;
            if (!zoomState || zoomState.level <= 1.0) return;

            e.preventDefault();
            isPanningRef.current = true;
            panStartRef.current = { x: e.clientX, y: e.clientY };
        };

        const handleMouseMove = (e: MouseEvent): void => {
            if (!isPanningRef.current || !onPan) return;
            const dx = e.clientX - panStartRef.current.x;
            const dy = e.clientY - panStartRef.current.y;
            panStartRef.current = { x: e.clientX, y: e.clientY };
            onPan(dx, dy);
        };

        const handleMouseUp = (): void => {
            isPanningRef.current = false;
        };

        // Prevent context menu when right-click is used for panning (zoomed state only)
        const handleContextMenu = (e: MouseEvent): void => {
            if (zoomState && zoomState.level > 1.0) {
                e.preventDefault();
            }
        };

        // Use capture phase so pan intercepts before canvas sees Alt+click
        container.addEventListener('mousedown', handleMouseDown, { capture: true });
        container.addEventListener('contextmenu', handleContextMenu);
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);

        return () => {
            container.removeEventListener('mousedown', handleMouseDown, { capture: true } as EventListenerOptions);
            container.removeEventListener('contextmenu', handleContextMenu);
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isActive, zoomState, onPan]);

    /**
     * Double-click to reset zoom (only when zoomed in).
     */
    const handleDoubleClick = useCallback((e: React.MouseEvent): void => {
        if (zoomState && zoomState.level > 1.0 && onZoomReset) {
            e.preventDefault();
            e.stopPropagation();
            onZoomReset();
        }
    }, [zoomState, onZoomReset]);

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

    // CSS transform for zoom: translate then scale from origin (0,0).
    // Both video and canvas overlay are inside the zoom-wrapper so they scale
    // together — bbox coordinates stay perfectly aligned with the video image.
    const zoomLevel = zoomState?.level ?? 1.0;
    const zoomWrapperStyle: React.CSSProperties = {
        width: '100%',
        height: '100%',
        position: 'relative' as const,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transformOrigin: '0 0',
        transform: zoomLevel > 1.0
            ? `translate(${zoomState!.translateX}px, ${zoomState!.translateY}px) scale(${zoomLevel})`
            : 'none',
        willChange: zoomLevel > 1.0 ? 'transform' : 'auto',
    };

    return (
        <div ref={containerRef} className='video-canvas-container' onDoubleClick={handleDoubleClick}>
            <div className='zoom-wrapper' style={zoomWrapperStyle}>
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
            </div>
            <div className='view-label'>
                View {viewId}
                {isActive && <span className='active-indicator'> (Active)</span>}
            </div>
            {isActive && zoomLevel > 1.0 && (
                <div className='zoom-indicator'>
                    {Math.round(zoomLevel * 100)}%
                </div>
            )}
        </div>
    );
}
