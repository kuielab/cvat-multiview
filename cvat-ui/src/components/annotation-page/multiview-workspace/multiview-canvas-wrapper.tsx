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
} from 'actions/annotation-actions';
import { filterAnnotations } from 'utils/filter-annotations';

const cvat = getCore();

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
        };
    }, [activeLabelID, activeObjectType, frameNumber, activeViewId, jobInstance, annotations, curZLayer, frameData, workspace]);

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
            console.error('[MultiviewCanvas] Failed to create annotation:', error);
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
     * Mount canvas to container - only depends on container and canvas instance
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
        }
        canvasInstance.cancel();

        // Set the active view ID on canvas for multiview annotation tracking
        if (typeof (canvasInstance as any).setViewId === 'function') {
            (canvasInstance as any).setViewId(activeViewId);
        }

        // Configure canvas for multiview mode
        canvasInstance.configure({
            forceDisableEditing: stateRefs.current.workspace === Workspace.REVIEW,
        });

        // Fit canvas to container size
        canvasInstance.fitCanvas();

        // Add event listeners
        canvasHTML.addEventListener('canvas.drawn', onCanvasShapeDrawn);
        canvasHTML.addEventListener('canvas.setup', onCanvasSetup);
        canvasHTML.addEventListener('canvas.canceled', onCanvasCancel);
        canvasHTML.addEventListener('canvas.zoomstart', onCanvasZoomStart);
        canvasHTML.addEventListener('canvas.zoomstop', onCanvasZoomDone);
        canvasHTML.addEventListener('canvas.dragstart', onCanvasDragStart);
        canvasHTML.addEventListener('canvas.dragstop', onCanvasDragDone);

        // Setup ResizeObserver to handle container resize
        if (resizeObserverRef.current) {
            resizeObserverRef.current.disconnect();
        }
        resizeObserverRef.current = new ResizeObserver(() => {
            if (mountedRef.current && canvasInstance) {
                canvasInstance.fitCanvas();
            }
        });
        resizeObserverRef.current.observe(canvasContainer);

        // Initial setup with current frame data
        if (stateRefs.current.frameData) {
            const filteredAnnotations = filterAnnotations(stateRefs.current.annotations, {
                frame: stateRefs.current.frameNumber,
                workspace: stateRefs.current.workspace,
                exclude: [ObjectType.TAG],
            }).filter((state: ObjectState) => {
                // Filter by viewId: show annotations for current view or annotations without viewId
                const stateViewId = (state as any).viewId;
                return stateViewId === stateRefs.current.activeViewId || stateViewId === null || stateViewId === undefined;
            });

            canvasInstance.setup(stateRefs.current.frameData, filteredAnnotations, stateRefs.current.curZLayer);
        }

        return () => {
            // Cancel any active drawing when unmounting
            canvasInstance.cancel();

            // Remove event listeners on cleanup
            canvasHTML.removeEventListener('canvas.drawn', onCanvasShapeDrawn);
            canvasHTML.removeEventListener('canvas.setup', onCanvasSetup);
            canvasHTML.removeEventListener('canvas.canceled', onCanvasCancel);
            canvasHTML.removeEventListener('canvas.zoomstart', onCanvasZoomStart);
            canvasHTML.removeEventListener('canvas.zoomstop', onCanvasZoomDone);
            canvasHTML.removeEventListener('canvas.dragstart', onCanvasDragStart);
            canvasHTML.removeEventListener('canvas.dragstop', onCanvasDragDone);

            // Disconnect resize observer
            if (resizeObserverRef.current) {
                resizeObserverRef.current.disconnect();
                resizeObserverRef.current = null;
            }

            mountedRef.current = false;
        };
    }, [canvasContainer, canvasInstance, activeViewId, onCanvasShapeDrawn, onCanvasSetup, onCanvasCancel, onCanvasZoomStart, onCanvasZoomDone, onCanvasDragStart, onCanvasDragDone]);

    /**
     * Setup canvas with frame data when frame or annotations change
     */
    useEffect(() => {
        if (!canvasInstance || !frameData || !mountedRef.current) {
            return;
        }

        // Filter annotations for current view and exclude tags
        const filteredAnnotations = filterAnnotations(annotations, {
            frame: frameNumber,
            workspace,
            exclude: [ObjectType.TAG],
        }).filter((state: ObjectState) => {
            // Filter by viewId: show annotations for current view or annotations without viewId
            const stateViewId = (state as any).viewId;
            return stateViewId === activeViewId || stateViewId === null || stateViewId === undefined;
        });

        canvasInstance.setup(frameData, filteredAnnotations, curZLayer);
    }, [canvasInstance, frameData, annotations, curZLayer, activeViewId, frameNumber, workspace]);

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
