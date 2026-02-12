# Multiview Refresh Alignment Refactor Plan

## Context

Multiview currently renders a `<video>` element and overlays an SVG canvas on top.
This creates a two-layer coordinate system:

- Storage: task/frameData coordinates
- Display: video element + CSS overlay coordinates

Small inconsistencies in video dimensions or layout timing can shift bbox positions
on refresh. Standard CVAT does not have this issue because the canvas renders the
image directly from frameData, keeping a single authoritative coordinate system.

## Why Standard CVAT Is Stable

- `canvasInstance.setup(frameData, ...)` uses server-provided frameData as the
  sole coordinate system.
- `fitCanvas()` and `fit()` are run consistently to align viewport geometry.
- No external `<video>` layer exists, so no cross-layer sync is required.

## Current Multiview Risk Areas

- `videoElement.videoWidth/Height` can vary per session and per view.
- Aspect ratio differences trigger coordinate transforms; small differences can
  still cause visible shifts.
- Layout shifts during initial setup can leave stale canvas geometry.

## Refactoring Goals

1. Stabilize coordinate transform inputs across refreshes.
2. Eliminate axis-specific transform gaps (X scaling and Y scaling consistent).
3. Harden setup gating to prevent transient values from being committed.

## Implemented Improvements

### 1) Metadata-First Dimension Selection

- Removed the video-dimension sampling hook and all HTMLVideoElement dependencies.
- Multiview now uses backend metadata as the sole dimension source.
- This removes session-to-session drift caused by video decoding variability.

Files:
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-wrapper.tsx`

### 2) X-Axis and Y-Axis Scaling

- Transform now scales both axes using task and video dimensions.
- The canvas coordinate system aligns to the actual video dimensions, while
  storage remains in task coordinates.

Files:
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-utils.ts`
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-wrapper.tsx`

### 2.5) Per-View Dimension Source of Truth

- Active view width/height now comes from `multiview_data` per-view metadata.
- FrameData width/height is overridden per view to match actual view resolution.
- Clamp/normalize logic uses per-view dimensions to avoid drift on mixed-res views.

Files:
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-wrapper.tsx`
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-preview.tsx`

### 3) Stability Gating (No Timeout Acceptance by Default)

- Canvas setup is now gated by frame data readiness and container sizing,
  without any timeout-based fallback.
- ResizeObserver re-fit logic is guarded to avoid stale geometry.

Files:
- `cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-wrapper.tsx`

## Optional Future Refactor (Bigger Change)

### Canvas-Renders-Video per View

- Each view uses a dedicated canvas that renders the video frames directly
  (standard CVAT pattern).
- This removes the two-layer sync problem entirely.
- Requires refactoring: frame extraction, playback sync, and performance tuning.

## Full Refactor Scope (All Parts to Modify)

This section enumerates all code areas, behaviors, and tests that must be
changed or re-validated if we move to a "canvas-renders-video per view" design.

### A. Backend and API Changes

1. Frame Image Delivery
   - Provide per-view frame images or a decode endpoint that can be drawn onto canvas.
   - Implemented: `/api/tasks/{id}/multiview/frame/{view_id}?number=...` returning PNG frames.
   - Implemented: `/api/tasks/{id}/multiview/data/{view_id}?type=chunk` for chunk-based decode.
   - Decide on format and performance strategy:
     - PNG/JPEG frames
     - WebP frames
     - HLS/MSE + canvas drawImage snapshots
   - Ensure frame index -> timestamp mapping is consistent across views.

2. Multiview Metadata
   - Confirm `multiview_data` returns authoritative width/height for each view.
   - Add fps and timebase information if needed by the canvas-driven player.
   - Implemented: `fps` injected into `multiview_data` per view.

3. Caching and Range
   - If using frame endpoints, design cache policies for repeated frames.
   - Verify API request rate limits for multi-view access patterns.
   - Implemented: in-memory LRU cache for multiview frame PNG responses.
   - Implemented: multiview chunks decoded client-side via cvat-core multiview frames cache.

### B. Frontend Rendering Pipeline

1. Remove HTMLVideoElement Rendering
   - Replace `<video>` elements with a canvas-only rendering path.
   - Remove object-fit letterboxing logic and overlay alignment hacks.
   - Implemented: multiview now renders canvas-only (no `<video>` elements).

2. Canvas Setup and Viewport Sync
   - Use standard CVAT ordering:
     - `setup(frameData, annotations)` -> `fitCanvas()` -> `fit()`
   - Avoid CSS transforms that could double-scale.

3. Coordinate Transform
   - If canvas renders frames directly, remove multiview-specific transforms.
   - If transforms remain, keep both X and Y scaling in a single canonical transform.
   - Implemented: multiview-specific transforms removed; frameData coords are authoritative.

4. Playback Engine
   - Replace video-based time control with a canvas frame clock.
   - Keep frames across views in exact sync.
   - Ensure frame number -> timestamp is stable.
   - Implemented: playback uses canvas clock only.

5. Zoom and Pan
   - Use canvas-native zoom/pan (or one unified transform only).
   - Remove CSS zoom wrapper and related event interception.
   - Implemented: CSS zoom removed; canvas zoom/pan only.

### C. Annotation Behavior Impacts

1. Draw/Drag/Resize
   - Validate that draw/drag hit-testing still works when no HTMLVideoElement exists.

2. Rotation and Skew
   - Ensure rotation uses the same frame coordinate system.

3. Visibility and Z-layer
   - Confirm z-layer ordering and visibility toggles still render correctly.

4. Review/Conflict Highlight
   - Verify highlight overlays render consistently on the canvas-only view.

### D. UI and Interaction Impacts

1. Multiview Grid Layout
   - Resize and focus transitions must re-run fitCanvas/fit.

2. Hotkeys and Cursor Modes
   - Ensure draw/drag/zoom modes are preserved during view changes.

3. Spectrogram + Audio Sync
   - Maintain a shared timebase between audio playback and canvas frames.

### E. Performance and Scaling

1. CPU/GPU Load
   - Canvas rendering for multiple views will increase CPU/GPU usage.
   - Avoid redundant redraws when frames do not change.

2. Network Load
   - Frame-by-frame loading may multiply bandwidth usage.
   - Test with 5, 8, 10 views.

3. Memory Usage
   - Ensure frame caching does not leak memory.

### F. Rollout Strategy

1. Feature Flag
   - Allow switching between current overlay mode and canvas-only mode.

2. Progressive Enablement
   - Test with 1?2 views first before expanding to 5?10 views.

3. Fallback Path
   - Provide an option to revert to HTMLVideoElement overlay if instability is found.

Status:
- Not implemented. Requires a runtime switch and parallel code paths.

## Behavior Impact Analysis

Below is a detailed list of existing behaviors that can be affected:

1. Playback and Sync
   - Video element playback timing might not match a custom canvas clock.

2. Annotation Stability on Refresh
   - Goal: eliminate bbox drift entirely by using a single coordinate system.

3. Zoom UX
   - Current CSS-based zoom will be replaced by canvas transforms.
   - Pan/zoom precision and performance need re-validation.

4. Frame Seeking
   - Seek should update all views on the same frame boundary.

5. Draw State Persistence
   - Switch view without breaking draw modes.

6. Event Handling
   - Mouse and keyboard events must be re-bound to canvas-only layers.

## Feature Parity Requirements (Must Stay Identical)

The following Multiview features must keep the same behavior after refactor:

1. Synchronized Playback
   - All views start at the same time and stay aligned.
   - Playback rate remains uniform across views.

2. Frame-Accurate Seeking
   - `frameNumber` changes must seek all views to the same frame.
   - During playback, the master time source must update Redux consistently.

3. Draw Mode Auto-Pause
   - Entering draw mode must pause playback immediately.

4. Active View Audio Policy
   - Only the active view should be audible.

5. Zoom/Pan UX
   - Scroll zoom (1x~5x), drag pan, double-click reset must remain intact.

6. View Switching
   - Clicking a view changes active view without breaking draw modes.
   - Zoom state resets on view change.

7. Spectrogram Generation
   - Generate from all video sources, mix audio, render spectrogram.

8. Spectrogram Seek
   - Clicking spectrogram seeks to correct frame and resumes playback if needed.

9. Annotation Filtering by View
   - View-specific annotations must remain isolated to their view.

10. Sidebar and Object List
   - Objects list must update correctly per view and on frame changes.

## Feature-to-Refactor Mapping

This section tells you what must be replaced or preserved for each feature.

1. Synchronized Playback
   - Current: HTMLVideoElement `play()` across all views.
   - Refactor: Replace with shared canvas clock + per-view frame draw.
   - Risk: drift if the clock is not stable.

2. Frame-Accurate Seeking
   - Current: set `video.currentTime` in all views.
   - Refactor: compute frame index and redraw all views at that index.
   - Risk: off-by-one with frame -> time mapping.

3. Zoom/Pan
   - Current: CSS transform on zoom wrapper.
   - Refactor: apply canvas transform once or internal CVAT zoom logic.
   - Risk: double scaling or mismatch in event coordinates.

4. Spectrogram
   - Current: uses metadata URLs and `fetchAndDecodeAudio()` (no DOM video).
   - Refactor: keep metadata URLs available for all views.
   - Risk: missing URLs in multiview metadata breaks spectrogram.

5. Draw Mode Auto-Pause
   - Current: relies on Redux `activeControl`.
   - Refactor: must keep activeControl transitions intact.

6. Active View Audio
   - Current: no DOM video playback, so no per-view audio output path.
   - Refactor: if audio playback is required, add an explicit audio routing policy.

7. Objects Sidebar
   - Current: viewId filtering in `multiview-canvas-wrapper` and objects list.
   - Refactor: must keep viewId tagging and filtering identical.

## Test Plan (Detailed)

### Unit Tests

1. Transform Round-Trip
   - Validate storage -> display -> storage round-trip is stable.
   - File: `tests/multiview-transform.test.js`

### E2E Tests (Playwright)

1. Refresh Alignment
   - Verify bbox centers remain within 2px after refresh.
   - File: `tests/e2e/multiview-refresh-alignment.spec.ts`

2. Cross-View Sync
   - Check the same frame renders on all views at the same time.

3. Zoom/Pan Consistency
   - Validate that zoom does not shift bbox relative to the frame.

4. Draw/Resize Persistence
   - Draw a bbox, refresh, confirm position and size are unchanged.

5. Playback Drift
   - Play for 60s and verify frame number remains consistent across views.

6. Spectrogram Seek
   - Click on spectrogram and verify frame seek matches the correct timestamp.

### Manual Validation

1. Multiple Refreshes
   - 5?10 refresh cycles on the same view/frame.

2. Edge Cases
   - Very small bbox near borders.
   - Rotated bbox.

3. Performance Stress
   - Run with max view count and continuous playback.

## Validation Summary

- Unit: `tests/multiview-transform.test.js`
- E2E: `tests/e2e/multiview-refresh-alignment.spec.ts`
- Manual: refresh and verify bbox center deltas <= 2px
