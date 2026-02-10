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
        onViewportLocked,
    } = params;

    canvasInstance.setup(frameData, displayAnnotations, curZLayer);

    if (!canvasContainer) {
        return;
    }

    const containerWidth = canvasContainer.clientWidth;
    const containerHeight = canvasContainer.clientHeight;

    // Always call fitCanvas when:
    // 1. Initial setup or view change (standard path)
    // 2. Container size differs from current canvasSize (safety net for late
    //    layout shifts that the ResizeObserver debounce hasn't caught yet)
    const currentGeometry = canvasInstance.geometry;
    const containerSizeChanged = containerWidth > 0 && containerHeight > 0 &&
        (currentGeometry.canvas.width !== containerWidth ||
         currentGeometry.canvas.height !== containerHeight);

    if (isInitialSetup || viewChanged || containerSizeChanged) {
        canvasInstance.fitCanvas(containerWidth, containerHeight);
    }

    // Always call fit() to keep SVG viewport geometry in sync with canvas dimensions.
    // CSS zoom transform is additive on top of this baseline.
    canvasInstance.fit();

    if (typeof (canvasInstance as any).lockViewport === 'function') {
        (canvasInstance as any).lockViewport();
        onViewportLocked?.();
    }
}
