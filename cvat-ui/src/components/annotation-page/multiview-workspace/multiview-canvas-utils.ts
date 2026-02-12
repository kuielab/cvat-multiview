// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { ObjectState } from 'cvat-core-wrapper';

export interface CoordinateTransform {
    canvasWidth: number;
    canvasHeight: number;
    taskHeight: number;
    taskWidth: number;
}

/**
 * Creates a frameData proxy that uses video-proportional dimensions.
 * This ensures the canvas coordinate system matches the video aspect ratio,
 * eliminating letterboxing that causes coordinate mismatch issues.
 */
export function createVideoProportionalFrameData(
    frameData: any,
    videoWidth: number,
    videoHeight: number,
): { frameData: any; transform: CoordinateTransform } | null {
    if (!frameData || videoWidth <= 0 || videoHeight <= 0) {
        return null;
    }

    const taskWidth = frameData.width;
    const taskHeight = frameData.height;
    if (!taskWidth || !taskHeight) {
        return null;
    }

    // Compute scaled canvas dimensions based on task->video scale.
    // This allows both X and Y scaling when task dimensions differ from video.
    const canvasWidth = Math.round(videoWidth);
    const canvasHeight = Math.round(videoHeight);
    if (!Number.isFinite(canvasWidth) || !Number.isFinite(canvasHeight) || canvasWidth <= 0 || canvasHeight <= 0) {
        return null;
    }

    // Create a proxy frameData with adjusted dimensions
    const proxyFrameData = new Proxy(frameData, {
        get(target, prop) {
            if (prop === 'width') {
                return canvasWidth;
            }
            if (prop === 'height') {
                return canvasHeight;
            }
            return target[prop];
        },
    });

    return {
        frameData: proxyFrameData,
        transform: {
            canvasWidth,
            canvasHeight,
            taskHeight,
            taskWidth,
        },
    };
}

function transformForStorage(value: number, canvas: number, task: number): number {
    return value * (task / canvas);
}

function transformForDisplay(value: number, canvas: number, task: number): number {
    return value * (canvas / task);
}

export function transformPointsForStorage(
    points: number[],
    canvasWidth: number,
    canvasHeight: number,
    taskHeight: number,
    taskWidth: number,
): number[] {
    return points.map((val, idx) => (
        idx % 2 === 1 ?
            transformForStorage(val, canvasHeight, taskHeight) :
            transformForStorage(val, canvasWidth, taskWidth)
    ));
}

export function transformPointsForDisplay(
    points: number[],
    canvasWidth: number,
    canvasHeight: number,
    taskHeight: number,
    taskWidth: number,
): number[] {
    return points.map((val, idx) => (
        idx % 2 === 1 ?
            transformForDisplay(val, canvasHeight, taskHeight) :
            transformForDisplay(val, canvasWidth, taskWidth)
    ));
}

export function clampPointsToCanvasBounds(
    points: number[],
    canvasWidth: number,
    canvasHeight: number,
): number[] {
    if (points.length < 4) return points;

    const xs: number[] = [];
    const ys: number[] = [];
    for (let i = 0; i < points.length; i += 2) {
        xs.push(points[i]);
        ys.push(points[i + 1]);
    }
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    let dx = 0;
    let dy = 0;
    if (maxX > canvasWidth) dx = canvasWidth - maxX;
    if (minX + dx < 0) dx = -minX;
    if (maxY > canvasHeight) dy = canvasHeight - maxY;
    if (minY + dy < 0) dy = -minY;

    const shifted = points.map((v, i) => (i % 2 === 0 ? v + dx : v + dy));

    return shifted.map((v, i) => {
        if (i % 2 === 0) return Math.max(0, Math.min(v, canvasWidth));
        return Math.max(0, Math.min(v, canvasHeight));
    });
}

export function normalizeAndClampTaskSpaceDimensions(
    points: number[],
    taskWidth: number,
    taskHeight: number,
): number[] {
    if (points.length !== 4) return points;

    let [x1, y1, x2, y2] = points;
    if (x1 > x2) [x1, x2] = [x2, x1];
    if (y1 > y2) [y1, y2] = [y2, y1];

    x1 = Math.max(0, Math.min(x1, taskWidth));
    y1 = Math.max(0, Math.min(y1, taskHeight));
    x2 = Math.max(0, Math.min(x2, taskWidth));
    y2 = Math.max(0, Math.min(y2, taskHeight));

    return [x1, y1, x2, y2];
}

export function cloneObjectStateForDisplay(ann: ObjectState, newPoints: number[]): ObjectState {
    return {
        clientID: ann.clientID,
        serverID: ann.serverID,
        parentID: ann.parentID,
        objectType: ann.objectType,
        shapeType: ann.shapeType,
        frame: ann.frame,
        updated: ann.updated,
        source: ann.source,
        isGroundTruth: ann.isGroundTruth,
        label: ann.label,
        color: ann.color,
        hidden: ann.hidden,
        pinned: ann.pinned,
        lock: ann.lock,
        outside: ann.outside,
        occluded: ann.occluded,
        zOrder: ann.zOrder,
        rotation: ann.rotation,
        attributes: ann.attributes,
        descriptions: ann.descriptions,
        group: ann.group,
        elements: ann.elements,
        keyframe: ann.keyframe,
        keyframes: ann.keyframes,
        viewId: (ann as any).viewId,
        points: newPoints,
    } as ObjectState;
}
