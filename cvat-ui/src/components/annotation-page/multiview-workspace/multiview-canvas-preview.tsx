// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';

import { Canvas } from 'cvat-canvas-wrapper';
import { CombinedState, Workspace } from 'reducers';
import { ObjectState, ObjectType } from 'cvat-core-wrapper';
import { filterAnnotations } from 'utils/filter-annotations';
import {
    createVideoProportionalFrameData,
    transformPointsForDisplay,
    cloneObjectStateForDisplay,
} from './multiview-canvas-utils';
import { useStableVideoDims } from './use-stable-video-dims';
import { fetchMultiviewFrameImage } from './multiview-frame-provider';

interface Props {
    container: HTMLDivElement | null;
    videoElement: HTMLVideoElement | null;
    viewId: number;
}

export default function MultiviewCanvasPreview(props: Props): JSX.Element | null {
    const { container, videoElement, viewId } = props;
    const canvasRef = useRef<Canvas | null>(null);

    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const frameData = useSelector((state: CombinedState) => state.annotation.player.frame.data);
    const annotations = useSelector((state: CombinedState) => state.annotation.annotations.states);
    const curZLayer = useSelector((state: CombinedState) => state.annotation.annotations.zLayer.cur);
    const workspace = useSelector((state: CombinedState) => state.annotation.workspace);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);
    const jobInstance = useSelector((state: CombinedState) => state.annotation.job.instance);

    const { getStableVideoDims, version: videoDimsVersion } = useStableVideoDims({
        videoElement,
        activeViewId: viewId,
        multiviewData,
        samplesRequired: 2,
        maxWaitMs: 1200,
        allowTimeoutFallback: false,
    });

    useEffect(() => {
        if (!container) return undefined;

        if (!canvasRef.current) {
            canvasRef.current = new Canvas();
        }

        const canvasInstance = canvasRef.current;
        const html = canvasInstance.html();
        if (container.firstChild !== html) {
            container.innerHTML = '';
            container.appendChild(html);
        }

        if (typeof (canvasInstance as any).setViewId === 'function') {
            (canvasInstance as any).setViewId(viewId);
        }

        canvasInstance.configure({
            forceDisableEditing: true,
        });

        return () => {
            if (container.contains(html)) {
                container.removeChild(html);
            }
        };
    }, [container]);

    useEffect(() => {
        const canvasInstance = canvasRef.current;
        if (!canvasInstance || !container || !frameData) return;

        const stableVideoDims = getStableVideoDims();
        if (!stableVideoDims) return;

        const transformResult = createVideoProportionalFrameData(
            frameData,
            stableVideoDims.width,
            stableVideoDims.height,
        );

        const filtered = filterAnnotations(annotations, {
            frame: frameNumber,
            workspace,
            exclude: [ObjectType.TAG],
        }).filter((state: ObjectState) => {
            const stateViewId = (state as any).viewId;
            if (stateViewId === null || stateViewId === undefined) {
                return viewId === 1;
            }
            return stateViewId === viewId;
        });

        let displayAnnotations = filtered;
        if (transformResult) {
            displayAnnotations = filtered.map((ann: any) => {
                if (ann.points && Array.isArray(ann.points)) {
                    const transformedPoints = transformPointsForDisplay(
                        ann.points,
                        transformResult.transform.canvasWidth,
                        transformResult.transform.canvasHeight,
                        transformResult.transform.taskHeight,
                        transformResult.transform.taskWidth,
                    );
                    return cloneObjectStateForDisplay(ann, transformedPoints);
                }
                return ann;
            });
        }

        let effectiveFrameData = transformResult ? transformResult.frameData : frameData;
        const taskId = jobInstance?.taskId ?? null;
        const renderWidth = stableVideoDims.width;
        const renderHeight = stableVideoDims.height;
        effectiveFrameData = new Proxy(effectiveFrameData, {
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
                                    renderWidthFallback: renderWidth,
                                    renderHeightFallback: renderHeight,
                                });
                            } catch (error) {
                                return target.data(...args);
                            }
                        }
                        return target.data(...args);
                    };
                }
                return Reflect.get(target, prop, receiver);
            },
        });

        canvasInstance.setup(effectiveFrameData, displayAnnotations, curZLayer);
        canvasInstance.fitCanvas(container.clientWidth, container.clientHeight);
        canvasInstance.fit();
    }, [
        container,
        frameData,
        frameNumber,
        annotations,
        curZLayer,
        workspace,
        viewId,
        videoDimsVersion,
        getStableVideoDims,
        jobInstance,
    ]);

    return null;
}
