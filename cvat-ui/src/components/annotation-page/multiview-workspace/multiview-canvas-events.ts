// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';

export type CanvasEventHandlers = {
    onShapeDrawn: ((e: any) => void) | null;
    onSetup: (() => void) | null;
    onCancel: (() => void) | null;
    onZoomStart: (() => void) | null;
    onZoomDone: (() => void) | null;
    onDragStart: (() => void) | null;
    onDragDone: (() => void) | null;
    onShapeClicked: ((e: any) => void) | null;
    onShapeDeactivated: ((e: any) => void) | null;
    onCursorMoved: ((e: any) => Promise<void>) | null;
    onEditDone: ((e: any) => void) | null;
    onMouseDown: ((e: MouseEvent) => void) | null;
    onMouseDownBubble: ((e: MouseEvent) => void) | null;
    onKeyDown: ((e: KeyboardEvent) => void) | null;
    onWheel: ((e: WheelEvent) => void) | null;
};

export function bindCanvasEventHandlers(
    canvasHTML: HTMLElement,
    eventHandlersRef: React.MutableRefObject<CanvasEventHandlers>,
): () => void {
    const handleShapeDrawn = (e: any): void => {
        eventHandlersRef.current.onShapeDrawn?.(e);
    };
    const handleSetup = (): void => {
        eventHandlersRef.current.onSetup?.();
    };
    const handleCancel = (): void => {
        eventHandlersRef.current.onCancel?.();
    };
    const handleZoomStart = (): void => {
        eventHandlersRef.current.onZoomStart?.();
    };
    const handleZoomDone = (): void => {
        eventHandlersRef.current.onZoomDone?.();
    };
    const handleDragStart = (): void => {
        eventHandlersRef.current.onDragStart?.();
    };
    const handleDragDone = (): void => {
        eventHandlersRef.current.onDragDone?.();
    };
    const handleShapeClicked = (e: any): void => {
        eventHandlersRef.current.onShapeClicked?.(e);
    };
    const handleShapeDeactivated = (e: any): void => {
        eventHandlersRef.current.onShapeDeactivated?.(e);
    };
    const handleCursorMoved = (e: any): void => {
        eventHandlersRef.current.onCursorMoved?.(e);
    };
    const handleEditDone = (e: any): void => {
        eventHandlersRef.current.onEditDone?.(e);
    };
    const handleMouseDown = (e: MouseEvent): void => {
        eventHandlersRef.current.onMouseDown?.(e);
    };
    const handleMouseDownBubble = (e: MouseEvent): void => {
        eventHandlersRef.current.onMouseDownBubble?.(e);
    };
    const handleKeyDown = (e: KeyboardEvent): void => {
        eventHandlersRef.current.onKeyDown?.(e);
    };
    const handleWheelWrapper = (e: WheelEvent): void => {
        eventHandlersRef.current.onWheel?.(e);
    };

    canvasHTML.addEventListener('canvas.drawn', handleShapeDrawn);
    canvasHTML.addEventListener('canvas.setup', handleSetup);
    canvasHTML.addEventListener('canvas.canceled', handleCancel);
    canvasHTML.addEventListener('canvas.zoomstart', handleZoomStart);
    canvasHTML.addEventListener('canvas.zoomstop', handleZoomDone);
    canvasHTML.addEventListener('canvas.dragstart', handleDragStart);
    canvasHTML.addEventListener('canvas.dragstop', handleDragDone);
    canvasHTML.addEventListener('canvas.clicked', handleShapeClicked);
    canvasHTML.addEventListener('canvas.deactivated', handleShapeDeactivated);
    canvasHTML.addEventListener('canvas.moved', handleCursorMoved as EventListener);
    canvasHTML.addEventListener('canvas.edited', handleEditDone);
    canvasHTML.addEventListener('mousedown', handleMouseDown, { capture: true });
    canvasHTML.addEventListener('wheel', handleWheelWrapper, { passive: false, capture: true });

    const svgContent = canvasHTML.querySelector('#cvat_canvas_content');
    if (svgContent) {
        svgContent.addEventListener('mousedown', handleMouseDownBubble, { capture: false });
    }

    document.addEventListener('keydown', handleKeyDown);

    return () => {
        canvasHTML.removeEventListener('canvas.drawn', handleShapeDrawn);
        canvasHTML.removeEventListener('canvas.setup', handleSetup);
        canvasHTML.removeEventListener('canvas.canceled', handleCancel);
        canvasHTML.removeEventListener('canvas.zoomstart', handleZoomStart);
        canvasHTML.removeEventListener('canvas.zoomstop', handleZoomDone);
        canvasHTML.removeEventListener('canvas.dragstart', handleDragStart);
        canvasHTML.removeEventListener('canvas.dragstop', handleDragDone);
        canvasHTML.removeEventListener('canvas.clicked', handleShapeClicked);
        canvasHTML.removeEventListener('canvas.deactivated', handleShapeDeactivated);
        canvasHTML.removeEventListener('canvas.moved', handleCursorMoved as EventListener);
        canvasHTML.removeEventListener('canvas.edited', handleEditDone);
        canvasHTML.removeEventListener('mousedown', handleMouseDown, { capture: true });
        canvasHTML.removeEventListener('wheel', handleWheelWrapper, { capture: true });
        if (svgContent) {
            svgContent.removeEventListener('mousedown', handleMouseDownBubble, { capture: false });
        }
        document.removeEventListener('keydown', handleKeyDown);
    };
}
