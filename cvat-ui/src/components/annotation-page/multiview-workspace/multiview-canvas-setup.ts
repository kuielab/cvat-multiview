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
    zoomLevel: number;
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
        zoomLevel,
        onViewportLocked,
    } = params;

    canvasInstance.setup(frameData, displayAnnotations, curZLayer);

    if (!canvasContainer) {
        return;
    }

    if (isInitialSetup || viewChanged) {
        canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
    }

    if (zoomLevel <= 1.0) {
        canvasInstance.fit();
    }

    if (typeof (canvasInstance as any).lockViewport === 'function') {
        (canvasInstance as any).lockViewport();
        onViewportLocked?.();
    }
}
