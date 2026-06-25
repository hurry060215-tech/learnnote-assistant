const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const resourceByTab = new Map();
const pageStateByTab = new Map();

function classify(url, mime = "") {
  const lower = url.toLowerCase();
  const type = mime.toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || MEDIA_RE.test(lower)) return "video";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower)) return "subtitle";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  return "unknown";
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
chrome.action.onClicked.addListener(tab => {
  if (chrome.sidePanel?.open) chrome.sidePanel.open({ tabId: tab.id });
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function collectPageData(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: "collect-page-data" });
    for (const resource of response.resources || []) addResource(tabId, resource);
    pageStateByTab.set(tabId, response);
    return response;
  } catch {
    const [injected] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => ({
        title: document.title,
        page_url: location.href,
        page_text: document.body?.innerText?.slice(0, 60000) || "",
        active_video: null,
        resources: []
      })
    });
    return injected.result;
  }
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
      const page = message.page || {};
      for (const resource of page.resources || []) {
        addResource(tabId, { ...resource, frame_id: resource.frame_id ?? sender.frameId ?? null });
      }
      const previous = pageStateByTab.get(tabId) || {};
      pageStateByTab.set(tabId, { ...previous, ...page });
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "get-current-context") {
      const tab = await activeTab();
      const page = await collectPageData(tab.id);
      const storedPage = pageStateByTab.get(tab.id) || {};
      const sniffed = resourceByTab.get(tab.id) || [];
      const merged = [...(page.resources || []), ...sniffed];
      const byUrl = new Map();
      for (const item of merged) {
        const previous = byUrl.get(item.url);
        if (!previous || (item.score || 0) > (previous.score || 0)) byUrl.set(item.url, item);
      }
      const resources = [...byUrl.values()].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 30);
      sendResponse({ tab, page: { ...storedPage, ...page, active_video: page.active_video || storedPage.active_video || null }, resources });
      return;
    }

    if (message.type === "start-current-task") {
      const tab = await activeTab();
      const page = message.page || await collectPageData(tab.id);
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
