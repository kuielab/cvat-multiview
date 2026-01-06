// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useRef, useEffect } from 'react';

interface Props {
    viewId: number;
    frameNumber: number;
    videoUrl: string;
    fps: number;
    isActive: boolean;
}

export default function VideoCanvas(props: Props): JSX.Element {
    const {
        viewId, frameNumber, videoUrl, fps, isActive,
    } = props;

    const videoRef = useRef<HTMLVideoElement>(null);

    // Sync video to frame number
    useEffect(() => {
        if (videoRef.current && fps > 0) {
            const video = videoRef.current;
            const targetTime = frameNumber / fps;

            // Only seek if difference is significant (> 100ms)
            if (Math.abs(video.currentTime - targetTime) > 0.1) {
                video.currentTime = targetTime;
            }
        }
    }, [frameNumber, fps]);

    return (
        <div className='video-canvas-container'>
            <video
                ref={videoRef}
                src={videoUrl}
                className='multiview-video'
                playsInline
                crossOrigin="anonymous"
                muted
            />
            <div className='view-label'>
                View {viewId}
                {isActive && <span className='active-indicator'> (Active)</span>}
            </div>
        </div>
    );
}
