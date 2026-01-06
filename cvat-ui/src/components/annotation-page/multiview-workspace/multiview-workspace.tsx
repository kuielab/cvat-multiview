// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useState, useEffect, useRef } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Layout from 'antd/lib/layout';

import { CombinedState } from 'reducers';
import { changeFrameAsync } from 'actions/annotation-actions';
import ControlsSideBarContainer from 'containers/annotation-page/standard-workspace/controls-side-bar/controls-side-bar';
import ObjectSideBarComponent from 'components/annotation-page/standard-workspace/objects-side-bar/objects-side-bar';
import CanvasContextMenuContainer from 'containers/annotation-page/canvas/canvas-context-menu';
import CanvasPointContextMenuComponent from 'components/annotation-page/canvas/views/canvas2d/canvas-point-context-menu';
import RemoveConfirmComponent from 'components/annotation-page/standard-workspace/remove-confirm';
import PropagateConfirmComponent from 'components/annotation-page/standard-workspace/propagate-confirm';

import MultiviewVideoGrid from './multiview-video-grid';
import SpectrogramPanel from './spectrogram-panel';
import MultiviewObjectsList from './multiview-objects-list';
import './styles.scss';

export default function MultiviewWorkspace(): JSX.Element {
    const [activeView, setActiveView] = useState<number>(1);
    const [audioEngine, setAudioEngine] = useState<any>(null);
    const lastFrameRef = useRef<number>(-1);

    const dispatch = useDispatch();
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const job = useSelector((state: CombinedState) => state.annotation.job.instance);

    const fps = 30; // TODO: Get actual FPS from job metadata

    // Sync video time to Redux frameNumber when playing
    useEffect(() => {
        if (!playing) {
            lastFrameRef.current = -1;
            return;
        }

        const videos = document.querySelectorAll('.multiview-video') as NodeListOf<HTMLVideoElement>;
        if (videos.length === 0) return;

        const handleTimeUpdate = (): void => {
            // Get max current time among all videos (some may have ended)
            const times = Array.from(videos).map((v) => v.currentTime);
            const maxTime = Math.max(...times);

            // Calculate frame number from time
            const newFrame = Math.floor(maxTime * fps);

            // Only dispatch if frame changed
            if (newFrame !== lastFrameRef.current && job) {
                lastFrameRef.current = newFrame;
                const targetFrame = Math.min(newFrame + job.startFrame, job.stopFrame);
                dispatch(changeFrameAsync(targetFrame));
            }
        };

        // Use first video's timeupdate event as the sync source
        const primaryVideo = videos[0];
        primaryVideo.addEventListener('timeupdate', handleTimeUpdate);

        return () => {
            primaryVideo.removeEventListener('timeupdate', handleTimeUpdate);
        };
    }, [playing, fps, job, dispatch]);

    // Handle audio engine initialization
    const handleEngineReady = async (engine: any): Promise<void> => {
        setAudioEngine(engine);

        // Wait for video elements to be available and loaded
        const initAudioEngine = async (): Promise<void> => {
            const videoElements = document.querySelectorAll('.multiview-video');
            if (videoElements.length === 5) {
                const videos = Array.from(videoElements) as HTMLVideoElement[];

                // Wait for all videos to have metadata loaded
                await Promise.all(
                    videos.map((video) => new Promise<void>((resolve) => {
                        if (video.readyState >= 1) {
                            resolve();
                        } else {
                            video.addEventListener('loadedmetadata', () => resolve(), { once: true });
                        }
                    })),
                );

                try {
                    await engine.initialize(videos);
                } catch (error) {
                    console.error('Failed to initialize audio engine:', error);
                }
            }
        };

        // Start initialization after a short delay to ensure DOM is ready
        setTimeout(() => {
            initAudioEngine().catch((error: Error) => {
                console.error('Audio engine initialization error:', error);
            });
        }, 100);
    };

    return (
        <Layout hasSider className='cvat-multiview-workspace'>
            <ControlsSideBarContainer />
            <Layout.Content className='cvat-multiview-workspace-content'>
                <MultiviewVideoGrid
                    activeView={activeView}
                    onViewSelect={setActiveView}
                />
                <SpectrogramPanel
                    audioEngine={audioEngine}
                    onEngineReady={handleEngineReady}
                />
            </Layout.Content>
            <ObjectSideBarComponent objectsList={<MultiviewObjectsList />} />
            <CanvasContextMenuContainer />
            <CanvasPointContextMenuComponent />
            <RemoveConfirmComponent />
            <PropagateConfirmComponent />
        </Layout>
    );
}
