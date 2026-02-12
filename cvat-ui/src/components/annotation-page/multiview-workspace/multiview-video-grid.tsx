// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { useSelector } from 'react-redux';
import { CombinedState } from 'reducers';

import VideoCanvas from './video-canvas';

interface Props {
    activeView: number;
    playbackRate: number;
    onViewSelect: (view: number) => void;
    onCanvasContainerReady?: (container: HTMLDivElement | null) => void;
    onPan?: (dx: number, dy: number) => void;
    onZoomReset?: () => void;
}

interface ViewConfig {
    viewId: number;
}

export default function MultiviewVideoGrid(props: Props): JSX.Element {
    const { activeView, playbackRate, onViewSelect, onCanvasContainerReady, onPan, onZoomReset } = props;

    const multiviewData = useSelector((state: CombinedState) => state.annotation.multiviewData);

    // Collect available views dynamically (supports 1-10 views)
    const availableViews: ViewConfig[] = [];
    if (multiviewData?.videos) {
        // Generate view keys dynamically for views 1-10
        for (let i = 1; i <= 10; i++) {
            const key = `view${i}` as keyof typeof multiviewData.videos;
            const viewData = multiviewData.videos[key];
            if (viewData?.url) {
                availableViews.push({
                    viewId: i,
                });
            }
        }
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

    // Get video aspect ratio from first available view (all views share the same dimensions)
    const firstView = availableViews[0];
    const firstViewKey = `view${firstView.viewId}` as keyof typeof multiviewData.videos;
    const firstViewData = multiviewData?.videos?.[firstViewKey];
    const videoWidth = firstViewData?.width || 320;
    const videoHeight = firstViewData?.height || 240;

    // Render a cell for a given view
    const renderCell = (view: ViewConfig): JSX.Element => (
        <div
            key={view.viewId}
            className={`multiview-cell ${activeView === view.viewId ? 'active' : ''}`}
            style={{ aspectRatio: `${videoWidth} / ${videoHeight}` }}
            onClick={() => onViewSelect(view.viewId)}
            role='button'
            tabIndex={0}
            onKeyPress={(e) => e.key === 'Enter' && onViewSelect(view.viewId)}
        >
            <VideoCanvas
                viewId={view.viewId}
                isActive={activeView === view.viewId}
                playbackRate={playbackRate}
                onCanvasContainerReady={activeView === view.viewId ? onCanvasContainerReady : undefined}
                onPan={activeView === view.viewId ? onPan : undefined}
                onZoomReset={activeView === view.viewId ? onZoomReset : undefined}
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
