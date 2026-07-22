const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
const PROTOCOL_VERSION = 1;
const HEALTH_TIMEOUT_MS = 2200;
const REQUEST_TIMEOUT_MS = 20000;
const PASSIVE_REFRESH_DELAY_MS = 450;
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
  handoffProgress: document.querySelector("#handoffProgress"),
  handoffStatus: document.querySelector("#handoffStatus"),
  handoffPercent: document.querySelector("#handoffPercent"),
  openTaskButton: document.querySelector("#openTaskButton")
};

let backendUrl = DEFAULT_BACKEND_URL;
let clientConnected = false;
let currentContext = null;
let displayedIdentity = null;
let preflightReport = null;
let preflightIdentity = null;
let currentTaskId = "";
let collecting = false;
let sending = false;
let refreshTimer = 0;
let contextGeneration = 0;

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

function platformIdentity(urlValue = "", page = {}) {
  const url = String(urlValue || "");
  const bilibili = /(?:bilibili\.com\/video\/|b23\.tv\/)(BV[0-9A-Za-z]+)/i.exec(url);
  if (bilibili) return { platform: "bilibili", platformVideoId: bilibili[1], label: "哔哩哔哩" };
  try {
    const parsed = new URL(url);
    if (/youtube\.com$/i.test(parsed.hostname) || /youtu\.be$/i.test(parsed.hostname)) {
      const id = /youtu\.be$/i.test(parsed.hostname) ? parsed.pathname.split("/").filter(Boolean)[0] : parsed.searchParams.get("v");
      return { platform: "youtube", platformVideoId: id || "", label: "YouTube" };
    }
    if (/chaoxing\.com$/i.test(parsed.hostname) || /xuexitong/i.test(parsed.hostname)) {
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

function sameSourceIdentity(left, right) {
  return Boolean(left && right && sourceIdentityKey(left) === sourceIdentityKey(right));
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
  const audioEvidence = Boolean(Number(active.src_object_audio_tracks || 0) > 0 || candidates.some(item => AUDIO_KIND_RE.test(String(item?.kind || "")) || /^audio\//i.test(String(item?.mime || item?.content_type || ""))));
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
  els.estimateValue.textContent = candidates.length || active.src ? "约 5–15 秒" : "--";
  setIntegrityItem("video", evidence.video);
  setIntegrityItem("audio", evidence.audio);
  setIntegrityItem("subtitle", evidence.subtitle);

  const hasPage = Boolean(identity?.canonical_page_url && !/^(?:chrome|edge|about):/i.test(identity.canonical_page_url));
  const hasMediaEvidence = evidence.video === true || candidates.length > 0;
  els.sendButton.disabled = sending || !clientConnected || !hasPage || !hasMediaEvidence;
  if (message) {
    els.preflightMessage.textContent = message;
  } else if (!hasPage) {
    els.preflightMessage.textContent = "请切换到正在播放视频的页面。";
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
  if (collecting) return currentContext;
  collecting = true;
  const generation = ++contextGeneration;
  els.refreshButton.disabled = true;
  try {
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "get-current-context",
      targetTabId: targetTabId ?? currentContext?.tab?.id ?? null,
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
      preflightReport = null;
      preflightIdentity = null;
      currentTaskId = "";
      els.openTaskButton.hidden = true;
    }
    renderContext(changed ? "页面或播放内容已切换，旧预检已清除。请确认后再发送。" : "");
    return next;
  } catch (error) {
    els.preflightMessage.dataset.state = "error";
    renderContext(`识别失败：${error?.message || "请刷新页面后重试"}`);
    return null;
  } finally {
    collecting = false;
    els.refreshButton.disabled = false;
  }
}

async function runPreflight(identity = displayedIdentity) {
  if (!clientConnected || !currentContext || !identity) return null;
  const candidates = mediaCandidates(currentContext);
  if (!candidates.length && !currentContext.page?.active_video) return null;
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
    els.preflightMessage.dataset.state = preflightReport?.ready ? "ready" : "info";
    renderContext();
    return preflightReport;
  } catch (error) {
    if (sameSourceIdentity(identity, displayedIdentity)) {
      els.preflightMessage.dataset.state = "error";
      renderContext(`已检测到媒体候选，但下载预检暂不可用：${error?.message || "客户端将继续检查"}`);
    }
    return null;
  }
}

async function refreshAndPreflight({ force = true } = {}) {
  els.preflightMessage.dataset.state = "info";
  els.preflightMessage.textContent = "正在读取播放器和媒体请求...";
  const context = await collectContext(force);
  if (context && clientConnected) await runPreflight(displayedIdentity);
  return context;
}

function pageSwitchMessage() {
  return "页面或播放内容已切换，已丢弃旧预检结果。请确认当前视频后重新发送。";
}

async function sendToClient() {
  if (sending || !displayedIdentity) return false;
  sending = true;
  els.sendButton.disabled = true;
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
      preflightReport = null;
      preflightIdentity = null;
      renderContext(pageSwitchMessage());
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    setProgress(46, "正在校验媒体完整性...");
    await runPreflight(freshIdentity);
    if (!sameSourceIdentity(freshIdentity, displayedIdentity)) {
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    setProgress(70, "正在进行发送前最终校验...");
    const finalResponse = await withTimeout(chrome.runtime.sendMessage({
      type: "get-current-context",
      targetTabId: freshIdentity.tab_id,
      useCached: false
    }), REQUEST_TIMEOUT_MS, "最终校验");
    if (finalResponse?.error) throw new Error(finalResponse.error);
    const finalContext = {
      tab: finalResponse?.tab || {},
      page: finalResponse?.page || {},
      resources: Array.isArray(finalResponse?.resources) ? finalResponse.resources : []
    };
    const finalIdentity = buildSourceIdentity(finalContext);
    if (!sameSourceIdentity(freshIdentity, finalIdentity)) {
      currentContext = finalContext;
      displayedIdentity = finalIdentity;
      preflightReport = null;
      preflightIdentity = null;
      renderContext(pageSwitchMessage());
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    setProgress(88, "正在发送视频来源到客户端...");
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "start-current-task",
      backendUrl,
      targetTabId: finalIdentity.tab_id,
      page: finalContext.page,
      resources: mediaCandidates(finalContext),
      pagePreflightReport: sameSourceIdentity(preflightIdentity, finalIdentity) ? preflightReport : null,
      sourceIdentity: finalIdentity,
      defer: true,
      mode: "video"
    }), REQUEST_TIMEOUT_MS, "发送到客户端");
    if (response?.error) throw new Error(response.error);
    currentTaskId = String(response?.task_id || "");
    setProgress(100, "已发送，等待在客户端确认。", "success");
    els.openTaskButton.hidden = !currentTaskId;
    if (currentTaskId) await openClient("task", currentTaskId, "note");
    return true;
  } catch (error) {
    setProgress(Number(els.handoffProgress.getAttribute("aria-valuenow") || 0), error?.message || "发送失败，请重试", "error");
    return false;
  } finally {
    sending = false;
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
  els.openClientButton?.addEventListener("click", () => openClient("workspace"));
  els.openClientBrand?.addEventListener("click", event => {
    event.preventDefault();
    openClient("workspace");
  });
  els.openTaskButton?.addEventListener("click", () => openClient("task", currentTaskId, "note"));
  document.querySelectorAll("[data-client-view]").forEach(button => {
    button.addEventListener("click", () => openClient(button.dataset.clientView || "workspace", currentTaskId, button.dataset.clientView === "diagnostics" && currentTaskId ? "diagnostics" : "note"));
  });
  if (HAS_EXTENSION_API) chrome.runtime?.onMessage?.addListener?.(message => {
    if (message?.type !== "current-context-updated") return;
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
  sourceIdentityKey,
  sameSourceIdentity,
  integrityEvidence,
  collectContext,
  runPreflight,
  sendToClient,
  openClient,
  getState: () => ({ backendUrl, clientConnected, currentContext, displayedIdentity, preflightReport, currentTaskId, sending })
};
