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

export default function MultiviewCanvasWrapper(props: Props): JSX.Element | null {
    const { canvasContainer, videoElement, activeViewId } = props;
    const dispatch = useDispatch();
    const mountedRef = useRef(false);
    const resizeObserverRef = useRef<ResizeObserver | null>(null);
    const prevViewIdRef = useRef<number | null>(null);

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
    const activeControl = useSelector((state: CombinedState) => state.annotation.canvas.activeControl);

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
        };
    }, [activeLabelID, activeObjectType, frameNumber, activeViewId, jobInstance, annotations, curZLayer, frameData, workspace, activatedStateID, activeControl]);

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
     * Handle canvas shape clicked - scroll sidebar to show the clicked item
     */
    const onCanvasShapeClicked = useCallback((e: any): void => {
        const { clientID, parentID } = e.detail.state;
        let sidebarItem = null;
        if (Number.isInteger(parentID)) {
            sidebarItem = window.document.getElementById(`cvat-objects-sidebar-state-item-element-${clientID}`);
        } else {
            sidebarItem = window.document.getElementById(`cvat-objects-sidebar-state-item-${clientID}`);
        }

        if (sidebarItem) {
            sidebarItem.scrollIntoView();
        }
    }, []);

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
     */
    const onCanvasMouseDown = useCallback((e: MouseEvent): void => {
        const refs = stateRefs.current;
        if ((e.target as HTMLElement).tagName === 'svg' && e.button !== 2) {
            if (refs.activatedStateID !== null) {
                dispatch(activateObject(null, null, null));
            }
        }
    }, [dispatch]);

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
     */
    const onCanvasEditDone = useCallback((event: any): void => {
        const { state, points, rotation } = event.detail;
        state.points = points;
        state.rotation = rotation;
        dispatch(updateAnnotationsAsync([state]));
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
            onKeyDown,
        };
    }, [onCanvasShapeDrawn, onCanvasSetup, onCanvasCancel, onCanvasZoomStart, onCanvasZoomDone, onCanvasDragStart, onCanvasDragDone, onCanvasShapeClicked, onCanvasShapeDeactivated, onCanvasCursorMoved, onCanvasEditDone, onCanvasMouseDown, onKeyDown]);

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

        // Fit canvas to container size - pass container dimensions explicitly
        // because SVG element dimensions may not match container after view switch
        canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
        canvasInstance.fit(); // Recalculate scale based on new canvas size

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
        const handleKeyDown = (e: KeyboardEvent): void => {
            eventHandlersRef.current.onKeyDown?.(e);
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
        canvasHTML.addEventListener('canvas.editdone', handleEditDone);
        canvasHTML.addEventListener('mousedown', handleMouseDown);

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

            // Use original frameData dimensions (task metadata) for canvas coordinate system
            // This ensures annotations are stored in the correct coordinate space (e.g., 1920x1080)
            // even when the video element shows transcoded lower-resolution chunks (e.g., 320x240)
            canvasInstance.setup(stateRefs.current.frameData, filteredAnnotations, stateRefs.current.curZLayer);
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
            canvasHTML.removeEventListener('canvas.editdone', handleEditDone);
            canvasHTML.removeEventListener('mousedown', handleMouseDown);
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

        // Note: We use frameData dimensions (task metadata) for canvas coordinate system
        // This ensures annotations are stored in the correct coordinate space (e.g., 1920x1080)
        // even when the video element shows transcoded lower-resolution chunks (e.g., 320x240)

        // Skip setup if canvas is in draw mode or draw operation is requested
        // This preserves active drawing state - canvas will be updated when drawing completes
        if (shouldPreserveDrawState(canvasInstance, activeControl)) {
            return;
        }

        // Check if viewId changed - need to recalculate canvas scale when view changes
        // because canvas may be attached to different container with different size
        const viewChanged = prevSetupViewIdRef.current !== null && prevSetupViewIdRef.current !== activeViewId;

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

        // Use original frameData dimensions (task metadata) for canvas coordinate system
        // This ensures annotations are stored in the correct coordinate space (e.g., 1920x1080)
        // even when the video element shows transcoded lower-resolution chunks (e.g., 320x240)
        // The canvas handles the visual scaling between display and coordinate system internally
        canvasInstance.setup(frameData, filteredAnnotations, curZLayer);

        // Call fitCanvas() and fit() AFTER setup() when view changes
        // Order matters:
        // 1. setup() sets imageSize from frameData
        // 2. fitCanvas() sets canvasSize from container dimensions
        // 3. fit() recalculates scale based on imageSize and canvasSize
        // Without this sequence, view switching leaves stale scale/size from previous view
        if (viewChanged && canvasContainer) {
            canvasInstance.fitCanvas(canvasContainer.clientWidth, canvasContainer.clientHeight);
            canvasInstance.fit();
        }

        // Always update prevSetupViewIdRef after processing
        prevSetupViewIdRef.current = activeViewId;
    }, [canvasInstance, canvasContainer, frameData, annotations, curZLayer, activeViewId, frameNumber, workspace, activeControl]);

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

    // Note: Removed the activeControl effect that was calling canvasInstance.cancel()
    // when activeControl changed to a draw mode. This was causing the drawing to be
    // immediately canceled after starting. The canvas mode is properly managed by
    // the draw-shape-popover which calls canvasInstance.draw() to start drawing.

    // This component doesn't render anything - it just manages the canvas
    return null;
}
