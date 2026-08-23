const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
const PROTOCOL_VERSION = 1;
const HEALTH_TIMEOUT_MS = 2200;
const REQUEST_TIMEOUT_MS = 20000;
const PASSIVE_REFRESH_DELAY_MS = 450;
const PREFLIGHT_TTL_MS = 30000;
const CLIENT_TAB_ACTIVATION_SUPPRESS_MS = 3000;
const LOCAL_BACKEND_RE = /^http:\/\/(?:127\.0\.0\.1|localhost)(?::\d{1,5})?\/?$/i;
const MEDIA_KIND_RE = /^(?:video|media|mp4|hls|dash|manifest|playlist)$/i;
const AUDIO_KIND_RE = /audio/i;
const SUBTITLE_KIND_RE = /subtitle|caption|vtt|srt/i;
const HAS_EXTENSION_API = typeof chrome !== "undefined" && Boolean(chrome.runtime?.sendMessage && chrome.storage?.local);

const els = {
  connectionCard: document.querySelector("#connectionCard"),
  connectionTitle: document.querySelector("#connectionTitle"),
  connectionDetail: document.querySelector("#connectionDetail"),
  openClientButton: document.querySelector("#openClientButton"),
  openClientBrand: document.querySelector("#openClientBrand"),
  refreshButton: document.querySelector("#refreshButton"),
  platformLabel: document.querySelector("#platformLabel"),
  playingBadge: document.querySelector("#playingBadge"),
  videoTitle: document.querySelector("#videoTitle"),
  videoMeta: document.querySelector("#videoMeta"),
  integrityGrid: document.querySelector("#integrityGrid"),
  candidateCount: document.querySelector("#candidateCount"),
  durationValue: document.querySelector("#durationValue"),
  estimateValue: document.querySelector("#estimateValue"),
  preflightMessage: document.querySelector("#preflightMessage"),
  sendButton: document.querySelector("#sendButton"),
  sendButtonLabel: document.querySelector("#sendButtonLabel"),
  handoffProgress: document.querySelector("#handoffProgress"),
  handoffStatus: document.querySelector("#handoffStatus"),
  handoffPercent: document.querySelector("#handoffPercent"),
  openTaskButton: document.querySelector("#openTaskButton"),
  quickResultCard: document.querySelector("#quickResultCard"),
  quickResultStatus: document.querySelector("#quickResultStatus"),
  quickDeepButton: document.querySelector("#quickDeepButton"),
  quickSummaryPanel: document.querySelector("#quickSummaryPanel"),
  quickTranscriptPanel: document.querySelector("#quickTranscriptPanel"),
  quickAskPanel: document.querySelector("#quickAskPanel"),
  quickAskConversation: document.querySelector("#quickAskConversation"),
  quickAskForm: document.querySelector("#quickAskForm"),
  quickAskQuestion: document.querySelector("#quickAskQuestion")
};

let backendUrl = DEFAULT_BACKEND_URL;
let clientConnected = false;
let currentContext = null;
let displayedIdentity = null;
let preflightReport = null;
let preflightIdentity = null;
let currentTaskId = "";
let sending = false;
let refreshTimer = 0;
let contextGeneration = 0;
let collectRequest = null;
let preflightRequest = null;
let preflightAt = 0;
let preflightFingerprint = "";
let activeHandoff = null;
let suppressTabActivationUntil = 0;
let currentTaskMode = "";
let quickPollTimer = 0;
let quickTranscript = [];
let selectedProcessingMode = "quick";

function processingOptions(mode = selectedProcessingMode) {
  if (mode === "deep") return { visual_understanding: true, frame_interval: 20, grid_columns: 3, grid_rows: 3, note_style: "lecture", note_template: "visual-handout", summary_depth: "deep" };
  if (mode === "study") return { visual_understanding: false, note_style: "classroom-review", note_template: "standard", summary_depth: "standard" };
  return { visual_understanding: false, note_style: "quick-summary", note_template: "timeline", summary_depth: "brief" };
}

function setProcessingMode(mode = "quick") {
  selectedProcessingMode = ["quick", "study", "deep"].includes(mode) ? mode : "quick";
  document.querySelectorAll?.("[data-processing-mode]").forEach(button => {
    const active = button.dataset.processingMode === selectedProcessingMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  renderContext();
}

function subtitleCues(context = currentContext) {
  return (context?.page?.browser_subtitles || [])
    .map(item => ({ start: Number(item?.start || 0), end: Number(item?.end || item?.start || 0), text: String(item?.text || "").trim() }))
    .filter(item => item.text && Number.isFinite(item.start) && Number.isFinite(item.end) && item.end >= item.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
}

function hasReliableBrowserSubtitles(context = currentContext) {
  const cues = subtitleCues(context);
  if (cues.length < 8) return false;
  const duration = Number(context?.page?.active_video?.duration || 0);
  const span = Math.max(0, cues[cues.length - 1].end - cues[0].start);
  if (duration > 0) return span / duration >= 0.55;
  return span >= 45;
}

function escapeQuickHtml(value = "") {
  return String(value).replace(/[&<>\"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]);
}

function renderQuickMarkdown(markdown = "") {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let list = false;
  const closeList = () => { if (list) { html.push("</ul>"); list = false; } };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (heading) { closeList(); html.push(`<h${heading[1].length}>${escapeQuickHtml(heading[2])}</h${heading[1].length}>`); continue; }
    if (bullet) { if (!list) { html.push("<ul>"); list = true; } html.push(`<li>${escapeQuickHtml(bullet[1])}</li>`); continue; }
    closeList();
    html.push(`<p>${escapeQuickHtml(line).replace(/`([^`]+)`/g, "<code>$1</code>")}</p>`);
  }
  closeList();
  return html.join("") || "<p>正在等待速记结果…</p>";
}

function formatCueTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function stopQuickPolling() {
  if (quickPollTimer) clearInterval(quickPollTimer);
  quickPollTimer = 0;
}

function showQuickResult(status = "正在生成字幕速记…") {
  if (!els.quickResultCard) return;
  els.quickResultCard.hidden = false;
  if (els.quickResultStatus) els.quickResultStatus.textContent = status;
}

function renderQuickTranscript(cues = quickTranscript) {
  if (!els.quickTranscriptPanel) return;
  els.quickTranscriptPanel.innerHTML = cues.length
    ? cues.map(cue => `<button type="button" class="quick-transcript-cue" data-seek-time="${Number(cue.start).toFixed(3)}"><time>${formatCueTime(cue.start)}</time><span>${escapeQuickHtml(cue.text)}</span></button>`).join("")
    : "<p>字幕尚未读取。</p>";
  els.quickTranscriptPanel.querySelectorAll?.("[data-seek-time]").forEach(button => {
    button.addEventListener("click", async () => {
      if (!HAS_EXTENSION_API || !displayedIdentity?.tab_id) return;
      await chrome.runtime.sendMessage({ type: "seek-current-video", targetTabId: displayedIdentity.tab_id, seconds: Number(button.dataset.seekTime) });
    });
  });
}

function setQuickTab(tabName = "summary") {
  document.querySelectorAll?.("[data-quick-tab]").forEach(button => {
    const active = button.dataset.quickTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll?.("[data-quick-panel]").forEach(panel => {
    panel.hidden = panel.dataset.quickPanel !== tabName;
  });
}

async function fetchQuickTask(taskId = currentTaskId) {
  const response = await fetchWithTimeout(`${backendUrl}/api/tasks/${encodeURIComponent(taskId)}`);
  if (!response.ok) throw new Error(`任务查询失败（HTTP ${response.status}）`);
  return response.json();
}

async function loadQuickArtifacts(task) {
  const [noteResponse, transcriptResponse] = await Promise.all([
    fetchWithTimeout(`${backendUrl}/api/tasks/${encodeURIComponent(task.id)}/note`),
    fetchWithTimeout(`${backendUrl}/api/tasks/${encodeURIComponent(task.id)}/transcript`)
  ]);
  const note = noteResponse.ok ? await noteResponse.text() : "";
  const transcript = transcriptResponse.ok ? await transcriptResponse.json() : {};
  quickTranscript = Array.isArray(transcript?.segments) ? transcript.segments : [];
  if (els.quickSummaryPanel) els.quickSummaryPanel.innerHTML = renderQuickMarkdown(note);
  renderQuickTranscript(quickTranscript);
  showQuickResult(task.summary_warning ? `速记完成 · ${task.summary_warning}` : "速记完成 · 未下载视频或分析画面");
}

async function pollQuickTask() {
  if (!currentTaskId || currentTaskMode !== "subtitle_only") return;
  try {
    const payload = await fetchQuickTask(currentTaskId);
    const task = payload?.task || payload;
    if (task.status === "failed" || task.status === "cancelled") {
      stopQuickPolling();
      showQuickResult(task.error_detail || task.message || "字幕速记失败，请改用深度图文模式");
      if (els.quickSummaryPanel) els.quickSummaryPanel.innerHTML = `<p>${escapeQuickHtml(task.error_detail || task.message || "字幕速记失败")}</p>`;
      return;
    }
    showQuickResult(task.note_path ? "正在载入速记结果…" : (task.message || "正在生成字幕速记…"));
    if (task.note_path && task.status === "success") {
      stopQuickPolling();
      await loadQuickArtifacts(task);
      setProgress(100, "字幕速记已完成，可继续深度图文学习。", "success");
    }
  } catch (error) {
    showQuickResult(error?.message || "正在等待本地服务响应…");
  }
}

function startQuickPolling() {
  stopQuickPolling();
  pollQuickTask();
  quickPollTimer = setInterval(pollQuickTask, 1200);
}

function withTimeout(promise, timeoutMs, label) {
  let timer = 0;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label}超时`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function normalizedBackendUrl(value) {
  const candidate = String(value || "").trim().replace(/\/$/, "");
  return LOCAL_BACKEND_RE.test(candidate) ? candidate : DEFAULT_BACKEND_URL;
}

function canonicalPageUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    url.hostname = url.hostname.toLowerCase();
    const keep = new Set(["v", "p", "list", "index", "courseId", "clazzid", "knowledgeId", "chapterId", "objectid"]);
    for (const key of [...url.searchParams.keys()]) {
      if (!keep.has(key)) url.searchParams.delete(key);
    }
    if ((url.protocol === "https:" && url.port === "443") || (url.protocol === "http:" && url.port === "80")) url.port = "";
    url.pathname = url.pathname.replace(/\/{2,}/g, "/");
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/$/, "");
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0].trim();
  }
}

function hostnameMatches(hostname = "", domain = "") {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  const root = String(domain || "").toLowerCase().replace(/\.$/, "");
  return host === root || host.endsWith(`.${root}`);
}

function platformIdentity(urlValue = "", page = {}) {
  const url = String(urlValue || "");
  const bilibili = /(?:bilibili\.com\/video\/|b23\.tv\/)(BV[0-9A-Za-z]+)/i.exec(url);
  if (bilibili) return { platform: "bilibili", platformVideoId: bilibili[1], label: "哔哩哔哩" };
  try {
    const parsed = new URL(url);
    if (hostnameMatches(parsed.hostname, "youtube.com") || hostnameMatches(parsed.hostname, "youtu.be")) {
      const id = hostnameMatches(parsed.hostname, "youtu.be") ? parsed.pathname.split("/").filter(Boolean)[0] : parsed.searchParams.get("v");
      return { platform: "youtube", platformVideoId: id || "", label: "YouTube" };
    }
    if (hostnameMatches(parsed.hostname, "chaoxing.com") || /xuexitong/i.test(parsed.hostname)) {
      const active = page.active_video || {};
      const id = parsed.searchParams.get("objectid") || parsed.searchParams.get("knowledgeId") || active.objectid || page.objectid || "";
      return { platform: "chaoxing", platformVideoId: String(id), label: "学习通 / 超星" };
    }
    return { platform: parsed.hostname.replace(/^www\./, "") || "web", platformVideoId: "", label: parsed.hostname.replace(/^www\./, "") || "当前页面" };
  } catch {
    return { platform: "web", platformVideoId: "", label: "当前页面" };
  }
}

function stableMediaUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    const volatile = /^(?:token|sign|signature|expires?|deadline|auth|auth_key|wsSecret|wsTime|timestamp|ts|t|rnd|random|callback)$/i;
    for (const key of [...url.searchParams.keys()]) {
      if (volatile.test(key)) url.searchParams.delete(key);
    }
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0];
  }
}

function fnv1a(value = "") {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function resourceFingerprint(page = {}, resources = []) {
  const stable = [];
  const active = page.active_video || {};
  const activeSrc = active.current_src || active.currentSrc || active.src || "";
  if (activeSrc) stable.push(`active:${stableMediaUrl(activeSrc)}`);
  const ranked = [...(resources || [])]
    .filter(item => item?.url && !SUBTITLE_KIND_RE.test(String(item.kind || "")))
    .sort((left, right) => Number(right.score || 0) - Number(left.score || 0));
  for (const item of ranked) {
    const url = stableMediaUrl(item.resolved_url || item.url);
    if (!url) continue;
    const kind = String(item.kind || "media").toLowerCase();
    const key = `${kind}:${url}`;
    if (!stable.includes(key)) stable.push(key);
    if (stable.length >= 12) break;
  }
  return fnv1a(stable.sort().join("\n") || "no-media");
}

function buildSourceIdentity(context, capturedAt = Date.now()) {
  const tab = context?.tab || {};
  const page = context?.page || {};
  const pageUrl = page.page_url || tab.url || "";
  const platform = platformIdentity(pageUrl, page);
  const active = page.active_video || {};
  const pageTitle = String(page.title || tab.title || "").trim();
  const activeCurrentSrc = String(active.current_src || active.currentSrc || active.src || "").trim();
  return {
    tab_id: Number.isFinite(Number(tab.id)) ? Number(tab.id) : null,
    canonical_page_url: canonicalPageUrl(pageUrl),
    platform: platform.platform,
    platform_video_id: platform.platformVideoId,
    BVID: platform.platform === "bilibili" ? platform.platformVideoId : "",
    page_title: pageTitle,
    active_video: { current_src: activeCurrentSrc },
    resource_fingerprint: resourceFingerprint(page, context?.resources || []),
    captured_at: new Date(capturedAt).toISOString()
  };
}

function sourceIdentityKey(identity = {}) {
  return [
    identity.tab_id ?? "",
    identity.canonical_page_url || "",
    identity.platform || "",
    identity.platform_video_id || identity.BVID || "",
    identity.page_title || "",
    identity.active_video?.current_src || "",
    identity.resource_fingerprint || ""
  ].join("\u001f");
}

function sourceContinuityKey(identity = {}) {
  return [
    identity.tab_id ?? "",
    identity.canonical_page_url || "",
    identity.platform || "",
    identity.platform_video_id || identity.BVID || "",
    stableMediaUrl(identity.active_video?.current_src || "")
  ].join("\u001f");
}

function sameSourceIdentity(left, right) {
  if (!left || !right) return false;
  const leftTab = Number(left.tab_id);
  const rightTab = Number(right.tab_id);
  if (Number.isFinite(leftTab) && Number.isFinite(rightTab) && leftTab !== rightTab) return false;
  if (left.canonical_page_url && right.canonical_page_url && left.canonical_page_url !== right.canonical_page_url) return false;
  const leftVideoId = String(left.platform_video_id || left.BVID || "");
  const rightVideoId = String(right.platform_video_id || right.BVID || "");
  if (leftVideoId && rightVideoId && leftVideoId !== rightVideoId) return false;
  const leftSrc = stableMediaUrl(left.active_video?.current_src || "");
  const rightSrc = stableMediaUrl(right.active_video?.current_src || "");
  if (!leftVideoId && !rightVideoId && leftSrc && rightSrc && leftSrc !== rightSrc) return false;
  return Boolean(left.canonical_page_url || right.canonical_page_url || leftVideoId || rightVideoId || leftSrc || rightSrc);
}

function resetSourceState() {
  stopQuickPolling();
  preflightReport = null;
  preflightIdentity = null;
  preflightAt = 0;
  preflightFingerprint = "";
  preflightRequest = null;
  activeHandoff = null;
  currentTaskId = "";
  currentTaskMode = "";
  quickTranscript = [];
  if (els.quickResultCard) els.quickResultCard.hidden = true;
  els.openTaskButton.hidden = true;
  els.sendButtonLabel.textContent = "发送到客户端";
}

function preflightCacheKey(identity = displayedIdentity) {
  return `${sourceContinuityKey(identity)}\u001f${identity?.resource_fingerprint || ""}`;
}

function hasFreshPreflight(identity = displayedIdentity) {
  return Boolean(
    preflightReport
    && preflightIdentity
    && sameSourceIdentity(preflightIdentity, identity)
    && preflightFingerprint === preflightCacheKey(identity)
    && Date.now() - preflightAt < PREFLIGHT_TTL_MS
  );
}

function handoffId(identity = displayedIdentity) {
  const sourceKey = sourceContinuityKey(identity);
  if (activeHandoff?.sourceKey === sourceKey) return activeHandoff.id;
  const id = `ln-${fnv1a(sourceKey)}-${Date.now().toString(36)}`;
  activeHandoff = { sourceKey, id };
  return id;
}

function mediaCandidates(context = currentContext) {
  return (context?.resources || []).filter(item => {
    const kind = String(item?.kind || "");
    if (SUBTITLE_KIND_RE.test(kind)) return false;
    return MEDIA_KIND_RE.test(kind) || AUDIO_KIND_RE.test(kind) || /\.(?:mp4|m3u8|mpd|m4s|ts)(?:$|[?#])/i.test(String(item?.url || ""));
  });
}

function formatDuration(seconds) {
  const total = Math.round(Number(seconds || 0));
  if (!Number.isFinite(total) || total <= 0) return "--";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remain = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}` : `${minutes}:${String(remain).padStart(2, "0")}`;
}

function explicitIntegrity(report = preflightReport) {
  const raw = report?.integrity || report?.media_integrity || report?.stream_integrity || {};
  const explicit = key => typeof raw[key] === "boolean" ? raw[key] : null;
  return {
    video: explicit("video") ?? explicit("has_video"),
    audio: explicit("audio") ?? explicit("has_audio"),
    subtitle: explicit("subtitle") ?? explicit("has_subtitle")
  };
}

function integrityEvidence(context = currentContext, report = preflightReport) {
  const page = context?.page || {};
  const active = page.active_video || {};
  const candidates = context?.resources || [];
  const explicit = explicitIntegrity(report);
  const videoEvidence = Boolean(active.current_src || active.currentSrc || active.src || active.src_object_video_tracks > 0 || candidates.some(item => {
    const kind = String(item?.kind || "");
    return !AUDIO_KIND_RE.test(kind) && !SUBTITLE_KIND_RE.test(kind) && (MEDIA_KIND_RE.test(kind) || /\.(?:mp4|m3u8|mpd|m4s)(?:$|[?#])/i.test(String(item?.url || "")));
  }));
  const audioEvidence = Boolean(
    active.has_audio === true ||
    Number(active.src_object_audio_tracks || 0) > 0 ||
    Number(active.capture_stream_audio_tracks || 0) > 0 ||
    Number(active.audio_decoded_byte_count || 0) > 0 ||
    candidates.some(item => AUDIO_KIND_RE.test(String(item?.kind || "")) || /^audio\//i.test(String(item?.mime || item?.content_type || "")))
  );
  const subtitleEvidence = Boolean((page.browser_subtitles || []).length || candidates.some(item => SUBTITLE_KIND_RE.test(String(item?.kind || item?.mime || item?.content_type || ""))));
  return {
    video: explicit.video === null ? (videoEvidence ? true : null) : explicit.video,
    audio: explicit.audio === null ? (audioEvidence ? true : null) : explicit.audio,
    subtitle: explicit.subtitle === null ? (subtitleEvidence ? true : null) : explicit.subtitle
  };
}

function setIntegrityItem(kind, value) {
  const item = els.integrityGrid?.querySelector(`[data-kind="${kind}"]`);
  if (!item) return;
  const label = value === true ? "已检测" : value === false ? "未发现" : "未确认";
  item.dataset.state = value === true ? "found" : value === false ? "missing" : "unknown";
  const strong = item.querySelector("strong");
  if (strong) strong.textContent = label;
}

function renderContext(message = "") {
  const page = currentContext?.page || {};
  const tab = currentContext?.tab || {};
  const active = page.active_video || {};
  const identity = currentContext ? buildSourceIdentity(currentContext) : null;
  const platform = platformIdentity(page.page_url || tab.url || "", page);
  const candidates = mediaCandidates();
  const subtitleReady = hasReliableBrowserSubtitles(currentContext);
  const title = identity?.page_title || "未识别到视频页面";
  const duration = Number(active.duration || 0);
  const playing = Boolean(active && active.paused === false && (active.src || active.src_object));
  const evidence = integrityEvidence();

  els.platformLabel.textContent = platform.label;
  els.videoTitle.textContent = title;
  els.videoMeta.textContent = identity?.platform_video_id
    ? `${identity.platform_video_id} · ${identity.canonical_page_url}`
    : (identity?.canonical_page_url || "请打开视频页面并开始播放");
  els.playingBadge.hidden = !playing;
  els.candidateCount.textContent = String(candidates.length);
  els.durationValue.textContent = formatDuration(duration);
  els.estimateValue.textContent = selectedProcessingMode === "quick" && subtitleReady ? "字幕速记 10–30 秒" : (candidates.length || active.src ? "按视频时长估算" : "--");
  setIntegrityItem("video", evidence.video);
  setIntegrityItem("audio", evidence.audio);
  setIntegrityItem("subtitle", evidence.subtitle);

  const hasPage = Boolean(identity?.canonical_page_url && !/^(?:chrome|edge|about):/i.test(identity.canonical_page_url));
  const hasMediaEvidence = evidence.video === true || candidates.length > 0;
  const alreadySent = Boolean(currentTaskId && activeHandoff?.sourceKey === sourceContinuityKey(identity));
  const quickUnavailable = selectedProcessingMode === "quick" && !subtitleReady;
  els.sendButton.disabled = sending || alreadySent || !clientConnected || !hasPage || (quickUnavailable && !hasMediaEvidence) || (!quickUnavailable && !hasMediaEvidence);
  els.sendButtonLabel.textContent = currentTaskId
    ? (currentTaskMode === "subtitle_only" ? "速记已开始" : "已发送到客户端")
    : selectedProcessingMode === "quick" ? (subtitleReady ? "快速生成字幕速记" : "快速速览需要完整字幕")
      : selectedProcessingMode === "study" ? "开始标准学习" : "开始深度图文";
  if (message) {
    els.preflightMessage.textContent = message;
  } else if (!hasPage) {
    els.preflightMessage.textContent = "请切换到正在播放视频的页面。";
  } else if (selectedProcessingMode === "quick" && subtitleReady) {
    els.preflightMessage.textContent = "已取得覆盖充分的浏览器字幕，可以直接生成速览；不会下载视频、调用 ASR 或分析画面。";
  } else if (selectedProcessingMode === "quick") {
    els.preflightMessage.textContent = "当前字幕覆盖不足；请选择标准学习使用 ASR，或选择深度图文分析视频。";
  } else if (!hasMediaEvidence) {
    els.preflightMessage.textContent = "还没有检测到播放器或媒体候选，请播放几秒后重新识别。";
  } else if (preflightReport?.ready || preflightReport?.downloadable_count > 0) {
    els.preflightMessage.textContent = preflightReport.message || "视频来源预检通过，可以发送到客户端。";
  } else if (preflightReport) {
    els.preflightMessage.textContent = preflightReport.message || "已检测到媒体候选，客户端将在接收后继续解析。";
  } else {
    els.preflightMessage.textContent = `已检测到 ${candidates.length || 1} 个媒体候选。声音和字幕只在有直接证据时标记。`;
  }
}

function setConnection(state, title, detail) {
  clientConnected = state === "connected";
  els.connectionCard.dataset.state = state;
  els.connectionTitle.textContent = title;
  els.connectionDetail.textContent = detail;
  renderContext();
}

function setProgress(value, message, state = "active") {
  const progress = Math.max(0, Math.min(100, Math.round(Number(value || 0))));
  els.handoffProgress.hidden = false;
  els.handoffPercent.hidden = false;
  els.handoffProgress.dataset.state = state;
  els.handoffProgress.setAttribute("aria-valuenow", String(progress));
  const bar = els.handoffProgress.querySelector("span");
  if (bar) bar.style.width = `${progress}%`;
  els.handoffPercent.textContent = `${progress}%`;
  els.handoffStatus.textContent = message;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let timer = 0;
  if (controller) timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, ...(controller ? { signal: controller.signal } : {}) });
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function loadBackendUrl() {
  if (!HAS_EXTENSION_API) return;
  const stored = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND_URL });
  backendUrl = normalizedBackendUrl(stored.backendUrl);
}

async function checkClient() {
  setConnection("checking", "正在连接客户端", backendUrl);
  try {
    const response = await fetchWithTimeout(`${backendUrl}/health`, {}, HEALTH_TIMEOUT_MS);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const health = await response.json();
    setConnection("connected", "客户端已连接", health.app_version ? `LearnNote ${health.app_version} · ${backendUrl}` : backendUrl);
    return true;
  } catch {
    setConnection("offline", "客户端未连接", "先打开 LearnNote，再重新识别当前视频");
    return false;
  }
}

async function collectContext(force = true, targetTabId = null) {
  if (!HAS_EXTENSION_API) {
    renderContext("请在 Chrome 或 Edge 的 LearnNote 扩展中识别当前视频。");
    return null;
  }
  const requestedTabId = targetTabId ?? currentContext?.tab?.id ?? null;
  if (collectRequest?.targetTabId === requestedTabId) return collectRequest.promise;
  const generation = ++contextGeneration;
  els.refreshButton.disabled = true;
  const promise = (async () => {
   try {
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "get-current-context",
      targetTabId: requestedTabId,
      useCached: !force
    }), REQUEST_TIMEOUT_MS, "读取当前页面");
    if (generation !== contextGeneration) return currentContext;
    if (response?.error) throw new Error(response.error);
    const next = {
      tab: response?.tab || {},
      page: response?.page || {},
      resources: Array.isArray(response?.resources) ? response.resources : []
    };
    const nextIdentity = buildSourceIdentity(next);
    const changed = displayedIdentity && !sameSourceIdentity(displayedIdentity, nextIdentity);
    currentContext = next;
    displayedIdentity = nextIdentity;
    if (changed) {
      resetSourceState();
    }
    renderContext(changed ? "页面或播放内容已切换，旧预检已清除。请确认后再发送。" : "");
    return next;
  } catch (error) {
    els.preflightMessage.dataset.state = "error";
    renderContext(`识别失败：${error?.message || "请刷新页面后重试"}`);
    return null;
  } finally {
    if (generation === contextGeneration) {
      collectRequest = null;
      els.refreshButton.disabled = false;
    }
  }
  })();
  collectRequest = { targetTabId: requestedTabId, promise };
  return promise;
}

async function runPreflight(identity = displayedIdentity) {
  if (!clientConnected || !currentContext || !identity) return null;
  if (selectedProcessingMode === "quick" && hasReliableBrowserSubtitles(currentContext)) return null;
  const candidates = mediaCandidates(currentContext);
  if (!candidates.length && !currentContext.page?.active_video) return null;
  if (hasFreshPreflight(identity)) return preflightReport;
  const requestKey = preflightCacheKey(identity);
  if (preflightRequest?.key === requestKey) return preflightRequest.promise;
  const promise = (async () => {
   try {
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "preflight-current-page",
      backendUrl,
      targetTabId: identity.tab_id,
      page: currentContext.page,
      resources: candidates,
      sourceIdentity: identity,
      probeLimit: 3
    }), REQUEST_TIMEOUT_MS, "媒体预检");
    if (response?.error) throw new Error(response.error);
    if (!sameSourceIdentity(identity, displayedIdentity)) return null;
    preflightReport = response?.report || null;
    preflightIdentity = identity;
    preflightAt = Date.now();
    preflightFingerprint = requestKey;
    els.preflightMessage.dataset.state = preflightReport?.ready ? "ready" : "info";
    renderContext();
    return preflightReport;
  } catch (error) {
    if (sameSourceIdentity(identity, displayedIdentity)) {
      els.preflightMessage.dataset.state = "error";
      renderContext(`已检测到媒体候选，但下载预检暂不可用：${error?.message || "客户端将继续检查"}`);
    }
    return null;
  } finally {
    if (preflightRequest?.key === requestKey) preflightRequest = null;
  }
  })();
  preflightRequest = { key: requestKey, promise };
  return promise;
}

async function refreshAndPreflight({ force = true } = {}) {
  els.preflightMessage.dataset.state = "info";
  els.preflightMessage.textContent = "正在读取播放器和媒体请求...";
  const context = await collectContext(force);
  if (context && clientConnected && !(selectedProcessingMode === "quick" && hasReliableBrowserSubtitles(context))) await runPreflight(displayedIdentity);
  return context;
}

function pageSwitchMessage() {
  return "页面或播放内容已切换，已丢弃旧预检结果。请确认当前视频后重新发送。";
}

async function sendToClient(modeOverride = "") {
  if (sending || !displayedIdentity) return false;
  sending = true;
  els.sendButton.disabled = true;
  els.sendButton.setAttribute("aria-busy", "true");
  els.sendButtonLabel.textContent = "正在发送...";
  els.openTaskButton.hidden = true;
  const expectedIdentity = displayedIdentity;
  try {
    setProgress(8, "正在连接 LearnNote...");
    if (!clientConnected && !(await checkClient())) throw new Error("客户端未运行，请先打开 LearnNote");

    setProgress(24, "正在重新读取当前页面...");
    const fresh = await collectContext(true);
    if (!fresh) throw new Error("无法读取当前页面");
    const freshIdentity = buildSourceIdentity(fresh);
    if (!sameSourceIdentity(expectedIdentity, freshIdentity)) {
      displayedIdentity = freshIdentity;
      resetSourceState();
      renderContext(pageSwitchMessage());
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    const requestedMode = modeOverride === "video" ? "deep" : (modeOverride || selectedProcessingMode);
    const effectiveMode = requestedMode === "quick" && !hasReliableBrowserSubtitles(fresh) ? "study" : requestedMode;
    const quick = effectiveMode === "quick";
    if (quick) {
      currentTaskMode = "subtitle_only";
      setProgress(48, "已取得完整字幕，跳过媒体预检和视频处理...");
      const response = await withTimeout(chrome.runtime.sendMessage({
        type: "start-current-task",
        backendUrl,
        targetTabId: freshIdentity.tab_id,
        page: fresh.page,
        resources: [],
        sourceIdentity: freshIdentity,
        handoffId: handoffId(freshIdentity),
        defer: false,
        mode: "subtitle_only",
        options: processingOptions("quick")
      }), REQUEST_TIMEOUT_MS, "创建字幕速记任务");
      if (response?.error) throw new Error(response.error);
      currentTaskId = String(response?.task_id || "");
      if (!currentTaskId) throw new Error("客户端未确认字幕速记任务");
      els.openTaskButton.hidden = false;
      showQuickResult("正在生成字幕速记…");
      setQuickTab("summary");
      startQuickPolling();
      setProgress(72, "字幕已交给本地服务，正在生成速览...");
      return true;
    }

    setProgress(48, hasFreshPreflight(freshIdentity) ? "已复用刚刚的媒体预检" : "正在校验媒体完整性...");
    if (!hasFreshPreflight(freshIdentity)) await runPreflight(freshIdentity);
    if (!sameSourceIdentity(freshIdentity, displayedIdentity)) {
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    currentTaskMode = "video";
    const videoHandoffId = effectiveMode === "deep" && activeHandoff?.sourceKey === sourceContinuityKey(freshIdentity)
      ? (activeHandoff = null, handoffId(freshIdentity))
      : handoffId(freshIdentity);
    setProgress(76, "正在发送视频来源到客户端...");
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "start-current-task",
      backendUrl,
      targetTabId: freshIdentity.tab_id,
      page: fresh.page,
      resources: mediaCandidates(fresh),
      pagePreflightReport: sameSourceIdentity(preflightIdentity, freshIdentity) ? preflightReport : null,
      sourceIdentity: freshIdentity,
      handoffId: videoHandoffId,
      defer: true,
      mode: "video",
      options: processingOptions(effectiveMode)
    }), REQUEST_TIMEOUT_MS, "发送到客户端");
    if (response?.error) throw new Error(response.error);
    currentTaskId = String(response?.task_id || "");
    if (!currentTaskId) throw new Error("客户端未确认任务创建，请重试");
    setProgress(92, response?.deduplicated ? "任务已存在，正在打开客户端..." : "任务已创建，正在打开客户端...");
    els.openTaskButton.hidden = !currentTaskId;
    const opened = await openClient("task", currentTaskId, "note");
    setProgress(100, opened ? "任务已创建，并已在客户端打开。" : "任务已创建；点击下方按钮打开。", "success");
    return true;
  } catch (error) {
    setProgress(Number(els.handoffProgress.getAttribute("aria-valuenow") || 0), error?.message || "发送失败，请重试", "error");
    return false;
  } finally {
    sending = false;
    els.sendButton.setAttribute("aria-busy", "false");
    els.sendButtonLabel.textContent = currentTaskMode === "subtitle_only"
      ? (currentTaskId ? "速记已开始" : "重试速记")
      : (currentTaskId ? "已发送到客户端" : "重试发送");
    const preservedMessage = els.preflightMessage.textContent;
    renderContext(preservedMessage);
  }
}

function clientUrl(view = "workspace", taskId = "", tab = "note") {
  const url = new URL(`${backendUrl}/`);
  if (taskId) {
    url.searchParams.set("task", taskId);
    url.searchParams.set("tab", tab);
  } else if (view && view !== "workspace") {
    url.searchParams.set("view", view);
  }
  return url.href;
}

async function openClient(view = "workspace", taskId = "", tab = "note") {
  const targetUrl = clientUrl(view, taskId, tab);
  if (clientConnected) {
    try {
      const response = await fetchWithTimeout(`${backendUrl}/api/desktop/focus`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId, tab, view })
      }, HEALTH_TIMEOUT_MS);
      const result = await response.json().catch(() => ({}));
      if (result?.ok && result?.available) return true;
    } catch {
      // The browser workbench is the fallback when the desktop bridge is unavailable.
    }
  }
  try {
    if (!HAS_EXTENSION_API || !chrome.tabs?.create) throw new Error("extension API unavailable");
    suppressTabActivationUntil = Date.now() + CLIENT_TAB_ACTIVATION_SUPPRESS_MS;
    await chrome.tabs.create({ url: targetUrl });
    return true;
  } catch {
    return Boolean(window.open?.(targetUrl, "_blank", "noopener"));
  }
}

function scheduleRefresh(reason = "media", targetTabId = null) {
  if (sending) return;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    refreshTimer = 0;
    const previous = displayedIdentity;
    const context = await collectContext(reason === "tab-activated", targetTabId);
    if (context && previous && !sameSourceIdentity(previous, displayedIdentity)) {
      els.handoffStatus.textContent = "已识别新的播放内容";
    }
  }, PASSIVE_REFRESH_DELAY_MS);
}

function bindEvents() {
  els.refreshButton?.addEventListener("click", () => refreshAndPreflight({ force: true }));
  els.sendButton?.addEventListener("click", sendToClient);
  els.quickDeepButton?.addEventListener("click", () => { setProcessingMode("deep"); sendToClient("video"); });
  document.querySelectorAll?.("[data-processing-mode]").forEach(button => {
    button.addEventListener("click", () => setProcessingMode(button.dataset.processingMode || "quick"));
  });
  els.openClientButton?.addEventListener("click", () => openClient("workspace"));
  els.openClientBrand?.addEventListener("click", event => {
    event.preventDefault();
    openClient("workspace");
  });
  els.openTaskButton?.addEventListener("click", () => openClient("task", currentTaskId, "note"));
  document.querySelectorAll?.("[data-quick-tab]").forEach(button => {
    button.addEventListener("click", () => setQuickTab(button.dataset.quickTab || "summary"));
  });
  els.quickAskForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const question = String(els.quickAskQuestion?.value || "").trim();
    if (!question || !currentTaskId || !els.quickAskConversation) return;
    const entry = document.createElement?.("article");
    if (entry) {
      entry.innerHTML = `<strong>你</strong><p>${escapeQuickHtml(question)}</p>`;
      els.quickAskConversation.appendChild(entry);
    }
    try {
      const response = await fetchWithTimeout(`${backendUrl}/api/tasks/${encodeURIComponent(currentTaskId)}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question })
      });
      if (!response.ok) throw new Error(`提问失败（HTTP ${response.status}）`);
      const result = await response.json();
      const answer = document.createElement?.("article");
      if (answer) {
        answer.innerHTML = `<strong>LearnNote</strong>${renderQuickMarkdown(result?.answer || "没有找到可引用的字幕证据。")}`;
        els.quickAskConversation.appendChild(answer);
      }
      if (els.quickAskQuestion) els.quickAskQuestion.value = "";
    } catch (error) {
      const answer = document.createElement?.("article");
      if (answer) {
        answer.innerHTML = `<strong>提示</strong><p>${escapeQuickHtml(error?.message || "提问失败")}</p>`;
        els.quickAskConversation.appendChild(answer);
      }
    }
  });
  document.querySelectorAll("[data-client-view]").forEach(button => {
    button.addEventListener("click", () => openClient(button.dataset.clientView || "workspace", currentTaskId, button.dataset.clientView === "diagnostics" && currentTaskId ? "diagnostics" : "note"));
  });
  if (HAS_EXTENSION_API) chrome.runtime?.onMessage?.addListener?.(message => {
    if (message?.type !== "current-context-updated") return;
    if (message.reason === "tab-activated" && Date.now() < suppressTabActivationUntil) return;
    if (message.reason !== "tab-activated" && displayedIdentity?.tab_id !== null && message.tabId !== displayedIdentity?.tab_id) return;
    scheduleRefresh(message.reason || "media", message.reason === "tab-activated" ? message.tabId : null);
  });
  window.addEventListener?.("focus", () => checkClient());
}

async function initialize() {
  bindEvents();
  await loadBackendUrl();
  await checkClient();
  await refreshAndPreflight({ force: true });
}

initialize();

globalThis.__learnnoteSidepanel = {
  canonicalPageUrl,
  platformIdentity,
  resourceFingerprint,
  buildSourceIdentity,
  hasReliableBrowserSubtitles,
  renderQuickMarkdown,
  renderQuickTranscript,
  sourceIdentityKey,
  sourceContinuityKey,
  sameSourceIdentity,
  hasFreshPreflight,
  handoffId,
  integrityEvidence,
  collectContext,
  runPreflight,
  sendToClient,
  openClient,
  getState: () => ({ backendUrl, clientConnected, currentContext, displayedIdentity, preflightReport, currentTaskId, currentTaskMode, selectedProcessingMode, sending })
};
