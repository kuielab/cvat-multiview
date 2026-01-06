// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { useSelector } from 'react-redux';
import { CombinedState } from 'reducers';

import VideoCanvas from './video-canvas';

interface Props {
    activeView: number;
    onViewSelect: (view: number) => void;
}

export default function MultiviewVideoGrid(props: Props): JSX.Element {
    const { activeView, onViewSelect } = props;

    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);

    // Check if multiviewData is loaded with all required views
    if (!multiviewData?.videos?.view1?.url ||
        !multiviewData?.videos?.view2?.url ||
        !multiviewData?.videos?.view3?.url ||
        !multiviewData?.videos?.view4?.url ||
        !multiviewData?.videos?.view5?.url) {
        return (
            <div className='multiview-grid-loading'>
                <p>Loading multiview data...</p>
                <p>Please ensure this is a multiview task with 5 video streams.</p>
            </div>
        );
    }

    return (
        <div className='multiview-grid'>
            <div className='multiview-grid-row'>
                <div
                    className={`multiview-cell ${activeView === 1 ? 'active' : ''}`}
                    onClick={() => onViewSelect(1)}
                    role='button'
                    tabIndex={0}
                    onKeyPress={(e) => e.key === 'Enter' && onViewSelect(1)}
                >
                    <VideoCanvas
                        viewId={1}
                        frameNumber={frameNumber}
                        videoUrl={multiviewData.videos.view1.url}
                        fps={multiviewData.videos.view1.fps}
                        isActive={activeView === 1}
                        playing={playing}
                    />
                </div>
                <div
                    className={`multiview-cell ${activeView === 2 ? 'active' : ''}`}
                    onClick={() => onViewSelect(2)}
                    role='button'
                    tabIndex={0}
                    onKeyPress={(e) => e.key === 'Enter' && onViewSelect(2)}
                >
                    <VideoCanvas
                        viewId={2}
                        frameNumber={frameNumber}
                        videoUrl={multiviewData.videos.view2.url}
                        fps={multiviewData.videos.view2.fps}
                        isActive={activeView === 2}
                        playing={playing}
                    />
                </div>
            </div>
            <div className='multiview-grid-row'>
                <div
                    className={`multiview-cell ${activeView === 3 ? 'active' : ''}`}
                    onClick={() => onViewSelect(3)}
                    role='button'
                    tabIndex={0}
                    onKeyPress={(e) => e.key === 'Enter' && onViewSelect(3)}
                >
                    <VideoCanvas
                        viewId={3}
                        frameNumber={frameNumber}
                        videoUrl={multiviewData.videos.view3.url}
                        fps={multiviewData.videos.view3.fps}
                        isActive={activeView === 3}
                        playing={playing}
                    />
                </div>
                <div
                    className={`multiview-cell ${activeView === 4 ? 'active' : ''}`}
                    onClick={() => onViewSelect(4)}
                    role='button'
                    tabIndex={0}
                    onKeyPress={(e) => e.key === 'Enter' && onViewSelect(4)}
                >
                    <VideoCanvas
                        viewId={4}
                        frameNumber={frameNumber}
                        videoUrl={multiviewData.videos.view4.url}
                        fps={multiviewData.videos.view4.fps}
                        isActive={activeView === 4}
                        playing={playing}
                    />
                </div>
            </div>
            <div className='multiview-grid-row single'>
                <div
                    className={`multiview-cell ${activeView === 5 ? 'active' : ''}`}
                    onClick={() => onViewSelect(5)}
                    role='button'
                    tabIndex={0}
                    onKeyPress={(e) => e.key === 'Enter' && onViewSelect(5)}
                >
                    <VideoCanvas
                        viewId={5}
                        frameNumber={frameNumber}
                        videoUrl={multiviewData.videos.view5.url}
                        fps={multiviewData.videos.view5.fps}
                        isActive={activeView === 5}
                        playing={playing}
                    />
                </div>
            </div>
        </div>
    );
}
