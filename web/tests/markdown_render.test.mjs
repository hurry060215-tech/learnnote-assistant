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
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true, ffprobe: false, ffprobe_optional: true, duration_probe: "ffmpeg", yt_dlp_available: true, yt_dlp_package_available: true, vision_model_configured: false, default_llm_model: "gpt-4.1-mini", default_llm_provider: "openai", default_llm_base_host: "api.openai.com", data_paths: { root: "D:\\Projects\\learnnote-assistant\\data", data_drive: "D:", all_under_data_dir: true, all_on_data_drive: true, paths: { tasks: "D:\\Projects\\learnnote-assistant\\data\\tasks" } }, model_provider_presets: [
      { key: "openai", label: "OpenAI 官方", base_url: "https://api.openai.com/v1", model: "gpt-4.1-mini", transcriber: "openai-compatible", whisper_model: "whisper-1", tier: "mainstream", recommended: true, capabilities: ["text", "vision", "asr"] },
      { key: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4.1-mini", transcriber: "faster-whisper", whisper_model: "small", tier: "compatible", recommended: false, capabilities: ["text", "vision"] }
    ] }) };
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
const workspaceCss = await readFile(new URL("../workspace.css", import.meta.url), "utf8");
const productCss = await readFile(new URL("../product.css", import.meta.url), "utf8");
const matureCss = await readFile(new URL("../mature.css", import.meta.url), "utf8");
vm.runInContext(webCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
await new Promise(resolve => setTimeout(resolve, 0));
const settingsButtons = ["general", "connection"].map(name => {
  const element = makeElement();
  element.dataset.settingsTab = name;
  return element;
});
const settingsPanes = ["general", "connection"].map(name => {
  const element = makeElement();
  element.dataset.settingsPane = name;
  return element;
});
context.settingsButtons = settingsButtons;
context.settingsPanes = settingsPanes;
vm.runInContext("els.settingsMenuButtons = settingsButtons; els.settingsPanes = settingsPanes;", context);
context.showAppView("settings");
context.showSettingsPane("connection");
context.showAppView("settings");
assert.equal(settingsButtons[1].classList.contains("active"), true);
assert.equal(settingsPanes[1].classList.contains("active"), true);
assert.equal(elements.get("#health").textContent, "本地服务已连接");
assert.equal(context.normalizeApiBase(" http://127.0.0.1:8765/ "), "http://127.0.0.1:8765");
assert.equal(context.normalizeApiBase("https://example.com"), "");
assert.equal(context.resolveApiBase({ protocol: "http:", hostname: "127.0.0.1", port: "8765" }, null), "");
assert.equal(context.resolveApiBase({ protocol: "http:", hostname: "127.0.0.1", port: "8766" }, null), "");
assert.equal(context.resolveApiBase({ protocol: "https:", hostname: "learnnote.example", port: "" }, null), "");
assert.equal(context.resolveApiBase({ protocol: "file:", hostname: "", port: "" }, null), "http://127.0.0.1:8765");
assert.equal(context.resolveApiBase(
  { protocol: "http:", hostname: "127.0.0.1", port: "8878" },
  { getItem: () => "http://localhost:9000/" }
), "http://localhost:9000");
assert.match(indexHtml, /id="startupReadiness"/);
assert.equal(context.safeNoteMediaUrl("/api/tasks/task-web/assets/grid_001.jpg"), "http://127.0.0.1:8765/api/tasks/task-web/assets/grid_001.jpg");
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
  { id: "older-full-note", status: "success", source_type: "current_page", created_at: "2026-07-10T10:00:00Z", media_path: "media.mp4", note_path: "note.md" },
  { id: "latest-download", status: "success", source_type: "current_page", created_at: "2026-07-12T10:00:00Z", media_path: "media.mp4", mode: "download_only" }
]).id, "latest-download");
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
assert.match(matureCss, /@media \(max-width: 680px\)[\s\S]*body\.settings-mode \.nav-rail[\s\S]*top:\s*auto !important;[\s\S]*height:\s*58px !important;/);
assert.match(webCode, /function isActiveTask\(task\)[\s\S]*ACTIVE_TASK_STATUSES\.has/);
assert.match(webCode, /function extensionVersionMatches\(data = lastHealthData\)/);
assert.equal(context.extensionVersionMatches({ app_version: "0.1.32", extension_version: "0.1.32" }), true);
assert.equal(context.extensionVersionMatches({ app_version: "0.1.32", extension_version: "0.1.31" }), false);
assert.match(webCode, /const activeTasks = tasks\.filter\(isActiveTask\)/);
assert.match(webCode, /if \(appSettings\.autoOpenNote[\s\S]*showAppView\("notes"\);[\s\S]*selectTask\(latest\.id\)/);
assert.doesNotMatch(webCode, /task\.evidence_quality\?\.can_claim_video_content === false\) return;/);
assert.match(webCode, /const response = await fetch\(apiUrl\(`\/api\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/exports\/\$\{exportType\}`\)\)[\s\S]*if \(!response\.ok\)[\s\S]*await response\.blob\(\)/);
assert.match(webCode, /if \(taskListLoadPromise\) return taskListLoadPromise/);
assert.match(webCode, /const taskListChanged = nextTaskListFingerprint !== lastTaskListFingerprint/);
assert.match(webCode, /if \(taskListChanged\) \{\s*renderTasks\(\);\s*lastTaskListFingerprint = nextTaskListFingerprint;/);
assert.equal(context.taskListFingerprint([{ id: "stable", status: "success", progress: 100, updated_at: "1" }]), context.taskListFingerprint([{ id: "stable", status: "success", progress: 100, updated_at: "1" }]));
assert.notEqual(context.taskListFingerprint([{ id: "active", status: "running", progress: 30, updated_at: "1" }]), context.taskListFingerprint([{ id: "active", status: "running", progress: 31, updated_at: "2" }]));
assert.doesNotMatch(webCode, /catch \{\s*tasks = \[\];\s*selectedTaskId = null;/);
assert.equal(elements.get("#browserBridgeStatus").classList.contains("capture-status-grid"), true);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip bridge/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /打开课程视频，再点击 LearnNote 扩展图标/);
assert.doesNotMatch(elements.get("#browserBridgeStatus").innerHTML, /ffmpeg|ffprobe|m3u8|mpd|DRM|ASR|Cookie/);
assert.match(elements.get("#startupReadiness").innerHTML, /启动就绪/);
assert.match(elements.get("#startupReadiness").innerHTML, /增强项待配置|本机学习助手已就绪/);
assert.match(elements.get("#startupReadiness").innerHTML, /本地后端/);
assert.match(elements.get("#startupReadiness").innerHTML, /ffmpeg/);
assert.match(elements.get("#startupReadiness").innerHTML, /yt-dlp/);
assert.match(elements.get("#startupReadiness").innerHTML, /Python 包可用/);
assert.match(elements.get("#startupReadiness").innerHTML, /D:\\Projects\\learnnote-assistant\\extension/);
assert.match(elements.get("#startupReadiness").innerHTML, /data-startup-action="copy-backend"/);
assert.match(elements.get("#startupReadiness").innerHTML, /data-startup-action="open-options"/);
assert.match(context.startupReadinessHtml({ ffmpeg: false, yt_dlp_available: false, data_paths: null }), /必需项未就绪/);
context.updateHealthVisionStatus({
  ffmpeg: true,
  ffprobe_optional: true,
  default_llm_model: "gpt-4.1-mini",
  default_llm_provider: "openai",
  default_llm_base_host: "api.openai.com"
});
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip bridge pending/);
assert.match(elements.get("#browserBridgeStatus").innerHTML, /点击 LearnNote 扩展图标/);
assert.doesNotMatch(elements.get("#browserBridgeStatus").innerHTML, /data · 待检测|路径异常/);
assert.match(elements.get("#detail").innerHTML, /class="empty-workbench"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-demo-board"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-quick-routes"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-production-brief"/);
assert.match(elements.get("#detail").innerHTML, /Markdown · 诊断 · 资料包/);
assert.match(elements.get("#detail").innerHTML, /当前页直取/);
assert.match(elements.get("#detail").innerHTML, /读取正在播放的视频/);
assert.match(elements.get("#detail").innerHTML, /拖入文件直接切片/);
assert.match(elements.get("#detail").innerHTML, /粘贴页面或媒体链接/);
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
assert.match(stylesCss, /Compact BiliNote-style left workbench/);
assert.match(stylesCss, /\.workspace-panel #sourceWorkflow\s*\{\s*order: 3;/);
assert.match(stylesCss, /\.workspace-panel \.source-pane\s*\{\s*order: 4;/);
assert.match(stylesCss, /\.workspace-panel \.source-route-rail\s*\{\s*display: none;/);
assert.match(stylesCss, /\.capture-flow\s*\{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(indexHtml, /id="toggleWorkspaceButton"/);
assert.match(indexHtml, /id="deleteAllTasksButton"/);
assert.match(indexHtml, /id="deleteAllTasksSettingsButton"/);
assert.match(webCode, /\/api\/tasks\?confirm=delete_all_tasks/);
assert.match(matureCss, /\.danger-button\s*\{/);
assert.match(indexHtml, /styles\.css\?v=20260714-v0124/);
assert.match(indexHtml, /app\.js\?v=20260721-v0132/);
assert.match(indexHtml, /mature\.css\?v=20260721-v0132/);
assert.match(indexHtml, /id="sourceRouteRail"/);
assert.match(indexHtml, /id="urlPreflightReport"/);
assert.match(indexHtml, /href="#settingsView" data-app-view="settings" title="设置"/);
assert.doesNotMatch(indexHtml, /href="#settings" title="设置"/);
assert.match(indexHtml, /workspace\.css\?v=20260714-v0124/);
assert.match(indexHtml, /product\.css\?v=20260714-v0124/);
assert.match(indexHtml, /<body data-app-view="workspace">/);
assert.match(indexHtml, /进入笔记时收起笔记列表/);
assert.doesNotMatch(indexHtml, /id="settingCompactHistory" type="checkbox" checked/);
assert.match(indexHtml, /id="settingsView"/);
assert.match(indexHtml, /data-settings-tab="general"/);
assert.match(indexHtml, /data-settings-tab="model"/);
assert.match(indexHtml, /data-settings-tab="transcriber"/);
assert.match(indexHtml, /data-settings-tab="processing"/);
assert.match(workspaceCss, /body\.queue-collapsed \.queue-panel\s*\{\s*display: none;/);
assert.match(workspaceCss, /body\.settings-mode \.workspace-panel/);
assert.match(indexHtml, /id="downloadUrlButton"[\s\S]*只下载到本地/);
assert.doesNotMatch(indexHtml, />只下载本地</);
assert.match(indexHtml, /class="result-tab active" role="tab" aria-selected="true" data-tab="note"/);
assert.match(indexHtml, /class="result-tab" role="tab" aria-selected="false" data-tab="slices">画面与时间轴/);
assert.doesNotMatch(indexHtml, /data-tab="qa">问这节课/);
assert.match(indexHtml, /id="aiAssistantDrawer"/);
assert.match(webCode, /function assistantTaskKindLabel\(task\)/);
vm.runInContext(`document.body.classList.add("queue-collapsed", "workspace-collapsed", "reading-mode"); showAppView("notes");`, context);
assert.equal(context.document.body.classList.contains("queue-collapsed"), false);
assert.equal(context.document.body.classList.contains("workspace-collapsed"), false);
assert.equal(context.document.body.classList.contains("reading-mode"), false);
assert.equal(context.assistantTaskKindLabel({ evidence_quality: { video_evidence: "invalid", can_claim_video_content: false } }), "视频来源无效");
assert.match(context.noteEvidenceNoticeHtml({ evidence_quality: { video_evidence: "invalid", can_claim_video_content: false } }), /保存的不是视频/);
assert.match(context.noteProvenanceHtml({ evidence_quality: { video_evidence: "invalid", has_media: false } }), /无效文件/);
assert.match(matureCss, /\.nav-rail,[\s\S]*min-width:\s*var\(--mature-nav\) !important;[\s\S]*max-width:\s*var\(--mature-nav\) !important;/);
assert.match(matureCss, /\.nav-item,[\s\S]*width:\s*168px !important;[\s\S]*max-width:\s*168px !important;/);
assert.match(webCode, /页面文本笔记/);
assert.match(webCode, /已连接视频证据/);
assert.match(webCode, /这不是完整的视频笔记/);
assert.match(webCode, /当前笔记缺少可核对的视频证据/);
assert.match(matureCss, /box-shadow: inset 3px 0 0 var\(--mature-teal\)/);
assert.match(matureCss, /\.task-headline > strong[\s\S]*overflow-wrap: anywhere/);
assert.match(indexHtml, /id="openAiAssistantButton"[\s\S]*AI 助教/);
assert.match(indexHtml, /id="expandAiAssistantButton"/);
assert.match(indexHtml, /id="assistantGroundingState"/);
assert.doesNotMatch(indexHtml, /data-tab="qa"|data-open-assistant/);
assert.match(webCode, /if \(taskRoute\) showAppView\("notes"\)/);
assert.match(webCode, /assistantContextTaskId = task\?\.id \|\| ""/);
assert.match(webCode, /assistantOpenPreference\(\) === true/);
assert.match(indexHtml, /class="result-tab" role="tab" aria-selected="false" data-tab="diagnostics">处理检查/);
assert.match(indexHtml, /id="onboardingOverlay"/);
assert.match(indexHtml, /id="openOnboardingButton"/);
assert.match(indexHtml, /id="installUpdateButton"[\s\S]*下载并安装/);
assert.match(indexHtml, /id="llmProvider"/);
assert.match(indexHtml, /value="kimi" selected>Kimi/);
assert.match(indexHtml, /id="recentNotesRail"/);
assert.match(indexHtml, /value="gemini">Google Gemini/);
assert.match(indexHtml, /value="dashscope">/);
assert.match(indexHtml, /value="deepseek">DeepSeek/);
assert.match(indexHtml, /value="kimi" selected>Kimi/);
assert.match(indexHtml, /value="zhipu">/);
assert.match(indexHtml, /value="doubao">/);
assert.match(indexHtml, /value="minimax">MiniMax/);
assert.match(indexHtml, /value="qianfan">/);
assert.doesNotMatch(indexHtml, /value="siliconflow"/);
assert.doesNotMatch(indexHtml, /value="openrouter"/);
assert.doesNotMatch(indexHtml, /value="local-openai"/);
assert.match(indexHtml, /id="providerHint"/);
assert.match(elements.get("#llmProvider").innerHTML, /OpenAI 官方/);
assert.doesNotMatch(elements.get("#llmProvider").innerHTML, /OpenRouter/);
assert.match(elements.get("#llmProvider").innerHTML, /手动配置 OpenAI-compatible/);
assert.equal(elements.get("#llmProvider").value, "custom");
assert.equal(elements.get("#llmModel").value, "openai/gpt-4.1-mini");
assert.equal(elements.get("#llmBaseUrl").value, "https://openrouter.ai/api/v1");
assert.equal(elements.get("#transcriber").value, "faster-whisper");
assert.equal(elements.get("#whisperModel").value, "small");
assert.match(elements.get("#providerHint").innerHTML, /高级/);
assert.match(elements.get("#providerHint").innerHTML, /手动填写 OpenAI-compatible 端点/);
elements.get("#llmProvider").value = "gemini";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://generativelanguage.googleapis.com/v1beta/openai/");
assert.equal(elements.get("#llmModel").value, "gemini-3.5-flash");
assert.equal(elements.get("#transcriber").value, "faster-whisper");
assert.equal(elements.get("#whisperModel").value, "small");
assert.match(elements.get("#providerHint").innerHTML, /主流/);
assert.match(elements.get("#providerHint").innerHTML, /支持图文总结/);
assert.equal(context.healthVisionProvider({}), "Gemini");
context.updateHealthVisionStatus({ ffmpeg: true, ffprobe_optional: true, vision_model_configured: false });
assert.match(elements.get("#browserBridgeStatus").innerHTML, /capture-status-chip bridge/);
assert.doesNotMatch(elements.get("#browserBridgeStatus").innerHTML, /Gemini|faster-whisper|small/);
elements.get("#llmProvider").value = "dashscope";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://dashscope.aliyuncs.com/compatible-mode/v1");
assert.equal(elements.get("#llmModel").value, "qwen-vl-max");
assert.equal(context.healthVisionProvider({}), "DashScope");
elements.get("#llmProvider").value = "deepseek";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.deepseek.com");
assert.equal(elements.get("#llmModel").value, "deepseek-v4-flash");
elements.get("#llmApiKey").value = "local-text-key";
assert.equal(context.healthVisionReady({}), false);
assert.equal(context.healthTextModelReady({}), true);
assert.match(context.healthVisionText({}), /文本总结模型已配置/);
elements.get("#llmApiKey").value = "";
elements.get("#llmProvider").value = "kimi";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.moonshot.cn/v1");
assert.equal(elements.get("#llmModel").value, "kimi-k2.6");
elements.get("#llmProvider").value = "dashscope";
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
assert.equal(documentStub.body.classList.contains("workspace-collapsed"), false);
assert.equal(documentStub.body.classList.contains("queue-collapsed"), false);
assert.equal(documentStub.body.classList.contains("reading-mode"), false);
context.window.location.href = "http://127.0.0.1:8765/";
context.window.location.search = "";
context.window.localStorage.setItem("learnnote.workspaceCollapsed", "0");
context.window.localStorage.setItem("learnnote.historyCollapsed", "0");
context.window.localStorage.setItem("learnnote.readingMode", "0");
context.initializeWorkspaceView();
assert.match(indexHtml, /class="browser-capture-card"/);
assert.match(indexHtml, /class="capture-flow"/);
assert.match(indexHtml, /非录制/);
assert.match(indexHtml, /侧栏开始/);
assert.match(indexHtml, /阅读笔记/);
assert.match(indexHtml, /id="browserRouteSummary"/);
assert.match(indexHtml, /id="visualWindowsButton"/);
assert.match(indexHtml, /id="manifestButton"/);
assert.match(indexHtml, /id="subtitlesButton"/);
assert.match(indexHtml, /title="导出字幕"/);
assert.match(indexHtml, /id="resultMoreActions"/);
assert.match(indexHtml, /class="result-more-panel"/);
assert.match(indexHtml, /id="unifiedExportButton"[^>]*>统一导出</);
assert.match(indexHtml, /id="assistantSubmitButton"[^>]*type="submit"/);
assert.match(productCss, /Absolute cascade lock[\s\S]*grid-template-rows:\s*auto auto minmax\(0, 1fr\) auto auto/);
assert.match(productCss, /@media \(max-width: 620px\)[\s\S]*\.ai-assistant-drawer\s*\{[\s\S]*left:\s*0;[\s\S]*width:\s*auto;/);
assert.match(productCss, /@media \(max-width: 620px\)[\s\S]*\.assistant-launch-button\s*\{[\s\S]*font-size:\s*0;/);

const progressFingerprint = context.taskDetailFingerprint({
  id: "task-progress",
  status: "running",
  phase: "downloading",
  progress: 12
});
assert.notEqual(progressFingerprint, context.taskDetailFingerprint({
  id: "task-progress",
  status: "running",
  phase: "transcribing",
  progress: 48
}));
const liveProgressHtml = context.sourceWorkflowProgressHtml({
  id: "task-progress",
  status: "running",
  phase: "transcribing",
  progress: 48
});
assert.match(liveProgressHtml, /role="progressbar"/);
assert.match(liveProgressHtml, /aria-valuenow="48"/);
assert.match(liveProgressHtml, /48%/);
assert.equal(context.sourceWorkflowProgressHtml({ status: "success", progress: 100 }), "");

vm.runInContext(`tasks = [
  { id: "selected-running", title: "当前运行任务", status: "running", progress: 42 },
  { id: "older-note", title: "另一篇旧笔记", status: "success", note_path: "note.md" }
]; selectedTaskId = "selected-running";`, context);
assert.equal(context.assistantSelectedTask(), null);
context.renderAssistant();
assert.equal(elements.get("#assistantQuestion").disabled, true);
assert.equal(elements.get("#assistantSubmitButton").disabled, true);
assert.match(elements.get("#assistantConversation").innerHTML, /还没有选择笔记/);

vm.runInContext(`selectedTaskId = "older-note";`, context);
context.renderAssistant();
assert.equal(context.assistantSelectedTask().id, "older-note");
assert.equal(elements.get("#assistantQuestion").disabled, false);
assert.equal(elements.get("#assistantSubmitButton").disabled, false);
assert.equal(context.assistantCitationTarget({ source: "transcript" }), "transcript");
assert.equal(context.assistantCitationTarget({ window_id: "W003" }), "slices");
assert.match(context.assistantEvidenceHtml([{ source: "transcript", start: 42, time_range: "00:42", text: "课程原话" }]), /data-assistant-target-tab="transcript"/);
assert.match(context.assistantEvidenceHtml([{ source: "visual_window", window_id: "W003", text: "画面证据" }]), /data-assistant-window="W003"/);
context.setAssistantWide(true);
assert.equal(documentStub.body.classList.contains("assistant-wide"), true);
assert.equal(elements.get("#expandAiAssistantButton").attributes["aria-pressed"], "true");
context.setAssistantWide(false);
assert.equal(documentStub.body.classList.contains("assistant-wide"), false);
assert.equal((indexHtml.match(/id="resultMeta"/g) || []).length, 1);
assert.match(indexHtml, /id="generateNoteButton"[\s\S]*在浏览器侧栏开始/);
assert.doesNotMatch(indexHtml, /id="notePreset"/);
assert.equal((indexHtml.match(/name="learningGoal"/g) || []).length, 4);
const migratedTutorial = context.normalizedAppSettings({ notePreset: "tutorial" });
assert.equal(migratedTutorial.noteStyle, "code");
assert.equal(migratedTutorial.noteTemplate, "visual-handout");
assert.equal(migratedTutorial.summaryDepth, "deep");
context.applyLearningGoal("exam");
assert.equal(elements.get("#noteStyle").value, "exam");
assert.equal(elements.get("#noteTemplate").value, "qa");
assert.equal(elements.get("#summaryDepth").value, "standard");
assert.equal(context.readOptions().note_style, "exam");
assert.equal(context.readOptions().note_template, "qa");
assert.equal(context.readOptions().summary_depth, "standard");
context.setSource("browser");
assert.match(elements.get("#generateNoteHint").textContent, /扩展侧栏/);
context.setSource("local");
assert.equal(elements.get("#generateNoteHint").textContent, "选择视频后直接上传处理");
context.setSource("browser");
assert.match(productCss, /\.note-workbench\s*\{[\s\S]*grid-template-columns:\s*minmax\(720px, 820px\) minmax\(220px, 260px\)/);
assert.match(productCss, /\.reading-rail\s*\{[\s\S]*position:\s*sticky;[\s\S]*min-width:\s*220px;[\s\S]*max-width:\s*260px;/);
assert.match(productCss, /body\[data-app-view="notes"\] \.note-workbench > \.markdown-note[\s\S]*grid-column:\s*1;/);
assert.match(productCss, /body\[data-app-view="notes"\] \.note-workbench > \.reading-rail[\s\S]*grid-column:\s*2;[\s\S]*order:\s*0;/);
assert.match(matureCss, /#sourceWorkflow\.settled/);
assert.match(webCode, /assistantOpenPreference\(\) === true/);
assert.match(indexHtml, /data-tab="slices">画面与时间轴/);
assert.ok(
  indexHtml.indexOf('id="browserRouteSummary"') < indexHtml.indexOf('id="sourceWorkflow"'),
  "current-page route summary should appear before the workflow explainer"
);
assert.match(indexHtml, /当前页直取状态/);
assert.match(indexHtml, /当前页交接流程/);
assert.doesNotMatch(indexHtml, /Blob\/MSE 来源映射/);
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
assert.match(readyGateHtml, /DashScope · qwen-vl-max/);
assert.doesNotMatch(readyGateHtml, /<script>bad/);

const blockedGateHtml = context.emptyReadinessGatesHtml({
  ffmpeg: false,
  vision_model_configured: false,
  default_llm_provider: "openai"
});
assert.match(blockedGateHtml, /section class="block"/);
assert.match(blockedGateHtml, /后端未就绪/);
assert.match(blockedGateHtml, /DashScope/);
assert.match(indexHtml, /accept="video\/\*,\.mp4,\.m4v,\.mov,\.mkv,\.webm,\.flv,\.avi"/);
assert.match(indexHtml, /data-tab="frames">原始画面/);
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
vm.runInContext(`qaState = {
  taskId: "task-qa-visual",
  question: "画面里有哪些步骤？",
  answer: "请回看 W001。",
  source: "local-extractive",
  warning: "",
  citations: [{
    source: "visual_window",
    label: "W001",
    text: "函数封装演示",
    window_id: "W001",
    time_range: "00:00:00-00:01:00",
    grid_url: "/api/tasks/task-qa-visual/grids/grid_000.jpg",
    target_tab: "slices"
  }],
  historyCount: 1,
  recent: [],
  loading: false
}`, context);
const qaPanelVisualHtml = context.qaPanelHtml({ id: "task-qa-visual" });
assert.match(qaPanelVisualHtml, /qa-citations/);
assert.match(qaPanelVisualHtml, /class="visual"/);
assert.match(qaPanelVisualHtml, /W001/);
assert.match(qaPanelVisualHtml, /00:00:00-00:01:00/);
assert.match(qaPanelVisualHtml, /data-switch-result-tab="slices"/);
assert.match(qaPanelVisualHtml, /data-focus-visual-window="W001"/);
assert.match(qaPanelVisualHtml, /打开网格/);
assert.match(qaPanelVisualHtml, /\/api\/tasks\/task-qa-visual\/grids\/grid_000\.jpg/);
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
  reuse: { rerun_from_media_ready: true, media_available: true },
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
assert.match(resultMetaHtml, /内容<\/b>视频 · 字幕 · 1 画面/);
assert.match(resultMetaHtml, /笔记<\/b>可阅读/);
assert.doesNotMatch(resultMetaHtml, /导出<\/b>/);
assert.doesNotMatch(resultMetaHtml, /20 秒切片/);
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
  reuse: { rerun_from_media_ready: true, media_available: true },
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

| 参数 | 含义 | 数值 |
|:---|:---|---:|
| \`min_cells\` | 最少细胞数 | 3 |

---
[查看截图](http://127.0.0.1:8765/api/tasks/demo/assets/grid.jpg)
`);

assert.match(html, /<h2 id="note-画面索引">画面索引<\/h2>/);
assert.match(html, /<figure class="note-image-frame">/);
assert.match(html, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(html, /src="javascript:alert/);
assert.match(html, /class="markdown-table-wrap"/);
assert.match(html, /<th style="text-align:left">参数<\/th>/);
assert.match(html, /<td style="text-align:right">3<\/td>/);
assert.doesNotMatch(html, /<p>\| 参数 \|/);
assert.match(html, /<hr>/);
assert.match(html, /<a href="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/assets\/grid\.jpg"/);

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
assert.match(readingRailHtml, /class="note-outline"/);
assert.doesNotMatch(readingRailHtml, /class="(?:reading-progress-rail|visual-rail|reading-actions-rail|reading-artifacts-rail)"/);

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
assert.match(richReadingRailHtml, /笔记目录/);
assert.match(richReadingRailHtml, /3 节/);
assert.doesNotMatch(richReadingRailHtml, /exports\/|data-switch-result-tab/);

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
assert.match(reuseReadingRailHtml, /笔记目录/);
assert.doesNotMatch(reuseReadingRailHtml, /exports\/|data-switch-result-tab|data-rerun-from-media/);

const visualDeckHtml = context.visualStudyDeck({
  id: "task-visual-deck",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-visual-deck/media.mp4",
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
      local_summary: "本段讲解第一章概念\n- 对照 PPT 标题和公式",
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
assert.match(visualDeckHtml, /class="visual-window-summary"/);
assert.match(visualDeckHtml, /本段要点/);
assert.match(visualDeckHtml, /本段讲解第一章概念/);
assert.match(visualDeckHtml, /对照 PPT 标题和公式/);
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
assert.match(visualDeckHtml, /\/api\/tasks\/task-visual-deck\/exports\/clips\/W001/);
assert.match(visualDeckHtml, /导出片段/);
assert.match(visualDeckHtml, /data-media-seek-time="0\.000"/);
assert.match(visualDeckHtml, /data-window-start="180\.000"/);
assert.match(visualDeckHtml, />回看此段<\/button>/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

const visualCorrelationHtml = context.visualStudyCorrelationHtml({
  id: "task-visual-correlation",
  title: "视觉课程",
  summary_source: "vision-llm",
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
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      local_summary: "<script>alert(2)</script> 本段讲解第一章概念\n- 对照 PPT 标题和公式",
      transcript_excerpt: "<script>alert(1)</script> PPT 演示"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 0,
      grid_url: "",
      frame_timestamps: [180, 210]
    }
  ]
}, {
  segments: [
    { start: 10, end: 18, text: "第一段讲概念" },
    { start: 30, end: 38, text: "继续解释公式" },
    { start: 220, end: 230, text: "第二段讲例题" }
  ]
});
assert.match(visualCorrelationHtml, /class="visual-study-correlation"/);
assert.match(visualCorrelationHtml, /证据核对矩阵/);
assert.match(visualCorrelationHtml, /逐窗对齐画面、字幕、局部总结和复习动作/);
assert.match(visualCorrelationHtml, /2\/2 窗口/);
assert.match(visualCorrelationHtml, /article class="vision"/);
assert.match(visualCorrelationHtml, /article class="missing"/);
assert.match(visualCorrelationHtml, /截图网格/);
assert.match(visualCorrelationHtml, /无图/);
assert.match(visualCorrelationHtml, /2 段字幕 · 00:00:10 起/);
assert.match(visualCorrelationHtml, /本段讲解第一章概念/);
assert.match(visualCorrelationHtml, /对照 PPT 标题和公式/);
assert.match(visualCorrelationHtml, /data-focus-visual-window="W001"/);
assert.match(visualCorrelationHtml, /data-switch-result-tab="note"/);
assert.match(visualCorrelationHtml, /data-media-seek-time="180\.000"/);
assert.doesNotMatch(visualCorrelationHtml, /<script>alert/);
assert.match(visualCorrelationHtml, /&lt;script&gt;alert\(2\)&lt;\/script&gt; 本段讲解第一章概念/);

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
assert.match(sliceWorkbenchHtml, /class="visual-study-overview"/);
assert.match(sliceWorkbenchHtml, /切片总览/);
assert.match(sliceWorkbenchHtml, /图文证据完整/);
assert.match(sliceWorkbenchHtml, /2\/2 已参与/);
assert.match(sliceWorkbenchHtml, /W001/);
assert.match(sliceWorkbenchHtml, /已进视觉|本地索引/);
assert.match(sliceWorkbenchHtml, /网格图已参与图文总结 · 9 帧/);
assert.match(sliceWorkbenchHtml, /class="visual-study-handout"/);
assert.match(sliceWorkbenchHtml, /切片讲义时间轴/);
assert.match(sliceWorkbenchHtml, /画面-字幕-总结对齐/);
assert.match(sliceWorkbenchHtml, /data-media-seek-time="180\.000"/);
assert.match(sliceWorkbenchHtml, /data-switch-result-tab="transcript"/);
assert.match(sliceWorkbenchHtml, /\/api\/tasks\/task-slice-workbench\/exports\/visual-windows/);
assert.match(sliceWorkbenchHtml, /\/api\/tasks\/task-slice-workbench\/exports\/bundle/);
assert.doesNotMatch(sliceWorkbenchHtml, /class="visual-study-navigator"/);
assert.doesNotMatch(sliceWorkbenchHtml, /class="visual-review-path"/);
assert.doesNotMatch(sliceWorkbenchHtml, /class="visual-study-correlation"/);
assert.doesNotMatch(sliceWorkbenchHtml, /class="visual-study-deck"/);
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
assert.match(frameWorkbenchHtml, /class="visual-study-correlation"/);
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
  reuse: { rerun_from_media_ready: true, media_available: true },
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

const rawPendingSliceHtml = context.pendingSliceWorkbench({
  id: "task-pending-raw-slice",
  title: "Downloaded raw lesson",
  status: "failed",
  phase: "failed",
  mode: "video",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-pending-raw-slice/downloaded-original.mp4",
  reuse: { rerun_from_media_ready: true, media_available: true },
  download_attempts: [{ strategy: "direct-file", status: "success" }],
  visual_windows: []
});
assert.match(rawPendingSliceHtml, /downloaded-original\.mp4/);
assert.match(rawPendingSliceHtml, /data-rerun-from-media="task-pending-raw-slice"/);
assert.doesNotMatch(rawPendingSliceHtml, /导出 media\.mp4/);

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
const nativeExports = [];
context.window.pywebview = {
  api: {
    async export_task(taskId, exportType) {
      nativeExports.push([taskId, exportType]);
      return { ok: true, filename: "lesson.srt" };
    }
  }
};
await elements.get("#subtitlesButton").onclick();
assert.deepEqual(nativeExports.at(-1), ["task-note-download-only", "subtitles"]);
assert.match(elements.get("#exportStatus").textContent, /lesson\.srt/);
context.window.pywebview.api.export_task = async () => ({ ok: false, error: "目标文件夹不可写" });
await elements.get("#subtitlesButton").onclick();
assert.match(elements.get("#exportStatus").textContent, /导出失败/);
assert.match(elements.get("#exportStatus").textContent, /目标文件夹不可写/);
assert.equal(elements.get("#subtitlesButton").disabled, false);
delete context.window.pywebview;
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
          recovery: {
            chaoxing_profile: {
              detected: true,
              has_ananas_candidate: true,
              has_playurl: true,
              has_objectid: true,
              has_dtoken: false,
              has_replay_body: true,
              has_referer: true,
              has_origin: true,
              has_x_requested_with: true,
              has_iframe_context: true,
              cookie_domain_count: 2,
              cookie_count: 7,
              partitioned_cookie_count: 1,
              partition_key_count: 1,
              safe_request_header_names: ["Origin", "Referer", "X-Requested-With"],
              candidate_kinds: ["hls", "video"],
              likely_issue: "anti_hotlink_or_expired_signature",
              page_preflight: { present: true, candidate_count: 3, probed_count: 2, downloadable_count: 0 }
            }
          },
          download_attempts: [
            {
              strategy: "manifest-ffmpeg",
              status: "failed",
              code: "download_forbidden",
              message: "signed URL expired",
              request_header_names: ["Referer", "Origin", "Cookie", "Authorization", "User-Agent"],
              companion_audio_url: "https://cdn.example.com/course/audio-only.m4a?token=a"
            }
          ]
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
assert.match(diagnosticsEvidenceHtml, /class="chaoxing-profile"/);
assert.match(diagnosticsEvidenceHtml, /平台线索 · 学习通\/超星/);
assert.match(diagnosticsEvidenceHtml, /anti_hotlink_or_expired_signature/);
assert.match(diagnosticsEvidenceHtml, /Origin, Referer, X-Requested-With/);
assert.match(diagnosticsEvidenceHtml, /播放 API/);
assert.match(diagnosticsEvidenceHtml, /真实媒体/);
assert.match(diagnosticsEvidenceHtml, /POST\/body/);
assert.match(diagnosticsEvidenceHtml, /学习通模式/);
assert.match(diagnosticsEvidenceHtml, /ananas 已抓到/);
assert.match(diagnosticsEvidenceHtml, /playurl 已抓到/);
assert.match(diagnosticsEvidenceHtml, /objectid 已抓到/);
assert.match(diagnosticsEvidenceHtml, /dtoken 缺失/);
assert.match(diagnosticsEvidenceHtml, /cookie 已抓到/);
assert.match(diagnosticsEvidenceHtml, /播放器入口/);
assert.match(diagnosticsEvidenceHtml, /已看到 ananas\/playurl 播放接口/);
assert.match(diagnosticsEvidenceHtml, /媒体落地/);
assert.match(diagnosticsEvidenceHtml, /有媒体候选但预检未通过/);
assert.match(diagnosticsEvidenceHtml, /缺口：媒体落地/);
assert.match(diagnosticsEvidenceHtml, /通用策略/);
assert.match(diagnosticsEvidenceHtml, /不录制、不刷课、不伪造进度、不自动答题/);
assert.match(diagnosticsEvidenceHtml, /class="direct-extraction-evidence"/);
assert.match(diagnosticsEvidenceHtml, /非录制下载路线/);
assert.match(diagnosticsEvidenceHtml, /直取和总结证据/);
assert.match(diagnosticsEvidenceHtml, /class="pipeline-audit"/);
assert.match(diagnosticsEvidenceHtml, /manifest-ffmpeg/);
assert.match(diagnosticsEvidenceHtml, /headers Origin, Referer, User-Agent/);
assert.match(diagnosticsEvidenceHtml, /audio .*audio-only\.m4a/);
assert.doesNotMatch(diagnosticsEvidenceHtml, /secret=1/);
assert.doesNotMatch(diagnosticsEvidenceHtml, /headers .*Cookie|headers .*Authorization/);
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

const reviewWorkbenchHtml = context.noteReviewWorkbench(`# 机器学习导论

## 第一章
### 概念`, {
  id: "task-review-workbench",
  title: "复习工作台课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-review-workbench/media.mp4",
  subtitle_path: "D:/Projects/learnnote-assistant/data/tasks/task-review-workbench/subtitles.vtt",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-review-workbench/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-review-workbench/note.md",
  summary_source: "vision-llm",
  download_attempts: [{ strategy: "manifest-ffmpeg", status: "success" }],
  qa: { history_count: 2 },
  options: { frame_interval: 20, grid_columns: 3, grid_rows: 3, visual_understanding: true },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
});
assert.match(reviewWorkbenchHtml, /class="review-workbench ready"/);
assert.match(reviewWorkbenchHtml, /复习工作台/);
assert.match(reviewWorkbenchHtml, /复习笔记/);
assert.match(reviewWorkbenchHtml, /学习切片/);
assert.match(reviewWorkbenchHtml, /字幕时间轴/);
assert.match(reviewWorkbenchHtml, /学习路径/);
assert.match(reviewWorkbenchHtml, /读笔记 → 看切片 → 核字幕/);
assert.doesNotMatch(reviewWorkbenchHtml, /data-switch-result-tab="qa"|问答复习|打开学习助手/);
assert.match(reviewWorkbenchHtml, /高级诊断/);
assert.doesNotMatch(reviewWorkbenchHtml, /直取诊断/);
assert.match(reviewWorkbenchHtml, /3 个标题/);
assert.match(reviewWorkbenchHtml, /data-open-note-version="task-review-workbench"/);
assert.match(reviewWorkbenchHtml, /data-switch-result-tab="slices"/);
assert.match(reviewWorkbenchHtml, /data-switch-result-tab="diagnostics"/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/markdown/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/subtitles/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/visual-windows/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/media/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/bundle/);
assert.match(reviewWorkbenchHtml, /\/api\/tasks\/task-review-workbench\/exports\/diagnostics/);
assert.match(stylesCss, /\.review-command-grid[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/);
assert.match(stylesCss, /@container \(max-width: 960px\)[\s\S]*\.review-command-grid[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(stylesCss, /@container \(max-width: 960px\)[\s\S]*\.learning-path-steps[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/);

const partialReviewWorkbenchHtml = context.noteReviewWorkbench("", {
  id: "task-review-partial",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-review-partial/media.mp4",
  reuse: { rerun_from_media_ready: true, media_available: true },
  options: { visual_understanding: true }
});
assert.match(partialReviewWorkbenchHtml, /class="review-workbench partial"/);
assert.match(partialReviewWorkbenchHtml, /继续切片总结/);
assert.match(partialReviewWorkbenchHtml, /data-rerun-from-media="task-review-partial"/);
assert.match(partialReviewWorkbenchHtml, /视频已直取到本地/);

const taskOverviewHtml = context.taskOverview({
  id: "task-web-overview",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-overview/media.mp4",
  resource_inventory_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-overview/resource_inventory.json",
  page_preflight_report_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-overview/page_preflight_report.json",
  reuse: { rerun_from_media_ready: true, media_available: true },
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
    { key: "ask_assistant", label: "打开 AI 助手", detail: "围绕当前任务继续追问。", intent: "open_assistant", target: "current_task" },
    { key: "export_media", label: "导出 media.mp4", detail: "核对本地视频。", intent: "export", target: "media" },
    { key: "view_diagnostics", label: "看下载诊断", detail: "查看候选和失败原因。", intent: "switch_tab", target: "diagnostics" }
  ]
});

assert.match(taskOverviewHtml, /class="task-overview status-success"/);
assert.match(taskOverviewHtml, /资料包/);
assert.match(taskOverviewHtml, /生成完整笔记/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/media/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/bundle/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.match(taskOverviewHtml, /当前页下载/);
assert.match(taskOverviewHtml, /音视频合并/);
assert.match(taskOverviewHtml, /最终 URL 已记录/);
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
assert.match(taskOverviewHtml, /class="next-action assistant-action" data-open-assistant/);
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

const directResponseOverviewHtml = context.taskOverview({
  id: "task-web-direct-response",
  title: "JSON play API",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-direct-response/media.mp4",
  selected_resource: {
    url: "https://course.example.com/api/play?id=42",
    kind: "video",
    source: "webRequest",
    resolved_url: "https://media.example.com/real/lesson.mp4?sig=abc",
    mime: "application/json",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=1"
    }
  },
  download_attempts: [{ strategy: "direct-response-scan", status: "success" }],
  options: { frame_interval: 20, grid_columns: 3, grid_rows: 3 },
  visual_windows: []
});
assert.match(directResponseOverviewHtml, /播放接口解析: https:\/\/media\.example\.com\/real\/lesson\.mp4\?sig=abc/);
assert.match(directResponseOverviewHtml, /<b>接口解析<\/b>/);
assert.match(directResponseOverviewHtml, /direct-response-scan/);
assert.doesNotMatch(directResponseOverviewHtml, /secret=1/);

const rawMediaNameTask = {
  id: "task-raw-media-name",
  title: "downloaded original",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-raw-media-name/downloaded-original.mp4",
  selected_resource: {
    kind: "hls",
    source: "webRequest",
    playback_match: "blob-source"
  },
  direct_extraction: {
    no_tab_recording: true,
    no_drm_bypass: true,
    route: "download_only_to_local_media",
    media_landed: true,
    media_reusable: true,
    selected_candidate: {
      kind: "hls",
      source: "webRequest"
    },
    download: {
      successful_attempt_count: 1,
      failed_attempt_count: 0,
      strategy_order: ["manifest-ffmpeg"]
    },
    processing: {
      download_only: true
    },
    boundary: "normal_accessible_media_only"
  },
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3,
    visual_understanding: true
  },
  visual_windows: []
};
const rawMediaOverviewHtml = context.taskOverview(rawMediaNameTask);
assert.match(rawMediaOverviewHtml, /downloaded-original\.mp4/);
assert.doesNotMatch(rawMediaOverviewHtml, /已保存 media\.mp4|导出 media\.mp4|media\.mp4 继续/);
const rawMediaNoteTask = {
  ...rawMediaNameTask,
  status: "success",
  mode: "rerun_from_media",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-raw-media-name/note.md",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-raw-media-name/transcript.json"
};
assert.match(context.noteHeroBanner("# downloaded original", rawMediaNoteTask), /downloaded-original\.mp4/);
assert.match(context.noteReviewWorkbench("# downloaded original", rawMediaNoteTask), />downloaded-original\.mp4</);
assert.match(context.noteStudyBar("# downloaded original", rawMediaNoteTask), /downloaded-original\.mp4/);
assert.match(context.noteExportCtaBar(rawMediaNoteTask), />downloaded-original\.mp4</);
assert.match(context.readingProgressRail("# downloaded original", rawMediaNoteTask), /downloaded-original\.mp4/);
assert.match(context.readingArtifactsRail(rawMediaNoteTask), />downloaded-original\.mp4</);
assert.doesNotMatch(context.readingArtifactsRail(rawMediaNoteTask), />media\.mp4</);

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
assert.match(fallbackTaskOverviewHtml, /阅读笔记/);
assert.match(fallbackTaskOverviewHtml, /查看诊断/);
assert.match(fallbackTaskOverviewHtml, /资料包/);
const failureGuideHtml = context.failureGuide({
  status: "failed",
  error_code: "download_forbidden",
  note_path: "D:/note.md",
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script> Referer expired" },
    { strategy: "page-ytdlp", code: "download_forbidden", message: "no fallback" }
  ]
});
assert.match(failureGuideHtml, /已保留完整诊断信息/);
assert.doesNotMatch(failureGuideHtml, /page-ytdlp|download_forbidden|no fallback/);
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
  reuse: { rerun_from_media_ready: true, media_available: true },
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
assert.doesNotMatch(diagnosticRecoveryHtml, /\/api\/tasks\/task-recovery\/exports\/diagnostics/);
assert.doesNotMatch(diagnosticRecoveryHtml, /\/api\/tasks\/task-recovery\/exports\/audit/);
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
assert.doesNotMatch(recoveryDecisionHtml, /data-switch-result-tab="diagnostics"/);
assert.doesNotMatch(recoveryDecisionHtml, /\/api\/tasks\/task-decision\/exports\/audit/);
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
}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-processing-failed",
  status: "failed",
  media_path: "D:/media.mp4",
  note_path: ""
}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-reuse-ready",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "",
  reuse: { media_available: true, rerun_from_media_ready: true }
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
  note_path: "",
  reuse: { media_available: true, rerun_from_media_ready: true }
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
  reuse: { rerun_from_media_ready: true, media_available: true },
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
assert.match(taskPreviewWithImage, /<img src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/task-preview\/assets\/grid_000.jpg"/);
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

const localUploadEvidenceHtml = context.taskRouteEvidenceHtml({
  source_type: "local",
  source_media_path: "D:/Projects/learnnote-assistant/data/uploads/local-task_queued-local.mp4<script>",
  selected_resource: {},
  download_attempts: []
});
assert.match(localUploadEvidenceHtml, /上传原片/);
assert.match(localUploadEvidenceHtml, /local-task_queued-local\.mp4/);
assert.match(localUploadEvidenceHtml, /data\/uploads/);
assert.match(localUploadEvidenceHtml, /&lt;script&gt;/);
assert.doesNotMatch(localUploadEvidenceHtml, /<script>/);

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
assert.match(routeBlockedHtml, /不录制 · 不绕过 DRM · 不刷课/);
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
assert.match(browserWorkflowHtml, /source-primary-command active/);
assert.match(browserWorkflowHtml, /查看进度/);
assert.match(browserWorkflowHtml, /data-select-workflow-task="task-workflow-browser"/);
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
assert.match(localWorkflowHtml, /source-primary-command ready/);
assert.match(localWorkflowHtml, /选择本地视频/);
assert.match(localWorkflowHtml, /data-source-workflow-action="choose-local"/);
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
assert.match(urlWorkflowHtml, /source-primary-command done/);
assert.match(urlWorkflowHtml, /查看笔记/);
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
assert.match(failedWorkflowHtml, /source-primary-command blocked/);
assert.match(failedWorkflowHtml, /切到本地兜底/);
assert.match(failedWorkflowHtml, /DRM/);

const routeEmptyHtml = context.browserRouteSummaryHtml(null);
assert.match(routeEmptyHtml, /等待扩展侧栏创建当前页任务/);
assert.match(routeEmptyHtml, /不录制 · 不绕过 DRM · 不刷课/);
assert.match(routeEmptyHtml, /mp4、mkv、webm、flv、m3u8、mpd/);
assert.match(routeEmptyHtml, /data-browser-route-action="refresh"/);
assert.match(routeEmptyHtml, /data-browser-route-action="copy-backend"/);
assert.match(routeEmptyHtml, /data-browser-route-action="open-extension"/);
assert.match(routeEmptyHtml, /去扩展侧栏开始/);
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
  reuse: { rerun_from_media_ready: true, media_available: true },
  selected_resource: { kind: "hls" },
  visual_windows: []
});
assert.match(downloadOnlyRunModesHtml, /media\.mp4 已保存/);
assert.match(downloadOnlyRunModesHtml, /从 media\.mp4 继续/);
assert.match(downloadOnlyRunModesHtml, /data-source-workflow-action="continue-media"/);
assert.match(downloadOnlyRunModesHtml, /data-task-id="task-workflow-download-only"/);

const downloadOnlyPrimaryHtml = context.sourcePrimaryCommandHtml("browser", {
  id: "task-workflow-download-only",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-workflow-download-only/media.mp4",
  reuse: { rerun_from_media_ready: true, media_available: true }
});
assert.match(downloadOnlyPrimaryHtml, /继续切片总结/);
assert.match(downloadOnlyPrimaryHtml, /data-source-workflow-action="continue-media"/);
assert.match(downloadOnlyPrimaryHtml, /data-task-id="task-workflow-download-only"/);

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
assert.equal(posts[5].page_preflight_report.ready, true);
assert.equal(posts[5].page_preflight_report.candidate_count, 5);
assert.equal(posts[5].page_preflight_report.downloadable_count, 2);
assert.equal(posts[5].page_preflight_report.candidates[0].preflight.resolved_url, "https://media.example.com/page/final-master.m3u8");

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
elements.get("#gridColumns").value = "7";
elements.get("#gridRows").value = "nope";
let boundedOptions = context.readOptions();
assert.equal(boundedOptions.frame_interval, 1);
assert.equal(boundedOptions.grid_columns, 6);
assert.equal(boundedOptions.grid_rows, 3);
assert.match(context.visualPlanText(), /1秒 · 6x3/);
elements.get("#frameInterval").value = "30";
elements.get("#gridSize").value = "4x3";
elements.get("#gridColumns").value = "4";
elements.get("#gridRows").value = "3";
elements.get("#noteTemplate").value = "cornell";
elements.get("#llmProvider").value = "groq";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.groq.com/openai/v1");
assert.equal(elements.get("#llmModel").value, "meta-llama/llama-4-scout-17b-16e-instruct");
assert.equal(elements.get("#transcriber").value, "groq");
assert.equal(elements.get("#whisperModel").value, "whisper-large-v3");
assert.match(elements.get("#providerHint").innerHTML, /Groq/);
assert.match(elements.get("#providerHint").innerHTML, /支持图文总结/);
assert.match(elements.get("#providerHint").innerHTML, /Groq ASR/);
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
const rawRerunNotice = context.rerunFromMediaNotice("source-media-task", "rerun-task", {
  reuse: { source_media_path: "D:/Projects/learnnote-assistant/data/tasks/source-media-task/downloaded-original.mp4" }
});
assert.match(rerunMetaHtml, /内容/);
assert.doesNotMatch(rerunMetaHtml, /已下载媒体/);
assert.match(rerunNotice, /完整笔记任务 rerun-task/);
assert.match(rerunNotice, /不会录制页面/);

assert.match(rawRerunNotice, /downloaded-original\.mp4/);

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

const normalizedBvid = context.normalizeSourceInput("BV1xx411c7mD");
assert.equal(normalizedBvid.valid, true);
assert.equal(normalizedBvid.platform, "bilibili");
assert.equal(normalizedBvid.sourceId, "BV1xx411c7mD");
assert.equal(normalizedBvid.url, "https://www.bilibili.com/video/BV1xx411c7mD?p=1");
assert.equal(normalizedBvid.partNumber, 1);

const normalizedBilibiliUrl = context.normalizeSourceInput("视频 https://www.bilibili.com/video/BV1xx411c7mD?p=2。");
assert.equal(normalizedBilibiliUrl.url, "https://www.bilibili.com/video/BV1xx411c7mD?p=2");
assert.match(normalizedBilibiliUrl.label, /B站视频/);

const invalidSourceInput = context.normalizeSourceInput("not a video source");
assert.equal(invalidSourceInput.valid, false);

assert.deepEqual(
  JSON.parse(JSON.stringify(context.normalizedAppSettings({ uiScale: "999", textSize: "huge", defaultSource: "bad" }))),
  {
    uiScale: "100",
    textSize: "standard",
    theme: "light",
    colorTheme: "teal",
    defaultSource: "browser",
    autoOpenNote: true,
    taskNotifications: false,
    compactHistory: false,
    autoPreflight: true,
    frameInterval: "20",
    gridSize: "3x3",
    gridColumns: "3",
    gridRows: "3",
    visualUnderstanding: true,
    noteStyle: "study",
    noteTemplate: "standard",
    summaryDepth: "standard",
    customNoteProfile: null
  }
);
const customProfile = context.normalizeCustomNoteProfile({
  name: "Lab notes",
  description: "Methods and evidence",
  prompt: "Preserve methods, parameters, and evidence.",
  sections: ["Question", "Methods", "Results"],
  template: "timeline",
  depth: "deep"
});
assert.equal(customProfile.name, "Lab notes");
assert.deepEqual(JSON.parse(JSON.stringify(customProfile.sections)), ["Question", "Methods", "Results"]);
assert.equal(context.normalizeCustomNoteProfile({ name: "Missing prompt", sections: ["A"] }), null);
vm.runInContext(`appSettings = normalizedAppSettings({
  theme: "dark",
  textSize: "large",
  defaultSource: "local",
  frameInterval: "30",
  gridSize: "4x3",
  visualUnderstanding: false
}); applyAppSettings(); storeAppSettings();`, context);
assert.equal(context.document.body.classList.contains("theme-dark"), true);
assert.equal(context.document.body.dataset.textSize, "large");
assert.equal(elements.get("#frameInterval").value, "30");
assert.equal(elements.get("#gridSize").value, "4x3");
assert.equal(elements.get("#visualUnderstanding").checked, false);
assert.equal(JSON.parse(context.window.localStorage.getItem("learnnote_app_settings")).defaultSource, "local");

const updateCalls = [];
context.window.pywebview = { api: {
  async download_update(version, url, sha256) {
    updateCalls.push(["download", version, url, sha256]);
    return { ok: true, path: "D:\\LearnNote\\data\\installers\\v9.8.7\\LearnNote-Setup-x64.exe" };
  },
  async install_update(version, path) {
    updateCalls.push(["install", version, path]);
    return { ok: true, installing: true };
  }
} };
vm.runInContext(`tasks = []; pendingDesktopUpdate = {
  version: "9.8.7",
  url: "https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Setup-x64.exe",
  sha256: "${"a".repeat(64)}"
};`, context);
await context.installDesktopUpdate();
assert.equal(updateCalls.length, 2);
assert.deepEqual(updateCalls[0].slice(0, 2), ["download", "9.8.7"]);
assert.deepEqual(updateCalls[1], ["install", "9.8.7", "D:\\LearnNote\\data\\installers\\v9.8.7\\LearnNote-Setup-x64.exe"]);
