const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const resourceByTab = new Map();
const pageStateByTab = new Map();

function classify(url, mime = "") {
  const lower = url.toLowerCase();
  const type = mime.toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (FRAGMENT_RE.test(lower) && inferManifestUrl(url)) return "fragment";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || MEDIA_RE.test(lower)) return "video";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower)) return "subtitle";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  return "unknown";
}

function inferManifestUrl(url) {
  try {
    const parsed = new URL(url);
    const lowerPath = parsed.pathname.toLowerCase();
    for (const ext of [".m3u8", ".mpd"]) {
      const index = lowerPath.indexOf(ext);
      if (index < 0) continue;
      const manifestPath = parsed.pathname.slice(0, index + ext.length);
      if (manifestPath === parsed.pathname) return "";
      parsed.pathname = manifestPath;
      parsed.hash = "";
      return parsed.href;
    }
  } catch {
    return "";
  }
  return "";
}

function scoreResource(url, mime, source) {
  const kind = classify(url, mime);
  let score = 0;
  if (kind === "hls" || kind === "dash") score += 95;
  else if (kind === "video") score += 85;
  else if (kind === "fragment") score += 15;
  else if (kind === "subtitle") score += 60;
  else if (kind === "blob") score += 5;
  if (source === "webRequest") score += 10;
  if (/chaoxing|xuexitong/i.test(url)) score += 8;
  return Math.min(score, 100);
}

function isDownloadableKind(kind) {
  return kind === "hls" || kind === "dash" || kind === "video";
}

function urlHost(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

function sameSite(urlA, urlB) {
  const hostA = urlHost(urlA);
  const hostB = urlHost(urlB);
  if (!hostA || !hostB) return false;
  return hostA === hostB || hostA.endsWith(`.${hostB}`) || hostB.endsWith(`.${hostA}`);
}

function withPlaybackHints(resource, page = {}) {
  const active = page.active_video || {};
  const activeSrc = active.src || "";
  const activeFrameId = active.frame_id ?? null;
  const kind = resource.kind || classify(resource.url || "", resource.mime || "");
  const hinted = { ...resource, kind };
  let boost = 0;
  let match = hinted.playback_match || "";

  if (activeSrc && hinted.url === activeSrc) {
    boost += 20;
    match = match || "exact-src";
    hinted.is_main_video = true;
  }

  if (
    activeFrameId !== null &&
    hinted.frame_id !== null &&
    hinted.frame_id !== undefined &&
    hinted.frame_id === activeFrameId &&
    isDownloadableKind(kind)
  ) {
    boost += activeSrc.startsWith("blob:") ? 16 : 12;
    match = match || (activeSrc.startsWith("blob:") ? "blob-same-frame" : "same-frame");
    hinted.is_main_video = true;
  }

  const recent = hinted.time_stamp && Date.now() - hinted.time_stamp < 5 * 60 * 1000;
  if (recent && hinted.source === "webRequest" && isDownloadableKind(kind)) {
    if (activeSrc.startsWith("blob:")) {
      boost += 8;
      match = match || "recent-media-request";
    }
    if (sameSite(hinted.initiator || "", page.page_url || "")) {
      boost += 4;
      match = match || "same-site-request";
    }
  }

  if (match) hinted.playback_match = match;
  hinted.score = Math.min(100, Math.max(hinted.score || 0, scoreResource(hinted.url || "", hinted.mime || "", hinted.source || "")) + boost);
  return hinted;
}

function mergeResource(previous, incoming) {
  if (!previous) return incoming;
  const merged = { ...previous, ...incoming };
  merged.score = Math.max(previous.score || 0, incoming.score || 0);
  merged.is_main_video = Boolean(previous.is_main_video || incoming.is_main_video);
  merged.playback_match = previous.playback_match || incoming.playback_match || "";
  merged.headers = { ...(previous.headers || {}), ...(incoming.headers || {}) };
  merged.current_time = incoming.current_time ?? previous.current_time ?? null;
  merged.duration = incoming.duration ?? previous.duration ?? null;
  merged.width = incoming.width ?? previous.width ?? null;
  merged.height = incoming.height ?? previous.height ?? null;
  merged.status_code = incoming.status_code ?? previous.status_code ?? null;
  merged.content_length = incoming.content_length ?? previous.content_length ?? null;
  merged.time_stamp = Math.max(previous.time_stamp || 0, incoming.time_stamp || 0) || null;
  return merged;
}

function frameStates(tabId) {
  if (!pageStateByTab.has(tabId)) pageStateByTab.set(tabId, new Map());
  return pageStateByTab.get(tabId);
}

function normalizePageForFrame(page = {}, frameId = 0, tab = {}) {
  const normalized = {
    title: page.title || tab.title || "",
    page_url: page.page_url || tab.url || "",
    page_text: page.page_text || "",
    active_video: page.active_video || null,
    resources: Array.isArray(page.resources) ? page.resources : [],
    frame_id: frameId
  };
  if (normalized.active_video) normalized.active_video = { ...normalized.active_video, frame_id: frameId };
  normalized.resources = normalized.resources.map(resource => ({ ...resource, frame_id: resource.frame_id ?? frameId }));
  return normalized;
}

function rememberFramePage(tabId, frameId, page, tab = {}) {
  const normalized = normalizePageForFrame(page, frameId, tab);
  frameStates(tabId).set(frameId, normalized);
  return normalized;
}

function mergePageContexts(tab = {}, pages = []) {
  const byFrame = new Map();
  for (const page of pages) {
    if (!page) continue;
    byFrame.set(page.frame_id ?? 0, page);
  }
  const ordered = [...byFrame.values()].sort((a, b) => (a.frame_id ?? 0) - (b.frame_id ?? 0));
  const top = ordered.find(page => (page.frame_id ?? 0) === 0) || ordered[0] || {};
  const activePage = ordered.find(page => page.active_video?.src && !page.active_video.paused) ||
    ordered.find(page => page.active_video?.src) ||
    null;
  const textParts = [];
  const seenText = new Set();
  for (const page of ordered) {
    const text = (page.page_text || "").trim();
    if (!text || seenText.has(text)) continue;
    seenText.add(text);
    textParts.push(text);
  }
  return {
    title: top.title || activePage?.title || tab.title || "",
    page_url: top.page_url || tab.url || activePage?.page_url || "",
    page_text: textParts.join("\n\n--- iframe ---\n\n").slice(0, 60000),
    active_video: activePage?.active_video || null,
    resources: ordered.flatMap(page => page.resources || []),
    frames: ordered.map(page => ({
      frame_id: page.frame_id ?? 0,
      title: page.title || "",
      page_url: page.page_url || "",
      has_active_video: Boolean(page.active_video?.src),
      resource_count: (page.resources || []).length
    }))
  };
}

function addResource(tabId, resource) {
  if (tabId < 0 || !resource?.url) return;
  const list = resourceByTab.get(tabId) || [];
  const existing = list.find(item => item.url === resource.url);
  const normalized = {
    url: resource.url,
    source: resource.source || "unknown",
    kind: resource.kind || classify(resource.url, resource.mime),
    mime: resource.mime || "",
    score: Math.max(resource.score || 0, scoreResource(resource.url, resource.mime || "", resource.source || "")),
    label: resource.label || "",
    is_main_video: Boolean(resource.is_main_video),
    playback_match: resource.playback_match || "",
    tab_id: tabId,
    frame_id: resource.frame_id ?? null,
    current_time: resource.current_time ?? null,
    duration: resource.duration ?? null,
    width: resource.width ?? null,
    height: resource.height ?? null,
    request_type: resource.request_type || "",
    method: resource.method || "",
    status_code: resource.status_code ?? null,
    content_length: resource.content_length ?? null,
    initiator: resource.initiator || "",
    time_stamp: resource.time_stamp ?? null,
    headers: resource.headers || {}
  };
  if (existing) {
    Object.assign(existing, normalized, {
      score: Math.max(existing.score || 0, normalized.score),
      is_main_video: Boolean(existing.is_main_video || normalized.is_main_video),
      playback_match: existing.playback_match || normalized.playback_match || "",
      current_time: normalized.current_time ?? existing.current_time ?? null,
      duration: normalized.duration ?? existing.duration ?? null,
      width: normalized.width ?? existing.width ?? null,
      height: normalized.height ?? existing.height ?? null,
      status_code: normalized.status_code ?? existing.status_code ?? null,
      content_length: normalized.content_length ?? existing.content_length ?? null,
      request_type: normalized.request_type || existing.request_type || "",
      method: normalized.method || existing.method || "",
      initiator: normalized.initiator || existing.initiator || "",
      time_stamp: normalized.time_stamp ?? existing.time_stamp ?? null,
      headers: { ...(existing.headers || {}), ...(normalized.headers || {}) }
    });
  } else {
    list.unshift(normalized);
  }
  resourceByTab.set(tabId, list.slice(0, 80));

  const inferredUrl = inferManifestUrl(normalized.url);
  if (inferredUrl && inferredUrl !== normalized.url) {
    const inferredKind = classify(inferredUrl, normalized.mime);
    addResource(tabId, {
      ...normalized,
      url: inferredUrl,
      source: "inferred-manifest",
      kind: inferredKind,
      mime: inferredKind === "hls" ? "application/vnd.apple.mpegurl" : "application/dash+xml",
      label: inferredKind === "hls" ? "Inferred HLS manifest" : "Inferred DASH manifest",
      score: Math.min(100, (normalized.score || 0) + 24),
      playback_match: normalized.playback_match || "inferred-from-fragment"
    });
  }
}

chrome.webRequest.onCompleted.addListener(
  details => {
    const headers = {};
    for (const header of details.responseHeaders || []) {
      headers[header.name.toLowerCase()] = header.value || "";
    }
    const mime = headers["content-type"] || "";
    const kind = classify(details.url, mime);
    if (kind === "unknown") return;
    const contentLength = Number(headers["content-length"] || 0);
    addResource(details.tabId, {
      url: details.url,
      source: "webRequest",
      kind,
      mime,
      headers,
      request_type: details.type || "",
      method: details.method || "",
      status_code: details.statusCode || null,
      content_length: Number.isFinite(contentLength) && contentLength > 0 ? contentLength : null,
      initiator: details.initiator || "",
      time_stamp: details.timeStamp || null,
      label: kind.toUpperCase()
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

chrome.tabs.onRemoved.addListener(tabId => {
  resourceByTab.delete(tabId);
  pageStateByTab.delete(tabId);
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" || changeInfo.url) {
    resourceByTab.delete(tabId);
    pageStateByTab.delete(tabId);
  }
});
chrome.action.onClicked.addListener(tab => {
  if (chrome.sidePanel?.open) chrome.sidePanel.open({ tabId: tab.id });
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function getAllFrameInfos(tabId) {
  return new Promise(resolve => {
    if (!chrome.webNavigation?.getAllFrames) {
      resolve([{ frameId: 0 }]);
      return;
    }
    try {
      const maybePromise = chrome.webNavigation.getAllFrames({ tabId }, frames => resolve(frames || [{ frameId: 0 }]));
      if (maybePromise?.then) maybePromise.then(frames => resolve(frames || [{ frameId: 0 }])).catch(() => resolve([{ frameId: 0 }]));
    } catch {
      resolve([{ frameId: 0 }]);
    }
  });
}

async function collectFramePageData(tab, frameId) {
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "collect-page-data" }, { frameId });
    const page = rememberFramePage(tab.id, frameId, response, tab);
    for (const resource of page.resources || []) addResource(tab.id, resource);
    return page;
  } catch {
    try {
      const [injected] = await chrome.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [frameId] },
        func: () => ({
          title: document.title,
          page_url: location.href,
          page_text: document.body?.innerText?.slice(0, 60000) || "",
          active_video: null,
          resources: []
        })
      });
      return rememberFramePage(tab.id, frameId, injected.result, tab);
    } catch {
      return null;
    }
  }
}

async function collectPageData(tab) {
  const frameInfos = await getAllFrameInfos(tab.id);
  const frameIds = [...new Set([0, ...(frameInfos || []).map(frame => frame.frameId).filter(frameId => frameId !== undefined)])];
  await Promise.all(frameIds.map(frameId => collectFramePageData(tab, frameId)));
  const remembered = [...(pageStateByTab.get(tab.id)?.values() || [])];
  return mergePageContexts(tab, remembered);
}

async function cookiesForUrls(urls) {
  const result = new Map();
  for (const url of urls) {
    if (!/^https?:\/\//i.test(url)) continue;
    try {
      const cookies = await chrome.cookies.getAll({ url });
      for (const cookie of cookies) {
        result.set(`${cookie.domain}|${cookie.path}|${cookie.name}`, cookie);
      }
    } catch {
      // Ignore browser-internal or malformed URLs.
    }
  }
  return [...result.values()];
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message.type === "page-media-detected" && sender.tab?.id !== undefined) {
      const tabId = sender.tab.id;
      const frameId = sender.frameId ?? 0;
      const page = rememberFramePage(tabId, frameId, message.page || {}, sender.tab || {});
      for (const resource of page.resources || []) {
        addResource(tabId, resource);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "get-current-context") {
      const tab = await activeTab();
      const page = await collectPageData(tab);
      const sniffed = resourceByTab.get(tab.id) || [];
      const activePage = page;
      const merged = [...(page.resources || []), ...sniffed].map(item => withPlaybackHints(item, activePage));
      const byUrl = new Map();
      for (const item of merged) {
        const previous = byUrl.get(item.url);
        byUrl.set(item.url, mergeResource(previous, item));
      }
      const resources = [...byUrl.values()].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 30);
      sendResponse({ tab, page: activePage, resources });
      return;
    }

    if (message.type === "start-current-task") {
      const tab = await activeTab();
      const page = message.page || await collectPageData(tab);
      const resources = message.resources || resourceByTab.get(tab.id) || [];
      const urls = [page.page_url || tab.url, ...resources.map(item => item.url)];
      const cookies = await cookiesForUrls(urls);
      const backendUrl = message.backendUrl || "http://127.0.0.1:8765";
      const res = await fetch(`${backendUrl}/api/tasks/from-current-page`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: message.mode || "video",
          page_url: page.page_url || tab.url,
          title: page.title || tab.title || "",
          page_text: page.page_text || "",
          active_video: page.active_video || null,
          resources,
          cookies,
          options: message.options || {}
        })
      });
      sendResponse(await res.json());
      return;
    }
  })().catch(error => sendResponse({ error: String(error?.message || error) }));
  return true;
});
