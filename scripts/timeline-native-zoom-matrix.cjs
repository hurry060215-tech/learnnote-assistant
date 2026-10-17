/* Additional browser-native presets in the same owned disposable Edge window. */
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { captureNativeViews, pngSize } = require('./timeline-native-capture.cjs');
const PERCENTAGES = Object.freeze([90, 125, 150]);
function assertZoomMetrics(actual, baseline, percent) {
  const ratio = percent / 100;
  assert(Math.abs(actual.dpr / baseline.dpr - ratio) < .015, 'Native DPR must match requested preset');
  assert(Math.abs(actual.width / baseline.width - 1 / ratio) < .015, 'Native CSS viewport must track inverse zoom');
  assert(['1', 'normal'].includes(actual.cssZoom));
  assert(['1', 'normal'].includes(actual.documentZoom));
  assert.equal(actual.visualScale, 1, 'Pinch zoom is not browser zoom');
  assert(Math.abs(actual.height / baseline.height - 1 / ratio) < .03, 'Native CSS viewport height must track inverse zoom');
  if (percent === 100) {
    assert.equal(actual.dpr, baseline.dpr);
    assert(Math.abs(actual.width - baseline.width) <= 1 && Math.abs(actual.height - baseline.height) <= 1, 'Reset must restore the measured baseline viewport');
  }
  assert(actual.overflow <= 2, 'Native zoom must not create horizontal overflow');
}
async function waitForNativePreset(page, metrics, baseline, percent) {
  await page.waitForFunction(({ initial, ratio }) => Math.abs(devicePixelRatio / initial.dpr - ratio) < .015 &&
    Math.abs(innerWidth / initial.width - 1 / ratio) < .015, { initial: baseline, ratio: percent / 100 });
  const actual = await metrics(); assertZoomMetrics(actual, baseline, percent); return actual;
}
function secondaryLayout() {
  const menu = document.querySelector('#readerOptions .reader-options-menu');
  const box = node => { const r = node.getBoundingClientRect(); return { left:r.left, right:r.right, top:r.top, bottom:r.bottom,
    width:r.width, height:r.height, client:node.clientWidth, scroll:node.scrollWidth }; };
  return { width:innerWidth, height:innerHeight, open:document.querySelector('#readerOptions').open,
    menu:box(menu), controls:['#export','#moreTools'].map(selector => ({selector,...box(document.querySelector(selector))})) };
}
function assertSecondaryLayout(state) {
  assert.equal(state.open, true);
  for (const box of [state.menu, ...state.controls]) {
    assert(box.width > 0 && box.height > 0 && box.left >= -1 && box.right <= state.width + 1 &&
      box.top >= -1 && box.bottom <= state.height + 1 && box.scroll <= box.client + 2, 'Secondary controls must be fully visible without clipping');
  }
}
async function runNativeZoomMatrix({ page, marker, nativeKey, metrics, baseline, out, cases }) {
  for (const percent of PERCENTAGES) {
    const record = { percent, captures:[] }; cases.push(record);
    await marker.click(); await page.waitForFunction(() => document.querySelector('#player').readyState >= 1);
    await marker.focus(); await page.bringToFront(); record.command = nativeKey(String(percent));
    record.metrics = await waitForNativePreset(page, metrics, baseline, percent);
    assert.equal(await marker.evaluate(node => node === document.activeElement), true);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => Math.abs(document.querySelector('#player').currentTime - 10) < .1 && !document.querySelector('#player').seeking);
    assert.equal(await page.locator('#player').evaluate(node => node.paused), true);
    record.keyboard_source_seek = true;
    const cue = page.locator('#sourceContent .cue[aria-current="time"]');
    await cue.focus(); await page.keyboard.press('Home');
    await page.waitForFunction(() => document.activeElement?.dataset.cueIndex === '0');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#player').currentTime < .1 && !document.querySelector('#player').seeking);
    assert.equal(await page.locator('#player').evaluate(node => node.paused), true);
    record.keyboard_first_cue = true;
    await captureNativeViews(page, { out, zoomed:record.metrics, percent, nativeCapture:filename => nativeKey('capture',filename), reports:record.captures });
    await page.locator('#closeSource').click();
    await page.locator('#readerOptions > summary').focus(); await page.keyboard.press('Enter');
    assert(await page.locator('#export').isVisible()); assert(await page.locator('#moreTools').isVisible());
    record.secondary = await page.evaluate(secondaryLayout); assertSecondaryLayout(record.secondary);
    await page.bringToFront();
    const filename = `native-${percent}-secondary-owned-window.png`;
    record.secondary_capture = { filename,...nativeKey('capture',path.join(out,filename)) };
    const size = pngSize(fs.readFileSync(path.join(out,filename)));
    assert.equal(size.width,record.secondary_capture.width); assert.equal(size.height,record.secondary_capture.height);
    assert(record.secondary_capture.sampled_colors > 1);
    assertSecondaryLayout(await page.evaluate(secondaryLayout));
    assertZoomMetrics(await metrics(),baseline,percent);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#readerOptions').evaluate(node => node.open),false);
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('#readerOptions > summary')),true);
    record.keyboard_secondary_actions = true;
    nativeKey('reset'); record.restored = await waitForNativePreset(page,metrics,baseline,100);
  }
}
module.exports = { PERCENTAGES, assertZoomMetrics, waitForNativePreset, secondaryLayout, assertSecondaryLayout, runNativeZoomMatrix };
