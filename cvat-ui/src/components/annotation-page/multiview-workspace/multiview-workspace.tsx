// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Layout from 'antd/lib/layout';
import Select from 'antd/lib/select';

import { CombinedState, ActiveControl } from 'reducers';
import {
    changeFrameAsync,
    switchPlay,
    setCanvasInstance,
    updateActiveControl as updateActiveControlAction,
    updateCanvasContextMenu,
} from 'actions/annotation-actions';
import { Canvas } from 'cvat-canvas-wrapper';
import ControlsSideBarContainer from 'containers/annotation-page/standard-workspace/controls-side-bar/controls-side-bar';
import ObjectSideBarComponent from 'components/annotation-page/standard-workspace/objects-side-bar/objects-side-bar';
import CanvasContextMenuContainer from 'containers/annotation-page/canvas/canvas-context-menu';
import CanvasPointContextMenuComponent from 'components/annotation-page/canvas/views/canvas2d/canvas-point-context-menu';
import RemoveConfirmComponent from 'components/annotation-page/standard-workspace/remove-confirm';
import PropagateConfirmComponent from 'components/annotation-page/standard-workspace/propagate-confirm';

import MultiviewVideoGrid from './multiview-video-grid';
import SpectrogramPanel from './spectrogram-panel';
import MultiviewObjectsList from './multiview-objects-list';
import MultiviewCanvasWrapper from './multiview-canvas-wrapper';
import { clearMultiviewFrameCache } from './multiview-frame-provider';
import './styles.scss';

const PLAYBACK_RATE_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

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

export default function MultiviewWorkspace(): JSX.Element {
    const [activeView, setActiveView] = useState<number>(1);
    const [audioEngine, setAudioEngine] = useState<any>(null);
    const [canvasContainer, setCanvasContainer] = useState<HTMLDivElement | null>(null);
    const [playbackRate, setPlaybackRate] = useState<number>(1.0);
    const lastFrameRef = useRef<number>(-1);
    const clockStartTimeRef = useRef<number | null>(null);
    const clockStartFrameRef = useRef<number | null>(null);
    const canvasInstancesRef = useRef<Map<number, Canvas>>(new Map());
    // Use a ref to track playing state synchronously to avoid race conditions
    // This ref is updated BEFORE starting/stopping playback to prevent seek effect from triggering
    const playingRef = useRef<boolean>(false);
    // Hidden audio-only video: plays the active view's audio track
    const audioVideoRef = useRef<HTMLVideoElement>(null);
    const audioPrevPlayingRef = useRef<boolean>(false);
    const audioLoadedUrlRef = useRef<string>('');

    const dispatch = useDispatch();
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const job = useSelector((state: CombinedState) => state.annotation.job.instance);
    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);
    const activeControl = useSelector((state: CombinedState) => state.annotation.canvas.activeControl);
    const canvasInstance = useSelector((state: CombinedState) => state.annotation.canvas.instance) as Canvas | null;

    // Get FPS from multiview data, fallback to 30
    const fps = multiviewData?.videos?.view1?.fps || 30;

    // Audio URL for the currently active view
    const audioViewKey = `view${activeView}` as keyof typeof multiviewData.videos;
    const audioUrl = multiviewData?.videos?.[audioViewKey]?.url || '';

    // Use ref for frameNumber to avoid recreating callbacks on every frame change
    const frameNumberRef = useRef(frameNumber);
    useEffect(() => {
        frameNumberRef.current = frameNumber;
    }, [frameNumber]);

    // Handle play/pause state changes - synchronized playback
    // Only depends on `playing` to avoid unnecessary re-runs
    useEffect(() => {
        if (playing) {
            // Set ref BEFORE starting playback to prevent seek effect from triggering
            playingRef.current = true;
            clockStartTimeRef.current = performance.now();
            clockStartFrameRef.current = frameNumberRef.current;
        } else {
            // Set ref BEFORE pausing to allow seek effect to work
            playingRef.current = false;
            clockStartTimeRef.current = null;
            clockStartFrameRef.current = null;
        }

        return () => {
            // no-op
        };
    }, [playing]);

    // Auto-pause video when in draw mode — prevents playback during any draw operation.
    // Covers: entering draw mode while playing, pressing Space while in draw mode,
    // and any external API call that triggers play while draw mode is active.
    useEffect(() => {
        const isInDrawMode = DRAW_ACTIVE_CONTROLS.includes(activeControl);

        if (playing && isInDrawMode && playingRef.current) {
            // Update playingRef FIRST to prevent seek effect from triggering
            playingRef.current = false;
            // Also update Redux state to stay in sync
            dispatch(switchPlay(false));
        }
    }, [activeControl, playing, dispatch]);

    // Sync video time to Redux frameNumber when playing
    // Use requestAnimationFrame with throttling to prevent out-of-order async completions
    // B: frame dropping — if previous dispatch is still pending, skip and log
    useEffect(() => {
        if (!playing) {
            lastFrameRef.current = -1;
            return undefined;
        }

        let animationId: number;
        let lastDispatchedFrame = lastFrameRef.current;
        let lastDispatchTime = 0;
        let pendingDispatch = false;

        // Throttle interval: dispatch at most every 100ms (10fps for Redux updates)
        const THROTTLE_MS = 100;

        const updateFrameFromClock = (): void => {
            const now = performance.now();
            if (clockStartTimeRef.current === null || clockStartFrameRef.current === null) {
                clockStartTimeRef.current = now;
                clockStartFrameRef.current = frameNumberRef.current;
            }
            const elapsed = (now - clockStartTimeRef.current) / 1000;
            const newFrame = Math.round(clockStartFrameRef.current + elapsed * fps * playbackRate);

            const shouldDispatch = newFrame !== lastDispatchedFrame &&
                (now - lastDispatchTime) >= THROTTLE_MS &&
                job && !pendingDispatch;

            if (shouldDispatch) {
                lastDispatchedFrame = newFrame;
                lastFrameRef.current = newFrame;
                lastDispatchTime = now;
                pendingDispatch = true;

                const targetFrame = Math.min(Math.max(newFrame, job.startFrame || 0), job.stopFrame);
                Promise.resolve(dispatch(changeFrameAsync(targetFrame))).finally(() => {
                    pendingDispatch = false;
                });
            }

            animationId = requestAnimationFrame(updateFrameFromClock);
        };

        animationId = requestAnimationFrame(updateFrameFromClock);

        return () => {
            cancelAnimationFrame(animationId);
        };
    }, [playing, fps, job, dispatch, playbackRate]);

    // Audio: load new source when active view changes
    useEffect(() => {
        const video = audioVideoRef.current;
        if (!video || !audioUrl || audioUrl === audioLoadedUrlRef.current) return undefined;
        audioLoadedUrlRef.current = audioUrl;

        video.pause();
        video.src = audioUrl;

        const syncAfterLoad = (): void => {
            video.currentTime = frameNumberRef.current / fps;
            if (playingRef.current) {
                video.playbackRate = playbackRate;
                video.play().catch(() => { /* autoplay policy */ });
            }
            audioPrevPlayingRef.current = playingRef.current;
        };

        video.addEventListener('canplay', syncAfterLoad, { once: true });
        return () => video.removeEventListener('canplay', syncAfterLoad);
    }, [audioUrl, fps, playbackRate]);

    // Audio: sync play/pause/seek with canvas clock
    useEffect(() => {
        const video = audioVideoRef.current;
        if (!video || !audioUrl || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;

        const wasPlaying = audioPrevPlayingRef.current;
        audioPrevPlayingRef.current = playing;

        if (playing && !wasPlaying) {
            video.currentTime = frameNumberRef.current / fps;
            video.playbackRate = playbackRate;
            video.play().catch(() => { /* autoplay policy */ });
        } else if (!playing && wasPlaying) {
            video.pause();
            video.currentTime = frameNumberRef.current / fps;
        } else if (!playing) {
            video.currentTime = frameNumberRef.current / fps;
        }
    }, [playing, frameNumber, fps, audioUrl, playbackRate]);

    // Audio: update playback rate
    useEffect(() => {
        const video = audioVideoRef.current;
        if (video) video.playbackRate = playbackRate;
    }, [playbackRate]);

    // Audio: drift correction — resync if audio drifts >300ms from canvas
    useEffect(() => {
        if (!playing) return undefined;
        const interval = setInterval(() => {
            const video = audioVideoRef.current;
            if (!video || video.paused) return;
            const expectedTime = frameNumberRef.current / fps;
            if (Math.abs(video.currentTime - expectedTime) > 0.3) {
                video.currentTime = expectedTime;
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [playing, fps]);

    // Spectrogram engine (offline audio decode, separate from playback audio)
    const handleEngineReady = async (engine: any): Promise<void> => {
        setAudioEngine(engine);
    };

    // Handle zoom from mouse wheel on canvas overlay
    // Uses pointer-centered zoom: the point under the mouse stays fixed during zoom
    // Handle pan (drag to move when zoomed)
    const handlePan = useCallback((dx: number, dy: number): void => {
        if (canvasInstance) {
            canvasInstance.move(dy, dx);
        }
    }, [canvasInstance]);

    // Reset zoom to default
    const handleZoomReset = useCallback((): void => {
        if (canvasInstance) {
            canvasInstance.fit();
        }
    }, [canvasInstance]);

    // Handle canvas container ready callback from active view
    const handleCanvasContainerReady = useCallback((
        container: HTMLDivElement | null,
    ): void => {
        setCanvasContainer(container);
    }, []);

    useEffect(() => {
        let instance = canvasInstancesRef.current.get(activeView);
        if (!instance) {
            instance = new Canvas();
            canvasInstancesRef.current.set(activeView, instance);
        }

        dispatch(setCanvasInstance(instance));
        dispatch(updateActiveControlAction(ActiveControl.CURSOR));
        dispatch(updateCanvasContextMenu(false, 0, 0));
    }, [activeView, dispatch]);

    useEffect(() => {
        return () => {
            canvasInstancesRef.current.forEach((instance) => instance.destroy());
            canvasInstancesRef.current.clear();
            clearMultiviewFrameCache();
        };
    }, []);

    useEffect(() => {
        if (!canvasInstance) return;
        try {
            canvasInstance.cancel();
        } catch {
            // Ignore if canvas is not in a cancelable state
        }
    }, [canvasInstance, activeView]);

    return (
        <Layout hasSider className='cvat-multiview-workspace'>
            <ControlsSideBarContainer />
            <Layout.Content className='cvat-multiview-workspace-content'>
                {/* Hidden audio-only video: plays active view's audio track */}
                <video
                    ref={audioVideoRef}
                    playsInline
                    preload='auto'
                    style={{ position: 'absolute', width: 0, height: 0, opacity: 0, pointerEvents: 'none' }}
                />
                <div className='multiview-controls'>
                    <span className='playback-rate-label'>Playback Speed:</span>
                    <Select
                        value={playbackRate}
                        onChange={setPlaybackRate}
                        className='playback-rate-select'
                        size='small'
                    >
                        {PLAYBACK_RATE_OPTIONS.map((rate) => (
                            <Select.Option key={rate} value={rate}>
                                {rate}x
                            </Select.Option>
                        ))}
                    </Select>
                </div>
                <MultiviewVideoGrid
                    activeView={activeView}
                    playbackRate={playbackRate}
                    onViewSelect={setActiveView}
                    onCanvasContainerReady={handleCanvasContainerReady}
                    onPan={handlePan}
                    onZoomReset={handleZoomReset}
                />
                <SpectrogramPanel
                    audioEngine={audioEngine}
                    onEngineReady={handleEngineReady}
                />
            </Layout.Content>
            <ObjectSideBarComponent objectsList={<MultiviewObjectsList activeView={activeView} />} />
            <CanvasContextMenuContainer />
            <CanvasPointContextMenuComponent />
            <RemoveConfirmComponent />
            <PropagateConfirmComponent />
                <MultiviewCanvasWrapper
                    canvasContainer={canvasContainer}
                    activeViewId={activeView}
                />
        </Layout>
    );
}
