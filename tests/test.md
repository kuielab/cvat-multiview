# Multiview Refactor Test Plan

This document lists the tests to validate the multiview refactor. It focuses on
what to test and how to run the checks, without installation or environment setup.

## Scope

These tests verify that multiview functionality remains identical in behavior
while moving toward canvas-based rendering for all views.

## Test Matrix

Run all tests in both modes:

- Overlay mode (default): current `<video>` + canvas overlay
- Canvas render mode: set `window.CVAT_MULTIVIEW_CANVAS_RENDER = true`

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

## Spectrogram Tests

1. Generate Spectrogram
   - Click ¡°Generate Spectrogram.¡±
   - Pass: completes without error.

2. Spectrogram Seek (Paused)
   - Click in spectrogram while paused.
   - Pass: frame jumps to expected time.

3. Spectrogram Seek (Playing)
   - While playing, click spectrogram.
   - Pass: pauses, seeks, resumes correctly.

4. Playhead Sync
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
