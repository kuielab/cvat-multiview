// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Layout from 'antd/lib/layout';
import Select from 'antd/lib/select';

import { CombinedState, ActiveControl } from 'reducers';
import { changeFrameAsync, switchPlay } from 'actions/annotation-actions';
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
import './styles.scss';

const PLAYBACK_RATE_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
const SYNC_THRESHOLD = 0.1; // Max allowed time difference in seconds
const SYNC_INTERVAL = 500; // How often to check sync in ms

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
    const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
    const [playbackRate, setPlaybackRate] = useState<number>(1.0);
    const lastFrameRef = useRef<number>(-1);
    const videoRefsMap = useRef<Map<number, HTMLVideoElement>>(new Map());
    const syncIntervalRef = useRef<number | null>(null);
    // Use a ref to track playing state synchronously to avoid race conditions
    // This ref is updated BEFORE starting/stopping playback to prevent seek effect from triggering
    const playingRef = useRef<boolean>(false);

    const dispatch = useDispatch();
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const job = useSelector((state: CombinedState) => state.annotation.job.instance);
    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);
    const activeControl = useSelector((state: CombinedState) => state.annotation.canvas.activeControl);

    // Track previous activeControl to detect transitions into draw mode
    const prevActiveControlRef = useRef<ActiveControl>(activeControl);

    // Get FPS from multiview data, fallback to 30
    const fps = multiviewData?.videos?.view1?.fps || 30;

    // Use ref for frameNumber to avoid recreating callbacks on every frame change
    const frameNumberRef = useRef(frameNumber);
    useEffect(() => {
        frameNumberRef.current = frameNumber;
    }, [frameNumber]);

    // Handle video ref registration from child components
    const handleVideoRef = useCallback((viewId: number, video: HTMLVideoElement | null): void => {
        if (video) {
            videoRefsMap.current.set(viewId, video);
        } else {
            videoRefsMap.current.delete(viewId);
        }
    }, []);

    // Get all registered videos as array
    const getAllVideos = useCallback((): HTMLVideoElement[] => Array.from(videoRefsMap.current.values()), []);

    // Sync all videos to target time
    const syncAllVideosToTime = useCallback((targetTime: number): void => {
        const videos = getAllVideos();
        videos.forEach((video) => {
            // Only sync if video hasn't ended and time difference is significant
            if (!video.ended && Math.abs(video.currentTime - targetTime) > SYNC_THRESHOLD) {
                video.currentTime = targetTime;
            }
        });
    }, [getAllVideos]);

    // Play all videos synchronously
    const playAllVideos = useCallback(async (): Promise<void> => {
        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        if (domVideos.length === 0) {
            console.warn('No videos found');
            return;
        }

        const videos = Array.from(domVideos);

        // Sync all videos to same time before playing
        const currentFrame = frameNumberRef.current;
        const targetTime = (currentFrame - (job?.startFrame || 0)) / fps;

        // First pause all and mute all (browser autoplay policy requires muted for programmatic play)
        videos.forEach((video) => {
            video.pause();
            video.muted = true;
        });

        // Seek all to target time
        videos.forEach((video) => {
            video.currentTime = targetTime;
        });

        // Small delay for seeks to complete
        await new Promise((resolve) => { setTimeout(resolve, 50); });

        // Play all videos (all muted first to satisfy autoplay policy)
        await Promise.all(
            videos.map((video) => video.play().catch((e) => console.warn('Play failed:', e))),
        );

        // After successful play, unmute only the active view
        videos.forEach((video, index) => {
            // Find which video corresponds to active view by checking parent element class
            const cell = video.closest('.multiview-cell');
            const isActiveCell = cell?.classList.contains('active');
            video.muted = !isActiveCell;
        });
    }, [job, fps]);

    // Pause all videos
    const pauseAllVideos = useCallback((): void => {
        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        domVideos.forEach((video) => {
            video.pause();
        });
    }, []);

    // Periodic sync during playback to correct drift (disabled for now - let videos play naturally)
    const startSyncInterval = useCallback((): void => {
        // Sync interval disabled - videos should stay in sync if started together
    }, []);

    const stopSyncInterval = useCallback((): void => {
        if (syncIntervalRef.current) {
            clearInterval(syncIntervalRef.current);
            syncIntervalRef.current = null;
        }
    }, []);

    // Store callbacks in refs to avoid effect re-running when callbacks change
    const playAllVideosRef = useRef(playAllVideos);
    const pauseAllVideosRef = useRef(pauseAllVideos);
    const startSyncIntervalRef = useRef(startSyncInterval);
    const stopSyncIntervalRef = useRef(stopSyncInterval);

    useEffect(() => {
        playAllVideosRef.current = playAllVideos;
        pauseAllVideosRef.current = pauseAllVideos;
        startSyncIntervalRef.current = startSyncInterval;
        stopSyncIntervalRef.current = stopSyncInterval;
    }, [playAllVideos, pauseAllVideos, startSyncInterval, stopSyncInterval]);

    // Handle play/pause state changes - synchronized playback
    // Only depends on `playing` to avoid unnecessary re-runs
    useEffect(() => {
        if (playing) {
            // Set ref BEFORE starting playback to prevent seek effect from triggering
            playingRef.current = true;
            playAllVideosRef.current().then(() => {
                startSyncIntervalRef.current();
            });
        } else {
            // Set ref BEFORE pausing to allow seek effect to work
            playingRef.current = false;
            stopSyncIntervalRef.current();
            pauseAllVideosRef.current();
        }

        return () => {
            stopSyncIntervalRef.current();
        };
    }, [playing]);

    // Auto-pause video when ENTERING draw mode (not when already in draw mode)
    // This provides better UX - user can't draw while video is playing anyway
    useEffect(() => {
        const prevControl = prevActiveControlRef.current;
        const wasInDrawMode = DRAW_ACTIVE_CONTROLS.includes(prevControl);
        const isInDrawMode = DRAW_ACTIVE_CONTROLS.includes(activeControl);

        // Only pause when transitioning INTO draw mode, not when already in it
        if (playing && !wasInDrawMode && isInDrawMode) {
            // Update playingRef FIRST to prevent seek effect from triggering
            playingRef.current = false;
            // Immediately pause videos (synchronous) - don't wait for Redux state change
            pauseAllVideosRef.current();
            // Also update Redux state to stay in sync
            dispatch(switchPlay(false));
        }

        // Update ref for next comparison
        prevActiveControlRef.current = activeControl;
    }, [activeControl, playing, dispatch]);

    // Seek all videos when frame changes while NOT playing
    // Use playingRef (synchronous) instead of playing (from Redux) to avoid race conditions
    useEffect(() => {
        // Only seek when paused - during playback, videos control their own time
        // Use playingRef for synchronous check to prevent race conditions
        if (playingRef.current) return;

        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        if (domVideos.length === 0) return;

        const targetTime = (frameNumber - (job?.startFrame || 0)) / fps;

        // Use tighter tolerance (0.5 frame @ 30fps ≈ 16ms) to avoid unnecessary seeks
        const tolerance = 0.5 / fps;

        domVideos.forEach((video) => {
            if (Math.abs(video.currentTime - targetTime) > tolerance) {
                video.currentTime = targetTime;
            }
        });
    }, [frameNumber, job, fps]); // Removed 'playing' - we use playingRef instead

    // Apply playback rate to all videos
    useEffect(() => {
        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        domVideos.forEach((video) => {
            video.playbackRate = playbackRate;
        });
    }, [playbackRate]);

    // Update muted state when active view changes
    useEffect(() => {
        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        domVideos.forEach((video) => {
            const cell = video.closest('.multiview-cell');
            const isActiveCell = cell?.classList.contains('active');
            video.muted = !isActiveCell;
        });
    }, [activeView]);

    // Sync video time to Redux frameNumber when playing
    // Use requestAnimationFrame with throttling to prevent out-of-order async completions
    useEffect(() => {
        if (!playing) {
            lastFrameRef.current = -1;
            return undefined;
        }

        const domVideos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        if (domVideos.length === 0) return undefined;

        const primaryVideo = domVideos[0];
        let animationId: number;
        let lastDispatchedFrame = lastFrameRef.current;
        let lastDispatchTime = 0;
        let pendingDispatch = false;

        // Throttle interval: dispatch at most every 100ms (10fps for Redux updates)
        // This prevents multiple changeFrameAsync calls from completing out of order
        const THROTTLE_MS = 100;

        const updateFrame = (): void => {
            if (!primaryVideo || primaryVideo.paused) {
                animationId = requestAnimationFrame(updateFrame);
                return;
            }

            const now = performance.now();
            const masterTime = primaryVideo.currentTime;
            // Use Math.round instead of Math.floor to avoid oscillation at frame boundaries
            const newFrame = Math.round(masterTime * fps);

            // Only dispatch if:
            // 1. Frame actually changed
            // 2. Enough time has passed since last dispatch (throttle)
            // 3. No pending dispatch in progress
            const shouldDispatch = newFrame !== lastDispatchedFrame &&
                                   (now - lastDispatchTime) >= THROTTLE_MS &&
                                   !pendingDispatch &&
                                   job;

            if (shouldDispatch) {
                lastDispatchedFrame = newFrame;
                lastFrameRef.current = newFrame;
                lastDispatchTime = now;
                pendingDispatch = true;

                const targetFrame = Math.min(newFrame + (job.startFrame || 0), job.stopFrame);

                // Use Promise to track when dispatch completes
                Promise.resolve(dispatch(changeFrameAsync(targetFrame))).finally(() => {
                    pendingDispatch = false;
                });
            }

            animationId = requestAnimationFrame(updateFrame);
        };

        // Handle video ended - stop playback and update Redux state
        const handleEnded = (): void => {
            dispatch(switchPlay(false));
        };

        primaryVideo.addEventListener('ended', handleEnded);
        animationId = requestAnimationFrame(updateFrame);

        return () => {
            cancelAnimationFrame(animationId);
            primaryVideo.removeEventListener('ended', handleEnded);
        };
    }, [playing, fps, job, dispatch]);

    // Handle audio engine initialization
    // Note: We intentionally do NOT call engine.initialize(videos) here because
    // createMediaElementSource() hijacks the video's audio output and routes it
    // through the Web Audio API. This breaks normal video.muted control.
    // The spectrogram generation uses fetchAndDecodeAudio() instead, which
    // fetches and decodes the video file separately without affecting playback.
    const handleEngineReady = async (engine: any): Promise<void> => {
        setAudioEngine(engine);
    };

    // Handle canvas container ready callback from active view
    const handleCanvasContainerReady = useCallback((
        container: HTMLDivElement | null,
        video: HTMLVideoElement | null,
    ): void => {
        setCanvasContainer(container);
        setVideoElement(video);
    }, []);

    return (
        <Layout hasSider className='cvat-multiview-workspace'>
            <ControlsSideBarContainer />
            <Layout.Content className='cvat-multiview-workspace-content'>
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
                    onViewSelect={setActiveView}
                    playbackRate={playbackRate}
                    onCanvasContainerReady={handleCanvasContainerReady}
                    onVideoRef={handleVideoRef}
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
                videoElement={videoElement}
                activeViewId={activeView}
            />
        </Layout>
    );
}
