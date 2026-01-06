// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/**
 * MultiviewAudioEngine
 *
 * Manages audio mixing from multiple video sources and provides
 * real-time frequency analysis for spectrogram visualization.
 *
 * Uses Web Audio API to:
 * - Create MediaElementAudioSourceNode for each video
 * - Mix all sources into stereo output
 * - Provide FFT analysis via AnalyserNode
 */

export class MultiviewAudioEngine {
    private audioContext: AudioContext | null = null;
    private videoSources: MediaElementAudioSourceNode[] = [];
    private merger: ChannelMergerNode | null = null;
    private analyser: AnalyserNode | null = null;
    private gainNodes: GainNode[] = [];
    private initialized = false;

    constructor() {
        // AudioContext will be created on first user interaction
        // to comply with browser autoplay policies
    }

    /**
     * Initialize the audio engine with video elements
     * Must be called after user interaction
     */
    public async initialize(videoElements: HTMLVideoElement[]): Promise<void> {
        if (this.initialized) {
            return;
        }

        if (videoElements.length !== 5) {
            throw new Error('MultiviewAudioEngine requires exactly 5 video elements');
        }

        try {
            // Create AudioContext
            this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();

            // Create merger node (stereo output)
            this.merger = this.audioContext.createChannelMerger(2);

            // Create analyser for FFT
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 2048;
            this.analyser.smoothingTimeConstant = 0.8;
            this.analyser.minDecibels = -90;
            this.analyser.maxDecibels = -10;

            // Connect merger to analyser to destination
            this.merger.connect(this.analyser);
            this.analyser.connect(this.audioContext.destination);

            // Attach each video to the audio graph
            videoElements.forEach((video, index) => {
                this.attachVideo(video, index);
            });

            this.initialized = true;
        } catch (error) {
            console.error('Failed to initialize audio engine:', error);
            throw error;
        }
    }

    /**
     * Attach a video element to the audio mixing graph
     */
    private attachVideo(video: HTMLVideoElement, index: number): void {
        if (!this.audioContext || !this.merger) {
            throw new Error('Audio engine not initialized');
        }

        try {
            // Create source from video element
            const source = this.audioContext.createMediaElementSource(video);

            // Create gain node for volume control (20% each to prevent clipping)
            const gain = this.audioContext.createGain();
            gain.gain.value = 0.2;

            // Connect: source -> gain -> merger (both left and right channels)
            source.connect(gain);
            gain.connect(this.merger, 0, 0); // to left channel
            gain.connect(this.merger, 0, 1); // to right channel

            this.videoSources.push(source);
            this.gainNodes.push(gain);
        } catch (error) {
            // If video already has a source, this will throw
            // In that case, skip this video
            console.warn(`Could not attach video ${index}:`, error);
        }
    }

    /**
     * Get frequency data for spectrogram visualization
     * Returns Uint8Array with frequency bin values (0-255)
     */
    public getFrequencyData(): Uint8Array | null {
        if (!this.analyser) {
            return null;
        }

        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteFrequencyData(dataArray);
        return dataArray;
    }

    /**
     * Get time domain data (waveform)
     */
    public getTimeDomainData(): Uint8Array | null {
        if (!this.analyser) {
            return null;
        }

        const dataArray = new Uint8Array(this.analyser.fftSize);
        this.analyser.getByteTimeDomainData(dataArray);
        return dataArray;
    }

    /**
     * Set volume for a specific view (0-5)
     */
    public setViewVolume(viewIndex: number, volume: number): void {
        if (viewIndex >= 0 && viewIndex < this.gainNodes.length) {
            this.gainNodes[viewIndex].gain.value = Math.max(0, Math.min(1, volume));
        }
    }

    /**
     * Get the analyser node for direct access
     */
    public getAnalyser(): AnalyserNode | null {
        return this.analyser;
    }

    /**
     * Resume audio context (needed after browser suspends it)
     */
    public async resume(): Promise<void> {
        if (this.audioContext && this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }
    }

    /**
     * Suspend audio context
     */
    public async suspend(): Promise<void> {
        if (this.audioContext && this.audioContext.state === 'running') {
            await this.audioContext.suspend();
        }
    }

    /**
     * Get current audio context state
     */
    public getState(): AudioContextState | null {
        return this.audioContext?.state || null;
    }

    /**
     * Check if engine is initialized
     */
    public isInitialized(): boolean {
        return this.initialized;
    }

    /**
     * Get FFT size (number of frequency bins * 2)
     */
    public getFFTSize(): number {
        return this.analyser?.fftSize || 0;
    }

    /**
     * Get frequency bin count (half of FFT size)
     */
    public getFrequencyBinCount(): number {
        return this.analyser?.frequencyBinCount || 0;
    }

    /**
     * Cleanup and disconnect all audio nodes
     */
    public dispose(): void {
        this.videoSources.forEach((source) => {
            source.disconnect();
        });

        this.gainNodes.forEach((gain) => {
            gain.disconnect();
        });

        if (this.merger) {
            this.merger.disconnect();
        }

        if (this.analyser) {
            this.analyser.disconnect();
        }

        if (this.audioContext) {
            this.audioContext.close();
        }

        this.videoSources = [];
        this.gainNodes = [];
        this.merger = null;
        this.analyser = null;
        this.audioContext = null;
        this.initialized = false;
    }

    /**
     * Ensure AudioContext is created (for offline processing)
     */
    public ensureContext(): AudioContext {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
        }
        return this.audioContext;
    }

    /**
     * Fetch audio from video URL and decode to AudioBuffer
     */
    public async fetchAndDecodeAudio(videoUrl: string): Promise<AudioBuffer> {
        const context = this.ensureContext();
        const response = await fetch(videoUrl);
        const arrayBuffer = await response.arrayBuffer();
        return context.decodeAudioData(arrayBuffer);
    }

    /**
     * Mix multiple AudioBuffers into one (each at 20% volume to prevent clipping)
     */
    public mixAudioBuffers(buffers: AudioBuffer[]): AudioBuffer {
        if (buffers.length === 0) {
            throw new Error('No buffers to mix');
        }

        const context = this.ensureContext();
        const sampleRate = buffers[0].sampleRate;
        const maxLength = Math.max(...buffers.map((b) => b.length));
        const numberOfChannels = 2; // Stereo output

        const mixedBuffer = context.createBuffer(numberOfChannels, maxLength, sampleRate);

        for (let channel = 0; channel < numberOfChannels; channel++) {
            const outputData = mixedBuffer.getChannelData(channel);

            buffers.forEach((buffer) => {
                const sourceChannel = Math.min(channel, buffer.numberOfChannels - 1);
                const inputData = buffer.getChannelData(sourceChannel);
                const gain = 0.2; // 20% each to prevent clipping with 5 sources

                for (let i = 0; i < inputData.length; i++) {
                    outputData[i] += inputData[i] * gain;
                }
            });
        }

        return mixedBuffer;
    }

    /**
     * Generate spectrogram data from AudioBuffer using FFT
     * Returns 2D array: [timeSlice][frequencyBin]
     */
    public generateSpectrogramData(
        buffer: AudioBuffer,
        fftSize: number = 2048,
        hopSize?: number,
    ): number[][] {
        const channelData = buffer.getChannelData(0); // Use left channel
        const actualHopSize = hopSize || Math.floor(fftSize / 4); // 75% overlap
        const spectrogramData: number[][] = [];

        // Apply Hann window for smoother FFT
        const hannWindow = new Float32Array(fftSize);
        for (let i = 0; i < fftSize; i++) {
            hannWindow[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (fftSize - 1)));
        }

        // Process each time window
        for (let i = 0; i + fftSize <= channelData.length; i += actualHopSize) {
            const windowedSignal = new Float32Array(fftSize);
            for (let j = 0; j < fftSize; j++) {
                windowedSignal[j] = channelData[i + j] * hannWindow[j];
            }

            const magnitudes = this.performFFT(windowedSignal);
            spectrogramData.push(magnitudes);
        }

        return spectrogramData;
    }

    /**
     * Perform FFT using Cooley-Tukey radix-2 algorithm
     * Returns magnitude spectrum (0-255 scaled)
     */
    private performFFT(signal: Float32Array): number[] {
        const n = signal.length;
        const real = new Float32Array(signal);
        const imag = new Float32Array(n);

        // Bit-reversal permutation
        const bits = Math.log2(n);
        for (let i = 0; i < n; i++) {
            const j = this.reverseBits(i, bits);
            if (j > i) {
                [real[i], real[j]] = [real[j], real[i]];
                [imag[i], imag[j]] = [imag[j], imag[i]];
            }
        }

        // Cooley-Tukey FFT
        for (let size = 2; size <= n; size *= 2) {
            const halfSize = size / 2;
            const angleStep = (-2 * Math.PI) / size;

            for (let i = 0; i < n; i += size) {
                for (let j = 0; j < halfSize; j++) {
                    const angle = angleStep * j;
                    const cos = Math.cos(angle);
                    const sin = Math.sin(angle);

                    const evenIndex = i + j;
                    const oddIndex = i + j + halfSize;

                    const tReal = cos * real[oddIndex] - sin * imag[oddIndex];
                    const tImag = sin * real[oddIndex] + cos * imag[oddIndex];

                    real[oddIndex] = real[evenIndex] - tReal;
                    imag[oddIndex] = imag[evenIndex] - tImag;
                    real[evenIndex] += tReal;
                    imag[evenIndex] += tImag;
                }
            }
        }

        // Calculate magnitudes (only first half - Nyquist)
        const magnitudes: number[] = [];
        const halfN = n / 2;

        for (let i = 0; i < halfN; i++) {
            const magnitude = Math.sqrt(real[i] * real[i] + imag[i] * imag[i]);
            // Convert to decibels and scale to 0-255
            const db = 20 * Math.log10(magnitude + 1e-10);
            const minDb = -90;
            const maxDb = -10;
            const scaled = Math.round(((db - minDb) / (maxDb - minDb)) * 255);
            magnitudes.push(Math.max(0, Math.min(255, scaled)));
        }

        return magnitudes;
    }

    /**
     * Reverse bits for FFT bit-reversal permutation
     */
    private reverseBits(x: number, bits: number): number {
        let result = 0;
        for (let i = 0; i < bits; i++) {
            result = (result << 1) | (x & 1);
            x >>= 1;
        }
        return result;
    }

    /**
     * Get sample rate from AudioContext
     */
    public getSampleRate(): number {
        return this.audioContext?.sampleRate || 44100;
    }
}
