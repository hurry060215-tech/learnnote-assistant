const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8765";

function normalizeApiBase(value) {
  const text = String(value || "").trim().replace(/\/+$/, "");
  return /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/i.test(text) ? text : "";
}

function isBackendSameOrigin(loc = window?.location || location) {
  const protocol = String(loc?.protocol || "");
  const hostname = String(loc?.hostname || "");
  return (protocol === "http:" || protocol === "https:") && Boolean(hostname);
}

function resolveApiBase(loc = window?.location || location, storage = window?.localStorage) {
  const explicit = normalizeApiBase(currentUrlParam(["api", "backend", "backend_url"]));
  if (explicit) return explicit;
  const saved = normalizeApiBase(storage?.getItem?.("learnnote_api_base"));
  if (saved) return saved;
  return isBackendSameOrigin(loc) ? "" : DEFAULT_BACKEND_ORIGIN;
}

function apiUrl(path) {
  return `${API}${path}`;
}

let API = resolveApiBase();
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const HLS_RE = /\.(m3u8|mpd)(\?|#|$)/i;
const LOCAL_VIDEO_EXT_RE = /\.(mp4|m4v|mov|mkv|webm|flv|avi)$/i;
const RESULT_TAB_NAMES = new Set(["note", "transcript", "slices", "frames", "qa", "diagnostics"]);
const LOCAL_ASR_MODELS = new Set(["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]);
const MODEL_SETTINGS_STORAGE_KEY = "learnnote_model_settings";
const MAINSTREAM_MODEL_PROVIDER_KEYS = new Set([
  "openai", "groq", "gemini", "dashscope", "deepseek", "kimi", "zhipu", "doubao", "minimax", "qianfan"
]);
const MODEL_PROVIDER_PRESETS = {
  openai: {
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
    transcriber: "openai-compatible",
    whisperModel: "whisper-1",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision", "asr"]
  },
  groq: {
    baseUrl: "https://api.groq.com/openai/v1",
    model: "meta-llama/llama-4-scout-17b-16e-instruct",
    transcriber: "groq",
    whisperModel: "whisper-large-v3",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision", "asr"]
  },
  gemini: {
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    model: "gemini-3.5-flash",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision"]
  },
  dashscope: {
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-vl-max",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision"]
  },
  deepseek: {
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text"]
  },
  kimi: {
    baseUrl: "https://api.moonshot.cn/v1",
    model: "kimi-k2.6",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision"]
  },
  zhipu: {
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-5v-turbo",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision"]
  },
  doubao: {
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    model: "doubao-seed-2-0-lite-260215",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text"]
  },
  minimax: {
    baseUrl: "https://api.minimaxi.com/v1",
    model: "MiniMax-M2.7",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text"]
  },
  qianfan: {
    baseUrl: "https://qianfan.baidubce.com/v2",
    model: "ernie-4.5-8k-preview",
    transcriber: "faster-whisper",
    whisperModel: "small",
    tier: "mainstream",
    recommended: true,
    capabilities: ["text", "vision"]
  }
};
let modelProviderPresets = { ...MODEL_PROVIDER_PRESETS };

function normalizeModelProviderPreset(preset) {
  const key = String(preset?.key || "").trim();
  if (!key) return null;
  return {
    key,
    label: String(preset.label || key).trim(),
    baseUrl: String(preset.baseUrl || preset.base_url || "").trim(),
    model: String(preset.model || "").trim(),
    transcriber: String(preset.transcriber || "faster-whisper").trim(),
    whisperModel: String(preset.whisperModel || preset.whisper_model || "small").trim(),
    tier: String(preset.tier || "compatible").trim(),
    recommended: Boolean(preset.recommended),
    capabilities: Array.isArray(preset.capabilities)
      ? preset.capabilities.map(item => String(item || "").trim()).filter(Boolean)
      : []
  };
}

function syncModelProviderPresets(data) {
  const raw = data?.model_provider_presets;
  if (!raw) return;
  const previous = els?.llmProvider?.value || "";
  const entries = Array.isArray(raw)
    ? raw
    : Object.entries(raw).map(([key, preset]) => ({ ...(preset || {}), key }));
  const next = { ...MODEL_PROVIDER_PRESETS };
  for (const item of entries) {
    const preset = normalizeModelProviderPreset(item);
    if (preset && !MAINSTREAM_MODEL_PROVIDER_KEYS.has(preset.key)) continue;
    if (preset) next[preset.key] = preset;
  }
  modelProviderPresets = next;
  renderModelProviderOptions(previous);
  updateModelProviderHint();
}

function renderModelProviderOptions(preferred = "") {
  if (!els?.llmProvider) return;
  const current = preferred || els.llmProvider.value || "";
  const entries = Object.values(modelProviderPresets)
    .filter(preset => preset?.key && MAINSTREAM_MODEL_PROVIDER_KEYS.has(preset.key))
    .sort((left, right) => {
      const recommendedDelta = Number(Boolean(right.recommended)) - Number(Boolean(left.recommended));
      if (recommendedDelta) return recommendedDelta;
      return String(left.label || left.key).localeCompare(String(right.label || right.key), "zh-Hans-CN");
    });
  els.llmProvider.innerHTML = [
    ...entries.map(preset => `<option value="${escapeHtml(preset.key)}">${escapeHtml(preset.label || preset.key)}</option>`),
    `<option value="custom">手动配置 OpenAI-compatible</option>`
  ].join("");
  els.llmProvider.value = modelProviderPresets[current] ? current : "custom";
}

function modelProviderLabel(key) {
  return modelProviderPresets[key]?.label || ({
    custom: "手动配置",
    openai: "OpenAI",
    groq: "Groq",
    gemini: "Gemini",
    dashscope: "DashScope",
    deepseek: "DeepSeek",
    kimi: "Kimi",
    zhipu: "智谱 GLM",
    doubao: "豆包",
    minimax: "MiniMax",
    qianfan: "百度千帆",
    "openai-compatible": "Compatible",
    ollama: "Ollama"
  })[key] || key;
}

function providerBaseHost(baseUrl) {
  const text = String(baseUrl || "").trim().replace(/^https?:\/\//i, "");
  return text.split(/[/?#]/)[0] || "custom";
}

function providerCapabilitySummary(preset) {
  const capabilities = new Set(preset?.capabilities || []);
  const visual = capabilities.has("vision") ? "支持图文总结" : "仅文本/转写";
  const asr = preset?.transcriber === "groq"
    ? "Groq ASR"
    : preset?.transcriber === "openai-compatible"
      ? "远程 ASR"
      : "本地 faster-whisper";
  return `${visual} · ${asr}`;
}

function updateModelProviderHint() {
  if (!els?.providerHint) return;
  const key = els.llmProvider?.value || "";
  const preset = modelProviderPresets[key];
  if (!preset) {
    els.providerHint.innerHTML = `<span class="provider-tier compatible">高级</span><span>手动填写 OpenAI-compatible 端点；图文总结需要支持视觉输入的模型。</span>`;
    return;
  }
  const tier = preset.recommended || preset.tier === "mainstream" ? "mainstream" : "compatible";
  const tierLabel = tier === "mainstream" ? "主流" : "高级";
  const label = escapeHtml(modelProviderLabel(key));
  const summary = escapeHtml(providerCapabilitySummary(preset));
  const host = escapeHtml(providerBaseHost(preset.baseUrl));
  els.providerHint.innerHTML = `<span class="provider-tier ${tier}">${tierLabel}</span><span>${label} · ${summary} · ${host}</span>`;
}

let selectedSource = "browser";
let selectedTaskId = taskIdFromCurrentUrl();
let selectedTab = resultTabFromCurrentUrl();
let lastNote = "";
let lastNoteTaskId = "";
let lastTranscript = null;
let lastTranscriptTaskId = "";
let tasks = [];
let taskQuery = "";
let taskStatusFilter = "all";
let urlPreflightResourceUrl = "";
let urlPreflightResult = null;
let urlPagePreflightUrl = "";
let urlPagePreflightResource = null;
let urlPagePreflightReport = null;
let lastHealthData = null;
let pendingLocalFile = null;
let pendingRerunNotice = null;
let qaState = { taskId: "", question: "", answer: "", source: "", warning: "", citations: [], historyCount: 0, recent: [], loading: false };

const els = {
  health: document.querySelector("#health"),
  refreshButton: document.querySelector("#refreshButton"),
  toggleWorkspaceButton: document.querySelector("#toggleWorkspaceButton"),
  toggleHistoryButton: document.querySelector("#toggleHistoryButton"),
  readingModeButton: document.querySelector("#readingModeButton"),
  sourceTabs: document.querySelectorAll(".source-tab"),
  panes: document.querySelectorAll(".source-pane"),
  urlInput: document.querySelector("#urlInput"),
  urlSourceIdentity: document.querySelector("#urlSourceIdentity"),
  urlMode: document.querySelector("#urlMode"),
  urlModeHint: document.querySelector("#urlModeHint"),
  urlPreflightReport: document.querySelector("#urlPreflightReport"),
  optionsDisclosure: document.querySelector("#optionsDisclosure"),
  titleInput: document.querySelector("#titleInput"),
  startUrlButton: document.querySelector("#startUrlButton"),
  preflightUrlButton: document.querySelector("#preflightUrlButton"),
  downloadUrlButton: document.querySelector("#downloadUrlButton"),
  copyBackendButton: document.querySelector("#copyBackendButton"),
  browserRefreshButton: document.querySelector("#browserRefreshButton"),
  browserBridgeStatus: document.querySelector("#browserBridgeStatus"),
  browserRouteSummary: document.querySelector("#browserRouteSummary"),
  startupReadiness: document.querySelector("#startupReadiness"),
  sourceRouteRail: document.querySelector("#sourceRouteRail"),
  sourceWorkflow: document.querySelector("#sourceWorkflow"),
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  uploadButton: document.querySelector("#uploadButton"),
  taskSearch: document.querySelector("#taskSearch"),
  statusFilter: document.querySelector("#statusFilter"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  visualUnderstanding: document.querySelector("#visualUnderstanding"),
  transcriber: document.querySelector("#transcriber"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  noteTemplate: document.querySelector("#noteTemplate"),
  summaryDepth: document.querySelector("#summaryDepth"),
  llmProvider: document.querySelector("#llmProvider"),
  providerHint: document.querySelector("#providerHint"),
  llmModel: document.querySelector("#llmModel"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmApiKey: document.querySelector("#llmApiKey"),
  taskCount: document.querySelector("#taskCount"),
  successCount: document.querySelector("#successCount"),
  runningCount: document.querySelector("#runningCount"),
  failedCount: document.querySelector("#failedCount"),
  tasks: document.querySelector("#tasks"),
  selectedSource: document.querySelector("#selectedSource"),
  selectedTitle: document.querySelector("#selectedTitle"),
  resultMeta: document.querySelector("#resultMeta"),
  resultTabs: document.querySelectorAll(".result-tab"),
  detail: document.querySelector("#detail"),
  continueFromMediaButton: document.querySelector("#continueFromMediaButton"),
  copyButton: document.querySelector("#copyButton"),
  bundleButton: document.querySelector("#bundleButton"),
  diagnosticsButton: document.querySelector("#diagnosticsButton"),
  visualWindowsButton: document.querySelector("#visualWindowsButton"),
  manifestButton: document.querySelector("#manifestButton"),
  subtitlesButton: document.querySelector("#subtitlesButton"),
  mediaButton: document.querySelector("#mediaButton"),
  downloadButton: document.querySelector("#downloadButton")
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function compactUrl(value, limit = 88) {
  const text = String(value || "").trim();
  if (!text || text.length <= limit) return text;
  const head = Math.max(24, Math.floor(limit * 0.42));
  const tail = Math.max(24, limit - head - 3);
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

function isUnreadableTitle(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  const compact = text.replace(/\s+/g, "");
  if (!compact) return true;
  if (/^[?？\uFFFD]+$/.test(compact)) return true;
  if (compact.length >= 4) {
    const suspectCount = (compact.match(/[?？\uFFFD]/g) || []).length;
    if (suspectCount / compact.length >= 0.65) return true;
  }
  return false;
}

function hostFromUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    return parsed.hostname || "";
  } catch {
    const match = /^https?:\/\/([^/?#]+)/i.exec(text);
    return match ? match[1] : "";
  }
}

function displayTaskTitle(task, fallback = "未命名任务") {
  const raw = String(task?.title || "").trim();
  if (!isUnreadableTitle(raw)) return raw;
  const selected = task?.selected_resource || {};
  const kind = mediaKindText(selected.kind) || selected.kind || (task?.media_path ? taskMediaDisplayName(task) : "");
  const source = task?.mode === "download_only"
    ? "当前页下载"
    : task?.mode === "rerun_from_media"
      ? "复用本地视频"
      : task?.source_type === "local"
        ? "本地视频"
        : task?.source_type === "page_text"
          ? "页面文本"
          : task?.source_type === "current_page"
            ? "当前页直取"
            : "";
  const host = hostFromUrl(task?.page_url || selected.page_url || selected.frame_url || selected.url);
  if (source && kind) return `${source} · ${kind}`;
  if (host && source) return `${source} · ${host}`;
  if (host) return compactUrl(host, 48);
  if (source) return source;
  return task?.id ? `任务 ${String(task.id).slice(0, 8)}` : fallback;
}

function preferredInitialTask(list) {
  const candidates = Array.isArray(list) ? list : [];
  return candidates.find(task => task.status === "running")
    || candidates.find(task => task.status === "success" && task.note_path)
    || candidates.find(task => task.status === "success" && (hasExportableMedia(task) || visualWindows(task).length))
    || candidates.find(task => task.status === "success")
    || candidates.find(task => task.status === "queued")
    || candidates.find(task => task.status === "failed" && task.note_path)
    || candidates[0]
    || null;
}

function taskStudyRank(task, currentTaskId = selectedTaskId) {
  if (!task) return 90;
  if (task.id && task.id === currentTaskId) return 0;
  if (task.status === "running") return 1;
  if (task.status === "success" && task.note_path) return 2;
  if (task.status === "success" && (hasExportableMedia(task) || visualWindows(task).length)) return 3;
  if (task.status === "success") return 4;
  if (task.status === "queued") return 5;
  if (task.status === "failed" && task.note_path) return 6;
  if (task.status === "failed") return 7;
  return 8;
}

function sortedVisibleTasks(list, currentTaskId = selectedTaskId) {
  return (Array.isArray(list) ? list : [])
    .map((task, index) => ({ task, index }))
    .sort((a, b) => taskStudyRank(a.task, currentTaskId) - taskStudyRank(b.task, currentTaskId) || a.index - b.index)
    .map(item => item.task);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers?.get?.("content-type") || "";
  if (response.ok === false) {
    const message = contentType.includes("application/json")
      ? JSON.stringify(await response.json().catch(() => ({})))
      : (typeof response.text === "function" ? await response.text().catch(() => "") : "");
    throw new Error(message || `HTTP ${response.status}`);
  }
  if (contentType && !contentType.includes("application/json")) {
    throw new Error(`Expected JSON from ${url}`);
  }
  const payload = await response.json();
  if (String(url).endsWith("/health")) {
    lastHealthData = payload;
  }
  return payload;
}

function currentUrlSearchText() {
  const href = String(window?.location?.href || location?.href || "");
  const explicitSearch = String(window?.location?.search || location?.search || "");
  return explicitSearch || (href.includes("?") ? href.slice(href.indexOf("?")) : "");
}

function currentUrlParam(names) {
  const search = currentUrlSearchText();
  const pattern = new RegExp(`[?&](?:${names.join("|")})=([^&#]+)`);
  const match = pattern.exec(search);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1].replace(/\+/g, " ")).trim() || null;
  } catch {
    return match[1].trim() || null;
  }
}

function taskIdFromCurrentUrl() {
  return currentUrlParam(["task", "task_id"]);
}

function resultTabFromCurrentUrl() {
  const tab = currentUrlParam(["tab", "result_tab"]);
  return normalizeResultTabName(tab);
}

function normalizeResultTabName(tabName) {
  const tab = String(tabName || "").trim();
  return RESULT_TAB_NAMES.has(tab) ? tab : "note";
}

function syncSelectedTaskUrl(taskId) {
  if (!taskId || !window?.history?.replaceState) return;
  const path = window.location?.pathname || "/";
  const hash = window.location?.hash || "";
  if (typeof URLSearchParams === "undefined") {
    window.history.replaceState(null, "", `${path}?task=${encodeURIComponent(taskId)}&tab=${encodeURIComponent(selectedTab)}${hash}`);
    return;
  }
  const params = new URLSearchParams(String(window.location?.search || ""));
  params.set("task", taskId);
  params.set("tab", selectedTab);
  window.history.replaceState(null, "", `${path}?${params.toString()}${hash}`);
}

function selectTask(taskId, { clearCaches = true, syncUrl = true } = {}) {
  if (!taskId) return;
  const changed = selectedTaskId !== taskId;
  selectedTaskId = taskId;
  if (changed && clearCaches) clearTaskCaches();
  if (syncUrl) syncSelectedTaskUrl(taskId);
}

function safeNoteMediaUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const localMatch = /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(\/(?:api|data)\/.*)$/i.exec(raw);
  if (localMatch && API) return escapeHtml(`${API}${localMatch[1]}`);
  if (/^\/(?:api|data)\//i.test(raw)) return escapeHtml(API ? `${API}${raw}` : raw);
  if (/^https?:\/\//i.test(raw)) return escapeHtml(raw);
  return "";
}

function safeExternalUrl(value) {
  const raw = String(value || "").trim();
  return /^https?:\/\//i.test(raw) ? raw : "";
}

function isSupportedLocalVideoFile(file) {
  if (!file?.name) return false;
  if (String(file.type || "").startsWith("video/")) return true;
  return LOCAL_VIDEO_EXT_RE.test(file.name);
}

function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (typeof detail?.message === "string" && detail.message.trim()) return detail.message.trim();
  if (typeof payload?.message === "string" && payload.message.trim()) return payload.message.trim();
  return fallback;
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function plainHeadingText(value) {
  return String(value || "")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[`*_~#]/g, "")
    .trim();
}

function noteHeadingId(value, counts = new Map()) {
  const plain = plainHeadingText(value);
  const slug = plain
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-+|-+$/g, "") || "section";
  const base = `note-${slug}`;
  const count = counts.get(base) || 0;
  counts.set(base, count + 1);
  return count ? `${base}-${count + 1}` : base;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  const headingIds = new Map();
  let listType = "";
  let inCode = false;
  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = "";
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      closeList();
      if (inCode) {
        html.push("</code></pre>");
      } else {
        html.push("<pre><code>");
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      html.push(escapeHtml(rawLine) + "\n");
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line.trim());
    if (image) {
      closeList();
      const src = safeNoteMediaUrl(image[2]);
      const alt = escapeHtml(image[1] || "frame grid");
      if (src) {
        html.push(`<figure class="note-image-frame"><img src="${src}" alt="${alt}"><figcaption>${alt}</figcaption></figure>`);
      } else {
        html.push(`<p>${inlineMarkdown(line)}</p>`);
      }
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      closeList();
      const level = heading[1].length;
      const id = noteHeadingId(heading[2], headingIds);
      html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    const numbered = /^\d+\.\s+(.+)$/.exec(line);
    if (numbered) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
      continue;
    }
    if (line.startsWith(">")) {
      closeList();
      html.push(`<blockquote>${inlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  if (inCode) html.push("</code></pre>");
  return html.join("");
}

function noteOutline(markdown, limit = 12) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const headingIds = new Map();
  const headings = [];
  let inCode = false;
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (!heading) continue;
    const text = plainHeadingText(heading[2]);
    if (!text) continue;
    headings.push({
      level: heading[1].length,
      text,
      id: noteHeadingId(heading[2], headingIds)
    });
  }
  if (!headings.length) return "";
  return `<section class="note-outline" aria-label="笔记目录">
    <div class="visual-rail-head">
      <strong>笔记目录</strong>
      <span>${headings.length} 节</span>
    </div>
    <div class="note-outline-list">
      ${headings.slice(0, limit).map(heading => `
        <a class="level-${heading.level}" href="#${escapeHtml(heading.id)}">${escapeHtml(heading.text)}</a>
      `).join("")}
    </div>
  </section>`;
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}

function seekTimeValue(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function seekTimeButton(seconds, className = "time-seek") {
  return `<button type="button" class="${escapeHtml(className)}" data-media-seek-time="${seekTimeValue(seconds)}" title="跳到 ${escapeHtml(fmt(seconds))}"><time>${escapeHtml(fmt(seconds))}</time></button>`;
}

function seekLearningVideo(seconds, sourceElement = null) {
  const value = Math.max(0, Number(seconds || 0));
  if (!Number.isFinite(value)) return false;
  const video = document.querySelector("[data-learning-video]");
  if (!video) return false;
  video.currentTime = value;
  video.scrollIntoView?.({ behavior: "smooth", block: "center" });
  const playResult = video.play?.();
  if (playResult?.catch) playResult.catch(() => {});
  document.querySelectorAll(".media-seek-active").forEach(node => node.classList.remove("media-seek-active"));
  sourceElement?.classList?.add("media-seek-active");
  video.classList?.add("media-seek-active");
  setTimeout(() => video.classList?.remove("media-seek-active"), 1400);
  return true;
}

function frameTimestampText(window, limit = 4) {
  const values = (window?.frame_timestamps || []).slice(0, limit).map(value => fmt(value));
  if (!values.length) return "";
  const suffix = (window.frame_timestamps || []).length > values.length ? "..." : "";
  return `${values.join(" / ")}${suffix}`;
}

function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function contentDispositionFilename(value = "") {
  let filename = "";
  for (const part of String(value || "").split(";")) {
    const [rawKey, ...rest] = part.trim().split("=");
    if (!rawKey || !rest.length) continue;
    const key = rawKey.toLowerCase();
    let raw = rest.join("=").trim().replace(/^"|"$/g, "");
    if (key === "filename*") {
      const marker = raw.indexOf("''");
      raw = marker >= 0 ? raw.slice(marker + 2) : raw;
      try {
        filename = decodeURIComponent(raw);
      } catch {
        filename = raw;
      }
      break;
    }
    if (key === "filename" && raw) {
      try {
        filename = decodeURIComponent(raw);
      } catch {
        filename = raw;
      }
    }
  }
  return filename.split(/[\\/]/).pop() || "";
}

function contentDispositionHint(value = "") {
  const filename = contentDispositionFilename(value);
  return filename ? `filename ${filename}` : "";
}

function requestHeaderNames(resource) {
  return safeHeaderNames(Object.keys(resource?.request_headers || {})) || "-";
}

function safeHeaderNames(names) {
  return (names || [])
    .map(name => String(name || "").trim())
    .filter(name => !/cookie|authorization/i.test(name))
    .sort()
    .join(", ");
}

function attemptHeaderNames(attempt) {
  return safeHeaderNames(attempt?.request_header_names) || "-";
}

function requestBodySummary(resource) {
  const body = resource?.request_body || {};
  const content = String(body.content || "");
  if (!content) return "";
  const method = String(resource.method || "POST").toUpperCase();
  const type = String(body.type || "body");
  if (content === "<redacted>") return `${method} ${type} body 已捕获`;
  return `${method} ${type} body ${fmtBytes(content.length) || `${content.length} B`}`;
}

function mseAppendEvidence(resource) {
  if (!resource?.mse_append_count && !resource?.mse_append_magic && !resource?.mse_append_total_bytes) return "";
  return [
    resource.mse_append_count ? `MSE append ${resource.mse_append_count}x` : "MSE append",
    resource.mse_append_magic || "",
    fmtBytes(resource.mse_append_total_bytes),
    resource.mse_append_mime || "",
    resource.mse_append_detected_kind ? `detected ${resource.mse_append_detected_kind}` : ""
  ].filter(Boolean).join(" ");
}

function hasRangeRequestHeader(resource) {
  return Object.keys(resource?.request_headers || {}).some(name => String(name).toLowerCase() === "range");
}

function compactIdList(values, limit = 3) {
  const ids = (values || []).map(value => String(value || "").trim()).filter(Boolean);
  if (!ids.length) return "";
  const suffix = ids.length > limit ? ` 等 ${ids.length} 个` : "";
  return `${ids.slice(0, limit).join(", ")}${suffix}`;
}

function llmAuditFlags(diag = {}) {
  const flags = [];
  if (diag.vision_failed_batch_count) flags.push(`视觉批次失败 ${diag.vision_failed_batch_count}`);
  if (diag.vision_model_rejected_image) flags.push("模型拒绝图片输入");
  if (diag.llm_event_count) flags.push(`LLM 事件 ${diag.llm_event_count}`);
  const lastFailure = diag.llm_last_failure || {};
  if (lastFailure.stage || lastFailure.code) {
    flags.push(`最后失败 ${lastFailure.stage || "llm"}/${lastFailure.code || "unknown"}`);
  }
  return flags;
}

function summaryDiagnosticText(task) {
  const diag = task?.summary_diagnostics || {};
  if (!Object.keys(diag).length) return "-";
  const visionGridCount = diag.vision_grid_count ?? diag.frame_grid_count ?? 0;
  const sentImages = diag.vision_image_count ?? 0;
  const omittedCount = Number(diag.omitted_frame_grid_count || 0);
  const missingImages = diag.all_sent_grids_had_images === false || diag.all_grids_had_images === false;
  const missingWindowIds = compactIdList(diag.missing_vision_image_window_ids);
  const omittedWindowIds = compactIdList(diag.omitted_vision_window_ids);
  return [
    diag.used_vision_llm ? "已使用视觉 LLM" : diag.used_text_llm ? "已使用文本 LLM" : diag.used_local_template ? "本地模板" : "",
    `模型 ${diag.llm_model || task.summary_source || "-"}`,
    diag.llm_provider ? `Provider ${diag.llm_provider}` : "",
    diag.llm_base_host ? `Base ${diag.llm_base_host}` : "",
    diag.llm_failure_code ? `LLM 失败 ${diag.llm_failure_stage || "unknown"}/${diag.llm_failure_code}` : "",
    diag.llm_failure_reason ? `原因 ${diag.llm_failure_reason}` : "",
    `视觉窗口 ${diag.visual_window_count ?? 0}`,
    `画面网格 ${diag.frame_grid_count ?? 0}`,
    `\u9001\u5165\u89c6\u89c9 ${sentImages}/${visionGridCount}`,
    omittedCount > 0 ? `\u8d85\u9650\u7701\u7565 ${omittedCount}` : "",
    missingWindowIds ? `缺图 ${missingWindowIds}` : "",
    omittedWindowIds ? `省略窗口 ${omittedWindowIds}` : "",
    missingImages ? "\u5b58\u5728\u7f3a\u5931\u56fe\u7247" : "",
    ...llmAuditFlags(diag),
    diag.used_page_text_fallback ? `页面文本 ${diag.page_text_char_count ?? 0} 字` : "",
    diag.used_page_text_fallback ? `浏览器字幕 ${diag.browser_subtitle_count ?? 0} 条` : "",
    diag.used_page_text_fallback ? `合并文本 ${diag.combined_text_char_count ?? 0} 字` : "",
    diag.summary_warning || ""
  ].filter(Boolean).join(" · ");
}

function currentPageTasks() {
  return tasks.filter(task => task.source_type === "current_page");
}

function latestCurrentPageTask() {
  return currentPageTasks()[0] || null;
}

function currentPageDisplayRank(task) {
  if (!task) return 90;
  if (task.status === "running") return 0;
  if (task.status === "queued") return 1;
  if (task.status === "success" && hasExportableMedia(task) && task.note_path) return 2;
  if (task.status === "success" && hasExportableMedia(task)) return 3;
  if (task.status === "success") return 4;
  if (task.status === "failed" && task.note_path) return 5;
  if (task.status === "failed") return 6;
  return 7;
}

function currentPageDisplayTask(list, { includeManual = false } = {}) {
  const candidates = (Array.isArray(list) ? list : [])
    .filter(task => task?.source_type === "current_page")
    .filter(task => includeManual || !isManualUrlTask(task));
  if (!candidates.length && !includeManual) {
    return currentPageDisplayTask(list, { includeManual: true });
  }
  return candidates
    .map((task, index) => ({ task, index }))
    .sort((a, b) => currentPageDisplayRank(a.task) - currentPageDisplayRank(b.task) || a.index - b.index)[0]?.task || null;
}

function preferredCurrentPageTask() {
  return currentPageDisplayTask(currentPageTasks());
}

function directRouteState(task) {
  if (!task) return "empty";
  if (task.status === "running" || task.status === "queued") return "running";
  if (task.status === "success" && hasExportableMedia(task) && task.note_path) return "ready";
  if (task.status === "success" && hasExportableMedia(task)) return "downloaded";
  if (task.status === "failed") {
    return ["drm_or_encrypted", "no_media_found", "unsupported_manifest"].includes(task.error_code) ? "blocked" : "failed";
  }
  return "empty";
}

function directRouteCopy(task) {
  const state = directRouteState(task);
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const mediaName = taskMediaDisplayName(task);
  if (state === "ready") {
    return {
      badge: "可复习",
      title: "最近当前页直取已生成笔记",
      detail: `${selected.kind || "media"} · ${attempts.length || 0} 次下载尝试 · ${visualWindows(task).length || 0} 个视觉窗口`,
      hint: "在右侧结果区查看笔记、字幕、画面切片和下载诊断。"
    };
  }
  if (state === "downloaded") {
    return {
      badge: "已下载",
      title: "视频已直取到本地",
      detail: `${selected.kind || "media"} · 可导出 ${mediaName}`,
      hint: "选择该任务后点击“继续切片总结”，复用已下载视频生成完整笔记。"
    };
  }
  if (state === "running") {
    return {
      badge: "处理中",
      title: task.status === "queued" ? "当前页任务排队中" : "当前页任务正在处理",
      detail: `${task.phase || "running"} · ${task.progress || 0}%`,
      hint: "后端会按下载、转写、切片、图文总结顺序更新进度。"
    };
  }
  if (state === "blocked") {
    return {
      badge: "不可直取",
      title: task.error_code === "drm_or_encrypted" ? "最近任务遇到 DRM/不可还原媒体" : "最近任务没有拿到可下载视频",
      detail: task.error_detail || task.message || task.error_code || "无法直接下载",
      hint: `${directFailureBoundaryText()}。继续播放后重检，或切到本地视频入口上传文件。`
    };
  }
  if (state === "failed") {
    return {
      badge: "需重试",
      title: "最近当前页任务下载失败",
      detail: task.error_detail || task.message || task.error_code || "下载失败",
      hint: "常见原因是登录态、Referer、签名过期；回到原页面播放几秒后重新预检。"
    };
  }
  return {
    badge: "等待",
    title: "等待扩展侧栏创建当前页任务",
    detail: "在课程页打开 Chrome/Edge Side Panel，先预检候选，再开始总结。",
    hint: `只直取浏览器暴露的 ${directCapabilityFormatsText()} 或 yt-dlp 可解析页面，${directFailureBoundaryText()}。`
  };
}

function browserRouteMetrics(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  return [
    { label: "最近资源", value: selected.kind || "-" },
    { label: "视觉窗口", value: task ? String(visualWindows(task).length || 0) : "-" },
    { label: "下载尝试", value: task ? String(attempts.length || 0) : "-" },
    { label: "状态", value: task ? statusText(task) : "等待" }
  ];
}

function browserRouteHandoffItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  const mediaName = taskMediaDisplayName(task);
  return [
    {
      state: selected.url ? "done" : "pending",
      label: "资源证据",
      value: selected.kind || (task ? "未锁定" : "等待侧栏"),
      detail: selected.url
        ? (resourceSourceText(selected) || selected.source || "浏览器候选")
        : "播放几秒后由扩展读取播放器和媒体请求"
    },
    {
      state: task?.media_path ? "done" : attempts.length ? "active" : "pending",
      label: "本地落地",
      value: task?.media_path ? mediaName : attempts.length ? `${attempts.length} 次尝试` : "未下载",
      detail: task?.media_path ? "已可导出或继续切片总结" : "直接文件、ffmpeg 或 yt-dlp 路线"
    },
    {
      state: windows.length ? "done" : task?.frame_grids?.length ? "active" : "pending",
      label: "画面切片",
      value: windows.length ? `${windows.length} 窗口` : task?.frame_grids?.length ? `${task.frame_grids.length} 网格` : "待生成",
      detail: "按字幕时间和抽帧网格对齐"
    },
    {
      state: task?.note_path ? "done" : canContinueFromDownloadedMedia(task) ? "active" : "pending",
      label: "学习笔记",
      value: task?.note_path ? "已完成" : canContinueFromDownloadedMedia(task) ? "可继续" : "待总结",
      detail: task?.note_path ? "可导出 Markdown/资料包" : "复用本地视频生成完整笔记"
    }
  ];
}

function browserRouteHandoffHtml(task) {
  return `<div class="browser-route-handoff" aria-label="当前页直取交接清单">
    ${browserRouteHandoffItems(task).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function browserExtensionHandoffSteps(backendUrl = "") {
  return [
    {
      index: "1",
      title: "打开课程播放页",
      detail: "在学习通、B 站、YouTube 或其他课程页播放几秒，让真实媒体请求出现。"
    },
    {
      index: "2",
      title: "打开扩展侧栏",
      detail: backendUrl
        ? `后端 ${backendUrl} 已复制；在 Chrome/Edge 侧栏点击“总结当前视频”。`
        : "必要时先复制后端地址，再在 Chrome/Edge 侧栏点击“总结当前视频”。"
    },
    {
      index: "3",
      title: "回到工作台",
      detail: "这里跟踪下载、转写、抽帧切片、视觉窗口和 Markdown 笔记。"
    }
  ];
}

function browserExtensionHandoffHtml(backendUrl = "") {
  return `<div class="browser-extension-handoff" aria-label="当前播放页交接操作">
    ${browserExtensionHandoffSteps(backendUrl).map(item => `<section>
      <b>${escapeHtml(item.index)}</b>
      <strong>${escapeHtml(item.title)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function browserExtensionHandoffStatusHtml(backendUrl = "") {
  const url = backendUrl || (API || (isBackendSameOrigin() ? window.location.origin : DEFAULT_BACKEND_ORIGIN));
  return `
    <span class="capture-status-chip bridge handoff"><b>后端</b>${escapeHtml(url)} 已复制</span>
    <span class="capture-status-chip media handoff"><b>课程页</b>播放几秒后打开扩展侧栏</span>
    <span class="capture-status-chip vision pending handoff"><b>侧栏</b>点击“总结当前视频”</span>
    <span class="capture-status-chip asr handoff"><b>工作台</b>等待任务、切片和笔记</span>
  `;
}

function setBrowserExtensionHandoffStatus(backendUrl = "") {
  if (!els.browserBridgeStatus) return;
  const url = backendUrl || (API || (isBackendSameOrigin() ? window.location.origin : DEFAULT_BACKEND_ORIGIN));
  els.browserBridgeStatus.classList.add("capture-status-grid");
  els.browserBridgeStatus.innerHTML = browserExtensionHandoffStatusHtml(url);
  els.browserBridgeStatus.title = `后端地址已复制：${url}。请在课程播放页打开 LearnNote 扩展侧栏，点击“总结当前视频”。`;
  els.browserBridgeStatus.dataset.mediaText = "等待扩展侧栏读取当前页视频";
}

function browserBridgeGateItems(task) {
  const hasCurrentPageTask = task?.source_type === "current_page";
  const hasBrowserEvidence = Boolean(task?.selected_resource?.url || task?.active_video || task?.download_attempts?.length);
  const hasProcessedMedia = Boolean(task?.media_path || task?.note_path);
  return [
    {
      state: hasCurrentPageTask ? "done" : "active",
      label: "扩展侧栏",
      value: hasCurrentPageTask ? "已交接" : "必须从课程页打开",
      detail: hasCurrentPageTask
        ? "任务由 Chrome/Edge Side Panel 创建，保留浏览器上下文。"
        : "Web 工作台不能直接读取你正在播放的 Chrome 标签页。"
    },
    {
      state: hasBrowserEvidence ? "done" : hasCurrentPageTask ? "active" : "pending",
      label: "播放证据",
      value: hasBrowserEvidence ? "已记录" : "等待侧栏读取",
      detail: hasBrowserEvidence
        ? "已保存候选资源、播放器快照或下载尝试。"
        : "侧栏会读取 DOM、Performance、webRequest、字幕和一次性 cookie。"
    },
    {
      state: hasProcessedMedia ? "done" : task ? "active" : "pending",
      label: "本地管线",
      value: hasProcessedMedia ? "已保存" : "等待任务",
      detail: hasProcessedMedia
        ? "可以继续查看笔记、切片、审计或导出资料。"
        : "拿到可访问媒体后才进入下载、转写、抽帧和总结。"
    }
  ];
}

function browserBridgeGateHtml(task) {
  return `<div class="browser-bridge-gate" aria-label="扩展侧栏交接门">
    <header>
      <span>扩展侧栏交接门</span>
      <strong>读取当前播放页只能从 Chrome/Edge 扩展发起</strong>
    </header>
    <div>
      ${browserBridgeGateItems(task).map(item => `<section class="${escapeHtml(item.state)}">
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </section>`).join("")}
    </div>
  </div>`;
}

function browserRouteActions(task) {
  const state = directRouteState(task);
  const actions = [];
  if (task?.id) {
    actions.push(`<button type="button" data-select-browser-task="${escapeHtml(task.id)}">查看任务</button>`);
  }
  if (task?.id && canContinueFromDownloadedMedia(task)) {
    actions.push(`<button type="button" data-rerun-browser-task="${escapeHtml(task.id)}">继续切片总结</button>`);
  }
  if (task?.media_path) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>`);
  }
  if (hasTaskAudit(task)) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "audit"))}">下载审计</a>`);
  }
  if (hasTaskDiagnostics(task)) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">下载诊断</a>`);
  }
  if (!task?.id) {
    actions.push(`<button type="button" class="primary" data-browser-route-action="open-extension">去扩展侧栏开始</button>`);
  }
  actions.push(`<button type="button" data-browser-route-action="refresh">刷新任务</button>`);
  actions.push(`<button type="button" data-browser-route-action="copy-backend">复制后端地址</button>`);
  if (!task?.id || state === "blocked" || state === "failed" || state === "empty") {
    actions.push(`<button type="button" data-browser-route-action="local-video">本地视频兜底</button>`);
  }
  return `<div class="browser-route-actions">${actions.join("")}</div>`;
}

function browserRouteSummaryHtml(task = null) {
  const state = directRouteState(task);
  const copy = directRouteCopy(task);
  return `<section class="browser-route-summary-card ${escapeHtml(state)}">
    <div class="browser-route-summary-main">
      <span>${escapeHtml(copy.badge)}</span>
      <strong>${escapeHtml(copy.title)}</strong>
      <small>${escapeHtml(copy.hint)}</small>
    </div>
    <p>${escapeHtml(copy.detail)}</p>
    <div class="browser-route-summary-metrics">
      ${browserRouteMetrics(task).map(item => `<span><b>${escapeHtml(item.value)}</b>${escapeHtml(item.label)}</span>`).join("")}
    </div>
    ${browserBridgeGateHtml(task)}
    ${browserRouteHandoffHtml(task)}
    ${browserRouteActions(task)}
  </section>`;
}

function browserRouteEmptyHandoffHtml() {
  return `<section class="browser-route-summary-card handoff empty">
    <div class="browser-route-summary-main">
      <span>交接</span>
      <strong>当前页直取需要从扩展侧栏开始</strong>
      <small>Web 工作台不能直接读取你正在播放的浏览器标签页；这里负责查看任务、切片和笔记。</small>
    </div>
    <p>不做标签页录制、不刷课、不绕过 DRM；如果课程页没有暴露可访问媒体 URL，就切到本地视频上传。</p>
    ${browserExtensionHandoffHtml()}
    ${browserBridgeGateHtml(null)}
    ${browserRouteHandoffHtml(null)}
    ${browserRouteActions(null)}
  </section>`;
}

function renderBrowserRouteSummary() {
  if (!els.browserRouteSummary) return;
  const task = preferredCurrentPageTask();
  els.browserRouteSummary.innerHTML = task ? browserRouteSummaryHtml(task) : browserRouteEmptyHandoffHtml();
}

function isManualUrlTask(task) {
  const selected = task?.selected_resource || {};
  return task?.source_type === "current_page"
    && (selected.source === "manual" || String(selected.request_type || "").startsWith("manual"));
}

function workflowTaskForSource(source) {
  const matchesSource = source === "local"
    ? task => task?.source_type === "local"
    : source === "url"
      ? isManualUrlTask
      : task => task?.source_type === "current_page" && !isManualUrlTask(task);
  const candidates = tasks.filter(matchesSource);
  if (!candidates.length && source === "browser") return latestCurrentPageTask();
  const selected = tasks.find(task => task.id === selectedTaskId);
  if (selected && matchesSource(selected)) return selected;
  return sortedVisibleTasks(candidates, selectedTaskId)[0] || null;
}

function sourceRouteRailItem(source) {
  const task = workflowTaskForSource(source);
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const failed = task?.status === "failed";
  const running = task?.status === "running" || task?.status === "queued";
  const windows = task ? visualWindows(task) : [];
  const sourceMeta = {
    browser: {
      label: "当前页",
      title: "浏览器直取",
      detail: "扩展交接播放器、请求和一次性 Cookie",
      empty: "待扩展交接"
    },
    local: {
      label: "本地",
      title: "本地视频",
      detail: "拖入文件后复用转写、切片、图文总结",
      empty: "待选择文件"
    },
    url: {
      label: "链接",
      title: "链接解析",
      detail: "页面、直连、HLS/DASH 先预检再下载",
      empty: "待填写 URL"
    }
  }[source];
  const status = hasNote
    ? "已成稿"
    : hasMedia
      ? "已下载"
      : failed
        ? (task.error_code || "需兜底")
        : running
          ? `${task.progress || 0}%`
          : sourceMeta.empty;
  const detail = hasNote
    ? "笔记、转写和资料包可查看"
    : windows.length
      ? `${windows.length} 个视觉窗口已生成`
      : hasMedia
        ? "可继续切片总结"
        : failed
          ? source === "browser" ? "不录制，切本地上传兜底" : "查看诊断后重试"
          : sourceMeta.detail;
  const state = hasNote || hasMedia
    ? "ready"
    : failed
      ? "blocked"
      : running
        ? "active"
        : "idle";
  return { source, task, state, status, detail, ...sourceMeta };
}

function sourceRouteRailHtml() {
  return ["browser", "local", "url"].map(source => {
    const item = sourceRouteRailItem(source);
    const selected = selectedSource === source ? " selected" : "";
    const taskAttr = item.task?.id ? ` data-task-id="${escapeHtml(item.task.id)}"` : "";
    return `<button type="button" class="source-route-item ${escapeHtml(item.state)}${selected}" data-source-route="${escapeHtml(source)}"${taskAttr}>
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.title)}</strong>
      <small>${escapeHtml(item.status)}</small>
      <em>${escapeHtml(item.detail)}</em>
    </button>`;
  }).join("");
}

function renderSourceRouteRail() {
  if (!els.sourceRouteRail) return;
  els.sourceRouteRail.innerHTML = sourceRouteRailHtml();
}

function workflowSourceConfig(source, task = null) {
  if (source === "local") {
    return {
      eyebrow: "本地视频",
      title: task ? "本地视频正在走完整切片链路" : "拖入本地视频，走同一套图文总结",
      hint: task ? statusText(task) : "适合 DRM、不可还原 blob 或学习平台不暴露媒体 URL 的课程。",
      steps: [
        ["导入文件", "mp4 / flv / avi / mkv / webm"],
        ["提取音频", "字幕优先，所选 ASR 兜底"],
        ["抽帧切片", "按视觉窗口生成网格"],
        ["整理笔记", "Markdown + 资料包"]
      ]
    };
  }
  if (source === "url") {
    return {
      eyebrow: "链接解析",
      title: task ? "链接任务已进入处理队列" : "粘贴网页或媒体链接，先预检再处理",
      hint: task ? statusText(task) : "无后缀播放接口可以手动指定视频直连、HLS 或 DASH。",
      steps: [
        ["粘贴链接", "页面 / 直连 / manifest"],
        ["预检类型", "检查 MIME、大小和策略"],
        ["下载合并", "yt-dlp 或 ffmpeg"],
        ["图文笔记", "字幕 + 切片总结"]
      ]
    };
  }
  const routeCopy = directRouteCopy(task);
  return {
    eyebrow: "当前页直取",
    title: routeCopy.title,
    hint: routeCopy.hint,
    steps: [
      ["读取当前页", "播放器、请求、Cookie"],
      ["预检资源", "mp4 / FLV / HLS / DASH"],
      ["切片识别", "字幕和画面网格"],
      ["生成笔记", "时间轴、复习题、资料包"]
    ]
  };
}

function workflowActiveIndex(task) {
  if (!task) return -1;
  if (task.status === "success") return 4;
  if (task.status === "failed") {
    if (task.note_path) return 4;
    if (hasReadableTranscript(task) || task.visual_windows?.length || task.frame_grids?.length) return 3;
    if (hasExportableMedia(task)) return 2;
    return 1;
  }
  const phase = task.phase || "queued";
  if (["queued", "detecting"].includes(phase)) return 0;
  if (phase === "downloading") return 1;
  if (["processing_video", "transcribing", "extracting_frames"].includes(phase)) return 2;
  if (phase === "summarizing") return 3;
  if (phase === "completed") return 4;
  return 0;
}

function workflowStepState(task, index) {
  if (!task) return "pending";
  const activeIndex = workflowActiveIndex(task);
  if (task.status === "failed") {
    if (index < activeIndex) return "done";
    if (index === activeIndex) return "blocked";
    return "pending";
  }
  if (task.status === "success" || activeIndex >= 4) return "done";
  if (index < activeIndex) return "done";
  if (index === activeIndex) return "active";
  return "pending";
}

function sourceRouteInsightItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  const mediaName = taskMediaDisplayName(task);
  if (source === "local") {
    return [
      ["视频入口", "本地文件直进管线", task?.media_path ? `已生成 ${mediaName}` : "拖拽上传后保存在 D 盘 data/uploads"],
      ["理解方式", "字幕优先，所选 ASR 兜底", "同样抽帧切片并送入视觉窗口"],
      ["适用场景", "平台不暴露 URL 时兜底", "DRM、不可还原 blob、过期签名都可改走本地"]
    ];
  }
  if (source === "url") {
    return [
      ["解析顺序", "直连优先，页面解析兜底", "手动指定 video/HLS/DASH 可减少误判"],
      ["下载方式", "yt-dlp / ffmpeg / 直接下载", task ? `${attempts.length || 0} 次下载尝试` : "预检通过后再进入任务"],
      ["输出产物", "media.mp4 + 图文笔记", windows.length ? `${windows.length} 个视觉窗口` : "生成后可导出资料包"]
    ];
  }
  return [
    ["浏览器证据", selected.url ? (resourceSourceText(selected) || selected.source || "候选资源") : "Side Panel 嗅探候选", selected.kind ? `${selected.kind} · ${selected.playback_match ? playbackText(selected.playback_match) : "待预检"}` : "播放器、请求、字幕、Cookie 一次性交接"],
    ["直取边界", "只下载可访问媒体", "不录制、不刷课、不绕过 DRM"],
    ["学习产物", "转写 + 切片 + 视觉总结", windows.length ? `${windows.length} 个视觉窗口` : task ? statusText(task) : "预检后生成完整笔记"]
  ];
}

function sourceRouteInsightsHtml(source, task = null) {
  return `<div class="source-route-insights" aria-label="路线产物">
    ${sourceRouteInsightItems(source, task).map(([label, title, detail]) => `<section>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceWorkflowBriefItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const routeLabel = source === "local" ? "本地视频" : source === "url" ? "链接解析" : "当前页直取";
  const routeDetail = source === "browser"
    ? selected.url
      ? `${selected.kind || "media"} · ${resourceSourceText(selected) || selected.source || "浏览器候选"}`
      : "从扩展侧栏读取播放器、请求和字幕"
    : source === "local"
      ? "拖拽或选择视频后直接进入同一套切片管线"
      : "粘贴页面、直连视频或 manifest，先预检再处理";
  const nextStep = task
    ? canContinueFromDownloadedMedia(task)
      ? "继续切片总结"
      : task.status === "failed"
        ? "查看诊断或切本地兜底"
        : task.status === "success"
          ? "查看笔记和资料包"
          : statusText(task)
    : source === "local"
      ? "选择文件"
      : source === "url"
        ? "预检链接"
        : "打开扩展侧栏总结当前页";
  const visualDetail = visualUnderstandingEnabled()
    ? `${visualPlanText()}，与字幕片段对齐`
    : "视觉理解关闭，仅生成转写笔记";
  return [
    ["入口", routeLabel, routeDetail],
    ["下一步", nextStep, task ? `${task.phase || task.status || "任务"} · ${task.progress || 0}%` : "先完成入口动作"],
    ["切片", visualUnderstandingEnabled() ? "图文窗口" : "纯文本", visualDetail],
    ["边界", source === "browser" ? "非录制直取" : source === "local" ? "离线兜底" : "可预检链接", source === "browser" ? "只下载已暴露且可访问的媒体，不刷课、不绕过 DRM" : "输出与当前页任务一致：media、转写、切片、Markdown"]
  ];
}

function sourceWorkflowBriefHtml(source, task = null) {
  return `<div class="source-workflow-brief" aria-label="学习流总览">
    ${sourceWorkflowBriefItems(source, task).map(([label, value, detail]) => `<section>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceRunModeItems(source, task = null) {
  const mediaName = taskMediaDisplayName(task);
  if (source === "url") {
    return [
      {
        state: "ready",
        label: "完整笔记",
        title: "生成新的链接笔记",
        detail: "粘贴页面、直连视频或 manifest，下载后进入转写、切片和图文总结。",
        action: "start-url"
      },
      {
        state: "ready",
        label: "只下载",
        title: "先把视频拉到本地",
        detail: `适合先验证平台资源是否可访问，再从 ${mediaName} 继续切片总结。`,
        action: "download-url"
      },
      {
        state: canContinueFromDownloadedMedia(task) ? "active" : "wait",
        label: "继续切片",
        title: canContinueFromDownloadedMedia(task) ? `从 ${mediaName} 继续` : "等待本地媒体",
        detail: "复用已下载视频进入转写、抽帧、视觉窗口和图文总结；不会录制页面。",
        action: canContinueFromDownloadedMedia(task) ? "continue-media" : ""
      }
    ];
  }
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const canContinue = canContinueFromDownloadedMedia(task);
  const isDownloadOnly = task?.mode === "download_only";
  const isRerun = task?.mode === "rerun_from_media";
  const fullState = hasNote ? "pass" : isRerun || (task && !isDownloadOnly) ? "active" : "ready";
  const downloadState = hasMedia ? "pass" : isDownloadOnly ? "active" : "ready";
  const continueState = canContinue ? "active" : isRerun ? "pass" : "wait";
  const fullAction = source === "url" ? "start-url" : source === "browser" ? "open-extension" : "upload-local";
  const downloadAction = source === "url" ? "download-url" : source === "browser" ? "open-extension" : "";
  return [
    {
      state: fullState,
      label: "完整笔记",
      title: hasNote ? "已生成图文笔记" : source === "local" ? "上传后直接总结" : "下载后直接总结",
      detail: source === "local"
        ? "上传文件后进入转写、切片、视觉总结。"
        : "媒体直取成功后自动进入转写、切片和图文总结。",
      action: hasNote ? "" : fullAction
    },
    {
      state: downloadState,
      label: "只下载",
      title: hasMedia ? `${mediaName} 已保存` : "先把视频拉到本地",
      detail: source === "local"
        ? "本地文件会复制到任务目录，无需平台下载。"
        : "适合先验证平台资源是否可访问，再决定是否继续总结。",
      action: hasMedia ? "" : downloadAction
    },
    {
      state: continueState,
      label: "继续切片",
      title: canContinue ? `从 ${mediaName} 继续` : isRerun ? "正在生成完整笔记" : "等待本地媒体",
      detail: "复用已下载视频进入转写、抽帧、视觉窗口和图文总结；不会录制页面。",
      action: canContinue ? "continue-media" : ""
    }
  ];
}

function sourceRunModesHtml(source, task = null) {
  return `<div class="source-run-modes" aria-label="运行模式">
    ${sourceRunModeItems(source, task).map(item => {
      const attrs = item.action
        ? ` data-source-workflow-action="${escapeHtml(item.action)}"${item.action === "continue-media" && task?.id ? ` data-task-id="${escapeHtml(task.id)}"` : ""}`
        : " disabled";
      return `<button type="button" class="${escapeHtml(item.state)}"${attrs}>
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.title)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </button>`;
    }).join("")}
  </div>`;
}

function sourcePrimaryCommand(source, task = null) {
  if (task?.note_path) {
    return {
      state: "done",
      label: "查看笔记",
      title: "已生成图文学习笔记",
      detail: "打开结果区查看 Markdown、视觉切片、问答和资料包导出。",
      selectTask: task.id
    };
  }
  if (task?.status === "running" || task?.status === "queued") {
    return {
      state: "active",
      label: "查看进度",
      title: statusText(task),
      detail: `${task.phase || "processing"} · ${task.progress || 0}%`,
      selectTask: task.id
    };
  }
  if (canContinueFromDownloadedMedia(task)) {
    const mediaName = taskMediaDisplayName(task);
    return {
      state: "ready",
      label: "继续切片总结",
      title: "复用已下载视频",
      detail: `从本地 ${mediaName} 继续转写、抽帧、视觉窗口和图文总结。`,
      action: "continue-media",
      taskId: task.id
    };
  }
  if (task?.status === "success") {
    return {
      state: "done",
      label: "查看结果",
      title: "任务已完成",
      detail: "打开结果区查看下载产物、切片索引、诊断和可继续动作。",
      selectTask: task.id
    };
  }
  if (task?.status === "failed") {
    return {
      state: "blocked",
      label: source === "browser" ? "切到本地兜底" : "查看诊断",
      title: task.error_code || "任务失败",
      detail: source === "browser"
        ? "当前页直取失败时，优先上传本地视频继续同一套切片总结管线。"
        : "打开结果区查看诊断、失败原因和可恢复动作。",
      action: source === "browser" ? "switch-local" : "",
      selectTask: source === "browser" ? "" : task.id
    };
  }
  if (source === "local") {
    return {
      state: "ready",
      label: "选择本地视频",
      title: "拖入或选择 mp4 / mkv / webm",
      detail: "本地文件直接进入转写、抽帧、视觉切片和笔记生成。",
      action: "choose-local"
    };
  }
  if (source === "url") {
    return {
      state: "ready",
      label: "预检链接",
      title: "先确认可下载再生成",
      detail: "适合页面链接、直连视频、m3u8 或 mpd；通过后可一键生成笔记。",
      action: "preflight-url"
    };
  }
  return {
    state: "ready",
    label: "去扩展侧栏开始",
    title: "读取正在播放的视频",
    detail: "从 Chrome/Edge 当前页嗅探可访问媒体，不录制标签页。",
    action: "open-extension"
  };
}

function sourcePrimaryCommandHtml(source, task = null) {
  const command = sourcePrimaryCommand(source, task);
  const attrs = command.selectTask
    ? `data-select-workflow-task="${escapeHtml(command.selectTask)}"`
    : command.action
      ? `data-source-workflow-action="${escapeHtml(command.action)}"${command.taskId ? ` data-task-id="${escapeHtml(command.taskId)}"` : ""}`
      : "disabled";
  return `<div class="source-primary-command ${escapeHtml(command.state)}" aria-label="主要下一步">
    <div>
      <span>下一步</span>
      <strong>${escapeHtml(command.title)}</strong>
      <small>${escapeHtml(command.detail)}</small>
    </div>
    <button type="button" ${attrs}>${escapeHtml(command.label)}</button>
  </div>`;
}

function sourceWorkflowStatusItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  const failed = task?.status === "failed";
  const running = task?.status === "running" || task?.status === "queued";
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const sourceLabel = source === "local" ? "本地视频" : source === "url" ? "链接解析" : "当前页直取";
  const routeDetail = source === "browser"
    ? selected.kind ? `${selected.kind} · ${resourceSourceText(selected) || selected.source || "候选"}` : "扩展侧栏交接播放器、媒体请求和一次性 Cookie"
    : source === "local"
      ? "文件直接进入本地管线，不依赖平台暴露 URL"
      : "手动 URL 可先预检，再进入直连、manifest 或 yt-dlp 路线";
  const downloadValue = hasMedia
    ? taskMediaDisplayName(task)
    : attempts.length
      ? `${attempts.length} 次尝试`
      : source === "local" ? "待上传" : source === "url" ? "待预检" : "待候选";
  const downloadDetail = hasMedia
    ? "已保存到本地，可导出或继续切片总结"
    : failed
      ? task.error_code || "下载失败"
      : running ? `${task.phase || "running"} · ${task.progress || 0}%` : "开始任务前先确认后端可访问媒体";
  const sliceValue = windows.length
    ? `${windows.length} 个视觉窗口`
    : visualUnderstandingEnabled() ? visualPlanText() : "仅转写";
  const sliceDetail = windows.length
    ? "可在学习切片页核对画面、字幕和自测题"
    : visualUnderstandingEnabled() ? "下载后抽帧拼网格，并按窗口对齐字幕" : "图文理解关闭，不生成视觉窗口";
  const fallbackValue = source === "browser"
    ? failed ? "本地兜底" : "非录制"
    : source === "local" ? "离线管线" : "页面兜底";
  const fallbackDetail = source === "browser"
    ? "不可还原 blob、DRM 或签名过期时切到本地视频"
    : source === "local" ? "同样输出 Markdown、诊断和资料包" : "直连失败后可切页面解析或本地上传";
  return [
    {
      state: task || source !== "browser" ? "pass" : "active",
      label: "入口",
      value: sourceLabel,
      detail: routeDetail
    },
    {
      state: hasMedia ? "pass" : failed ? "block" : running ? "active" : "wait",
      label: "下载",
      value: downloadValue,
      detail: downloadDetail
    },
    {
      state: windows.length ? "pass" : visualUnderstandingEnabled() ? (hasMedia || running ? "active" : "wait") : "skip",
      label: "切片",
      value: sliceValue,
      detail: sliceDetail
    },
    {
      state: failed && source === "browser" ? "warn" : "pass",
      label: "边界",
      value: fallbackValue,
      detail: fallbackDetail
    }
  ];
}

function sourceWorkflowStatusHtml(source, task = null) {
  return `<div class="source-workflow-status" aria-label="路线状态">
    ${sourceWorkflowStatusItems(source, task).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceWorkflowActionsHtml(source, task = null) {
  const actions = [];
  if (source === "browser") {
    if (task?.id && canContinueFromDownloadedMedia(task)) {
      actions.push(["continue-media", "继续切片总结", task.id]);
    }
    if (!task?.id) actions.push(["open-extension", "去扩展侧栏开始", ""]);
    actions.push(["refresh-browser", task?.id ? "刷新任务" : "刷新交接状态", ""]);
    actions.push(["copy-backend", "复制后端地址", ""]);
    actions.push(["switch-local", task?.id ? "本地兜底" : "上传本地视频兜底", ""]);
  } else if (source === "local") {
    actions.push(["choose-local", "选择文件", ""]);
    actions.push(["upload-local", "上传并生成", ""]);
    actions.push(["open-options", "处理参数", ""]);
  } else {
    actions.push(["focus-url", "填写链接", ""]);
    actions.push(["preflight-url", "预检链接", ""]);
    actions.push(["start-url", "生成笔记", ""]);
    actions.push(["download-url", "只下载", ""]);
  }
  return `<div class="source-workflow-actions" aria-label="下一步操作">
    ${actions.map(([action, label, taskId]) => `<button type="button" data-source-workflow-action="${escapeHtml(action)}"${taskId ? ` data-task-id="${escapeHtml(taskId)}"` : ""}>${escapeHtml(label)}</button>`).join("")}
  </div>`;
}

function sourceWorkflowHtml(source = selectedSource, task = workflowTaskForSource(source)) {
  const config = workflowSourceConfig(source, task);
  const state = task ? statusText(task) : "等待开始";
  return `<section class="source-workflow-card ${escapeHtml(source)}">
    <header>
      <span>${escapeHtml(config.eyebrow)}</span>
      <strong>${escapeHtml(config.title)}</strong>
      <small>${escapeHtml(config.hint)}</small>
    </header>
    ${sourcePrimaryCommandHtml(source, task)}
    ${sourceWorkflowBriefHtml(source, task)}
    ${sourceRunModesHtml(source, task)}
    ${sourceWorkflowStatusHtml(source, task)}
    <ol class="source-workflow-lane">
      ${config.steps.map(([title, detail], index) => `<li class="${workflowStepState(task, index)}">
        <b>${index + 1}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(detail)}</small>
      </li>`).join("")}
    </ol>
    ${sourceRouteInsightsHtml(source, task)}
    <div class="source-option-strip" aria-label="当前处理参数">
      ${currentOptionSummaryItems().map(item => `<span>${escapeHtml(item)}</span>`).join("")}
    </div>
    ${sourceWorkflowActionsHtml(source, task)}
    <footer>
      <span>${escapeHtml(state)}</span>
      ${task ? `<button type="button" data-select-workflow-task="${escapeHtml(task.id)}">查看最近任务</button>` : `<em>选择入口后开始处理</em>`}
    </footer>
  </section>`;
}

function renderSourceWorkflow() {
  renderSourceRouteRail();
  if (!els.sourceWorkflow) return;
  els.sourceWorkflow.innerHTML = sourceWorkflowHtml();
}

function drmSignalText(signals = []) {
  const parts = [];
  const keySystems = [...new Set(signals.map(item => item.key_system).filter(Boolean))];
  const initTypes = [...new Set(signals.map(item => item.init_data_type).filter(Boolean))];
  if (keySystems.length) parts.push(`key system：${keySystems.slice(0, 3).join(", ")}`);
  if (initTypes.length) parts.push(`init data：${initTypes.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

function activeVideoText(active) {
  if (!active?.src) return "-";
  return [
    active.paused ? "暂停" : "播放中",
    `${fmt(active.current_time || 0)} / ${fmt(active.duration || 0)}`,
    `${active.width || 0}x${active.height || 0}`,
    active.frame_id !== null && active.frame_id !== undefined ? `frame ${active.frame_id}` : "",
    active.drm_detected ? "DRM/EME" : "",
    active.src
  ].filter(Boolean).join(" · ");
}

function statusText(task) {
  if (task.status === "success") return "已完成";
  if (task.status === "failed") return task.error_code || "失败";
  if (task.status === "queued") return "排队中";
  return task.message || task.phase;
}

function sourceText(task) {
  if (task.mode === "download_only") return "当前页下载";
  if (task.mode === "rerun_from_media") return "复用本地视频";
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${mediaKindText(task.selected_resource.kind) || "媒体"}` : "页面解析";
}

function mediaKindText(kind = "") {
  return ({
    hls: "HLS",
    dash: "DASH",
    video: "视频",
    audio: "音频",
    subtitle: "字幕",
    fragment: "分片",
    blob: "Blob"
  })[String(kind || "").toLowerCase()] || kind || "";
}

function playerLibrarySourceText(resource) {
  if (resource?.source !== "pageHookPlayer") return "";
  const label = String(resource.label || "");
  const libraries = [
    [/hls\.js/i, "hls.js"],
    [/dash\.js/i, "dash.js"],
    [/shaka/i, "shaka"],
    [/video\.js/i, "video.js"],
    [/DPlayer/i, "DPlayer"],
    [/ArtPlayer/i, "ArtPlayer"],
    [/\bxgplayer\b|XGPlayer/i, "xgplayer"],
    [/Aliplayer/i, "Aliplayer"],
    [/TcPlayer/i, "TcPlayer"],
    [/jwplayer/i, "jwplayer"]
  ];
  const match = libraries.find(([pattern]) => pattern.test(label));
  if (match) return `${match[1]} 已加载`;
  return "播放器已加载";
}

function resourceSourceText(resource) {
  const playerSource = playerLibrarySourceText(resource);
  if (playerSource) return `${playerSource}源地址`;
  if (resource?.source === "manifest-guess") return "同目录 manifest 猜测";
  if (resource?.source === "inferred-manifest") return "分片路径回推 manifest";
  if (resource?.source === "webRequestResolved") return "最终媒体地址";
  if (resource?.source === "webRequest") return "浏览器请求";
  if (resource?.source === "iframeHint") return "iframe 内播放器线索";
  if (resource?.source === "scriptHint") return "页面脚本线索";
  if (resource?.source === "domHint") return "页面元素线索";
  if (resource?.source === "locationHint") return "页面 URL 线索";
  if (String(resource?.source || "").startsWith("pageHook")) return "页面接口";
  return resource?.source || "";
}

function taskResolvedTargetText(task, limit = 92) {
  const selected = task?.selected_resource || {};
  const target = selected.resolved_url || "";
  if (!target || target === selected.url) return "";
  return compactUrl(target, limit);
}

function directResponseResolvedFact(resource = {}, limit = 86) {
  const target = String(resource?.resolved_url || "").trim();
  if (!target || target === resource?.url) return "";
  const source = String(resource?.source || "").toLowerCase();
  const responseType = String(resource?.headers?.["content-type"] || resource?.mime || "").toLowerCase();
  const url = String(resource?.url || "");
  const looksLikePlaybackApi = /(?:^|[/?&=._-])(api|play|player|stream|video|media|vod|quality|definition|rendition|profile|track)(?:[/?&=._-]|$)/i.test(url);
  const resolvedByResponse = source === "direct-response" || isTextResponseMime(responseType) || looksLikePlaybackApi;
  return resolvedByResponse ? `播放接口解析: ${compactUrl(target, limit)}` : "";
}

function playbackText(match) {
  return ({
    "exact-src": "当前 src",
    "source-element": "当前 source",
    "same-frame": "同播放器 frame",
    "blob-same-frame": "blob 播放同 frame",
    "blob-source": "Blob/MSE 来源映射",
    "range-near-playhead": "播放进度附近 Range 请求",
    "manifest-near-playhead": "播放进度附近 Manifest 请求",
    "resolved-final-url": "跳转后的真实媒体",
    "recent-media-request": "最近播放请求",
    "same-site-request": "同站请求",
    "inferred-from-fragment": "分片推断"
  })[match] || match || "";
}

const PIPELINE_STEPS = [
  { key: "downloading", label: "下载" },
  { key: "transcribing", label: "识别" },
  { key: "extracting_frames", label: "切片" },
  { key: "summarizing", label: "生成" },
  { key: "completed", label: "完成" }
];

const DOWNLOAD_ERROR_CODES = new Set(["no_media_found", "auth_required", "drm_or_encrypted", "download_forbidden", "unsupported_manifest"]);

const ERROR_GUIDES = {
  no_media_found: {
    title: "没有发现可直取的视频资源",
    body: ""
  },
  auth_required: {
    title: "资源需要登录态",
    body: "重新打开课程页面并确认已登录，再从扩展侧边栏创建任务；后端只会在点击任务时同步一次当前域 cookie。"
  },
  drm_or_encrypted: {
    title: "页面触发了 DRM/EME 加密媒体信号",
    body: ""
  },
  download_forbidden: {
    title: "媒体服务器拒绝下载",
    body: "通常是 Referer、cookie 或时效签名不匹配。回到原页面重新播放并立刻开始任务，或选择另一个候选资源。"
  },
  unsupported_manifest: {
    title: "manifest 或分片无法合并",
    body: ""
  },
  processing_failed: {
    title: "本地处理失败",
    body: "下载可能成功，但转音频、转写、抽帧或总结阶段失败。请查看诊断里的阶段和本地 data/tasks 产物。"
  },
  task_interrupted: {
    title: "任务已中断并自动收口",
    body: "任务超过 6 小时没有进度，通常是后端退出或系统重启。旧记录和已下载文件仍保留；有本地媒体时可继续切片总结，否则重新创建任务。"
  }
};

function directCapabilityFormatsText() {
  return healthDirectMediaFormats().split("/").filter(Boolean).join("、");
}

function directCapabilityManifestText() {
  const direct = assistantCapabilities().direct_media || {};
  return capabilityList(direct.manifests, ["m3u8", "mpd"], 2).join("/");
}

function directFailureBoundaryText() {
  return healthDirectBoundaryText() || "不录制 · 不绕过 DRM · 不刷课";
}

function errorGuideForCode(code, fallbackBody = "") {
  const guide = ERROR_GUIDES[code] || { title: "任务失败", body: fallbackBody || "请查看下载诊断里的尝试记录。" };
  if (code === "no_media_found") {
    return {
      ...guide,
      body: `可以先让页面视频播放几秒后重新检测；如果仍没有 ${directCapabilityFormatsText()}，请改用本地视频上传。`
    };
  }
  if (code === "drm_or_encrypted") {
    return {
      ...guide,
      body: `${directFailureBoundaryText()}。可直取 ${directCapabilityFormatsText()} 不存在时，只能使用本地视频入口。`
    };
  }
  if (code === "unsupported_manifest") {
    return {
      ...guide,
      body: `检测到了媒体线索，但它不是完整可下载的视频或播放列表。继续播放后重新检测，优先选择 ${directCapabilityManifestText()} 候选。`
    };
  }
  return guide;
}

function failureGuide(task) {
  if (!task || task.status !== "failed") return "";
  const guide = errorGuideForCode(task.error_code, task.error_detail);
  const attempts = task.download_attempts || [];
  const lastAttempt = attempts[attempts.length - 1] || null;
  const steps = recoveryStepItems(task);
  return `<div class="failure-guide">
    <strong>${escapeHtml(guide.title)}</strong>
    <p>${escapeHtml(guide.body)}</p>
    ${lastAttempt ? `<small>最近尝试：${escapeHtml([lastAttempt.strategy, lastAttempt.code, lastAttempt.status_code ? `HTTP ${lastAttempt.status_code}` : "", lastAttempt.message].filter(Boolean).join(" · "))}</small>` : ""}
    <ul>
      ${steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}
    </ul>
    ${recoveryActionsHtml(task)}
  </div>`;
}

function isChaoxingTask(task = {}) {
  const values = [
    task.page_url,
    task.title,
    task.error_detail,
    task.selected_resource?.url,
    task.selected_resource?.resolved_url,
    task.selected_resource?.initiator,
    task.selected_resource?.label,
    ...(task.download_attempts || []).flatMap(attempt => [attempt.url, attempt.resolved_url, attempt.source, attempt.message])
  ].map(value => String(value || "").toLowerCase()).join(" ");
  return /chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|\u5b66\u4e60\u901a|\u8d85\u661f/.test(values);
}

function recoveryStepItems(task) {
  if (Array.isArray(task?.recovery?.steps) && task.recovery.steps.length) {
    return task.recovery.steps.map(step => String(step));
  }
  const attempts = task?.download_attempts || [];
  const codes = new Set([task?.error_code, ...attempts.map(attempt => attempt.code)].filter(Boolean));
  const steps = [];
  const add = text => {
    if (text && !steps.includes(text)) steps.push(text);
  };
  if (isChaoxingTask(task)) {
    add(`检测到学习通/超星页面线索：请先在原课程页真实播放几秒，让 ananas/播放接口暴露 ${directCapabilityFormatsText()} 或带 Referer 的媒体请求；本工具只复用你当前登录态可访问的资源，${directFailureBoundaryText()}，不伪造进度，不自动答题。`);
  }
  if (codes.has("drm_or_encrypted") || task?.drm_detected) {
    add(`${directFailureBoundaryText()}；没有可访问 ${directCapabilityFormatsText()} 时，请改用本地视频入口。`);
  }
  if (codes.has("auth_required")) {
    add("重新打开课程页并确认登录有效，播放几秒后立刻重新创建任务。");
  }
  if (codes.has("download_forbidden")) {
    add("回到原页面继续播放后重新检测，优先选择带 Referer/Origin 或当前播放匹配的候选。");
  }
  if (codes.has("unsupported_manifest")) {
    add(`继续播放后重新检测，优先选择完整 ${directCapabilityManifestText()}，而不是孤立 ts/m4s 分片。`);
  }
  if (codes.has("task_interrupted")) {
    add(canContinueFromDownloadedMedia(task) ? "已下载媒体仍然可用，点击“继续切片总结”即可从本地断点继续。" : "重新创建同一链接任务；旧任务记录不会继续占用运行队列。" );
  }
  if (codes.has("no_media_found") || (!attempts.length && task?.status === "failed")) {
    add("先让视频实际播放几秒再重新检测；仍没有候选时上传本地视频。");
  }
  if (attempts.length > 1) {
    add(`后端已尝试 ${attempts.length} 条路线；打开诊断查看每次失败的 URL、状态码和策略。`);
  }
  if (task?.selected_resource?.request_headers && Object.keys(task.selected_resource.request_headers).length) {
    add(`已捕获可复用请求头名：${requestHeaderNames(task.selected_resource)}；不会保存 Cookie 或 Authorization 值。`);
  }
  if (hasRangeRequestHeader(task?.selected_resource)) {
    add("Range 只作为浏览器播放证据；正式下载会去掉播放 Range，避免只保存一个视频片段。");
  }
  if (canContinueFromDownloadedMedia(task)) {
    add(`这个任务已把视频下载到本地，可先导出 ${taskMediaDisplayName(task)}，或点击“继续切片总结”复用本地视频生成完整笔记。`);
  }
  if (task?.note_path) {
    add("已生成兜底笔记时，可以先导出 Markdown/资料包复习，再按诊断重新尝试直取。");
  }
  if (!steps.length) add("打开诊断查看下载尝试记录；当前页直取不稳定时可改用本地视频入口。");
  return steps;
}

function diagnosticRecoveryHtml(task) {
  const steps = recoveryStepItems(task);
  const recovery = task?.recovery || {};
  const primary = recovery.primary_action || null;
  const diagnosis = recovery.diagnosis || "";
  const summary = diagnosis || primary?.detail
    ? `<div class="recovery-diagnosis">
        ${diagnosis ? `<span>判断</span><strong>${escapeHtml(diagnosis)}</strong>` : ""}
        ${primary ? `<small>主动作：${escapeHtml(primary.label || primary.key || "查看诊断")}${primary.detail ? ` · ${escapeHtml(primary.detail)}` : ""}</small>` : ""}
      </div>`
    : "";
  return `<section class="diagnostic-recovery" aria-label="恢复建议">
    <strong>下一步建议</strong>
    ${summary}
    <ul>${steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
    ${recoveryActionsHtml(task)}
  </section>`;
}

function recoveryActionButtonHtml(action, task) {
  const label = escapeHtml(action.label || action.key || "查看诊断");
  const title = action.detail ? ` title="${escapeHtml(action.detail)}"` : "";
  const intent = action.ui_intent || action.key || "";
  if (intent === "local_upload") {
    return `<button type="button" data-recovery-source="local"${title}>${label}</button>`;
  }
  if (intent === "retry_current_page") {
    return `<button type="button" data-recovery-source="browser"${title}>${label}</button>`;
  }
  if (intent === "inspect_diagnostics") {
    return `<button type="button" data-switch-result-tab="diagnostics"${title}>${label}</button>`;
  }
  if (intent === "continue_from_media") {
    return canContinueFromDownloadedMedia(task)
      ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}"${title}>${label}</button>`
      : "";
  }
  if (intent === "export_markdown") {
    return task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}"${title}>${label}</a>` : "";
  }
  if (intent === "export_diagnostics") {
    return hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}"${title}>${label}</a>` : "";
  }
  if (intent === "export_audit" || intent === "inspect_audit") {
    return hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}"${title}>${label}</a>` : "";
  }
  return `<button type="button" data-switch-result-tab="diagnostics"${title}>${label}</button>`;
}

function recoveryActionsHtml(task, skipKeys = new Set()) {
  if (!task) return "";
  const structured = Array.isArray(task.recovery?.actions) ? task.recovery.actions : [];
  if (structured.length) {
    const skipped = skipKeys instanceof Set ? skipKeys : new Set(skipKeys || []);
    const rendered = structured
      .filter(action => !skipped.has(action.key) && !skipped.has(action.ui_intent))
      .map(action => recoveryActionButtonHtml(action, task))
      .filter(Boolean);
    return `<div class="recovery-actions">${rendered.join("")}</div>`;
  }
  const actions = [
    `<button type="button" data-recovery-source="local">上传本地视频</button>`,
    `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
  ];
  if (hasTaskDiagnostics(task)) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>`);
  if (hasTaskAudit(task)) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>`);
  if (canContinueFromDownloadedMedia(task)) actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>`);
  if (task.note_path) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>`);
  return `<div class="recovery-actions">${actions.join("")}</div>`;
}

function taskChaoxingProfile(task) {
  const profile = task?.recovery?.chaoxing_profile || task?.site_profiles?.chaoxing || task?.chaoxing_profile || {};
  return profile && typeof profile === "object" ? profile : {};
}

function profileYesNo(value) {
  return value ? "是" : "否";
}

function profileChip(label, value) {
  return `<span class="${value ? "pass" : "warn"}"><b>${escapeHtml(label)}</b>${escapeHtml(profileYesNo(value))}</span>`;
}

function platformSignalSiteName(task, profile = taskChaoxingProfile(task)) {
  if (profile?.detected) return "学习通/超星";
  const selected = task?.selected_resource || {};
  return hostFromUrl(task?.page_url || selected.page_url || selected.frame_url || selected.url) || "当前网站";
}

function compactEvidenceHaystack(task, profile = {}) {
  const selected = task?.selected_resource || {};
  const direct = task?.direct_extraction || {};
  const candidate = direct.selected_candidate || {};
  return [
    task?.page_url,
    selected.url,
    selected.resolved_url,
    selected.frame_url,
    selected.label,
    candidate.url,
    candidate.resolved_url,
    profile.sample_url,
    requestBodySummary(selected)
  ].filter(Boolean).join(" ");
}

function platformHeaderNames(task, profile = taskChaoxingProfile(task)) {
  const selected = task?.selected_resource || {};
  const safe = Array.isArray(profile.safe_request_header_names) ? profile.safe_request_header_names : [];
  if (safe.length) return safe;
  const headers = selected.request_headers && typeof selected.request_headers === "object"
    ? Object.keys(selected.request_headers)
    : [];
  const explicit = Array.isArray(selected.request_header_names) ? selected.request_header_names : [];
  return [...new Set([...headers, ...explicit].filter(name => !/cookie|authorization/i.test(String(name || ""))))].sort();
}

function looksLikePlayableApi(resource) {
  const text = [
    resource?.url,
    resource?.resolved_url,
    resource?.frame_url,
    resource?.label,
    resource?.request_type,
    requestBodySummary(resource)
  ].filter(Boolean).join(" ");
  return /ananas|play_?url|playURL|objectid|dtoken|httpmd|\/play(?:[/?#]|$)|playback|player|source/i.test(text);
}

function directMediaKind(kind) {
  return ["hls", "dash", "video", "audio"].includes(String(kind || "").toLowerCase());
}

function platformSignalProfile(task) {
  const profile = taskChaoxingProfile(task);
  const direct = task?.direct_extraction || {};
  const selected = task?.selected_resource || {};
  const selectedDirect = direct.selected_candidate || {};
  const browser = direct.browser_context || {};
  const preflight = profile.page_preflight || {};
  const headerNames = platformHeaderNames(task, profile);
  const requestBody = requestBodySummary(selected);
  const profileKinds = Array.isArray(profile.candidate_kinds) ? profile.candidate_kinds : [];
  const hasReplayBody = Boolean(profile.has_replay_body || selectedDirect.has_replay_body || requestBody);
  const hasFrameContext = Boolean(profile.has_iframe_context || selected.frame_url || selected.frame_id !== null && selected.frame_id !== undefined || browser.active_frame_id !== null && browser.active_frame_id !== undefined);
  const cookieCount = Number(profile.cookie_count ?? browser.cookie_count ?? 0);
  const cookieDomainCount = Number(profile.cookie_domain_count ?? browser.cookie_domain_count ?? 0);
  const hasPlayableApi = Boolean(profile.has_ananas_candidate || profile.has_playurl || profile.has_objectid || profile.has_dtoken || profile.has_httpmd || looksLikePlayableApi(selected));
  const hasDirectMedia = Boolean([selected.kind, selectedDirect.kind, ...profileKinds].some(directMediaKind) || selected.resolved_url || direct.media_landed);
  const hasPreflight = Boolean(preflight.present || task?.page_preflight_report_path);
  const downloadable = Number(preflight.downloadable_count || 0);
  const pageScan = Boolean(preflight.page_scan_attempted || preflight.page_scan_discovered_count);
  const issue = profile.likely_issue || direct.boundary || task?.error_code || "evidence_pending";
  return {
    detected: Boolean(profile.detected || task?.source_type === "current_page" || hasPlayableApi || hasDirectMedia || hasFrameContext || cookieCount || hasPreflight),
    site: platformSignalSiteName(task, profile),
    issue,
    headerNames,
    candidateKinds: profileKinds.length ? profileKinds : [selected.kind || selectedDirect.kind].filter(Boolean),
    cookieCount,
    cookieDomainCount,
    partitionedCookieCount: Number(profile.partitioned_cookie_count ?? browser.partitioned_cookie_count ?? 0),
    partitionKeyCount: Number(profile.partition_key_count ?? browser.partition_key_count ?? 0),
    preflight,
    hasPlayableApi,
    hasDirectMedia,
    hasReplayBody,
    hasReferer: Boolean(profile.has_referer || headerNames.some(name => /^referer$/i.test(name))),
    hasOrigin: Boolean(profile.has_origin || headerNames.some(name => /^origin$/i.test(name))),
    hasXRequestedWith: Boolean(profile.has_x_requested_with || headerNames.some(name => /^x-requested-with$/i.test(name))),
    hasFrameContext,
    hasBlobOrMse: Boolean(selected.blob_url || selected.kind === "blob" || mseAppendEvidence(selected) || browser.active_source_type === "blob"),
    hasPreflight,
    preflightReady: Boolean(preflight.ready || downloadable > 0),
    pageScan,
    downloadable,
    requestBody
  };
}

function chaoxingModeChecklist(task, signal, profile = taskChaoxingProfile(task)) {
  if (!profile?.detected) return "";
  const haystack = compactEvidenceHaystack(task, profile);
  const items = [
    ["ananas", Boolean(profile.has_ananas_candidate || /ananas/i.test(haystack))],
    ["playurl", Boolean(profile.has_playurl || /play_?url|playURL/i.test(haystack))],
    ["objectid", Boolean(profile.has_objectid || /objectid/i.test(haystack))],
    ["dtoken", Boolean(profile.has_dtoken || /dtoken/i.test(haystack))],
    ["iframe", Boolean(signal.hasFrameContext)],
    ["cookie", Boolean(signal.cookieCount || signal.cookieDomainCount)]
  ];
  const itemMap = Object.fromEntries(items);
  const steps = [
    {
      label: "播放器入口",
      ok: itemMap.ananas || itemMap.playurl || itemMap.objectid || signal.hasPlayableApi,
      detail: itemMap.ananas || itemMap.playurl ? "已看到 ananas/playurl 播放接口" : "先在原课程页真实播放几秒"
    },
    {
      label: "登录上下文",
      ok: itemMap.cookie && (signal.hasReferer || signal.hasFrameContext),
      detail: itemMap.cookie ? "Cookie 已同步，等待 Referer/iframe 对齐" : "需要当前登录态 Cookie"
    },
    {
      label: "接口回放",
      ok: signal.hasReplayBody || signal.hasDirectMedia,
      detail: signal.hasReplayBody ? "POST/body 可交给后端回放" : "等待 objectid/dtoken/body 或直接媒体 URL"
    },
    {
      label: "媒体落地",
      ok: signal.hasDirectMedia && (signal.preflightReady || !signal.hasPreflight),
      warn: signal.hasDirectMedia && signal.hasPreflight && !signal.preflightReady,
      detail: signal.preflightReady ? "预检已有可下载候选" : signal.hasDirectMedia ? "有媒体候选但预检未通过" : "还没有 mp4/HLS/DASH 可下载资源"
    }
  ];
  const missing = steps
    .filter(step => !step.ok)
    .map(step => step.label)
    .join("、");
  const next = missing
    ? `缺口：${missing}。继续播放几秒后重新检测；若媒体始终是 DRM/不可还原 blob，就走本地视频入口。`
    : "证据链基本完整：可以先预检，预检可下载后再开始总结或只下载到本地。";
  return `<div class="chaoxing-mode-checklist" aria-label="学习通模式证据">
    <strong>学习通模式</strong>
    <span>差哪一步一眼看清：播放接口、参数、frame 和登录态都只做可访问性诊断。</span>
    <p>${items.map(([label, ok]) => `<em class="${ok ? "pass" : "warn"}">${escapeHtml(label)} ${ok ? "已抓到" : "缺失"}</em>`).join("")}</p>
    <ol class="chaoxing-mode-flow">
      ${steps.map(step => `<li class="${step.ok ? "pass" : step.warn ? "warn" : "miss"}">
        <b>${escapeHtml(step.label)}</b>
        <small>${escapeHtml(step.detail)}</small>
      </li>`).join("")}
    </ol>
    <small class="chaoxing-mode-next">${escapeHtml(next)}</small>
  </div>`;
}

function platformSignalHtml(task) {
  const profile = taskChaoxingProfile(task);
  const signal = platformSignalProfile(task);
  if (!signal.detected) return "";
  const safeHeaders = signal.headerNames.join(", ") || "-";
  const candidateKinds = signal.candidateKinds.join(", ") || "-";
  const preflightText = signal.hasPreflight
    ? `${Number(signal.preflight.candidate_count || 0)} 候选 / ${Number(signal.preflight.probed_count || 0)} 探测 / ${Number(signal.preflight.downloadable_count || 0)} 可下载${signal.pageScan ? " / 已扫页面" : ""}`
    : "未随任务落盘";
  return `<section class="chaoxing-profile" data-platform-signal="true" aria-label="平台直取线索">
    <div class="chaoxing-profile-head">
      <span>平台线索 · ${escapeHtml(signal.site)}</span>
      <strong>${escapeHtml(signal.issue)}</strong>
    </div>
    <div class="chaoxing-profile-grid">
      ${profileChip("播放 API", signal.hasPlayableApi)}
      ${profileChip("真实媒体", signal.hasDirectMedia)}
      ${profileChip("POST/body", signal.hasReplayBody)}
      ${profileChip("Referer", signal.hasReferer)}
      ${profileChip("Origin", signal.hasOrigin)}
      ${profileChip("XHR", signal.hasXRequestedWith)}
      ${profileChip("iframe", signal.hasFrameContext)}
      ${profileChip("blob/MSE", signal.hasBlobOrMse)}
    </div>
    ${chaoxingModeChecklist(task, signal, profile)}
    <dl>
      <dt>Cookie</dt><dd>${signal.cookieDomainCount} 域 / ${signal.cookieCount} 条；分区 ${signal.partitionedCookieCount} / ${signal.partitionKeyCount} key</dd>
      <dt>预检</dt><dd>${preflightText}</dd>
      <dt>请求头</dt><dd>${escapeHtml(safeHeaders)}</dd>
      <dt>候选类型</dt><dd>${escapeHtml(candidateKinds)}</dd>
    </dl>
    <p>通用策略：优先复用当前播放暴露的媒体 URL、播放 API、iframe、Referer/Origin、一次性 Cookie 和可回放 POST body；不录制、不刷课、不伪造进度、不自动答题。</p>
  </section>`;
}

function chaoxingProfileHtml(task) {
  return platformSignalHtml(task);
}

function primaryRecoveryAction(task) {
  const primary = task?.recovery?.primary_action || null;
  if (!primary) return null;
  const intent = primary.ui_intent || primary.key || "";
  const actionable = task?.status === "failed"
    || canContinueFromDownloadedMedia(task)
    || ["local_upload", "retry_current_page", "continue_from_media"].includes(intent)
    || ["recoverable", "hard_boundary"].includes(task?.recovery?.severity || "");
  return actionable ? primary : null;
}

function recoveryDecisionTone(task) {
  const severity = task?.recovery?.severity || "";
  if (severity === "hard_boundary" || task?.drm_detected) return "blocked";
  if (task?.status === "failed" || severity === "recoverable") return "warn";
  if (canContinueFromDownloadedMedia(task)) return "ready";
  return "active";
}

function recoveryDecisionMetrics(task) {
  const recovery = task?.recovery || {};
  const direct = task?.direct_extraction || {};
  const reuse = task?.reuse || {};
  return [
    ["诊断码", recovery.code || task?.error_code || "-"],
    ["置信度", recovery.confidence || "-"],
    ["尝试", Number.isFinite(recovery.attempt_count) ? `${recovery.attempt_count} 条路线` : `${task?.download_attempts?.length || 0} 条路线`],
    ["边界", directExtractionBoundaryText(direct.boundary)],
    ["复用", reuse.rerun_from_media_ready || canContinueFromDownloadedMedia(task) ? `${taskMediaDisplayName(task)} 可续跑` : reuse.suggested_next_step || "-"]
  ];
}

function recoveryDecisionHtml(task) {
  if (!task?.id || !task.recovery) return "";
  const primary = primaryRecoveryAction(task);
  const show = Boolean(
    primary
    || task.status === "failed"
    || canContinueFromDownloadedMedia(task)
    || task.mode === "download_only"
    || task.direct_extraction?.boundary && task.direct_extraction.boundary !== "normal_accessible_media_only"
  );
  if (!show) return "";

  const recovery = task.recovery || {};
  const notes = Array.isArray(recovery.boundary_notes)
    ? recovery.boundary_notes.map(value => String(value || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  const steps = Array.isArray(recovery.steps)
    ? recovery.steps.map(value => String(value || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  const primaryHtml = primary ? recoveryActionButtonHtml(primary, task) : "";
  const skipKeys = new Set([primary?.key, primary?.ui_intent].filter(Boolean));
  const secondaryHtml = recoveryActionsHtml(task, skipKeys);
  const detail = recovery.diagnosis || primary?.detail || task.error_detail || "按阶段审计继续处理当前任务。";

  return `<section class="recovery-decision ${escapeHtml(recoveryDecisionTone(task))}" aria-label="推荐行动">
    <div class="recovery-decision-main">
      <span>推荐行动</span>
      <strong>${escapeHtml(primary?.label || (canContinueFromDownloadedMedia(task) ? "继续切片总结" : "查看阶段检查"))}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <div class="recovery-decision-actions">
      ${primaryHtml ? `<div class="recovery-decision-primary">${primaryHtml}</div>` : ""}
      ${secondaryHtml}
    </div>
    <div class="recovery-decision-metrics">
      ${recoveryDecisionMetrics(task).map(([label, value]) => `<span><b>${escapeHtml(label)}</b><strong>${escapeHtml(value || "-")}</strong></span>`).join("")}
    </div>
    ${notes.length || steps.length ? `<ul>
      ${[...notes, ...steps].slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>` : ""}
  </section>`;
}

function failedStepIndex(task) {
  if (DOWNLOAD_ERROR_CODES.has(task.error_code)) return 0;
  if (task.media_path && !task.transcript_path) return 1;
  if (task.transcript_path && !task.frame_grids?.length) return 2;
  return 3;
}

function stepState(task, step) {
  if (task.status === "failed") {
    const failedIndex = failedStepIndex(task);
    const stepIndex = PIPELINE_STEPS.findIndex(item => item.key === step.key);
    if (stepIndex < failedIndex) return "done";
    if (stepIndex === failedIndex) return "failed";
    return "pending";
  }
  if (task.status === "success" || task.phase === "completed") return "done";
  const currentIndex = PIPELINE_STEPS.findIndex(item => item.key === task.phase);
  const stepIndex = PIPELINE_STEPS.findIndex(item => item.key === step.key);
  if (currentIndex < 0) return stepIndex === 0 && task.status === "running" ? "active" : "pending";
  if (stepIndex < currentIndex) return "done";
  if (stepIndex === currentIndex) return "active";
  return "pending";
}

function stageRail(task) {
  if (task.source_type === "page_text") {
    const done = task.status === "success";
    const failed = task.status === "failed";
    return `<div class="stage-rail compact">
      <span class="${done ? "done" : failed ? "failed" : "active"}">解析</span>
      <span class="${done ? "done" : failed ? "failed" : task.phase === "summarizing" ? "active" : "pending"}">总结</span>
      <span class="${done ? "done" : failed ? "failed" : "pending"}">完成</span>
    </div>`;
  }
  return `<div class="stage-rail">${PIPELINE_STEPS.map(step => `<span class="${stepState(task, step)}">${step.label}</span>`).join("")}</div>`;
}

function transcriberLabel(value) {
  return ({
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible": "OpenAI-compatible ASR",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    openai: "OpenAI ASR",
    groq: "Groq ASR",
    "groq-asr": "Groq ASR"
  })[String(value || "faster-whisper").toLowerCase()] || String(value || "ASR");
}

function asrOptionText(options = {}) {
  return `${transcriberLabel(options.transcriber)} · ${options.whisper_model || "small"}`;
}

function transcriptSourceText(source) {
  return ({
    "browser-subtitle": "浏览器字幕",
    "page-subtitle": "页面字幕",
    "embedded-subtitle": "视频内嵌字幕",
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    "groq-asr": "Groq ASR"
  })[String(source || "").toLowerCase()] || source || "转写";
}

function optionText(task) {
  const options = task.options || {};
  return [
    options.frame_interval ? `${options.frame_interval} 秒切片` : "",
    options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 画面网格` : "",
    asrOptionText(options),
    options.note_style ? `风格 ${options.note_style}` : "",
    options.note_template ? `格式 ${options.note_template}` : "",
    options.visual_understanding === false ? "未开启视觉理解" : "视觉理解"
  ].filter(Boolean).join(" · ");
}

function mediaKind(url) {
  if (HLS_RE.test(url)) return url.toLowerCase().includes(".mpd") ? "dash" : "hls";
  if (MEDIA_RE.test(url)) return "video";
  return "unknown";
}

function normalizeSourceInput(value) {
  const raw = String(value || "").trim().replace(/^["']|["']$/g, "");
  if (!raw) return { valid: false, raw, url: "", platform: "", sourceId: "", label: "" };
  const urlMatch = raw.match(/https?:\/\/[^\s<>"']+/i);
  if (urlMatch) {
    const url = urlMatch[0].replace(/[.,;:!?，。；：！？)\]}）】》]+$/g, "");
    const parsedUrl = url.match(/^https?:\/\/([^/?#]+)([^?#]*)/i);
    if (!parsedUrl) {
      return { valid: false, raw, url: "", platform: "", sourceId: "", label: "链接格式无效" };
    }
    const host = parsedUrl[1].split("@").at(-1).split(":")[0].toLowerCase();
    const bilibili = host === "b23.tv" || host.endsWith(".bilibili.com");
    const youtube = host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com");
    const idMatch = bilibili ? decodeURIComponent(parsedUrl[2] || "").match(/(?:BV([A-Za-z0-9]{10})|av(\d{1,20}))/i) : null;
    const sourceId = idMatch ? (idMatch[1] ? `BV${idMatch[1]}` : `av${idMatch[2]}`) : "";
    const platform = bilibili ? "bilibili" : youtube ? "youtube" : "web";
    const platformLabel = bilibili ? "B站视频" : youtube ? "YouTube 视频" : mediaKind(url) === "unknown" ? "网页链接" : "媒体直链";
    return { valid: true, raw, url, platform, sourceId, label: sourceId ? `${platformLabel} · ${sourceId}` : platformLabel };
  }
  const bv = raw.match(/(?:^|[^A-Za-z0-9])BV([A-Za-z0-9]{10})(?![A-Za-z0-9])/i);
  if (bv) {
    const sourceId = `BV${bv[1]}`;
    return { valid: true, raw, url: `https://www.bilibili.com/video/${sourceId}`, platform: "bilibili", sourceId, label: `B站视频 · ${sourceId}` };
  }
  const av = raw.match(/(?:^|[^A-Za-z0-9])av(\d{1,20})(?![A-Za-z0-9])/i);
  if (av) {
    const sourceId = `av${av[1]}`;
    return { valid: true, raw, url: `https://www.bilibili.com/video/${sourceId}`, platform: "bilibili", sourceId, label: `B站视频 · ${sourceId}` };
  }
  return { valid: false, raw, url: "", platform: "", sourceId: "", label: "请输入 BV/AV 号或完整链接" };
}

function renderUrlSourceIdentity(source = normalizeSourceInput(els.urlInput?.value)) {
  if (!els.urlSourceIdentity) return source;
  els.urlSourceIdentity.hidden = !source.raw;
  els.urlSourceIdentity.className = `url-source-identity ${source.valid ? "valid" : "invalid"}`;
  els.urlSourceIdentity.textContent = source.valid
    ? `${source.label}${source.url !== source.raw ? `  →  ${source.url}` : ""}`
    : source.label;
  return source;
}

function selectedUrlMode() {
  return els.urlMode?.value || "auto";
}

function urlModeDescription(mode = selectedUrlMode()) {
  return ({
    auto: "B站 BV/AV 号会自动转换为视频页；页面链接交给 yt-dlp 和页面扫描，mp4/FLV/AVI/m3u8/mpd 会按媒体直链处理。",
    page: "按课程网页处理：后端先扫描页面里的媒体地址，再用 yt-dlp 解析，不把这个 URL 当直连文件。",
    video: "按视频文件直连处理：适合没有后缀但实际返回 video/* 的签名接口或播放接口。",
    hls: "按 HLS 播放列表处理：后端会用 ffmpeg 合并 m3u8 可访问的分片。",
    dash: "按 DASH manifest 处理：后端会用 ffmpeg 合并 mpd 可访问的分片。"
  })[mode] || "";
}

function resourceKindForUrl(url, mode = selectedUrlMode()) {
  if (mode === "video" || mode === "hls" || mode === "dash") return mode;
  if (mode === "page") return "unknown";
  return mediaKind(url);
}

function mimeForKind(kind) {
  if (kind === "video") return "video/mp4";
  if (kind === "hls") return "application/vnd.apple.mpegurl";
  if (kind === "dash") return "application/dash+xml";
  return "";
}

function isTextResponseMime(value = "") {
  return /(?:^|;|\s)(text\/|application\/json|application\/xml|application\/javascript)/i.test(String(value || ""));
}

function labelForUrlResource(kind, mode = selectedUrlMode()) {
  if (mode === "video") return "手动视频直连";
  if (mode === "hls") return "手动 HLS";
  if (mode === "dash") return "手动 DASH";
  if (kind === "video") return "手动媒体链接";
  if (kind === "hls") return "手动 HLS";
  if (kind === "dash") return "手动 DASH";
  return "手动链接";
}

function manualUrlResource(url) {
  const kind = resourceKindForUrl(url);
  if (kind === "unknown") return null;
  const resource = {
    url,
    source: "manual",
    kind,
    mime: mimeForKind(kind),
    score: selectedUrlMode() === "auto" ? 96 : 98,
    label: labelForUrlResource(kind),
    request_type: selectedUrlMode() === "auto" ? "manual-auto" : "manual-forced"
  };
  applyUrlPreflightToResource(resource);
  return resource;
}

function selectedPagePreflightResource(url) {
  if (!url || url !== urlPagePreflightUrl || !urlPagePreflightResource?.url) return null;
  return { ...urlPagePreflightResource };
}

function selectedPagePreflightReport(url) {
  if (!url || url !== urlPagePreflightUrl || !urlPagePreflightReport) return null;
  return urlPagePreflightReport;
}

function clearUrlPreflight() {
  urlPreflightResourceUrl = "";
  urlPreflightResult = null;
  urlPagePreflightUrl = "";
  urlPagePreflightResource = null;
  urlPagePreflightReport = null;
  renderUrlPreflightReport(null, null);
}

function rememberUrlPreflight(resource, result) {
  if (!resource?.url || !result) return result;
  urlPreflightResourceUrl = resource.url;
  urlPreflightResult = result;
  applyPreflightResultToResource(resource, result);
  return result;
}

function applyPreflightResultToResource(resource, result) {
  if (!resource?.url || !result?.downloadable) return;
  const kind = String(result.kind || "").toLowerCase();
  if (["video", "hls", "dash"].includes(kind)) {
    resource.kind = kind;
    resource.mime = mimeForKind(kind) || resource.mime;
  }
  if (result.resolved_url && result.resolved_url !== resource.url) {
    resource.resolved_url = result.resolved_url;
  }
  if (result.content_type) {
    const resolvedMime = result.strategy === "direct-response-probe" && isTextResponseMime(result.content_type)
      ? mimeForKind(resource.kind || kind)
      : result.content_type;
    if (resolvedMime) resource.mime = resolvedMime;
    resource.headers = { ...(resource.headers || {}), "content-type": result.content_type };
  }
  if (result.content_disposition) {
    resource.headers = { ...(resource.headers || {}), "content-disposition": result.content_disposition };
  }
  const statusCode = Number(result.status_code);
  if (Number.isFinite(statusCode) && statusCode > 0) resource.status_code = statusCode;
  const contentLength = Number(result.content_length);
  if (Number.isFinite(contentLength) && contentLength > 0) resource.content_length = contentLength;
}

function applyUrlPreflightToResource(resource) {
  if (!resource?.url || resource.url !== urlPreflightResourceUrl || !urlPreflightResult?.downloadable) return;
  applyPreflightResultToResource(resource, urlPreflightResult);
}

function rememberUrlPagePreflight(pageUrl, report) {
  urlPagePreflightUrl = pageUrl || "";
  urlPagePreflightResource = null;
  urlPagePreflightReport = report && typeof report === "object" ? report : null;
  const selectedUrl = report?.selected_url || "";
  const candidates = Array.isArray(report?.candidates) ? report.candidates : [];
  const selectedItem = candidates.find(item => {
    const resource = item?.resource || {};
    const result = item?.preflight || {};
    return resource.url === selectedUrl
      || resource.resolved_url === selectedUrl
      || result.resolved_url === selectedUrl;
  });
  const selected = selectedItem?.resource || {};
  if (selected?.url) {
    urlPagePreflightResource = {
      ...selected,
      source: selected.source || "page-preflight",
      request_type: selected.request_type || "manual-page-preflight",
      page_url: pageUrl
    };
    applyPreflightResultToResource(urlPagePreflightResource, selectedItem?.preflight || {});
  }
  return report;
}

function preflightKindLabel(kind) {
  const key = String(kind || "").toLowerCase();
  if (key === "hls") return "HLS";
  if (key === "dash") return "DASH";
  if (key === "video") return "视频直连";
  if (key === "page") return "页面扫描";
  return key || "未知";
}

function preflightStrategyLabel(strategy) {
  const key = String(strategy || "").trim();
  const labels = {
    "direct-response-probe": "直连响应探测",
    "manifest-probe": "清单探测",
    "range-probe": "分段探测",
    "page-scan": "页面扫描",
    "yt-dlp": "yt-dlp 页面解析"
  };
  return labels[key] || key || "后端预检";
}

function renderUrlPreflightReport(resource, result, state = "") {
  if (!els.urlPreflightReport) return;
  if (!resource && !result) {
    els.urlPreflightReport.hidden = true;
    els.urlPreflightReport.className = "url-preflight-report";
    els.urlPreflightReport.innerHTML = "";
    return;
  }

  const downloadable = Boolean(result?.downloadable);
  const status = state || (downloadable ? "pass" : "fail");
  const statusText = status === "checking" ? "预检中" : downloadable ? "可直取" : "未通过";
  const target = result?.resolved_url || (downloadable ? resource?.resolved_url : "") || resource?.url || "";
  const original = resource?.url || "";
  const sizeText = fmtBytes(result?.content_length) || (result?.bytes_checked ? `${result.bytes_checked} B checked` : "未知");
  const httpText = result?.status_code ? `HTTP ${result.status_code}` : "未返回";
  const kindText = preflightKindLabel(result?.kind || resource?.kind);
  const strategyText = preflightStrategyLabel(result?.strategy);
  const message = state === "checking"
    ? "正在确认后端是否能直接访问这个媒体资源。"
    : downloadable
      ? "可以直接生成笔记或只下载到本地；后续会复用这个解析目标。"
      : (result?.message || result?.code || "这个链接暂时不能直接下载，可切换链接类型、创建页面扫描任务，或改用本地视频。");
  const requestHeaders = Array.isArray(result?.request_header_names) && result.request_header_names.length
    ? result.request_header_names.slice(0, 5).join(" / ")
    : "";

  const rows = [
    ["类型", kindText],
    ["探测", strategyText],
    ["HTTP", httpText],
    ["大小", sizeText]
  ];
  if (target && target !== original) rows.push(["目标", compactUrl(target, 96)]);
  if (requestHeaders) rows.push(["请求头", requestHeaders]);

  els.urlPreflightReport.hidden = false;
  els.urlPreflightReport.className = `url-preflight-report ${status}`;
  els.urlPreflightReport.innerHTML = `
    <div class="url-preflight-report-head">
      <span>${escapeHtml(statusText)}</span>
      <strong>${escapeHtml(kindText)}</strong>
    </div>
    <div class="url-preflight-report-grid">
      ${rows.map(([label, value]) => `
        <span>${escapeHtml(label)}</span>
        <b>${escapeHtml(value)}</b>
      `).join("")}
    </div>
    <p>${escapeHtml(message)}</p>
  `;
}

function renderUrlPagePreflightReport(url, report = {}, state = "") {
  if (!els.urlPreflightReport) return;
  if (!url && !report) {
    renderUrlPreflightReport(null, null);
    return;
  }
  const ready = Boolean(report?.ready || report?.selected_url);
  const status = state || (ready ? "pass" : "fail");
  const statusText = status === "checking" ? "页面预检中" : ready ? "发现可直取资源" : "未发现可直取资源";
  const candidates = Array.isArray(report?.candidates) ? report.candidates : [];
  const selectedUrl = report?.selected_url || "";
  const selectedItem = candidates.find(item => {
    const resource = item?.resource || {};
    return resource.url === selectedUrl || resource.resolved_url === selectedUrl;
  }) || candidates[0] || {};
  const selectedResource = selectedItem.resource || {};
  const selectedResult = selectedItem.preflight || {};
  const kindText = preflightKindLabel(selectedResult.kind || selectedResource.kind || "page");
  const strategyText = preflightStrategyLabel(selectedResult.strategy || "page-scan");
  const target = selectedResult.resolved_url || selectedResource.resolved_url || selectedResource.url || selectedUrl || url || "";
  const scan = report?.page_scan || {};
  const rows = [
    ["候选", `${report?.downloadable_count || 0}/${report?.candidate_count || candidates.length || 0}`],
    ["探测", `${report?.probed_count || 0}`],
    ["页面发现", `${scan.discovered_count || 0}`],
    ["类型", kindText],
    ["策略", strategyText]
  ];
  if (target) rows.push(["目标", compactUrl(target, 96)]);

  els.urlPreflightReport.hidden = false;
  els.urlPreflightReport.className = `url-preflight-report ${status}`;
  els.urlPreflightReport.innerHTML = `
    <div class="url-preflight-report-head">
      <span>${escapeHtml(statusText)}</span>
      <strong>${escapeHtml(kindText)}</strong>
    </div>
    <div class="url-preflight-report-grid">
      ${rows.map(([label, value]) => `
        <span>${escapeHtml(label)}</span>
        <b>${escapeHtml(value)}</b>
      `).join("")}
    </div>
    <p>${escapeHtml(state === "checking" ? "正在扫描页面和候选媒体地址；不会录制标签页。" : (report?.message || report?.code || "页面预检完成。"))}</p>
  `;
}

function renderUrlModeHint() {
  if (!els.urlModeHint) return;
  els.urlModeHint.textContent = urlModeDescription();
  renderUrlPreflightReport(null, null);
}

function visualUnderstandingEnabled() {
  return els.visualUnderstanding?.checked !== false;
}

function boundedNumber(value, fallback, min, max) {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  const number = Number(text);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

function readVisualSliceOptions() {
  const [rawCols, rawRows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  return {
    frame_interval: boundedNumber(els.frameInterval?.value, 20, 1, 600),
    grid_columns: boundedNumber(rawCols, 3, 1, 6),
    grid_rows: boundedNumber(rawRows, 3, 1, 6)
  };
}

function visualPlanText() {
  if (!visualUnderstandingEnabled()) return "无视觉 · 仅转写";
  const visual = readVisualSliceOptions();
  return `${visual.frame_interval}秒 · ${visual.grid_columns}x${visual.grid_rows}`;
}

function currentOptionSummaryItems() {
  return [
    visualPlanText(),
    asrOptionText({
      transcriber: els.transcriber?.value || "faster-whisper",
      whisper_model: els.whisperModel?.value || "small"
    }),
    `${els.noteStyle?.value || "study"} · ${els.noteTemplate?.value || "standard"} · ${els.summaryDepth?.value || "standard"}`
  ];
}

function refreshOptionDependentUi() {
  syncTranscriberModelDefault();
  renderSourceWorkflow();
}

function applyModelProviderPreset(force = false) {
  const preset = modelProviderPresets[els.llmProvider?.value || ""];
  if (!preset) return;
  if (els.llmBaseUrl && (force || !els.llmBaseUrl.value.trim())) {
    els.llmBaseUrl.value = preset.baseUrl;
  }
  if (els.llmModel && (force || !els.llmModel.value.trim())) {
    els.llmModel.value = preset.model;
  }
  if (els.transcriber && preset.transcriber && (force || els.transcriber.value === "faster-whisper")) {
    els.transcriber.value = preset.transcriber;
  }
  if (els.whisperModel && preset.whisperModel && (force || !els.whisperModel.value.trim() || LOCAL_ASR_MODELS.has(els.whisperModel.value))) {
    els.whisperModel.value = preset.whisperModel;
  }
  syncTranscriberModelDefault(false);
  renderSourceWorkflow();
  updateModelProviderHint();
  updateHealthVisionStatus();
}

function currentModelSettings() {
  return {
    llm_provider: els.llmProvider?.value || "",
    llm_model: els.llmModel?.value?.trim() || "",
    llm_base_url: els.llmBaseUrl?.value?.trim() || "",
    transcriber: els.transcriber?.value || "faster-whisper",
    whisper_model: els.whisperModel?.value || "small"
  };
}

function applyModelSettings(settings = {}) {
  if (!settings || typeof settings !== "object") return;
  if (els.llmProvider && typeof settings.llm_provider === "string") {
    els.llmProvider.value = modelProviderPresets[settings.llm_provider] ? settings.llm_provider : "custom";
  }
  if (els.llmModel && typeof settings.llm_model === "string") {
    els.llmModel.value = settings.llm_model;
  }
  if (els.llmBaseUrl && typeof settings.llm_base_url === "string") {
    els.llmBaseUrl.value = settings.llm_base_url;
  }
  if (els.transcriber && typeof settings.transcriber === "string") {
    els.transcriber.value = settings.transcriber;
  }
  if (els.whisperModel && typeof settings.whisper_model === "string") {
    els.whisperModel.value = settings.whisper_model;
  }
  syncTranscriberModelDefault(false);
  updateModelProviderHint();
}

function loadModelSettings() {
  try {
    const raw = window.localStorage?.getItem(MODEL_SETTINGS_STORAGE_KEY);
    if (!raw) return;
    applyModelSettings(JSON.parse(raw));
  } catch {
    return;
  }
}

function saveModelSettings() {
  try {
    window.localStorage?.setItem(MODEL_SETTINGS_STORAGE_KEY, JSON.stringify(currentModelSettings()));
  } catch {
    return;
  }
}

function readOptions() {
  syncTranscriberModelDefault();
  const visual = readVisualSliceOptions();
  const options = {
    visual_understanding: visualUnderstandingEnabled(),
    frame_interval: visual.frame_interval,
    grid_columns: visual.grid_columns,
    grid_rows: visual.grid_rows,
    transcriber: els.transcriber?.value || "faster-whisper",
    whisper_model: els.whisperModel.value || "small",
    note_style: els.noteStyle.value || "study",
    note_template: els.noteTemplate?.value || "standard",
    summary_depth: els.summaryDepth.value || "standard"
  };
  const llmModel = els.llmModel.value.trim();
  const llmBaseUrl = els.llmBaseUrl.value.trim();
  const llmApiKey = els.llmApiKey.value.trim();
  if (llmModel) options.llm_model = llmModel;
  if (llmBaseUrl) options.llm_base_url = llmBaseUrl;
  if (llmApiKey) options.llm_api_key = llmApiKey;
  return options;
}

function syncTranscriberModelDefault(force = false) {
  if (!els.transcriber || !els.whisperModel) return;
  const transcriber = els.transcriber.value || "faster-whisper";
  const model = els.whisperModel.value || "small";
  if (transcriber === "faster-whisper" && !LOCAL_ASR_MODELS.has(model)) {
    els.whisperModel.value = "small";
  } else if (transcriber === "openai-compatible" && (force || LOCAL_ASR_MODELS.has(model))) {
    els.whisperModel.value = "whisper-1";
  } else if (transcriber === "groq" && (force || LOCAL_ASR_MODELS.has(model))) {
    els.whisperModel.value = "whisper-large-v3";
  }
}

function healthVisionReady(data) {
  const taskKeyConfigured = Boolean(els.llmApiKey?.value?.trim());
  if (!taskKeyConfigured) return Boolean(data?.vision_model_configured);
  const preset = modelProviderPresets[els.llmProvider?.value || ""];
  return !preset || preset.capabilities.includes("vision");
}

function healthTextModelReady(data) {
  return Boolean(data?.llm_model_configured || els.llmApiKey?.value?.trim());
}

function healthVisionModel(data) {
  if (!els.llmApiKey?.value?.trim() && data?.llm_model_configured) {
    return data.default_llm_model || "gpt-4.1-mini";
  }
  return els.llmModel?.value?.trim() || data?.default_llm_model || "gpt-4.1-mini";
}

function healthVisionProvider(data) {
  if (!els.llmApiKey?.value?.trim() && data?.llm_model_configured) {
    const configuredProvider = String(data?.default_llm_provider || "").trim();
    return modelProviderLabel(configuredProvider) || "Compatible";
  }
  const selected = (els.llmProvider?.value || "").trim();
  if (selected) {
    return modelProviderLabel(selected);
  }
  const provider = String(data?.default_llm_provider || "").trim();
  return modelProviderLabel(provider) || "Compatible";
}

function healthVisionText(data) {
  const model = healthVisionModel(data);
  const provider = healthVisionProvider(data);
  const asr = healthAsrChipText(data);
  if (healthVisionReady(data)) {
    return `视觉模型已配置（${provider} · ${model}），切片网格会随字幕进入图文总结；转写：${asr}。`;
  }
  if (healthTextModelReady(data)) {
    return `文本总结模型已配置（${provider} · ${model}）；画面切片仍会生成，但不会发送给该文本模型；转写：${asr}。`;
  }
  return `未配置视觉模型 API Key：当前默认 ${provider} · ${model} 仅作待用配置；转写：${asr}；仍会生成字幕、切片网格和本地图文索引。`;
}

function healthVisionChipText(data) {
  const model = healthVisionModel(data);
  const provider = healthVisionProvider(data);
  if (healthVisionReady(data)) return `${provider} · ${model}`;
  if (healthTextModelReady(data)) return `仅文本 · ${provider}`;
  return `待填 · ${provider}`;
}

function healthAsrChipText(data = lastHealthData) {
  const transcriber = els.transcriber?.value || "faster-whisper";
  const base = `${transcriberLabel(transcriber)} · ${els.whisperModel?.value || "small"}`;
  if (transcriber !== "faster-whisper") return `${base} · 远程`;
  if (!data) return `${base} · 待检测`;
  return `${base} · ${data.local_asr_available ? "可用" : "未安装"}`;
  return `${transcriberLabel(els.transcriber?.value || "faster-whisper")} · ${els.whisperModel?.value || "small"}`;
}

function healthMediaChipText(data) {
  if (!data?.ffmpeg) return "ffmpeg 缺失";
  if (data.ffprobe_optional) return "后端 · ffmpeg 时长回退";
  return "后端 · 直取/切片就绪";
}

function assistantCapabilities(data = lastHealthData) {
  return data?.assistant_capabilities || {};
}

function capabilityList(items, fallback, limit = 5) {
  const values = Array.isArray(items) ? items.map(item => String(item || "").trim()).filter(Boolean) : [];
  const chosen = values.length ? values : fallback;
  return chosen.slice(0, limit);
}

function healthDirectMediaFormats(data = lastHealthData) {
  const direct = assistantCapabilities(data).direct_media || {};
  const files = capabilityList(direct.file_extensions, ["mp4", "mkv", "webm", "flv", "avi"], 4);
  const manifests = capabilityList(direct.manifests, ["m3u8", "mpd"], 2);
  return [...files, ...manifests].join("/");
}

function healthDirectDetectorText(data = lastHealthData) {
  const direct = assistantCapabilities(data).direct_media || {};
  const labels = {
    dom_video: "DOM",
    performance_resource: "Performance",
    web_request: "webRequest",
    player_runtime: "播放器",
    yt_dlp: "yt-dlp"
  };
  return capabilityList(direct.detectors, ["dom_video", "performance_resource", "web_request", "yt_dlp"], 4)
    .map(item => labels[item] || item)
    .join(" + ");
}

function healthDirectBoundaryText(data = lastHealthData) {
  const labels = {
    tab_recording: "不录制",
    drm_bypass: "不绕过 DRM",
    progress_spoofing: "不刷课",
    auto_answering: "不自动答题"
  };
  return capabilityList(assistantCapabilities(data).non_goals, ["tab_recording", "drm_bypass", "progress_spoofing"], 3)
    .map(item => labels[item] || item)
    .join(" · ");
}

function healthDirectChipText(data = lastHealthData) {
  return `${healthDirectMediaFormats(data)} · ${healthDirectBoundaryText(data)}`;
}

function hasHealthDataPaths(data) {
  const paths = data?.data_paths;
  return Boolean(paths && typeof paths === "object" && Object.keys(paths).length);
}

function healthDataPathsReady(data) {
  const paths = data?.data_paths || {};
  const serverMode = ["server", "public", "cloud"].includes(String(data?.deployment_mode || "").toLowerCase());
  return Boolean(hasHealthDataPaths(data) && paths.all_under_data_dir && (serverMode || paths.all_on_data_drive));
}

function healthDataChipText(data) {
  const paths = data?.data_paths || {};
  const drive = paths.data_drive || "";
  const state = !hasHealthDataPaths(data)
    ? "待检测"
    : healthDataPathsReady(data) ? "data内" : "路径异常";
  const serverMode = ["server", "public", "cloud"].includes(String(data?.deployment_mode || "").toLowerCase());
  return `${serverMode ? "持久卷" : drive || "data"} · ${state}`;
}

function ytdlpChipText(data) {
  if (!data) return "待连接";
  if (data.yt_dlp_package_available) return "Python 包可用";
  if (data.yt_dlp_available) return "CLI 可用";
  return "未安装";
}

function projectPathFromHealth(data) {
  const root = String(data?.data_paths?.root || "");
  if (!root) return "D:\\Projects\\learnnote-assistant";
  return root.replace(/[\\/]+data[\\/]?$/i, "") || root;
}

function startupReadinessItems(data = lastHealthData) {
  const connected = Boolean(data);
  const serverMode = ["server", "public", "cloud"].includes(String(data?.deployment_mode || "").toLowerCase());
  const projectPath = projectPathFromHealth(data);
  return [
    {
      state: connected ? "pass" : "block",
      label: serverMode ? "部署服务" : "本地后端",
      value: connected ? "已连接" : "未连接",
      detail: connected ? `API ${API || window.location.origin}` : "先运行 start-learnnote.ps1，后端监听 127.0.0.1。"
    },
    {
      state: data?.ffmpeg ? "pass" : "block",
      label: "ffmpeg",
      value: data ? healthMediaChipText(data) : "待检测",
      detail: data?.ffmpeg ? "可下载合并、转音频和抽帧。" : "缺少 ffmpeg 时无法完成 HLS/DASH 合并和切片。"
    },
    {
      state: data?.yt_dlp_available ? "pass" : connected ? "warn" : "wait",
      label: "yt-dlp",
      value: ytdlpChipText(data),
      detail: data?.yt_dlp_available ? "页面解析和平台字幕兜底可用。" : "YouTube/B站等页面兜底需要安装 yt-dlp。"
    },
    {
      state: data?.local_asr_available ? "pass" : connected ? "warn" : "wait",
      label: "转写",
      value: healthAsrChipText(data),
      detail: data?.local_asr_available ? "本地 faster-whisper 可用。" : "未安装时仍可用平台字幕、远程 ASR 或本地索引兜底。"
    },
    {
      state: healthVisionReady(data) ? "pass" : connected ? "warn" : "wait",
      label: "视觉总结",
      value: data ? healthVisionChipText(data) : "待检测",
      detail: healthVisionReady(data) ? "切片网格可进入多模态总结。" : "未填 Key 时仍生成截图网格和本地索引。"
    },
    {
      state: healthDataPathsReady(data) ? "pass" : connected ? "warn" : "wait",
      label: serverMode ? "持久化数据" : "D盘数据",
      value: healthDataChipText(data),
      detail: hasHealthDataPaths(data) ? data.data_paths.root : "任务、上传和缓存应落在项目 data 目录。"
    },
    {
      state: "active",
      label: "浏览器扩展",
      value: "手动加载",
      detail: `${projectPath}\\extension`
    },
    {
      state: "ready",
      label: "样例回归",
      value: "可选",
      detail: "start-learnnote.ps1 -WithSamples 后打开本地 MP4/HLS/API mock。"
    }
  ];
}

function startupReadinessSummary(data = lastHealthData) {
  const items = startupReadinessItems(data);
  const blocks = items.filter(item => item.state === "block").length;
  const warns = items.filter(item => item.state === "warn").length;
  if (blocks) return `${blocks} 个必需项未就绪`;
  if (warns) return `${warns} 个增强项待配置，基础流程可用`;
  return "本机学习助手已就绪";
}

function startupReadinessHtml(data = lastHealthData) {
  const items = startupReadinessItems(data);
  return `
    <div class="startup-readiness-head">
      <div>
        <span>启动就绪</span>
        <strong>${escapeHtml(startupReadinessSummary(data))}</strong>
      </div>
      <em>${escapeHtml(API || window.location.origin || "127.0.0.1")}</em>
    </div>
    <div class="startup-readiness-grid">
      ${items.map(item => `<section class="${escapeHtml(item.state)}">
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </section>`).join("")}
    </div>
    <div class="startup-readiness-actions">
      <button type="button" data-startup-action="copy-backend">复制后端地址</button>
      <button type="button" data-startup-action="open-options">模型参数</button>
      <button type="button" data-startup-action="browser">当前页入口</button>
      <button type="button" data-startup-action="local">本地视频</button>
    </div>
  `;
}

function updateStartupReadiness(data = lastHealthData) {
  if (!els.startupReadiness) return;
  els.startupReadiness.innerHTML = startupReadinessHtml(data);
}

function emptyReadinessItems(data = lastHealthData) {
  const backendReady = Boolean(data?.ffmpeg);
  return [
    {
      state: backendReady ? "pass" : "block",
      label: "后端媒体检查",
      value: backendReady ? healthMediaChipText(data) : "后端未就绪",
      detail: backendReady
        ? "可以下载、合并、转音频、抽帧和生成本地 media.mp4。"
        : "先启动 127.0.0.1 后端并确认 ffmpeg 可用。"
    },
    {
      state: healthVisionReady(data) ? "pass" : "warn",
      label: "视觉总结检查",
      value: healthVisionChipText(data),
      detail: healthVisionReady(data)
        ? "切片网格会和转写片段一起进入多模态总结。"
        : `${healthVisionProvider(data)} 默认模型待用；仍会生成转写、截图网格和本地索引，配置 Key 后再启用图文总结。`
    },
    {
      state: "pass",
      label: "本地视频检查",
      value: `${healthDirectMediaFormats(data)} 可上传`,
      detail: "平台直取失败时，本地视频会走同一套转写、抽帧、视觉窗口和图文总结管线。"
    },
    {
      state: !hasHealthDataPaths(data) ? "warn" : healthDataPathsReady(data) ? "pass" : "warn",
      label: "本地数据目录",
      value: healthDataChipText(data),
      detail: hasHealthDataPaths(data) ? data?.data_paths?.root || "等待后端返回 data 目录。" : "当前后端未上报 data 目录；刷新或重启后端后会重新检测。"
    },
    {
      state: "warn",
      label: "当前页直取检查",
      value: healthDirectMediaFormats(data),
      detail: `${healthDirectDetectorText(data)} 捕获可访问媒体；${healthDirectBoundaryText(data)}。`
    }
  ];
}

function emptyReadinessGatesHtml(data = lastHealthData) {
  return `<div class="empty-readiness-gates" data-empty-readiness aria-label="准备度检查">
    ${emptyReadinessItems(data).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function refreshEmptyWorkbenchReadiness() {
  const node = document.querySelector("[data-empty-readiness]");
  if (node) node.innerHTML = emptyReadinessItems().map(item => `<section class="${escapeHtml(item.state)}">
    <span>${escapeHtml(item.label)}</span>
    <strong>${escapeHtml(item.value)}</strong>
    <small>${escapeHtml(item.detail)}</small>
  </section>`).join("");
}

function updateHealthVisionStatus(data = lastHealthData) {
  if (!data || !els.browserBridgeStatus) return;
  const mediaText = String(els.browserBridgeStatus.dataset.mediaText || els.browserBridgeStatus.textContent || "").trim();
  const visionText = healthVisionText(data);
  els.browserBridgeStatus.dataset.mediaText = mediaText;
  els.browserBridgeStatus.title = `${mediaText} ${visionText}`.trim();
  els.browserBridgeStatus.classList.add("capture-status-grid");
  els.browserBridgeStatus.innerHTML = `
    <span class="capture-status-chip bridge"><b>桥接</b>需 Chrome/Edge 扩展侧栏</span>
    <span class="capture-status-chip media"><b>媒体</b>${escapeHtml(healthMediaChipText(data))}</span>
    <span class="capture-status-chip direct"><b>直取</b>${escapeHtml(healthDirectChipText(data))}</span>
    <span class="capture-status-chip vision ${healthVisionReady(data) ? "ready" : "pending"}"><b>视觉</b>${escapeHtml(healthVisionChipText(data))}</span>
    <span class="capture-status-chip asr"><b>转写</b>${escapeHtml(healthAsrChipText(data))}</span>
    <span class="capture-status-chip data ${healthDataPathsReady(data) ? "ready" : "pending"}"><b>数据</b>${escapeHtml(healthDataChipText(data))}</span>
  `;
}

async function checkHealth() {
  try {
    const data = await fetchJson(apiUrl("/health"));
    syncModelProviderPresets(data);
    els.health.className = data.ffmpeg ? "health ok" : "health bad";
    els.health.textContent = data.ffmpeg
      ? data.ffprobe_optional ? "后端可用 · ffprobe 可选" : "本地后端可用"
      : "ffmpeg 缺失";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = data.ffmpeg
        ? data.ffprobe_optional
          ? "ffmpeg 可用，缺少 ffprobe 时会用 ffmpeg 输出解析时长；仍可下载、转写、切片和图文总结。"
          : "扩展读取播放器、媒体请求和一次性 cookie，后端只下载可访问的视频地址。"
        : "后端已连接，但 ffmpeg 缺失；当前页直取后无法完成合并/切片。";
      updateHealthVisionStatus(data);
      updateStartupReadiness(data);
      refreshEmptyWorkbenchReadiness();
    }
  } catch {
    els.health.className = "health bad";
    els.health.textContent = "后端未连接";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = "先启动本地后端，再从扩展 Side Panel 创建当前页任务。";
    }
    updateStartupReadiness(null);
    refreshEmptyWorkbenchReadiness();
  }
}

function setSource(source) {
  selectedSource = source;
  els.sourceTabs.forEach(tab => tab.classList.toggle("active", tab.dataset.source === source));
  els.panes.forEach(pane => pane.classList.toggle("active", pane.id === `${source}Source`));
  renderSourceWorkflow();
}

function shouldFocusResultPanel() {
  if (window.matchMedia) return window.matchMedia("(max-width: 760px)").matches;
  return Number(window.innerWidth || 0) <= 760;
}

function focusResultPanelOnMobile() {
  if (!shouldFocusResultPanel()) return;
  document.querySelector(".result-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initializeResponsiveChrome() {
  if (shouldFocusResultPanel() && els.optionsDisclosure) {
    els.optionsDisclosure.open = false;
  }
}

function storedUiFlag(key) {
  try {
    return window.localStorage?.getItem(key) === "1";
  } catch {
    return false;
  }
}

function storeUiFlag(key, value) {
  try {
    window.localStorage?.setItem(key, value ? "1" : "0");
  } catch {
    // Storage can be unavailable in private contexts or tests.
  }
}

function setPressed(button, pressed) {
  if (!button) return;
  button.setAttribute?.("aria-pressed", pressed ? "true" : "false");
  button.classList?.toggle("active", Boolean(pressed));
}

function setHistoryCollapsed(collapsed, persist = true) {
  document.body?.classList?.toggle("queue-collapsed", Boolean(collapsed));
  setPressed(els.toggleHistoryButton, collapsed);
  if (persist) storeUiFlag("learnnote.historyCollapsed", collapsed);
}

function setWorkspaceCollapsed(collapsed, persist = true) {
  document.body?.classList?.toggle("workspace-collapsed", Boolean(collapsed));
  setPressed(els.toggleWorkspaceButton, collapsed);
  if (persist) storeUiFlag("learnnote.workspaceCollapsed", collapsed);
}

function setReadingMode(enabled, persist = true) {
  document.body?.classList?.toggle("reading-mode", Boolean(enabled));
  setPressed(els.readingModeButton, enabled);
  if (persist) storeUiFlag("learnnote.readingMode", enabled);
}

function renderResultTabState() {
  els.resultTabs.forEach(item => {
    const active = normalizeResultTabName(item.dataset.tab) === selectedTab;
    item.classList.toggle("active", active);
    item.setAttribute?.("aria-selected", active ? "true" : "false");
  });
}

function hasExplicitTaskRoute() {
  return Boolean(taskIdFromCurrentUrl());
}

function initializeWorkspaceView() {
  const taskRoute = hasExplicitTaskRoute();
  setWorkspaceCollapsed(taskRoute && storedUiFlag("learnnote.workspaceCollapsed"), false);
  setHistoryCollapsed(taskRoute && storedUiFlag("learnnote.historyCollapsed"), false);
  setReadingMode(taskRoute && storedUiFlag("learnnote.readingMode"), false);
  renderResultTabState();
}

async function loadTasks() {
  let data = { tasks: [] };
  try {
    data = await fetchJson(apiUrl("/api/tasks"));
  } catch {
    tasks = [];
    selectedTaskId = null;
    renderTasks();
    renderBrowserRouteSummary();
    renderSourceWorkflow();
    await renderDetail();
    return;
  }
  tasks = data.tasks || [];
  if (selectedTaskId && !tasks.some(task => task.id === selectedTaskId)) selectedTaskId = null;
  if (!selectedTaskId) {
    const initialTask = preferredInitialTask(tasks);
    if (initialTask) selectTask(initialTask.id, { clearCaches: false });
  }
  else if (selectedTaskId) syncSelectedTaskUrl(selectedTaskId);
  renderTasks();
  renderBrowserRouteSummary();
  renderSourceWorkflow();
  await renderDetail();
}

function taskMatchesFilters(task) {
  if (taskStatusFilter !== "all") {
    const running = task.status === "running" || task.status === "queued";
    if (taskStatusFilter === "running" && !running) return false;
    if (taskStatusFilter !== "running" && task.status !== taskStatusFilter) return false;
  }
  const query = taskQuery.trim().toLowerCase();
  if (!query) return true;
  return [
    task.title,
    displayTaskTitle(task),
    task.page_url,
    task.source_type,
    task.error_code,
    task.error_detail,
    task.drm_detected ? "drm eme encrypted" : "",
    ...(task.drm_signals || []).map(signal => `${signal.key_system || ""} ${signal.init_data_type || ""}`),
    task.selected_resource?.url,
    task.selected_resource?.source,
    task.selected_resource?.kind
  ].filter(Boolean).join(" ").toLowerCase().includes(query);
}

function renderTasks() {
  els.taskCount.textContent = String(tasks.length);
  els.successCount.textContent = String(tasks.filter(task => task.status === "success").length);
  els.runningCount.textContent = String(tasks.filter(task => task.status === "running" || task.status === "queued").length);
  els.failedCount.textContent = String(tasks.filter(task => task.status === "failed").length);

  const visibleTasks = sortedVisibleTasks(tasks.filter(taskMatchesFilters), selectedTaskId);

  if (!tasks.length) {
    els.tasks.innerHTML = emptyTaskQueueHtml();
    return;
  }
  if (!visibleTasks.length) {
    els.tasks.innerHTML = `<div class="detail empty">没有匹配的任务。</div>`;
    return;
  }

  els.tasks.innerHTML = visibleTasks.map(task => `
    <button class="task status-${escapeHtml(task.status)} ${task.id === selectedTaskId ? "selected" : ""}" data-id="${escapeHtml(task.id)}">
      ${taskPreviewHtml(task)}
      <div class="task-body">
        <div class="task-headline">
          <strong>${escapeHtml(displayTaskTitle(task))}</strong>
          <span class="task-status-pill ${escapeHtml(taskStatusClass(task))}">${escapeHtml(statusText(task))} · ${task.progress || 0}%</span>
        </div>
        <small class="task-meta-line">${escapeHtml(taskMetaLine(task))}</small>
        ${taskChipsHtml(task)}
        ${taskHandoffHtml(task)}
        ${taskAuditMiniHtml(task)}
        ${stageRail(task)}
        <div class="progress"><span style="width:${task.progress || 0}%"></span></div>
      </div>
    </button>
  `).join("");

  document.querySelectorAll(".task").forEach(button => {
    button.onclick = async () => {
      selectTask(button.dataset.id);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
    };
  });
}

function emptyTaskQueueHtml() {
  const steps = [
    ["1", "直取/上传", "当前页候选、链接或本地视频"],
    ["2", "下载与转写", "ffmpeg / yt-dlp / Whisper"],
    ["3", "画面切片", "按时间窗生成网格截图"],
    ["4", "整理笔记", "时间轴、概念、复习题"]
  ];
  return `<section class="queue-empty-workflow" aria-label="任务队列空状态">
    <span>暂无任务</span>
    <strong>选择左侧入口开始生成学习笔记</strong>
    <p>任务会在这里形成队列；成功后右侧直接进入笔记、字幕、画面切片和下载诊断。</p>
    <ol>
      ${steps.map(([index, title, detail]) => `<li>
        <b>${escapeHtml(index)}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(detail)}</small>
      </li>`).join("")}
    </ol>
  </section>`;
}

function taskPreviewHtml(task) {
  const windows = visualWindows(task);
  const firstWindow = windows[0];
  const selected = task.selected_resource || {};
  const status = taskStatusClass(task);
  const mediaName = taskMediaDisplayName(task);
  const label = firstWindow
    ? firstWindow.id || "切片"
    : selected.kind || (task.media_path ? "视频" : task.error_code ? "诊断" : "任务");
  const detail = firstWindow
    ? `${fmt(firstWindow.start)} - ${fmt(firstWindow.end)}`
    : task.media_path
      ? mediaName
      : task.error_code || statusText(task);
  if (firstWindow?.grid_url) {
    return `<figure class="task-preview status-${escapeHtml(status)}">
      <img src="${escapeHtml(firstWindow.grid_url)}" alt="${escapeHtml(firstWindow.id || "frame grid")}">
      <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
    </figure>`;
  }
  return `<figure class="task-preview status-${escapeHtml(status)} empty">
    <div>${taskPreviewIcon(status)}</div>
    <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
  </figure>`;
}

function taskPreviewIcon(status) {
  if (status === "success") return "✓";
  if (status === "failed") return "!";
  if (status === "running") return "…";
  return "LN";
}

function taskChipItems(task) {
  const selected = task.selected_resource || {};
  const windows = visualWindows(task);
  const attempts = task.download_attempts || [];
  const mediaName = taskMediaDisplayName(task);
  const route = selected.playback_match
    ? playbackText(selected.playback_match)
    : resourceSourceText(selected) || (task.source_type === "current_page" ? "页面解析" : sourceText(task));
  const chips = task.status === "failed" ? [
    route,
    mediaKindText(selected.kind),
    task.error_code || "",
    attempts.length ? `${attempts.length} 次尝试` : "",
    task.note_path ? "兜底笔记" : task.media_path ? mediaName : "",
    windows.length ? `${windows.length} 窗口` : ""
  ] : [
    route,
    mediaKindText(selected.kind),
    task.media_path ? mediaName : "",
    task.note_path ? "笔记" : "",
    windows.length ? `${windows.length} 窗口` : "",
    attempts.length > 1 ? `${attempts.length} 次尝试` : ""
  ];
  const seen = new Set();
  return chips.filter(value => {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  }).slice(0, 5);
}

function taskChipsHtml(task) {
  const metaParts = new Set(taskMetaLine(task).split(" · ").map(item => item.trim()).filter(Boolean));
  const chips = taskChipItems(task).filter(chip => {
    const text = String(chip || "").trim();
    return !(metaParts.has(text) && ["本地视频", "视频"].includes(text));
  });
  if (!chips.length) return "";
  return `<div class="task-chips">${chips.map(chip => `<span>${escapeHtml(chip)}</span>`).join("")}</div>`;
}

function taskHandoffItems(task) {
  const selected = task?.selected_resource || {};
  const windows = visualWindows(task || {});
  const attempts = task?.download_attempts || [];
  const sourceLabel = sourceText(task);
  const mediaName = taskMediaDisplayName(task);
  const mediaLabel = task?.media_path
    ? `${mediaName} 已保存`
    : attempts.length
      ? `${attempts.length} 次下载尝试`
      : task?.source_type === "local"
        ? "等待上传"
        : "等待直取";
  const sliceLabel = task?.options?.visual_understanding === false || task?.source_type === "page_text"
    ? "文本路线"
    : windows.length
      ? `${windows.length} 个切片窗口`
      : "等待切片";
  const nextLabel = (() => {
    if (canContinueFromDownloadedMedia(task)) return "下一步：继续切片总结";
    if (task?.status === "failed") return task?.recovery?.primary_action?.label ? `下一步：${task.recovery.primary_action.label}` : "下一步：查看诊断";
    if (task?.note_path) return windows.length ? "下一步：核对画面笔记" : "下一步：阅读笔记";
    if (task?.status === "running" || task?.status === "queued") return `下一步：${statusText(task)}`;
    return "下一步：打开任务";
  })();
  return [
    ["来源", [sourceLabel, selected.kind ? mediaKindText(selected.kind) : ""].filter(Boolean).join(" · ") || "-"],
    ["媒体", mediaLabel],
    ["切片", sliceLabel],
    ["动作", nextLabel]
  ];
}

function taskHandoffHtml(task) {
  const tone = task?.status === "failed"
    ? "blocked"
    : canContinueFromDownloadedMedia(task)
      ? "ready"
      : task?.note_path
        ? "done"
        : task?.status === "running" || task?.status === "queued"
          ? "active"
          : "idle";
  return `<div class="task-handoff ${escapeHtml(tone)}" aria-label="学习接力">
    ${taskHandoffItems(task).map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join("")}
  </div>`;
}

function resultMetaChipsHtml(task) {
  if (!task) return "";
  const gates = pipelineAuditItems(task);
  const blocked = gates.find(item => item.state === "fail" || item.state === "warn" || item.state === "wait");
  const windows = visualWindows(task);
  const selected = task.selected_resource || {};
  const reuseEvidence = taskReuseEvidenceItem(task);
  const hasMedia = hasExportableMedia(task);
  const hasTranscript = hasReadableTranscript(task);
  const transcriptSource = reusableTranscriptSourceText(task);
  const chips = [
    { state: taskStatusClass(task), label: statusText(task), value: `${task.progress || 0}%` },
    { state: "source", label: sourceText(task), value: selected.kind ? mediaKindText(selected.kind) : task.source_type || "-" },
    reuseEvidence ? { state: "source", label: "复用", value: "已下载媒体" } : null,
    { state: hasMedia ? "pass" : "wait", label: "媒体", value: hasMedia ? "已保存" : "待下载" },
    { state: hasTranscript ? "pass" : "wait", label: "字幕", value: hasTranscript ? (transcriptSource || "已生成") : "待转写" },
    {
      state: task.options?.visual_understanding === false ? "skip" : windows.length ? "pass" : "wait",
      label: "切片",
      value: task.options?.visual_understanding === false ? "关闭" : windows.length ? `${windows.length} 窗口` : "待生成"
    },
    { state: task.note_path ? "pass" : "wait", label: "笔记", value: task.summary_source || (task.note_path ? "完成" : "待总结") },
    { state: hasTaskBundle(task) ? "pass" : "wait", label: "导出", value: hasTaskBundle(task) ? "可导出" : "等待" },
    blocked ? { state: blocked.state, label: "当前门", value: `${blocked.label} · ${blocked.value || blocked.state}` } : null
  ].filter(Boolean);
  const optionLine = optionText(task);
  const notice = pendingRerunNotice?.taskId === task.id ? pendingRerunNotice.message : "";
  return `<div class="result-meta-chips" aria-label="任务阶段摘要">
    ${chips.map(chip => `<span class="${escapeHtml(chip.state)}"><b>${escapeHtml(chip.label)}</b>${escapeHtml(chip.value || "-")}</span>`).join("")}
    ${notice ? `<small class="rerun-notice">${escapeHtml(notice)}</small>` : ""}
    ${optionLine ? `<small>${escapeHtml(optionLine)}</small>` : ""}
  </div>`;
}

function taskAuditMiniHtml(task) {
  const items = pipelineAuditItems(task);
  if (!items.length) return "";
  const blocked = items.find(item => item.state === "fail" || item.state === "warn" || item.state === "wait");
  const passedCount = items.filter(item => item.state === "pass" || item.state === "skip").length;
  return `<div class="task-audit-mini" aria-label="任务检查">
    <div class="task-audit-dots">
      ${items.map(item => `<span class="${escapeHtml(item.state)}" title="${escapeHtml(`${item.label}：${item.value || "-"}；${item.detail || "-"}`)}">
        <b>${escapeHtml(item.label.slice(0, 2))}</b>
      </span>`).join("")}
    </div>
    <small>${escapeHtml(blocked ? `${blocked.label} · ${blocked.value || blocked.state}` : `${passedCount}/${items.length} 已放行`)}</small>
  </div>`;
}

function taskMetaLine(task) {
  return [
    sourceText(task),
    task.phase && task.phase !== "completed" ? task.phase : "",
  ].filter(Boolean).join(" · ");
}

async function taskRecord() {
  if (!selectedTaskId) return null;
  return fetch(apiUrl(`/api/tasks/${selectedTaskId}`)).then(r => r.json()).then(taskFromPayload);
}

function taskFromPayload(payload) {
  const task = payload?.task || null;
  if (task && (payload?.audit || task.audit)) task.audit = payload.audit || task.audit;
  return task;
}

async function noteForTask(taskId) {
  if (!taskId) return "";
  if (lastNoteTaskId === taskId && lastNote) return lastNote;
  const response = await fetch(apiUrl(`/api/tasks/${taskId}/note`));
  if (!response.ok) return "";
  lastNote = await response.text();
  lastNoteTaskId = taskId;
  return lastNote;
}

function clearTaskCaches() {
  lastNote = "";
  lastNoteTaskId = "";
  lastTranscript = null;
  lastTranscriptTaskId = "";
}

async function transcriptForTask(task) {
  if (!task?.id || !hasReadableTranscript(task)) return null;
  if (lastTranscriptTaskId === task.id && lastTranscript) return lastTranscript;
  const response = await fetch(apiUrl(`/api/tasks/${task.id}/transcript`));
  if (!response.ok) return null;
  lastTranscript = await response.json();
  lastTranscriptTaskId = task.id;
  return lastTranscript;
}

function taskBrief(task) {
  const selected = task.selected_resource || {};
  const options = task.options || {};
  return `<div class="task-brief">
    <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
    <span><b>${escapeHtml(sourceText(task))}</b>${escapeHtml(selected.kind || task.source_type || "-")}</span>
    <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
    <span><b>${escapeHtml(task.summary_source || asrOptionText(options))}</b>${escapeHtml(task.summary_warning ? "已降级，详见诊断" : `${options.note_style || "study"} · ${options.note_template || "standard"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
  </div>`;
}

function taskStatusClass(task) {
  if (task.status === "success") return "success";
  if (task.status === "failed") return "failed";
  if (task.status === "running" || task.status === "queued") return "running";
  return "idle";
}

function taskExportUrl(task, type) {
  return apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/exports/${type}`);
}

function taskClipExportUrl(task, windowId) {
  return taskExportUrl(task, `clips/${encodeURIComponent(windowId || "window")}`);
}

function taskMediaPreviewUrl(task) {
  if (!task?.id || !hasExportableMedia(task)) return "";
  return apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/media`);
}

function taskRerunUrl(taskId) {
  return apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/rerun-from-media`);
}

function taskQaUrl(taskId) {
  return apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/qa`);
}

function hasTaskBundle(task) {
  if (!task) return false;
  const reuse = task.reuse || {};
  return Boolean(
    task.note_path ||
    task.subtitle_path ||
    task.media_path ||
    reuse.subtitle_available ||
    reuse.transcript_ready ||
    reuse.media_available ||
    task.status === "failed" ||
    task.download_attempts?.length ||
    task.resource_inventory_path ||
    task.page_preflight_report_path ||
    visualWindows(task).length
  );
}

function hasVisualWindowExport(task) {
  return Boolean(task?.visual_windows?.length || task?.frame_grids?.length);
}

function hasTaskDiagnostics(task) {
  if (!task) return false;
  return Boolean(
    task.status === "failed" ||
    task.download_attempts?.length ||
    task.selected_resource ||
    task.media_path ||
    task.summary_diagnostics_path ||
    task.resource_inventory_path ||
    task.page_preflight_report_path ||
    Object.keys(task.summary_diagnostics || {}).length
  );
}

function hasTaskAudit(task) {
  return Boolean(task?.id && (hasTaskBundle(task) || hasTaskDiagnostics(task) || task.source_type || task.status));
}

function hasReusableSubtitle(task) {
  const reuse = task?.reuse || {};
  return Boolean(task?.subtitle_path || task?.transcript_path || reuse.subtitle_available || reuse.transcript_ready);
}

function hasExportableSubtitle(task) {
  const reuse = task?.reuse || {};
  return Boolean(task?.subtitle_path || reuse.subtitle_available);
}

function hasExportableMedia(task) {
  const reuse = task?.reuse || {};
  return Boolean(task?.media_path || reuse.media_available);
}

function taskMediaDisplayName(task) {
  const reuse = task?.reuse || {};
  const raw = String(
    task?.media_path ||
    reuse.media_path_recorded ||
    task?.source_media_path ||
    reuse.source_media_path ||
    ""
  ).trim();
  if (!raw) return "media.mp4";
  const withoutQuery = raw.replace(/[?#].*$/, "").replace(/\\/g, "/");
  const parts = withoutQuery.split("/").filter(Boolean);
  return parts[parts.length - 1] || "media.mp4";
}

function hasReadableTranscript(task) {
  const reuse = task?.reuse || {};
  return Boolean(task?.transcript_path || reuse.transcript_ready);
}

function reusableTranscriptSourceText(task) {
  const source = task?.reuse?.transcript_source || "";
  return source ? transcriptSourceText(source) : "";
}

function canContinueFromDownloadedMedia(task) {
  const finished = task?.status === "success" || task?.status === "failed";
  const reuse = task?.reuse || {};
  return Boolean(task?.id && finished && !task.note_path && reuse.rerun_from_media_ready);
}

function downloadOnlyEmptyNoteHtml(task) {
  const hasSubtitle = hasReusableSubtitle(task);
  const transcriptSource = reusableTranscriptSourceText(task);
  const mediaName = taskMediaDisplayName(task);
  const title = hasSubtitle ? "视频和字幕已直取到本地" : "视频已直取到本地";
  const detail = hasSubtitle
    ? `已保存${transcriptSource ? ` ${transcriptSource}` : "字幕/转写"}，可先导出字幕核对，也可以继续进入抽帧、视觉窗口和图文笔记流程；不会录制页面。`
    : `可以先导出 ${mediaName} 核对，也可以继续进入转写、抽帧、视觉窗口和图文笔记流程；不会录制页面。`;
  const actions = [
    hasExportableSubtitle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">导出字幕</a>` : "",
    hasExportableMedia(task) ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 ${escapeHtml(mediaName)}</a>` : "",
    canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""
  ].filter(Boolean).join("");
  return `<section class="download-only-callout note-empty-continue ${hasSubtitle ? "subtitle-ready" : ""}">
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(detail)}</span>
    ${actions ? `<div class="download-only-actions">${actions}</div>` : ""}
  </section>`;
}

function updateContinueFromMediaAction(task) {
  if (!els.continueFromMediaButton) return;
  const canContinue = canContinueFromDownloadedMedia(task);
  els.continueFromMediaButton.hidden = !canContinue;
  els.continueFromMediaButton.disabled = !canContinue;
}

function visualCoverageHtml(task) {
  const windows = visualWindows(task || {});
  const diag = task?.summary_diagnostics || {};
  const hasDiagnostics = Object.keys(diag).length > 0;
  const gridCount = Number(diag.frame_grid_count ?? task?.frame_grids?.length ?? windows.length ?? 0);
  const visionGridCount = Number(diag.vision_grid_count ?? gridCount ?? 0);
  const sentImages = Number(diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length ?? 0);
  const missingIds = (diag.missing_vision_image_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const omittedIds = (diag.omitted_vision_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const windowCount = Number(diag.visual_window_count ?? windows.length ?? 0);
  if (!windows.length && !hasDiagnostics && !gridCount) return "";

  const validWindows = windows
    .map((window, index) => ({
      ...window,
      id: String(window.id || `W${String(index + 1).padStart(3, "0")}`),
      start: Number(window.start || 0),
      end: Number(window.end ?? window.start ?? 0),
      frame_count: Number(window.frame_count || 0)
    }))
    .filter(window => Number.isFinite(window.start) && Number.isFinite(window.end));
  const minStart = validWindows.length ? Math.min(...validWindows.map(window => window.start)) : 0;
  const maxEnd = validWindows.length ? Math.max(...validWindows.map(window => window.end)) : 0;
  const totalDuration = Math.max(1, maxEnd - minStart);
  const shownWindows = validWindows.slice(0, 8);
  const missingSet = new Set(missingIds);
  const omittedSet = new Set(omittedIds);
  const lane = shownWindows.length
    ? `<div class="visual-coverage-lane" aria-label="视觉窗口覆盖">
      ${shownWindows.map(window => {
        const width = Math.max(8, Math.min(100, ((Math.max(1, window.end - window.start) / totalDuration) * 100)));
        const state = omittedSet.has(window.id) ? "omitted" : missingSet.has(window.id) ? "missing" : safeNoteMediaUrl(window.grid_url) ? "ready" : "pending";
        return `<span class="${escapeHtml(state)}" style="--w:${width.toFixed(2)}%" title="${escapeHtml(`${window.id} ${fmt(window.start)} - ${fmt(window.end)}`)}">
          <b>${escapeHtml(window.id)}</b><small>${escapeHtml(fmt(window.start))}</small>
        </span>`;
      }).join("")}
      ${validWindows.length > shownWindows.length ? `<em>+${validWindows.length - shownWindows.length}</em>` : ""}
    </div>`
    : `<div class="visual-coverage-empty">等待抽帧生成视觉窗口</div>`;
  const flags = [
    missingIds.length ? `缺图 ${compactIdList(missingIds)}` : "",
    omittedIds.length ? `超限省略 ${compactIdList(omittedIds)}` : "",
    ...llmAuditFlags(diag),
    diag.summary_warning || "",
    diag.used_page_text_fallback ? "已使用页面文本/浏览器字幕兜底" : ""
  ].filter(Boolean);

  return `<section class="visual-coverage" aria-label="视觉切片覆盖">
    <header>
      <span>视觉切片覆盖</span>
      <strong>${windowCount || windows.length || "-"} 个窗口</strong>
      <small>${validWindows.length ? `${fmt(minStart)} - ${fmt(maxEnd)}` : "尚无时间覆盖"}</small>
    </header>
    <div class="visual-coverage-metrics">
      <span><b>${gridCount || "-"}</b>画面网格</span>
      <span><b>${sentImages}/${visionGridCount || gridCount || 0}</b>送入视觉</span>
      <span><b>${missingIds.length || "-"}</b>缺图窗口</span>
      <span><b>${omittedIds.length || "-"}</b>超限省略</span>
    </div>
    ${lane}
    ${flags.length ? `<p>${flags.map(escapeHtml).join(" · ")}</p>` : ""}
  </section>`;
}

function visionEvidenceBar(task) {
  if (!task) return "";
  const windows = visualWindows(task || {});
  const diag = task.summary_diagnostics || {};
  const hasDiagnostics = Object.keys(diag).length > 0;
  const gridCount = Number(diag.frame_grid_count ?? task.frame_grids?.length ?? windows.length ?? 0);
  const visionGridCount = Number(diag.vision_grid_count ?? gridCount ?? 0);
  const sentImages = Number(diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length ?? 0);
  const missingIds = (diag.missing_vision_image_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const omittedIds = (diag.omitted_vision_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const source = task.summary_source || diag.summary_source || (diag.used_vision_llm ? "vision-llm" : diag.used_text_llm ? "text-llm" : diag.used_local_template ? "local-template" : "");
  const visualDisabled = task.options?.visual_understanding === false || task.source_type === "page_text";
  const shouldShow = visualDisabled || hasDiagnostics || gridCount || windows.length || task.note_path || task.media_path;
  if (!shouldShow) return "";

  let state = "empty";
  if (visualDisabled) state = "skip";
  else if (source === "vision-llm" || diag.used_vision_llm) state = "strong";
  else if (sentImages > 0 || missingIds.length || omittedIds.length) state = "partial";
  else if (gridCount || windows.length) state = "index";

  const title = {
    strong: "画面已参与图文总结",
    partial: "已生成画面证据，模型链路存在降级",
    index: "已有画面切片，当前笔记未确认使用视觉模型",
    skip: "本任务走文本路线",
    empty: "还没有视觉切片证据"
  }[state];
  const badge = {
    strong: "已接入视觉模型",
    partial: "视觉索引",
    index: "本地切片",
    skip: "文本总结",
    empty: "等待切片"
  }[state];
  const detail = {
    strong: `已把 ${sentImages}/${visionGridCount || gridCount || 0} 张网格图送入视觉模型，并和对应转写窗口合并成笔记。`,
    partial: `检测到 ${windows.length || gridCount || 0} 个视觉窗口；当前结果可能使用了文本模型、模板或存在缺图窗口。`,
    index: `已生成 ${windows.length || gridCount || 0} 个视觉窗口，可在“画面”页复核；总结来源为 ${source || "本地索引"}。`,
    skip: "页面文本或用户选项关闭了视觉理解，因此不会调用画面切片总结。",
    empty: "尚未看到抽帧、网格或视觉模型诊断；任务完成后这里会显示画面证据。"
  }[state];
  const flags = [
    missingIds.length ? `缺图 ${compactIdList(missingIds, 4)}` : "",
    omittedIds.length ? `超限省略 ${compactIdList(omittedIds, 4)}` : "",
    diag.summary_warning || "",
    diag.used_page_text_fallback ? "已使用页面文本/浏览器字幕兜底" : "",
    diag.used_local_template ? "本地模板兜底" : ""
  ].filter(Boolean);

  return `<section class="vision-evidence ${escapeHtml(state)}" aria-label="图文总结证据">
    <div class="vision-evidence-main">
      <span>${escapeHtml(badge)}</span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>
    <div class="vision-evidence-metrics">
      <span><b>${windows.length || gridCount || "-"}</b>视觉窗口</span>
      <span><b>${sentImages}/${visionGridCount || gridCount || 0}</b>送入视觉</span>
      <span><b>${escapeHtml(source || "-")}</b>总结来源</span>
      <span><b>${missingIds.length + omittedIds.length || "-"}</b>异常窗口</span>
    </div>
    ${flags.length ? `<p class="vision-evidence-flags">${flags.map(escapeHtml).join(" · ")}</p>` : ""}
    <div class="vision-evidence-actions">
      ${windows.length ? `<button type="button" data-switch-result-tab="frames">查看切片</button>` : ""}
      ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>` : ""}
      ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a>` : ""}
      ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""}
    </div>
  </section>`;
}

function auditGateState(task, passed) {
  if (passed) return "pass";
  if (task?.status === "failed") return "fail";
  if (task?.status === "success") return "warn";
  return "wait";
}

function mergeBackendAuditItems(task, items) {
  const gates = Array.isArray(task?.audit?.gates) ? task.audit.gates : [];
  if (!gates.length) return items;
  const byKey = new Map(gates.map(gate => [gate.key, gate]));
  return items.map(item => {
    const gate = byKey.get(item.key);
    if (!gate) return item;
    return {
      ...item,
      state: gate.state || item.state,
      value: gate.value || item.value,
      detail: gate.detail || item.detail
    };
  });
}

function pipelineAuditItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = visualWindows(task || {});
  const diag = task?.summary_diagnostics || {};
  const isLocal = task?.source_type === "local";
  const isPageText = task?.source_type === "page_text" || Boolean(diag.used_page_text_fallback);
  const hasSelectedRoute = Boolean(selected.url || selected.kind || isLocal || isPageText);
  const hasMedia = hasExportableMedia(task);
  const mediaName = taskMediaDisplayName(task);
  const hasTranscript = hasReadableTranscript(task);
  const transcriptSource = reusableTranscriptSourceText(task);
  const hasVisuals = Boolean(windows.length || task?.frame_grids?.length || Number(diag.frame_grid_count || 0));
  const hasNote = Boolean(task?.note_path);
  const visualDisabled = task?.options?.visual_understanding === false || isPageText;

  const sourceState = auditGateState(task, hasSelectedRoute || attempts.length || hasMedia || hasNote);
  const mediaState = isPageText ? "skip" : auditGateState(task, hasMedia);
  const transcriptState = isPageText && hasNote ? "pass" : auditGateState(task, hasTranscript);
  const visualState = visualDisabled ? "skip" : auditGateState(task, hasVisuals);
  const summaryState = auditGateState(task, hasNote);

  const items = [
    {
      key: "source",
      label: "来源检查",
      state: sourceState,
      value: sourceState === "pass" ? (resourceSourceText(selected) || sourceText(task)) : task?.error_code || "待捕获",
      detail: hasSelectedRoute
        ? [selected.kind || task?.source_type, selected.playback_match ? playbackText(selected.playback_match) : "", selected.resolved_url ? "最终 URL 已记录" : ""].filter(Boolean).join(" · ")
        : (attempts.length ? `${attempts.length} 次候选尝试` : "等待扩展/链接/本地入口提供来源")
    },
    {
      key: "media",
      label: "媒体检查",
      state: mediaState,
      value: mediaState === "skip" ? "文本路线" : hasMedia ? mediaName : task?.error_code || "待下载",
      detail: hasMedia
        ? "已保存到本地，可导出或复用继续总结"
        : (attempts.length ? `${attempts.length} 次下载尝试` : "等待 yt-dlp、直连或 ffmpeg 合并")
    },
    {
      key: "transcript",
      label: "字幕检查",
      state: transcriptState,
      value: hasTranscript ? (transcriptSource || "字幕已生成") : isPageText && hasNote ? "页面文本/浏览器字幕" : task?.phase === "transcribing" ? "转写中" : "待转写",
      detail: hasTranscript
        ? "时间轴可在字幕页查看或导出核对"
        : (isPageText ? `${diag.browser_subtitle_count ?? 0} 条浏览器字幕 · ${diag.combined_text_char_count ?? 0} 字` : task?.summary_warning || `字幕优先，${asrOptionText(task?.options || {})} 兜底`)
    },
    {
      key: "visual",
      label: "切片检查",
      state: visualState,
      value: visualDisabled ? "未启用" : hasVisuals ? `${windows.length || diag.frame_grid_count || task?.frame_grids?.length} 个窗口` : task?.phase === "extracting_frames" ? "抽帧中" : "待切片",
      detail: visualDisabled
        ? "当前任务不走视觉窗口"
        : hasVisuals
          ? `${diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length}/${diag.vision_grid_count ?? (windows.length || 0)} 送入视觉`
          : "等待 ffmpeg 抽帧生成网格"
    },
    {
      key: "summary",
      label: "总结检查",
      state: summaryState,
      value: hasNote ? (task?.summary_source || "笔记完成") : task?.phase === "summarizing" ? "总结中" : task?.error_code || "待总结",
      detail: hasNote
        ? (task?.summary_warning || `${task?.options?.note_style || "study"} · ${task?.options?.note_template || "standard"} · ${task?.options?.summary_depth || "standard"}`)
        : "等待字幕与视觉窗口汇总"
    }
  ];
  return mergeBackendAuditItems(task, items);
}

function pipelineAuditActionHtml(task, item) {
  if (!task || !item) return "";
  const actions = [];
  const state = String(item.state || "");
  const blocked = state === "fail" || state === "warn";

  if (item.key === "media") {
    if (canContinueFromDownloadedMedia(task)) {
      actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>`);
    } else if (hasExportableMedia(task)) {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看证据</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看失败原因</button>`);
      actions.push(`<button type="button" data-recovery-source="local">本地兜底</button>`);
    }
  } else if (item.key === "transcript") {
    if (hasReadableTranscript(task)) {
      actions.push(`<button type="button" data-switch-result-tab="transcript">核对转写</button>`);
    } else if (canContinueFromDownloadedMedia(task)) {
      actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">开始转写</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "visual") {
    if (visualWindows(task).length || task.frame_grids?.length) {
      actions.push(`<button type="button" data-switch-result-tab="frames">看切片</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "summary") {
    if (task.note_path) {
      actions.push(`<button type="button" data-switch-result-tab="note">读笔记</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "source" && (blocked || task.status === "failed")) {
    actions.push(`<button type="button" data-switch-result-tab="diagnostics">看来源证据</button>`);
    actions.push(`<button type="button" data-recovery-source="local">本地兜底</button>`);
  }

  if (!actions.length) return "";
  return `<div class="pipeline-audit-actions">${actions.join("")}</div>`;
}

function pipelineAuditHtml(task) {
  const items = pipelineAuditItems(task);
  return `<section class="pipeline-audit" aria-label="阶段检查">
    <header>
      <span>阶段检查</span>
      <strong>${items.filter(item => item.state === "pass" || item.state === "skip").length}/${items.length} 已放行</strong>
    </header>
    <div class="pipeline-audit-grid">
      ${items.map(item => `<article class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value || "-")}</strong>
        <small>${escapeHtml(item.detail || "-")}</small>
        ${pipelineAuditActionHtml(task, item)}
      </article>`).join("")}
    </div>
  </section>`;
}

function nextStepHtml(task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasMedia = hasExportableMedia(task);
  const mediaName = taskMediaDisplayName(task);
  const hasTranscript = hasReadableTranscript(task);
  const hasVisuals = Boolean(windows.length || task.frame_grids?.length || Number(task.summary_diagnostics?.frame_grid_count || 0));
  const failed = task.status === "failed";
  let tone = "active";
  let title = "继续处理";
  let detail = "等待任务进入下一阶段。";
  let actions = [];
  const recoveryPrimary = primaryRecoveryAction(task);

  if (recoveryPrimary) {
    tone = recoveryDecisionTone(task);
    title = recoveryPrimary.label || "按推荐动作继续";
    detail = task.recovery?.diagnosis || recoveryPrimary.detail || detail;
    actions = [
      recoveryActionButtonHtml(recoveryPrimary, task),
      hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>` : ""
    ];
  } else if (canContinueFromDownloadedMedia(task)) {
    tone = "ready";
    title = "继续生成完整笔记";
    detail = `视频已经下载到本地，可以复用 ${mediaName} 继续转写、切片和图文总结。`;
    actions = [
      `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>`,
      `<button type="button" data-switch-result-tab="diagnostics">看下载证据</button>`
    ];
  } else if (failed && !hasNote) {
    tone = "blocked";
    title = "直取链路需要处理";
    detail = task.error_detail || task.error_code || "当前任务失败；先看诊断确认是登录、DRM、签名过期还是资源不完整。";
    actions = [
      `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`,
      `<button type="button" data-recovery-source="local">改用本地视频</button>`
    ];
  } else if (hasNote) {
    tone = "ready";
    title = "阅读并核对笔记";
    detail = hasVisuals
      ? "笔记、字幕和画面切片已经形成，可以按时间轴回看关键画面。"
      : "笔记已生成；如果缺少画面证据，请查看诊断确认视觉理解是否关闭或降级。";
    actions = [
      `<button type="button" data-switch-result-tab="note">阅读笔记</button>`,
      hasVisuals ? `<button type="button" data-switch-result-tab="frames">核对画面</button>` : `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
    ];
  } else if (hasMedia && !hasTranscript) {
    title = "等待转写字幕";
    detail = "媒体已保存到本地，下一步会优先使用平台/内嵌字幕，没有字幕时再进入 ASR。";
    actions = [`<button type="button" data-switch-result-tab="diagnostics">看处理状态</button>`];
  } else if (hasTranscript && !hasVisuals && task.options?.visual_understanding !== false) {
    title = "等待画面切片";
    detail = "字幕已经生成，下一步应抽帧、拼网格并按视觉窗口对齐字幕。";
    actions = [
      `<button type="button" data-switch-result-tab="transcript">核对字幕</button>`,
      `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
    ];
  } else {
    title = "等待图文总结";
    detail = "任务会按下载、转写、切片、总结顺序推进；阶段检查会显示当前卡点。";
    actions = [`<button type="button" data-switch-result-tab="diagnostics">查看阶段检查</button>`];
  }

  return `<section class="next-step-card ${escapeHtml(tone)}" aria-label="下一步">
    <div>
      <span>下一步</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <div class="next-step-actions">${actions.filter(Boolean).join("")}</div>
  </section>`;
}

function mediaPreviewHtml(task) {
  const url = taskMediaPreviewUrl(task);
  if (!url) return "";
  const title = displayTaskTitle(task, "media");
  const mediaName = taskMediaDisplayName(task);
  return `<section class="media-preview-card" aria-label="本地视频核对">
    <div class="media-preview-copy">
      <span>本地视频核对</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(task.media_path || "")}</small>
    </div>
    <video controls preload="metadata" src="${escapeHtml(url)}" data-learning-video></video>
    <div class="media-preview-actions">
      <span>点击字幕或视觉窗口时间可回看对应画面</span>
      <a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 ${escapeHtml(mediaName)}</a>
      ${canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""}
    </div>
  </section>`;
}

function mediaSeekDockHtml(task) {
  if (!hasExportableMedia(task)) return "";
  return `<section class="media-seek-dock" aria-label="本地视频回看">
    ${mediaPreviewHtml(task)}
  </section>`;
}

function taskCommandCenterItemState(task, key) {
  const windows = visualWindows(task || {});
  if (!task) return "wait";
  const hasMedia = hasExportableMedia(task);
  const hasTranscript = hasReadableTranscript(task);
  if (task.status === "failed" && ["source", "media"].includes(key) && !hasMedia) return "fail";
  if (key === "source") return (task.selected_resource?.url || task.download_attempts?.length || hasMedia) ? "pass" : "wait";
  if (key === "transcript") return hasTranscript || task.source_type === "page_text" ? "pass" : task.phase === "transcribing" ? "active" : "wait";
  if (key === "visual") {
    if (task.options?.visual_understanding === false || task.source_type === "page_text") return "skip";
    return windows.length || task.frame_grids?.length ? "pass" : task.phase === "extracting_frames" ? "active" : "wait";
  }
  if (key === "note") return task.note_path ? "pass" : task.phase === "summarizing" ? "active" : "wait";
  return "wait";
}

function nextCommandCenterText(task, items) {
  if (task.status === "failed") {
    return {
      title: "先看来源证据和失败原因",
      detail: task.error_detail || task.error_code || "确认是登录态、签名、DRM 还是无可直取资源。"
    };
  }
  if (canContinueFromDownloadedMedia(task)) {
    const mediaName = taskMediaDisplayName(task);
    return {
      title: "视频已保存到本地，可以继续切片总结",
      detail: `复用 ${mediaName} 进入转写、抽帧、视觉窗口和图文笔记。`
    };
  }
  const waiting = items.find(item => !["pass", "skip"].includes(taskCommandCenterItemState(task, item.key)));
  if (waiting) {
    return {
      title: `${waiting.label}正在推进`,
      detail: "任务会按来源、媒体、字幕、切片、总结顺序流转。"
    };
  }
  return {
    title: "笔记和资料包已就绪",
    detail: "可以阅读笔记、核对字幕/画面，或导出完整学习资料包。"
  };
}

function taskCommandCenter(task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const selected = task.selected_resource || {};
  const attempts = task.download_attempts || [];
  const hasTranscript = hasReadableTranscript(task);
  const transcriptSource = reusableTranscriptSourceText(task);
  const sourceDetail = selected.audio_url
    ? `音视频合并 · ${compactUrl(selected.audio_url, 52)}`
    : selected.playback_match ? playbackText(selected.playback_match) : `${attempts.length || 0} 次下载尝试`;
  const items = [
    {
      key: "source",
      label: "来源证据",
      value: mediaKindText(selected.kind) || selected.kind || task.source_type || "-",
      detail: sourceDetail,
      action: hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">看证据</button>` : ""
    },
    {
      key: "transcript",
      label: "字幕转写",
      value: hasTranscript ? (transcriptSource || "已生成") : task.source_type === "page_text" ? "页面文本" : task.phase === "transcribing" ? "转写中" : "等待",
      detail: hasTranscript ? "可核对或导出字幕" : "平台字幕优先，ASR 兜底",
      action: hasTranscript ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""
    },
    {
      key: "visual",
      label: "画面切片",
      value: windows.length ? `${windows.length} 窗口` : task.options?.visual_understanding === false ? "已关闭" : "等待",
      detail: windows.length ? `${fmt(windows[0]?.start || 0)} - ${fmt(windows[windows.length - 1]?.end || 0)}` : "抽帧后按视觉窗口对齐",
      action: windows.length ? `<button type="button" data-switch-result-tab="frames">看切片</button>` : ""
    },
    {
      key: "note",
      label: "笔记导出",
      value: task.note_path ? (task.summary_source || "笔记完成") : task.phase === "summarizing" ? "总结中" : canContinueFromDownloadedMedia(task) ? "可继续" : "等待",
      detail: task.note_path ? `${task.options?.note_style || "study"} · ${task.options?.note_template || "standard"}` : "生成 Markdown 和资料包",
      action: task.note_path
        ? `<button type="button" data-switch-result-tab="note">读笔记</button>${hasTaskBundle(task) ? `<button type="button" data-export="bundle">资料包</button>` : ""}`
        : canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>` : ""
    }
  ];
  const next = nextCommandCenterText(task, items);
  return `<section class="task-command-center" aria-label="BiliNote 式任务导航">
    <header>
      <div>
        <span>学习任务导航</span>
        <strong>${escapeHtml(next.title)}</strong>
      </div>
      <small>${escapeHtml(next.detail)}</small>
    </header>
    <div class="task-command-grid">
      ${items.map(item => `<article class="${escapeHtml(taskCommandCenterItemState(task, item.key))}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
        ${item.action ? `<div>${item.action}</div>` : ""}
      </article>`).join("")}
    </div>
  </section>`;
}

function directExtractionRouteLabel(route) {
  const labels = {
    download_only_to_local_media: "只下载到本地",
    browser_candidate_to_local_media: "浏览器候选直取",
    local_video_pipeline: "本地视频管线",
    page_text_only: "页面文本兜底",
    resolver_to_local_media: "解析器落地",
    attempted_direct_extraction: "已尝试直取",
    pending_or_no_media: "等待媒体"
  };
  return labels[route] || route || "未知路线";
}

function directExtractionBoundaryText(boundary) {
  const labels = {
    normal_accessible_media_only: "仅可访问媒体",
    drm_or_encrypted_not_bypassed: "DRM 不绕过",
    mediastream_not_recorded: "MediaStream 不录制",
    unresolved_blob_or_fragment_not_recorded: "blob/分片不录制"
  };
  return labels[boundary] || boundary || "边界正常";
}

function directExtractionSafeHeaders(direct) {
  const names = direct?.selected_candidate?.safe_request_header_names;
  if (!Array.isArray(names)) return "";
  return names
    .map(name => String(name || "").trim())
    .filter(name => name && !/cookie|authorization/i.test(name))
    .sort()
    .join(", ");
}

function directExtractionEvidenceItems(task) {
  const direct = task?.direct_extraction;
  if (!direct) return [];
  const selected = direct.selected_candidate || {};
  const mediaName = taskMediaDisplayName(task);
  const browser = direct.browser_context || {};
  const download = direct.download || {};
  const processing = direct.processing || {};
  const safeHeaders = directExtractionSafeHeaders(direct);
  const contextDetail = [
    selected.source ? `source ${selected.source}` : "",
    selected.playback_match ? playbackText(selected.playback_match) : "",
    browser.active_source_type ? `active ${browser.active_source_type}` : "",
    Number.isFinite(browser.browser_subtitle_count) ? `${browser.browser_subtitle_count} 字幕` : "",
    Number.isFinite(browser.cookie_count) ? `${browser.cookie_count} cookie` : "",
    Number.isFinite(browser.cookie_domain_count) ? `${browser.cookie_domain_count} cookie 域` : "",
    Number.isFinite(browser.partitioned_cookie_count) && browser.partitioned_cookie_count > 0 ? `${browser.partitioned_cookie_count} 分区 cookie` : "",
    Number.isFinite(browser.partition_key_count) && browser.partition_key_count > 0 ? `${browser.partition_key_count} partition key` : "",
    safeHeaders ? `headers ${safeHeaders}` : ""
  ].filter(Boolean).join(" · ");
  const strategyOrder = Array.isArray(download.strategy_order)
    ? download.strategy_order.map(item => String(item || "").trim()).filter(Boolean).slice(0, 4).join(" → ")
    : "";
  const successCount = Number(download.successful_attempt_count || 0);
  const failedCount = Number(download.failed_attempt_count || 0);
  const processingDetail = [
    processing.transcript_ready ? "转写已就绪" : "转写待生成",
    Number.isFinite(processing.frame_grid_count) ? `${processing.frame_grid_count} 网格` : "",
    Number.isFinite(processing.visual_window_count) ? `${processing.visual_window_count} 视觉窗` : "",
    processing.note_ready ? "笔记已就绪" : "",
    directExtractionBoundaryText(direct.boundary)
  ].filter(Boolean).join(" · ");

  return [
    {
      state: direct.no_tab_recording === false ? "warn" : "pass",
      label: "直取路线",
      value: directExtractionRouteLabel(direct.route),
      detail: [
        direct.no_tab_recording === false ? "录制状态未知" : "不录制标签页",
        direct.no_drm_bypass === false ? "DRM 边界未知" : "不绕过 DRM"
      ].join(" · ")
    },
    {
      state: direct.media_landed ? "pass" : "warn",
      label: "媒体保存",
      value: direct.media_landed ? `已保存 ${mediaName}` : "未保存",
      detail: direct.media_reusable ? "可复用本地视频" : directExtractionBoundaryText(direct.boundary)
    },
    {
      state: contextDetail ? "active" : "skip",
      label: "浏览器上下文",
      value: selected.kind ? `${selected.kind} · ${selected.source || "候选"}` : (browser.active_source_type ? `active ${browser.active_source_type}` : "无候选"),
      detail: contextDetail || "Cookie 仅任务启动时同步"
    },
    {
      state: successCount ? "pass" : failedCount ? "fail" : "wait",
      label: "下载尝试",
      value: `成功 ${successCount} / 失败 ${failedCount}`,
      detail: strategyOrder || "等待下载器结果"
    },
    {
      state: processing.note_ready || processing.transcript_ready || processing.download_only ? "pass" : "wait",
      label: "处理状态",
      value: processing.download_only ? "只下载模式" : processing.note_ready ? "已生成笔记" : processing.transcript_ready ? "已转写" : "待处理",
      detail: processingDetail || directExtractionBoundaryText(direct.boundary)
    }
  ];
}

function directExtractionEvidenceHtml(task) {
  const items = directExtractionEvidenceItems(task);
  if (!items.length) return "";
  return `<section class="direct-extraction-evidence" aria-label="直取证据">
    <header>
      <span>直取证据</span>
      <strong>非录制下载路线</strong>
    </header>
    <div class="direct-extraction-grid">
      ${items.map(item => `<article class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </article>`).join("")}
    </div>
  </section>`;
}

function taskNextActionsHtml(task) {
  const actions = Array.isArray(task?.next_actions) ? task.next_actions : [];
  if (!actions.length) return "";
  const controls = actions.map(action => {
    const label = escapeHtml(action.label || action.key || "下一步");
    const detail = escapeHtml(action.detail || "");
    const content = `<span>${label}</span>${detail ? `<small>${detail}</small>` : ""}`;
    if (action.intent === "rerun_from_media") {
      return `<button type="button" class="next-action primary" data-rerun-from-media="${escapeHtml(task.id)}">${content}</button>`;
    }
    if (action.intent === "switch_tab" && action.target) {
      return `<button type="button" class="next-action" data-switch-result-tab="${escapeHtml(action.target)}">${content}</button>`;
    }
    if (action.intent === "export" && action.target) {
      return `<a class="next-action" href="${escapeHtml(taskExportUrl(task, action.target))}">${content}</a>`;
    }
    return `<span class="next-action muted">${content}</span>`;
  }).join("");
  return `<section class="task-next-actions" aria-label="推荐下一步">
    <header>
      <span>推荐下一步</span>
      <strong>按当前产物继续学习</strong>
    </header>
    <div>${controls}</div>
  </section>`;
}

function taskOverview(task) {
  const selected = task.selected_resource || {};
  const options = task.options || {};
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasMedia = Boolean(task.media_path);
  const hasBundle = hasTaskBundle(task);
  const statusClass = taskStatusClass(task);
  const downloadOnly = hasMedia && !hasNote && task.status === "success";
  const canContinueMedia = canContinueFromDownloadedMedia(task);
  const fallbackNote = task.status === "failed" && hasNote;
  const failedWithoutFallback = task.status === "failed" && !fallbackNote;
  const mediaName = taskMediaDisplayName(task);
  const resourceLine = [
    sourceText(task),
    mediaKindText(selected.kind) || selected.kind || task.source_type || "",
    selected.audio_url ? "伴随音频流" : "",
    resourceSourceText(selected),
    selected.playback_match ? playbackText(selected.playback_match) : "",
    directResponseResolvedFact(selected, 72),
    selected.resolved_url ? "已跟踪最终 URL" : "",
    contentDispositionHint(selected.headers?.["content-disposition"]),
    selected.content_length ? fmtBytes(selected.content_length) : ""
  ].filter(Boolean).join(" · ");
  const actionLinks = [
    canContinueMedia ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>` : "",
    hasNote ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>` : "",
    hasMedia ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>` : "",
    task.resource_inventory_path ? `<a href="${escapeHtml(taskExportUrl(task, "resource-inventory"))}">导出候选证据</a>` : "",
    task.page_preflight_report_path ? `<a href="${escapeHtml(taskExportUrl(task, "page-preflight-report"))}">导出预检报告</a>` : "",
    hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a>` : "",
    hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
  ].filter(Boolean).join("");

  return `<section class="task-overview status-${statusClass}">
    <div class="task-overview-main">
      <span class="eyeless">当前学习任务</span>
      <strong>${escapeHtml(displayTaskTitle(task))}</strong>
      <small>${escapeHtml(resourceLine || statusText(task))}</small>
      ${stageRail(task)}
    </div>
    <div class="task-overview-actions">
      ${actionLinks || `<span>${escapeHtml(statusText(task))}</span>`}
    </div>
    ${taskNextActionsHtml(task)}
    <div class="task-overview-metrics">
      <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
      <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
      <span><b>${escapeHtml(task.summary_source || asrOptionText(options))}</b>${escapeHtml(task.summary_warning ? "已降级，查看诊断" : `${options.note_style || "study"} · ${options.note_template || "standard"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "画面窗口" : "等待画面切片"}</span>
    </div>
    ${taskBrowserEvidenceHtml(task)}
    ${directExtractionEvidenceHtml(task)}
    ${pipelineAuditHtml(task)}
    ${recoveryDecisionHtml(task)}
    ${taskCommandCenter(task)}
    ${nextStepHtml(task)}
    ${mediaPreviewHtml(task)}
    ${visualCoverageHtml(task)}
    ${taskRouteEvidenceHtml(task)}
    ${downloadOnly ? `<div class="download-only-callout">
      <strong>已完成直取下载</strong>
      <span>这个任务按“只下载本地”运行，未进入转写、切片和总结。可以先导出 ${escapeHtml(mediaName)}，或直接复用这个本地视频生成完整笔记。</span>
    </div>` : ""}
    ${fallbackNote ? `<div class="download-only-callout fallback-note-callout">
      <strong>已生成兜底笔记</strong>
      <span>视频直取失败，但已用页面文本/浏览器字幕生成可读笔记；诊断仍保留原始下载错误和资源证据。</span>
    </div>` : ""}
    ${failedWithoutFallback ? `<div class="download-only-callout failed-media-callout">
      <strong>${escapeHtml(task.error_code || "任务失败")}</strong>
      <span>${escapeHtml(task.error_detail || "请查看诊断里的下载尝试和处理日志。")}</span>
    </div>` : ""}
  </section>`;
}

function taskBrowserEvidenceHtml(task) {
  if (!task || task.source_type !== "current_page") return "";
  const selected = task.selected_resource || {};
  const activeText = activeVideoText(task.active_video);
  const target = taskResolvedTargetText(task, 108) || selected.url || "";
  const resolvedFact = directResponseResolvedFact(selected, 108);
  const requestContext = [
    requestHeaderNames(selected),
    selected.frame_url ? `frame ${compactUrl(selected.frame_url, 58)}` : "",
    mseAppendEvidence(selected),
    selected.blob_url ? "blob 已映射" : ""
  ].filter(item => item && item !== "-").join(" · ");
  if (activeText === "-" && !target && !requestContext) return "";
  return `<section class="task-browser-evidence" aria-label="浏览器播放证据">
    <header>
      <span>浏览器播放证据</span>
      <strong>非录制直取</strong>
    </header>
    <div>
      <article>
        <b>播放状态</b>
        <span>${escapeHtml(activeText)}</span>
      </article>
      <article>
        <b>${escapeHtml(resolvedFact ? "接口解析" : "直取目标")}</b>
        <span>${escapeHtml(target || "等待媒体候选")}</span>
      </article>
      <article>
        <b>请求上下文</b>
        <span>${escapeHtml(requestContext || "Cookie 仅任务启动时同步")}</span>
      </article>
    </div>
  </section>`;
}

function lastDownloadAttempt(task) {
  const attempts = task?.download_attempts || [];
  return attempts.length ? attempts[attempts.length - 1] : null;
}

function taskReuseEvidenceItem(task) {
  const reuse = task?.reuse || {};
  const sourceTaskId = String(task?.source_task_id || reuse.source_task_id || "").trim();
  const sourceMediaPath = String(task?.source_media_path || reuse.source_media_path || reuse.media_path_recorded || "").trim();
  if (!sourceTaskId && !sourceMediaPath) return null;
  const sourceMediaName = sourceMediaPath
    ? (sourceMediaPath.replace(/[?#].*$/, "").replace(/\\/g, "/").split("/").filter(Boolean).pop() || "原片")
    : "";
  if (!sourceTaskId && task?.source_type === "local" && task?.mode !== "rerun_from_media") {
    return {
      label: "上传原片",
      value: sourceMediaName || "本地视频",
      detail: sourceMediaPath ? compactUrl(sourceMediaPath, 86) : "已保存到 data/uploads"
    };
  }
  return {
    label: "复用来源",
    value: sourceTaskId ? `来自 ${sourceTaskId}` : "已复用本地媒体",
    detail: sourceMediaPath ? compactUrl(sourceMediaPath, 86) : "原直取任务媒体"
  };
}

function rerunFromMediaNotice(sourceTaskId, newTaskId, task = null) {
  const sourceId = String(sourceTaskId || task?.source_task_id || task?.reuse?.source_task_id || "").trim();
  const targetId = String(newTaskId || task?.id || "").trim();
  const mediaName = taskMediaDisplayName(task);
  const sourceText = sourceId ? `从任务 ${sourceId} 复用已下载 ${mediaName}` : `复用已下载 ${mediaName}`;
  const targetText = targetId ? `，新完整笔记任务 ${targetId}` : "";
  return `${sourceText}${targetText}，正在进入转写、抽帧、视觉窗口和图文总结；不会录制页面。`;
}

function taskRouteEvidenceItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const lastAttempt = lastDownloadAttempt(task);
  const headers = requestHeaderNames(selected);
  const diag = task?.summary_diagnostics || {};
  const reuseEvidence = taskReuseEvidenceItem(task);
  const resolvedTarget = taskResolvedTargetText(task, 86);
  const resolvedFact = directResponseResolvedFact(selected, 86);
  const attemptState = lastAttempt ? [lastAttempt.strategy, lastAttempt.code || lastAttempt.status].filter(Boolean).join(" · ") : "";
  const downloadDetail = resolvedTarget
    ? (lastAttempt ? `${resolvedTarget} · ${attemptState || "-"}` : resolvedTarget)
    : (lastAttempt ? `${attemptState || lastAttempt.strategy || "-"}` : (task.error_code || task.phase || "-"));
  const summaryText = summaryDiagnosticText(task);
  const summaryValue = task.summary_source || (diag.used_page_text_fallback ? "页面文本兜底" : task.note_path ? "已有笔记" : "待生成");
  const summaryDetail = summaryText === "-"
    ? (task.summary_warning || (task.note_path ? "未记录总结诊断" : "等待图文总结"))
    : summaryText;
  const items = [
    {
      label: "直取来源",
      value: selected.kind ? `${selected.kind} · ${resourceSourceText(selected) || selected.source || "候选资源"}` : sourceText(task),
      detail: selected.playback_match ? playbackText(selected.playback_match) : (selected.label || "页面/本地任务")
    },
    {
      label: "下载路线",
      value: attempts.length ? `${attempts.length} 次尝试` : task.media_path ? "已有本地媒体" : "等待下载",
      detail: resolvedFact ? `${resolvedFact} · ${downloadDetail}` : downloadDetail
    },
    ...(reuseEvidence ? [reuseEvidence] : []),
    {
      label: "浏览器证据",
      value: headers !== "-" ? headers : selected.status_code ? `HTTP ${selected.status_code}` : "无可复用请求头",
      detail: [
        selected.mime || "",
        selected.content_length ? fmtBytes(selected.content_length) : "",
        selected.request_type || "",
        mseAppendEvidence(selected)
      ].filter(Boolean).join(" · ") || "Cookie 仅任务启动时同步"
    },
    {
      label: "总结证据",
      value: summaryValue,
      detail: summaryDetail
    }
  ];
  return items.filter(item => item.value || item.detail);
}

function taskRouteEvidenceHtml(task) {
  const items = taskRouteEvidenceItems(task);
  if (!items.length) return "";
  return `<div class="route-evidence-strip" aria-label="直取和总结证据">
    ${items.map(item => `<span>
      <b>${escapeHtml(item.label)}</b>
      <strong>${escapeHtml(item.value || "-")}</strong>
      <small>${escapeHtml(item.detail || "-")}</small>
    </span>`).join("")}
  </div>`;
}

async function rerunTaskFromMedia(taskId) {
  if (!taskId) return;
  els.resultMeta.textContent = "正在复用已下载视频，并按当前切片、ASR 和视觉模型参数创建完整笔记任务...";
  const response = await fetch(taskRerunUrl(taskId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(readOptions())
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    els.resultMeta.textContent = detail?.detail?.message || detail?.detail || "无法复用已下载视频。";
    return;
  }
  const data = await response.json();
  pendingRerunNotice = {
    taskId: data.task_id,
    message: rerunFromMediaNotice(data.source_task_id || taskId, data.task_id, data.task)
  };
  selectTask(data.task_id);
  selectedTab = "note";
  renderResultTabState();
  syncSelectedTaskUrl(selectedTaskId);
  await loadTasks();
  focusResultPanelOnMobile();
}

async function copyBackendUrl(feedbackButton = els.copyBackendButton) {
  const url = API || (isBackendSameOrigin() ? window.location.origin : DEFAULT_BACKEND_ORIGIN);
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    const input = document.createElement("input");
    input.value = url;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  if (els.browserBridgeStatus) {
    setBrowserExtensionHandoffStatus(url);
  }
  if (feedbackButton) {
    const previous = feedbackButton.innerHTML;
    feedbackButton.textContent = "已复制";
    setTimeout(() => {
      feedbackButton.innerHTML = previous;
    }, 1400);
  }
  return url;
}

function safeCitationUrl(value) {
  const url = String(value || "").trim();
  return /^(https?:\/\/|\/)/i.test(url) ? url : "";
}

function qaCitationHtml(item) {
  const label = item?.label || item?.source || "证据";
  const meta = [item?.window_id, item?.time_range].filter(Boolean).join(" · ");
  const gridUrl = safeCitationUrl(item?.grid_url);
  const windowId = item?.window_id || "";
  const targetTab = RESULT_TAB_NAMES.has(item?.target_tab) ? item.target_tab : item?.window_id ? "slices" : "";
  return `<span class="${item?.window_id ? "visual" : ""}">
    <b>${escapeHtml(label)}</b>
    ${meta ? `<em>${escapeHtml(meta)}</em>` : ""}
    ${escapeHtml(item?.text || "")}
    ${(targetTab || gridUrl) ? `<small>
      ${targetTab ? `<button type="button" data-switch-result-tab="${escapeHtml(targetTab)}"${windowId ? ` data-focus-visual-window="${escapeHtml(windowId)}"` : ""}>查看切片</button>` : ""}
      ${gridUrl ? `<a href="${escapeHtml(gridUrl)}" target="_blank" rel="noreferrer">打开网格</a>` : ""}
    </small>` : ""}
  </span>`;
}

function qaPanelHtml(task) {
  const state = qaState.taskId === task?.id ? qaState : { taskId: task?.id || "", question: "", answer: "", source: "", warning: "", citations: [], historyCount: 0, recent: [], loading: false };
  const citations = Array.isArray(state.citations) ? state.citations : [];
  const historyCount = Number(state.historyCount || task?.qa?.history_count || 0);
  const recent = Array.isArray(state.recent) && state.recent.length ? state.recent : Array.isArray(task?.qa?.recent) ? task.qa.recent : [];
  const suggestions = Array.isArray(task?.qa?.suggestions) ? task.qa.suggestions : [];
  return `<section class="qa-panel" aria-label="任务问答">
    <form id="qaForm" class="qa-form">
      <label>
        <span>问这个任务</span>
        <textarea id="qaQuestion" rows="3" maxlength="1000" placeholder="例如：这节课最重要的概念是什么？">${escapeHtml(state.question || "")}</textarea>
      </label>
      <button class="primary action-button" type="submit"${state.loading ? " disabled" : ""}>${state.loading ? "回答中..." : "提问"}</button>
    </form>
    ${suggestions.length ? `<div class="qa-suggestions" aria-label="建议问题">${suggestions.map(item => `
      <button type="button" data-qa-suggestion="${escapeHtml(item.question || "")}">
        <span>${escapeHtml(item.label || item.source || "建议")}</span>
        ${escapeHtml(item.question || "")}
      </button>
    `).join("")}</div>` : ""}
    <div class="qa-history-bar">
      <span>已保存 ${historyCount} 条问答</span>
      ${historyCount ? `<a href="${escapeHtml(taskExportUrl(task, "qa"))}">导出问答</a>` : ""}
    </div>
    ${state.warning ? `<p class="qa-warning">${escapeHtml(state.warning)}</p>` : ""}
    ${state.answer ? `<article class="markdown-note qa-answer">${markdownToHtml(state.answer)}</article>` : `<div class="detail empty">基于当前任务的笔记、字幕和画面索引回答；没有模型 Key 时会先给出本地摘录。</div>`}
    ${citations.length ? `<div class="qa-citations">${citations.map(item => qaCitationHtml(item)).join("")}</div>` : ""}
    ${recent.length ? `<div class="qa-recent" aria-label="最近问答">${recent.map((item, index) => `
      <article>
        <span>Q${index + 1} · ${escapeHtml(item.source || "saved")}${item.citation_count ? ` · ${escapeHtml(item.citation_count)} 证据` : ""}</span>
        <strong>${escapeHtml(item.question || "-")}</strong>
        <p>${escapeHtml(item.answer_excerpt || "")}</p>
      </article>
    `).join("")}</div>` : ""}
  </section>`;
}

async function submitTaskQuestion(task) {
  const input = document.querySelector("#qaQuestion");
  const question = String(input?.value || "").trim();
  if (!task?.id || !question) return;
  const existingRecent = Array.isArray(task?.qa?.recent) ? task.qa.recent : [];
  qaState = { taskId: task.id, question, answer: "", source: "", warning: "", citations: [], historyCount: Number(task?.qa?.history_count || 0), recent: existingRecent, loading: true };
  renderDetail();
  try {
    const response = await fetch(taskQaUrl(task.id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, options: readOptions() })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.detail?.message || payload?.detail || "问答失败");
    }
    qaState = {
      taskId: task.id,
      question,
      answer: payload.answer || "",
      source: payload.source || "",
      warning: payload.warning || "",
      citations: payload.citations || [],
      historyCount: Number(payload.history_count || task?.qa?.history_count || 0),
      recent: payload.history_item ? [{
        id: payload.history_item.id || "",
        created_at: payload.history_item.created_at || "",
        question: payload.history_item.question || question,
        answer_excerpt: (payload.history_item.answer || payload.answer || "").replace(/\s+/g, " ").slice(0, 420),
        source: payload.history_item.source || payload.source || "",
        warning: payload.history_item.warning || payload.warning || "",
        provider: payload.history_item.provider || "",
        model: payload.history_item.model || "",
        citation_count: Array.isArray(payload.history_item.citations) ? payload.history_item.citations.length : 0
      }, ...existingRecent].slice(0, 5) : existingRecent,
      loading: false
    };
  } catch (error) {
    qaState = { taskId: task.id, question, answer: "", source: "", warning: error.message || "问答失败", citations: [], historyCount: Number(task?.qa?.history_count || 0), recent: existingRecent, loading: false };
  }
  renderDetail();
}

function bindQaActions(task) {
  const form = document.querySelector("#qaForm");
  if (!form) return;
  document.querySelectorAll("[data-qa-suggestion]").forEach(button => {
    button.onclick = () => {
      const input = document.querySelector("#qaQuestion");
      if (!input) return;
      input.value = button.dataset.qaSuggestion || "";
      input.focus();
    };
  });
  form.onsubmit = event => {
    event.preventDefault();
    submitTaskQuestion(task);
  };
}

function bindTaskOverviewActions() {
  document.querySelectorAll("[data-rerun-from-media]").forEach(button => {
    button.onclick = () => rerunTaskFromMedia(button.dataset.rerunFromMedia);
  });
  document.querySelectorAll("[data-switch-result-tab]").forEach(button => {
    button.onclick = () => switchResultTab(button.dataset.switchResultTab, button.dataset.focusVisualWindow || "");
  });
  document.querySelectorAll("[data-media-seek-time]").forEach(button => {
    button.onclick = () => seekLearningVideo(button.dataset.mediaSeekTime, button);
  });
  document.querySelectorAll("[data-recovery-source]").forEach(button => {
    button.onclick = () => {
      setSource(button.dataset.recoverySource);
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

function focusVisualWindow(windowId) {
  const id = String(windowId || "").trim();
  if (!id) return;
  const target = [...document.querySelectorAll("[data-visual-window]")]
    .find(item => item.dataset.visualWindow === id);
  if (!target) return;
  target.classList.remove("visual-window-focused");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => target.classList.add("visual-window-focused"), 20);
  window.setTimeout(() => target.classList.remove("visual-window-focused"), 1800);
}

function switchResultTab(tabName, focusWindowId = "") {
  const normalizedTab = normalizeResultTabName(tabName);
  if (!RESULT_TAB_NAMES.has(normalizedTab)) return;
  if (selectedTab !== normalizedTab) {
    selectedTab = normalizedTab;
    renderResultTabState();
    syncSelectedTaskUrl(selectedTaskId);
    renderDetail();
  }
  if (focusWindowId) window.setTimeout(() => focusVisualWindow(focusWindowId), 0);
}

function noteHeadingStats(markdown) {
  if (!markdown) return { total: 0, h1: 0, h2: 0, h3: 0 };
  const stats = { total: 0, h1: 0, h2: 0, h3: 0 };
  const inFence = { value: false };
  markdown.split(/\r?\n/).forEach(line => {
    if (/^\s*```/.test(line)) {
      inFence.value = !inFence.value;
      return;
    }
    if (inFence.value) return;
    const match = line.match(/^(#{1,3})\s+(.+)/);
    if (!match) return;
    stats.total += 1;
    stats[`h${match[1].length}`] += 1;
  });
  return stats;
}

function notePrimaryTitle(markdown, task) {
  const inFence = { value: false };
  for (const line of String(markdown || "").split(/\r?\n/)) {
    if (/^\s*```/.test(line)) {
      inFence.value = !inFence.value;
      continue;
    }
    if (inFence.value) continue;
    const match = line.match(/^\s*#{1,2}\s+(.+)/);
    if (match) {
      const text = plainHeadingText(match[1]);
      if (text) return text;
    }
  }
  return task?.title || task?.id || "LearnNote";
}

function noteHeroBanner(markdown, task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const headings = noteHeadingStats(markdown);
  const selected = task.selected_resource || {};
  const mediaName = taskMediaDisplayName(task);
  const firstWindow = windows.find(window => safeNoteMediaUrl(window.grid_url)) || windows[0] || null;
  const image = safeNoteMediaUrl(firstWindow?.grid_url || "");
  const sourceUrl = safeExternalUrl(task.page_url || selected.url || "");
  const sourceLabel = [
    sourceText(task),
    selected.playback_match ? playbackText(selected.playback_match) : "",
    selected.kind ? mediaKindText(selected.kind) : "",
    task.summary_source || ""
  ].filter(Boolean).join(" · ");
  const timeline = windows.length && firstWindow
    ? `${fmt(windows[0].start || 0)} - ${fmt(windows[windows.length - 1].end || 0)}`
    : hasExportableMedia(task) ? `${mediaName} 已保存` : "等待切片";
  const metrics = [
    { label: "章节", value: headings.total ? `${headings.total}` : "-" },
    { label: "字幕", value: hasReadableTranscript(task) ? "已生成" : task.browser_subtitles?.length ? `${task.browser_subtitles.length} 条` : "-" },
    { label: "画面", value: windows.length ? `${windows.length} 窗口` : "-" },
    { label: "状态", value: statusText(task) }
  ];
  const actions = [
    task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">Markdown</a>` : "",
    hasReadableTranscript(task) ? `<button type="button" data-switch-result-tab="transcript">字幕</button>` : "",
    windows.length ? `<button type="button" data-switch-result-tab="frames">画面</button>` : "",
    sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">原页面</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">资料包</a>` : ""
  ].filter(Boolean).join("");

  return `<section class="note-hero-banner" aria-label="课程笔记资料页">
    <div class="note-hero-media ${image ? "" : "empty"}">
      ${image ? `<img src="${image}" alt="课程画面预览">` : `<span>LN</span>`}
    </div>
    <div class="note-hero-main">
      <span>课程笔记</span>
      <strong>${escapeHtml(notePrimaryTitle(markdown, task))}</strong>
      <small>${escapeHtml(sourceLabel || task.page_url || task.source_type || "-")}</small>
      <div class="note-hero-meta">
        <em>${escapeHtml(timeline)}</em>
        <em>${escapeHtml(optionText(task) || asrOptionText(task.options || {}))}</em>
      </div>
      <div class="note-hero-metrics">
        ${metrics.map(item => `<b><span>${escapeHtml(item.value)}</span>${escapeHtml(item.label)}</b>`).join("")}
      </div>
      ${actions ? `<div class="note-hero-actions">${actions}</div>` : ""}
    </div>
  </section>`;
}

function reviewCommandButton(target, label, enabled = true) {
  if (!enabled) return `<span>${escapeHtml(label)}</span>`;
  return `<button type="button" data-switch-result-tab="${escapeHtml(target)}">${escapeHtml(label)}</button>`;
}

function learningPathHtml(markdown, task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const headings = noteHeadingStats(markdown);
  const hasNote = Boolean(task.note_path || markdown);
  const hasTranscript = hasReadableTranscript(task);
  const hasVisuals = windows.length > 0;
  const hasQa = Boolean(hasNote);
  const steps = [
    {
      number: "01",
      label: "读笔记",
      value: headings.total ? `${headings.total} 个标题` : hasNote ? "已生成" : "等待总结",
      detail: hasNote ? "先读课程主题、重点和易错点。" : "任务完成后进入阅读。",
      target: "note",
      enabled: hasNote,
      state: hasNote ? "ready" : "wait"
    },
    {
      number: "02",
      label: "看切片",
      value: hasVisuals ? `${windows.length} 个窗口` : task.options?.visual_understanding === false ? "未启用" : "等待抽帧",
      detail: hasVisuals ? "按时间窗核对 PPT、代码或演示。" : "开启视觉理解后显示画面网格。",
      target: "slices",
      enabled: hasVisuals,
      state: hasVisuals ? "ready" : task.options?.visual_understanding === false ? "skip" : "wait"
    },
    {
      number: "03",
      label: "核字幕",
      value: hasTranscript ? "已对齐" : "等待 ASR",
      detail: hasTranscript ? "用时间戳回查原片上下文。" : asrOptionText(task.options || {}),
      target: "transcript",
      enabled: hasTranscript,
      state: hasTranscript ? "ready" : "wait"
    },
    {
      number: "04",
      label: "问答复习",
      value: task.qa?.history_count ? `${task.qa.history_count} 条` : hasQa ? "可提问" : "等待笔记",
      detail: hasQa ? "基于笔记、字幕和画面索引追问。" : "先生成笔记再提问。",
      target: "qa",
      enabled: hasQa,
      state: task.qa?.history_count ? "ready" : hasQa ? "active" : "wait"
    }
  ];
  return `<section class="learning-path" aria-label="学习路径">
    <header>
      <span>学习路径</span>
      <strong>读笔记 → 看切片 → 核字幕 → 提问</strong>
    </header>
    <div class="learning-path-steps">
      ${steps.map(step => `<article class="${escapeHtml(step.state)}">
        <b>${escapeHtml(step.number)}</b>
        <div>
          <span>${escapeHtml(step.label)}</span>
          <strong>${escapeHtml(step.value)}</strong>
          <small>${escapeHtml(step.detail)}</small>
        </div>
        ${step.enabled ? `<button type="button" data-switch-result-tab="${escapeHtml(step.target)}">进入</button>` : `<em>待就绪</em>`}
      </article>`).join("")}
    </div>
  </section>`;
}

function noteReviewWorkbench(markdown, task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const headings = noteHeadingStats(markdown);
  const hasNote = Boolean(task.note_path || markdown);
  const hasTranscript = hasReadableTranscript(task);
  const hasVisuals = windows.length > 0;
  const hasDiagnostics = hasTaskDiagnostics(task);
  const hasAudit = hasTaskAudit(task);
  const hasMedia = hasExportableMedia(task);
  const canContinueMedia = canContinueFromDownloadedMedia(task);
  const mediaName = taskMediaDisplayName(task);
  const cards = [
    {
      state: hasNote ? "ready" : "wait",
      label: "复习笔记",
      value: headings.total ? `${headings.total} 个标题` : hasNote ? "已生成" : "等待生成",
      detail: hasNote ? "先读总笔记，再回看字幕和画面证据。" : "下载、转写和总结完成后显示。",
      action: reviewCommandButton("note", "阅读笔记", hasNote)
    },
    {
      state: hasVisuals ? "ready" : task.options?.visual_understanding === false ? "skip" : "wait",
      label: "学习切片",
      value: hasVisuals ? `${windows.length} 个窗口` : task.options?.visual_understanding === false ? "未启用视觉" : "等待切片",
      detail: hasVisuals ? `${fmt(windows[0]?.start || 0)} - ${fmt(windows[windows.length - 1]?.end || 0)}` : "抽帧后按时间窗口对齐字幕。",
      action: reviewCommandButton("slices", "看切片", hasVisuals)
    },
    {
      state: hasTranscript ? "ready" : "wait",
      label: "字幕时间轴",
      value: hasTranscript ? "可核对" : "等待转写",
      detail: hasTranscript ? "点击时间戳可回到本地视频定位。" : asrOptionText(task.options || {}),
      action: reviewCommandButton("transcript", "核对字幕", hasTranscript)
    },
    {
      state: task.qa?.history_count ? "ready" : hasNote ? "active" : "wait",
      label: "问答复习",
      value: task.qa?.history_count ? `${task.qa.history_count} 条记录` : hasNote ? "可提问" : "等待笔记",
      detail: hasNote ? "基于笔记、字幕和画面索引回答。" : "笔记生成后启用任务问答。",
      action: reviewCommandButton("qa", "打开问答", hasNote)
    }
  ];
  const exports = [
    task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">Markdown</a>` : "",
    hasExportableSubtitle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">字幕</a>` : "",
    hasVisualWindowExport(task) ? `<a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">切片索引</a>` : "",
    hasMedia ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">${escapeHtml(mediaName)}</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">资料包</a>` : ""
  ].filter(Boolean);
  const advanced = [
    hasDiagnostics ? `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>` : "",
    hasDiagnostics ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>` : "",
    hasAudit ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>` : "",
    task.resource_inventory_path ? `<a href="${escapeHtml(taskExportUrl(task, "resource-inventory"))}">候选证据</a>` : "",
    task.page_preflight_report_path ? `<a href="${escapeHtml(taskExportUrl(task, "page-preflight-report"))}">预检报告</a>` : ""
  ].filter(Boolean);
  const primary = canContinueMedia
    ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>`
    : hasNote
      ? `<button type="button" data-switch-result-tab="qa">问这节课</button>`
      : `<button type="button" data-switch-result-tab="diagnostics">查看阶段检查</button>`;
  const detail = canContinueMedia
    ? `视频已直取到本地，下一步复用 ${mediaName} 进入转写、抽帧和图文总结。`
    : hasNote
      ? "按 BiliNote 式阅读路径组织：笔记先读，切片和字幕随时核对，最后导出资料包。"
      : "任务还在推进，先用诊断和阶段检查确认卡点。";
  return `<section class="review-workbench ${canContinueMedia ? "partial" : hasNote ? "ready" : "pending"}" aria-label="复习工作台">
    <header>
      <div>
        <span>复习工作台</span>
        <strong>${escapeHtml(canContinueMedia ? "已直取视频，继续生成完整笔记" : "按证据复习这节课")}</strong>
        <small>${escapeHtml(detail)}</small>
      </div>
      <div class="review-workbench-primary">${primary}</div>
    </header>
    ${learningPathHtml(markdown, task)}
    <div class="review-command-grid">
      ${cards.map(card => `<article class="${escapeHtml(card.state)}">
        <span>${escapeHtml(card.label)}</span>
        <strong>${escapeHtml(card.value)}</strong>
        <small>${escapeHtml(card.detail)}</small>
        <div>${card.action}</div>
      </article>`).join("")}
    </div>
    ${exports.length ? `<nav class="review-export-row" aria-label="快速导出"><span>快速导出</span>${exports.join("")}</nav>` : ""}
    ${advanced.length ? `<nav class="review-advanced-row" aria-label="高级诊断工具"><span>高级诊断</span>${advanced.join("")}</nav>` : ""}
  </section>`;
}

function noteStudyBar(markdown, task) {
  const headings = noteHeadingStats(markdown);
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasTranscript = hasReadableTranscript(task);
  const hasMedia = hasExportableMedia(task);
  const hasBundle = hasTaskBundle(task);
  const mediaName = taskMediaDisplayName(task);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const visualRange = windows.length && firstWindow && lastWindow
    ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}`
    : "等待切片";
  const cards = [
    {
      label: "笔记目录",
      value: headings.total ? `${headings.total} 个标题` : hasNote ? "无标题" : "未生成",
      text: headings.h2 ? `${headings.h2} 个章节 · ${headings.h3} 个小节` : "生成后自动提取目录",
      action: hasNote ? `<button type="button" data-switch-result-tab="note">阅读笔记</button>` : ""
    },
    {
      label: "画面切片",
      value: windows.length ? `${windows.length} 个窗口` : "未生成",
      text: visualRange,
      action: windows.length ? `<button type="button" data-switch-result-tab="frames">查看画面</button>` : ""
    },
    {
      label: "转写字幕",
      value: hasTranscript ? "已对齐" : "未生成",
      text: task.summary_warning ? "有降级提示，建议看诊断" : asrOptionText(task.options || {}),
      action: hasTranscript ? `<button type="button" data-switch-result-tab="transcript">看字幕</button>` : ""
    },
    {
      label: "本地产物",
      value: [hasMedia ? "视频" : "", hasBundle ? "资料包" : ""].filter(Boolean).join(" · ") || "等待产物",
      text: hasMedia ? `可复用 ${mediaName} 继续处理` : "任务完成后可导出",
      action: hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a><a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
    }
  ];
  return `<section class="study-map" aria-label="学习笔记导览">
    <div class="study-map-head">
      <div>
        <span>学习导览</span>
        <strong>${escapeHtml(displayTaskTitle(task))}</strong>
      </div>
      <small>${escapeHtml(sourceText(task))} · ${escapeHtml(statusText(task))}</small>
    </div>
    <div class="study-map-grid">
      ${cards.map(card => `<div class="study-map-card">
        <span>${escapeHtml(card.label)}</span>
        <strong>${escapeHtml(card.value)}</strong>
        <small>${escapeHtml(card.text)}</small>
        ${card.action ? `<div class="study-map-action">${card.action}</div>` : ""}
      </div>`).join("")}
    </div>
  </section>`;
}

function noteExportCtaBar(task) {
  if (!task?.id) return "";
  const hasMedia = hasExportableMedia(task);
  const mediaName = taskMediaDisplayName(task);
  const primary = [
    task.note_path ? `<a class="primary" href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>` : "",
    hasVisualWindowExport(task) ? `<a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
  ].filter(Boolean);
  const secondary = [
    hasExportableSubtitle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">字幕</a>` : "",
    hasMedia ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">${escapeHtml(mediaName)}</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">诊断</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">审计</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">清单</a>` : ""
  ].filter(Boolean);
  if (!primary.length && !secondary.length) return "";
  const windows = visualWindows(task);
  const status = task.note_path ? "ready" : hasMedia ? "partial" : "diagnostic";
  const detail = task.note_path
    ? `Markdown、切片索引和资料包可直接保存；${windows.length ? `${windows.length} 个视觉窗口会写入资料包。` : "当前任务没有视觉窗口。"}`
    : hasMedia
      ? "视频已保存到本地，可先导出媒体或继续切片总结。"
      : "任务未生成完整笔记，但诊断和审计仍可导出。";
  return `<section class="export-cta-bar ${escapeHtml(status)}" aria-label="导出学习成果">
    <div>
      <span>导出阶段</span>
      <strong>拿走学习成果</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <nav>
      ${primary.join("")}
      ${secondary.length ? `<span>${secondary.join("")}</span>` : ""}
    </nav>
  </section>`;
}

function visualRail(task, limit = 8) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  return `<section class="visual-rail" aria-label="画面索引">
    <div class="visual-rail-head">
      <strong>画面索引</strong>
      <span>${windows.length} 个窗口</span>
    </div>
    <div class="visual-rail-list">
      ${windows.slice(0, limit).map(window => `
        <figure>
          <img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">
          <figcaption>
            <strong>${escapeHtml(window.id)}</strong>
            <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count} 帧</span>
            ${window.transcript_excerpt ? `<small>${escapeHtml(window.transcript_excerpt)}</small>` : ""}
          </figcaption>
        </figure>
      `).join("")}
    </div>
  </section>`;
}

function readingProgressRail(markdown, task) {
  const headings = noteHeadingStats(markdown);
  const windows = visualWindows(task || {});
  const hasTranscript = hasReadableTranscript(task);
  const hasMedia = hasExportableMedia(task);
  const hasNote = Boolean(task?.note_path);
  const mediaName = taskMediaDisplayName(task);
  const items = [
    {
      state: hasNote ? "done" : "wait",
      label: "笔记",
      value: headings.total ? `${headings.total} 标题` : hasNote ? "已生成" : "等待",
      detail: headings.h2 ? `${headings.h2} 章节 · ${headings.h3} 小节` : "阅读主笔记"
    },
    {
      state: hasTranscript ? "done" : "wait",
      label: "字幕",
      value: hasTranscript ? "已对齐" : "等待",
      detail: hasTranscript ? "可切到字幕时间轴核对" : asrOptionText(task?.options || {})
    },
    {
      state: windows.length ? "done" : task?.options?.visual_understanding === false ? "skip" : "wait",
      label: "画面",
      value: windows.length ? `${windows.length} 窗口` : task?.options?.visual_understanding === false ? "未启用" : "等待",
      detail: windows.length ? `${fmt(windows[0]?.start || 0)} - ${fmt(windows[windows.length - 1]?.end || 0)}` : "抽帧后在这里预览"
    },
    {
      state: hasTaskBundle(task) ? "done" : hasMedia ? "active" : "wait",
      label: "产物",
      value: hasTaskBundle(task) ? "可导出" : hasMedia ? mediaName : "等待",
      detail: hasMedia ? `本地 ${mediaName} 可复用` : "完成后生成资料包"
    }
  ];
  return `<section class="reading-progress-rail" aria-label="学习进度">
    <div class="visual-rail-head">
      <strong>学习进度</strong>
      <span>${escapeHtml(statusText(task || {}))}</span>
    </div>
    <div class="reading-progress-list">
      ${items.map(item => `<div class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </div>`).join("")}
    </div>
  </section>`;
}

function readingArtifactsRail(task) {
  if (!task?.id) return "";
  const mediaName = taskMediaDisplayName(task);
  const actions = [
    task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">Markdown</a>` : "",
    hasExportableSubtitle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">字幕文件</a>` : "",
    hasExportableMedia(task) ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">${escapeHtml(mediaName)}</a>` : "",
    hasVisualWindowExport(task) ? `<a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">切片索引</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">审计</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">诊断</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">清单</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">资料包</a>` : ""
  ].filter(Boolean);
  if (!actions.length) return "";
  return `<section class="reading-artifacts-rail" aria-label="导出产物">
    <div class="visual-rail-head">
      <strong>导出产物</strong>
      <span>${actions.length} 项</span>
    </div>
    <div class="reading-artifact-actions">${actions.join("")}</div>
  </section>`;
}

function readingActionsRail(task) {
  if (!task) return "";
  const actions = [
    `<button type="button" data-switch-result-tab="note">读笔记</button>`,
    hasReadableTranscript(task) ? `<button type="button" data-switch-result-tab="transcript">查字幕</button>` : "",
    hasVisualWindowExport(task) ? `<button type="button" data-switch-result-tab="frames">看画面</button>` : "",
    hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">看诊断</button>` : "",
    canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>` : ""
  ].filter(Boolean);
  return `<section class="reading-actions-rail" aria-label="阅读动作">
    <div class="visual-rail-head">
      <strong>阅读动作</strong>
      <span>${actions.length} 个入口</span>
    </div>
    <div class="reading-action-list">${actions.join("")}</div>
  </section>`;
}

function readingRail(markdown, task) {
  const outline = noteOutline(markdown);
  const visuals = visualRail(task);
  const progress = readingProgressRail(markdown, task);
  const artifacts = readingArtifactsRail(task);
  const actions = readingActionsRail(task);
  const blocks = [progress, outline, visuals, actions, artifacts].filter(Boolean);
  if (!blocks.length) return "";
  return `<aside class="reading-rail" aria-label="笔记阅读导航">${blocks.join("")}</aside>`;
}

function visualWindows(task) {
  if (task.visual_windows?.length) return task.visual_windows;
  return (task.frame_grids || []).map((grid, index) => ({
    id: `W${String(index + 1).padStart(3, "0")}`,
    index: index + 1,
    start: grid.start,
    end: grid.end,
    frame_count: grid.frame_count,
    frame_timestamps: grid.frame_timestamps || [],
    grid_url: grid.url,
    transcript_excerpt: ""
  }));
}

function segmentOverlapsWindow(segment, window) {
  const start = Number(segment.start || 0);
  const end = Number(segment.end ?? start);
  return start < Number(window.end || 0) && end >= Number(window.start || 0);
}

function transcriptLines(segments) {
  return segments.map(seg => `<div class="line" data-line-time="${seekTimeValue(seg.start)}">${seekTimeButton(seg.start)}<span>${escapeHtml(seg.text)}</span></div>`).join("");
}

function transcriptOverview(transcript, task) {
  const segments = transcript?.segments || [];
  const windows = visualWindows(task);
  const first = segments[0];
  const last = segments[segments.length - 1];
  const range = first && last ? `${fmt(first.start)} - ${fmt(last.end ?? last.start)}` : "无时间轴";
  const source = transcriptSourceText(transcript?.source);
  return `<section class="transcript-overview" aria-label="字幕概览">
    <div>
      <span>字幕时间轴</span>
      <strong>${escapeHtml(source)}</strong>
      <small>${escapeHtml(windows.length ? "已按画面窗口对齐" : "独立字幕时间轴")}</small>
    </div>
    <div class="transcript-overview-metrics">
      <span><b>${segments.length}</b>段字幕</span>
      <span><b>${escapeHtml(range)}</b>时间范围</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "视觉窗口" : "无切片"}</span>
    </div>
  </section>`;
}

function transcriptTimeline(transcript, task, limit = Infinity) {
  const segments = (transcript?.segments || []).slice(0, limit);
  const windows = visualWindows(task);
  if (!windows.length) {
    return `${transcriptOverview(transcript, task)}<div class="transcript-timeline transcript-timeline-plain">${transcriptLines(segments)}</div>`;
  }

  const used = new Set();
  const cards = windows.map(window => {
    const matched = segments.filter((segment, index) => {
      if (!segmentOverlapsWindow(segment, window)) return false;
      used.add(index);
      return true;
    });
    const body = matched.length
      ? transcriptLines(matched)
      : window.transcript_excerpt
        ? `<p>${escapeHtml(window.transcript_excerpt)}</p>`
        : `<p class="muted">这个画面窗口没有匹配到字幕段落。</p>`;
    return `<section class="transcript-window" data-visual-window="${escapeHtml(window.id || "")}" data-window-start="${seekTimeValue(window.start)}">
      <figure>
        ${window.grid_url ? `<img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">` : ""}
        <figcaption>
          <strong>${escapeHtml(window.id)}</strong>
          <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count || 0} 帧</span>
          ${seekTimeButton(window.start, "window-seek")}
        </figcaption>
      </figure>
      <div class="transcript-window-lines">${body}</div>
    </section>`;
  });

  const unmatched = segments.filter((_, index) => !used.has(index));
  if (unmatched.length) {
    cards.push(`<section class="transcript-window transcript-window-orphan">
      <figure>
        <figcaption>
          <strong>未归入切片</strong>
          <span>${unmatched.length} 段字幕</span>
        </figcaption>
      </figure>
      <div class="transcript-window-lines">${transcriptLines(unmatched)}</div>
    </section>`);
  }

  return `${transcriptOverview(transcript, task)}<div class="transcript-timeline">${cards.join("")}</div>`;
}

function visualStudyCueHtml(window, transcript) {
  const segments = transcript?.segments || [];
  const matched = segments.filter(segment => segmentOverlapsWindow(segment, window)).slice(0, 4);
  if (matched.length) {
    return `<div class="visual-study-cues">
      ${matched.map(segment => `<div>${seekTimeButton(segment.start)}<span>${escapeHtml(segment.text)}</span></div>`).join("")}
    </div>`;
  }
  const excerpt = window.transcript_excerpt || "这个窗口暂无字幕摘录，可切到“字幕”查看完整时间轴。";
  return `<p>${escapeHtml(excerpt)}</p>`;
}

function visualWindowSummaryItems(window, transcript = null) {
  const rawItems = [
    window?.local_summary,
    window?.window_summary,
    window?.slice_summary,
    window?.visual_summary,
    window?.summary,
    window?.learning_summary
  ];
  const arrays = [
    window?.key_points,
    window?.summary_points,
    window?.concepts
  ].filter(Array.isArray);
  const items = [];
  const pushText = value => {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text || items.includes(text)) return;
    items.push(text);
  };
  rawItems.forEach(value => {
    const text = String(value || "").trim();
    if (!text) return;
    text.split(/\n+|(?:^|\s)[-•]\s+/).forEach(pushText);
  });
  arrays.flat().forEach(pushText);
  if (items.length) return items.slice(0, 3);

  const matched = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 2)
    .map(segment => String(segment.text || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (matched.length) {
    return matched.map(text => text.length > 120 ? `${text.slice(0, 120).trim()}...` : text);
  }

  const excerpt = String(window?.transcript_excerpt || "").replace(/\s+/g, " ").trim();
  if (excerpt) return [excerpt.length > 160 ? `${excerpt.slice(0, 160).trim()}...` : excerpt];

  const frameTimes = (window?.frame_timestamps || []).slice(0, 3).map(value => fmt(value)).join(" / ");
  return [frameTimes ? `按 ${frameTimes} 这几帧核对本段画面变化。` : "暂无局部总结；先从截图标题、公式、代码或演示状态提炼本段主题。"];
}

function visualWindowSummaryHtml(window, transcript = null) {
  const items = visualWindowSummaryItems(window, transcript);
  return `<div class="visual-window-summary">
    <span>本段要点</span>
    <ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  </div>`;
}

function visualWindowCueSegments(window, transcript = null, limit = 2) {
  return (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, limit)
    .map(segment => ({
      start: Number(segment.start || 0),
      text: String(segment.text || "").replace(/\s+/g, " ").trim()
    }))
    .filter(item => item.text);
}

function visualStudyChecklistHtml(window, transcript) {
  const hasCue = Boolean(window.transcript_excerpt) || (transcript?.segments || []).some(segment => segmentOverlapsWindow(segment, window));
  const target = hasCue
    ? "核对截图里的板书、PPT 切换、代码/界面状态是否已被字幕覆盖。"
    : "先从截图判断这一段的主题，重点看标题、公式、代码和演示状态。";
  const action = hasCue
    ? "复述这一窗口的结论，再按画面顺序补齐遗漏步骤。"
    : "补一句本段主题，再和前后窗口串成完整时间线。";
  return `<div class="visual-study-checklist">
    <span>学习动作</span>
    <ul>
      <li>${escapeHtml(target)}</li>
      <li>${escapeHtml(action)}</li>
    </ul>
  </div>`;
}

function visualStudyCheckpointHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 3)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => `<li>${seekTimeButton(item.seconds, "checkpoint-seek")}<span>${escapeHtml(item.text.length > 96 ? `${item.text.slice(0, 96).trim()}...` : item.text)}；对照画面确认对应的板书、PPT、代码或操作步骤。</span></li>`)
    : [`<li><span>无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。</span></li>`];
  return `<div class="visual-study-checkpoints">
    <span>回看检查点</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

function visualStudyQuestionHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 2)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => {
      const text = item.text.length > 72 ? `${item.text.slice(0, 72).trim()}...` : item.text;
      return `<li>${seekTimeButton(item.seconds, "question-seek")}<span>这句“${escapeHtml(text)}”在画面中对应的标题、公式、代码或操作状态是什么？</span></li>`;
    })
    : (() => {
      const frameTimes = (window.frame_timestamps || []).slice(0, 3).map(value => fmt(value)).join(" / ");
      return [
        `<li><span>${escapeHtml(frameTimes ? `这些帧（${frameTimes}）里最能说明本段主题的画面证据是什么？` : "这个窗口里最值得回看的标题、公式、代码、界面状态或演示步骤是什么？")}</span></li>`,
        `<li><span>如果没有字幕，能否用一句话描述这组截图的操作顺序或 PPT 结构？</span></li>`
      ];
    })();
  return `<div class="visual-study-questions">
    <span>自测问题</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

function visualWindowEvidenceState(task, window, index = 0) {
  const diag = task?.summary_diagnostics || {};
  const id = String(window?.id || `W${String(index + 1).padStart(3, "0")}`);
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  if (missingIds.has(id)) {
    return { state: "missing", label: "缺图", detail: "未送入视觉模型，按字幕与索引复习" };
  }
  if (omittedIds.has(id)) {
    return { state: "omitted", label: "已省略", detail: "超出视觉批次上限，保留本地索引" };
  }
  if (sentIds.has(id) || diag.used_vision_llm || task?.summary_source === "vision-llm") {
    return { state: "vision", label: "已进视觉", detail: "网格图已参与图文总结" };
  }
  return { state: "ready", label: "本地索引", detail: safeNoteMediaUrl(window?.grid_url || "") ? "可核对画面和字幕" : "等待网格图" };
}

function visualStudyCorrelationHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const shown = windows.slice(0, 10);
  const rows = shown.map((window, index) => {
    const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
    const evidence = visualWindowEvidenceState(task, window, index);
    const image = safeNoteMediaUrl(window.grid_url || "");
    const cues = visualWindowCueSegments(window, transcript, 3);
    const points = visualWindowSummaryItems(window, transcript).slice(0, 2);
    const hasReviewEvidence = Boolean(cues.length || window.transcript_excerpt || (window.frame_timestamps || []).length);
    const cueText = cues.length
      ? `${cues.length} 段字幕 · ${fmt(cues[0].start)} 起`
      : window.transcript_excerpt
        ? "有窗口摘录"
        : "待补字幕";
    const cuePreview = cues[0]?.text || window.transcript_excerpt || "切到字幕页核对完整上下文";
    const summaryText = points[0] || "等待局部总结";
    const secondarySummary = points[1] || evidence.detail;
    return `<article class="${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(id)}" data-window-start="${seekTimeValue(window.start)}">
      <div class="visual-study-correlation-id">
        <b>${escapeHtml(id)}</b>
        <time>${fmt(window.start)} - ${fmt(window.end)}</time>
      </div>
      <div>
        <span>画面</span>
        <strong>${image ? "截图网格" : "无图"}</strong>
        <small>${escapeHtml(evidence.label)} · ${Number(window.frame_count || 0)} 帧</small>
      </div>
      <div>
        <span>字幕</span>
        <strong>${escapeHtml(cueText)}</strong>
        <small>${escapeHtml(cuePreview.length > 86 ? `${cuePreview.slice(0, 86).trim()}...` : cuePreview)}</small>
      </div>
      <div>
        <span>局部总结</span>
        <strong>${escapeHtml(summaryText.length > 74 ? `${summaryText.slice(0, 74).trim()}...` : summaryText)}</strong>
        <small>${escapeHtml(secondarySummary.length > 96 ? `${secondarySummary.slice(0, 96).trim()}...` : secondarySummary)}</small>
      </div>
      <div>
        <span>复习动作</span>
        <strong>${hasReviewEvidence ? "可自测" : "先看片"}</strong>
        <small>${hasReviewEvidence ? "按画面解释字幕中的标题、公式、代码或操作状态" : "先描述截图再补字幕"}</small>
      </div>
      <nav>
        <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看</button>
        <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(id)}">字幕</button>
        <button type="button" data-switch-result-tab="note">笔记</button>
      </nav>
    </article>`;
  });
  const remaining = Math.max(0, windows.length - shown.length);
  return `<section class="visual-study-correlation" aria-label="切片证据核对矩阵">
    <header>
      <div>
        <span>证据核对矩阵</span>
        <strong>逐窗对齐画面、字幕、局部总结和复习动作</strong>
      </div>
      <small>${shown.length}/${windows.length} 窗口${remaining ? ` · 余 ${remaining}` : ""}</small>
    </header>
    <div>${rows.join("")}</div>
  </section>`;
}

function visualStudyOverviewHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  const states = windows.map((window, index) => visualWindowEvidenceState(task, window, index).state);
  const visionCount = states.filter(state => state === "vision").length;
  const missingCount = states.filter(state => state === "missing").length;
  const omittedCount = states.filter(state => state === "omitted").length;
  const transcriptSegments = transcript?.segments || [];
  const alignedCueCount = transcriptSegments.filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const cueWindowCount = windows.filter(window => (
    window.transcript_excerpt ||
    transcriptSegments.some(segment => segmentOverlapsWindow(segment, window))
  )).length;
  const frameCount = windows.reduce((total, window) => total + Number(window.frame_count || 0), 0);
  const gridText = task.options?.grid_columns && task.options?.grid_rows
    ? `${task.options.grid_columns}x${task.options.grid_rows}`
    : "网格";
  const quality = missingCount || omittedCount
    ? "部分窗口需要人工核对"
    : visionCount
      ? "图文证据完整"
      : "本地索引可复习";
  const cards = [
    { label: "覆盖范围", value: range, detail: `${windows.length} 个视觉窗口` },
    { label: "视觉总结", value: visionCount ? `${visionCount}/${windows.length} 已参与` : "未调用视觉", detail: quality },
    { label: "字幕对齐", value: alignedCueCount ? `${alignedCueCount} 段` : "无匹配字幕", detail: cueWindowCount ? `${cueWindowCount}/${windows.length} 窗口有线索` : transcriptSegments.length ? "可逐窗核对" : "等待转写产物" },
    { label: "画面证据", value: `${frameCount} 帧`, detail: `${gridText} 截图网格` }
  ];
  return `<section class="visual-study-overview" aria-label="切片学习总览">
    <header>
      <div>
        <span>切片总览</span>
        <strong>${escapeHtml(quality)}</strong>
      </div>
      <small>${escapeHtml(displayTaskTitle(task, "视觉窗口"))}</small>
    </header>
    <div class="visual-study-overview-grid">
      ${cards.map(card => `<article>
        <span>${escapeHtml(card.label)}</span>
        <strong>${escapeHtml(card.value)}</strong>
        <small>${escapeHtml(card.detail)}</small>
      </article>`).join("")}
    </div>
    ${(missingCount || omittedCount) ? `<p>有 ${missingCount + omittedCount} 个窗口未完整进入视觉模型；请优先打开对应卡片，结合截图和字幕人工核对。</p>` : ""}
    <nav>
      <button type="button" data-switch-result-tab="transcript">核对字幕</button>
      <button type="button" data-switch-result-tab="note">回到笔记</button>
      ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>` : ""}
      <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
    </nav>
  </section>`;
}

function visualWindowReviewItem(task, window, index = 0, transcript = null) {
  const id = String(window?.id || `W${String(index + 1).padStart(3, "0")}`);
  const evidence = visualWindowEvidenceState(task, window, index);
  const cues = visualWindowCueSegments(window, transcript, 3);
  const hasImage = Boolean(safeNoteMediaUrl(window?.grid_url || ""));
  const points = visualWindowSummaryItems(window, transcript).filter(Boolean);
  const hasSummary = points.some(point => point && !/暂无局部总结|先从截图/i.test(point));
  const frameCount = Number(window?.frame_count || 0);
  let priority = 5;
  let label = "常规复核";
  let reason = "确认画面、字幕和笔记结论一致。";
  if (evidence.state === "missing" || evidence.state === "omitted") {
    priority = 0;
    label = "优先核对";
    reason = evidence.detail;
  } else if (!hasImage) {
    priority = 1;
    label = "缺少截图";
    reason = "没有截图网格，先用字幕和前后窗口补全上下文。";
  } else if (!cues.length && !window?.transcript_excerpt) {
    priority = 2;
    label = "补字幕线索";
    reason = "没有同步字幕，先看截图判断本段主题。";
  } else if (!hasSummary) {
    priority = 3;
    label = "补局部总结";
    reason = "已有画面或字幕，但本段总结仍需要人工提炼。";
  } else if (evidence.state === "vision") {
    priority = 4;
    label = "快速确认";
    reason = "已进入视觉模型，复核重点是模型是否漏掉画面细节。";
  }
  return {
    id,
    window,
    evidence,
    priority,
    label,
    reason,
    cueCount: cues.length || (window?.transcript_excerpt ? 1 : 0),
    frameCount,
    hasSummary,
    summary: points[0] || reason
  };
}

function visualStudyReviewPathHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const items = windows
    .map((window, index) => visualWindowReviewItem(task, window, index, transcript))
    .sort((left, right) => left.priority - right.priority || Number(left.window.start || 0) - Number(right.window.start || 0));
  const shown = items.slice(0, 6);
  const urgentCount = items.filter(item => item.priority <= 2).length;
  const readyCount = items.filter(item => item.evidence.state === "vision" || item.hasSummary).length;
  return `<section class="visual-review-path" aria-label="切片复核路线">
    <header>
      <div>
        <span>复核路线</span>
        <strong>${urgentCount ? `先处理 ${urgentCount} 个重点窗口` : "按时间线快速复核"}</strong>
      </div>
      <small>${readyCount}/${items.length} 窗口已有总结或视觉证据</small>
    </header>
    <div class="visual-review-path-list">
      ${shown.map(item => `<article class="${escapeHtml(item.evidence.state)} priority-${item.priority}">
        <button type="button" class="visual-review-path-main" data-switch-result-tab="slices" data-focus-visual-window="${escapeHtml(item.id)}">
          <b>${escapeHtml(item.id)}</b>
          <span>${escapeHtml(item.label)}</span>
          <strong>${fmt(item.window.start)} - ${fmt(item.window.end)}</strong>
          <small>${escapeHtml(item.reason)}</small>
        </button>
        <div>
          <em>${item.frameCount || "-"} 帧</em>
          <em>${item.cueCount || "-"} 字幕</em>
          <em>${escapeHtml(item.hasSummary ? "有总结" : "待总结")}</em>
        </div>
        <p>${escapeHtml(String(item.summary || item.reason).replace(/\s+/g, " ").slice(0, 160))}</p>
        <nav>
          <button type="button" data-media-seek-time="${seekTimeValue(item.window.start)}">回看</button>
          <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(item.id)}">字幕</button>
        </nav>
      </article>`).join("")}
    </div>
    ${items.length > shown.length ? `<footer>还有 ${items.length - shown.length} 个窗口；导出切片索引可查看完整顺序。</footer>` : ""}
  </section>`;
}

function visualStudyHandoutHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const shown = windows.slice(0, 8);
  const remaining = Math.max(0, windows.length - shown.length);
  return `<section class="visual-study-handout" aria-label="切片讲义时间轴">
    <header>
      <div>
        <span>切片讲义时间轴</span>
        <strong>${escapeHtml(displayTaskTitle(task, "切片讲义"))}</strong>
      </div>
      <small>画面-字幕-总结对齐</small>
    </header>
    <div class="visual-study-handout-list">
      ${shown.map((window, index) => {
        const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
        const image = safeNoteMediaUrl(window.grid_url || "");
        const evidence = visualWindowEvidenceState(task, window, index);
        const points = visualWindowSummaryItems(window, transcript).slice(0, 2);
        const cues = visualWindowCueSegments(window, transcript, 2);
        const cueHtml = cues.length
          ? cues.map(cue => `<p>${seekTimeButton(cue.start, "window-seek")}<span>${escapeHtml(cue.text.length > 130 ? `${cue.text.slice(0, 130).trim()}...` : cue.text)}</span></p>`).join("")
          : `<p><span>${escapeHtml(String(window.transcript_excerpt || "暂无字幕线索；先看截图中的标题、公式、代码或演示状态。").replace(/\s+/g, " ").trim())}</span></p>`;
        return `<article class="${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(id)}" data-window-start="${seekTimeValue(window.start)}">
          <div class="visual-study-handout-time">
            <b>${escapeHtml(id)}</b>
            <time>${fmt(window.start)} - ${fmt(window.end)}</time>
            <em>${escapeHtml(evidence.label)}</em>
          </div>
          <div class="visual-study-handout-body">
            <div class="visual-study-handout-title">
              <strong>${escapeHtml(points[0] || "先核对本段画面变化")}</strong>
              <small>${escapeHtml(evidence.detail)} · ${Number(window.frame_count || 0)} 帧</small>
            </div>
            ${image ? `<figure><img src="${image}" alt="${escapeHtml(id)} frame grid"><figcaption>${escapeHtml(frameTimestampText(window) || "截图网格")}</figcaption></figure>` : ""}
            ${points.length > 1 ? `<ul>${points.slice(1).map(point => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
            <div class="visual-study-handout-cues">${cueHtml}</div>
            <div class="visual-study-handout-actions">
              <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看</button>
              <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(id)}">字幕</button>
              ${image ? `<a href="${escapeHtml(image)}" target="_blank" rel="noreferrer">网格</a>` : ""}
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
    ${remaining ? `<footer>还有 ${remaining} 个窗口；导出切片索引可查看完整列表。</footer>` : ""}
  </section>`;
}

function visualStudyDeck(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  const matchedCueCount = (transcript?.segments || []).filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const headDetail = matchedCueCount ? `${windows.length} 个窗口 · ${matchedCueCount} 段字幕已同步` : `${windows.length} 个窗口 · ${range}`;
  return `<section class="visual-study-deck" aria-label="视觉窗口复习">
    <div class="visual-study-head">
      <div>
        <span>视觉窗口复习</span>
        <strong>${escapeHtml(displayTaskTitle(task, "画面切片"))}</strong>
      </div>
      <div class="visual-study-head-actions">
        <small>${escapeHtml(headDetail)}</small>
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </div>
    </div>
    <div class="visual-study-list">
      ${windows.map((window, index) => {
        const image = safeNoteMediaUrl(window.grid_url || "");
        const evidence = visualWindowEvidenceState(task, window, index);
        return `<article class="visual-study-card ${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(window.id || "")}" data-window-start="${seekTimeValue(window.start)}">
          <figure>
            ${image ? `<img src="${image}" alt="${escapeHtml(window.id)} frame grid">` : `<div class="visual-study-placeholder">无画面</div>`}
            <figcaption>${escapeHtml(window.id || `W${String(index + 1).padStart(3, "0")}`)}</figcaption>
          </figure>
          <div class="visual-study-card-body">
            <span>窗口 ${String(index + 1).padStart(2, "0")}</span>
            <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
            <small class="visual-study-evidence ${escapeHtml(evidence.state)}">${escapeHtml(evidence.label)} · ${escapeHtml(evidence.detail)}</small>
            ${visualWindowSummaryHtml(window, transcript)}
            ${visualStudyCueHtml(window, transcript)}
            ${visualStudyCheckpointHtml(window, transcript)}
            ${visualStudyQuestionHtml(window, transcript)}
            ${visualStudyChecklistHtml(window, transcript)}
            ${hasExportableMedia(task) ? `<p class="visual-clip-action"><a href="${escapeHtml(taskClipExportUrl(task, window.id || `W${String(index + 1).padStart(3, "0")}`))}">导出片段</a></p>` : ""}
            <div class="visual-study-meta">
              <em>${Number(window.frame_count || 0)} 帧</em>
              ${frameTimestampText(window) ? `<em>${escapeHtml(frameTimestampText(window))}</em>` : ""}
              <em>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "网格")}</em>
              <em>${escapeHtml(task.summary_source || "本地索引")}</em>
            </div>
            <div class="visual-study-actions">
              <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看此段</button>
              <button type="button" data-switch-result-tab="transcript">看对应字幕</button>
              <button type="button" data-switch-result-tab="note">回到笔记</button>
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function visualStudyNavigatorHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const diag = task.summary_diagnostics || {};
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  const items = windows.map((window, index) => {
    const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
    const matched = (transcript?.segments || []).filter(segment => segmentOverlapsWindow(segment, window));
    let state = "ready";
    if (missingIds.has(id)) state = "missing";
    else if (omittedIds.has(id)) state = "omitted";
    else if (sentIds.has(id) || diag.used_vision_llm || task.summary_source === "vision-llm") state = "vision";
    const label = {
      vision: "已进视觉",
      ready: "本地索引",
      missing: "缺图",
      omitted: "已省略"
    }[state];
    return `<button type="button" class="${escapeHtml(state)}" data-media-seek-time="${seekTimeValue(window.start)}" data-window-start="${seekTimeValue(window.start)}">
      <span>${escapeHtml(id)}</span>
      <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
      <small>${escapeHtml(label)} · ${Number(window.frame_count || 0)} 帧 · ${matched.length || 0} 字幕</small>
    </button>`;
  });
  return `<section class="visual-study-navigator" aria-label="视觉窗口学习队列">
    <header>
      <span>复习队列</span>
      <strong>按画面窗口回看</strong>
      <small>先扫窗口，再进入下方卡片核对字幕、截图和自测题。</small>
    </header>
    <div>${items.join("")}</div>
  </section>`;
}

function learningSliceWorkbench(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const matchedCueCount = (transcript?.segments || []).filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const totalFrames = windows.reduce((sum, window) => sum + Number(window.frame_count || 0), 0);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  return `<div class="slice-workbench" aria-label="学习切片工作台">
    <section class="slice-brief">
      <div>
        <span>学习切片</span>
        <strong>${escapeHtml(displayTaskTitle(task, "视频学习切片"))}</strong>
        <small>按视觉窗口把截图网格、同步字幕和回看动作组织在一起，适合复习 PPT、板书、代码演示和界面操作。</small>
      </div>
      <dl>
        <div><dt>窗口</dt><dd>${windows.length}</dd></div>
        <div><dt>画面</dt><dd>${totalFrames || "-"}</dd></div>
        <div><dt>字幕</dt><dd>${matchedCueCount || "-"}</dd></div>
        <div><dt>范围</dt><dd>${escapeHtml(range)}</dd></div>
      </dl>
      <nav>
        ${transcript?.segments?.length ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
        ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""}
      </nav>
    </section>
    ${visualStudyOverviewHtml(task, transcript)}
    ${visualStudyNavigatorHtml(task, transcript)}
    ${visualStudyReviewPathHtml(task, transcript)}
    ${visualStudyCorrelationHtml(task, transcript)}
    ${visualStudyHandoutHtml(task, transcript)}
    ${visualStudyDeck(task, transcript)}
  </div>`;
}

function visualFrameWorkbench(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const totalFrames = windows.reduce((sum, window) => sum + Number(window.frame_count || 0), 0);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  return `<div class="slice-workbench frame-workbench" aria-label="画面网格复核">
    <section class="slice-brief">
      <div>
        <span>画面网格</span>
        <strong>${escapeHtml(displayTaskTitle(task, "视频画面网格"))}</strong>
        <small>集中核对每个视觉窗口的截图网格、帧时间和回看按钮，适合检查 PPT、板书、代码和界面操作有没有进入笔记。</small>
      </div>
      <dl>
        <div><dt>窗口</dt><dd>${windows.length}</dd></div>
        <div><dt>帧数</dt><dd>${totalFrames || "-"}</dd></div>
        <div><dt>网格</dt><dd>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "默认")}</dd></div>
        <div><dt>范围</dt><dd>${escapeHtml(range)}</dd></div>
      </dl>
      <nav>
        <button type="button" data-switch-result-tab="slices">学习切片</button>
        ${transcript?.segments?.length ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </nav>
    </section>
    ${visualStudyCorrelationHtml(task, transcript)}
    ${visualStudyDeck(task, transcript)}
  </div>`;
}

function pendingSliceWorkbench(task) {
  if (!task?.media_path) return "";
  const canContinue = canContinueFromDownloadedMedia(task);
  const mediaName = taskMediaDisplayName(task);
  return `<div class="slice-workbench pending" aria-label="待生成学习切片">
    ${mediaSeekDockHtml(task)}
    <section class="slice-pending-card">
      <div>
        <span>下一步</span>
        <strong>${canContinue ? "视频已直取到本地，可以继续切片总结" : "等待生成学习切片"}</strong>
        <small>${canContinue
          ? `复用已下载的 ${mediaName}，按当前参数进入转写、抽帧、视觉窗口和图文笔记流程；不会重新录制页面。`
          : "任务完成抽帧后，这里会显示按时间窗口组织的截图网格、字幕片段和回看动作。"}</small>
      </div>
      <ol>
        <li class="done"><b>1</b><span>本地视频</span><small>${escapeHtml(mediaName)} 已保存，可导出核对。</small></li>
        <li class="${canContinue ? "active" : "wait"}"><b>2</b><span>转写与抽帧</span><small>继续任务后生成字幕和画面网格。</small></li>
        <li class="wait"><b>3</b><span>学习切片</span><small>按视觉窗口汇总字幕、截图和复习问题。</small></li>
      </ol>
      <nav>
        ${canContinue ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 ${escapeHtml(mediaName)}</a>
        ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看下载诊断</button>` : ""}
      </nav>
    </section>
  </div>`;
}

function emptyResultWorkbench() {
  return `
    <section class="empty-workbench" aria-label="学习工作区起始页">
      <div class="empty-hero">
        <div class="empty-hero-copy">
          <span>LearnNote 工作区</span>
          <h3>把正在看的课程视频变成可复习的图文笔记</h3>
          <p>从扩展 Side Panel 直取当前页可访问的视频资源，或上传本地视频；后端会下载到本机、转写、切片、生成画面网格，再合并成学习笔记。</p>
          <div class="empty-production-brief" aria-label="本次产出工作台">
            <section>
              <b>输入</b>
              <strong>当前页 / 本地 / 链接</strong>
              <small>优先直取可访问媒体，不录制页面。</small>
            </section>
            <section>
              <b>处理</b>
              <strong>下载 · 转写 · 切片</strong>
              <small>生成字幕、时间轴和视觉窗口。</small>
            </section>
            <section>
              <b>交付</b>
              <strong>Markdown · 诊断 · 资料包</strong>
              <small>可直接下载，不写入额外记录。</small>
            </section>
          </div>
          <div class="empty-hero-actions">
            <button type="button" data-empty-source="browser">当前页直取</button>
            <button type="button" data-empty-source="local">本地视频</button>
            <button type="button" data-empty-source="url">链接解析</button>
          </div>
        </div>
        <div class="empty-demo-board" aria-label="图文笔记生成预览">
          <header>
            <strong>当前页课程</strong>
            <span>直取候选 · HLS</span>
          </header>
          <div class="empty-demo-video">
            <div class="empty-demo-play"></div>
            <span>00:12:48</span>
          </div>
          <div class="empty-demo-caption">
            <time>12:48</time>
            <span>浏览器字幕和转写片段会按视觉窗口对齐。</span>
          </div>
          <div class="empty-demo-grids">
            ${Array.from({ length: 9 }).map(() => "<i></i>").join("")}
          </div>
          <div class="empty-demo-note">
            <b>生成笔记</b>
            <span>课程主题、时间轴重点、画面索引、易错点、复习题</span>
          </div>
        </div>
      </div>

      <div class="empty-quick-routes" aria-label="开始路线">
        <button type="button" class="primary" data-empty-source="browser">
          <div>
            <span>当前页直取</span>
            <strong>读取正在播放的视频</strong>
            <small>扩展侧栏嗅探媒体请求、播放器源和一次性 Cookie。</small>
          </div>
        </button>
        <button type="button" data-empty-source="local">
          <div>
            <span>本地视频</span>
            <strong>拖入文件直接切片</strong>
            <small>mp4、mkv、webm、flv、avi 走同一套转写和视觉总结。</small>
          </div>
        </button>
        <button type="button" data-empty-source="url">
          <div>
            <span>链接解析</span>
            <strong>粘贴页面或媒体链接</strong>
            <small>预检 mp4、m3u8、mpd 或平台页面，再决定下载/总结。</small>
          </div>
        </button>
      </div>

      <div class="empty-flow" aria-label="处理流程">
        <span><b>01</b>检测媒体</span>
        <span><b>02</b>预检下载</span>
        <span><b>03</b>转写切片</span>
        <span><b>04</b>图文总结</span>
      </div>
    </section>
  `;
}

function bindEmptyWorkbenchActions() {
  document.querySelectorAll("[data-empty-source]").forEach(button => {
    button.onclick = () => {
      setSource(button.dataset.emptySource);
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
  document.querySelectorAll("[data-empty-action]").forEach(button => {
    button.onclick = async () => {
      if (button.dataset.emptyAction === "copy-backend") {
        await copyBackendUrl(button);
        return;
      }
      if (button.dataset.emptyAction === "open-options") {
        if (els.optionsDisclosure) els.optionsDisclosure.open = true;
        els.optionsDisclosure?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      }
    };
  });
}

async function renderDetail() {
  const task = await taskRecord();
  if (!task) {
    els.selectedTitle.textContent = "选择一个任务";
    els.selectedSource.textContent = "结果工作区";
    els.resultMeta.textContent = "";
    els.detail.className = "detail empty";
    els.detail.innerHTML = emptyResultWorkbench();
    bindEmptyWorkbenchActions();
    lastNote = "";
    lastNoteTaskId = "";
    els.copyButton.disabled = true;
    els.bundleButton.disabled = true;
    els.diagnosticsButton.disabled = true;
    if (els.visualWindowsButton) els.visualWindowsButton.disabled = true;
    if (els.manifestButton) els.manifestButton.disabled = true;
    if (els.subtitlesButton) els.subtitlesButton.disabled = true;
    els.mediaButton.disabled = true;
    els.downloadButton.disabled = true;
    updateContinueFromMediaAction(null);
    return;
  }

  els.selectedTitle.textContent = displayTaskTitle(task);
  els.selectedSource.textContent = `${sourceText(task)} · ${statusText(task)}`;
  els.resultMeta.innerHTML = resultMetaChipsHtml(task);
  els.detail.className = "detail";
  const hasNote = Boolean(task.note_path);
  els.copyButton.disabled = !hasNote;
  els.bundleButton.disabled = !hasTaskBundle(task);
  els.diagnosticsButton.disabled = !hasTaskDiagnostics(task);
  if (els.visualWindowsButton) els.visualWindowsButton.disabled = !hasVisualWindowExport(task);
  if (els.manifestButton) els.manifestButton.disabled = !hasTaskBundle(task);
  if (els.subtitlesButton) els.subtitlesButton.disabled = !hasExportableSubtitle(task);
  els.mediaButton.disabled = !hasExportableMedia(task);
  els.downloadButton.disabled = !hasNote;
  updateContinueFromMediaAction(task);

  if (selectedTab === "note") {
    lastNote = await noteForTask(task.id);
    const emptyNoteHtml = hasExportableMedia(task) ? downloadOnlyEmptyNoteHtml(task) : "<p>笔记尚未生成。</p>";
    els.detail.innerHTML = `
      <div class="note-shell">
        ${taskOverview(task)}
        ${noteHeroBanner(lastNote, task)}
        ${noteReviewWorkbench(lastNote, task)}
        ${failureGuide(task)}
        ${visionEvidenceBar(task)}
        ${noteStudyBar(lastNote, task)}
        ${noteExportCtaBar(task)}
        <div class="note-workbench">
          <article class="markdown-note">${lastNote ? markdownToHtml(lastNote) : emptyNoteHtml}</article>
          ${readingRail(lastNote, task)}
        </div>
      </div>
    `;
    bindTaskOverviewActions();
    return;
  }

  if (selectedTab === "slices" || selectedTab === "frames") {
    const windows = visualWindows(task);
    if (!windows.length && hasExportableMedia(task)) {
      els.detail.className = "detail";
      els.detail.innerHTML = pendingSliceWorkbench(task);
      bindTaskOverviewActions();
      return;
    }
    if (!windows.length) {
      els.detail.className = "detail empty";
      els.detail.textContent = "画面切片尚未生成。";
      return;
    }
    const transcript = await transcriptForTask(task);
    const workbench = selectedTab === "frames"
      ? visualFrameWorkbench(task, transcript)
      : learningSliceWorkbench(task, transcript);
    els.detail.innerHTML = `${mediaSeekDockHtml(task)}${learningPathHtml(lastNote, task)}${visionEvidenceBar(task)}${workbench}`;
    bindTaskOverviewActions();
    return;
  }

  if (selectedTab === "qa") {
    els.detail.className = "detail";
    els.detail.innerHTML = `${taskOverview(task)}${qaPanelHtml(task)}`;
    bindTaskOverviewActions();
    bindQaActions(task);
    return;
  }

  if (selectedTab === "diagnostics") {
    const selected = task.selected_resource || {};
    const attempts = task.download_attempts || [];
    const transcript = await transcriptForTask(task);
    const transcriptSource = transcript?.source ? transcriptSourceText(transcript.source) : "-";
    const attemptHtml = attempts.length ? `
      <div class="attempt-list">
        ${attempts.map(attempt => `
          <div class="attempt ${escapeHtml(attempt.status)}">
            <div class="attempt-header">
              <div>
                <strong>${escapeHtml(attempt.strategy)}</strong>
                <small>${escapeHtml([
                  attempt.code,
                  attempt.status_code ? `HTTP ${attempt.status_code}` : "",
                  fmtBytes(attempt.bytes_downloaded || attempt.content_length),
                  attempt.kind,
                  attempt.source,
                  attemptHeaderNames(attempt) !== "-" ? `headers ${attemptHeaderNames(attempt)}` : "",
                  attempt.companion_audio_url ? `audio ${compactUrl(attempt.companion_audio_url, 44)}` : ""
                ].filter(Boolean).join(" · "))}</small>
              </div>
              <span class="attempt-status">${escapeHtml(attempt.status)}</span>
            </div>
            <p>${escapeHtml(attempt.message || attempt.url || "-")}</p>
            ${attempt.url ? `<code>${escapeHtml(attempt.url)}</code>` : ""}
          </div>
        `).join("")}
      </div>
    ` : "暂无下载尝试记录";
    els.detail.innerHTML = `
      ${failureGuide(task)}
      ${diagnosticRecoveryHtml(task)}
      ${chaoxingProfileHtml(task)}
      ${taskBrowserEvidenceHtml(task)}
      ${directExtractionEvidenceHtml(task)}
      ${taskRouteEvidenceHtml(task)}
      ${pipelineAuditHtml(task)}
      <dl class="diagnostics">
        <dt>任务 ID</dt><dd>${escapeHtml(task.id)}</dd>
        <dt>状态</dt><dd>${escapeHtml(task.status)} / ${escapeHtml(task.phase)} / ${task.progress || 0}%</dd>
        <dt>来源</dt><dd>${escapeHtml(task.page_url || task.source_type)}</dd>
        <dt>播放器快照</dt><dd>${escapeHtml(activeVideoText(task.active_video))}</dd>
        <dt>DRM/EME</dt><dd>${escapeHtml(task.drm_detected ? (drmSignalText(task.drm_signals || []) || "已检测到") : "-")}</dd>
        <dt>下载策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>已选资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>实际媒体 URL</dt><dd>${escapeHtml(taskResolvedTargetText(task, 140) || "-")}</dd>
        <dt>播放 blob</dt><dd>${escapeHtml(selected.blob_url || "-")}</dd>
        <dt>MSE append</dt><dd>${escapeHtml(mseAppendEvidence(selected) || "-")}</dd>
        <dt>所在 frame</dt><dd>${escapeHtml(selected.frame_url || "-")}</dd>
        <dt>资源类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          resourceSourceText(selected) || selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          playbackText(selected.playback_match),
          selected.request_type || "",
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length),
          contentDispositionHint(selected.headers?.["content-disposition"]),
          selected.mime || "-"
        ].filter(Boolean).join(" · "))}</dd>
        <dt>复用请求头</dt><dd>${escapeHtml(requestHeaderNames(selected))}</dd>
        <dt>请求 body</dt><dd>${escapeHtml(requestBodySummary(selected) || "-")}</dd>
        <dt>媒体文件</dt><dd>${escapeHtml(task.media_path || "-")}</dd>
        <dt>音频文件</dt><dd>${escapeHtml(task.audio_path || "-")}</dd>
        <dt>转写引擎</dt><dd>${escapeHtml(asrOptionText(task.options || {}))}</dd>
        <dt>转写来源</dt><dd>${escapeHtml(transcriptSource)}</dd>
        <dt>字幕文件</dt><dd>${escapeHtml(task.subtitle_path || "-")}</dd>
        <dt>总结来源</dt><dd>${escapeHtml(task.summary_source || "-")}</dd>
        <dt>图文总结诊断</dt><dd>${escapeHtml(summaryDiagnosticText(task))}</dd>
        <dt>总结提示</dt><dd>${escapeHtml(task.summary_warning || "-")}</dd>
        <dt>处理选项</dt><dd>${escapeHtml(optionText(task) || "-")}</dd>
        <dt>错误</dt><dd>${escapeHtml(task.error_detail || task.error_code || "-")}</dd>
        <dt>尝试记录</dt><dd>${attemptHtml}</dd>
      </dl>
    `;
    return;
  }

  const transcript = await transcriptForTask(task) || {};
  if (!transcript.segments?.length) {
    els.detail.className = "detail empty";
    els.detail.textContent = transcript.warning || "转写尚未生成。";
    return;
  }
  els.detail.innerHTML = `${mediaSeekDockHtml(task)}${transcriptTimeline(transcript, task)}`;
  bindTaskOverviewActions();
}

async function startUrlTask(mode = "video") {
  const source = renderUrlSourceIdentity();
  const url = source.url;
  if (!source.valid) {
    els.urlInput.focus();
    return;
  }
  const resource = manualUrlResource(url);
  const pagePreflightResource = resource ? null : selectedPagePreflightResource(url);
  const pagePreflightReport = resource ? null : selectedPagePreflightReport(url);
  const resources = resource ? [resource] : pagePreflightResource ? [pagePreflightResource] : [];
  els.startUrlButton.disabled = true;
  if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
  if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
  try {
    const data = await fetchJson(apiUrl("/api/tasks/from-current-page"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        page_url: url,
        title: els.titleInput.value.trim() || source.label || url,
        page_text: "",
        resources,
        page_preflight_report: pagePreflightReport || {},
        cookies: [],
        options: readOptions()
      })
    });
    selectTask(data.task_id);
    await loadTasks();
    focusResultPanelOnMobile();
  } finally {
    els.startUrlButton.disabled = false;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
  }
}

async function preflightUrlTask() {
  const source = renderUrlSourceIdentity();
  const url = source.url;
  if (!source.valid) {
    els.urlInput.focus();
    return;
  }
  if (urlPreflightResourceUrl === url) clearUrlPreflight();
  const resource = manualUrlResource(url);
  if (!resource) {
    els.startUrlButton.disabled = true;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
    els.urlModeHint.textContent = "正在预检页面 URL；后端会扫描页面里的 mp4/m3u8/mpd 线索。";
    renderUrlPagePreflightReport(url, null, "checking");
    try {
      const data = await fetchJson(apiUrl("/api/media/preflight-current-page"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_url: url,
          resources: [],
          cookies: [],
          probe_limit: 3
        })
      });
      const report = rememberUrlPagePreflight(url, data.report || {});
      els.urlModeHint.textContent = report.ready
        ? `页面预检通过：${report.downloadable_count || 1} 个候选可访问，生成笔记时会优先复用已发现资源。`
        : `页面预检未通过：${report.message || report.code || "未发现可直取媒体"}；仍可创建任务交给 yt-dlp 或页面扫描兜底。`;
      renderUrlPagePreflightReport(url, report);
    } finally {
      els.startUrlButton.disabled = false;
      if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
      if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
    }
    return;
  }
  els.startUrlButton.disabled = true;
  if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
  if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
  els.urlModeHint.textContent = "正在预检链接可访问性...";
  renderUrlPreflightReport(resource, { downloadable: false }, "checking");
  try {
    const data = await fetchJson(apiUrl("/api/media/preflight"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_url: url,
        resource,
        cookies: []
      })
    });
    const result = rememberUrlPreflight(resource, data.preflight || {});
    const resolvedTarget = resource.resolved_url && resource.resolved_url !== resource.url
      ? `，目标：${compactUrl(resource.resolved_url, 92)}`
      : "";
    els.urlModeHint.textContent = result.downloadable
      ? `预检通过：${result.kind || resource.kind} 可访问，${result.status_code ? `HTTP ${result.status_code}，` : ""}${fmtBytes(result.content_length) || `${result.bytes_checked || 0} B`}${resolvedTarget}。`
      : `预检未通过：${result.message || result.code || "该链接暂不可直接下载"}`;
    renderUrlPreflightReport(resource, result);
  } finally {
    els.startUrlButton.disabled = false;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
  }
}

async function uploadSelectedFile(fileOverride = null) {
  const file = fileOverride || els.fileInput.files?.[0] || pendingLocalFile;
  if (!file) return;
  pendingLocalFile = file;
  if (!isSupportedLocalVideoFile(file)) {
    els.fileName.textContent = `${file.name} 暂不支持，请选择 mp4 / m4v / mov / flv / avi / mkv / webm 等视频文件`;
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  form.append("options", JSON.stringify(readOptions()));
  els.uploadButton.disabled = true;
  els.uploadButton.textContent = "上传中...";
  try {
    const response = await fetch(apiUrl("/api/tasks/from-local"), { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (response.ok === false || !data?.task_id) {
      els.fileName.textContent = apiErrorMessage(data, "本地视频上传失败，请确认文件格式和后端状态。");
      return;
    }
    selectTask(data.task_id);
    await loadTasks();
    focusResultPanelOnMobile();
  } finally {
    els.uploadButton.disabled = false;
    els.uploadButton.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5M4 17v3h16v-3"/></svg>上传并生成`;
  }
}

els.sourceTabs.forEach(tab => {
  tab.onclick = () => setSource(tab.dataset.source);
});

if (els.sourceRouteRail) {
  els.sourceRouteRail.addEventListener("click", async event => {
    const route = event.target.closest("[data-source-route]");
    if (!route) return;
    setSource(route.dataset.sourceRoute);
    if (route.dataset.taskId) {
      selectTask(route.dataset.taskId);
      renderTasks();
      await renderDetail();
    }
  });
}

if (els.sourceWorkflow) {
  els.sourceWorkflow.addEventListener("click", async event => {
    const button = event.target.closest("[data-select-workflow-task]");
    if (button) {
      selectTask(button.dataset.selectWorkflowTask);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
      return;
    }
    const actionButton = event.target.closest("[data-source-workflow-action]");
    if (!actionButton) return;
    const action = actionButton.dataset.sourceWorkflowAction;
    if (action === "continue-media" && actionButton.dataset.taskId) {
      await rerunTaskFromMedia(actionButton.dataset.taskId);
      return;
    }
    if (action === "refresh-browser") {
      actionButton.disabled = true;
      try {
        await loadTasks();
      } finally {
        actionButton.disabled = false;
      }
      return;
    }
    if (action === "copy-backend") {
      await copyBackendUrl(actionButton);
      return;
    }
    if (action === "open-extension") {
      const url = await copyBackendUrl(actionButton);
      setBrowserExtensionHandoffStatus(url);
      return;
    }
    if (action === "switch-local") {
      setSource("local");
      els.fileInput?.focus?.();
      return;
    }
    if (action === "choose-local") {
      els.fileInput?.click?.();
      return;
    }
    if (action === "upload-local") {
      await uploadSelectedFile();
      return;
    }
    if (action === "open-options") {
      if (els.optionsDisclosure) els.optionsDisclosure.open = true;
      els.optionsDisclosure?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (action === "focus-url") {
      els.urlInput?.focus?.();
      return;
    }
    if (action === "preflight-url") {
      await preflightUrlTask();
      return;
    }
    if (action === "start-url") {
      await startUrlTask("video");
      return;
    }
    if (action === "download-url") {
      await startUrlTask("download_only");
    }
  });
}

if (els.browserRouteSummary) {
  els.browserRouteSummary.addEventListener("click", async event => {
    const selectButton = event.target.closest("[data-select-browser-task]");
    if (selectButton) {
      selectTask(selectButton.dataset.selectBrowserTask);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
      return;
    }
    const rerunButton = event.target.closest("[data-rerun-browser-task]");
    if (rerunButton) {
      await rerunTaskFromMedia(rerunButton.dataset.rerunBrowserTask);
      return;
    }
    const routeAction = event.target.closest("[data-browser-route-action]");
    if (!routeAction) return;
    if (routeAction.dataset.browserRouteAction === "refresh") {
      routeAction.disabled = true;
      try {
        await loadTasks();
      } finally {
        routeAction.disabled = false;
      }
      return;
    }
    if (routeAction.dataset.browserRouteAction === "copy-backend") {
      await copyBackendUrl(routeAction);
      return;
    }
    if (routeAction.dataset.browserRouteAction === "open-extension") {
      await copyBackendUrl(routeAction);
      setBrowserExtensionHandoffStatus(backendDisplayUrl());
      return;
    }
    if (routeAction.dataset.browserRouteAction === "local-video") {
      setSource("local");
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
}

if (els.startupReadiness) {
  els.startupReadiness.addEventListener("click", async event => {
    const button = event.target.closest("[data-startup-action]");
    if (!button) return;
    const action = button.dataset.startupAction;
    if (action === "copy-backend") {
      await copyBackendUrl(button);
      return;
    }
    if (action === "open-options") {
      if (els.optionsDisclosure) els.optionsDisclosure.open = true;
      els.optionsDisclosure?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (action === "browser" || action === "local" || action === "url") {
      setSource(action);
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
}

if (els.urlMode) {
  els.urlMode.onchange = () => {
    clearUrlPreflight();
    renderUrlModeHint();
  };
  renderUrlModeHint();
}
if (els.urlInput) {
  els.urlInput.oninput = () => {
    clearUrlPreflight();
    renderUrlSourceIdentity();
  };
}
if (els.transcriber) {
  els.transcriber.onchange = () => {
    syncTranscriberModelDefault(true);
    saveModelSettings();
    updateHealthVisionStatus();
    updateStartupReadiness();
  };
}
if (els.llmProvider) {
  els.llmProvider.onchange = () => {
    applyModelProviderPreset(true);
    saveModelSettings();
    updateHealthVisionStatus();
    updateStartupReadiness();
  };
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => switchResultTab(tab.dataset.tab);
});

els.startUrlButton.onclick = () => startUrlTask("video");
if (els.preflightUrlButton) els.preflightUrlButton.onclick = preflightUrlTask;
if (els.downloadUrlButton) els.downloadUrlButton.onclick = () => startUrlTask("download_only");
if (els.toggleWorkspaceButton) {
  els.toggleWorkspaceButton.onclick = () => {
    const collapsed = !document.body?.classList?.contains?.("workspace-collapsed");
    setWorkspaceCollapsed(collapsed);
  };
}
if (els.toggleHistoryButton) {
  els.toggleHistoryButton.onclick = () => {
    const collapsed = !document.body?.classList?.contains?.("queue-collapsed");
    setHistoryCollapsed(collapsed);
  };
}
if (els.readingModeButton) {
  els.readingModeButton.onclick = () => {
    const enabled = !document.body?.classList?.contains?.("reading-mode");
    setReadingMode(enabled);
  };
}
els.copyBackendButton.onclick = () => copyBackendUrl(els.copyBackendButton);
els.browserRefreshButton.onclick = () => loadTasks();
els.uploadButton.onclick = uploadSelectedFile;
els.refreshButton.onclick = () => loadTasks();
els.taskSearch.oninput = () => {
  taskQuery = els.taskSearch.value;
  renderTasks();
};
els.statusFilter.onchange = () => {
  taskStatusFilter = els.statusFilter.value;
  renderTasks();
};
els.copyButton.onclick = async () => navigator.clipboard.writeText(await noteForTask(selectedTaskId) || "");
if (els.continueFromMediaButton) els.continueFromMediaButton.onclick = () => rerunTaskFromMedia(selectedTaskId);
els.bundleButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/bundle`));
};
if (els.manifestButton) {
  els.manifestButton.onclick = () => {
    if (!selectedTaskId) return;
    window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/manifest`));
  };
}
els.diagnosticsButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/diagnostics`));
};
if (els.visualWindowsButton) {
  els.visualWindowsButton.onclick = () => {
    if (!selectedTaskId) return;
    window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/visual-windows`));
  };
}
if (els.subtitlesButton) {
  els.subtitlesButton.onclick = () => {
    if (!selectedTaskId) return;
    window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/subtitles`));
  };
}
els.mediaButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/media`));
};
els.downloadButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/markdown`));
};

els.dropzone.addEventListener("dragover", event => {
  event.preventDefault();
  els.dropzone.classList.add("drag");
});
els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("drag"));
els.dropzone.addEventListener("drop", event => {
  event.preventDefault();
  els.dropzone.classList.remove("drag");
  if (event.dataTransfer.files?.[0]) {
    pendingLocalFile = event.dataTransfer.files[0];
    els.fileName.textContent = pendingLocalFile.name;
    setSource("local");
    uploadSelectedFile(pendingLocalFile);
  }
});

els.fileInput.onchange = () => {
  pendingLocalFile = els.fileInput.files?.[0] || null;
  els.fileName.textContent = pendingLocalFile?.name || "mp4 / flv / avi / webm / mov / mkv";
  setSource("local");
};

[
  els.frameInterval,
  els.gridSize,
  els.visualUnderstanding,
  els.noteStyle,
  els.noteTemplate,
  els.summaryDepth,
  els.llmProvider,
  els.transcriber,
  els.whisperModel
].filter(Boolean).forEach(control => {
  control.addEventListener("change", () => {
    refreshOptionDependentUi();
    if ([els.llmProvider, els.transcriber, els.whisperModel].includes(control)) saveModelSettings();
  });
});
els.llmModel?.addEventListener("input", () => {
  updateHealthVisionStatus();
  updateStartupReadiness();
  saveModelSettings();
});
els.llmBaseUrl?.addEventListener("input", () => {
  updateHealthVisionStatus();
  updateStartupReadiness();
  saveModelSettings();
});
els.llmApiKey?.addEventListener("input", () => {
  updateHealthVisionStatus();
  updateStartupReadiness();
});

initializeResponsiveChrome();
loadModelSettings();
applyModelProviderPreset(false);
updateModelProviderHint();
initializeWorkspaceView();
renderSourceWorkflow();
checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks();
}, 3000);
