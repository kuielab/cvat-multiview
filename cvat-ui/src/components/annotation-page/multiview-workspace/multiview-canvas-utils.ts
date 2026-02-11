// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { ObjectState } from 'cvat-core-wrapper';

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

const MIN_SHAPE_DIMENSION = 10;
const MIN_TASK_SHAPE_SIZE = 2;

export function normalizeAndEnforceTaskSpaceDimensions(
    points: number[],
    taskWidth: number,
    taskHeight: number,
): number[] {
    if (points.length !== 4) return points;

    let [x1, y1, x2, y2] = points;
    if (x1 > x2) [x1, x2] = [x2, x1];
    if (y1 > y2) [y1, y2] = [y2, y1];

    let width = x2 - x1;
    let height = y2 - y1;

    if (width < MIN_TASK_SHAPE_SIZE) {
        const cx = (x1 + x2) / 2;
        x1 = cx - MIN_TASK_SHAPE_SIZE / 2;
        x2 = cx + MIN_TASK_SHAPE_SIZE / 2;
        width = MIN_TASK_SHAPE_SIZE;
    }
    if (height < MIN_TASK_SHAPE_SIZE) {
        const cy = (y1 + y2) / 2;
        y1 = cy - MIN_TASK_SHAPE_SIZE / 2;
        y2 = cy + MIN_TASK_SHAPE_SIZE / 2;
        height = MIN_TASK_SHAPE_SIZE;
    }

    if (x1 < 0) { x2 -= x1; x1 = 0; }
    if (y1 < 0) { y2 -= y1; y1 = 0; }
    if (x2 > taskWidth) { x1 -= (x2 - taskWidth); x2 = taskWidth; }
    if (y2 > taskHeight) { y1 -= (y2 - taskHeight); y2 = taskHeight; }

    x1 = Math.max(0, x1);
    y1 = Math.max(0, y1);
    x2 = Math.min(taskWidth, x2);
    y2 = Math.min(taskHeight, y2);

    return [x1, y1, x2, y2];
}

export function enforceMinimumShapeDimensions(
    newPoints: number[],
    originalPoints: number[],
): number[] {
    if (newPoints.length !== 4 || originalPoints.length !== 4) return newPoints;

    const [nx1, ny1, nx2, ny2] = newPoints;
    const [ox1, oy1, ox2, oy2] = originalPoints;

    let newWidth = Math.abs(nx2 - nx1);
    let newHeight = Math.abs(ny2 - ny1);
    const origWidth = Math.abs(ox2 - ox1);
    const origHeight = Math.abs(oy2 - oy1);

    const isSmallShape = origWidth < 40 || origHeight < 40;
    if (!isSmallShape) return newPoints;

    let correctedX1 = Math.min(nx1, nx2);
    let correctedY1 = Math.min(ny1, ny2);
    let correctedX2 = Math.max(nx1, nx2);
    let correctedY2 = Math.max(ny1, ny2);

    const widthRatio = origWidth > 0 ? newWidth / origWidth : 1;
    const heightRatio = origHeight > 0 ? newHeight / origHeight : 1;

    if (widthRatio < 0.5 && heightRatio > 0.5 && heightRatio < 2.0) {
        const centerX = (correctedX1 + correctedX2) / 2;
        correctedX1 = centerX - origWidth / 2;
        correctedX2 = centerX + origWidth / 2;
        newWidth = origWidth;
    } else if (heightRatio < 0.5 && widthRatio > 0.5 && widthRatio < 2.0) {
        const centerY = (correctedY1 + correctedY2) / 2;
        correctedY1 = centerY - origHeight / 2;
        correctedY2 = centerY + origHeight / 2;
        newHeight = origHeight;
    }

    if (newWidth < MIN_SHAPE_DIMENSION) {
        const centerX = (correctedX1 + correctedX2) / 2;
        correctedX1 = centerX - MIN_SHAPE_DIMENSION / 2;
        correctedX2 = centerX + MIN_SHAPE_DIMENSION / 2;
    }
    if (newHeight < MIN_SHAPE_DIMENSION) {
        const centerY = (correctedY1 + correctedY2) / 2;
        correctedY1 = centerY - MIN_SHAPE_DIMENSION / 2;
        correctedY2 = centerY + MIN_SHAPE_DIMENSION / 2;
    }

    return [correctedX1, correctedY1, correctedX2, correctedY2];
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
