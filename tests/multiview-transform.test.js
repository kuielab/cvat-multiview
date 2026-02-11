const assert = require('assert');

require('@babel/register')({
    extensions: ['.ts', '.tsx'],
    presets: [
        ['@babel/preset-env', { targets: { node: 'current' } }],
        ['@babel/preset-typescript', { allExtensions: true, isTSX: true }],
    ],
    ignore: [/node_modules/],
});

const {
    createVideoProportionalFrameData,
    transformPointsForStorage,
    transformPointsForDisplay,
} = require('../cvat-ui/src/components/annotation-page/multiview-workspace/multiview-canvas-utils.ts');

function approxEqual(a, b, eps = 1e-6) {
    assert.ok(Math.abs(a - b) <= eps, `Expected ${a} ~= ${b}`);
}

function approxArray(a, b, eps = 1e-6) {
    assert.strictEqual(a.length, b.length, 'Array lengths differ');
    for (let i = 0; i < a.length; i += 1) {
        approxEqual(a[i], b[i], eps);
    }
}

// Case 1: Exact aspect ratio match should still return transform
{
    const frameData = { width: 1920, height: 1080 };
    const res = createVideoProportionalFrameData(frameData, 1920, 1080);
    assert.ok(res, 'Expected transform result');
    assert.strictEqual(res.transform.taskWidth, 1920);
    assert.strictEqual(res.transform.taskHeight, 1080);
    assert.strictEqual(res.transform.canvasWidth, 1920);
    assert.strictEqual(res.transform.canvasHeight, 1080);
}

// Case 2: Small aspect ratio difference should return transform
{
    const frameData = { width: 1920, height: 1080 };
    const res = createVideoProportionalFrameData(frameData, 1918, 1080);
    assert.ok(res, 'Expected transform result for small aspect diff');
    assert.ok(res.transform.canvasWidth > 0, 'Expected positive canvasWidth');
    assert.ok(res.transform.canvasHeight > 0, 'Expected positive canvasHeight');
}

// Case 3: Storage->Display round trip should preserve points
{
    const frameData = { width: 1920, height: 1080 };
    const res = createVideoProportionalFrameData(frameData, 1280, 720);
    assert.ok(res, 'Expected transform result');
    const { canvasWidth, canvasHeight, taskHeight, taskWidth } = res.transform;

    const points = [100, 50, 400, 300];
    const stored = transformPointsForStorage(points, canvasWidth, canvasHeight, taskHeight, taskWidth);
    const displayed = transformPointsForDisplay(stored, canvasWidth, canvasHeight, taskHeight, taskWidth);
    approxArray(displayed, points, 1e-5);
}

console.log('multiview-transform.test.js: OK');
