import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeClassList = () => {
  const values = new Set();
  return {
    values,
    add(name) {
      values.add(name);
    },
    remove(name) {
      values.delete(name);
    },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      if (enabled) values.add(name);
      else values.delete(name);
      return enabled;
    },
    contains(name) {
      return values.has(name);
    }
  };
};

const makeElement = () => ({
  listeners: {},
  addEventListener(type, listener) {
    this.listeners[type] = listener;
  },
  classList: makeClassList(),
  style: {},
  dataset: {},
  attributes: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  onclick: null,
  onchange: null,
  files: [],
  scrollCalls: [],
  scrollIntoView(options) {
    this.scrollCalls.push(options || {});
  },
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  },
  getAttribute(name) {
    return this.attributes[name];
  }
});

const resultTabs = ["note", "transcript", "slices", "frames", "qa", "diagnostics"]
  .map(tab => {
    const element = makeElement();
    element.dataset.tab = tab;
    return element;
  });

const documentStub = {
  body: makeElement(),
  createElement() {
    return makeElement();
  },
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll(selector) {
    if (selector === ".result-tab") return resultTabs;
    return [];
  }
};

const context = {
  console,
  document: documentStub,
  location: { href: "http://127.0.0.1:8765/", protocol: "http:", hostname: "127.0.0.1", port: "8765", origin: "http://127.0.0.1:8765" },
  navigator: { clipboard: { writeText() {} } },
  window: {
    innerWidth: 1280,
    location: { origin: "http://127.0.0.1:8765", href: "http://127.0.0.1:8765/", protocol: "http:", hostname: "127.0.0.1", port: "8765", pathname: "/", search: "", hash: "", assignedUrls: [], assign(url) { this.assignedUrls.push(String(url)); } },
    history: {
      replacedUrls: [],
      replaceState(_state, _title, url) {
        this.replacedUrls.push(String(url));
        context.window.location.href = `http://127.0.0.1:8765${url}`;
        const queryIndex = String(url).indexOf("?");
        const hashIndex = String(url).indexOf("#");
        context.window.location.pathname = queryIndex >= 0 ? String(url).slice(0, queryIndex) : String(url);
        context.window.location.search = queryIndex >= 0 ? String(url).slice(queryIndex, hashIndex >= 0 ? hashIndex : undefined) : "";
        context.window.location.hash = hashIndex >= 0 ? String(url).slice(hashIndex) : "";
      }
    },
    localStorage: {
      values: new Map(),
      getItem(key) {
        return this.values.get(key) || null;
      },
      setItem(key, value) {
        this.values.set(key, String(value));
      }
    }
  },
  Blob: class Blob {},
  FormData: class FormData {
    constructor() {
      this.values = new Map();
    }
    append(name, value) {
      this.values.set(name, value);
    }
    get(name) {
      return this.values.get(name);
    }
  },
  URL: class URL {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true, ffprobe: false, ffprobe_optional: true, duration_probe: "ffmpeg", vision_model_configured: false, default_llm_model: "gpt-4.1-mini", default_llm_provider: "openai", default_llm_base_host: "api.openai.com", data_paths: { root: "D:\\Projects\\learnnote-assistant\\data", data_drive: "D:", all_under_data_dir: true, all_on_data_drive: true, paths: { tasks: "D:\\Projects\\learnnote-assistant\\data\\tasks" } } }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
    return { ok: false, json: async () => ({}), text: async () => "" };
  },
  setInterval() {},
  setTimeout,
  clearTimeout
};
context.window.document = context.document;
context.window.navigator = context.navigator;

vm.createContext(context);
context.window.localStorage.setItem("learnnote_model_settings", JSON.stringify({
  llm_provider: "openrouter",
  llm_model: "openai/gpt-4.1-mini",
  llm_base_url: "https://openrouter.ai/api/v1",
  transcriber: "faster-whisper",
  whisper_model: "small"
}));
const webCode = await readFile(new URL("../app.js", import.meta.url), "utf8");
const indexHtml = await readFile(new URL("../index.html", import.meta.url), "utf8");
const stylesCss = await readFile(new URL("../styles.css", import.meta.url), "utf8");
vm.runInContext(webCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
await new Promise(resolve => setTimeout(resolve, 0));
assert.match(elements.get("#health").textContent, /ffprobe/);
assert.equal(context.normalizeApiBase(" http://127.0.0.1:8765/ "), "http://127.0.0.1:8765");
assert.equal(context.normalizeApiBase("https://example.com"), "");
assert.equal(context.resolveApiBase({ protocol: "http:", hostname: "127.0.0.1", port: "8765" }, null), "");
assert.equal(context.resolveApiBase({ protocol: "http:", hostname: "127.0.0.1", port: "8766" }, null), "");
assert.equal(context.resolveApiBase({ protocol: "file:", hostname: "", port: "" }, null), "http://127.0.0.1:8765");
assert.equal(context.resolveApiBase(
  { protocol: "http:", hostname: "127.0.0.1", port: "8878" },
  { getItem: () => "http://localhost:9000/" }
), "http://localhost:9000");
assert.equal(context.safeNoteMediaUrl("/api/tasks/task-web/assets/grid_001.jpg"), "/api/tasks/task-web/assets/grid_001.jpg");
vm.runInContext(`API = "http://127.0.0.1:8766";`, context);
assert.equal(context.safeNoteMediaUrl("/api/tasks/task-web/assets/grid_001.jpg"), "http://127.0.0.1:8766/api/tasks/task-web/assets/grid_001.jpg");
assert.equal(context.safeNoteMediaUrl("http://127.0.0.1:8765/api/tasks/task-web/assets/grid_001.jpg"), "http://127.0.0.1:8766/api/tasks/task-web/assets/grid_001.jpg");
assert.equal(context.safeNoteMediaUrl("https://cdn.example.com/image.jpg"), "https://cdn.example.com/image.jpg");
assert.equal(context.safeNoteMediaUrl("javascript:alert(1)"), "");
vm.runInContext(`API = "";`, context);
assert.equal(context.displayTaskTitle({
  id: "bad-title",
  title: "?????????",
  source_type: "current_page",
  selected_resource: { kind: "hls" }
}), "当前页直取 · HLS");
assert.equal(context.preferredInitialTask([
  { id: "latest-failed", status: "failed", title: "?????????", source_type: "current_page" },
  { id: "usable-success", status: "success", title: "Usable lesson", source_type: "local", note_path: "note.md" }
]).id, "usable-success");
assert.equal(context.preferredInitialTask([
  { id: "plain-success", status: "success", source_type: "current_page" },
  { id: "reuse-media-success", status: "success", source_type: "current_page", reuse: { media_available: true } }
]).id, "reuse-media-success");
assert.equal(context.preferredInitialTask([
  { id: "running-now", status: "running", source_type: "current_page" },
  { id: "usable-success", status: "success", source_type: "local", note_path: "note.md" }
]).id, "running-now");
assert.equal(context.preferredInitialTask([
  { id: "stale-queued", status: "queued", source_type: "page_text" },
  { id: "usable-success", status: "success", source_type: "local", note_path: "note.md" }
]).id, "usable-success");
assert.equal(context.currentPageDisplayTask([
  { id: "latest-failed", status: "failed", source_type: "current_page", error_code: "download_forbidden" },
  { id: "usable-current", status: "success", source_type: "current_page", media_path: "media.mp4", note_path: "note.md" }
]).id, "usable-current");
assert.equal(context.currentPageDisplayTask([
  { id: "plain-current", status: "success", source_type: "current_page" },
  { id: "reuse-current", status: "success", source_type: "current_page", reuse: { media_available: true } }
]).id, "reuse-current");
assert.equal(context.currentPageDisplayTask([
  { id: "manual-url", status: "success", source_type: "current_page", media_path: "media.mp4", selected_resource: { source: "manual", request_type: "manual-forced" } },
  { id: "browser-current", status: "success", source_type: "current_page", media_path: "media.mp4", note_path: "note.md", selected_resource: { source: "webRequest" } }
]).id, "browser-current");
vm.runInContext(`tasks = ${JSON.stringify([
  { id: "latest-local", status: "success", source_type: "local", note_path: "note.md" },
  { id: "selected-local", status: "failed", source_type: "local", error_code: "processing_failed" },
  { id: "latest-url", status: "success", source_type: "current_page", selected_resource: { source: "manual", request_type: "manual-forced" }, note_path: "note.md" },
  { id: "selected-url", status: "running", source_type: "current_page", selected_resource: { source: "manual", request_type: "manual-forced" }, progress: 12 },
  { id: "browser-current", status: "success", source_type: "current_page", selected_resource: { source: "webRequest" }, note_path: "note.md" }
])}; selectedTaskId = "selected-local";`, context);
assert.equal(context.workflowTaskForSource("local").id, "selected-local");
assert.equal(context.workflowTaskForSource("url").id, "selected-url");
assert.equal(context.workflowTaskForSource("browser").id, "browser-current");
vm.runInContext(`selectedTaskId = "selected-url";`, context);
assert.equal(context.workflowTaskForSource("url").id, "selected-url");
vm.runInContext(`tasks = []; selectedTaskId = "";`, context);
assert.equal(context.directRouteState({ status: "success", reuse: { media_available: true } }), "downloaded");
assert.equal(context.workflowActiveIndex({ status: "failed", reuse: { transcript_ready: true } }), 3);
assert.deepEqual(context.sortedVisibleTasks([
  { id: "latest-failed", status: "failed", source_type: "current_page" },
  { id: "stale-queued", status: "queued", source_type: "page_text" },
  { id: "older-success", status: "success", source_type: "local", note_path: "note.md" },
  { id: "selected-success", status: "success", source_type: "local", note_path: "note.md" }
], "selected-success").map(task => task.id), ["selected-success", "older-success", "stale-queued", "latest-failed"]);
assert.match(stylesCss, /@media \(max-width: 900px\)[\s\S]*body\s*\{[\s\S]*min-width:\s*0;[\s\S]*overflow-x:\s*hidden;/);
assert.match(stylesCss, /@media \(max-width: 900px\)[\s\S]*\.app-shell,[\s\S]*max-width:\s*100vw;/);
assert.match(stylesCss, /\.recovery-decision\s*\{/);
assert.match(stylesCss, /\.recovery-decision-metrics\s*\{/);
assert.match(stylesCss, /@media \(max-width: 900px\)[\s\S]*\.recovery-decision\s*\{[\s\S]*grid-template-columns:\s*1fr;/);
assert.equal(elements.get("#browserBridgeStatus").classList.contains("capture-status-grid"), true);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip bridge/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /需 Chrome\/Edge 扩展侧栏/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip media/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip direct/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /mp4\/mkv\/webm\/flv\/m3u8\/mpd/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /不录制 · 不绕过 DRM · 不刷课/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /待填 · OpenRouter/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip asr/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /转写/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /本地 faster-whisper · small/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip data ready/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /D: · data/);
assert.match(elements.get("#detail").innerHTML, /class="empty-workbench"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-demo-board"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-route-grid"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-production-brief"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-readiness-panel"/);
assert.match(elements.get("#detail").innerHTML, /data-empty-readiness/);
assert.match(elements.get("#detail").innerHTML, /Markdown · 诊断 · 资料包/);
assert.match(elements.get("#detail").innerHTML, /后端媒体检查/);
assert.match(elements.get("#detail").innerHTML, /视觉总结检查/);
assert.match(elements.get("#detail").innerHTML, /本地视频检查/);
assert.match(elements.get("#detail").innerHTML, /当前页直取检查/);
assert.match(elements.get("#detail").innerHTML, /DOM \+ Performance \+ webRequest \+ yt-dlp/);
assert.match(elements.get("#detail").innerHTML, /mp4\/mkv\/webm\/flv\/m3u8\/mpd 可上传/);
assert.match(elements.get("#detail").innerHTML, /复制后端地址/);
assert.match(elements.get("#detail").innerHTML, /当前页直取/);
assert.match(elements.get("#detail").innerHTML, /打开当前页路线/);
assert.match(elements.get("#detail").innerHTML, /选择本地视频/);
assert.match(elements.get("#detail").innerHTML, /粘贴链接/);
assert.match(elements.get("#detail").innerHTML, /直取候选 · HLS/);
assert.match(elements.get("#detail").innerHTML, /浏览器字幕和转写片段会按视觉窗口对齐/);
assert.match(elements.get("#detail").innerHTML, /不.*录制页面/);
assert.equal(elements.get("#copyButton").disabled, true);
assert.equal(elements.get("#visualWindowsButton").disabled, true);
assert.equal(elements.get("#manifestButton").disabled, true);
assert.equal(elements.get("#subtitlesButton").disabled, true);
assert.match(elements.get("#sourceWorkflow").innerHTML, /class="source-workflow-card browser"/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /class="source-workflow-status"/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /学习生产线|当前页直取/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /读取当前页/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /预检资源/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /<span>入口<\/span>/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /当前页直取/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /待候选/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /20秒 · 3x3/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /非录制/);
assert.match(elements.get("#sourceRouteRail").innerHTML, /class="source-route-item idle selected"/);
assert.match(elements.get("#sourceRouteRail").innerHTML, /浏览器直取/);
assert.match(elements.get("#sourceRouteRail").innerHTML, /本地视频/);
assert.match(elements.get("#sourceRouteRail").innerHTML, /链接解析/);
assert.match(stylesCss, /\.source-route-rail\s*\{/);
assert.match(stylesCss, /\.source-route-item\.blocked\s*\{/);
assert.match(stylesCss, /cockpit polish/);
assert.match(stylesCss, /\.workspace-panel \.source-route-rail\s*\{\s*display: none;/);
assert.match(stylesCss, /\.capture-flow\s*\{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(indexHtml, /id="toggleWorkspaceButton"/);
assert.match(indexHtml, /styles\.css\?v=20260704-cockpit-polish/);
assert.match(indexHtml, /app\.js\?v=20260704-reuse-ui/);
assert.match(indexHtml, /id="sourceRouteRail"/);
assert.match(indexHtml, /id="urlPreflightReport"/);
assert.match(indexHtml, /href="#optionsDisclosure" title="模板"/);
assert.doesNotMatch(indexHtml, /href="#settings" title="模板"/);
assert.match(indexHtml, /id="downloadUrlButton"[\s\S]*只下载到本地/);
assert.doesNotMatch(indexHtml, />只下载本地</);
assert.match(indexHtml, /class="result-tab active" role="tab" aria-selected="true" data-tab="note"/);
assert.match(indexHtml, /class="result-tab" role="tab" aria-selected="false" data-tab="qa">问答/);
assert.match(indexHtml, /class="result-tab" role="tab" aria-selected="false" data-tab="diagnostics">下载诊断/);
assert.match(indexHtml, /id="llmProvider"/);
assert.match(indexHtml, /value="gemini">Google Gemini/);
assert.match(indexHtml, /value="dashscope">/);
assert.match(indexHtml, /value="siliconflow">SiliconFlow/);
assert.equal(elements.get("#llmProvider").value, "openrouter");
assert.equal(elements.get("#llmModel").value, "openai/gpt-4.1-mini");
assert.equal(elements.get("#llmBaseUrl").value, "https://openrouter.ai/api/v1");
assert.equal(elements.get("#transcriber").value, "faster-whisper");
assert.equal(elements.get("#whisperModel").value, "small");
elements.get("#llmProvider").value = "gemini";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://generativelanguage.googleapis.com/v1beta/openai/");
assert.equal(elements.get("#llmModel").value, "gemini-3.5-flash");
assert.equal(elements.get("#transcriber").value, "faster-whisper");
assert.equal(elements.get("#whisperModel").value, "small");
assert.equal(context.healthVisionProvider({}), "Gemini");
context.updateHealthVisionStatus({ ffmpeg: true, ffprobe_optional: true, vision_model_configured: false });
assert.match(elements.get("#browserBridgeStatus").innerHTML, /待填 · Gemini/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /本地 faster-whisper · small/);
elements.get("#llmProvider").value = "dashscope";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://dashscope.aliyuncs.com/compatible-mode/v1");
assert.equal(elements.get("#llmModel").value, "qwen-vl-max");
assert.equal(context.healthVisionProvider({}), "DashScope");
elements.get("#llmProvider").value = "siliconflow";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.siliconflow.cn/v1");
assert.equal(elements.get("#llmModel").value, "Qwen/Qwen2.5-VL-72B-Instruct");
assert.equal(context.healthVisionProvider({}), "SiliconFlow");
elements.get("#llmProvider").value = "local-openai";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "http://127.0.0.1:11434/v1");
assert.equal(elements.get("#llmModel").value, "qwen2.5vl:7b");
assert.equal(context.healthVisionProvider({}), "Local");
elements.get("#llmProvider").value = "openrouter";
context.applyModelProviderPreset(true);
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), false);
elements.get("#toggleWorkspaceButton").onclick();
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), true);
assert.equal(elements.get("#toggleWorkspaceButton").getAttribute("aria-pressed"), "true");
assert.equal(context.window.localStorage.getItem("learnnote.workspaceCollapsed"), "1");
elements.get("#toggleWorkspaceButton").onclick();
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), false);
assert.equal(elements.get("#toggleWorkspaceButton").getAttribute("aria-pressed"), "false");
context.window.localStorage.setItem("learnnote.workspaceCollapsed", "1");
context.window.localStorage.setItem("learnnote.historyCollapsed", "1");
context.window.localStorage.setItem("learnnote.readingMode", "1");
context.window.location.href = "http://127.0.0.1:8765/";
context.window.location.search = "";
context.initializeWorkspaceView();
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), false);
assert.equal(documentStub.body.classList.contains("queue-collapsed"), false);
assert.equal(documentStub.body.classList.contains("reading-mode"), false);
context.window.location.href = "http://127.0.0.1:8765/?task=existing&tab=note";
context.window.location.search = "?task=existing&tab=note";
context.initializeWorkspaceView();
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), true);
assert.equal(documentStub.body.classList.contains("queue-collapsed"), true);
assert.equal(documentStub.body.classList.contains("reading-mode"), true);
context.window.location.href = "http://127.0.0.1:8765/";
context.window.location.search = "";
context.window.localStorage.setItem("learnnote.workspaceCollapsed", "0");
context.window.localStorage.setItem("learnnote.historyCollapsed", "0");
context.window.localStorage.setItem("learnnote.readingMode", "0");
context.initializeWorkspaceView();
assert.match(indexHtml, /class="browser-capture-card"/);
assert.match(indexHtml, /class="capture-flow"/);
assert.match(indexHtml, /非录制/);
assert.match(indexHtml, /预检候选/);
assert.match(indexHtml, /本地总结/);
assert.match(indexHtml, /id="browserRouteSummary"/);
assert.match(indexHtml, /id="visualWindowsButton"/);
assert.match(indexHtml, /id="manifestButton"/);
assert.match(indexHtml, /id="subtitlesButton"/);
assert.match(indexHtml, /title="导出字幕"/);
assert.match(indexHtml, /id="resultMoreActions"/);
assert.match(indexHtml, /class="result-more-panel"/);
assert.match(indexHtml, /data-tab="slices">学习切片/);
assert.ok(
  indexHtml.indexOf('id="browserRouteSummary"') < indexHtml.indexOf('id="sourceWorkflow"'),
  "current-page route summary should appear before the workflow explainer"
);
assert.match(indexHtml, /当前页直取状态/);
assert.match(indexHtml, /当前页交接流程/);
assert.match(indexHtml, /Blob\/MSE 来源映射/);
assert.equal(context.resourceSourceText({ source: "iframeHint" }), "iframe 内播放器线索");
assert.equal(context.resourceSourceText({ source: "scriptHint" }), "页面脚本线索");
assert.equal(context.resourceSourceText({ source: "domHint" }), "页面元素线索");
assert.equal(context.resourceSourceText({ source: "locationHint" }), "页面 URL 线索");

const browserWorkflowStatusHtml = context.sourceWorkflowStatusHtml("browser", {
  id: "workflow-current",
  status: "success",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/workflow-current/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/workflow-current/note.md",
  selected_resource: { kind: "hls", source: "webRequest" },
  visual_windows: [{ id: "W001", start: 0, end: 180, frame_count: 9 }]
});
assert.match(browserWorkflowStatusHtml, /class="source-workflow-status"/);
assert.match(browserWorkflowStatusHtml, /hls · 浏览器请求/);
assert.match(browserWorkflowStatusHtml, /media\.mp4/);
assert.match(browserWorkflowStatusHtml, /1 个视觉窗口/);
assert.match(browserWorkflowStatusHtml, /不可还原 blob、DRM 或签名过期时切到本地视频/);
assert.doesNotMatch(browserWorkflowStatusHtml, /<script>/);

const localWorkflowStatusHtml = context.sourceWorkflowStatusHtml("local");
assert.match(localWorkflowStatusHtml, /本地视频/);
assert.match(localWorkflowStatusHtml, /待上传/);
assert.match(localWorkflowStatusHtml, /离线管线/);

const readyGateHtml = context.emptyReadinessGatesHtml({
  ffmpeg: true,
  ffprobe_optional: false,
  vision_model_configured: true,
  default_llm_model: "gpt-4.1-mini",
  default_llm_provider: "openai"
});
assert.match(readyGateHtml, /class="empty-readiness-gates"/);
assert.match(readyGateHtml, /section class="pass"/);
assert.match(readyGateHtml, /直取\/切片就绪/);
assert.match(readyGateHtml, /OpenRouter · openai\/gpt-4\.1-mini/);
assert.doesNotMatch(readyGateHtml, /<script>bad/);

const blockedGateHtml = context.emptyReadinessGatesHtml({
  ffmpeg: false,
  vision_model_configured: false,
  default_llm_provider: "openai"
});
assert.match(blockedGateHtml, /section class="block"/);
assert.match(blockedGateHtml, /后端未就绪/);
assert.match(blockedGateHtml, /待填 · OpenRouter/);
assert.match(indexHtml, /accept="video\/\*,\.mp4,\.m4v,\.mov,\.mkv,\.webm,\.flv,\.avi"/);
assert.match(indexHtml, /data-tab="frames">画面网格/);
const qaPanelInitialHtml = context.qaPanelHtml({ id: "task-qa-test" });
assert.match(qaPanelInitialHtml, /id="qaForm"/);
assert.match(qaPanelInitialHtml, /id="qaQuestion"/);
assert.match(qaPanelInitialHtml, /基于当前任务的笔记、字幕和画面索引回答/);
assert.match(qaPanelInitialHtml, /已保存 0 条问答/);
const qaPanelSuggestionHtml = context.qaPanelHtml({
  id: "task-qa-suggestions",
  qa: {
    suggestions: [
      { label: "核心概念", question: "这节课最重要的 3 个概念是什么？", source: "note" },
      { label: "画面线索", question: "哪些演示步骤最值得回看？", source: "visual" }
    ]
  }
});
assert.match(qaPanelSuggestionHtml, /class="qa-suggestions"/);
assert.match(qaPanelSuggestionHtml, /data-qa-suggestion=/);
assert.match(qaPanelSuggestionHtml, /核心概念/);
assert.match(qaPanelSuggestionHtml, /哪些演示步骤最值得回看/);
const qaPanelHistoryHtml = context.qaPanelHtml({ id: "task-qa-history", qa: { history_count: 2 } });
assert.match(qaPanelHistoryHtml, /已保存 2 条问答/);
assert.match(qaPanelHistoryHtml, /\/api\/tasks\/task-qa-history\/exports\/qa/);
const qaPanelRecentHtml = context.qaPanelHtml({
  id: "task-qa-recent",
  qa: {
    history_count: 1,
    recent: [{ question: "如何复习函数封装？", answer_excerpt: "先看输入输出，再看边界条件。", source: "local-extractive", citation_count: 2 }]
  }
});
assert.match(qaPanelRecentHtml, /class="qa-recent"/);
assert.match(qaPanelRecentHtml, /如何复习函数封装/);
assert.match(qaPanelRecentHtml, /先看输入输出/);
assert.match(qaPanelRecentHtml, /2 证据/);
context.window.location.search = "?task=task%20from%20url";
assert.equal(context.taskIdFromCurrentUrl(), "task from url");
context.window.location.search = "?result_tab=frames";
assert.equal(context.resultTabFromCurrentUrl(), "frames");
context.window.location.search = "?result_tab=slices";
assert.equal(context.resultTabFromCurrentUrl(), "slices");
context.window.location.search = "?tab=unknown";
assert.equal(context.resultTabFromCurrentUrl(), "note");
context.window.location.search = "";
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.mkv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.flv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.avi", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "bad.txt", type: "text/plain" }), false);

const routeSummaryHtml = context.browserRouteSummaryHtml({
  id: "task-route-summary",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-route-summary/media.mp4",
  note_path: "",
  selected_resource: {
    kind: "hls"
  },
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: [
    { id: "W001", start: 0, end: 180 },
    { id: "W002", start: 180, end: 360 }
  ]
});

assert.match(routeSummaryHtml, /class="browser-route-summary-card downloaded"/);
assert.match(routeSummaryHtml, /视频已直取到本地/);
assert.match(routeSummaryHtml, /继续切片总结/);
assert.match(routeSummaryHtml, /data-select-browser-task="task-route-summary"/);
assert.match(routeSummaryHtml, /data-rerun-browser-task="task-route-summary"/);
assert.match(routeSummaryHtml, /data-browser-route-action="refresh"/);
assert.match(routeSummaryHtml, /data-browser-route-action="copy-backend"/);
assert.match(routeSummaryHtml, /\/api\/tasks\/task-route-summary\/exports\/media/);
assert.match(routeSummaryHtml, /\/api\/tasks\/task-route-summary\/exports\/diagnostics/);
assert.match(routeSummaryHtml, /class="browser-bridge-gate"/);
assert.match(routeSummaryHtml, /扩展侧栏交接门/);
assert.match(routeSummaryHtml, /读取当前播放页只能从 Chrome\/Edge 扩展发起/);
assert.match(routeSummaryHtml, /已交接/);
assert.match(routeSummaryHtml, /已记录/);
assert.match(routeSummaryHtml, /class="browser-route-handoff"/);
assert.match(routeSummaryHtml, /资源证据/);
assert.match(routeSummaryHtml, /本地落地/);
assert.match(routeSummaryHtml, /学习笔记/);
assert.match(routeSummaryHtml, /视觉窗口/);
assert.doesNotMatch(routeSummaryHtml, /<script>bad/);

const queueChipTask = {
  id: "queue-chip-task",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/queue-chip-task/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/queue-chip-task/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/queue-chip-task/note.md",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    playback_match: "exact-src"
  },
  visual_windows: [{ id: "W001", start: 0, end: 180 }],
  download_attempts: [{ strategy: "direct-file" }, { strategy: "page-ytdlp" }]
};

assert.equal(JSON.stringify(context.taskChipItems(queueChipTask)), JSON.stringify(["当前 src", "视频", "media.mp4", "笔记", "1 窗口"]));
assert.equal(context.taskMetaLine(queueChipTask), "直取 · 视频");
const queueHandoffHtml = context.taskHandoffHtml(queueChipTask);
assert.match(queueHandoffHtml, /class="task-handoff done"/);
assert.match(queueHandoffHtml, /学习接力/);
assert.match(queueHandoffHtml, /来源<\/b>直取 · 视频/);
assert.match(queueHandoffHtml, /媒体<\/b>media\.mp4 已保存/);
assert.match(queueHandoffHtml, /切片<\/b>1 个切片窗口/);
assert.match(queueHandoffHtml, /动作<\/b>下一步：核对画面笔记/);
assert.doesNotMatch(queueHandoffHtml, /<script>/);
const queueAuditMiniHtml = context.taskAuditMiniHtml(queueChipTask);
assert.match(queueAuditMiniHtml, /class="task-audit-mini"/);
assert.match(queueAuditMiniHtml, /任务检查/);
assert.match(queueAuditMiniHtml, /来源/);
assert.match(queueAuditMiniHtml, /媒体/);
assert.match(queueAuditMiniHtml, /字幕/);
assert.match(queueAuditMiniHtml, /切片/);
assert.match(queueAuditMiniHtml, /总结/);
assert.match(queueAuditMiniHtml, /5\/5 已放行/);

const resultMetaHtml = context.resultMetaChipsHtml({
  ...queueChipTask,
  title: "<script>bad()</script> 课程",
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3,
    transcriber: "faster-whisper",
    whisper_model: "small",
    note_style: "study",
    note_template: "visual-handout",
    visual_understanding: true
  },
  summary_source: "vision-llm"
});
assert.match(resultMetaHtml, /class="result-meta-chips"/);
assert.match(resultMetaHtml, /任务阶段摘要/);
assert.match(resultMetaHtml, /已完成/);
assert.match(resultMetaHtml, /直取 · 视频/);
assert.match(resultMetaHtml, /媒体<\/b>已保存/);
assert.match(resultMetaHtml, /字幕<\/b>已生成/);
assert.match(resultMetaHtml, /切片<\/b>1 窗口/);
assert.match(resultMetaHtml, /笔记<\/b>vision-llm/);
assert.match(resultMetaHtml, /导出<\/b>可导出/);
assert.match(resultMetaHtml, /20 秒切片/);
assert.match(resultMetaHtml, /visual-handout/);
assert.doesNotMatch(resultMetaHtml, /<script>bad/);
assert.match(stylesCss, /\.result-meta-chips[\s\S]*flex-wrap:\s*wrap/);
assert.match(stylesCss, /\.result-meta-chips \.success,[\s\S]*\.result-meta-chips \.pass/);

const blockedAuditMiniHtml = context.taskAuditMiniHtml({
  id: "blocked-audit-mini",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  error_code: "download_forbidden",
  selected_resource: { kind: "hls", source: "webRequest" },
  audit: {
    gates: [
      { key: "source", state: "pass", value: "browser candidate", detail: "webRequest HLS" },
      { key: "media", state: "fail", value: "403 forbidden", detail: "cookie expired" }
    ]
  }
});
assert.match(blockedAuditMiniHtml, /class="fail"/);
assert.match(blockedAuditMiniHtml, /媒体检查 · 403 forbidden/);
assert.match(blockedAuditMiniHtml, /cookie expired/);

const reusableHandoffHtml = context.taskHandoffHtml({
  id: "downloaded-media",
  status: "success",
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/downloaded-media/media.mp4",
  note_path: "",
  selected_resource: { kind: "hls", source: "webRequest" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.match(reusableHandoffHtml, /class="task-handoff ready"/);
assert.match(reusableHandoffHtml, /动作<\/b>下一步：继续切片总结/);
assert.match(reusableHandoffHtml, /媒体<\/b>media\.mp4 已保存/);

const failedHandoffHtml = context.taskHandoffHtml({
  id: "failed-route",
  status: "failed",
  source_type: "current_page",
  error_code: "download_forbidden",
  recovery: { primary_action: { key: "local_upload", label: "上传本地视频" } },
  selected_resource: { kind: "hls", source: "webRequest" },
  download_attempts: [{ strategy: "manifest-ffmpeg", status: "failed" }]
});
assert.match(failedHandoffHtml, /class="task-handoff blocked"/);
assert.match(failedHandoffHtml, /媒体<\/b>1 次下载尝试/);
assert.match(failedHandoffHtml, /动作<\/b>下一步：上传本地视频/);
assert.match(stylesCss, /\.task-handoff[\s\S]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/);

const visionEvidenceHtml = context.visionEvidenceBar({
  id: "vision-task",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/vision-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/vision-task/note.md",
  summary_source: "vision-llm",
  summary_diagnostics: {
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 2,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"],
    summary_warning: "<script>bad()</script> warning"
  },
  visual_windows: [
    { id: "W001", start: 0, end: 180, grid_url: "/api/tasks/vision-task/grids/grid_001.jpg" },
    { id: "W002", start: 180, end: 360, grid_url: "" }
  ]
});

assert.match(visionEvidenceHtml, /class="vision-evidence strong"/);
assert.match(visionEvidenceHtml, /画面已参与图文总结/);
assert.match(visionEvidenceHtml, /2\/3/);
assert.match(visionEvidenceHtml, /缺图 W002/);
assert.match(visionEvidenceHtml, /超限省略 W099/);
assert.match(visionEvidenceHtml, /data-switch-result-tab="frames"/);
assert.match(visionEvidenceHtml, /data-switch-result-tab="diagnostics"/);
assert.match(visionEvidenceHtml, /\/api\/tasks\/vision-task\/exports\/bundle/);
assert.match(visionEvidenceHtml, /\/api\/tasks\/vision-task\/exports\/manifest/);
assert.match(visionEvidenceHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; warning/);
assert.doesNotMatch(visionEvidenceHtml, /<script>bad/);

const blockedRouteSummaryHtml = context.browserRouteSummaryHtml({
  id: "task-route-blocked",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  error_detail: "<script>bad()</script> DRM"
});

assert.match(blockedRouteSummaryHtml, /class="browser-route-summary-card blocked"/);
assert.match(blockedRouteSummaryHtml, /不可直取/);
assert.match(blockedRouteSummaryHtml, /data-browser-route-action="local-video"/);
assert.match(blockedRouteSummaryHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; DRM/);
assert.doesNotMatch(blockedRouteSummaryHtml, /导出本地视频/);
assert.doesNotMatch(blockedRouteSummaryHtml, /<script>bad/);

const emptyBrowserGateHtml = context.browserRouteSummaryHtml(null);
assert.match(emptyBrowserGateHtml, /class="browser-bridge-gate"/);
assert.match(emptyBrowserGateHtml, /必须从课程页打开/);
assert.match(emptyBrowserGateHtml, /Web 工作台不能直接读取你正在播放的 Chrome 标签页/);
assert.match(emptyBrowserGateHtml, /等待侧栏读取/);
assert.match(emptyBrowserGateHtml, /等待任务/);
const emptyBrowserHandoffHtml = context.browserRouteEmptyHandoffHtml();
assert.match(emptyBrowserHandoffHtml, /browser-route-summary-card handoff empty/);
assert.match(emptyBrowserHandoffHtml, /当前页直取需要从扩展侧栏开始/);
assert.match(emptyBrowserHandoffHtml, /class="browser-extension-handoff"/);
assert.match(emptyBrowserHandoffHtml, /打开课程播放页/);
assert.match(emptyBrowserHandoffHtml, /打开扩展侧栏/);
assert.match(emptyBrowserHandoffHtml, /总结当前视频/);
assert.match(emptyBrowserHandoffHtml, /回到工作台/);
assert.match(emptyBrowserHandoffHtml, /抽帧切片/);
assert.match(emptyBrowserHandoffHtml, /当前页直取交接清单/);
assert.match(emptyBrowserHandoffHtml, /不做标签页录制/);
assert.match(emptyBrowserHandoffHtml, /data-browser-route-action="local-video"/);

const extensionHandoffHtml = context.browserExtensionHandoffHtml("http://127.0.0.1:8765");
assert.match(extensionHandoffHtml, /后端 http:\/\/127\.0\.0\.1:8765 已复制/);
assert.match(extensionHandoffHtml, /Chrome\/Edge 侧栏点击“总结当前视频”/);
assert.doesNotMatch(extensionHandoffHtml, /<script>/);

const extensionStatusHtml = context.browserExtensionHandoffStatusHtml("http://127.0.0.1:8765");
assert.match(extensionStatusHtml, /capture-status-chip bridge handoff/);
assert.match(extensionStatusHtml, /http:\/\/127\.0\.0\.1:8765 已复制/);
assert.match(extensionStatusHtml, /播放几秒后打开扩展侧栏/);
assert.match(extensionStatusHtml, /等待任务、切片和笔记/);

const html = context.markdownToHtml(`## 画面索引

![W001](http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg)
![bad](javascript:alert(1))
`);

assert.match(html, /<h2 id="note-画面索引">画面索引<\/h2>/);
assert.match(html, /<figure class="note-image-frame">/);
assert.match(html, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(html, /src="javascript:alert/);

const outlineHtml = context.noteOutline(`# Smoke Current Page Video

## 画面索引
### **重点** 片段
## 画面索引
\`\`\`
## 不应进入目录
\`\`\`
`);

assert.match(outlineHtml, /class="note-outline"/);
assert.match(outlineHtml, /href="#note-smoke-current-page-video"/);
assert.match(outlineHtml, /href="#note-画面索引"/);
assert.match(outlineHtml, /href="#note-画面索引-2"/);
assert.match(outlineHtml, /重点 片段/);
assert.doesNotMatch(outlineHtml, /不应进入目录/);

const resultPanel = elements.get(".result-panel") || documentStub.querySelector(".result-panel");
context.window.innerWidth = 1280;
context.focusResultPanelOnMobile();
assert.equal(resultPanel.scrollCalls.length, 0);

context.window.innerWidth = 390;
context.focusResultPanelOnMobile();
assert.equal(resultPanel.scrollCalls.length, 1);
assert.equal(resultPanel.scrollCalls[0].block, "start");

context.setHistoryCollapsed(true);
assert.equal(documentStub.body.classList.contains("queue-collapsed"), true);
assert.equal(elements.get("#toggleHistoryButton").getAttribute("aria-pressed"), "true");
assert.equal(context.window.localStorage.getItem("learnnote.historyCollapsed"), "1");

context.setReadingMode(true);
assert.equal(documentStub.body.classList.contains("reading-mode"), true);
assert.equal(elements.get("#readingModeButton").getAttribute("aria-pressed"), "true");
assert.equal(context.window.localStorage.getItem("learnnote.readingMode"), "1");

const railHtml = context.visualRail({
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: "<script>alert(1)</script> 课程演示"
  }]
});

assert.match(railHtml, /class="visual-rail"/);
assert.match(railHtml, /W001/);
assert.match(railHtml, /00:00:00 - 00:03:00/);
assert.match(railHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(railHtml, /<script>/);
assert.match(railHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);

const readingRailHtml = context.readingRail("## 第一节", {
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 30,
    frame_count: 3,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: ""
  }]
});

assert.match(readingRailHtml, /class="reading-rail"/);
assert.match(readingRailHtml, /class="reading-progress-rail"/);
assert.match(readingRailHtml, /class="note-outline"/);
assert.match(readingRailHtml, /class="visual-rail"/);
assert.match(readingRailHtml, /class="reading-actions-rail"/);
assert.match(readingRailHtml, /读笔记/);
assert.match(readingRailHtml, /看画面/);

const richReadingRailHtml = context.readingRail(`# 课程笔记

## 第一节
### 例题
`, {
  id: "task-reading-rail",
  status: "success",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-reading-rail/media.mp4",
  subtitle_path: "D:/Projects/learnnote-assistant/data/tasks/task-reading-rail/browser_subtitles.srt",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-reading-rail/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-reading-rail/note.md",
  selected_resource: { kind: "hls", source: "webRequest" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: "重点演示"
  }]
});
assert.match(richReadingRailHtml, /学习进度/);
assert.match(richReadingRailHtml, /3 标题/);
assert.match(richReadingRailHtml, /1 章节 · 1 小节/);
assert.match(richReadingRailHtml, /1 窗口/);
assert.match(richReadingRailHtml, /class="reading-artifacts-rail"/);
assert.match(richReadingRailHtml, /Markdown/);
assert.match(richReadingRailHtml, /字幕文件/);
assert.match(richReadingRailHtml, /media\.mp4/);
assert.match(richReadingRailHtml, /切片索引/);
assert.match(richReadingRailHtml, /资料包/);
assert.match(richReadingRailHtml, /\/api\/tasks\/task-reading-rail\/exports\/bundle/);
assert.match(richReadingRailHtml, /\/api\/tasks\/task-reading-rail\/exports\/subtitles/);
assert.match(richReadingRailHtml, /data-switch-result-tab="transcript"/);
assert.match(richReadingRailHtml, /data-switch-result-tab="diagnostics"/);

const reuseReadingRailHtml = context.readingRail("## Reuse", {
  id: "task-reuse-rail",
  status: "success",
  source_type: "current_page",
  reuse: {
    media_available: true,
    subtitle_available: true,
    transcript_ready: true,
    rerun_from_media_ready: true
  }
});
assert.match(reuseReadingRailHtml, /data-switch-result-tab="transcript"/);
assert.match(reuseReadingRailHtml, /\/api\/tasks\/task-reuse-rail\/exports\/subtitles/);
assert.match(reuseReadingRailHtml, /\/api\/tasks\/task-reuse-rail\/exports\/media/);
assert.match(reuseReadingRailHtml, /data-rerun-from-media="task-reuse-rail"/);

const visualDeckHtml = context.visualStudyDeck({
  id: "task-visual-deck",
  title: "<script>bad()</script> 视觉课程",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  summary_diagnostics: {
    vision_image_window_ids: ["W001"],
    missing_vision_image_window_ids: ["W002"]
  },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      frame_timestamps: [0, 20, 40, 60, 80],
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: "<script>alert(1)</script> PPT 演示"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: "javascript:alert(1)",
      transcript_excerpt: ""
    }
  ]
});
assert.match(visualDeckHtml, /class="visual-study-deck"/);
assert.match(visualDeckHtml, /visual-study-card vision/);
assert.match(visualDeckHtml, /visual-study-card missing/);
assert.match(visualDeckHtml, /visual-study-evidence vision/);
assert.match(visualDeckHtml, /visual-study-evidence missing/);
assert.match(visualDeckHtml, /已进视觉 · 网格图已参与图文总结/);
assert.match(visualDeckHtml, /缺图 · 未送入视觉模型，按字幕与索引复习/);
assert.match(visualDeckHtml, /视觉窗口复习/);
assert.match(visualDeckHtml, /2 个窗口 · 00:00:00 - 00:06:00/);
assert.match(visualDeckHtml, /导出切片索引/);
assert.match(visualDeckHtml, /\/api\/tasks\/task-visual-deck\/exports\/visual-windows/);
assert.match(visualDeckHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.match(visualDeckHtml, /学习动作/);
assert.match(visualDeckHtml, /复述这一窗口的结论/);
assert.match(visualDeckHtml, /回看检查点/);
assert.match(visualDeckHtml, /00:00:00/);
assert.match(visualDeckHtml, /对照画面确认对应的板书、PPT、代码或操作步骤/);
assert.match(visualDeckHtml, /class="visual-study-questions"/);
assert.match(visualDeckHtml, /自测问题/);
assert.match(visualDeckHtml, /这句“&lt;script&gt;alert\(1\)&lt;\/script&gt; PPT 演示”在画面中对应的标题、公式、代码或操作状态是什么？/);
assert.match(visualDeckHtml, /00:00:00 \/ 00:00:20 \/ 00:00:40 \/ 00:01:00\.\.\./);
assert.doesNotMatch(visualDeckHtml, /src="javascript:alert/);
assert.match(visualDeckHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; PPT 演示/);
assert.match(visualDeckHtml, /data-switch-result-tab="transcript"/);
assert.match(visualDeckHtml, /data-switch-result-tab="note"/);
assert.match(visualDeckHtml, /data-media-seek-time="0\.000"/);
assert.match(visualDeckHtml, /data-window-start="180\.000"/);
assert.match(visualDeckHtml, />回看此段<\/button>/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

const sliceWorkbenchHtml = context.learningSliceWorkbench({
  id: "task-slice-workbench",
  title: "<script>bad()</script> 切片课程",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-slice-workbench/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-slice-workbench/note.md",
  visual_index_path: "D:/Projects/learnnote-assistant/data/tasks/task-slice-workbench/visual_windows.json",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: "PPT 演示"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_001.jpg",
      transcript_excerpt: "代码演示"
    }
  ]
}, {
  segments: [
    { start: 10, end: 18, text: "第一段讲概念" },
    { start: 220, end: 230, text: "第二段讲例题" }
  ]
});
assert.match(sliceWorkbenchHtml, /class="slice-workbench"/);
assert.match(sliceWorkbenchHtml, /学习切片工作台/);
assert.match(sliceWorkbenchHtml, /按视觉窗口把截图网格、同步字幕和回看动作组织在一起/);
assert.match(sliceWorkbenchHtml, /<dt>窗口<\/dt><dd>2<\/dd>/);
assert.match(sliceWorkbenchHtml, /<dt>画面<\/dt><dd>18<\/dd>/);
assert.match(sliceWorkbenchHtml, /<dt>字幕<\/dt><dd>2<\/dd>/);
assert.match(sliceWorkbenchHtml, /00:00:00 - 00:06:00/);
assert.match(sliceWorkbenchHtml, /class="visual-study-navigator"/);
assert.match(sliceWorkbenchHtml, /复习队列/);
assert.match(sliceWorkbenchHtml, /按画面窗口回看/);
assert.match(sliceWorkbenchHtml, /W001/);
assert.match(sliceWorkbenchHtml, /已进视觉|本地索引/);
assert.match(sliceWorkbenchHtml, /9 帧 · 1 字幕/);
assert.match(sliceWorkbenchHtml, /data-media-seek-time="180\.000"/);
assert.match(sliceWorkbenchHtml, /data-switch-result-tab="transcript"/);
assert.match(sliceWorkbenchHtml, /\/api\/tasks\/task-slice-workbench\/exports\/visual-windows/);
assert.match(sliceWorkbenchHtml, /\/api\/tasks\/task-slice-workbench\/exports\/bundle/);
assert.match(sliceWorkbenchHtml, /class="visual-study-deck"/);
assert.match(sliceWorkbenchHtml, /data-media-seek-time="0\.000"/);
assert.doesNotMatch(sliceWorkbenchHtml, /<script>bad/);

const frameWorkbenchHtml = context.visualFrameWorkbench({
  id: "task-frame-workbench",
  title: "<script>bad()</script> 画面课程",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-frame-workbench/media.mp4",
  visual_index_path: "D:/Projects/learnnote-assistant/data/tasks/task-frame-workbench/visual_windows.json",
  options: { grid_columns: 3, grid_rows: 3 },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: "PPT 演示"
    }
  ]
}, {
  segments: [{ start: 10, end: 18, text: "第一段讲概念" }]
});
assert.match(frameWorkbenchHtml, /class="slice-workbench frame-workbench"/);
assert.match(frameWorkbenchHtml, /画面网格复核/);
assert.match(frameWorkbenchHtml, /集中核对每个视觉窗口的截图网格/);
assert.match(frameWorkbenchHtml, /<dt>帧数<\/dt><dd>9<\/dd>/);
assert.match(frameWorkbenchHtml, /<dt>网格<\/dt><dd>3x3<\/dd>/);
assert.match(frameWorkbenchHtml, /data-switch-result-tab="slices"/);
assert.match(frameWorkbenchHtml, /class="visual-study-deck"/);
assert.doesNotMatch(frameWorkbenchHtml, /<script>bad/);

const pendingSliceHtml = context.pendingSliceWorkbench({
  id: "task-pending-slice",
  title: "Downloaded only lesson",
  status: "success",
  phase: "completed",
  mode: "download_only",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-pending-slice/media.mp4",
  download_attempts: [{ strategy: "direct-file", status: "success" }],
  visual_windows: []
});
assert.match(pendingSliceHtml, /class="slice-workbench pending"/);
assert.match(pendingSliceHtml, /视频已直取到本地，可以继续切片总结/);
assert.match(pendingSliceHtml, /不会重新录制页面/);
assert.match(pendingSliceHtml, /data-rerun-from-media="task-pending-slice"/);
assert.match(pendingSliceHtml, /\/api\/tasks\/task-pending-slice\/exports\/media/);
assert.match(pendingSliceHtml, /data-switch-result-tab="diagnostics"/);
assert.match(pendingSliceHtml, /media-preview-card/);

const originalFetchForDownloadNote = context.fetch;
context.fetch = async url => {
  const value = String(url);
  if (value.endsWith("/api/tasks/task-note-download-only")) {
    return {
      json: async () => ({
        task: {
          id: "task-note-download-only",
          title: "Downloaded only note",
          status: "success",
          phase: "completed",
          mode: "download_only",
          source_type: "current_page",
          media_path: "",
          subtitle_path: "",
          transcript_path: "",
          reuse: {
            media_available: true,
            subtitle_available: true,
            transcript_ready: true,
            transcript_source: "page-subtitle",
            rerun_from_media_ready: true
          },
          visual_windows: []
        }
      })
    };
  }
  if (value.endsWith("/api/tasks/task-note-download-only/note")) {
    return { ok: false, text: async () => "" };
  }
  return originalFetchForDownloadNote(url);
};
context.selectTask("task-note-download-only", { syncUrl: false });
context.switchResultTab("note");
await context.renderDetail();
assert.match(elements.get("#detail").innerHTML, /视频和字幕已直取到本地/);
assert.match(elements.get("#detail").innerHTML, /页面字幕/);
assert.match(elements.get("#detail").innerHTML, /导出字幕/);
assert.match(elements.get("#detail").innerHTML, /导出 media\.mp4/);
assert.match(elements.get("#detail").innerHTML, /继续切片总结/);
assert.match(elements.get("#detail").innerHTML, /data-rerun-from-media="task-note-download-only"/);
assert.doesNotMatch(elements.get("#detail").innerHTML, /不会继续转写、切片或总结/);
assert.equal(elements.get("#subtitlesButton").disabled, false);
context.window.location.assignedUrls = [];
elements.get("#subtitlesButton").onclick();
assert.equal(context.window.location.assignedUrls.at(-1), "/api/tasks/task-note-download-only/exports/subtitles");
context.fetch = originalFetchForDownloadNote;

const originalFetchForDiagnostics = context.fetch;
context.fetch = async url => {
  const value = String(url);
  if (value.endsWith("/api/tasks/task-diagnostics-evidence")) {
    return {
      json: async () => ({
        task: {
          id: "task-diagnostics-evidence",
          title: "Diagnostics lesson",
          status: "failed",
          phase: "failed",
          progress: 100,
          source_type: "current_page",
          error_code: "download_forbidden",
          error_detail: "signed URL expired",
          active_video: {
            src: "blob:https://course.example.com/player",
            current_time: 42,
            duration: 300,
            paused: false,
            width: 1280,
            height: 720
          },
          selected_resource: {
            kind: "hls",
            source: "webRequest",
            url: "https://cdn.example.com/lesson/master.m3u8",
            resolved_url: "https://cdn.example.com/lesson/master.m3u8",
            playback_match: "blob-source",
            request_headers: { Referer: "https://course.example.com/lesson", Cookie: "secret=1" }
          },
          direct_extraction: {
            no_tab_recording: true,
            no_drm_bypass: true,
            route: "attempted_direct_extraction",
            boundary: "download_failed",
            media_landed: false,
            media_reusable: false,
            selected_candidate: { kind: "hls", source: "webRequest", playback_match: "blob-source" },
            browser_context: { active_source_type: "blob", cookie_count: 3, cookie_domain_count: 1 },
            download: { successful_attempt_count: 0, failed_attempt_count: 1, strategy_order: ["manifest-ffmpeg"] },
            processing: { note_ready: false, transcript_ready: false, frame_grid_count: 0, visual_window_count: 0 }
          },
          download_attempts: [{ strategy: "manifest-ffmpeg", status: "failed", code: "download_forbidden", message: "signed URL expired" }]
        }
      })
    };
  }
  return originalFetchForDiagnostics(url);
};
context.selectTask("task-diagnostics-evidence", { syncUrl: false });
context.switchResultTab("diagnostics");
await context.renderDetail();
const diagnosticsEvidenceHtml = elements.get("#detail").innerHTML;
assert.match(diagnosticsEvidenceHtml, /class="task-browser-evidence"/);
assert.match(diagnosticsEvidenceHtml, /浏览器播放证据/);
assert.match(diagnosticsEvidenceHtml, /class="direct-extraction-evidence"/);
assert.match(diagnosticsEvidenceHtml, /非录制下载路线/);
assert.match(diagnosticsEvidenceHtml, /直取和总结证据/);
assert.match(diagnosticsEvidenceHtml, /class="pipeline-audit"/);
assert.match(diagnosticsEvidenceHtml, /manifest-ffmpeg/);
assert.doesNotMatch(diagnosticsEvidenceHtml, /secret=1/);
context.fetch = originalFetchForDiagnostics;
vm.runInContext(`selectedTab = "note";`, context);
context.renderResultTabState();

const visualDeckWithTranscriptHtml = context.visualStudyDeck({
  id: "task-visual-transcript",
  title: "带字幕切片",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: ""
    }
  ]
}, {
  segments: [
    { start: 12, end: 18, text: "老师讲解概念定义" },
    { start: 45, end: 52, text: "<script>alert(1)</script> 例题演示" },
    { start: 220, end: 230, text: "不属于这个窗口" }
  ]
});
assert.match(visualDeckWithTranscriptHtml, /1 个窗口 · 2 段字幕已同步/);
assert.match(visualDeckWithTranscriptHtml, /class="visual-study-cues"/);
assert.match(visualDeckWithTranscriptHtml, /00:00:12/);
assert.match(visualDeckWithTranscriptHtml, /data-media-seek-time="12\.000"/);
assert.match(visualDeckWithTranscriptHtml, /data-media-seek-time="45\.000"/);
assert.match(visualDeckWithTranscriptHtml, /老师讲解概念定义/);
assert.match(visualDeckWithTranscriptHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 例题演示/);
assert.match(visualDeckWithTranscriptHtml, /回看检查点/);
assert.match(visualDeckWithTranscriptHtml, /对照画面确认对应的板书、PPT、代码或操作步骤/);
assert.match(visualDeckWithTranscriptHtml, /自测问题/);
assert.match(visualDeckWithTranscriptHtml, /这句“老师讲解概念定义”在画面中对应的标题、公式、代码或操作状态是什么？/);
assert.match(visualDeckWithTranscriptHtml, /核对截图里的板书/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /不属于这个窗口/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /<script>/);

const mediaPreviewHtml = context.mediaPreviewHtml({
  id: "task-media-preview",
  title: "本地回看",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-media-preview/media.mp4",
  status: "success"
});
assert.match(mediaPreviewHtml, /data-learning-video/);
assert.match(mediaPreviewHtml, /点击字幕或视觉窗口时间可回看对应画面/);

const transcriptSeekHtml = context.transcriptTimeline({
  source: "whisper",
  segments: [
    { start: 12, end: 18, text: "第一句" },
    { start: 190, end: 195, text: "第二句" }
  ]
}, {
  id: "task-transcript-seek",
  title: "转写回看",
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
});
assert.match(transcriptSeekHtml, /class="transcript-window"/);
assert.match(transcriptSeekHtml, /data-media-seek-time="0\.000"/);
assert.match(transcriptSeekHtml, /data-media-seek-time="12\.000"/);
assert.match(transcriptSeekHtml, /data-line-time="190\.000"/);

const seekVideo = documentStub.querySelector("[data-learning-video]");
let playCalls = 0;
seekVideo.play = () => {
  playCalls += 1;
  return Promise.resolve();
};
assert.equal(context.seekLearningVideo(42.25), true);
assert.equal(seekVideo.currentTime, 42.25);
assert.equal(playCalls, 1);
assert.equal(seekVideo.classList.contains("media-seek-active"), true);

const studyBarHtml = context.noteStudyBar(`# <script>bad()</script> 课程

## 第一节
### 画面演示
`, {
  id: "task-study-map",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/note.md",
  options: {
    transcriber: "faster-whisper",
    whisper_model: "small"
  },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: ""
  }],
  download_attempts: [{ strategy: "direct-file" }]
});

assert.match(studyBarHtml, /class="study-map"/);
assert.match(studyBarHtml, /笔记目录/);
assert.match(studyBarHtml, /3 个标题/);
assert.match(studyBarHtml, /1 个章节 · 1 个小节/);
assert.match(studyBarHtml, /画面切片/);
assert.match(studyBarHtml, /00:00:00 - 00:03:00/);
assert.match(studyBarHtml, /data-switch-result-tab="frames"/);
assert.match(studyBarHtml, /data-switch-result-tab="transcript"/);
assert.match(studyBarHtml, /\/api\/tasks\/task-study-map\/exports\/bundle/);
assert.match(studyBarHtml, /\/api\/tasks\/task-study-map\/exports\/manifest/);
assert.doesNotMatch(studyBarHtml, /<script>bad/);
assert.match(studyBarHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const exportCtaHtml = context.noteExportCtaBar({
  id: "task-study-map",
  status: "success",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/media.mp4",
  subtitle_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/subtitles.srt",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/note.md",
  summary_diagnostics_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/summary_diagnostics.json",
  visual_windows: [{ id: "W001", start: 0, end: 180, grid_url: "http://127.0.0.1/grid.jpg" }],
  download_attempts: [{ strategy: "direct-file" }]
});
assert.match(exportCtaHtml, /class="export-cta-bar ready"/);
assert.match(exportCtaHtml, /导出阶段/);
assert.match(exportCtaHtml, /拿走学习成果/);
assert.match(exportCtaHtml, /\/api\/tasks\/task-study-map\/exports\/markdown/);
assert.match(exportCtaHtml, /\/api\/tasks\/task-study-map\/exports\/visual-windows/);
assert.match(exportCtaHtml, /\/api\/tasks\/task-study-map\/exports\/bundle/);
assert.match(exportCtaHtml, /\/api\/tasks\/task-study-map\/exports\/media/);
assert.match(exportCtaHtml, /\/api\/tasks\/task-study-map\/exports\/diagnostics/);
assert.match(stylesCss, /\.export-cta-bar[\s\S]*grid-template-columns:\s*minmax\(260px, 1fr\) minmax\(280px, auto\)/);
assert.match(stylesCss, /@container \(max-width: 960px\)[\s\S]*\.export-cta-bar[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/);

const reuseExportCtaHtml = context.noteExportCtaBar({
  id: "task-reuse-export",
  status: "success",
  source_type: "current_page",
  reuse: {
    media_available: true,
    subtitle_available: true,
    transcript_ready: true
  }
});
assert.match(reuseExportCtaHtml, /class="export-cta-bar partial"/);
assert.match(reuseExportCtaHtml, /\/api\/tasks\/task-reuse-export\/exports\/subtitles/);
assert.match(reuseExportCtaHtml, /\/api\/tasks\/task-reuse-export\/exports\/media/);

const noteHeroHtml = context.noteHeroBanner(`# 机器学习导论

## 第一章
`, {
  id: "task-note-hero",
  title: "<script>bad()</script> fallback",
  page_url: "https://course.example.com/lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-note-hero/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-note-hero/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-note-hero/note.md",
  summary_source: "vision-llm",
  selected_resource: {
    kind: "hls",
    playback_match: "blob-source",
    url: "javascript:alert(1)"
  },
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3,
    visual_understanding: true
  },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
});

assert.match(noteHeroHtml, /class="note-hero-banner"/);
assert.match(noteHeroHtml, /机器学习导论/);
assert.doesNotMatch(noteHeroHtml, /&lt;script&gt;bad/);
assert.match(noteHeroHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.match(noteHeroHtml, /00:00:00 - 00:03:00/);
assert.match(noteHeroHtml, /1 窗口/);
assert.match(noteHeroHtml, /data-switch-result-tab="transcript"/);
assert.match(noteHeroHtml, /data-switch-result-tab="frames"/);
assert.match(noteHeroHtml, /href="https:\/\/course\.example\.com\/lesson"/);
assert.doesNotMatch(noteHeroHtml, /javascript:alert/);

const taskOverviewHtml = context.taskOverview({
  id: "task-web-overview",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-overview/media.mp4",
  active_video: {
    src: "blob:https://course.example.com/current-player",
    current_time: 42,
    duration: 600,
    width: 1280,
    height: 720,
    frame_id: 7,
    paused: false
  },
  selected_resource: {
    url: "https://cdn.example.com/source.mp4?token=abc",
    kind: "video",
    audio_url: "https://cdn.example.com/audio.m4a?token=abc",
    playback_match: "exact-src",
    content_length: 1048576,
    resolved_url: "https://cdn.example.com/final.mp4?token=abc",
    frame_url: "https://course.example.com/player/frame.html",
    blob_url: "blob:https://course.example.com/current-player",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=1",
      Authorization: "Bearer secret"
    }
  },
  direct_extraction: {
    no_tab_recording: true,
    no_drm_bypass: true,
    route: "download_only_to_local_media",
    media_landed: true,
    media_reusable: true,
    selected_candidate: {
      kind: "hls",
      source: "webRequest",
      playback_match: "blob-source",
      safe_request_header_names: ["Referer", "Origin", "Cookie", "Authorization"]
    },
    browser_context: {
      active_source_type: "blob",
      browser_subtitle_count: 2,
      cookie_count: 3,
      partitioned_cookie_count: 2,
      partition_key_count: 1,
      cookie_domain_count: 1
    },
    download: {
      successful_attempt_count: 1,
      failed_attempt_count: 0,
      strategy_order: ["manifest-ffmpeg", "yt-dlp-page"]
    },
    processing: {
      download_only: true,
      transcript_ready: false,
      frame_grid_count: 0,
      visual_window_count: 0,
      note_ready: false
    },
    boundary: "normal_accessible_media_only"
  },
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3,
    whisper_model: "small",
    note_style: "study",
    visual_understanding: true
  },
  visual_windows: [],
  next_actions: [
    { key: "continue_from_media", label: "从 media.mp4 继续", detail: "复用已下载视频进入切片总结。", intent: "rerun_from_media" },
    { key: "export_media", label: "导出 media.mp4", detail: "核对本地视频。", intent: "export", target: "media" },
    { key: "view_diagnostics", label: "看下载诊断", detail: "查看候选和失败原因。", intent: "switch_tab", target: "diagnostics" }
  ]
});

assert.match(taskOverviewHtml, /class="task-overview status-success"/);
assert.match(taskOverviewHtml, /导出本地视频/);
assert.match(taskOverviewHtml, /导出审计/);
assert.match(taskOverviewHtml, /导出资料包/);
assert.match(taskOverviewHtml, /生成完整笔记/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/media/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/audit/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/diagnostics/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/bundle/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/manifest/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.match(taskOverviewHtml, /当前页下载/);
assert.match(taskOverviewHtml, /伴随音频流/);
assert.match(taskOverviewHtml, /音视频合并/);
assert.match(taskOverviewHtml, /已跟踪最终 URL/);
assert.match(taskOverviewHtml, /final\.mp4\?token=abc/);
assert.match(taskOverviewHtml, /浏览器播放证据/);
assert.match(taskOverviewHtml, /3 cookie/);
assert.match(taskOverviewHtml, /2 分区 cookie/);
assert.match(taskOverviewHtml, /1 partition key/);
assert.doesNotMatch(taskOverviewHtml, /secret=1/);
assert.match(taskOverviewHtml, /非录制直取/);
assert.match(taskOverviewHtml, /播放中 · 00:00:42 \/ 00:10:00 · 1280x720 · frame 7/);
assert.match(taskOverviewHtml, /直取目标/);
assert.match(taskOverviewHtml, /请求上下文/);
assert.match(taskOverviewHtml, /Referer/);
assert.match(taskOverviewHtml, /blob 已映射/);
assert.match(taskOverviewHtml, /class="direct-extraction-evidence"/);
assert.match(taskOverviewHtml, /直取证据/);
assert.match(taskOverviewHtml, /非录制下载路线/);
assert.match(taskOverviewHtml, /只下载到本地/);
assert.match(taskOverviewHtml, /不录制标签页/);
assert.match(taskOverviewHtml, /已保存 media\.mp4/);
assert.match(taskOverviewHtml, /可复用本地视频/);
assert.match(taskOverviewHtml, /headers Origin, Referer/);
assert.match(taskOverviewHtml, /manifest-ffmpeg → yt-dlp-page/);
assert.match(taskOverviewHtml, /仅可访问媒体/);
assert.doesNotMatch(taskOverviewHtml, /secret=1/);
assert.doesNotMatch(taskOverviewHtml, /Bearer secret/);
assert.doesNotMatch(taskOverviewHtml, /Authorization/);
assert.match(taskOverviewHtml, /阶段检查/);
assert.match(taskOverviewHtml, /class="task-command-center"/);
assert.match(taskOverviewHtml, /class="task-command-grid"/);
assert.match(taskOverviewHtml, /class="task-next-actions"/);
assert.match(taskOverviewHtml, /推荐下一步/);
assert.match(taskOverviewHtml, /从 media\.mp4 继续/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.match(taskOverviewHtml, /data-switch-result-tab="diagnostics"/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/media/);
assert.match(taskOverviewHtml, /data-switch-result-tab="diagnostics"/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.match(taskOverviewHtml, /class="next-step-card ready"/);
assert.match(taskOverviewHtml, /继续生成完整笔记/);
assert.match(taskOverviewHtml, /看下载证据/);
assert.match(taskOverviewHtml, /class="media-preview-card"/);
assert.match(taskOverviewHtml, /本地视频核对/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/media/);
assert.match(taskOverviewHtml, /导出 media\.mp4/);
assert.match(taskOverviewHtml, /来源检查/);
assert.match(taskOverviewHtml, /媒体检查/);
assert.match(taskOverviewHtml, /字幕检查/);
assert.match(taskOverviewHtml, /切片检查/);
assert.match(taskOverviewHtml, /总结检查/);
assert.match(taskOverviewHtml, /pipeline-audit-actions/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const downloadedAuditItems = context.pipelineAuditItems({
  id: "audit-downloaded",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/audit-downloaded/media.mp4",
  selected_resource: {
    kind: "hls",
    source: "webRequest",
    resolved_url: "https://cdn.example.com/master.m3u8"
  },
  options: { visual_understanding: true },
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.equal(JSON.stringify(downloadedAuditItems.map(item => item.state)), JSON.stringify(["pass", "pass", "warn", "warn", "warn"]));
const unsafeAuditHtml = context.pipelineAuditHtml({
  status: "failed",
  phase: "failed",
  source_type: "current_page",
  error_code: "<script>bad()</script>",
  selected_resource: { kind: "video", source: "webRequest" },
  download_attempts: []
});
assert.match(unsafeAuditHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(unsafeAuditHtml, /<script>bad/);
assert.match(unsafeAuditHtml, /data-recovery-source="local"/);
const fallbackTaskOverviewHtml = context.taskOverview({
  id: "task-web-fallback",
  title: "直取失败课程",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-fallback/note.md",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-fallback/transcript.json",
  error_code: "download_forbidden",
  error_detail: "signed URL expired 已生成页面文本/浏览器字幕兜底笔记。",
  download_attempts: [
    {
      strategy: "direct-file",
      status: "failed",
      code: "download_forbidden",
      status_code: 403,
      message: "HTTP 403：Referer 或签名过期"
    },
    {
      strategy: "page-ytdlp",
      status: "failed",
      code: "download_forbidden",
      message: "yt-dlp no video"
    }
  ],
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3
  }
});
assert.match(fallbackTaskOverviewHtml, /class="task-overview status-failed"/);
assert.match(fallbackTaskOverviewHtml, /已生成兜底笔记/);
assert.match(fallbackTaskOverviewHtml, /导出 Markdown/);
assert.match(fallbackTaskOverviewHtml, /导出诊断/);
assert.match(fallbackTaskOverviewHtml, /导出资料包/);
const failureGuideHtml = context.failureGuide({
  status: "failed",
  error_code: "download_forbidden",
  note_path: "D:/note.md",
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script> Referer expired" },
    { strategy: "page-ytdlp", code: "download_forbidden", message: "no fallback" }
  ]
});
assert.match(failureGuideHtml, /最近尝试：page-ytdlp · download_forbidden · no fallback/);
assert.match(failureGuideHtml, /后端已尝试 2 条路线/);
assert.match(failureGuideHtml, /已生成兜底笔记/);
assert.match(failureGuideHtml, /<ul>/);
assert.match(failureGuideHtml, /class="recovery-actions"/);
assert.match(failureGuideHtml, /data-recovery-source="local"/);
assert.match(failureGuideHtml, /data-switch-result-tab="diagnostics"/);
assert.match(failureGuideHtml, /导出 Markdown/);
assert.doesNotMatch(failureGuideHtml, /<script>bad/);
const diagnosticRecoveryHtml = context.diagnosticRecoveryHtml({
  id: "task-recovery",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "",
  selected_resource: {
    kind: "hls",
    url: "https://mooc1.chaoxing.com/ananas/status/lesson.m3u8",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Range: "bytes=100-200",
      Cookie: "secret=bad"
    }
  },
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script>" },
    { strategy: "manifest-ffmpeg", code: "unsupported_manifest" }
  ],
  recovery: {
    diagnosis: "媒体地址被防盗链、时效签名或 Referer 拒绝。",
    primary_action: {
      key: "refresh_playback_and_retry",
      label: "继续播放后重检",
      ui_intent: "retry_current_page",
      detail: "回到原页面继续播放后重试。"
    },
    actions: [
      { key: "refresh_playback_and_retry", label: "继续播放后重检", ui_intent: "retry_current_page", detail: "回到原页面继续播放后重试。" },
      { key: "continue_from_media", label: "继续切片总结", ui_intent: "continue_from_media" },
      { key: "local_upload", label: "上传本地视频", ui_intent: "local_upload" },
      { key: "inspect_diagnostics", label: "查看诊断", ui_intent: "inspect_diagnostics" },
      { key: "export_diagnostics", label: "导出诊断", ui_intent: "export_diagnostics" },
      { key: "export_audit", label: "导出审计", ui_intent: "export_audit" }
    ]
  }
});
assert.match(diagnosticRecoveryHtml, /class="diagnostic-recovery"/);
assert.match(diagnosticRecoveryHtml, /学习通\/超星/);
assert.match(diagnosticRecoveryHtml, /不刷课/);
assert.match(diagnosticRecoveryHtml, /下一步建议/);
assert.match(diagnosticRecoveryHtml, /媒体地址被防盗链/);
assert.match(diagnosticRecoveryHtml, /主动作：继续播放后重检/);
assert.match(diagnosticRecoveryHtml, /data-recovery-source="browser"/);
assert.match(diagnosticRecoveryHtml, /后端已尝试 2 条路线/);
assert.match(diagnosticRecoveryHtml, /Referer/);
assert.match(diagnosticRecoveryHtml, /Range 只作为浏览器播放证据/);
assert.match(diagnosticRecoveryHtml, /Cookie/);
assert.doesNotMatch(diagnosticRecoveryHtml, /secret=bad/);
assert.match(diagnosticRecoveryHtml, /继续切片总结/);
assert.match(diagnosticRecoveryHtml, /data-rerun-from-media="task-recovery"/);
assert.match(diagnosticRecoveryHtml, /\/api\/tasks\/task-recovery\/exports\/diagnostics/);
assert.match(diagnosticRecoveryHtml, /\/api\/tasks\/task-recovery\/exports\/audit/);
assert.match(diagnosticRecoveryHtml, /data-recovery-source="local"/);
assert.doesNotMatch(diagnosticRecoveryHtml, /<script>bad/);
const recoveryDecisionHtml = context.recoveryDecisionHtml({
  id: "task-decision",
  status: "failed",
  phase: "failed",
  source_type: "current_page",
  error_code: "download_forbidden",
  error_detail: "<script>bad()</script> expired",
  selected_resource: {
    kind: "hls",
    source: "webRequest",
    request_headers: { Referer: "https://course.example.com" }
  },
  download_attempts: [{ strategy: "manifest-ffmpeg", code: "download_forbidden" }],
  direct_extraction: {
    boundary: "normal_accessible_media_only",
    download: { failed_attempt_count: 1 },
    processing: {}
  },
  recovery: {
    code: "download_forbidden",
    severity: "recoverable",
    confidence: "medium",
    diagnosis: "媒体地址被防盗链或签名拒绝。",
    attempt_count: 1,
    primary_action: {
      key: "refresh_playback_and_retry",
      label: "继续播放后重检",
      ui_intent: "retry_current_page",
      detail: "回到原页面播放后重试。"
    },
    actions: [
      { key: "refresh_playback_and_retry", label: "继续播放后重检", ui_intent: "retry_current_page" },
      { key: "local_upload", label: "上传本地视频", ui_intent: "local_upload" },
      { key: "inspect_diagnostics", label: "查看诊断", ui_intent: "inspect_diagnostics" },
      { key: "export_audit", label: "导出审计", ui_intent: "export_audit" }
    ],
    boundary_notes: [
      "已捕获可复用请求头名：Referer；不会保存 Cookie 或 Authorization 值。"
    ],
    steps: [
      "回到原页面继续播放后重新检测，优先选择带 Referer/Origin 或当前播放匹配的候选。"
    ]
  }
});
assert.match(recoveryDecisionHtml, /class="recovery-decision warn"/);
assert.match(recoveryDecisionHtml, /推荐行动/);
assert.match(recoveryDecisionHtml, /继续播放后重检/);
assert.match(recoveryDecisionHtml, /data-recovery-source="browser"/);
assert.match(recoveryDecisionHtml, /data-recovery-source="local"/);
assert.match(recoveryDecisionHtml, /data-switch-result-tab="diagnostics"/);
assert.match(recoveryDecisionHtml, /\/api\/tasks\/task-decision\/exports\/audit/);
assert.match(recoveryDecisionHtml, /媒体地址被防盗链或签名拒绝/);
assert.match(recoveryDecisionHtml, /诊断码/);
assert.match(recoveryDecisionHtml, /download_forbidden/);
assert.match(recoveryDecisionHtml, /1 条路线/);
assert.match(recoveryDecisionHtml, /仅可访问媒体/);
assert.match(recoveryDecisionHtml, /Referer/);
assert.doesNotMatch(recoveryDecisionHtml, /<script>bad/);
const recoveryNextStepHtml = context.nextStepHtml({
  id: "task-decision",
  status: "failed",
  source_type: "current_page",
  error_code: "download_forbidden",
  recovery: {
    severity: "recoverable",
    diagnosis: "媒体地址被防盗链或签名拒绝。",
    primary_action: {
      key: "refresh_playback_and_retry",
      label: "继续播放后重检",
      ui_intent: "retry_current_page"
    }
  }
});
assert.match(recoveryNextStepHtml, /class="next-step-card warn"/);
assert.match(recoveryNextStepHtml, /继续播放后重检/);
assert.match(recoveryNextStepHtml, /data-recovery-source="browser"/);
assert.equal(context.hasTaskBundle({ media_path: "D:/media.mp4" }), true);
assert.equal(context.hasTaskBundle({ status: "failed", error_code: "download_forbidden" }), true);
assert.equal(context.hasTaskBundle({ download_attempts: [{ strategy: "direct-file" }] }), true);
assert.equal(context.hasTaskBundle({}), false);
assert.equal(context.hasTaskDiagnostics({ selected_resource: { kind: "video" } }), true);
assert.equal(context.hasTaskDiagnostics({ summary_diagnostics_path: "summary.json" }), true);
assert.equal(context.hasTaskDiagnostics({}), false);
assert.equal(context.hasTaskAudit({ id: "audit-task", source_type: "current_page" }), true);
assert.equal(context.hasTaskAudit({}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-downloaded",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-processing-failed",
  status: "failed",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-running",
  status: "running",
  media_path: "D:/media.mp4",
  note_path: ""
}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-noted",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
}), false);
context.updateContinueFromMediaAction({
  id: "task-downloaded",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
});
assert.equal(elements.get("#continueFromMediaButton").hidden, false);
assert.equal(elements.get("#continueFromMediaButton").disabled, false);
context.updateContinueFromMediaAction({
  id: "task-noted",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
});
assert.equal(elements.get("#continueFromMediaButton").hidden, true);
assert.equal(elements.get("#continueFromMediaButton").disabled, true);

const failedMediaOverviewHtml = context.taskOverview({
  id: "task-failed-media",
  title: "Downloaded but processing failed",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  media_path: "D:/media.mp4",
  note_path: "",
  error_code: "processing_failed",
  error_detail: "Whisper failed",
  selected_resource: { kind: "video", source: "webRequest" },
  recovery: {
    code: "media_ready_for_rerun",
    severity: "recoverable",
    confidence: "high",
    diagnosis: "视频已保存到本地，但完整笔记尚未生成；优先复用 media.mp4 继续转写、切片和图文总结。",
    attempt_count: 1,
    primary_action: {
      key: "continue_from_media",
      label: "继续切片总结",
      ui_intent: "continue_from_media"
    },
    actions: [
      { key: "continue_from_media", label: "继续切片总结", ui_intent: "continue_from_media" },
      { key: "local_upload", label: "上传本地视频", ui_intent: "local_upload" },
      { key: "inspect_diagnostics", label: "查看诊断", ui_intent: "inspect_diagnostics" }
    ]
  },
  options: {},
  visual_windows: []
});
assert.match(failedMediaOverviewHtml, /data-rerun-from-media="task-failed-media"/);
assert.match(failedMediaOverviewHtml, /Whisper failed/);
assert.match(failedMediaOverviewHtml, /class="recovery-decision warn"/);
assert.match(failedMediaOverviewHtml, /视频已保存到本地/);
assert.match(failedMediaOverviewHtml, /继续切片总结/);
assert.doesNotMatch(failedMediaOverviewHtml, /继续切片总结继续切片总结/);

const failedNextStepHtml = context.nextStepHtml({
  id: "task-failed-next",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  error_code: "<script>bad()</script>",
  error_detail: "signed URL expired",
  selected_resource: { kind: "video", source: "webRequest" },
  options: {}
});
assert.match(failedNextStepHtml, /直取链路需要处理/);
assert.match(failedNextStepHtml, /signed URL expired/);
assert.match(failedNextStepHtml, /data-recovery-source="local"/);
assert.doesNotMatch(failedNextStepHtml, /<script>bad/);

const taskChipsHtml = context.taskChipsHtml({
  title: "<script>bad()</script>",
  status: "failed",
  source_type: "current_page",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md",
  error_code: "download_forbidden",
  selected_resource: {
    kind: "hls",
    playback_match: "blob-source"
  },
  download_attempts: [{ strategy: "direct-file" }, { strategy: "page-ytdlp" }],
  visual_windows: [{ id: "W001" }, { id: "W002" }]
});
assert.match(taskChipsHtml, /task-chips/);
assert.match(taskChipsHtml, /HLS/);
assert.doesNotMatch(taskChipsHtml, /2 窗口/);
assert.match(taskChipsHtml, /2 次尝试/);
assert.match(taskChipsHtml, /download_forbidden/);
assert.doesNotMatch(taskChipsHtml, /<script>bad/);

const backendAuditHtml = context.pipelineAuditHtml({
  status: "success",
  source_type: "current_page",
  media_path: "D:/media.mp4",
  options: {},
  audit: {
    gates: [
      { key: "source", state: "pass", value: "browser", detail: "server source" },
      { key: "media", state: "pass", value: "media.mp4", detail: "server media" },
      { key: "transcript", state: "warn", value: "backend transcript", detail: "server says wait" },
      { key: "visual", state: "wait", value: "backend visual", detail: "server visual" },
      { key: "summary", state: "wait", value: "backend summary", detail: "server summary" }
    ]
  }
});
assert.match(backendAuditHtml, /backend transcript/);
assert.match(backendAuditHtml, /server says wait/);
assert.match(backendAuditHtml, /class="warn"/);

const embeddedAuditTask = context.taskFromPayload({
  task: {
    id: "embedded-audit-task",
    audit: {
      gates: [{ key: "transcript", state: "warn", value: "embedded transcript", detail: "embedded audit detail" }]
    }
  }
});
assert.equal(embeddedAuditTask.audit.gates[0].value, "embedded transcript");

const taskPreviewWithImage = context.taskPreviewHtml({
  status: "success",
  source_type: "current_page",
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "/api/tasks/task-preview/assets/grid_000.jpg"
  }]
});
assert.match(taskPreviewWithImage, /class="task-preview status-success"/);
assert.match(taskPreviewWithImage, /<img src="\/api\/tasks\/task-preview\/assets\/grid_000.jpg"/);
assert.match(taskPreviewWithImage, /00:00:00 - 00:03:00/);

const taskPreviewFallback = context.taskPreviewHtml({
  status: "failed",
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  selected_resource: { kind: "blob" }
});
assert.match(taskPreviewFallback, /class="task-preview status-failed empty"/);
assert.match(taskPreviewFallback, /drm_or_encrypted/);

const summaryDiagnostic = context.summaryDiagnosticText({
  summary_source: "vision-llm",
  summary_diagnostics: {
    used_vision_llm: true,
    llm_model: "vision-model",
    llm_provider: "openrouter",
    llm_base_host: "openrouter.ai",
    llm_failure_stage: "vision_merge",
    llm_failure_code: "api_error",
    llm_failure_reason: "HTTP 429",
    llm_event_count: 2,
    llm_last_failure: { stage: "vision_batch", code: "api_error" },
    vision_failed_batch_count: 1,
    vision_model_rejected_image: true,
    visual_window_count: 2,
    frame_grid_count: 2,
    vision_grid_count: 2,
    vision_image_count: 2,
    omitted_frame_grid_count: 1,
    all_grids_had_images: true,
    missing_vision_image_window_ids: ["W001"],
    omitted_vision_window_ids: ["W081", "W082", "W083", "W084"],
    used_page_text_fallback: true,
    page_text_char_count: 18,
    browser_subtitle_count: 3,
    combined_text_char_count: 72
  }
});

assert.match(summaryDiagnostic, /Provider openrouter/);
assert.match(summaryDiagnostic, /Base openrouter\.ai/);
assert.match(summaryDiagnostic, /视觉批次失败 1/);
assert.match(summaryDiagnostic, /模型拒绝图片输入/);
assert.match(summaryDiagnostic, /LLM 事件 2/);
assert.match(summaryDiagnostic, /最后失败 vision_batch\/api_error/);
assert.match(summaryDiagnostic, /LLM 失败 vision_merge\/api_error/);
assert.match(summaryDiagnostic, /原因 HTTP 429/);

assert.match(summaryDiagnostic, /已使用视觉 LLM/);
assert.match(summaryDiagnostic, /模型 vision-model/);
assert.match(summaryDiagnostic, /视觉窗口 2/);
assert.match(summaryDiagnostic, /送入视觉 2\/2/);
assert.match(summaryDiagnostic, /超限省略 1/);
assert.match(summaryDiagnostic, /缺图 W001/);
assert.match(summaryDiagnostic, /省略窗口 W081, W082, W083 等 4 个/);
assert.match(summaryDiagnostic, /页面文本 18 字/);
assert.match(summaryDiagnostic, /浏览器字幕 3 条/);
assert.match(summaryDiagnostic, /合并文本 72 字/);

const visualCoverageHtml = context.visualCoverageHtml({
  id: "task-visual-coverage",
  summary_warning: "<script>bad()</script> 降级",
  summary_diagnostics: {
    visual_window_count: 3,
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 1,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"]
  },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: ""
    },
    {
      id: "<script>bad()</script>",
      start: 360,
      end: 540,
      frame_count: 9,
      grid_url: ""
    }
  ]
});
assert.match(visualCoverageHtml, /class="visual-coverage"/);
assert.match(visualCoverageHtml, /视觉切片覆盖/);
assert.match(visualCoverageHtml, /3 个窗口/);
assert.match(visualCoverageHtml, /00:00:00 - 00:09:00/);
assert.match(visualCoverageHtml, /1\/3/);
assert.match(visualCoverageHtml, /缺图 W002/);
assert.match(visualCoverageHtml, /超限省略 W099/);
assert.match(visualCoverageHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(visualCoverageHtml, /<script>bad/);

const routeReadyHtml = context.browserRouteSummaryHtml({
  id: "route-ready",
  title: "<script>bad()</script> 课程",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/route-ready/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/route-ready/note.md",
  selected_resource: { kind: "hls" },
  visual_windows: [{ id: "W001", start: 0, end: 180, frame_count: 9 }],
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.match(routeReadyHtml, /browser-route-summary-card ready/);
assert.match(routeReadyHtml, /最近当前页直取已生成笔记/);
assert.match(routeReadyHtml, /hls · 1 次下载尝试 · 1 个视觉窗口/);
assert.doesNotMatch(routeReadyHtml, /<script>bad/);

const playerSourceOverview = context.taskOverview({
  id: "player-source-task",
  title: "播放器来源任务",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/player-source-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/player-source-task/note.md",
  selected_resource: {
    kind: "video",
    source: "pageHookPlayer",
    label: "DPlayer constructor switchVideo",
    url: "https://cdn.example.com/lesson.mp4?<script>bad()</script>"
  },
  summary_diagnostics: {
    visual_window_count: 0,
    frame_grid_count: 0,
    vision_grid_count: 0,
    vision_image_count: 0
  },
  options: {},
  visual_windows: []
});
assert.match(playerSourceOverview, /DPlayer 已加载源地址/);
assert.match(playerSourceOverview, /直取来源/);
assert.match(playerSourceOverview, /浏览器证据/);
assert.match(playerSourceOverview, /总结证据/);
assert.match(playerSourceOverview, /class="visual-coverage"/);
assert.match(playerSourceOverview, /等待抽帧生成视觉窗口/);
assert.doesNotMatch(playerSourceOverview, /<script>bad/);

const manifestGuessOverview = context.taskOverview({
  id: "manifest-guess-task",
  title: "Manifest guess task",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  error_code: "unsupported_manifest",
  selected_resource: {
    kind: "hls",
    source: "manifest-guess",
    label: "Guessed HLS manifest from segment directory",
    url: "https://cdn.example.com/live/master.m3u8"
  },
  options: {},
  download_attempts: [{ strategy: "manifest-ffmpeg", code: "unsupported_manifest" }],
  visual_windows: []
});
assert.match(manifestGuessOverview, /同目录 manifest 猜测/);
assert.match(manifestGuessOverview, /unsupported_manifest/);
assert.match(manifestGuessOverview, /下载路线/);
assert.match(manifestGuessOverview, /manifest-ffmpeg/);

const routeEvidenceItems = context.taskRouteEvidenceItems({
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  error_code: "download_forbidden",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    url: "https://course.example.com/player/video?id=1",
    resolved_url: "https://cdn.example.com/final.mp4?token=abc",
    playback_match: "same-frame",
    mime: "video/mp4",
    content_length: 1048576,
    mse_append_count: 12,
    mse_append_total_bytes: 2097152,
    mse_append_magic: "ftyp",
    mse_append_mime: "video/mp4",
    mse_append_detected_kind: "video",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=bad",
      Authorization: "Bearer bad"
    }
  },
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", message: "<script>bad()</script>" }
  ],
  summary_source: "local-template",
  summary_diagnostics: {
    used_local_template: true,
    used_page_text_fallback: true,
    page_text_char_count: 24,
    browser_subtitle_count: 2,
    combined_text_char_count: 80
  }
});
assert.equal(routeEvidenceItems.length, 4);
assert.equal(routeEvidenceItems[2].value, "Referer");
assert.match(routeEvidenceItems[2].detail, /MSE append 12x ftyp 2\.0 MB video\/mp4 detected video/);
assert.match(JSON.stringify(routeEvidenceItems), /final\.mp4\?token=abc/);
assert.doesNotMatch(JSON.stringify(routeEvidenceItems), /secret=bad|Bearer bad/);
assert.match(context.taskBrowserEvidenceHtml({
  source_type: "current_page",
  active_video: { src: "blob:https://course.example.com/player", current_time: 12, duration: 120, paused: false },
  selected_resource: {
    kind: "blob",
    source: "pageHookMse",
    url: "blob:https://course.example.com/player",
    blob_url: "blob:https://course.example.com/player",
    mse_append_count: 12,
    mse_append_total_bytes: 2097152,
    mse_append_magic: "ftyp",
    mse_append_mime: "video/mp4",
    mse_append_detected_kind: "video"
  }
}), /MSE append 12x ftyp 2\.0 MB video\/mp4 detected video/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    url: "https://course.example.com/player/video?id=1",
    resolved_url: "https://cdn.example.com/final.mp4?token=abc"
  },
  note_path: "D:/note.md",
  download_attempts: [{ strategy: "direct-file", code: "download_forbidden" }]
}), /final\.mp4\?token=abc/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: { kind: "video", source: "webRequest" },
  note_path: "D:/note.md",
  download_attempts: []
}), /已有笔记/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: { kind: "video", source: "webRequest" },
  note_path: "D:/note.md",
  download_attempts: []
}), /未记录总结诊断/);

const rerunRouteEvidenceHtml = context.taskRouteEvidenceHtml({
  mode: "rerun_from_media",
  source_type: "local",
  source_task_id: "download-only-task<script>bad()</script>",
  source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4",
  reuse: {
    source_task_id: "download-only-task<script>bad()</script>",
    source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4"
  },
  media_path: "D:/Projects/learnnote-assistant/data/tasks/rerun-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/rerun-task/note.md",
  selected_resource: { kind: "video", source: "webRequest" },
  download_attempts: [{ strategy: "direct-file", status: "success" }]
});
assert.match(rerunRouteEvidenceHtml, /复用来源/);
assert.match(rerunRouteEvidenceHtml, /download-only-task/);
assert.match(rerunRouteEvidenceHtml, /media\.mp4/);
assert.match(rerunRouteEvidenceHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(rerunRouteEvidenceHtml, /<script>bad/);

const routeDownloadedHtml = context.browserRouteSummaryHtml({
  id: "route-downloaded",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/route-downloaded/media.mp4",
  note_path: "",
  selected_resource: { kind: "video" },
  download_attempts: [{ strategy: "direct-file" }]
});
assert.match(routeDownloadedHtml, /browser-route-summary-card downloaded/);
assert.match(routeDownloadedHtml, /视频已直取到本地/);
assert.match(routeDownloadedHtml, /继续切片总结/);

const routeBlockedHtml = context.browserRouteSummaryHtml({
  id: "route-blocked",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  error_code: "drm_or_encrypted",
  error_detail: "<script>bad()</script> encrypted"
});
assert.match(routeBlockedHtml, /browser-route-summary-card blocked/);
assert.match(routeBlockedHtml, /不会录制或绕过 DRM/);
assert.match(routeBlockedHtml, /本地视频兜底/);
assert.match(routeBlockedHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; encrypted/);
assert.doesNotMatch(routeBlockedHtml, /<script>bad/);

const browserWorkflowHtml = context.sourceWorkflowHtml("browser", {
  id: "task-workflow-browser",
  title: "Current page lesson",
  status: "running",
  phase: "downloading",
  progress: 35,
  source_type: "current_page",
  selected_resource: { kind: "hls" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: []
});
assert.match(browserWorkflowHtml, /class="source-workflow-card browser"/);
assert.match(browserWorkflowHtml, /当前页直取/);
assert.match(browserWorkflowHtml, /source-workflow-brief/);
assert.match(browserWorkflowHtml, /学习流总览/);
assert.match(browserWorkflowHtml, /打开扩展侧栏总结当前页|downloading · 35%/);
assert.match(browserWorkflowHtml, /source-run-modes/);
assert.match(browserWorkflowHtml, /完整笔记/);
assert.match(browserWorkflowHtml, /只下载/);
assert.match(browserWorkflowHtml, /继续切片/);
assert.match(browserWorkflowHtml, /非录制直取/);
assert.match(browserWorkflowHtml, /预检资源/);
assert.match(browserWorkflowHtml, /source-route-insights/);
assert.match(browserWorkflowHtml, /浏览器证据/);
assert.match(browserWorkflowHtml, /ffmpeg 合并|页面接口|候选资源|HLS|hls/);
assert.match(browserWorkflowHtml, /不录制、不刷课、不绕过 DRM/);
assert.match(browserWorkflowHtml, /source-workflow-actions/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="refresh-browser"/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="copy-backend"/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="switch-local"/);
assert.match(browserWorkflowHtml, /class="active"/);
assert.match(browserWorkflowHtml, /data-select-workflow-task="task-workflow-browser"/);

vm.runInContext(`tasks = ${JSON.stringify([
  {
    id: "rail-browser",
    title: "Current page rail",
    status: "running",
    phase: "downloading",
    progress: 42,
    source_type: "current_page",
    selected_resource: { kind: "hls", source: "webRequest" }
  },
  {
    id: "rail-local",
    title: "Local rail",
    status: "success",
    phase: "completed",
    progress: 100,
    source_type: "local",
    media_path: "D:/Projects/learnnote-assistant/data/tasks/rail-local/media.mp4",
    note_path: "D:/Projects/learnnote-assistant/data/tasks/rail-local/note.md",
    visual_windows: [{ id: "W001" }]
  },
  {
    id: "rail-url",
    title: "Bad <script>",
    status: "failed",
    phase: "failed",
    progress: 100,
    source_type: "current_page",
    error_code: "download_forbidden",
    selected_resource: { kind: "video", source: "manual", request_type: "manual-forced" }
  }
])};`, context);
const routeRailHtml = context.sourceRouteRailHtml();
assert.match(routeRailHtml, /data-source-route="browser"/);
assert.match(routeRailHtml, /data-task-id="rail-browser"/);
assert.match(routeRailHtml, />42%<\/small>/);
assert.match(routeRailHtml, /class="source-route-item ready"/);
assert.match(routeRailHtml, /已成稿/);
assert.match(routeRailHtml, /class="source-route-item blocked"/);
assert.match(routeRailHtml, /download_forbidden/);
assert.doesNotMatch(routeRailHtml, /<script>/);
vm.runInContext(`tasks = [];`, context);

const localWorkflowHtml = context.sourceWorkflowHtml("local", null);
assert.match(localWorkflowHtml, /本地视频/);
assert.match(localWorkflowHtml, /source-workflow-brief/);
assert.match(localWorkflowHtml, /source-run-modes/);
assert.match(localWorkflowHtml, /选择文件/);
assert.match(localWorkflowHtml, /离线兜底/);
assert.match(localWorkflowHtml, /导入文件/);
assert.match(localWorkflowHtml, /本地文件直进管线/);
assert.match(localWorkflowHtml, /平台不暴露 URL 时兜底/);
assert.match(localWorkflowHtml, /data-source-workflow-action="choose-local"/);
assert.match(localWorkflowHtml, /data-source-workflow-action="upload-local"/);
assert.match(localWorkflowHtml, /选择入口后开始处理/);

const urlWorkflowHtml = context.sourceWorkflowHtml("url", {
  id: "task-workflow-url",
  title: "Manual lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  selected_resource: { kind: "dash", source: "manual", request_type: "manual-forced" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }, { strategy: "direct-file" }],
  visual_windows: [{ id: "W001" }, { id: "W002" }]
});
assert.match(urlWorkflowHtml, /链接解析/);
assert.match(urlWorkflowHtml, /source-workflow-brief/);
assert.match(urlWorkflowHtml, /source-run-modes/);
assert.match(urlWorkflowHtml, /生成新的链接笔记/);
assert.match(urlWorkflowHtml, /先把视频拉到本地/);
assert.match(urlWorkflowHtml, /查看笔记和资料包/);
assert.match(urlWorkflowHtml, /可预检链接/);
assert.match(urlWorkflowHtml, /2 次下载尝试/);
assert.match(urlWorkflowHtml, /2 个视觉窗口/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="preflight-url"/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="start-url"/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="download-url"/);

const failedWorkflowHtml = context.sourceWorkflowHtml("browser", {
  id: "task-workflow-failed",
  title: "Blocked page",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  selected_resource: { kind: "blob" },
  download_attempts: []
});
assert.match(failedWorkflowHtml, /class="blocked"/);
assert.match(failedWorkflowHtml, /DRM/);

const routeEmptyHtml = context.browserRouteSummaryHtml(null);
assert.match(routeEmptyHtml, /等待扩展侧栏创建当前页任务/);
assert.match(routeEmptyHtml, /不做标签页录制/);
assert.match(routeEmptyHtml, /data-browser-route-action="refresh"/);
assert.match(routeEmptyHtml, /data-browser-route-action="copy-backend"/);
assert.match(routeEmptyHtml, /data-browser-route-action="local-video"/);
const emptyWorkflowHtml = context.sourceWorkflowActionsHtml("browser", null);
assert.match(emptyWorkflowHtml, /data-source-workflow-action="open-extension"/);
assert.match(emptyWorkflowHtml, /去扩展侧栏开始/);
assert.match(emptyWorkflowHtml, /刷新交接状态/);
assert.match(emptyWorkflowHtml, /上传本地视频兜底/);

const downloadOnlyRunModesHtml = context.sourceRunModesHtml("browser", {
  id: "task-workflow-download-only",
  title: "Downloaded lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-workflow-download-only/media.mp4",
  selected_resource: { kind: "hls" },
  visual_windows: []
});
assert.match(downloadOnlyRunModesHtml, /media\.mp4 已保存/);
assert.match(downloadOnlyRunModesHtml, /从 media\.mp4 继续/);
assert.match(downloadOnlyRunModesHtml, /data-source-workflow-action="continue-media"/);
assert.match(downloadOnlyRunModesHtml, /data-task-id="task-workflow-download-only"/);

const urlRunModesHtml = context.sourceRunModesHtml("url", null);
assert.match(urlRunModesHtml, /data-source-workflow-action="start-url"/);
assert.match(urlRunModesHtml, /data-source-workflow-action="download-url"/);
assert.match(urlRunModesHtml, /生成新的链接笔记/);

const timelineHtml = context.transcriptTimeline({
  segments: [
    { start: 5, end: 8, text: "第一段字幕" },
    { start: 190, end: 196, text: "<script>alert(1)</script>" }
  ]
}, {
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: ""
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_001.jpg",
      transcript_excerpt: ""
    }
  ]
});

assert.match(timelineHtml, /class="transcript-timeline"/);
assert.match(timelineHtml, /字幕时间轴/);
assert.match(timelineHtml, /已按画面窗口对齐/);
assert.match(timelineHtml, /2<\/b>段字幕/);
assert.match(timelineHtml, /W001/);
assert.match(timelineHtml, /00:00:00 - 00:03:00/);
assert.match(timelineHtml, /第一段字幕/);
assert.match(timelineHtml, /W002/);
assert.match(timelineHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(timelineHtml, /<script>/);

const plainTimelineHtml = context.transcriptTimeline({
  source: "browser-subtitle",
  segments: [
    { start: 10, end: 13, text: "兜底字幕一" },
    { start: 20, end: 25, text: "兜底字幕二" }
  ]
}, {
  visual_windows: []
});
assert.match(plainTimelineHtml, /浏览器字幕/);
assert.match(plainTimelineHtml, /独立字幕时间轴/);
assert.match(plainTimelineHtml, /无切片/);
assert.match(plainTimelineHtml, /兜底字幕一/);
assert.equal(context.transcriptSourceText("embedded-subtitle"), "视频内嵌字幕");
const embeddedTimelineHtml = context.transcriptTimeline({
  source: "embedded-subtitle",
  segments: [
    { start: 0, end: 2, text: "内嵌字幕" }
  ]
}, {
  visual_windows: []
});
assert.match(embeddedTimelineHtml, /视频内嵌字幕/);

const preflightedUrlResource = {
  url: "https://course.example.com/api/play",
  source: "manual",
  kind: "video",
  mime: "video/mp4",
  headers: {}
};
context.rememberUrlPreflight(preflightedUrlResource, {
  downloadable: true,
  strategy: "direct-response-probe",
  kind: "hls",
  resolved_url: "https://cdn.example.com/lesson/master.m3u8",
  content_type: "application/json"
});
assert.equal(preflightedUrlResource.kind, "hls");
assert.equal(preflightedUrlResource.mime, "application/vnd.apple.mpegurl");
assert.equal(preflightedUrlResource.resolved_url, "https://cdn.example.com/lesson/master.m3u8");
assert.equal(preflightedUrlResource.headers["content-type"], "application/json");

const posts = [];
const preflights = [];
const pagePreflights = [];
let preflightDownloadable = true;
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-current-page")) {
    posts.push(JSON.parse(options.body));
    return { json: async () => ({ task_id: "task-url-direct" }) };
  }
  if (value.endsWith("/api/media/preflight")) {
    preflights.push(JSON.parse(options.body));
    return {
      json: async () => ({
        preflight: preflightDownloadable ? {
          ok: true,
          downloadable: true,
          strategy: "direct-response-probe",
          kind: "hls",
          resolved_url: "https://cdn.example.com/archive/master.m3u8",
          content_type: "application/vnd.apple.mpegurl",
          status_code: 206,
          content_length: 123456,
          bytes_checked: 4096
        } : {
          ok: false,
          downloadable: false,
          code: "download_forbidden",
          message: "HTTP 403：Referer 或签名已过期"
        }
      })
    };
  }
  if (value.endsWith("/api/media/preflight-current-page")) {
    pagePreflights.push(JSON.parse(options.body));
    return {
      json: async () => ({
        report: {
          ok: true,
          ready: true,
          selected_url: "https://cdn.example.com/page/master.m3u8",
          candidate_count: 5,
          probed_count: 3,
          downloadable_count: 2,
          message: "page preflight ok",
          page_scan: {
            attempted: true,
            discovered_count: 4,
            attempts: []
          },
          candidates: [{
            rank: 1,
            resource: {
              url: "https://cdn.example.com/page/master.m3u8",
              source: "page-scan",
              kind: "hls",
              mime: "application/vnd.apple.mpegurl",
              score: 92
            },
            preflight: {
              ok: true,
              downloadable: true,
              strategy: "manifest-probe",
              kind: "hls",
              resolved_url: "https://media.example.com/page/final-master.m3u8",
              status_code: 200,
              content_type: "application/vnd.apple.mpegurl",
              content_length: 654321
            }
          }]
        }
      })
    };
  }
  if (value.endsWith("/api/tasks/task-url-direct")) {
    return { json: async () => ({ task: { id: "task-url-direct", status: "queued", phase: "downloading", progress: 0, source_type: "url" } }) };
  }
  if (value.endsWith("/api/tasks")) {
    return { json: async () => ({ tasks: [{ id: "task-url-direct", status: "queued", phase: "downloading", progress: 0, source_type: "url" }] }) };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#urlInput").value = "https://cdn.example.com/api/play?id=shadow";
elements.get("#urlMode").value = "video";
elements.get("#titleInput").value = "无后缀直连课件";
await context.startUrlTask("video");

assert.equal(posts.length, 1);
assert.equal(context.window.history.replacedUrls.at(-1), "/?task=task-url-direct&tab=note");
context.switchResultTab("frames");
assert.equal(context.window.history.replacedUrls.at(-1), "/?task=task-url-direct&tab=frames");
assert.equal(resultTabs.find(tab => tab.dataset.tab === "frames").getAttribute("aria-selected"), "true");
assert.equal(resultTabs.find(tab => tab.dataset.tab === "note").getAttribute("aria-selected"), "false");
assert.equal(posts[0].mode, "video");
assert.equal(posts[0].resources.length, 1);
assert.equal(posts[0].resources[0].kind, "video");
assert.equal(posts[0].resources[0].source, "manual");
assert.equal(posts[0].resources[0].request_type, "manual-forced");
assert.equal(posts[0].resources[0].url, "https://cdn.example.com/api/play?id=shadow");

elements.get("#urlInput").value = "https://cdn.example.com/live/lesson.flv?token=abc";
elements.get("#urlMode").value = "auto";
await context.startUrlTask("video");

assert.equal(posts.length, 2);
assert.equal(posts[1].resources.length, 1);
assert.equal(posts[1].resources[0].kind, "video");
assert.equal(posts[1].resources[0].url, "https://cdn.example.com/live/lesson.flv?token=abc");

elements.get("#urlInput").value = "https://cdn.example.com/archive/lesson.avi?token=abc";
elements.get("#urlMode").value = "auto";
await context.startUrlTask("video");

assert.equal(posts.length, 3);
assert.equal(posts[2].resources.length, 1);
assert.equal(posts[2].resources[0].kind, "video");
assert.equal(posts[2].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");

await context.startUrlTask("download_only");

assert.equal(posts.length, 4);
assert.equal(posts[3].mode, "download_only");
assert.equal(posts[3].resources.length, 1);
assert.equal(posts[3].resources[0].kind, "video");
assert.equal(posts[3].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.equal(elements.get("#downloadUrlButton").disabled, false);

await context.preflightUrlTask();

assert.equal(preflights.length, 1);
assert.equal(preflights[0].resource.kind, "video");
assert.equal(preflights[0].resource.request_type, "manual-auto");
assert.equal(preflights[0].resource.url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.match(elements.get("#urlModeHint").textContent, /预检通过/);
assert.match(elements.get("#urlModeHint").textContent, /120\.6 KB/);
assert.match(elements.get("#urlModeHint").textContent, /目标：https:\/\/cdn\.example\.com\/archive\/master\.m3u8/);
assert.equal(elements.get("#urlPreflightReport").hidden, false);
assert.match(elements.get("#urlPreflightReport").className, /pass/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /可直取/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /HLS/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /直连响应探测/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /206/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /120\.6 KB/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /master\.m3u8/);
assert.equal(elements.get("#preflightUrlButton").disabled, false);

await context.startUrlTask("video");

assert.equal(posts.length, 5);
assert.equal(posts[4].resources.length, 1);
assert.equal(posts[4].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.equal(posts[4].resources[0].kind, "hls");
assert.equal(posts[4].resources[0].resolved_url, "https://cdn.example.com/archive/master.m3u8");
assert.equal(posts[4].resources[0].mime, "application/vnd.apple.mpegurl");
assert.equal(posts[4].resources[0].status_code, 206);
assert.equal(posts[4].resources[0].content_length, 123456);

preflightDownloadable = false;
await context.preflightUrlTask();

assert.equal(preflights.length, 2);
assert.match(elements.get("#urlModeHint").textContent, /预检未通过/);
assert.match(elements.get("#urlModeHint").textContent, /HTTP 403/);
assert.match(elements.get("#urlPreflightReport").className, /fail/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /未通过/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /HTTP 403/);
assert.doesNotMatch(elements.get("#urlPreflightReport").innerHTML, /master\.m3u8/);

elements.get("#urlInput").value = "https://course.example.com/watch?id=page-preflight";
elements.get("#urlMode").value = "page";
await context.preflightUrlTask();

assert.equal(pagePreflights.length, 1);
assert.equal(pagePreflights[0].page_url, "https://course.example.com/watch?id=page-preflight");
assert.equal(pagePreflights[0].resources.length, 0);
assert.equal(pagePreflights[0].probe_limit, 3);
assert.match(elements.get("#urlPreflightReport").className, /pass/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /2\/5/);
assert.match(elements.get("#urlPreflightReport").innerHTML, /page\/final-master\.m3u8/);

await context.startUrlTask("video");

assert.equal(posts.length, 6);
assert.equal(posts[5].page_url, "https://course.example.com/watch?id=page-preflight");
assert.equal(posts[5].resources.length, 1);
assert.equal(posts[5].resources[0].url, "https://cdn.example.com/page/master.m3u8");
assert.equal(posts[5].resources[0].kind, "hls");
assert.equal(posts[5].resources[0].resolved_url, "https://media.example.com/page/final-master.m3u8");
assert.equal(posts[5].resources[0].mime, "application/vnd.apple.mpegurl");
assert.equal(posts[5].resources[0].status_code, 200);
assert.equal(posts[5].resources[0].content_length, 654321);
assert.equal(posts[5].resources[0].request_type, "manual-page-preflight");
assert.equal(posts[5].resources[0].page_url, "https://course.example.com/watch?id=page-preflight");

const localUploads = [];
const droppedFile = { name: "drag-local-lesson.mkv", type: "", size: 456789 };
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-local")) {
    localUploads.push(options.body);
    return { json: async () => ({ task_id: "task-local-drop" }) };
  }
  if (value.endsWith("/api/tasks")) {
    return {
      json: async () => ({
        tasks: [{
          id: "task-local-drop",
          title: "drag-local-lesson.mkv",
          status: "queued",
          phase: "queued",
          progress: 0,
          source_type: "local",
          visual_windows: []
        }]
      })
    };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

await elements.get("#dropzone").listeners.drop({
  preventDefault() {},
  dataTransfer: { files: [droppedFile] }
});
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(localUploads.length, 1);
assert.equal(elements.get("#fileInput").files.length, 0);
assert.equal(localUploads[0].get("file"), droppedFile);
assert.equal(localUploads[0].get("title"), "drag-local-lesson.mkv");
assert.match(localUploads[0].get("options"), /"visual_understanding":true/);
assert.equal(elements.get("#fileName").textContent, "drag-local-lesson.mkv");
assert.equal(elements.get("#uploadButton").disabled, false);

let rerunPayload = null;
elements.get("#frameInterval").value = "0";
elements.get("#gridSize").value = "7xnope";
let boundedOptions = context.readOptions();
assert.equal(boundedOptions.frame_interval, 1);
assert.equal(boundedOptions.grid_columns, 6);
assert.equal(boundedOptions.grid_rows, 3);
assert.match(context.visualPlanText(), /1秒 · 6x3/);
elements.get("#frameInterval").value = "30";
elements.get("#gridSize").value = "4x3";
elements.get("#noteTemplate").value = "cornell";
elements.get("#llmProvider").value = "groq";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.groq.com/openai/v1");
assert.equal(elements.get("#llmModel").value, "meta-llama/llama-4-scout-17b-16e-instruct");
assert.equal(elements.get("#transcriber").value, "groq");
assert.equal(elements.get("#whisperModel").value, "whisper-large-v3");
elements.get("#llmApiKey").value = "sk-rerun";
context.saveModelSettings();
const savedModelSettings = JSON.parse(context.window.localStorage.getItem("learnnote_model_settings"));
assert.equal(savedModelSettings.llm_provider, "groq");
assert.equal(savedModelSettings.llm_base_url, "https://api.groq.com/openai/v1");
assert.equal(savedModelSettings.llm_model, "meta-llama/llama-4-scout-17b-16e-instruct");
assert.equal(savedModelSettings.transcriber, "groq");
assert.equal(savedModelSettings.whisper_model, "whisper-large-v3");
assert.equal(Object.hasOwn(savedModelSettings, "llm_api_key"), false);
assert.equal(JSON.stringify(savedModelSettings).includes("sk-rerun"), false);
elements.get("#transcriber").value = "openai-compatible";
elements.get("#whisperModel").value = "whisper-1";
elements.get("#llmModel").value = "vision-rerun";
elements.get("#llmBaseUrl").value = "https://models.example/v1";
elements.get("#visualUnderstanding").checked = false;
elements.get("#visualUnderstanding").listeners.change();
assert.match(elements.get("#sourceWorkflow").innerHTML, /\u65e0\u89c6\u89c9/);
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/source-media-task/rerun-from-media")) {
    rerunPayload = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({
        task_id: "rerun-task",
        source_task_id: "source-media-task",
        task: {
          id: "rerun-task",
          source_task_id: "source-media-task",
          source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/media.mp4"
        }
      })
    };
  }
  if (value.endsWith("/api/tasks")) {
    return {
      json: async () => ({
        tasks: [{
          id: "rerun-task",
          title: "rerun",
          status: "queued",
          phase: "queued",
          progress: 0,
          source_type: "local",
          source_task_id: "source-media-task",
          source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/media.mp4",
          reuse: {
            source_task_id: "source-media-task",
            source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/media.mp4"
          },
          visual_windows: []
        }]
      })
    };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};
await context.rerunTaskFromMedia("source-media-task");
assert.equal(rerunPayload.frame_interval, 30);
assert.equal(rerunPayload.grid_columns, 4);
assert.equal(rerunPayload.grid_rows, 3);
assert.equal(rerunPayload.note_template, "cornell");
assert.equal(rerunPayload.visual_understanding, false);
assert.equal(rerunPayload.llm_model, "vision-rerun");
assert.equal(rerunPayload.llm_base_url, "https://models.example/v1");
assert.equal(rerunPayload.llm_api_key, "sk-rerun");
const rerunMetaHtml = context.resultMetaChipsHtml({
  id: "rerun-task",
  status: "queued",
  phase: "queued",
  progress: 0,
  source_type: "local",
  source_task_id: "source-media-task",
  source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/media.mp4",
  reuse: {
    source_task_id: "source-media-task",
    source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/media.mp4"
  },
  options: { visual_understanding: false },
  visual_windows: []
});
const rerunNotice = context.rerunFromMediaNotice("source-media-task", "rerun-task");
assert.match(rerunMetaHtml, /复用/);
assert.match(rerunMetaHtml, /已下载媒体/);
assert.match(rerunNotice, /完整笔记任务 rerun-task/);
assert.match(rerunNotice, /不会录制页面/);

let rejectedUploadCalled = false;
context.fetch = async url => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-local")) {
    rejectedUploadCalled = true;
    return {
      ok: false,
      json: async () => ({
        detail: {
          code: "unsupported_local_file",
          message: "本地视频仅支持 mp4、m4v、mov、mkv、webm、flv、avi。"
        }
      })
    };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#fileInput").files = [{ name: "server-reject.mov", type: "video/quicktime", size: 128 }];
await context.uploadSelectedFile();

assert.equal(rejectedUploadCalled, true);
assert.match(elements.get("#fileName").textContent, /本地视频仅支持/);
assert.equal(elements.get("#uploadButton").disabled, false);

let unsupportedFetchCalled = false;
context.fetch = async () => {
  unsupportedFetchCalled = true;
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#fileInput").files = [{ name: "notes.txt", type: "text/plain", size: 64 }];
await context.uploadSelectedFile();

assert.equal(unsupportedFetchCalled, false);
assert.match(elements.get("#fileName").textContent, /暂不支持/);
