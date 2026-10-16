// Only synthetic PNG headers and browser/OS doubles; no native commands run.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { pngSize, assertNativeLayout } = require("../timeline-native-capture.cjs");
const box = { left: 8, right: 502, top: 120, bottom: 200, width: 494, height: 80,
  client_width: 494, scroll_width: 494, client_height: 80, scroll_height: 80, scroll_top: 0 };
const state = () => ({ width: 510, height: 348, dpr: 2, visual_scale: 1, css_zoom: "1", document_zoom: "1",
  visibility: "visible", target_visible: true, target_text: "First synthetic window.",
  document: {...box}, body: {...box}, elements: Object.fromEntries([".source-panel", "#sourceClaims", "#sourceWindow", "#sourceContent", "#sourceClaims li", '#sourceContent .cue[data-cue-index="0"]'].map(key => [key, {...box}])) });
const zoomed = {width: 510, height: 348, dpr: 2}, selector = "#sourceClaims li";
assertNativeLayout(state(), zoomed, selector);
for (const mutate of [
  s => s.elements[selector].scroll_width += 3,
  s => s.body.scroll_width += 3,
  s => s.elements[".source-panel"].right = 513,
  s => s.target_visible = false,
  s => s.target_text = " ",
  s => s.dpr = 1,
  s => s.css_zoom = "2",
  s => s.width = 1020,
]) {
  const invalid = state(); mutate(invalid);
  assert.throws(() => assertNativeLayout(invalid, zoomed, selector));
}
const png = (width, height) => {
  const bytes = Buffer.alloc(24); Buffer.from([137,80,78,71,13,10,26,10]).copy(bytes);
  bytes.write("IHDR", 12); bytes.writeUInt32BE(width, 16); bytes.writeUInt32BE(height, 20); return bytes;
};
assert.deepEqual(pngSize(png(1020, 696)), {width: 1020, height: 696});
assert.throws(() => pngSize(Buffer.alloc(24)));

async function probe(fail = "", detachFails = false) {
  const calls = [], reports = [], files = new Map();
  const primary = new Error(`${fail.toUpperCase()}_CAPTURE_FAILURE`), detachError = new Error("DETACH_FAILURE");
  const code = fs.readFileSync(path.join(__dirname, "../timeline-native-capture.cjs"), "utf8");
  const sandbox = {module: {exports: {}}, Buffer, require: name => name === "node:fs" ? {
    readFileSync: filename => files.get(filename), writeFileSync: (filename, bytes) => {
      if (fail === "write") throw primary;
      files.set(filename, bytes);
    },
  } : require(name)};
  vm.runInNewContext(code, sandbox);
  const page = {
    locator: () => ({first: () => ({evaluate: async () => calls.push("scroll")})}),
    bringToFront: async () => calls.push("foreground"),
    evaluate: async (fn, selected) => selected ? state() : undefined,
    context: () => ({newCDPSession: async () => ({send: async (method, args) => {
      calls.push("cdp"); assert.equal(method, "Page.captureScreenshot"); assert.equal(args.captureBeyondViewport, false);
      assert.equal("clip" in args, false); if (fail === "cdp") throw primary;
      return {data: png(1020, 696).toString("base64")};
    }, detach: async () => { calls.push("detach"); if (detachFails) throw detachError; }})}),
    screenshot: async args => { calls.push(args.fullPage ? "fullpage" : "playwright"); return png(510, 348); },
  };
  const nativeCapture = filename => {
    calls.push("owned"); files.set(filename, png(1024, 768));
    return {width: 1024, height: 768, sampled_colors: fail === "blank" ? 1 : 30};
  };
  const task = sandbox.module.exports.captureNativeViews(page, {out: "/not-written", zoomed, nativeCapture, reports});
  if (fail || detachFails) {
    await assert.rejects(task, error => fail === "blank" ? /must not be blank/.test(String(error)) : error === (fail ? primary : detachError));
    assert.equal(reports.length, 1, "Failure retains partial native capture diagnostics");
    assert.equal(calls.includes("detach"), fail !== "blank");
    assert.equal(Boolean(reports[0].detach_error), detachFails && fail !== "blank");
  } else {
    await task;
    assert.deepEqual(calls, ["scroll", "foreground", "owned", "cdp", "detach", "playwright", "scroll", "foreground", "owned", "cdp", "detach", "playwright", "fullpage"]);
    assert.equal(reports.length, 3);
    assert.equal(reports[0].expected_content_pixels.width, 1020);
    assert.equal(reports[0].playwright_diagnostic.width, 510, "CSS-sized diagnostics cannot masquerade as native window pixels");
    assert.equal(reports[0].owned_window.width, 1024);
  }
}
(async () => {
  for (const failure of ["", "blank", "cdp", "write"])
    for (const detachFails of [false, true]) await probe(failure, detachFails);
  console.log("Native capture: hidden overflow, blank pixels, geometry changes, capture order and failure diagnostics passed; no native commands executed");
})().catch(error => { console.error(error); process.exitCode = 1; });
