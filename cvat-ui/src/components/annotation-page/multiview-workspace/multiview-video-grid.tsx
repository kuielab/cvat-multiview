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
    playbackRate?: number;
    onCanvasContainerReady?: (container: HTMLDivElement | null, videoElement: HTMLVideoElement | null) => void;
    onVideoRef?: (viewId: number, video: HTMLVideoElement | null) => void;
}

interface ViewConfig {
    viewId: number;
    url: string;
    fps: number;
}

export default function MultiviewVideoGrid(props: Props): JSX.Element {
    const { activeView, onViewSelect, playbackRate, onCanvasContainerReady, onVideoRef } = props;

    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const playing = useSelector((state: CombinedState) => state.annotation.player.playing);
    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);

    // Collect available views dynamically
    const availableViews: ViewConfig[] = [];
    if (multiviewData?.videos) {
        const viewKeys = ['view1', 'view2', 'view3', 'view4', 'view5'] as const;
        viewKeys.forEach((key, index) => {
            const viewData = multiviewData.videos[key];
            if (viewData?.url) {
                availableViews.push({
                    viewId: index + 1,
                    url: viewData.url,
                    fps: viewData.fps || 30,
                });
            }
        });
    }

    // Check if we have at least one view
    if (availableViews.length === 0) {
        return (
            <div className='multiview-grid-loading'>
                <p>Loading multiview data...</p>
                <p>Please ensure this is a multiview task with video streams.</p>
            </div>
        );
    }

    // Single view mode - show full width
    const isSingleView = availableViews.length === 1;

    // Render a cell for a given view
    const renderCell = (view: ViewConfig): JSX.Element => (
        <div
            key={view.viewId}
            className={`multiview-cell ${activeView === view.viewId ? 'active' : ''}`}
            onClick={() => onViewSelect(view.viewId)}
            role='button'
            tabIndex={0}
            onKeyPress={(e) => e.key === 'Enter' && onViewSelect(view.viewId)}
        >
            <VideoCanvas
                viewId={view.viewId}
                frameNumber={frameNumber}
                videoUrl={view.url}
                fps={view.fps}
                isActive={activeView === view.viewId}
                playing={playing}
                playbackRate={playbackRate}
                onCanvasContainerReady={activeView === view.viewId ? onCanvasContainerReady : undefined}
                onVideoRef={onVideoRef}
            />
        </div>
    );

    // Group views into rows of 2
    const rows: ViewConfig[][] = [];
    for (let i = 0; i < availableViews.length; i += 2) {
        rows.push(availableViews.slice(i, i + 2));
    }

    return (
        <div className='multiview-grid'>
            {rows.map((row, rowIndex) => {
                // Determine row class based on number of cells and total views
                let rowClass = 'multiview-grid-row';
                if (isSingleView) {
                    rowClass += ' single-view-mode';
                } else if (row.length === 1) {
                    // Odd cell at the end - use half width
                    rowClass += ' half-width';
                }

                return (
                    <div key={rowIndex} className={rowClass}>
                        {row.map(renderCell)}
                    </div>
                );
            })}
        </div>
    );
}
