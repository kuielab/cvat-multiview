# Multiview Refactor Test Plan

This document lists the tests to validate the multiview refactor. It focuses on
what to test and how to run the checks, without installation or environment setup.

## Scope

These tests verify that multiview functionality remains identical in behavior
while moving toward canvas-based rendering for all views.

## Test Matrix

Run all tests in both modes:

- Canvas render mode (default): canvas-only rendering
- Overlay mode: removed (ensure no `<video>` elements are rendered)

## Functional Tests (Manual or E2E)

1. Refresh Alignment
   - Open multiview job with existing bbox.
   - Record bbox center screen position.
   - Refresh 5?10 times.
   - Pass: center delta <= 2px.

2. View Switching
   - Switch across all available views rapidly.
   - Pass: active view updates, no draw mode stuck, no context menu persistence.

3. Draw Mode Auto-Pause
   - Start playback.
   - Enter draw mode.
   - Pass: playback pauses immediately.

4. Frame Seek (Paused)
   - Pause playback.
   - Scrub/seek to different frames.
   - Pass: all views render the same frame; no drift.

5. Frame Progression (Playing)
   - Play for 20?60 seconds.
   - Pass: frameNumber advances smoothly; views remain in sync.

6. Zoom/Pan
   - Zoom in/out (mouse wheel).
   - Pan with drag.
   - Reset zoom with double-click.
   - Pass: bbox stays aligned; pan does not drag shapes.

7. Object Selection
   - Click bbox in active view.
   - Pass: object highlights; sidebar scroll works.

8. Resize/Window Layout
   - Collapse/expand sidebars and resize window.
   - Pass: bbox alignment stable; no jump on resize.


9. No HTMLVideoElement
   - Open a multiview job.
   - Inspect DOM for `.multiview-video` elements.
   - Pass: none are rendered in multiview workspace.

10. Canvas-Only Zoom/Pan
   - Zoom with wheel and pan with middle/right/Alt-drag.
   - Pass: no CSS transform on `.zoom-wrapper`; zoom/pan is canvas-driven.


11. Playback Rate Effect
   - Set playback rate to 2x.
   - Play for 5 seconds.
   - Pass: frameNumber advances ~2x faster than 1x.


12. Edge Alignment (No Letterbox)
   - Draw bbox touching exact image edges (top-left and bottom-right).
   - Save and refresh.
   - Pass: bbox still touches edges with no margin/offset.

13. Mixed-Resolution Views
   - Use a multiview task where view sizes differ (e.g., 1920x1080 and 1280x720).
   - Draw a bbox in View 2 near an image edge.
   - Save and refresh.
   - Pass: bbox aligns to the same pixels in View 2; no drift vs. edge.

14. Per-View Dimension Source of Truth
   - Open devtools and inspect `state.annotation.multiviewData`.
   - Confirm each view has `width`/`height` and `fps`.
   - Draw a bbox at the right/bottom edge in a non-View1 camera.
   - Pass: bbox edge aligns with image edge after refresh.

15. Chunk Decode Network Path
   - Open devtools Network tab.
   - Play 3-5 seconds.
   - Pass: requests include `/multiview/data/{view_id}?type=chunk&index=`.

16. Frame Step / Skip Frame
   - Use a job with frameStep > 1.
   - Play and seek across frames.
   - Pass: frameNumber advances by step, bbox stays aligned.

17. Playback End Boundary
   - Play until the last frame.
   - Pass: playback stops at stopFrame and does not advance.

18. View Switch During Playback
   - Start playback and switch active view.
   - Pass: playback stays in sync, draw mode not stuck.

19. Zoom Reset on View Change
   - Zoom in on View A, switch to View B, then back to View A.
   - Pass: zoom state resets to fit; bbox alignment preserved.

20. Chunk Decode Failure Handling
   - Simulate a transient network error for chunk requests.
   - Pass: error is handled gracefully; frame loads on retry.

## Spectrogram Tests

1. Generate Spectrogram
   - Click ¡°Generate Spectrogram.¡±
   - Pass: completes without error.

2. Spectrogram Without DOM Video
   - Confirm DOM has no `<video>` elements in multiview.
   - Generate spectrogram.
   - Pass: uses metadata URLs and completes without error.


3. Spectrogram Seek (Paused)
   - Click in spectrogram while paused.
   - Pass: frame jumps to expected time.

4. Spectrogram Seek (Playing)
   - While playing, click spectrogram.
   - Pass: pauses, seeks, resumes correctly.

5. Playhead Sync
   - During playback, confirm playhead tracks frame time.
   - Pass: playhead moves smoothly with playback.

## Annotation Integrity

1. Create Annotation
   - Draw rectangle in active view.
   - Save.
   - Refresh.
   - Pass: bbox position and size unchanged.

2. Edit Annotation
   - Resize/move bbox.
   - Save.
   - Refresh.
   - Pass: bbox persists exactly.

3. View-Specific Filtering
   - Ensure bbox drawn in View 1 does not appear in View 2.

4. Rotation Edge Case
   - Rotate a bbox if supported.
   - Refresh.
   - Pass: rotation and position persist.

5. Non-Rectangle Shapes
   - Create polygon/polyline/points (if enabled).
   - Save and refresh.
   - Pass: shape vertices remain aligned.

6. Visibility Flags
   - Toggle occluded/outside/hidden states.
   - Save and refresh.
   - Pass: visibility states persist and render correctly.

## Regression Tests (Existing)

1. Canvas Context Menu
   - Right click on bbox.
   - Pass: menu appears; closes when view changes.

2. Delete Shortcut
   - Select bbox, press Delete.
   - Pass: bbox removed and sidebar updates.

3. Small Shape Resize Protection
   - Resize a small bbox.
   - Pass: bbox does not collapse unexpectedly.

## Performance Checks

1. Multi-View Load
   - Open a job with 5?10 views.
   - Pass: UI remains responsive.

2. Memory/CPU Observation
   - During playback, confirm no runaway memory usage.

3. Frame Endpoint Hot Cache
   - In canvas render mode, stay on a single frame.
   - Refresh the same frame 20+ times (e.g., toggle views without changing frame).
   - Pass: subsequent loads are faster; no stutter.

4. Frame Endpoint Cold Cache
   - In canvas render mode, jump to a new frame every time (e.g., +50 frames).
   - Pass: frames load consistently with no error responses.

5. Frame Endpoint Parallel Stress
   - Open 5?10 views and play for 30s in canvas mode.
   - Pass: no major frame drops; server remains stable.


## E2E Automation Candidates (Playwright)

1. Refresh Alignment
2. View Switch + Active Selection
3. Draw + Refresh Persistence
4. Spectrogram Seek
5. Zoom/Pan in Canvas Mode

6. Frame Endpoint Stability (Repeated Same Frame)
7. FPS Metadata Consistency (view fps reported in multiview_data)

## Pass/Fail Criteria Summary

- Alignment drift <= 2px after refresh
- Views remain synchronized in playback and seeking
- Draw/edit actions persist after refresh
- All multiview-specific features (spectrogram, zoom/pan, auto-pause) behave identically
- Multiview frame endpoint returns frames without errors under stress
- `multiview_data` fps present and used for playback timing


## Canvas-Only Regression

1. Overlay Mode Removal
   - Confirm there is no fallback to `<video>` elements.
   - Pass: multiview renders entirely via canvas.
