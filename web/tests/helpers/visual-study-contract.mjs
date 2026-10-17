import vm from "node:vm";

export const baseline = "d2b4ef09e48b7be0e21675603dba0d777c31ebf8";
export const rendererNames = [
  "visualStudyCorrelationHtml", "visualStudyOverviewHtml", "visualStudyReviewPathHtml",
  "visualStudyHandoutHtml", "visualStudyDeck", "visualStudyNavigatorHtml"
];
export const functionNames = ["visualWindowEvidenceState", "visualWindowReviewItem", ...rendererNames];
export const providerFiles = ["task-format.js", "task-display.js", "task-list.js", "visual-window-evidence.js"];
export const adapterNames = ["safeNoteMediaUrl", "hasTaskDiagnostics", "taskExportUrl", "taskClipExportUrl"];

// Git stores the frozen source as LF; Windows may check it out as CRLF.
// Canonicalize only that transport difference, preserving all other bytes.
export function canonicalSource(source) {
  return source.replace(/\r\n/g, "\n");
}

export function functionSource(source, name) {
  source = canonicalSource(source);
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw Error(`Missing original function ${name}`);
  const end = source.indexOf("\n}\n", start);
  if (end < 0) throw Error(`Missing function boundary ${name}`);
  return source.slice(start, end + 3);
}

// Actual app-owned policy runs in its own realm. The renderer never receives
// window/API/globalThis: only four callbacks which resolve current state on use.
export function createAdapters(appSource, readSource, runtime = {}) {
  const context = vm.createContext({
    API: runtime.api ?? "http://127.0.0.1:8766",
    window: { location: new URL(runtime.origin || "http://localhost:8765/classic") }
  });
  vm.runInContext(readSource("task-format.js"), context);
  vm.runInContext("var { escapeHtml } = globalThis.LearnNoteTaskFormat;", context);
  vm.runInContext(["isBackendSameOrigin", "apiUrl", ...adapterNames]
    .map(name => functionSource(appSource, name)).join("\n"), context);
  if (runtime.taskLinks !== false) vm.runInContext(readSource("task-links.js"), context);
  return { context, ports: Object.fromEntries(adapterNames.map(name => [name, context[name]])) };
}

export function project(domain, taskList, row) {
  const windows = taskList.visualWindows(row.task);
  return {
    ...Object.fromEntries(rendererNames.map(name => [name, domain[name](row.task, row.transcript)])),
    visualWindowEvidenceState: windows.map((window, index) => domain.visualWindowEvidenceState(row.task, window, index)),
    visualWindowReviewItem: windows.map((window, index) => domain.visualWindowReviewItem(row.task, window, index, row.transcript))
  };
}

const window = (id, start = 0, extra = {}) => ({
  id, start, end: start + 10, frame_count: 2, frame_timestamps: [start, start + 5],
  grid_url: `/data/fixture/${id}.jpg`, ...extra
});
const task = (windows, extra = {}) => ({ id: "synthetic-task", title: "合成课程", visual_windows: windows, ...extra });
const transcript = segments => ({ source: "browser", segments });

export function cases() {
  const priorityWindows = [
    window("ready", 70, { local_summary: "现有总结", transcript_excerpt: "摘录" }),
    window("vision", 50, { local_summary: "视觉总结", transcript_excerpt: "摘录" }),
    window("no-image", 40, { grid_url: "", transcript_excerpt: "摘录" }),
    window("no-cues", 30, { local_summary: "截图总结" }),
    window("no-summary", 20, { transcript_excerpt: "先从截图补总结" }),
    window("omitted", 10, { transcript_excerpt: "摘录" }),
    window("missing", 0, { transcript_excerpt: "摘录" })
  ];
  return [
    { name: "empty", task: {}, transcript: null },
    { name: "empty-arrays", task: task([], { frame_grids: [] }), transcript: transcript([]) },
    { name: "legacy-frame-grids", task: { id: "legacy", frame_grids: [
      { start: 0, end: 10, frame_count: 3, url: "/data/fixture/legacy.jpg", frame_timestamps: [0, 5, 10] },
      { start: 10, end: 20 }
    ] }, transcript: null },
    { name: "explicit-windows-win", task: task([window("explicit")], { frame_grids: [{ url: "/data/unused.jpg" }] }), transcript: null },
    { name: "diagnostic-precedence-and-review-priority", task: task(priorityWindows, {
      summary_diagnostics: { vision_image_window_ids: ["missing", "omitted", "vision"],
        missing_vision_image_window_ids: ["missing"], omitted_vision_window_ids: ["missing", "omitted"] },
      options: { grid_columns: 3, grid_rows: 2 }, media_path: "fixture.mp4"
    }), transcript: null },
    { name: "fallback-window-ids", task: task([window(""), window(0, 10), window(null, 20)], {
      summary_diagnostics: { missing_vision_image_window_ids: ["W001"], omitted_vision_window_ids: ["W002"], vision_image_window_ids: ["W003"] }
    }), transcript: null },
    { name: "global-vision-source", task: task([window("A"), window("B", 10)], { summary_source: "vision-llm" }), transcript: null },
    { name: "global-used-vision", task: task([window("A")], { summary_diagnostics: { used_vision_llm: true } }), transcript: null },
    { name: "numeric-diagnostic-ids", task: task([window("12")], { summary_diagnostics: { vision_image_window_ids: [12] } }), transcript: null },
    { name: "hostile-and-unicode", task: task([window('<img src=x onerror="bad">', 1.25, {
      grid_url: '/data/fixture/grid.jpg?a=1&b="quoted"', local_summary: '<script>bad()</script> ' + '中文😀'.repeat(65),
      key_points: ['<svg onload="bad">', '第二条'], transcript_excerpt: '<iframe src="bad">'
    })], { id: 'task /?&"', title: '<svg onload="bad">', media_path: "synthetic.mp4" }),
    transcript: transcript([{ start: 1.25, end: 4, text: '<script>cue()</script> ' + '字幕😀'.repeat(60) }]) },
    { name: "rejected-media-urls", task: task([
      window("remote", 0, { grid_url: "https://example.test/private.jpg" }),
      window("script", 10, { grid_url: "javascript:bad()" }),
      window("data", 20, { grid_url: "data:image/svg+xml,bad" }),
      window("protocol-relative", 30, { grid_url: "//example.test/private.jpg" }),
      window("relative", 40, { grid_url: "fixture.jpg" })
    ]), transcript: null },
    { name: "overlap-endpoints-and-empty-text", task: task([window("A", 10), window("B", 20)]), transcript: transcript([
      { start: 0, end: 10, text: "ends at first start" }, { start: 10, end: 11, text: "begins at first start" },
      { start: 20, end: 21, text: "begins at second start" }, { start: 30, end: 31, text: "after both" },
      { start: 12, end: 13, text: "   " }, { start: 14, text: "point cue" }
    ]) },
    { name: "negative-missing-and-zero-times", task: task([
      { id: "absent", frame_count: 0 }, window("negative", -5), window("zero", 0, { end: 0 })
    ]), transcript: transcript([{ text: "absent" }, { start: -4, end: 0, text: "negative" }, { start: 0, end: 0, text: "zero" }]) },
    { name: "limits-and-stable-priority-order", task: task(Array.from({ length: 12 }, (_, index) => window(`W${index}`, (index % 3) * 10, {
      local_summary: `summary ${index}`, transcript_excerpt: `excerpt ${index}`
    }))), transcript: null },
    { name: "dense-cues-and-summary-fallback", task: task([window("dense", 0, { frame_timestamps: [], frame_count: 0 })]),
      transcript: transcript(Array.from({ length: 8 }, (_, index) => ({ start: index, end: index + 1, text: `cue ${index} ` + "长文本".repeat(60) }))) },
    { name: "empty-summary-and-image", task: task([window("empty", 0, { grid_url: "", frame_timestamps: [] })]), transcript: null },
    { name: "reuse-media-and-failed-diagnostics", task: task([window("reuse")], { reuse: { media_available: true }, status: "failed" }), transcript: null },
    { name: "same-origin-and-fallback-links", runtime: { api: "", origin: "http://localhost:9010/classic", taskLinks: false },
      task: task([window("local", 0, { grid_url: "http://127.0.0.1:8765/data/synthetic.jpg?a=1&b=2" })], { media_path: "fixture.mp4" }), transcript: null },
    { name: "file-origin-and-relative-links", runtime: { api: "", origin: "file:///synthetic/classic.html" },
      task: task([window("local")]), transcript: null }
  ];
}
