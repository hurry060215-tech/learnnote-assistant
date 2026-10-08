import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const context = vm.createContext({ URL });
for (const filename of ["task-format.js", "task-display.js"]) {
  vm.runInContext(await readFile(new URL("../" + filename, import.meta.url), "utf8"), context);
}
const format = context.LearnNoteTaskFormat;
const display = context.LearnNoteTaskDisplay;
assert.ok(Object.isFrozen(format));
assert.ok(Object.isFrozen(display));
assert.equal(context.document, undefined);
assert.equal(context.localStorage, undefined);
assert.equal(context.fetch, undefined);

export function taskFormatSnapshot(format, display) {
  return {
    escaped: format.escapeHtml('<script title="x">A&B</script>'),
    clocks: [-1, 0, 1.25, 3599, 3600, 86401].map(format.fmt),
    seek: [NaN, -5, 1.2349].map(format.seekTimeValue),
    button: format.seekTimeButton(65.125, 'time-seek" onclick="bad'),
    bytes: [0, 1, 1024, 1048576, 1073741824].map(format.fmtBytes),
    compact: format.compactUrl("https://example.test/" + "long".repeat(50), 72),
    titles: ["", "????", "普通课程", "???问", "Question?"].map(format.isUnreadableTitle),
    disposition: format.contentDispositionFilename("attachment; filename=bad.txt; filename*=UTF-8''%E8%AF%BE%E7%A8%8B.mp4"),
    headers: format.requestHeaderNames({ request_headers: { Cookie: "private", Authorization: "private", Range: "bytes=0-10", Accept: "video/mp4" } }),
    body: format.requestBodySummary({ method: "POST", request_body: { type: "form", content: "<redacted>" } }),
    semver: [["1.2.3", "1.2.2"], ["1.2.3-beta", "1.2.2"], ["2.0.0", "10.0.0"]].map(args => format.isNewerVersion(...args)),
    sources: ["hls", "dash", "subtitle", "unexpected"].map(kind => display.sourceText({ selected_resource: { kind } })),
    active: display.activeVideoText({ src: "blob:https://example.test/fixture", paused: false, current_time: 65, duration: 120, frame_id: 0, width: 1920, height: 1080 }),
    playback: ["exact-src", "blob-source", "range-near-playhead", "unknown"].map(display.playbackText),
    diagnostic: display.summaryDiagnosticText({ summary_source: "source-only", summary_diagnostics: { used_text_llm: true, llm_model: "fixture-model", visual_window_count: 3, frame_grid_count: 2, vision_failed_batch_count: 1, missing_vision_image_window_ids: ["W001"] } }),
    options: display.optionText({ options: { transcriber: "openai-compatible", frame_interval: 30, visual_understanding: false } }),
  };
}

const snapshot = JSON.parse(await readFile(new URL("./fixtures/task_format_boundaries_v1.json", import.meta.url), "utf8"));
assert.deepEqual(JSON.parse(JSON.stringify(taskFormatSnapshot(format, display))), snapshot.result);
const source = await readFile(new URL("../task-display.js", import.meta.url), "utf8");
assert.throws(() => vm.runInContext(source, vm.createContext({ URL })), /undefined/);
console.log("Pure task formatting/display, escaping and dependency-order snapshots pass");
