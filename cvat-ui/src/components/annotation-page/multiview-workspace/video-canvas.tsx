// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useRef, useEffect, useCallback } from 'react';
import MultiviewCanvasPreview from './multiview-canvas-preview';

interface Props {
    viewId: number;
    isActive: boolean;
    onCanvasContainerReady?: (container: HTMLDivElement | null) => void;
    onPan?: (dx: number, dy: number) => void;
    onZoomReset?: () => void;
}

export default function VideoCanvas(props: Props): JSX.Element {
    const {
        viewId, isActive,
        onCanvasContainerReady, onPan, onZoomReset,
    } = props;

    const containerRef = useRef<HTMLDivElement>(null);
    const previewContainerRef = useRef<HTMLDivElement>(null);

    // Pan state for panning when zoomed in
    const isPanningRef = useRef(false);
    const panStartRef = useRef({ x: 0, y: 0 });
    // Track actual pan distance to suppress click events after left-click pan
    const panDistanceRef = useRef(0);

    // Notify parent when the canvas container is ready.
    const canvasContainerCallbackRef = useCallback((node: HTMLDivElement | null) => {
        if (!onCanvasContainerReady) return;

        onCanvasContainerReady(node);
    }, [onCanvasContainerReady]);

    // Cleanup when becoming inactive
    useEffect(() => {
        if (!isActive && onCanvasContainerReady) {
            onCanvasContainerReady(null);
        }
    }, [isActive, onCanvasContainerReady]);

    // No HTMLVideoElement rendering in canvas-only mode.

    /**
     * Pan support when zoomed in.
     * - Middle button (1), Right button (2), Alt+Left (0): pan when zoomed
     * - Left button (0) without Alt: NOT used for panning (allows drawing and shape interaction)
     * Listens on the container so pan works over both video and canvas overlay.
     */
    useEffect(() => {
        const container = containerRef.current;
        if (!container || !isActive) return undefined;

        const handleMouseDown = (e: MouseEvent): void => {
            // Middle button (1), Right button (2), Alt+Left (0) - pan when zoomed
            if (e.button === 1 || e.button === 2 || (e.button === 0 && e.altKey)) {
                e.preventDefault();
                isPanningRef.current = true;
                panDistanceRef.current = 0;
                panStartRef.current = { x: e.clientX, y: e.clientY };
                return;
            }
        };

        const handleMouseMove = (e: MouseEvent): void => {
            if (!isPanningRef.current || !onPan) return;
            const dx = e.clientX - panStartRef.current.x;
            const dy = e.clientY - panStartRef.current.y;
            panStartRef.current = { x: e.clientX, y: e.clientY };
            panDistanceRef.current += Math.abs(dx) + Math.abs(dy);
            onPan(dx, dy);
        };

        const handleMouseUp = (): void => {
            isPanningRef.current = false;
        };

        // Suppress click events that follow a left-click pan drag.
        // Without this, releasing the mouse after panning would fire a click
        // event that could activate a shape or trigger unwanted actions.
        const handleClick = (e: MouseEvent): void => {
            if (panDistanceRef.current > 3) {
                e.stopPropagation();
                e.preventDefault();
                panDistanceRef.current = 0;
            }
        };

        // Prevent context menu when right-click is used for panning (zoomed state only).
        // Use capture phase + stopPropagation to prevent CVAT's CanvasContextMenuContainer
        // from opening on right-click release.
        const handleContextMenu = (e: MouseEvent): void => {
            e.preventDefault();
            e.stopPropagation();
        };

        // Use capture phase so pan intercepts before canvas sees events
        container.addEventListener('mousedown', handleMouseDown, { capture: true });
        container.addEventListener('click', handleClick, { capture: true });
        container.addEventListener('contextmenu', handleContextMenu, { capture: true });
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);

        return () => {
            container.removeEventListener('mousedown', handleMouseDown, { capture: true } as EventListenerOptions);
            container.removeEventListener('click', handleClick, { capture: true } as EventListenerOptions);
            container.removeEventListener('contextmenu', handleContextMenu, { capture: true } as EventListenerOptions);
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
        }, [isActive, onPan]);

    /**
     * Double-click to reset zoom (only when zoomed in).
     */
    const handleDoubleClick = useCallback((e: React.MouseEvent): void => {
        if (!onZoomReset) return;
        e.preventDefault();
        e.stopPropagation();
        onZoomReset();
    }, [onZoomReset]);

    // ALL video control (play/pause/seek) is handled by parent component
    // This component only renders the video element

    const showPreview = !isActive;

    // Calculate inline styles for canvas overlay.
    // In canvas render mode (active view), use full container size to avoid letterboxing logic.
    const canvasOverlayStyle: React.CSSProperties = {
        position: 'absolute',
        left: 0,
        top: 0,
        width: '100%',
        height: '100%',
    };

    // CSS transform for zoom: translate then scale from origin (0,0).
    // Disabled in canvas render mode (canvas handles zoom/pan directly).
    const zoomWrapperStyle: React.CSSProperties = {
        width: '100%',
        height: '100%',
        position: 'relative' as const,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
    };

    return (
        <div ref={containerRef} className='video-canvas-container' onDoubleClick={handleDoubleClick}>
            <div className='zoom-wrapper' style={zoomWrapperStyle}>
                {isActive && (
                    <div
                        ref={canvasContainerCallbackRef}
                        className='annotation-canvas-overlay active-canvas'
                        style={canvasOverlayStyle}
                    />
                )}
                {showPreview && (
                    <div
                        ref={previewContainerRef}
                        className='annotation-canvas-preview'
                        style={canvasOverlayStyle}
                    />
                )}
                {showPreview && (
                    <MultiviewCanvasPreview
                        container={previewContainerRef.current}
                        viewId={viewId}
                    />
                )}
            </div>
            <div className='view-label'>
                View {viewId}
                {isActive && <span className='active-indicator'> (Active)</span>}
            </div>
        </div>
    );
}
