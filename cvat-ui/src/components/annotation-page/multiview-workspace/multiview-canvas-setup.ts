// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { Canvas } from 'cvat-canvas-wrapper';
import { ObjectState } from 'cvat-core-wrapper';

export function runSetupPipeline(params: {
    canvasInstance: Canvas;
    canvasContainer: HTMLDivElement | null;
    frameData: any;
    displayAnnotations: ObjectState[];
    curZLayer: number;
    viewChanged: boolean;
    isInitialSetup: boolean;
    activeViewId?: number;
    onViewportLocked?: () => void;
}): void {
    const {
        canvasInstance,
        canvasContainer,
        frameData,
        displayAnnotations,
        curZLayer,
        viewChanged,
        isInitialSetup,
        activeViewId,
        onViewportLocked,
    } = params;

    // Set viewId BEFORE setup() so that the async frame data callback in canvasModel.ts
    // captures the correct viewId (setupViewId = this.data.viewId). Without this,
    // the separate viewId effect may run after setup(), causing the callback to
    // see a stale viewId and early-return, resulting in a black canvas.
    if (activeViewId != null && typeof (canvasInstance as any).setViewId === 'function') {
        (canvasInstance as any).setViewId(activeViewId);
    }

    canvasInstance.setup(frameData, displayAnnotations, curZLayer);

    if (!canvasContainer) {
        return;
    }

    const containerWidth = canvasContainer.clientWidth;
    const containerHeight = canvasContainer.clientHeight;

    // Call fitCanvas + fit() only when the viewport needs recalculation:
    // 1. Initial setup or view change (standard path)
    // 2. Container size differs from current canvasSize (safety net for late
    //    layout shifts that the ResizeObserver debounce hasn't caught yet)
    // On regular frame changes / annotation updates, skip fit() to preserve
    // the user's current zoom/pan state (native canvas zoom).
    const currentGeometry = canvasInstance.geometry;
    const containerSizeChanged = containerWidth > 0 && containerHeight > 0 &&
        (currentGeometry.canvas.width !== containerWidth ||
         currentGeometry.canvas.height !== containerHeight);

    const needsRefit = isInitialSetup || viewChanged || containerSizeChanged;

    if (needsRefit) {
        canvasInstance.fitCanvas(containerWidth, containerHeight);
        canvasInstance.fit();
    }

    if (typeof (canvasInstance as any).lockViewport === 'function') {
        (canvasInstance as any).lockViewport();
        onViewportLocked?.();
    }
}
