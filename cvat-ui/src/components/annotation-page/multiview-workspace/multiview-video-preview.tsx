// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useEffect, useRef, useMemo } from 'react';
import { useSelector } from 'react-redux';
import { CombinedState, Workspace } from 'reducers';
import { ObjectState, ObjectType } from 'cvat-core-wrapper';
import { filterAnnotations } from 'utils/filter-annotations';

interface Props {
    viewId: number;
    playbackRate: number;
}

/**
 * Preview component that renders inactive views using a native HTML <video> element
 * with an SVG overlay showing bbox annotations for this view.
 * Uses browser hardware video decoding instead of Canvas + Broadway.js software decoding.
 * The active view continues to use CVAT Canvas for annotation interaction.
 */
export default function MultiviewVideoPreview(props: Props): JSX.Element {
    const { viewId, playbackRate } = props;
    const videoRef = useRef<HTMLVideoElement>(null);
    const prevPlayingRef = useRef<boolean>(false);

    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);
    const annotations = useSelector((state: CombinedState) => state.annotation.annotations.states);
    const workspace = useSelector((state: CombinedState) => state.annotation.workspace);

    const fps = multiviewData?.videos?.view1?.fps || 30;
    const viewKey = `view${viewId}` as keyof typeof multiviewData.videos;
    const videoUrl = multiviewData?.videos?.[viewKey]?.url || '';
    const videoWidth = multiviewData?.videos?.[viewKey]?.width || 320;
    const videoHeight = multiviewData?.videos?.[viewKey]?.height || 240;

    // Filter annotations for this specific view's bbox overlay
    const viewAnnotations = useMemo(() => {
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

        return filtered.filter((ann: any) => (
            ann.shapeType === 'rectangle' &&
            ann.points?.length >= 4 &&
            !ann.outside
        ));
    }, [annotations, frameNumber, workspace, viewId]);

    // Sync playback state: play/pause and seek
    useEffect(() => {
        const video = videoRef.current;
        if (!video || !videoUrl) return;

        const wasPlaying = prevPlayingRef.current;
        prevPlayingRef.current = playing;

        if (playing && !wasPlaying) {
            // Starting playback: seek to current frame, set rate, then play
            video.currentTime = frameNumber / fps;
            video.playbackRate = playbackRate;
            video.play().catch(() => {
                // Autoplay may be blocked; silently ignore
            });
        } else if (!playing && wasPlaying) {
            // Pausing: stop video and seek to exact frame
            video.pause();
            video.currentTime = frameNumber / fps;
        } else if (!playing) {
            // Seek while paused (frame navigation)
            video.currentTime = frameNumber / fps;
        }
        // During playback, let <video> free-run (no per-frame sync needed)
    }, [playing, frameNumber, fps, videoUrl, playbackRate]);

    // Update playback rate when changed during playback
    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;
        video.playbackRate = playbackRate;
    }, [playbackRate]);

    return (
        <div className='multiview-preview-container'>
            <video
                ref={videoRef}
                className='multiview-video-preview'
                src={videoUrl}
                muted
                playsInline
                preload='auto'
            />
            {viewAnnotations.length > 0 && (
                <svg
                    className='multiview-preview-bbox-overlay'
                    viewBox={`0 0 ${videoWidth} ${videoHeight}`}
                    preserveAspectRatio='xMidYMid meet'
                >
                    {viewAnnotations.map((ann: any) => {
                        const [xtl, ytl, xbr, ybr] = ann.points;
                        const color = ann.label?.color || '#00ff00';
                        return (
                            <rect
                                key={ann.clientID}
                                x={xtl}
                                y={ytl}
                                width={xbr - xtl}
                                height={ybr - ytl}
                                fill='none'
                                stroke={color}
                                strokeWidth={1.5}
                            />
                        );
                    })}
                </svg>
            )}
        </div>
    );
}
