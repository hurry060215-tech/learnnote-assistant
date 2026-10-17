/* Keep native window pixels separate from CDP/Playwright screenshot diagnostics. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
function pngSize(bytes) {
  assert(bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])), "Expected PNG bytes");
  assert.equal(bytes.toString("ascii", 12, 16), "IHDR");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}
function readNativeLayout(selector) {
  const describe = node => {
    const rect = node.getBoundingClientRect();
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      width: rect.width, height: rect.height, client_width: node.clientWidth, scroll_width: node.scrollWidth,
      client_height: node.clientHeight, scroll_height: node.scrollHeight, scroll_top: node.scrollTop };
  };
  const target = document.querySelector(selector), rect = target.getBoundingClientRect();
  const x = (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2;
  const y = (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2;
  return { width: innerWidth, height: innerHeight, outer_width: outerWidth, outer_height: outerHeight,
    dpr: devicePixelRatio, visual_scale: visualViewport.scale,
    css_zoom: getComputedStyle(document.body).zoom, document_zoom: getComputedStyle(document.documentElement).zoom,
    scroll_x: scrollX, scroll_y: scrollY, visibility: document.visibilityState,
    document: describe(document.documentElement), body: describe(document.body),
    elements: Object.fromEntries([".source-panel", "#sourceClaims", "#sourceWindow", "#sourceContent", selector]
      .map(key => [key, describe(document.querySelector(key))])),
    target_text: target.innerText, target_visible: rect.top < innerHeight && rect.bottom > 0 &&
      rect.left < innerWidth && rect.right > 0 && target.contains(document.elementFromPoint(x, y)),
    active_cue: document.activeElement?.dataset.cueIndex };
}
function assertNativeLayout(state, zoomed, selector) {
  assert.equal(state.width, zoomed.width, "Capture preserves the native CSS viewport width");
  assert.equal(state.height, zoomed.height, "Capture preserves the native CSS viewport height");
  assert.equal(state.dpr, zoomed.dpr, "Capture preserves the native device-pixel ratio");
  assert.equal(state.visual_scale, 1);
  assert(["1", "normal"].includes(state.css_zoom));
  assert(["1", "normal"].includes(state.document_zoom));
  assert.equal(state.visibility, "visible");
  assert(state.target_visible && state.target_text.trim(), "Capture target must have visible rendered source text");
  for (const [name, box] of Object.entries({ document: state.document, body: state.body, ...state.elements })) {
    assert(box.scroll_width <= box.client_width + 2, `${name}: no hidden horizontal content overflow`);
  }
  for (const name of [".source-panel", selector]) {
    const box = state.elements[name];
    assert(box.left >= -2 && box.right <= state.width + 2, `${name}: source content fits the native viewport`);
  }
}
async function captureNativeViews(page, { out, zoomed, nativeCapture, reports, percent = 200 }) {
  for (const [name, selector] of [["claims", "#sourceClaims li"], ["cue", '#sourceContent .cue[data-cue-index="0"]']]) {
    const record = { view: name, selector }; reports.push(record);
    await page.locator(selector).first().evaluate(node => node.scrollIntoView({ block: "center", behavior: "instant" }));
    await page.bringToFront();
    await page.evaluate(async () => { await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    record.before = await page.evaluate(readNativeLayout, selector);
    assertNativeLayout(record.before, zoomed, selector);
    const ownedName = `native-${percent}-${name}-owned-window.png`;
    record.owned_window = { filename: ownedName, ...nativeCapture(path.join(out, ownedName)) };
    const ownedSize = pngSize(fs.readFileSync(path.join(out, ownedName)));
    assert.equal(ownedSize.width, record.owned_window.width); assert.equal(ownedSize.height, record.owned_window.height);
    assert(record.owned_window.sampled_colors > 1, "Owned-window evidence must not be blank");
    const session = await page.context().newCDPSession(page);
    let captureFailure;
    try {
      // Read the actual surface without the CSS-sized clip used by Playwright.
      const { data } = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
      const bytes = Buffer.from(data, "base64"), filename = `native-${percent}-${name}-cdp-surface.png`;
      fs.writeFileSync(path.join(out, filename), bytes);
      record.cdp_surface_diagnostic = { filename, ...pngSize(bytes) };
    } catch (error) { captureFailure = error; throw error; }
    finally {
      try { await session.detach(); }
      catch (error) { record.detach_error = String(error); if (!captureFailure) throw error; }
    }
    const filename = `native-${percent}-${name}-playwright-viewport.png`;
    const bytes = await page.screenshot({ path: path.join(out, filename) });
    record.playwright_diagnostic = { filename, ...pngSize(bytes) };
    record.expected_content_pixels = { width: zoomed.width * zoomed.dpr, height: zoomed.height * zoomed.dpr };
    record.after = await page.evaluate(readNativeLayout, selector);
    assertNativeLayout(record.after, zoomed, selector);
  }
  // Retain the former full-page route only as a diagnostic, never visual proof.
  const record = { view: "playwright-full-page-diagnostic" }; reports.push(record);
  const selector = '#sourceContent .cue[data-cue-index="0"]';
  record.before = await page.evaluate(readNativeLayout, selector);
  const filename = `claim-timeline-native-${percent}-percent.png`;
  const bytes = await page.screenshot({ path: path.join(out, filename), fullPage: true });
  record.playwright_diagnostic = { filename, ...pngSize(bytes) };
  record.after = await page.evaluate(readNativeLayout, selector);
  assertNativeLayout(record.after, zoomed, selector);
}
module.exports = { pngSize, readNativeLayout, assertNativeLayout, captureNativeViews };
