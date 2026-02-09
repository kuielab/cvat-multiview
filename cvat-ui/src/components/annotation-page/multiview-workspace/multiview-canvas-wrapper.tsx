// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useEffect, useRef, useCallback, useMemo } from 'react';
import { useSelector, useDispatch } from 'react-redux';

import { Canvas } from 'cvat-canvas-wrapper';
import { CombinedState, ActiveControl, Workspace } from 'reducers';
import { getCore, ObjectState, ObjectType, ShapeType } from 'cvat-core-wrapper';
import {
    createAnnotationsAsync,
    updateActiveControl as updateActiveControlAction,
    confirmCanvasReadyAsync,
    resetCanvas,
    activateObject,
    updateAnnotationsAsync,
    removeObject as removeObjectAction,
} from 'actions/annotation-actions';
import { filterAnnotations } from 'utils/filter-annotations';

// Draw-related modes that should not be interrupted
const DRAW_MODES: string[] = ['draw', 'draw_rect', 'draw_polygon', 'draw_polyline', 'draw_points', 'draw_ellipse', 'draw_cuboid', 'draw_skeleton', 'draw_mask'];

// ActiveControl values that indicate a draw operation is requested/in progress
const DRAW_ACTIVE_CONTROLS = [
    ActiveControl.DRAW_RECTANGLE,
    ActiveControl.DRAW_POLYGON,
    ActiveControl.DRAW_POLYLINE,
    ActiveControl.DRAW_POINTS,
    ActiveControl.DRAW_ELLIPSE,
    ActiveControl.DRAW_CUBOID,
    ActiveControl.DRAW_SKELETON,
    ActiveControl.DRAW_MASK,
    ActiveControl.AI_TOOLS,
    ActiveControl.OPENCV_TOOLS,
];

const cvat = getCore();

// Debounce utility for ResizeObserver
function debounce<T extends (...args: any[]) => void>(func: T, wait: number): T {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    return ((...args: any[]) => {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        timeoutId = setTimeout(() => {
            func(...args);
            timeoutId = null;
        }, wait);
    }) as T;
}

// Helper to check if canvas is in draw mode
function isCanvasInDrawMode(canvasInstance: Canvas | null): boolean {
    if (!canvasInstance) return false;
    try {
        const currentMode = canvasInstance.mode();
        return DRAW_MODES.includes(currentMode);
    } catch {
        return false;
    }
}

// Helper to check if a draw operation is requested via Redux activeControl
// This catches cases where draw is requested but canvas hasn't entered draw mode yet
function isDrawOperationRequested(activeControl: ActiveControl): boolean {
    return DRAW_ACTIVE_CONTROLS.includes(activeControl);
}

// Combined check: either canvas is in draw mode OR draw operation is requested
function shouldPreserveDrawState(canvasInstance: Canvas | null, activeControl: ActiveControl): boolean {
    return isCanvasInDrawMode(canvasInstance) || isDrawOperationRequested(activeControl);
}

interface Props {
    canvasContainer: HTMLDivElement | null;
    videoElement: HTMLVideoElement | null;
    activeViewId: number;
}

/**
 * Creates a frameData proxy that uses video-proportional dimensions.
 * This ensures the canvas coordinate system matches the video aspect ratio,
 * eliminating letterboxing that causes coordinate mismatch issues.
 *
 * Example: If video is 320x240 (4:3) and task is 1920x1080 (16:9):
 * - We use width=1920, height=1440 (4:3) for the canvas
 * - This fills the overlay without letterboxing
 * - Coordinates are transformed when saving/loading annotations
 */
function createVideoProportionalFrameData(
    frameData: any,
    videoWidth: number,
    videoHeight: number,
): { frameData: any; canvasHeight: number; taskHeight: number } | null {
    if (!frameData || videoWidth <= 0 || videoHeight <= 0) {
        return null;
    }

    const taskWidth = frameData.width;
    const taskHeight = frameData.height;
    const videoAspect = videoWidth / videoHeight;

    // Calculate height that matches video aspect ratio at task width
    // This makes the canvas fill the overlay without letterboxing
    const canvasHeight = Math.round(taskWidth / videoAspect);

    // If aspect ratios are close (within 1%), no transformation needed
    const taskAspect = taskWidth / taskHeight;
    if (Math.abs(videoAspect - taskAspect) < 0.01) {
        return null; // Use original frameData
    }

    // Create a proxy frameData with adjusted dimensions
    const proxyFrameData = new Proxy(frameData, {
        get(target, prop) {
            if (prop === 'height') {
                return canvasHeight;
            }
            return target[prop];
        },
    });

    return { frameData: proxyFrameData, canvasHeight, taskHeight };
}

/**
 * Transform Y coordinate from canvas space to task space for storage.
 * Canvas space uses video aspect ratio, task space uses original video dimensions.
 */
function transformYForStorage(y: number, canvasHeight: number, taskHeight: number): number {
    return y * (taskHeight / canvasHeight);
}

/**
 * Transform Y coordinate from task space to canvas space for display.
 * Task space uses original video dimensions, canvas space uses video aspect ratio.
 */
function transformYForDisplay(y: number, canvasHeight: number, taskHeight: number): number {
    return y * (canvasHeight / taskHeight);
}

/**
 * Transform annotation points from canvas space to task space for storage.
 */
function transformPointsForStorage(
    points: number[],
    canvasHeight: number,
    taskHeight: number,
): number[] {
    // Points array is [x1, y1, x2, y2, ...] - transform Y values (odd indices)
    return points.map((val, idx) => (idx % 2 === 1 ? transformYForStorage(val, canvasHeight, taskHeight) : val));
}

/**
 * Transform annotation points from task space to canvas space for display.
 */
function transformPointsForDisplay(
    points: number[],
    canvasHeight: number,
    taskHeight: number,
): number[] {
    // Points array is [x1, y1, x2, y2, ...] - transform Y values (odd indices)
    return points.map((val, idx) => (idx % 2 === 1 ? transformYForDisplay(val, canvasHeight, taskHeight) : val));
}

/**
 * Clamp annotation points to canvas bounds, preserving shape size when possible.
 * For drag operations (shape moved out of bounds), translates the entire shape
 * back within bounds so it "slides" along the wall without shrinking.
 * For resize operations (shape enlarged past boundary), per-point clamping applies.
 *
 * This prevents the backend fitPoints() from clamping in task space, which
 * causes shapes to shrink when aspect ratio differs between video and task.
 */
function clampPointsToCanvasBounds(
    points: number[],
    canvasWidth: number,
    canvasHeight: number,
): number[] {
    if (points.length < 4) return points;

    // Compute bounding box
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

    // Compute translation needed to push shape back within bounds
    // This preserves shape dimensions for drag operations
    let dx = 0;
    let dy = 0;
    if (maxX > canvasWidth) dx = canvasWidth - maxX; // shift left
    if (minX + dx < 0) dx = -minX; // shift right (wins if shape fits)
    if (maxY > canvasHeight) dy = canvasHeight - maxY; // shift up
    if (minY + dy < 0) dy = -minY; // shift down

    // Apply translation
    const shifted = points.map((v, i) => (i % 2 === 0 ? v + dx : v + dy));

    // Final per-point clamp for safety (handles shapes larger than canvas)
    return shifted.map((v, i) => {
        if (i % 2 === 0) return Math.max(0, Math.min(v, canvasWidth));
        return Math.max(0, Math.min(v, canvasHeight));
    });
}

/**
 * Minimum shape dimension in canvas coordinates.
 * When a shape's width or height falls below this threshold after an edit,
 * we enforce this minimum to prevent shapes from collapsing due to
 * accidental resize (resize handles larger than the shape itself).
 *
 * In canvas space the coordinate system is typically 1920×1440,
 * so 10 units is extremely small (well below the ~20 units where
 * resize handles start overlapping the shape body).
 */
const MIN_SHAPE_DIMENSION = 10;

/**
 * Minimum shape dimension in task (storage) coordinates.
 * The backend's checkShapeArea() silently rejects shapes with width or
 * height < 1, causing save() to skip the point update without error.
 * This leads to canvas/Redux state divergence — the shape appears
 * distorted or invisible on canvas while remaining in the sidebar list.
 *
 * We use 2 instead of 1 for a safety margin against floating-point rounding.
 */
const MIN_TASK_SHAPE_SIZE = 2;

/**
 * Normalize and enforce minimum dimensions on rectangle points in task space.
 * This is the last line of defense before saving to Redux/backend.
 *
 * Fixes two classes of bugs:
 * 1. **Inverted coordinates** (x1 > x2 or y1 > y2): SVG rects get negative
 *    width/height and become invisible. Normalizing ensures x1 ≤ x2, y1 ≤ y2.
 * 2. **Sub-pixel dimensions**: After coordinate space transforms, a shape may
 *    end up with width or height < 1 in task space. The backend's
 *    checkShapeArea() silently sets fittedPoints=[], causing Shape.save() to
 *    skip persisting the new points. The shape then diverges between canvas
 *    (which shows the edit) and Redux/API (which keeps the old position).
 *
 * @param points  Rectangle points [x1, y1, x2, y2] in task space
 * @param taskWidth  Task frame width (for boundary clamping)
 * @param taskHeight Task frame height (for boundary clamping)
 * @returns Normalized, minimum-enforced points guaranteed to pass checkShapeArea()
 */
function normalizeAndEnforceTaskSpaceDimensions(
    points: number[],
    taskWidth: number,
    taskHeight: number,
): number[] {
    if (points.length !== 4) return points;

    // 1. Normalize: ensure x1 ≤ x2, y1 ≤ y2
    let [x1, y1, x2, y2] = points;
    if (x1 > x2) [x1, x2] = [x2, x1];
    if (y1 > y2) [y1, y2] = [y2, y1];

    // 2. Enforce minimum dimensions (must pass checkShapeArea)
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

    // 3. Clamp to task bounds (don't let the minimum enforcement push outside)
    if (x1 < 0) { x2 -= x1; x1 = 0; }
    if (y1 < 0) { y2 -= y1; y1 = 0; }
    if (x2 > taskWidth) { x1 -= (x2 - taskWidth); x2 = taskWidth; }
    if (y2 > taskHeight) { y1 -= (y2 - taskHeight); y2 = taskHeight; }

    // 4. Final clamp (safety for edge cases where shape > canvas)
    x1 = Math.max(0, x1);
    y1 = Math.max(0, y1);
    x2 = Math.min(taskWidth, x2);
    y2 = Math.min(taskHeight, y2);

    return [x1, y1, x2, y2];
}

/**
 * Enforce minimum shape dimensions for rectangle shapes.
 * When shapes are very small, the canvas resize handles (8×8px) overlap
 * the shape body, causing the user to accidentally resize instead of drag.
 * This function detects when a shape dimension has collapsed below the
 * minimum threshold and corrects it by preserving the original dimension.
 *
 * @param newPoints - The edited points [x1, y1, x2, y2] in canvas space
 * @param originalPoints - The original points [x1, y1, x2, y2] in canvas (display) space
 * @returns Corrected points with minimum dimensions enforced
 */
function enforceMinimumShapeDimensions(
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

    // Only apply correction if the shape was already small before the edit
    // (below resize-handle overlap threshold, roughly 2× the handle point size)
    const isSmallShape = origWidth < 40 || origHeight < 40;
    if (!isSmallShape) return newPoints;

    let correctedX1 = Math.min(nx1, nx2);
    let correctedY1 = Math.min(ny1, ny2);
    let correctedX2 = Math.max(nx1, nx2);
    let correctedY2 = Math.max(ny1, ny2);

    // Detect accidental resize: one dimension shrunk dramatically while the other stayed similar.
    // This happens when the user intended to drag but hit a resize handle instead.
    const widthRatio = origWidth > 0 ? newWidth / origWidth : 1;
    const heightRatio = origHeight > 0 ? newHeight / origHeight : 1;

    // If one dimension shrunk to <50% while the other didn't grow much, it's an accidental resize.
    // Restore the original dimension and treat it as a drag.
    if (widthRatio < 0.5 && heightRatio > 0.5 && heightRatio < 2.0) {
        // Width collapsed — was dragging a left/right edge handle accidentally
        // Restore original width, centered on the new center X
        const centerX = (correctedX1 + correctedX2) / 2;
        correctedX1 = centerX - origWidth / 2;
        correctedX2 = centerX + origWidth / 2;
        newWidth = origWidth;
    } else if (heightRatio < 0.5 && widthRatio > 0.5 && widthRatio < 2.0) {
        // Height collapsed — was dragging a top/bottom edge handle accidentally
        // Restore original height, centered on the new center Y
        const centerY = (correctedY1 + correctedY2) / 2;
        correctedY1 = centerY - origHeight / 2;
        correctedY2 = centerY + origHeight / 2;
        newHeight = origHeight;
    }

    // Final safety: enforce absolute minimum dimensions
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

/**
 * Create a display-safe clone of an ObjectState with overridden points.
 *
 * ObjectState uses Object.defineProperties with non-enumerable accessor descriptors,
 * which means the spread operator `{ ...objectState }` copies ZERO properties.
 * This function explicitly reads all properties needed by canvasView.ts setupObjects()
 * and creates a plain object that the canvas can correctly diff, render, and track.
 */
function cloneObjectStateForDisplay(ann: any, newPoints: number[]): any {
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
        viewId: ann.viewId,
        points: newPoints,
    };
}

/**
 * Get video dimensions from Redux multiviewData metadata.
 * This provides consistent dimensions across sessions, unlike videoElement which
 * can have different dimensions depending on loading state or frame position.
 */
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

export default function MultiviewCanvasWrapper(props: Props): JSX.Element | null {
    const { canvasContainer, videoElement, activeViewId } = props;
    const dispatch = useDispatch();
    const mountedRef = useRef(false);
    const resizeObserverRef = useRef<ResizeObserver | null>(null);
    const prevViewIdRef = useRef<number | null>(null);

    // Track coordinate transformation parameters for aspect ratio correction
    // When video aspect ratio differs from task metadata, we need to transform coordinates
    // taskWidth is included for boundary clamping (X doesn't scale but needs a bound)
    const transformParamsRef = useRef<{ canvasHeight: number; taskHeight: number; taskWidth: number } | null>(null);

    // Redux state selectors
    const canvasInstance = useSelector((state: CombinedState) => state.annotation.canvas.instance) as Canvas | null;
    const jobInstance = useSelector((state: CombinedState) => state.annotation.job.instance);
    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const frameData = useSelector((state: CombinedState) => state.annotation.player.frame.data);
    const annotations = useSelector((state: CombinedState) => state.annotation.annotations.states);
    const activeLabelID = useSelector((state: CombinedState) => state.annotation.drawing.activeLabelID);
    const activeObjectType = useSelector((state: CombinedState) => state.annotation.drawing.activeObjectType);
    const curZLayer = useSelector((state: CombinedState) => state.annotation.annotations.zLayer.cur);
    const workspace = useSelector((state: CombinedState) => state.annotation.workspace);
    const activatedStateID = useSelector((state: CombinedState) => state.annotation.annotations.activatedStateID);
    const activatedAttributeID = useSelector((state: CombinedState) => state.annotation.annotations.activatedAttributeID);
    const activeControl = useSelector((state: CombinedState) => state.annotation.canvas.activeControl);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);

    // Use refs for values that change frequently but shouldn't cause remount
    const stateRefs = useRef({
        activeLabelID,
        activeObjectType,
        frameNumber,
        activeViewId,
        jobInstance,
        annotations,
        curZLayer,
        frameData,
        workspace,
        activatedStateID,
        activeControl,
        multiviewData,
    });

    // Update refs when values change
    useEffect(() => {
        stateRefs.current = {
            activeLabelID,
            activeObjectType,
            frameNumber,
            activeViewId,
            jobInstance,
            annotations,
            curZLayer,
            frameData,
            workspace,
            activatedStateID,
            activeControl,
            multiviewData,
        };
    }, [activeLabelID, activeObjectType, frameNumber, activeViewId, jobInstance, annotations, curZLayer, frameData, workspace, activatedStateID, activeControl, multiviewData]);

    // Refs for stable event handler references (to avoid useEffect dependency issues)
    const eventHandlersRef = useRef<{
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
        onKeyDown: ((e: KeyboardEvent) => void) | null;
        onWheel: ((e: WheelEvent) => void) | null;
    }>({
        onShapeDrawn: null,
        onSetup: null,
        onCancel: null,
        onZoomStart: null,
        onZoomDone: null,
        onDragStart: null,
        onDragDone: null,
        onShapeClicked: null,
        onShapeDeactivated: null,
        onCursorMoved: null,
        onEditDone: null,
        onMouseDown: null,
        onKeyDown: null,
        onWheel: null,
    });

    /**
     * Handle shape drawn event - create annotation with viewId
     */
    const onCanvasShapeDrawn = useCallback((event: any): void => {
        const refs = stateRefs.current;

        if (!refs.jobInstance || !canvasInstance) {
            console.error('[MultiviewCanvas] Missing jobInstance or canvasInstance');
            return;
        }

        const { state } = event.detail;

        if (!event.detail.continue) {
            dispatch(updateActiveControlAction(ActiveControl.CURSOR));
        }

        // Set annotation properties
        state.objectType = state.shapeType === ShapeType.MASK
            ? ObjectType.SHAPE : state.objectType ?? refs.activeObjectType;

        // Find label: try activeLabelID first, then fallback to first available label
        const foundLabel = refs.jobInstance.labels.find((label: any) => label.id === refs.activeLabelID);
        const fallbackLabel = refs.jobInstance.labels[0];
        state.label = state.label || foundLabel || fallbackLabel;

        // Check if we have a valid label
        if (!state.label) {
            console.error('[MultiviewCanvas] No label available for annotation. Please create at least one label.');
            return;
        }

        state.frame = refs.frameNumber;
        state.rotation = state.rotation || 0;
        state.occluded = state.occluded || false;
        state.outside = state.outside || false;
        state.hidden = state.hidden || false;

        // Set viewId to track which view this annotation belongs to
        // Note: Do NOT set state.attributes here - ObjectState constructor handles
        // attribute initialization internally. Setting it here can cause validation
        // issues with non-integer attribute IDs.
        state.viewId = refs.activeViewId;

        // Transform coordinates from canvas space to task space if aspect ratio differs
        // This ensures annotations are stored in the original video coordinate system
        const transformParams = transformParamsRef.current;
        if (transformParams && state.points && Array.isArray(state.points)) {
            // Pre-clamp in canvas space to prevent shrinkage from aspect ratio mismatch
            state.points = clampPointsToCanvasBounds(
                state.points,
                transformParams.taskWidth,
                transformParams.canvasHeight,
            );
            state.points = transformPointsForStorage(
                state.points,
                transformParams.canvasHeight,
                transformParams.taskHeight,
            );

            // Normalize and enforce minimum dimensions in task space for new shapes
            if (state.shapeType === 'rectangle' && state.points.length === 4 && !state.rotation) {
                state.points = normalizeAndEnforceTaskSpaceDimensions(
                    state.points,
                    transformParams.taskWidth,
                    transformParams.taskHeight,
                );
            }
        }

        try {
            const objectState = new cvat.classes.ObjectState(state);
            dispatch(createAnnotationsAsync([objectState]));
        } catch (error) {
            // Error handling for failed annotation creation
        }
    }, [canvasInstance, dispatch]);

    /**
     * Handle canvas setup complete
     */
    const onCanvasSetup = useCallback((): void => {
        dispatch(confirmCanvasReadyAsync());
    }, [dispatch]);

    /**
     * Handle canvas cancel
     */
    const onCanvasCancel = useCallback((): void => {
        dispatch(resetCanvas());
    }, [dispatch]);

    /**
     * Handle canvas zoom start - sync with Redux activeControl
     */
    const onCanvasZoomStart = useCallback((): void => {
        dispatch(updateActiveControlAction(ActiveControl.ZOOM_CANVAS));
    }, [dispatch]);

    /**
     * Handle canvas zoom done - reset to cursor mode
     */
    const onCanvasZoomDone = useCallback((): void => {
        dispatch(updateActiveControlAction(ActiveControl.CURSOR));
    }, [dispatch]);

    /**
     * Handle canvas drag start - sync with Redux activeControl
     */
    const onCanvasDragStart = useCallback((): void => {
        dispatch(updateActiveControlAction(ActiveControl.DRAG_CANVAS));
    }, [dispatch]);

    /**
     * Handle canvas drag done - reset to cursor mode
     */
    const onCanvasDragDone = useCallback((): void => {
        dispatch(updateActiveControlAction(ActiveControl.CURSOR));
    }, [dispatch]);

    /**
     * Handle canvas shape clicked - activate the shape and scroll sidebar to show the clicked item
     */
    const onCanvasShapeClicked = useCallback((e: any): void => {
        const { clientID, parentID } = e.detail.state;

        // Dispatch activateObject to update Redux state, which triggers the useEffect
        // that calls canvasInstance.activate() to show resize handles
        dispatch(activateObject(clientID, null, null));

        // Scroll the sidebar to show the clicked item
        let sidebarItem = null;
        if (Number.isInteger(parentID)) {
            sidebarItem = window.document.getElementById(`cvat-objects-sidebar-state-item-element-${clientID}`);
        } else {
            sidebarItem = window.document.getElementById(`cvat-objects-sidebar-state-item-${clientID}`);
        }

        if (sidebarItem) {
            sidebarItem.scrollIntoView();
        }
    }, [dispatch]);

    /**
     * Handle canvas shape deactivated
     */
    const onCanvasShapeDeactivated = useCallback((e: any): void => {
        const refs = stateRefs.current;
        const { state } = e.detail;

        // Only deactivate if the deactivated state was the active one
        if (state.clientID === refs.activatedStateID) {
            dispatch(activateObject(null, null, null));
        }
    }, [dispatch]);

    /**
     * Handle mouse down on canvas - deactivate current object when clicking empty area
     * Also prevents canvas drag (pan) on left-click without Alt key in Multiview workspace
     *
     * IMPORTANT: We use capture phase (capture: true) to intercept events before they
     * reach SVG.js handlers. However, we must NOT block events when:
     * 1. Clicking on shape elements (SVG.js needs to handle shape dragging)
     * 2. Canvas is in draw mode (DrawHandler needs to receive mousedown to start drawing)
     */
    const onCanvasMouseDown = useCallback((e: MouseEvent): void => {
        const refs = stateRefs.current;
        const target = e.target as Element;

        // CRITICAL: Do NOT block events when canvas is in draw mode or draw operation is requested
        // Drawing requires mousedown events on background to start drawing shapes
        if (shouldPreserveDrawState(canvasInstance, refs.activeControl)) {
            return; // Allow event propagation to DrawHandler
        }

        // Check if clicking on a shape element or its interactive parts
        // These should NOT be blocked - SVG.js needs to handle shape dragging
        // Includes: shape containers, resize/rotation handles, and direct SVG elements
        const isShapeElement =
            // Shape containers
            target.closest('.cvat_canvas_shape') !== null ||
            target.closest('.cvat_canvas_shape_drawing') !== null ||
            // Resize/rotation handles (for activated shapes)
            target.closest('.svg_select_points') !== null ||
            target.closest('.svg_select_points_rot') !== null ||
            // Direct SVG shape elements (rect, polygon, ellipse, path, circle)
            // Also includes 'line' and 'g' for skeleton shapes
            ['rect', 'polygon', 'polyline', 'ellipse', 'path', 'circle', 'line', 'g'].includes(
                target.tagName.toLowerCase(),
            );

        // If clicking on a shape element, allow the event to propagate to SVG.js
        // This is critical for individual shape dragging to work correctly
        if (isShapeElement) {
            return; // Allow event propagation to SVG.js handlers
        }

        // Check if clicking on SVG background (not on a shape)
        const isSvgBackground = target.tagName.toLowerCase() === 'svg' ||
            target.classList.contains('cvat_canvas_background');

        // Left-click (button === 0) on canvas background without Alt key
        // should NOT trigger canvas drag (pan) - stop propagation
        // ONLY when NOT in draw mode (draw mode check is above)
        if (isSvgBackground && e.button === 0 && !e.altKey) {
            // Prevent canvas drag by stopping event propagation to canvasView's mousedown handler
            // which enables drag on left-click in IDLE mode (see canvasView.ts:1712-1720)
            e.stopPropagation();

            // Deactivate any active object
            if (refs.activatedStateID !== null) {
                dispatch(activateObject(null, null, null));
            }
            return;
        }

        // Original logic: deactivate on SVG click (except right-click)
        if (target.tagName.toLowerCase() === 'svg' && e.button !== 2) {
            if (refs.activatedStateID !== null) {
                dispatch(activateObject(null, null, null));
            }
        }
    }, [canvasInstance, dispatch]);

    /**
     * Handle wheel event on canvas - prevent canvas zoom
     * Mouse wheel should NOT zoom the canvas in Multiview workspace
     */
    const handleWheel = useCallback((e: WheelEvent): void => {
        e.preventDefault();
        e.stopPropagation();
    }, []);

    /**
     * Handle mousedown in bubble phase - this is now a no-op as canvasView.ts
     * has been modified to check for shape elements before enabling canvas drag.
     * Keeping this handler for potential future use or additional multiview-specific logic.
     */
    const onCanvasMouseDownBubble = useCallback((_e: MouseEvent): void => {
        // Canvas drag prevention for shapes is now handled directly in canvasView.ts
        // See canvasView.ts mousedown handler which checks isShapeElement
    }, []);

    /**
     * Handle cursor moved on canvas - activate object under cursor
     */
    const onCanvasCursorMoved = useCallback(async (event: any): Promise<void> => {
        const refs = stateRefs.current;

        if (!refs.jobInstance || !canvasInstance) {
            return;
        }

        const result = await refs.jobInstance.annotations.select(
            event.detail.states,
            event.detail.x,
            event.detail.y,
        );

        if (result && result.state) {
            const newActivatedElement = event.detail.activatedElementID || null;
            if (refs.activatedStateID !== result.state.clientID) {
                dispatch(activateObject(result.state.clientID, newActivatedElement, null));
            }
        }
    }, [canvasInstance, dispatch]);

    /**
     * Handle canvas edit done - update annotation
     * IMPORTANT: The state from event.detail may be a shallow copy (without save() method)
     * if coordinate transformation was applied. We need to find the original ObjectState
     * from Redux and update it.
     */
    const onCanvasEditDone = useCallback((event: any): void => {
        const refs = stateRefs.current;
        const { state, points, rotation } = event.detail;

        // Find the original ObjectState from Redux annotations by clientID
        // This is necessary because setup() may pass shallow copies with transformed coordinates
        const originalState = refs.annotations.find(
            (ann: ObjectState) => ann.clientID === state.clientID,
        );

        if (!originalState) {
            console.error('[MultiviewCanvas] Could not find original state for clientID:', state.clientID);
            return;
        }

        // For rectangle shapes without rotation, enforce minimum dimensions.
        // When shapes are very small, CVAT's resize handles (8×8px) overlap the shape
        // body, causing the user to accidentally resize instead of drag. This detects
        // and corrects such accidental resizes by preserving the original dimension.
        const transformParams = transformParamsRef.current;
        let updatedPoints = points;
        if (!rotation && state.shapeType === 'rectangle' &&
            updatedPoints && Array.isArray(updatedPoints) && updatedPoints.length === 4 &&
            state.points && state.points.length === 4) {
            updatedPoints = enforceMinimumShapeDimensions(updatedPoints, state.points);
        }

        // Transform coordinates from canvas space back to task space if needed
        if (transformParams && updatedPoints && Array.isArray(updatedPoints)) {
            // Pre-clamp in canvas space before converting to task space.
            // This prevents the backend fitPoints() from shrinking shapes that
            // extend beyond the canvas boundary due to aspect ratio mismatch.
            // Skip clamping for rotated shapes (fitPoints also skips them).
            if (!rotation) {
                updatedPoints = clampPointsToCanvasBounds(
                    updatedPoints,
                    transformParams.taskWidth,
                    transformParams.canvasHeight,
                );
            }
            updatedPoints = transformPointsForStorage(
                updatedPoints,
                transformParams.canvasHeight,
                transformParams.taskHeight,
            );

            // Normalize and enforce minimum dimensions in task space.
            // This prevents checkShapeArea() from silently rejecting the save
            // when repeated resizes produce sub-pixel or inverted coordinates.
            if (!rotation && state.shapeType === 'rectangle' &&
                updatedPoints.length === 4) {
                updatedPoints = normalizeAndEnforceTaskSpaceDimensions(
                    updatedPoints,
                    transformParams.taskWidth,
                    transformParams.taskHeight,
                );
            }
        }

        // Update the original ObjectState (which has the save() method)
        if (originalState.rotation !== rotation) {
            originalState.rotation = rotation;
        } else {
            originalState.points = updatedPoints;
        }

        dispatch(updateAnnotationsAsync([originalState]));
    }, [dispatch]);

    /**
     * Handle keydown event - Delete key to remove activated annotation
     */
    const onKeyDown = useCallback((event: KeyboardEvent): void => {
        const refs = stateRefs.current;

        // Only handle Delete key
        if (event.key !== 'Delete') return;

        // Prevent if in draw mode or other active operations
        if (isCanvasInDrawMode(canvasInstance)) return;

        // Find the activated state
        if (refs.activatedStateID === null) return;

        const activatedState = refs.annotations.find(
            (state: ObjectState) => state.clientID === refs.activatedStateID,
        );

        if (!activatedState) return;

        // Check if object is locked (shift key forces delete of locked objects)
        const force = event.shiftKey;

        // Dispatch remove action
        dispatch(removeObjectAction(activatedState, force));

        // Prevent default behavior
        event.preventDefault();
        event.stopPropagation();
    }, [canvasInstance, dispatch]);

    // Update event handler refs whenever callbacks change
    useEffect(() => {
        eventHandlersRef.current = {
            onShapeDrawn: onCanvasShapeDrawn,
            onSetup: onCanvasSetup,
            onCancel: onCanvasCancel,
            onZoomStart: onCanvasZoomStart,
            onZoomDone: onCanvasZoomDone,
            onDragStart: onCanvasDragStart,
            onDragDone: onCanvasDragDone,
            onShapeClicked: onCanvasShapeClicked,
            onShapeDeactivated: onCanvasShapeDeactivated,
            onCursorMoved: onCanvasCursorMoved,
            onEditDone: onCanvasEditDone,
            onMouseDown: onCanvasMouseDown,
            onMouseDownBubble: onCanvasMouseDownBubble,
            onKeyDown,
            onWheel: handleWheel,
        };
    }, [onCanvasShapeDrawn, onCanvasSetup, onCanvasCancel, onCanvasZoomStart, onCanvasZoomDone, onCanvasDragStart, onCanvasDragDone, onCanvasShapeClicked, onCanvasShapeDeactivated, onCanvasCursorMoved, onCanvasEditDone, onCanvasMouseDown, onCanvasMouseDownBubble, onKeyDown, handleWheel]);

    /**
     * Handle view changes - ALWAYS reset canvas mode when switching views
     * This prevents the canvas from getting stuck in draw mode after switching views
     */
    useEffect(() => {
        if (!canvasInstance) return;

        // Detect view change (not initial mount)
        if (prevViewIdRef.current !== null && prevViewIdRef.current !== activeViewId) {
            // View changed - force reset canvas mode
            // This is critical: without this, the canvas can get stuck in draw mode
            // when switching between views, causing drawing to fail
            try {
                canvasInstance.cancel();
            } catch (e) {
                // Canvas might not be in a cancelable state
            }

            // Reset activeControl to CURSOR to ensure clean state for new view
            dispatch(updateActiveControlAction(ActiveControl.CURSOR));
        }

        prevViewIdRef.current = activeViewId;
    }, [canvasInstance, activeViewId, dispatch]);

    /**
     * Mount canvas to container - only depends on container and canvas instance
     * Uses stable wrapper functions that delegate to refs to avoid unnecessary re-mounts
     */
    useEffect(() => {
        if (!canvasContainer || !canvasInstance) {
            return;
        }

        // Clear container first
        while (canvasContainer.firstChild) {
            canvasContainer.removeChild(canvasContainer.firstChild);
        }

        // Mount canvas HTML to container
        const canvasHTML = canvasInstance.html();
        canvasContainer.appendChild(canvasHTML);
        mountedRef.current = true;

        // Reset any stuck canvas modes to IDLE on mount
        // IMPORTANT: Skip cancel() if canvas is in draw mode to prevent interrupting active drawing
        const currentMode = canvasInstance.mode();
        if (currentMode === 'zoom_canvas') {
            try {
                canvasInstance.zoomCanvas(false);
            } catch (e) {
                // Mode might have already changed
            }
        } else if (currentMode === 'drag_canvas') {
            try {
                canvasInstance.dragCanvas(false);
            } catch (e) {
                // Mode might have already changed
            }
        } else if (!shouldPreserveDrawState(canvasInstance, stateRefs.current.activeControl)) {
            // Only cancel if NOT in draw mode AND no draw operation is requested
            // This prevents draw mode from being interrupted
            canvasInstance.cancel();
        }

        // Note: setViewId is handled in a separate effect that depends on activeViewId

        // Configure canvas for multiview mode
        canvasInstance.configure({
            forceDisableEditing: stateRefs.current.workspace === Workspace.REVIEW,
        });

        // NOTE: Do NOT call fitCanvas()/fit() here before setup().
        // This would calculate imageOffset using canvasSize (display container) instead of
        // imageSize (video dimensions), causing coordinate mismatch (~50% smaller drawings).
        // The correct sequence is: setup() -> fitCanvas() -> fit(), which happens below.

        // Create stable wrapper functions that delegate to refs
        // This allows callbacks to update without triggering useEffect re-runs
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

        // Add event listeners with stable wrapper functions
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

        // IMPORTANT: Use capture phase for mousedown to intercept before canvasView's handlers
        // This prevents canvas drag (pan) on left-click without Alt key
        canvasHTML.addEventListener('mousedown', handleMouseDown, { capture: true });

        // Add bubble phase handler on SVG content for potential future multiview-specific logic
        // NOTE: Canvas drag prevention for shapes is now handled directly in canvasView.ts
        const svgContent = canvasHTML.querySelector('#cvat_canvas_content');
        if (svgContent) {
            svgContent.addEventListener('mousedown', handleMouseDownBubble, { capture: false });
        }

        // IMPORTANT: Use capture phase and passive: false for wheel to intercept and prevent canvas zoom
        canvasHTML.addEventListener('wheel', handleWheelWrapper, { passive: false, capture: true });

        // Add keydown listener to document for Delete key support
        document.addEventListener('keydown', handleKeyDown);

        // Setup ResizeObserver to handle container resize with debouncing
        // to prevent excessive fitCanvas calls that can clear annotations
        if (resizeObserverRef.current) {
            resizeObserverRef.current.disconnect();
        }
        const debouncedFitCanvas = debounce(() => {
            if (mountedRef.current && canvasInstance && canvasContainer) {
                canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
            }
        }, 100);
        resizeObserverRef.current = new ResizeObserver(debouncedFitCanvas);
        resizeObserverRef.current.observe(canvasContainer);

        // Initial setup with current frame data (only if not in draw mode or draw requested)
        if (stateRefs.current.frameData && !shouldPreserveDrawState(canvasInstance, stateRefs.current.activeControl)) {
            // Check if aspect ratio transformation is needed
            // Priority: 1) videoElement (actual decoded video dimensions), 2) Backend metadata (fallback)
            // videoElement gives TRUE dimensions of the video file (e.g., 320x240),
            // while metadata may store task dimensions (e.g., 1920x1080) which can be wrong.
            const metadataDims = getVideoDimensionsFromMetadata(stateRefs.current.multiviewData, stateRefs.current.activeViewId);
            const videoWidth = videoElement?.videoWidth || metadataDims?.width || 0;
            const videoHeight = videoElement?.videoHeight || metadataDims?.height || 0;
            const transformResult = createVideoProportionalFrameData(
                stateRefs.current.frameData,
                videoWidth,
                videoHeight,
            );

            // Store transform params for coordinate transformation on annotation save
            if (transformResult) {
                transformParamsRef.current = {
                    canvasHeight: transformResult.canvasHeight,
                    taskHeight: transformResult.taskHeight,
                    taskWidth: stateRefs.current.frameData.width,
                };
            } else {
                transformParamsRef.current = null;
            }

            const effectiveFrameData = transformResult ? transformResult.frameData : stateRefs.current.frameData;

            const filteredAnnotations = filterAnnotations(stateRefs.current.annotations, {
                frame: stateRefs.current.frameNumber,
                workspace: stateRefs.current.workspace,
                exclude: [ObjectType.TAG],
            }).filter((state: ObjectState) => {
                // Filter by viewId: show annotations for current view only
                // Annotations without viewId are shown only in View 1 (for backward compatibility)
                const stateViewId = (state as any).viewId;
                if (stateViewId === null || stateViewId === undefined) {
                    return stateRefs.current.activeViewId === 1;
                }
                return stateViewId === stateRefs.current.activeViewId;
            });

            // Transform annotations from task space to canvas space for display if needed
            let displayAnnotations = filteredAnnotations;
            if (transformResult) {
                displayAnnotations = filteredAnnotations.map((ann: any) => {
                    if (ann.points && Array.isArray(ann.points)) {
                        const transformedPoints = transformPointsForDisplay(
                            ann.points,
                            transformResult.canvasHeight,
                            transformResult.taskHeight,
                        );
                        // Use explicit property clone instead of spread operator.
                        // ObjectState uses non-enumerable defineProperties, so { ...ann }
                        // copies ZERO properties and breaks canvas setupObjects() diffing.
                        return cloneObjectStateForDisplay(ann, transformedPoints);
                    }
                    return ann;
                });
            }

            // Use video-proportional frameData for canvas coordinate system
            // This eliminates letterboxing and ensures drawing coordinates match the overlay
            canvasInstance.setup(effectiveFrameData, displayAnnotations, stateRefs.current.curZLayer);

            // CRITICAL: Call fitCanvas() and fit() AFTER setup() so imageOffset is calculated
            // using imageSize (from frameData) instead of canvasSize (display container).
            // This ensures correct coordinate transformation for drawing operations.
            canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
            canvasInstance.fit();
        }

        return () => {
            // Only cancel if NOT in draw mode AND no draw operation is requested
            // This prevents interrupting active drawing operations
            if (!shouldPreserveDrawState(canvasInstance, stateRefs.current.activeControl)) {
                canvasInstance.cancel();
            }

            // Remove event listeners on cleanup
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
            // Remove bubble phase listener from SVG content
            const svgContentCleanup = canvasHTML.querySelector('#cvat_canvas_content');
            if (svgContentCleanup) {
                svgContentCleanup.removeEventListener('mousedown', handleMouseDownBubble, { capture: false });
            }
            canvasHTML.removeEventListener('wheel', handleWheelWrapper, { capture: true });
            document.removeEventListener('keydown', handleKeyDown);

            // Disconnect resize observer
            if (resizeObserverRef.current) {
                resizeObserverRef.current.disconnect();
                resizeObserverRef.current = null;
            }

            mountedRef.current = false;
        };
    }, [canvasContainer, canvasInstance]); // Remove activeViewId - viewId changes are handled by separate effects

    // Track previous viewId for canvas setup effect (separate from prevViewIdRef used elsewhere)
    const prevSetupViewIdRef = useRef<number | null>(null);

    /**
     * Setup canvas with frame data when frame or annotations change
     * IMPORTANT: Skip setup if canvas is in draw mode to avoid interrupting active drawing
     */
    useEffect(() => {
        if (!canvasInstance || !frameData || !mountedRef.current) {
            return;
        }

        // CRITICAL: Do not run setup until video dimensions are confirmed.
        // Without valid videoWidth/videoHeight, transformParamsRef will be set to null,
        // causing bbox coordinates to display in task space instead of canvas space.
        // This prevents the race condition where annotations arrive in Redux
        // (via fetchAnnotationsAsync / changeFrameAsync) before the video element
        // has decoded its metadata, resulting in slightly misaligned bboxes on first load.
        // The mount effect (gated by loadedmetadata) handles the initial setup;
        // this effect handles subsequent updates once video dimensions are stable.
        if (!videoElement?.videoWidth || !videoElement?.videoHeight) {
            return;
        }

        // Skip setup if canvas is in draw mode or draw operation is requested
        // This preserves active drawing state - canvas will be updated when drawing completes
        if (shouldPreserveDrawState(canvasInstance, activeControl)) {
            return;
        }

        // Check if viewId changed - need to recalculate canvas scale when view changes
        // because canvas may be attached to different container with different size
        const viewChanged = prevSetupViewIdRef.current !== null && prevSetupViewIdRef.current !== activeViewId;

        // Check if aspect ratio transformation is needed
        // Priority: 1) videoElement (actual decoded video dimensions), 2) Backend metadata (fallback)
        // videoElement gives TRUE dimensions of the video file (e.g., 320x240),
        // while metadata may store task dimensions (e.g., 1920x1080) which can be wrong.
        const metadataDims = getVideoDimensionsFromMetadata(multiviewData, activeViewId);
        const videoWidth = videoElement.videoWidth || metadataDims?.width || 0;
        const videoHeight = videoElement.videoHeight || metadataDims?.height || 0;
        const transformResult = createVideoProportionalFrameData(frameData, videoWidth, videoHeight);

        // Store transform params for coordinate transformation on annotation save
        if (transformResult) {
            transformParamsRef.current = {
                canvasHeight: transformResult.canvasHeight,
                taskHeight: transformResult.taskHeight,
                taskWidth: frameData.width,
            };
        } else {
            transformParamsRef.current = null;
        }

        const effectiveFrameData = transformResult ? transformResult.frameData : frameData;

        // Filter annotations for current view and exclude tags
        const filteredAnnotations = filterAnnotations(annotations, {
            frame: frameNumber,
            workspace,
            exclude: [ObjectType.TAG],
        }).filter((state: ObjectState) => {
            // Filter by viewId: show annotations for current view only
            // Annotations without viewId are shown only in View 1 (for backward compatibility)
            const stateViewId = (state as any).viewId;
            if (stateViewId === null || stateViewId === undefined) {
                return activeViewId === 1;
            }
            return stateViewId === activeViewId;
        });

        // Transform annotations from task space to canvas space for display if needed
        let displayAnnotations = filteredAnnotations;
        if (transformResult) {
            displayAnnotations = filteredAnnotations.map((ann: any) => {
                if (ann.points && Array.isArray(ann.points)) {
                    const transformedPoints = transformPointsForDisplay(
                        ann.points,
                        transformResult.canvasHeight,
                        transformResult.taskHeight,
                    );
                    // Use explicit property clone instead of spread operator.
                    // ObjectState uses non-enumerable defineProperties, so { ...ann }
                    // copies ZERO properties and breaks canvas setupObjects() diffing.
                    return cloneObjectStateForDisplay(ann, transformedPoints);
                }
                return ann;
            });
        }

        // Use video-proportional frameData for canvas coordinate system
        // This eliminates letterboxing and ensures drawing coordinates match the overlay
        canvasInstance.setup(effectiveFrameData, displayAnnotations, curZLayer);

        // CRITICAL: Always call fitCanvas() and fit() AFTER setup() to ensure proper scale calculation.
        // setup() sets imageSize from frameData, and fitCanvas()/fit() calculate imageOffset and scale
        // using imageSize. Without this order, imageOffset is calculated from canvasSize (display container)
        // instead of imageSize (video dimensions), causing coordinate mismatch (~50% smaller drawings).
        //
        // Call fitCanvas() on:
        // 1. Initial setup (prevSetupViewIdRef.current is null)
        // 2. View changes (need to update canvasSize from new container)
        const isInitialSetup = prevSetupViewIdRef.current === null;
        if (canvasContainer) {
            if (isInitialSetup || viewChanged) {
                canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
            }
            canvasInstance.fit();
        }

        // Always update prevSetupViewIdRef after processing
        prevSetupViewIdRef.current = activeViewId;
    }, [canvasInstance, canvasContainer, frameData, videoElement, annotations, curZLayer, activeViewId, frameNumber, workspace, activeControl, multiviewData]);

    /**
     * Update canvas viewId when active view changes
     */
    useEffect(() => {
        if (!canvasInstance) {
            return;
        }

        if (typeof (canvasInstance as any).setViewId === 'function') {
            (canvasInstance as any).setViewId(activeViewId);
        }
    }, [canvasInstance, activeViewId]);

    /**
     * Activate shape on canvas when activatedStateID changes in Redux
     * This shows resize handles and enables dragging for the selected shape
     */
    useEffect(() => {
        if (!canvasInstance) {
            return;
        }

        // Find the activated state to check if it's a valid annotation (not a tag)
        const activatedState = annotations.find(
            (state: ObjectState) => state.clientID === activatedStateID,
        );

        // Only activate if it's a valid annotation (not a tag) or if deactivating (null)
        if (activatedStateID === null || (activatedState && activatedState.objectType !== ObjectType.TAG)) {
            canvasInstance.activate(activatedStateID, activatedAttributeID);
        }
    }, [canvasInstance, activatedStateID, activatedAttributeID, annotations]);

    // Note: Removed the activeControl effect that was calling canvasInstance.cancel()
    // when activeControl changed to a draw mode. This was causing the drawing to be
    // immediately canceled after starting. The canvas mode is properly managed by
    // the draw-shape-popover which calls canvasInstance.draw() to start drawing.

    // This component doesn't render anything - it just manages the canvas
    return null;
}
