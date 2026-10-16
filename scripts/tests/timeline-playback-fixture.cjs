const assert = require("node:assert/strict"), vm = require("node:vm"), fs = require("node:fs"), path = require("node:path");
const { openVisibleTranscript, playbackTracksReady } = require("../timeline-playback-acceptance.cjs");

(async () => {
  for (const initiallyOpen of [false, true]) {
    const disclosure = { open: initiallyOpen }, actions = [];
    const summary = { click: async () => { actions.push("summary click"); disclosure.open = true; } };
    const transcript = { evaluate: async fn => fn(disclosure), locator: selector => { assert.equal(selector, "summary"); return summary; } };
    const page = { locator: selector => selector === "#sourceTranscript" ? transcript : {
      first: () => ({ waitFor: async options => { assert.equal(disclosure.open, true); assert.equal(options.state, "visible"); actions.push("visible cue"); } })
    } };
    await openVisibleTranscript(page);
    assert.deepEqual(actions, initiallyOpen ? ["visible cue"] : ["summary click", "visible cue"]);
  }
  const transcript = { open: true }, player = { paused: false }, frame = { dataset: { windowId: "window-2" } };
  const cue = { innerText: "0:10 Second synthetic window", textContent: "0:10 Second synthetic window", getClientRects: () => [{}] };
  const claim = { getAttribute: () => "true" };
  const document = { querySelector: selector => selector === "#sourceTranscript" ? transcript : selector === "#player" ? player
    : selector.startsWith("#sourceContent") ? cue : selector === "#sourceWindow figure" ? frame : claim };
  const ready = () => vm.runInNewContext(`(${playbackTracksReady.toString()})("fixture-claim")`, { document });
  assert.equal(ready(), true);
  transcript.open = false; assert.equal(Boolean(ready()), false); transcript.open = true;
  cue.innerText = ""; assert.equal(Boolean(ready()), false, "Hidden DOM textContent cannot satisfy rendered-text acceptance"); cue.innerText = cue.textContent;
  cue.getClientRects = () => []; assert.equal(Boolean(ready()), false); cue.getClientRects = () => [{}];
  player.paused = true; assert.equal(Boolean(ready()), false); player.paused = false;
  frame.dataset.windowId = "window-1"; assert.equal(Boolean(ready()), false); frame.dataset.windowId = "window-2";
  claim.getAttribute = () => null; assert.equal(Boolean(ready()), false);
  // Run the real fixture's failure path with browser/network/file writes mocked.
  const fixtureSource = fs.readFileSync(path.join(__dirname, "../evidence-source-acceptance.cjs"), "utf8").split('if (process.argv.includes("--self-test"))')[0] + "module.exports = main;";
  for (const reportFails of [false, true]) for (const closeFails of [false, true]) {
    const primary = new Error("PRIMARY_FIXTURE_FAILURE"), closed = [];
    const page = { context: () => ({ route: async () => {} }), on() {}, setDefaultTimeout() {},
      evaluate: async () => ({ fixture: "failure state" }), screenshot: async () => { throw new Error("SCREENSHOT_FAILURE"); },
      request: { fetch: async () => { throw primary; }, delete: async () => {} } };
    const browser = { newPage: async () => page, close: async () => { closed.push(true); if (closeFails) throw new Error("CLOSE_FAILURE"); } };
    const sandbox = { module: { exports: {} }, process: { argv: [] }, URL, console: { error() {} },
      require: name => name === "playwright" ? { chromium: { launch: async () => browser } }
        : name === "node:fs" ? { mkdirSync() {}, writeFileSync() { if (reportFails) throw new Error("REPORT_FAILURE"); } }
        : name === "node:child_process" ? { execFileSync: () => JSON.stringify({ task_id: "local", subtitle_task_id: "subtitles" }) }
        : name.startsWith("./") ? {} : require(name) };
    vm.runInNewContext(fixtureSource, sandbox);
    await assert.rejects(sandbox.module.exports(), error => error === primary);
    assert.deepEqual(closed, [true], "Failure evidence cannot skip browser cleanup or replace the primary error");
  }
  console.log("Visible transcript setup and simultaneous unpaused cue/frame/claim predicate passed offline");
})().catch(error => { console.error(error); process.exitCode = 1; });
