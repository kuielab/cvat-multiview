// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useEffect, useRef, useCallback } from 'react';
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
    removeObjectAsync,
} from 'actions/annotation-actions';
import { filterAnnotations } from 'utils/filter-annotations';
import { bindCanvasEventHandlers, CanvasEventHandlers } from './multiview-canvas-events';
import { runSetupPipeline } from './multiview-canvas-setup';
import {
    clampPointsToCanvasBounds,
    cloneObjectStateForDisplay,
    enforceMinimumShapeDimensions,
    normalizeAndEnforceTaskSpaceDimensions,
} from './multiview-canvas-utils';
import { fetchMultiviewFrameImage } from './multiview-frame-provider';

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
    activeViewId: number;
}

function prepareDisplayAnnotations(params: {
    annotations: ObjectState[];
    frameNumber: number;
    workspace: Workspace;
    activeViewId: number;
}): ObjectState[] {
    const {
        annotations,
        frameNumber,
        workspace,
        activeViewId,
    } = params;

    const filtered = filterAnnotations(annotations, {
        frame: frameNumber,
        workspace,
        exclude: [ObjectType.TAG],
    }).filter((state: ObjectState) => {
        const stateViewId = (state as any).viewId;
        if (stateViewId === null || stateViewId === undefined) {
            return activeViewId === 1;
        }
        return stateViewId === activeViewId;
    });

    return filtered.map((ann: any) => (
        ann.points && Array.isArray(ann.points) ?
            cloneObjectStateForDisplay(ann, ann.points) : ann
    ));
}

function getViewDimensions(
    multiviewData: any,
    viewId: number,
    frameData: any,
): { width: number; height: number } {
    const viewKey = `view${viewId}`;
    const viewData = multiviewData?.videos?.[viewKey];
    const width = viewData?.width || frameData?.width || 0;
    const height = viewData?.height || frameData?.height || 0;
    return { width, height };
}

export default function MultiviewCanvasWrapper(props: Props): JSX.Element | null {
    const { canvasContainer, activeViewId } = props;
    const dispatch = useDispatch();
    const mountedRef = useRef(false);
    const resizeObserverRef = useRef<ResizeObserver | null>(null);
    const prevViewIdRef = useRef<number | null>(null);
    const setupCompletedRef = useRef(false);
    // Track whether viewport has been locked after initial setup.
    // When locked, ResizeObserver only re-fits if the container size actually
    // changed (e.g., spectrogram panel load, sidebar toggle). This prevents
    // redundant fitCanvas calls while still handling legitimate layout shifts
    // that would otherwise leave canvasSize stale and cause bbox misalignment.
    const viewportLockedRef = useRef(false);

    const prevContainerSizeRef = useRef<{ width: number; height: number } | null>(null);

    // Canvas-only mode: frame dimensions come directly from metadata.

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
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);

    const debugMultiview = typeof window !== 'undefined' &&
        (window as any).CVAT_DEBUG_MULTIVIEW === true;

    const logDebug = useCallback((message: string, payload?: Record<string, unknown>): void => {
        if (!debugMultiview) return;
        // eslint-disable-next-line no-console
        console.debug(`[MultiviewCanvas] ${message}`, payload || {});
    }, [debugMultiview]);

    const createFrameDataFromMultiview = useCallback((
        baseFrameData: any,
        taskId: number | null,
        viewId: number,
        renderWidth: number,
        renderHeight: number,
        jobStartFrame: number,
        isPlaying: boolean,
        step: number,
    ) => {
        const proxy = new Proxy(baseFrameData, {
            get(target, prop, receiver) {
                if (prop === 'width') {
                    return renderWidth || Reflect.get(target, prop, receiver);
                }
                if (prop === 'height') {
                    return renderHeight || Reflect.get(target, prop, receiver);
                }
                if (prop === 'data') {
                    return async (...args: any[]) => {
                        if (taskId) {
                            try {
                                return await fetchMultiviewFrameImage({
                                    taskId,
                                    viewId,
                                    frameNumber: target.number,
                                    jobStartFrame,
                                    isPlaying,
                                    step,
                                });
                            } catch (error) {
                                // Fallback to base frame data if fetch fails
                                return baseFrameData.data(...args);
                            }
                        }
                        return baseFrameData.data(...args);
                    };
                }
                return Reflect.get(target, prop, receiver);
            },
        });
        return proxy;
    }, []);

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
    const eventHandlersRef = useRef<CanvasEventHandlers>({
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
        onMouseDownBubble: null,
        onKeyDown: null,
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
        const currentFrameData = refs.frameData;
        if (state.points && Array.isArray(state.points) && currentFrameData) {
            const { width, height } = getViewDimensions(
                refs.multiviewData,
                refs.activeViewId,
                currentFrameData,
            );
            state.points = clampPointsToCanvasBounds(
                state.points,
                width,
                height,
            );

            if (state.shapeType === 'rectangle' && state.points.length === 4 && !state.rotation) {
                state.points = normalizeAndEnforceTaskSpaceDimensions(
                    state.points,
                    width,
                    height,
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
            // Save window scroll before scrollIntoView to prevent window-level
            // scrolling when the sidebar extends beyond the viewport (small screens).
            const scrollX = window.scrollX;
            const scrollY = window.scrollY;
            sidebarItem.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            window.scrollTo(scrollX, scrollY);
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

        // ALWAYS block middle-click (button === 1) and right-click (button === 2) on canvas
        // regardless of draw mode. These buttons are never used for drawing or shape editing.
        // CSS-based pan in video-canvas.tsx handles these buttons for viewport panning when
        // zoomed in. Without this, SVG.js draggable handlers on shape elements receive
        // the mousedown and initiate shape drag, causing bbox to move during pan.
        // Use stopImmediatePropagation to also prevent any other listeners on the same element.
        if (e.button === 1 || e.button === 2) {
            e.stopImmediatePropagation();
            e.preventDefault();
            return;
        }

        // CRITICAL: Do NOT block LEFT-CLICK events when canvas is in draw mode or draw
        // operation is requested. Drawing requires mousedown events on background to start
        // drawing shapes. Only left-click (button 0) is used for drawing.
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
     * IMPORTANT: The state from event.detail may be a shallow copy (without save() method).
     * We need to find the original ObjectState from Redux and update it.
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
        let updatedPoints = points;
        if (!rotation && state.shapeType === 'rectangle' &&
            updatedPoints && Array.isArray(updatedPoints) && updatedPoints.length === 4 &&
            state.points && state.points.length === 4) {
            updatedPoints = enforceMinimumShapeDimensions(updatedPoints, state.points);
        }

        const currentFrameData = refs.frameData;
        if (currentFrameData && updatedPoints && Array.isArray(updatedPoints)) {
            const { width, height } = getViewDimensions(
                refs.multiviewData,
                refs.activeViewId,
                currentFrameData,
            );
            if (!rotation) {
                updatedPoints = clampPointsToCanvasBounds(
                    updatedPoints,
                    width,
                    height,
                );
            }

            if (!rotation && state.shapeType === 'rectangle' &&
                updatedPoints.length === 4) {
                updatedPoints = normalizeAndEnforceTaskSpaceDimensions(
                    updatedPoints,
                    width,
                    height,
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
     * Handle keydown event - Delete key to remove activated annotation.
     * Uses removeObjectAsync directly for reliable deletion, bypassing the
     * RemoveConfirmComponent flow which can have timing issues when both
     * this handler and the react-hotkeys handler in ObjectsListContainer fire.
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

        // Prevent default behavior and stop propagation FIRST to prevent
        // the react-hotkeys handler in ObjectsListContainer from also handling
        // this event (which would cause a double-delete attempt)
        event.preventDefault();
        event.stopImmediatePropagation();

        // Check if object is locked (shift key forces delete of locked objects)
        const force = event.shiftKey;

        // Use removeObjectAsync directly for reliable deletion
        dispatch(removeObjectAsync(activatedState, force));
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
        };
    }, [onCanvasShapeDrawn, onCanvasSetup, onCanvasCancel, onCanvasZoomStart, onCanvasZoomDone, onCanvasDragStart, onCanvasDragDone, onCanvasShapeClicked, onCanvasShapeDeactivated, onCanvasCursorMoved, onCanvasEditDone, onCanvasMouseDown, onCanvasMouseDownBubble, onKeyDown]);

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

        setupCompletedRef.current = false;

        // Clear container first
        while (canvasContainer.firstChild) {
            canvasContainer.removeChild(canvasContainer.firstChild);
        }

        // Mount canvas HTML to container
        const canvasHTML = canvasInstance.html();
        canvasContainer.appendChild(canvasHTML);
        mountedRef.current = true;

        // Initialize container size tracking early so ResizeObserver has a baseline
        prevContainerSizeRef.current = {
            width: canvasContainer.clientWidth,
            height: canvasContainer.clientHeight,
        };

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

        const cleanupCanvasEvents = bindCanvasEventHandlers(canvasHTML, eventHandlersRef);

        // Setup ResizeObserver to handle container resize with debouncing.
        // When the container resizes (e.g., sidebar toggle, spectrogram panel load),
        // we must update canvas dimensions AND re-fit the viewport to keep shapes
        // aligned. Without calling fit() after fitCanvas(), the canvas dimensions
        // change but top/left/scale remain stale, causing bbox misalignment.
        //
        // When CSS zoom is active, skip fit() to avoid resetting the SVG viewport
        // which would cause shapes to visually jump.
        if (resizeObserverRef.current) {
            resizeObserverRef.current.disconnect();
        }
        const debouncedFitCanvas = debounce(() => {
            if (mountedRef.current && canvasInstance && canvasContainer) {
                if (!setupCompletedRef.current) {
                    logDebug('resize skipped: setup not completed', {
                        containerWidth: canvasContainer.clientWidth,
                        containerHeight: canvasContainer.clientHeight,
                    });
                    return;
                }

                const containerWidth = canvasContainer.clientWidth;
                const containerHeight = canvasContainer.clientHeight;

                // Skip if container has zero dimensions (e.g., tab switch)
                if (containerWidth <= 0 || containerHeight <= 0) {
                    logDebug('resize skipped: container has zero size', {
                        containerWidth,
                        containerHeight,
                    });
                    return;
                }

                // When viewport is already locked, only re-fit if the container
                // size actually changed. This handles the case where the layout
                // shifts after initial setup (e.g., spectrogram panel loads,
                // sidebar renders) which would otherwise leave canvasSize stale,
                // causing bbox position misalignment on subsequent fit() calls.
                const currentGeometry = canvasInstance.geometry;
                if (!currentGeometry || currentGeometry.image.width <= 0 || currentGeometry.image.height <= 0) {
                    logDebug('resize skipped: geometry not ready', {
                        imageWidth: currentGeometry?.image.width,
                        imageHeight: currentGeometry?.image.height,
                    });
                    return;
                }

                if (viewportLockedRef.current) {
                    if (currentGeometry.canvas.width === containerWidth &&
                        currentGeometry.canvas.height === containerHeight) {
                        logDebug('resize skipped: container unchanged', {
                            canvasWidth: currentGeometry.canvas.width,
                            canvasHeight: currentGeometry.canvas.height,
                        });
                        return;
                    }
                }

                logDebug('resize applying fitCanvas', {
                    containerWidth,
                    containerHeight,
                });

                // Capture old container size before updating
                const oldSize = prevContainerSizeRef.current;

                canvasInstance.fitCanvas(containerWidth, containerHeight);

                // Always call fit() to keep SVG viewport geometry in sync.
                // CSS zoom transform is additive on top of this baseline.
                canvasInstance.fit();

                // Update tracked container size
                prevContainerSizeRef.current = { width: containerWidth, height: containerHeight };

                // Re-lock viewport after updating
                if (typeof (canvasInstance as any).lockViewport === 'function') {
                    (canvasInstance as any).lockViewport();
                    viewportLockedRef.current = true;
                }
            }
        }, 100);
        resizeObserverRef.current = new ResizeObserver(debouncedFitCanvas);
        resizeObserverRef.current.observe(canvasContainer);

        // NOTE: Initial setup() is NOT called here. The setup effect (below) is the SOLE
        // path for canvas setup. This eliminates a race condition where the mount effect
        // and setup effect could call setup() with different video dimensions / transform
        // params, causing bbox position misalignment on page refresh.
        // The setup effect will fire once frameData and annotations are ready.

        return () => {
            // Only cancel if NOT in draw mode AND no draw operation is requested
            // This prevents interrupting active drawing operations
            if (!shouldPreserveDrawState(canvasInstance, stateRefs.current.activeControl)) {
                canvasInstance.cancel();
            }

            cleanupCanvasEvents();

            // Disconnect resize observer
            if (resizeObserverRef.current) {
                resizeObserverRef.current.disconnect();
                resizeObserverRef.current = null;
            }

            mountedRef.current = false;
            // Reset viewport lock so the next mount/setup cycle can call fitCanvas
            viewportLockedRef.current = false;
            setupCompletedRef.current = false;
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

        if (canvasContainer) {
            const w = canvasContainer.clientWidth;
            const h = canvasContainer.clientHeight;
            if (w <= 0 || h <= 0) {
                logDebug('setup skipped: container has zero size', { w, h });
                return;
            }
        }

        // Skip setup if canvas is in draw mode or draw operation is requested
        // This preserves active drawing state - canvas will be updated when drawing completes
        if (shouldPreserveDrawState(canvasInstance, activeControl)) {
            return;
        }

        // Check if viewId changed - need to recalculate canvas scale when view changes
        // because canvas may be attached to different container with different size
        const viewChanged = prevSetupViewIdRef.current !== null && prevSetupViewIdRef.current !== activeViewId;

        // Unlock viewport on view change so fitCanvas can update geometry for new container
        if (viewChanged) {
            viewportLockedRef.current = false;
            setupCompletedRef.current = false;
        }

        let effectiveFrameData = frameData;
        const taskId = jobInstance?.taskId ?? null;
        const jobStartFrame = jobInstance?.startFrame || 0;
        const step = (jobInstance as any)?.frameStep || 1;
        const { width, height } = getViewDimensions(multiviewData, activeViewId, frameData);
        effectiveFrameData = createFrameDataFromMultiview(
            effectiveFrameData,
            taskId,
            activeViewId,
            width,
            height,
            jobStartFrame,
            playing,
            step,
        );

        const isInitialSetup = prevSetupViewIdRef.current === null;
        const displayAnnotations = prepareDisplayAnnotations({
            annotations,
            frameNumber,
            workspace,
            activeViewId,
        });

        runSetupPipeline({
            canvasInstance,
            canvasContainer,
            frameData: effectiveFrameData,
            displayAnnotations,
            curZLayer,
            viewChanged,
            isInitialSetup,
            onViewportLocked: () => {
                viewportLockedRef.current = true;
            },
        });
        logDebug('setup completed', {
            frame: frameNumber,
            viewId: activeViewId,
            viewChanged,
            isInitialSetup,
        });
        setupCompletedRef.current = true;

        // Initialize container size tracking for resize-while-zoomed detection
        if (canvasContainer) {
            prevContainerSizeRef.current = {
                width: canvasContainer.clientWidth,
                height: canvasContainer.clientHeight,
            };
        }

        // Always update prevSetupViewIdRef after processing
        prevSetupViewIdRef.current = activeViewId;
    }, [
        canvasInstance,
        canvasContainer,
        frameData,
        annotations,
        curZLayer,
        activeViewId,
        frameNumber,
        workspace,
        activeControl,
        playing,
        jobInstance,
        multiviewData,
    ]);

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

    // When activeControl transitions away from a draw mode back to CURSOR,
    // explicitly disable drawing so the canvas cleans up draw state (crosshair, etc.).
    // Note: We only call draw({ enabled: false }) when LEAVING draw mode, not when entering.
    // Entering draw mode is handled by the draw-shape-popover which calls canvasInstance.draw().
    useEffect(() => {
        if (!canvasInstance) return;
        if (!isDrawOperationRequested(activeControl)) {
            try {
                canvasInstance.draw({ enabled: false });
            } catch {
                // Canvas might not be in a drawable state
            }
        }
    }, [canvasInstance, activeControl]);

    // This component doesn't render anything - it just manages the canvas
    return null;
}
