// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Button from 'antd/lib/button';
import Progress from 'antd/lib/progress';
import { LoadingOutlined } from '@ant-design/icons';

import { CombinedState } from 'reducers';
import { changeFrameAsync } from 'actions/annotation-actions';
import { MultiviewAudioEngine } from './audio-engine';

interface Props {
    audioEngine: MultiviewAudioEngine | null;
    onEngineReady?: (engine: MultiviewAudioEngine) => void;
}

export default function SpectrogramPanel(props: Props): JSX.Element {
    const { audioEngine: externalEngine, onEngineReady } = props;

    const canvasRef = useRef<HTMLCanvasElement>(null);
    const spectrogramImageRef = useRef<ImageData | null>(null);

    const [audioEngine, setAudioEngine] = useState<MultiviewAudioEngine | null>(externalEngine);
    const [spectrogramData, setSpectrogramData] = useState<number[][] | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [loadingProgress, setLoadingProgress] = useState(0);
    const [loadingStatus, setLoadingStatus] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [audioDuration, setAudioDuration] = useState(0);

    const dispatch = useDispatch();
    const frameNumber = useSelector((state: CombinedState) => state.annotation.player.frame.number);
    const job = useSelector((state: CombinedState) => state.annotation.job.instance);

    const fps = 30; // TODO: Get actual FPS from job metadata
    const currentTime = frameNumber / fps;
    const duration = audioDuration || (job ? (job.stopFrame - job.startFrame) / fps : 100);

    // Initialize audio engine when component mounts
    useEffect(() => {
        if (!audioEngine) {
            const engine = new MultiviewAudioEngine();
            setAudioEngine(engine);
            if (onEngineReady) {
                onEngineReady(engine);
            }
        }
    }, [audioEngine, onEngineReady]);

    /**
     * Draw the complete spectrogram on canvas
     */
    const drawSpectrogram = useCallback((data: number[][]): void => {
        const canvas = canvasRef.current;
        if (!canvas || data.length === 0) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const { width, height } = canvas;
        const frequencyBinCount = data[0].length;

        // Create ImageData for efficient rendering
        const imageData = ctx.createImageData(width, height);
        const pixels = imageData.data;

        // Calculate scaling factors
        const timeScale = data.length / width;
        const freqScale = frequencyBinCount / height;

        for (let x = 0; x < width; x++) {
            const timeIndex = Math.floor(x * timeScale);
            const column = data[Math.min(timeIndex, data.length - 1)];

            for (let y = 0; y < height; y++) {
                // Invert Y axis (low frequencies at bottom)
                const freqIndex = Math.floor((height - 1 - y) * freqScale);
                const value = column[Math.min(freqIndex, column.length - 1)] || 0;

                // Color mapping: blue (low) -> cyan -> green -> yellow -> red (high)
                const intensity = value / 255;
                let r: number;
                let g: number;
                let b: number;

                if (intensity < 0.1) {
                    // Very low: dark blue/black
                    r = 0;
                    g = 0;
                    b = Math.floor(intensity * 10 * 100);
                } else if (intensity < 0.3) {
                    // Low: blue to cyan
                    const t = (intensity - 0.1) / 0.2;
                    r = 0;
                    g = Math.floor(t * 200);
                    b = 150 + Math.floor(t * 55);
                } else if (intensity < 0.5) {
                    // Medium-low: cyan to green
                    const t = (intensity - 0.3) / 0.2;
                    r = 0;
                    g = 200 + Math.floor(t * 55);
                    b = 205 - Math.floor(t * 205);
                } else if (intensity < 0.7) {
                    // Medium-high: green to yellow
                    const t = (intensity - 0.5) / 0.2;
                    r = Math.floor(t * 255);
                    g = 255;
                    b = 0;
                } else {
                    // High: yellow to red
                    const t = (intensity - 0.7) / 0.3;
                    r = 255;
                    g = 255 - Math.floor(t * 255);
                    b = 0;
                }

                const pixelIndex = (y * width + x) * 4;
                pixels[pixelIndex] = r;
                pixels[pixelIndex + 1] = g;
                pixels[pixelIndex + 2] = b;
                pixels[pixelIndex + 3] = 255; // Alpha
            }
        }

        // Store the image data for reuse when drawing playhead
        spectrogramImageRef.current = imageData;

        // Draw the spectrogram
        ctx.putImageData(imageData, 0, 0);

        // Draw time axis labels
        drawTimeLabels(ctx, width, height);

        // Draw frequency labels
        drawFrequencyLabels(ctx, width, height);
    }, []);

    /**
     * Draw time axis labels
     */
    const drawTimeLabels = (ctx: CanvasRenderingContext2D, width: number, height: number): void => {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.font = '11px monospace';
        ctx.textAlign = 'center';

        const numLabels = 10;
        for (let i = 0; i <= numLabels; i++) {
            const x = (i / numLabels) * width;
            const time = (i / numLabels) * duration;
            const label = time < 60
                ? `${time.toFixed(1)}s`
                : `${Math.floor(time / 60)}:${(time % 60).toFixed(0).padStart(2, '0')}`;
            ctx.fillText(label, x, height - 5);
        }
    };

    /**
     * Draw frequency axis labels
     */
    const drawFrequencyLabels = (ctx: CanvasRenderingContext2D, width: number, height: number): void => {
        ctx.fillStyle = 'rgba(200, 200, 200, 0.9)';
        ctx.font = '10px monospace';
        ctx.textAlign = 'right';

        const sampleRate = audioEngine?.getSampleRate() || 44100;
        const maxFreq = sampleRate / 2;

        // Draw 5 frequency markers
        for (let i = 0; i <= 4; i++) {
            const freq = (maxFreq * i) / 4;
            const y = height - (i * (height - 20)) / 4 - 15;
            ctx.fillText(`${(freq / 1000).toFixed(1)}kHz`, width - 5, y);
        }
    };

    /**
     * Draw playhead marker on the spectrogram
     */
    const drawPlayhead = useCallback((): void => {
        const canvas = canvasRef.current;
        if (!canvas || !spectrogramImageRef.current) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const { width, height } = canvas;

        // Restore the spectrogram image
        ctx.putImageData(spectrogramImageRef.current, 0, 0);

        // Redraw labels (they get overwritten by putImageData)
        drawTimeLabels(ctx, width, height);
        drawFrequencyLabels(ctx, width, height);

        // Draw playhead marker (vertical red line)
        if (duration > 0) {
            const markerX = (currentTime / duration) * width;

            ctx.strokeStyle = '#ff4d4d';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(markerX, 0);
            ctx.lineTo(markerX, height - 20);
            ctx.stroke();

            // Draw time label at playhead
            ctx.fillStyle = 'rgba(255, 77, 77, 0.95)';
            ctx.font = 'bold 12px monospace';
            ctx.textAlign = 'center';
            const timeLabel = currentTime < 60
                ? `${currentTime.toFixed(2)}s`
                : `${Math.floor(currentTime / 60)}:${(currentTime % 60).toFixed(1).padStart(4, '0')}`;
            const labelX = Math.max(30, Math.min(markerX, width - 30));
            ctx.fillText(timeLabel, labelX, 15);
        }
    }, [currentTime, duration, audioEngine]);

    // Draw spectrogram when data changes
    useEffect(() => {
        if (spectrogramData) {
            drawSpectrogram(spectrogramData);
        }
    }, [spectrogramData, drawSpectrogram]);

    // Update playhead position when frame changes
    useEffect(() => {
        if (spectrogramData && spectrogramImageRef.current) {
            drawPlayhead();
        }
    }, [frameNumber, spectrogramData, drawPlayhead]);

    /**
     * Handle canvas click for seeking
     */
    const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>): void => {
        const canvas = canvasRef.current;
        if (!canvas || !job || !spectrogramData) return;

        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const seekTime = (x / canvas.width) * duration;
        const targetFrame = Math.floor(seekTime * fps) + job.startFrame;

        dispatch(changeFrameAsync(Math.min(targetFrame, job.stopFrame)));
    };

    /**
     * Generate spectrogram from all video sources
     */
    const handleGenerateSpectrogram = async (): Promise<void> => {
        if (!audioEngine) return;

        setIsLoading(true);
        setError(null);
        setLoadingProgress(0);
        setLoadingStatus('Collecting video sources...');

        try {
            // Get all video elements from the page
            const videoElements = Array.from(
                document.querySelectorAll('.multiview-video'),
            ) as HTMLVideoElement[];

            if (videoElements.length === 0) {
                throw new Error('No video elements found');
            }

            const urls = videoElements.map((v) => v.src).filter((src) => src);

            if (urls.length === 0) {
                throw new Error('No video URLs available');
            }

            setLoadingStatus(`Decoding audio from ${urls.length} videos...`);
            setLoadingProgress(10);

            // Fetch and decode audio from all videos in parallel
            const bufferPromises = urls.map(async (url, index) => {
                try {
                    const buffer = await audioEngine.fetchAndDecodeAudio(url);
                    setLoadingProgress(10 + ((index + 1) / urls.length) * 40);
                    return buffer;
                } catch (err) {
                    console.warn(`Failed to decode audio from video ${index + 1}:`, err);
                    return null;
                }
            });

            const buffers = (await Promise.all(bufferPromises)).filter(
                (b): b is AudioBuffer => b !== null,
            );

            if (buffers.length === 0) {
                throw new Error('Failed to decode audio from any video');
            }

            setLoadingStatus('Mixing audio tracks...');
            setLoadingProgress(55);

            // Mix all audio buffers
            const mixedBuffer = audioEngine.mixAudioBuffers(buffers);
            setAudioDuration(mixedBuffer.duration);

            setLoadingStatus('Generating spectrogram...');
            setLoadingProgress(65);

            // Generate spectrogram data
            const fftSize = 2048;
            const data = audioEngine.generateSpectrogramData(mixedBuffer, fftSize);

            setLoadingProgress(95);
            setLoadingStatus('Rendering...');

            // Small delay to show final progress
            await new Promise((resolve) => { setTimeout(resolve, 100); });

            setSpectrogramData(data);
            setLoadingProgress(100);
        } catch (err) {
            console.error('Failed to generate spectrogram:', err);
            setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className='spectrogram-panel'>
            <div className='spectrogram-header'>
                <div className='spectrogram-title'>
                    <h3>Audio Spectrogram</h3>
                    {spectrogramData && (
                        <span className='spectrogram-status'>
                            {`${duration.toFixed(1)}s total`}
                        </span>
                    )}
                </div>
                <div className='spectrogram-controls'>
                    {!spectrogramData && !isLoading && (
                        <Button
                            type='primary'
                            onClick={handleGenerateSpectrogram}
                            size='small'
                        >
                            Generate Spectrogram
                        </Button>
                    )}
                    {spectrogramData && (
                        <Button
                            type='default'
                            onClick={handleGenerateSpectrogram}
                            size='small'
                            loading={isLoading}
                        >
                            Regenerate
                        </Button>
                    )}
                </div>
            </div>

            <div className='spectrogram-content'>
                <canvas
                    ref={canvasRef}
                    className='spectrogram-canvas'
                    width={1920}
                    height={180}
                    onClick={handleCanvasClick}
                    style={{
                        cursor: spectrogramData ? 'pointer' : 'default',
                        display: isLoading ? 'none' : 'block',
                    }}
                    title='Click to seek'
                />

                {isLoading && (
                    <div className='spectrogram-loading'>
                        <LoadingOutlined style={{ fontSize: 24, marginBottom: 12 }} />
                        <div className='loading-status'>{loadingStatus}</div>
                        <Progress
                            percent={loadingProgress}
                            status='active'
                            strokeColor={{
                                '0%': '#108ee9',
                                '100%': '#87d068',
                            }}
                            style={{ width: 300 }}
                        />
                    </div>
                )}

                {!spectrogramData && !isLoading && (
                    <div className='spectrogram-placeholder'>
                        <p>Click &quot;Generate Spectrogram&quot; to analyze audio from all video streams</p>
                        <p>The spectrogram will show the full timeline with mixed audio from all cameras</p>
                    </div>
                )}

                {error && (
                    <div className='spectrogram-error'>
                        <p>Error: {error}</p>
                        <p>Make sure video files are loaded and accessible</p>
                    </div>
                )}
            </div>
        </div>
    );
}
