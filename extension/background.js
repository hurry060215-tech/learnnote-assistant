const VIDEO_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const AUDIO_RE = /\.(m4a|mp3|aac|opus|ogg|oga|wav)(\?|#|$)/i;
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const PLAYBACK_ENDPOINT_RE = /m3u8|mpd|video|audio|media|subtitle|caption|stream|hls|dash|manifest|playlist|master|playback|player|download|attachment|ananas|objectid|dtoken|fileid|httpmd|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|(?:^|[/?&=._-])(?:source|sources|sourcelist|backup|backups|cdn|baseurl|base_url|base-url|host|domain)(?:[/?&=._-]|$)|\/play(?:[/?#]|$)/i;
const LOCAL_EXPORT_KIND_RE = /(?:(?:markdown|visual-windows|bundle|diagnostics|media|manifest|audit|subtitles|qa|resource-inventory|page-preflight-report)|clips\/[^/?#]+)/;
const LOCAL_TASK_FILE_RE = new RegExp(`^https?:\\/\\/(?:127\\.0\\.0\\.1|localhost)(?::\\d+)?\\/api\\/tasks\\/[^/]+(?:\\/media|\\/exports\\/${LOCAL_EXPORT_KIND_RE.source})(?:[?#].*)?$`, "i");
const LOCAL_EXPORT_RE = new RegExp(`^https?:\\/\\/(?:127\\.0\\.0\\.1|localhost)(?::\\d+)?\\/api\\/tasks\\/[^/]+\\/exports\\/${LOCAL_EXPORT_KIND_RE.source}(?:[?#].*)?$`, "i");
const resourceByTab = new Map();
const pageStateByTab = new Map();
const requestHeadersByRequestId = new Map();
const requestBodiesByRequestId = new Map();
const contextUpdateTimers = new Map();
const MAX_REQUEST_BODY_BYTES = 64 * 1024;
const MAX_CAPTURE_LOG_RESOURCES = 120;
const CAPTURE_LOG_KEY_PREFIX = "captureLog:";
const REQUEST_HEADER_ALLOWLIST = new Set([
  "accept",
  "accept-language",
  "authorization",
  "content-type",
  "origin",
  "range",
  "referer",
  "sec-ch-ua",
  "sec-ch-ua-mobile",
  "sec-ch-ua-platform",
  "sec-fetch-dest",
  "sec-fetch-mode",
  "sec-fetch-site",
  "user-agent",
  "x-requested-with"
]);
const RESPONSE_HEADER_ALLOWLIST = new Set(["accept-ranges", "content-disposition", "content-length", "content-location", "content-range", "content-type", "location"]);
const REQUEST_HEADER_CANONICAL = {
  "accept": "Accept",
  "accept-language": "Accept-Language",
  "authorization": "Authorization",
  "content-type": "Content-Type",
  "origin": "Origin",
  "range": "Range",
  "referer": "Referer",
  "sec-ch-ua": "Sec-CH-UA",
  "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
  "sec-ch-ua-platform": "Sec-CH-UA-Platform",
  "sec-fetch-dest": "Sec-Fetch-Dest",
  "sec-fetch-mode": "Sec-Fetch-Mode",
  "sec-fetch-site": "Sec-Fetch-Site",
  "user-agent": "User-Agent",
  "x-requested-with": "X-Requested-With"
};
const PERSISTED_REQUEST_HEADER_DENYLIST = new Set(["authorization", "cookie", "proxy-authorization"]);

function backendErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail?.message) return String(detail.message);
  if (payload?.message) return String(payload.message);
  if (payload?.error) return String(payload.error);
  return fallback;
}

async function backendJsonResponse(res, fallback) {
  const payload = await res.json().catch(() => ({}));
  if (res.ok === false) {
    return {
      ...payload,
      ok: false,
      error: backendErrorMessage(payload, fallback || `HTTP ${res.status}`),
      status: res.status
    };
  }
  return payload;
}

function mediaKindFromMime(mime = "") {
  const type = String(mime || "").toLowerCase();
  if (type.includes("mpegurl") || type.includes("application/x-mpegurl")) return "hls";
  if (type.includes("dash+xml")) return "dash";
  if (type.includes("video/") || type.includes("application/mp4")) return "video";
  if (type.includes("audio/") || type.includes("application/ogg")) return "audio";
  if (type.includes("text/vtt") || type.includes("subrip")) return "subtitle";
  return "unknown";
}

function classify(url, mime = "") {
  const lower = url.toLowerCase();
  const mimeKind = mediaKindFromMime(mime);
  if (lower.startsWith("blob:")) return "blob";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  if (mimeKind !== "unknown") return mimeKind;
  if (lower.includes(".m3u8")) return "hls";
  if (lower.includes(".mpd")) return "dash";
  if (VIDEO_RE.test(lower)) return "video";
  if (AUDIO_RE.test(lower)) return "audio";
  if (SUBTITLE_RE.test(lower)) return "subtitle";
  return "unknown";
}

function filenameFromContentDisposition(value = "") {
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

function classifyContentDisposition(contentDisposition = "", mime = "") {
  const filename = filenameFromContentDisposition(contentDisposition);
  return filename ? classify(filename, mime) : "unknown";
}

function hasRangeEvidence(requestHeaders = {}, responseHeaders = {}) {
  const requestRange = Object.entries(requestHeaders || {}).some(([name, value]) =>
    String(name).toLowerCase() === "range" && /^bytes=/i.test(String(value || "").trim())
  );
  const responseRange = Boolean(responseHeaders["content-range"]) ||
    String(responseHeaders["accept-ranges"] || "").toLowerCase().includes("bytes");
  return requestRange && responseRange;
}

function requestHasMediaDestination(requestHeaders = {}) {
  const headers = Object.fromEntries(
    Object.entries(requestHeaders || {}).map(([name, value]) => [String(name).toLowerCase(), String(value || "").toLowerCase()])
  );
  return /^(video|audio)$/i.test(headers["sec-fetch-dest"] || "") ||
    /(?:^|[,;\s])(?:video|audio)\//i.test(headers.accept || "") ||
    /mpegurl|dash\+xml|mp4|webm|x-matroska|m4a|mp3|aac|opus|ogg/i.test(headers.accept || "");
}

function requestHeaderArrayHasMediaDestination(requestHeaders = []) {
  const headers = {};
  for (const header of requestHeaders || []) {
    const name = String(header.name || "").toLowerCase();
    if (!name) continue;
    headers[name] = String(header.value || "");
  }
  return requestHasMediaDestination(headers);
}

function responseContentLength(responseHeaders = {}) {
  const value = Number(responseHeaders["content-length"] || 0);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function looksLikeLargeBinaryMediaEndpoint(details = {}, mime = "", responseHeaders = {}) {
  const type = String(details.type || "").toLowerCase();
  if (!/^(xmlhttprequest|fetch|media)$/.test(type)) return false;
  const binaryMime = /octet-stream|binary|application\/x-mpegurl/i.test(String(mime || ""));
  if (!binaryMime) return false;
  if (!PLAYBACK_ENDPOINT_RE.test(details.url || "")) return false;
  return responseContentLength(responseHeaders) >= 1024 * 1024;
}

function looksLikeSmallBinaryPlaybackEndpoint(details = {}, mime = "", responseHeaders = {}) {
  const type = String(details.type || "").toLowerCase();
  if (!/^(xmlhttprequest|fetch)$/.test(type)) return false;
  if (!/octet-stream|binary/i.test(String(mime || ""))) return false;
  if (!PLAYBACK_ENDPOINT_RE.test(details.url || "")) return false;
  const length = responseContentLength(responseHeaders);
  return length > 0 && length <= 512 * 1024;
}

function looksLikeTextPlayEndpoint(details = {}, mime = "") {
  const type = String(details.type || "").toLowerCase();
  if (!/^(xmlhttprequest|fetch)$/.test(type)) return false;
  if (!/json|text|javascript|xml/i.test(String(mime || ""))) return false;
  return PLAYBACK_ENDPOINT_RE.test(details.url || "");
}

function classifyCompletedRequest(details = {}, mime = "", requestHeaders = {}, responseHeaders = {}) {
  const kind = classify(details.url || "", mime);
  if (kind !== "unknown") return kind;
  const headerKind = classifyContentDisposition(responseHeaders["content-disposition"] || "", mime);
  if (headerKind !== "unknown") return headerKind;
  if (details.type === "media") return String(mime || "").toLowerCase().includes("audio/") ? "audio" : "video";
  const type = String(details.type || "").toLowerCase();
  const binaryMime = /octet-stream|binary|application\/x-mpegurl/i.test(String(mime || ""));
  if ((type === "xmlhttprequest" || type === "fetch") && binaryMime && hasRangeEvidence(requestHeaders, responseHeaders)) {
    return "video";
  }
  if ((type === "xmlhttprequest" || type === "fetch") && binaryMime && requestHasMediaDestination(requestHeaders) && responseContentLength(responseHeaders) >= 1024 * 1024) {
    return "video";
  }
  if (looksLikeSmallBinaryPlaybackEndpoint(details, mime, responseHeaders)) return "video";
  if (looksLikeTextPlayEndpoint(details, mime)) return "video";
  if (looksLikeLargeBinaryMediaEndpoint(details, mime, responseHeaders)) return "video";
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

function inferSiblingManifestUrls(url) {
  try {
    const parsed = new URL(url);
    const lowerPath = parsed.pathname.toLowerCase();
    if (!FRAGMENT_RE.test(parsed.pathname) || lowerPath.includes(".m3u8") || lowerPath.includes(".mpd")) return [];
    const slash = parsed.pathname.lastIndexOf("/");
    const directory = slash >= 0 ? parsed.pathname.slice(0, slash + 1) : "/";
    const names = lowerPath.endsWith(".ts")
      ? ["index.m3u8", "playlist.m3u8", "master.m3u8"]
      : ["manifest.mpd", "index.mpd", "master.m3u8", "index.m3u8"];
    const directories = [directory];
    const parent = directory.replace(/\/$/, "");
    const parentName = parent.split("/").pop().toLowerCase();
    const parentDirectory = parent.includes("/") ? `${parent.slice(0, parent.lastIndexOf("/") + 1)}` : "/";
    if (
      parentDirectory &&
      parentDirectory !== "/" &&
      !directories.includes(parentDirectory) &&
      /^(segments?|chunks?|fragments?|video|audio|v\d+|\d{3,4}p|[a-z]{2,4}_?\d{3,4}p|avc|h26[45]|dash|hls)$/.test(parentName)
    ) {
      directories.push(parentDirectory);
    }
    const results = [];
    for (const candidateDirectory of directories) {
      for (const name of names) {
        parsed.pathname = candidateDirectory + name;
        parsed.hash = "";
        const href = parsed.href;
        if (!results.includes(href)) results.push(href);
      }
    }
    return results;
  } catch {
    return [];
  }
}

function scoreKind(url, source, kind) {
  let score = 0;
  if (kind === "hls" || kind === "dash") score += 95;
  else if (kind === "video") score += 85;
  else if (kind === "audio") score += 35;
  else if (kind === "fragment") score += 15;
  else if (kind === "subtitle") score += 60;
  else if (kind === "blob") score += 5;
  if (source === "webRequest") score += 10;
  if (String(source || "").startsWith("pageHook")) score += 10;
  if (source === "pageHookBlobSource" || source === "pageHookMediaSource") score += 8;
  if (/chaoxing|xuexitong/i.test(url)) score += 8;
  if (PLAYBACK_ENDPOINT_RE.test(url)) score += 6;
  return Math.min(score, 100);
}

function scoreResource(url, mime, source) {
  return scoreKind(url, source, classify(url, mime));
}

function isDownloadableKind(kind) {
  return kind === "hls" || kind === "dash" || kind === "video";
}

function hasReplayableRequestBody(resource = {}) {
  const method = String(resource.method || "").toUpperCase();
  if (!["POST", "PUT", "PATCH"].includes(method)) return false;
  const body = resource.request_body || {};
  return Boolean(body.content || body.raw || body.formData || body.form_data || body.bytes);
}

function playableEndpointRank(resource = {}) {
  if (!PLAYBACK_ENDPOINT_RE.test(resource.url || "")) return 0;
  const requestType = String(resource.request_type || "").toLowerCase();
  const source = String(resource.source || "").toLowerCase();
  const method = String(resource.method || "").toUpperCase();
  let rank = 1;
  if (["xmlhttprequest", "fetch", "media"].includes(requestType)) rank += 2;
  if (source.startsWith("pagehook")) rank += 1;
  if (["POST", "PUT", "PATCH"].includes(method) || hasReplayableRequestBody(resource)) rank += 3;
  if (resource.playback_match || resource.is_main_video) rank += 2;
  return rank;
}

function isDirectResourceCandidate(resource = {}) {
  return isDownloadableKind(resource.kind) || playableEndpointRank(resource) > 0;
}

function isPlayableMediaEvidenceKind(kind) {
  return isDownloadableKind(kind) || kind === "fragment";
}

function kindRank(kind) {
  return ({
    hls: 6,
    dash: 6,
    video: 5,
    fragment: 3,
    audio: 2,
    subtitle: 2,
    blob: 1
  })[kind] || 0;
}

function effectiveKindRank(resource = {}) {
  const rank = kindRank(resource.kind);
  if (rank) return rank;
  return playableEndpointRank(resource) > 0 ? 4 : 0;
}

function playableEndpointScore(resource = {}) {
  const rank = playableEndpointRank(resource);
  if (!rank) return 0;
  const hostBoost = /chaoxing|xuexitong/i.test(resource.url || "") ? 8 : 0;
  return Math.min(100, 38 + rank * 8 + hostBoost);
}

function sourceRank(source = "") {
  if (source === "pageHookMediaSource" || source === "pageHookBlobSource") return 7;
  if (String(source || "").startsWith("pageHookPlayer")) return 6;
  if (source === "webRequestResolved") return 6;
  if (source === "webRequest") return 5;
  if (source === "activeVideo") return 4;
  if (String(source || "").startsWith("pageHook")) return 3;
  if (source === "scriptHint" || source === "domHint" || source === "locationHint" || source === "iframeHint") return 3;
  if (source === "dom") return 2;
  return 0;
}

function playbackMatchRank(match = "") {
  return ({
    "exact-src": 9,
    "source-element": 8,
    "blob-source": 8,
    "range-near-playhead": 7,
    "fragment-near-playhead": 6,
    "manifest-near-playhead": 6,
    "resolved-final-url": 6,
    "blob-same-frame": 5,
    "same-frame": 4,
    "recent-media-request": 3,
    "same-site-request": 2,
    "inferred-from-fragment": 1
  })[match] || 0;
}

function compareResourceCandidates(a = {}, b = {}) {
  const left = [
    a.user_selected ? 1 : 0,
    a.is_main_video ? 1 : 0,
    playbackMatchRank(a.playback_match),
    isDirectResourceCandidate(a) ? 1 : 0,
    effectiveKindRank(a),
    playableEndpointRank(a),
    sourceRank(a.source),
    Number(a.score || 0),
    Number(a.time_stamp || 0),
    Number(a.content_length || 0)
  ];
  const right = [
    b.user_selected ? 1 : 0,
    b.is_main_video ? 1 : 0,
    playbackMatchRank(b.playback_match),
    isDirectResourceCandidate(b) ? 1 : 0,
    effectiveKindRank(b),
    playableEndpointRank(b),
    sourceRank(b.source),
    Number(b.score || 0),
    Number(b.time_stamp || 0),
    Number(b.content_length || 0)
  ];
  for (let index = 0; index < left.length; index += 1) {
    if (right[index] !== left[index]) return right[index] - left[index];
  }
  return String(a.url || "").localeCompare(String(b.url || ""));
}

function mergeAndRankResources(resources, page = {}, tab = {}, { preserveOrder = false } = {}) {
  const baseResources = Array.isArray(resources) ? resources : resourceByTab.get(tab?.id) || [];
  const hinted = (baseResources || []).map(item => withPlaybackHints(item, page, tab));
  const byUrl = new Map();
  for (const item of hinted) {
    const previous = byUrl.get(item.url);
    byUrl.set(item.url, mergeResource(previous, item));
  }
  const merged = [...byUrl.values()];
  return preserveOrder ? merged : merged.sort(compareResourceCandidates);
}

function requestRangeHeader(resource = {}) {
  const headers = resource.request_headers || {};
  for (const [name, value] of Object.entries(headers)) {
    if (String(name).toLowerCase() === "range") return String(value || "");
  }
  return "";
}

function hasByteRangeRequest(resource = {}) {
  return /^bytes=\d*-\d*$/i.test(requestRangeHeader(resource).trim());
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

function cookieEligibleUrl(value) {
  const url = String(value || "").trim();
  if (/^https?:\/\//i.test(url)) return url;
  const blob = /^blob:(https?:\/\/[^/]+)/i.exec(url);
  return blob ? blob[1] : "";
}

function cookieDomainCandidates(value) {
  const url = cookieEligibleUrl(value);
  if (!url) return [];
  try {
    const host = new URL(url).hostname;
    if (!host || /^\d+\.\d+\.\d+\.\d+$/.test(host) || host === "localhost") return host ? [host] : [];
    const parts = host.split(".").filter(Boolean);
    const domains = [];
    for (let index = 0; index <= Math.max(0, parts.length - 2); index += 1) {
      const domain = parts.slice(index).join(".");
      if (domain && !domains.includes(domain)) domains.push(domain);
    }
    return domains;
  } catch {
    return [];
  }
}

function originForUrl(value = "") {
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

function addActiveVideoRequestContext(resource = {}, page = {}, tab = {}) {
  if (resource.source !== "activeVideo") return resource;
  if (!/^https?:\/\//i.test(String(resource.url || ""))) return resource;
  const headers = { ...(resource.request_headers || {}) };
  const referer = resource.frame_url || page.active_video?.frame_url || page.page_url || tab.url || "";
  const normalized = normalizeRequestHeaders([
    { name: "Referer", value: headers.Referer || referer },
    { name: "Origin", value: headers.Origin || originForUrl(referer) },
    ...Object.entries(headers).map(([name, value]) => ({ name, value }))
  ]);
  return { ...resource, request_headers: normalized };
}

function withPlaybackHints(resource, page = {}, tab = {}) {
  const active = page.active_video || {};
  const activeSrc = active.src || "";
  const activeFrameId = active.frame_id ?? null;
  const kind = resource.kind || classify(resource.url || "", resource.mime || "");
  const hinted = addActiveVideoRequestContext({ ...resource, kind }, page, tab);
  let boost = 0;
  let match = hinted.playback_match || "";

  if (activeSrc && hinted.url === activeSrc) {
    boost += 20;
    match = match || "exact-src";
    hinted.is_main_video = true;
  }

  if (activeSrc && hinted.blob_url === activeSrc && isDownloadableKind(kind)) {
    boost += 24;
    match = match || "blob-source";
    hinted.is_main_video = true;
  }

  if (
    activeFrameId !== null &&
    hinted.frame_id !== null &&
    hinted.frame_id !== undefined &&
    hinted.frame_id === activeFrameId &&
    (isDownloadableKind(kind) || (kind === "fragment" && activeSrc.startsWith("blob:")))
  ) {
    boost += kind === "fragment" ? 14 : activeSrc.startsWith("blob:") ? 16 : 12;
    match = match || (activeSrc.startsWith("blob:") ? "blob-same-frame" : "same-frame");
    hinted.is_main_video = true;
  }

  const recent = hinted.time_stamp && Date.now() - hinted.time_stamp < 5 * 60 * 1000;
  if (recent && activeSrc.startsWith("blob:") && /^pageHook(?:Blob|MediaSource)/.test(hinted.source || "") && isPlayableMediaEvidenceKind(kind)) {
    boost += 10;
    match = match || "blob-source";
    hinted.is_main_video = true;
  }

  const veryRecent = hinted.time_stamp && Date.now() - hinted.time_stamp < 45 * 1000;
  const sameActiveFrame = activeFrameId !== null && hinted.frame_id !== null && hinted.frame_id !== undefined && hinted.frame_id === activeFrameId;
  const sameActiveSite = sameSite(hinted.initiator || hinted.frame_url || hinted.page_url || "", page.page_url || active.frame_url || "");
  if (
    veryRecent &&
    !active.paused &&
    Number(active.current_time || 0) > 0 &&
    hinted.source === "webRequest" &&
    hasByteRangeRequest(hinted) &&
    isPlayableMediaEvidenceKind(kind) &&
    (sameActiveFrame || sameActiveSite || activeSrc.startsWith("blob:"))
  ) {
    boost += kind === "fragment" ? sameActiveFrame ? 18 : 14 : sameActiveFrame ? 22 : 18;
    match = ["exact-src", "blob-source"].includes(match) ? match : "range-near-playhead";
    hinted.is_main_video = true;
    hinted.current_time = active.current_time ?? hinted.current_time ?? null;
    hinted.duration = active.duration ?? hinted.duration ?? null;
  }

  if (
    veryRecent &&
    !active.paused &&
    Number(active.current_time || 0) > 0 &&
    hinted.source === "webRequest" &&
    kind === "fragment" &&
    !hasByteRangeRequest(hinted) &&
    activeSrc.startsWith("blob:") &&
    (sameActiveFrame || sameActiveSite)
  ) {
    boost += sameActiveFrame ? 18 : 12;
    match = ["exact-src", "blob-source", "blob-same-frame", "range-near-playhead"].includes(match)
      ? match
      : "fragment-near-playhead";
    hinted.is_main_video = true;
    hinted.current_time = active.current_time ?? hinted.current_time ?? null;
    hinted.duration = active.duration ?? hinted.duration ?? null;
  }

  if (
    veryRecent &&
    !active.paused &&
    Number(active.current_time || 0) > 0 &&
    hinted.source === "webRequest" &&
    (kind === "hls" || kind === "dash") &&
    (sameActiveFrame || sameActiveSite || activeSrc.startsWith("blob:"))
  ) {
    boost += sameActiveFrame ? 20 : 14;
    match = ["exact-src", "blob-source", "range-near-playhead"].includes(match) ? match : "manifest-near-playhead";
    hinted.is_main_video = true;
    hinted.current_time = active.current_time ?? hinted.current_time ?? null;
    hinted.duration = active.duration ?? hinted.duration ?? null;
  }

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
  hinted.score = Math.min(100, Math.max(hinted.score || 0, scoreKind(hinted.url || "", hinted.source || "", kind)) + boost);
  return hinted;
}

function mergeResource(previous, incoming) {
  if (!previous) return incoming;
  const merged = { ...previous, ...incoming };
  merged.score = Math.max(previous.score || 0, incoming.score || 0);
  merged.user_selected = Boolean(previous.user_selected || incoming.user_selected);
  merged.is_main_video = Boolean(previous.is_main_video || incoming.is_main_video);
  merged.playback_match = previous.playback_match || incoming.playback_match || "";
  merged.blob_url = incoming.blob_url || previous.blob_url || "";
  merged.frame_url = incoming.frame_url || previous.frame_url || "";
  merged.page_url = incoming.page_url || previous.page_url || "";
  merged.headers = { ...(previous.headers || {}), ...(incoming.headers || {}) };
  merged.request_headers = { ...(previous.request_headers || {}), ...(incoming.request_headers || {}) };
  merged.request_body = { ...(previous.request_body || {}), ...(incoming.request_body || {}) };
  merged.audio_url = incoming.audio_url || previous.audio_url || "";
  merged.audio_mime = incoming.audio_mime || previous.audio_mime || "";
  merged.current_time = incoming.current_time ?? previous.current_time ?? null;
  merged.duration = incoming.duration ?? previous.duration ?? null;
  merged.width = incoming.width ?? previous.width ?? null;
  merged.height = incoming.height ?? previous.height ?? null;
  merged.status_code = incoming.status_code ?? previous.status_code ?? null;
  merged.content_length = incoming.content_length ?? previous.content_length ?? null;
  merged.mse_append_bytes = incoming.mse_append_bytes ?? previous.mse_append_bytes ?? null;
  merged.mse_append_total_bytes = incoming.mse_append_total_bytes ?? previous.mse_append_total_bytes ?? null;
  merged.mse_append_count = incoming.mse_append_count ?? previous.mse_append_count ?? null;
  merged.mse_append_magic = incoming.mse_append_magic || previous.mse_append_magic || "";
  merged.mse_append_mime = incoming.mse_append_mime || previous.mse_append_mime || "";
  merged.mse_append_detected_kind = incoming.mse_append_detected_kind || previous.mse_append_detected_kind || "";
  merged.resolved_url = incoming.resolved_url || previous.resolved_url || "";
  merged.time_stamp = Math.max(previous.time_stamp || 0, incoming.time_stamp || 0) || null;
  return merged;
}

function captureLogStorageKey(tabId) {
  return `${CAPTURE_LOG_KEY_PREFIX}${tabId}`;
}

function safePersistedRequestHeaders(headers = {}) {
  const safe = {};
  for (const [name, value] of Object.entries(headers || {})) {
    const lower = String(name || "").toLowerCase();
    if (PERSISTED_REQUEST_HEADER_DENYLIST.has(lower)) continue;
    const cleaned = String(value || "").replace(/[\r\n]+/g, " ").trim();
    if (cleaned) safe[name] = cleaned.slice(0, 512);
  }
  return safe;
}

function requestBodyHasContent(details = {}) {
  const requestBody = details.requestBody || {};
  if (requestBody.formData && Object.keys(requestBody.formData || {}).length) return true;
  return Array.isArray(requestBody.raw) && requestBody.raw.some(part => part?.bytes);
}

function safePersistedRequestBody(resource = {}) {
  const body = resource.request_body || {};
  const type = String(body.type || "").trim();
  const content = String(body.content || "");
  if (type === "dropped") {
    return {
      type: "dropped",
      reason: String(body.reason || "too_large_or_binary").slice(0, 80)
    };
  }
  if (!type || !content) return {};
  const method = String(resource.method || "").toUpperCase();
  const kind = resource.kind || classify(resource.url || "", resource.mime || "");
  const replayable = ["POST", "PUT", "PATCH"].includes(method) && (
    ["video", "hls", "dash"].includes(kind) || PLAYBACK_ENDPOINT_RE.test(resource.url || "")
  );
  if (!replayable) return {};
  if (!["form", "text"].includes(type) || content.length > MAX_REQUEST_BODY_BYTES) {
    return { type: "dropped", reason: "too_large_or_binary" };
  }
  return { type, content };
}

function captureLogResource(resource = {}) {
  if (!resource?.url || isLocalLearnNoteTaskFile(resource.url)) return null;
  return {
    url: String(resource.url || ""),
    source: resource.source || "unknown",
    kind: resource.kind || classify(resource.url || "", resource.mime || ""),
    mime: resource.mime || "",
    score: Number(resource.score || 0),
    label: resource.label || "",
    is_main_video: Boolean(resource.is_main_video),
    playback_match: resource.playback_match || "",
    blob_url: resource.blob_url || "",
    frame_url: resource.frame_url || "",
    page_url: resource.page_url || "",
    tab_id: resource.tab_id ?? null,
    frame_id: resource.frame_id ?? null,
    current_time: resource.current_time ?? null,
    duration: resource.duration ?? null,
    width: resource.width ?? null,
    height: resource.height ?? null,
    request_type: resource.request_type || "",
    method: resource.method || "",
    status_code: resource.status_code ?? null,
    content_length: resource.content_length ?? null,
    mse_append_bytes: resource.mse_append_bytes ?? null,
    mse_append_total_bytes: resource.mse_append_total_bytes ?? null,
    mse_append_count: resource.mse_append_count ?? null,
    mse_append_magic: resource.mse_append_magic || "",
    mse_append_mime: resource.mse_append_mime || "",
    mse_append_detected_kind: resource.mse_append_detected_kind || "",
    audio_url: resource.audio_url || "",
    audio_mime: resource.audio_mime || "",
    resolved_url: resource.resolved_url || "",
    initiator: resource.initiator || "",
    time_stamp: resource.time_stamp ?? Date.now(),
    headers: resource.headers || {},
    request_headers: safePersistedRequestHeaders(resource.request_headers || {}),
    request_body: safePersistedRequestBody(resource)
  };
}

async function loadCaptureLog(tabId) {
  if (!chrome.storage?.local?.get || tabId === undefined || tabId < 0) return { resources: [], updated_at: 0 };
  try {
    const key = captureLogStorageKey(tabId);
    const data = await chrome.storage.local.get({ [key]: null });
    const log = data?.[key] || {};
    return {
      resources: Array.isArray(log.resources) ? log.resources : [],
      updated_at: Number(log.updated_at || 0)
    };
  } catch {
    return { resources: [], updated_at: 0 };
  }
}

function persistCaptureResource(tabId, resource = {}) {
  if (!chrome.storage?.local?.get || !chrome.storage?.local?.set || tabId === undefined || tabId < 0) return;
  const persisted = captureLogResource(resource);
  if (!persisted) return;
  (async () => {
    try {
      const key = captureLogStorageKey(tabId);
      const data = await chrome.storage.local.get({ [key]: null });
      const existing = Array.isArray(data?.[key]?.resources) ? data[key].resources : [];
      const merged = mergeAndRankResources([persisted, ...existing], {}, {}, { preserveOrder: false }).slice(0, MAX_CAPTURE_LOG_RESOURCES);
      await chrome.storage.local.set({
        [key]: {
          tab_id: tabId,
          updated_at: Date.now(),
          resources: merged
        }
      });
    } catch {
      // Storage is a recovery cache only; live capture remains in memory.
    }
  })();
}

function clearCaptureLog(tabId) {
  if (!chrome.storage?.local || tabId === undefined || tabId < 0) return;
  const key = captureLogStorageKey(tabId);
  try {
    if (chrome.storage.local.remove) {
      const removed = chrome.storage.local.remove(key);
      if (removed?.catch) removed.catch(() => {});
    } else if (chrome.storage.local.set) {
      const cleared = chrome.storage.local.set({ [key]: null });
      if (cleared?.catch) cleared.catch(() => {});
    }
  } catch {
    // Best effort cleanup.
  }
}

function notifyContextUpdated(tabId, reason = "media") {
  if (tabId < 0 || typeof setTimeout !== "function" || typeof clearTimeout !== "function") return;
  const previous = contextUpdateTimers.get(tabId);
  if (previous) clearTimeout(previous);
  const timer = setTimeout(() => {
    contextUpdateTimers.delete(tabId);
    try {
      const sent = chrome.runtime.sendMessage({
        type: "current-context-updated",
        tabId,
        reason,
        time_stamp: Date.now()
      });
      if (sent?.catch) sent.catch(() => {});
    } catch {
      // Side Panel may be closed; this is only a live refresh hint.
    }
  }, 250);
  contextUpdateTimers.set(tabId, timer);
}

function looksLikeMediaRequest(details) {
  const url = details?.url || "";
  if (details?.type === "media") return true;
  if (classify(url, "") !== "unknown") return true;
  if (/^(xmlhttprequest|fetch)$/i.test(String(details?.type || ""))) {
    const hasRange = (details.requestHeaders || []).some(header =>
      String(header.name || "").toLowerCase() === "range" && /^bytes=/i.test(String(header.value || "").trim())
    );
    if (hasRange) return true;
    if (requestHeaderArrayHasMediaDestination(details.requestHeaders || [])) return true;
  }
  return PLAYBACK_ENDPOINT_RE.test(url);
}

function normalizeRequestHeaders(requestHeaders = []) {
  const headers = {};
  for (const header of requestHeaders || []) {
    const lower = String(header.name || "").toLowerCase();
    if (!REQUEST_HEADER_ALLOWLIST.has(lower)) continue;
    const value = String(header.value || "").replace(/[\r\n]+/g, " ").trim();
    if (!value) continue;
    headers[REQUEST_HEADER_CANONICAL[lower] || header.name] = value;
  }
  return headers;
}

function rememberRequestHeaders(details) {
  if (!details?.requestId || !looksLikeMediaRequest(details)) return;
  const headers = normalizeRequestHeaders(details.requestHeaders || []);
  if (!Object.keys(headers).length) return;
  requestHeadersByRequestId.set(details.requestId, {
    headers,
    time: Date.now()
  });
  if (requestHeadersByRequestId.size <= 300) return;
  const oldest = [...requestHeadersByRequestId.entries()].sort((a, b) => a[1].time - b[1].time).slice(0, 60);
  for (const [requestId] of oldest) requestHeadersByRequestId.delete(requestId);
}

function trimRequestContextCaches() {
  if (requestHeadersByRequestId.size > 300) {
    const oldest = [...requestHeadersByRequestId.entries()].sort((a, b) => a[1].time - b[1].time).slice(0, 60);
    for (const [requestId] of oldest) requestHeadersByRequestId.delete(requestId);
  }
  if (requestBodiesByRequestId.size > 300) {
    const oldest = [...requestBodiesByRequestId.entries()].sort((a, b) => a[1].time - b[1].time).slice(0, 60);
    for (const [requestId] of oldest) requestBodiesByRequestId.delete(requestId);
  }
}

function requestBodyFromFormData(formData = {}) {
  const params = new URLSearchParams();
  for (const [name, values] of Object.entries(formData || {})) {
    for (const value of Array.isArray(values) ? values : [values]) {
      params.append(name, String(value ?? ""));
      if (params.toString().length > MAX_REQUEST_BODY_BYTES) return null;
    }
  }
  const content = params.toString();
  return content ? { type: "form", content } : null;
}

function requestBodyFromRaw(raw = []) {
  const chunks = [];
  let total = 0;
  for (const part of raw || []) {
    if (!part?.bytes) continue;
    const bytes = new Uint8Array(part.bytes);
    total += bytes.byteLength;
    if (total > MAX_REQUEST_BODY_BYTES) return null;
    chunks.push(bytes);
  }
  if (!chunks.length) return null;
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  if (merged.some(byte => byte === 0)) return null;
  const content = new TextDecoder("utf-8", { fatal: false }).decode(merged).trim();
  if (!content || /[\u0000-\u0008\u000e-\u001f]/.test(content)) return null;
  return { type: "text", content };
}

function rememberRequestBody(details = {}) {
  if (!details?.requestId || !looksLikeMediaRequest(details)) return;
  const method = String(details.method || "").toUpperCase();
  if (!["POST", "PUT", "PATCH"].includes(method)) return;
  const body = requestBodyFromFormData(details.requestBody?.formData) || requestBodyFromRaw(details.requestBody?.raw);
  if (!body?.content && !requestBodyHasContent(details)) return;
  requestBodiesByRequestId.set(details.requestId, {
    body: body?.content ? body : { type: "dropped", reason: "too_large_or_binary" },
    time: Date.now()
  });
  trimRequestContextCaches();
}

function takeRequestHeaders(requestId) {
  const entry = requestHeadersByRequestId.get(requestId);
  requestHeadersByRequestId.delete(requestId);
  return entry?.headers || {};
}

function peekRequestHeaders(requestId) {
  return requestHeadersByRequestId.get(requestId)?.headers || {};
}

function peekRequestBody(requestId) {
  return requestBodiesByRequestId.get(requestId)?.body || {};
}

function takeRequestContext(requestId) {
  const headers = takeRequestHeaders(requestId);
  const body = peekRequestBody(requestId);
  requestBodiesByRequestId.delete(requestId);
  return { headers, body };
}

function frameStates(tabId) {
  if (!pageStateByTab.has(tabId)) pageStateByTab.set(tabId, new Map());
  return pageStateByTab.get(tabId);
}

function normalizeBrowserSubtitles(items = []) {
  const normalized = [];
  const seen = new Set();
  for (const item of items || []) {
    const text = String(item?.text || "").replace(/\s+/g, " ").trim();
    if (!text) continue;
    const start = Number(item.start ?? 0);
    const end = Number(item.end ?? start);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const cue = {
      start: Math.max(0, start),
      end: Math.max(start, end),
      text
    };
    const key = `${Math.round(cue.start * 1000)}|${Math.round(cue.end * 1000)}|${cue.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    normalized.push(cue);
  }
  return normalized.sort((a, b) => a.start - b.start || a.end - b.end);
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

function bestPageTitle(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text && !isUnreadableTitle(text)) return text;
  }
  return "";
}

function normalizePageForFrame(page = {}, frameId = 0, tab = {}) {
  const normalized = {
    title: bestPageTitle(page.title, tab.title),
    page_url: page.page_url || tab.url || "",
    page_text: page.page_text || "",
    active_video: page.active_video || null,
    browser_subtitles: normalizeBrowserSubtitles(page.browser_subtitles),
    resources: Array.isArray(page.resources) ? page.resources : [],
    drm_detected: Boolean(page.drm_detected),
    drm_signals: Array.isArray(page.drm_signals) ? page.drm_signals : [],
    frame_id: frameId
  };
  if (normalized.active_video) {
    normalized.active_video = {
      ...normalized.active_video,
      frame_id: frameId,
      frame_url: normalized.active_video.frame_url || normalized.page_url || ""
    };
  }
  normalized.resources = normalized.resources.map(resource => ({
    ...resource,
    frame_id: resource.frame_id ?? frameId,
    frame_url: resource.frame_url || normalized.page_url || "",
    page_url: resource.page_url || normalized.page_url || ""
  }));
  normalized.drm_signals = normalized.drm_signals.map(signal => ({
    ...signal,
    frame_id: signal.frame_id ?? frameId,
    page_url: signal.page_url || normalized.page_url || ""
  }));
  return normalized;
}

function rememberFramePage(tabId, frameId, page, tab = {}) {
  const normalized = normalizePageForFrame(page, frameId, tab);
  frameStates(tabId).set(frameId, normalized);
  return normalized;
}

function hasActiveVideoSignal(page = {}) {
  const active = page.active_video || null;
  return Boolean(active?.src || active?.src_object);
}

function mergePageContexts(tab = {}, pages = []) {
  const byFrame = new Map();
  for (const page of pages) {
    if (!page) continue;
    byFrame.set(page.frame_id ?? 0, page);
  }
  const ordered = [...byFrame.values()].sort((a, b) => (a.frame_id ?? 0) - (b.frame_id ?? 0));
  const top = ordered.find(page => (page.frame_id ?? 0) === 0) || ordered[0] || {};
  const activePage = ordered.find(page => hasActiveVideoSignal(page) && !page.active_video.paused) ||
    ordered.find(hasActiveVideoSignal) ||
    null;
  const textParts = [];
  const seenText = new Set();
  const browserSubtitles = [];
  const seenSubtitle = new Set();
  const drmSignals = [];
  const seenDrm = new Set();
  for (const page of ordered) {
    const text = (page.page_text || "").trim();
    if (!text || seenText.has(text)) continue;
    seenText.add(text);
    textParts.push(text);
  }
  for (const page of ordered) {
    for (const cue of normalizeBrowserSubtitles(page.browser_subtitles || [])) {
      const key = `${Math.round(cue.start * 1000)}|${Math.round(cue.end * 1000)}|${cue.text}`;
      if (seenSubtitle.has(key)) continue;
      seenSubtitle.add(key);
      browserSubtitles.push(cue);
      if (browserSubtitles.length >= 2000) break;
    }
    if (browserSubtitles.length >= 2000) break;
  }
  for (const page of ordered) {
    for (const signal of page.drm_signals || []) {
      const key = [signal.source, signal.key_system, signal.init_data_type, signal.label, signal.frame_id].join("|");
      if (seenDrm.has(key)) continue;
      seenDrm.add(key);
      drmSignals.push(signal);
    }
  }
  return {
    title: bestPageTitle(top.title, activePage?.title, tab.title),
    page_url: top.page_url || tab.url || activePage?.page_url || "",
    page_text: textParts.join("\n\n--- iframe ---\n\n").slice(0, 60000),
    active_video: activePage?.active_video || null,
    browser_subtitles: browserSubtitles.sort((a, b) => a.start - b.start || a.end - b.end),
    drm_detected: ordered.some(page => page.drm_detected || page.active_video?.drm_detected) || drmSignals.length > 0,
    drm_signals: drmSignals.slice(0, 20),
    resources: ordered.flatMap(page => page.resources || []),
    frames: ordered.map(page => ({
      frame_id: page.frame_id ?? 0,
      title: page.title || "",
      page_url: page.page_url || "",
      has_active_video: hasActiveVideoSignal(page),
      drm_detected: Boolean(page.drm_detected || page.active_video?.drm_detected),
      resource_count: (page.resources || []).length
    }))
  };
}

function addResource(tabId, resource, notify = true) {
  if (tabId < 0 || !resource?.url) return;
  const list = resourceByTab.get(tabId) || [];
  const existing = list.find(item => item.url === resource.url);
  const kind = resource.kind || classify(resource.url, resource.mime);
  const rawScore = resource.source === "manifest-guess"
    ? Math.min(72, Math.max(0, Number(resource.score || 0)))
    : Math.max(resource.score || 0, scoreKind(resource.url, resource.source || "", kind), playableEndpointScore({ ...resource, kind }));
  const normalized = {
    url: resource.url,
    source: resource.source || "unknown",
    kind,
    mime: resource.mime || "",
    score: rawScore,
    label: resource.label || "",
    user_selected: Boolean(resource.user_selected),
    is_main_video: Boolean(resource.is_main_video),
    playback_match: resource.playback_match || "",
    blob_url: resource.blob_url || "",
    frame_url: resource.frame_url || "",
    page_url: resource.page_url || "",
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
    mse_append_bytes: resource.mse_append_bytes ?? null,
    mse_append_total_bytes: resource.mse_append_total_bytes ?? null,
    mse_append_count: resource.mse_append_count ?? null,
    mse_append_magic: resource.mse_append_magic || "",
    mse_append_mime: resource.mse_append_mime || "",
    mse_append_detected_kind: resource.mse_append_detected_kind || "",
    audio_url: resource.audio_url || "",
    audio_mime: resource.audio_mime || "",
    resolved_url: resource.resolved_url || "",
    initiator: resource.initiator || "",
    time_stamp: resource.time_stamp ?? null,
    headers: resource.headers || {},
    request_headers: resource.request_headers || {},
    request_body: resource.request_body || {}
  };
  if (existing) {
    Object.assign(existing, normalized, {
      score: Math.max(existing.score || 0, normalized.score),
      user_selected: Boolean(existing.user_selected || normalized.user_selected),
      is_main_video: Boolean(existing.is_main_video || normalized.is_main_video),
      playback_match: existing.playback_match || normalized.playback_match || "",
      blob_url: normalized.blob_url || existing.blob_url || "",
      frame_url: normalized.frame_url || existing.frame_url || "",
      page_url: normalized.page_url || existing.page_url || "",
      current_time: normalized.current_time ?? existing.current_time ?? null,
      duration: normalized.duration ?? existing.duration ?? null,
      width: normalized.width ?? existing.width ?? null,
      height: normalized.height ?? existing.height ?? null,
      status_code: normalized.status_code ?? existing.status_code ?? null,
      content_length: normalized.content_length ?? existing.content_length ?? null,
      mse_append_bytes: normalized.mse_append_bytes ?? existing.mse_append_bytes ?? null,
      mse_append_total_bytes: normalized.mse_append_total_bytes ?? existing.mse_append_total_bytes ?? null,
      mse_append_count: normalized.mse_append_count ?? existing.mse_append_count ?? null,
      mse_append_magic: normalized.mse_append_magic || existing.mse_append_magic || "",
      mse_append_mime: normalized.mse_append_mime || existing.mse_append_mime || "",
      mse_append_detected_kind: normalized.mse_append_detected_kind || existing.mse_append_detected_kind || "",
      audio_url: normalized.audio_url || existing.audio_url || "",
      audio_mime: normalized.audio_mime || existing.audio_mime || "",
      resolved_url: normalized.resolved_url || existing.resolved_url || "",
      request_type: normalized.request_type || existing.request_type || "",
      method: normalized.method || existing.method || "",
      initiator: normalized.initiator || existing.initiator || "",
      time_stamp: normalized.time_stamp ?? existing.time_stamp ?? null,
      headers: { ...(existing.headers || {}), ...(normalized.headers || {}) },
      request_headers: { ...(existing.request_headers || {}), ...(normalized.request_headers || {}) },
      request_body: { ...(existing.request_body || {}), ...(normalized.request_body || {}) }
    });
  } else {
    list.unshift(normalized);
  }
  resourceByTab.set(tabId, list.slice(0, 80));
  persistCaptureResource(tabId, normalized);

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
    }, notify);
  }
  if (normalized.kind === "fragment" && !inferredUrl) {
    for (const guessedUrl of inferSiblingManifestUrls(normalized.url)) {
      const guessedKind = classify(guessedUrl, "");
      addResource(tabId, {
        ...normalized,
        url: guessedUrl,
        source: "manifest-guess",
        kind: guessedKind,
        mime: guessedKind === "hls" ? "application/vnd.apple.mpegurl" : "application/dash+xml",
        label: guessedKind === "hls" ? "Guessed HLS manifest from segment directory" : "Guessed DASH manifest from segment directory",
        score: Math.min(72, Math.max(42, (normalized.score || 0) + 18)),
        playback_match: normalized.playback_match || "inferred-from-fragment",
        request_type: normalized.request_type || "fragment-guess"
      }, notify);
    }
  }
  if (notify) notifyContextUpdated(tabId, "media");
}

function registerBeforeSendHeadersListener(options) {
  chrome.webRequest.onBeforeSendHeaders.addListener(
    rememberRequestHeaders,
    { urls: ["<all_urls>"] },
    options
  );
}

if (chrome.webRequest.onBeforeRequest?.addListener) {
  chrome.webRequest.onBeforeRequest.addListener(
    rememberRequestBody,
    { urls: ["<all_urls>"] },
    ["requestBody"]
  );
}

try {
  registerBeforeSendHeadersListener(["requestHeaders", "extraHeaders"]);
} catch {
  registerBeforeSendHeadersListener(["requestHeaders"]);
}

function responseHeadersObject(responseHeaders = []) {
  const headers = {};
  for (const header of responseHeaders || []) {
    const lower = String(header.name || "").toLowerCase();
    if (RESPONSE_HEADER_ALLOWLIST.has(lower)) {
      const value = String(header.value || "").replace(/[\r\n]+/g, " ").trim();
      if (value) headers[lower] = value;
    }
  }
  return headers;
}

function responseResolvedUrl(url = "", headers = {}) {
  const raw = headers.location || headers["content-location"] || "";
  if (!raw) return "";
  try {
    return new URL(raw, url).href;
  } catch {
    return "";
  }
}

function isLocalLearnNoteTaskFile(url = "") {
  return LOCAL_TASK_FILE_RE.test(String(url || ""));
}

function recordResponseMedia(details = {}, requestHeaders = {}, requestBody = peekRequestBody(details.requestId)) {
  if (isLocalLearnNoteTaskFile(details.url || "")) return;
  const headers = responseHeadersObject(details.responseHeaders || []);
  const mime = headers["content-type"] || "";
  const kind = classifyCompletedRequest(details, mime, requestHeaders, headers);
  if (kind === "unknown") return;
  const contentLength = Number(headers["content-length"] || 0);
  const resolvedUrl = responseResolvedUrl(details.url || "", headers);
  const resource = {
    url: details.url,
    resolved_url: resolvedUrl,
    source: "webRequest",
    kind,
    mime,
    headers,
    request_type: details.type || "",
    method: details.method || "",
    status_code: details.statusCode || null,
    content_length: Number.isFinite(contentLength) && contentLength > 0 ? contentLength : null,
    initiator: details.initiator || "",
    frame_id: details.frameId ?? null,
    frame_url: details.documentUrl || "",
    page_url: details.documentUrl || details.initiator || "",
    time_stamp: details.timeStamp || Date.now(),
    request_headers: requestHeaders,
    request_body: requestBody || {},
    label: kind.toUpperCase()
  };
  addResource(details.tabId, resource, false);
  addResolvedMediaResource(details.tabId, resource);
  notifyContextUpdated(details.tabId, "media");
}

function recordRedirectMedia(details = {}, requestHeaders = {}, requestBody = peekRequestBody(details.requestId)) {
  if (isLocalLearnNoteTaskFile(details.url || "") || isLocalLearnNoteTaskFile(details.redirectUrl || "")) return;
  const headers = responseHeadersObject(details.responseHeaders || []);
  const redirectUrl = details.redirectUrl || responseResolvedUrl(details.url || "", headers);
  if (isLocalLearnNoteTaskFile(redirectUrl)) return;
  if (redirectUrl && !headers.location) headers.location = redirectUrl;
  const mime = headers["content-type"] || "";
  const redirectKind = classify(redirectUrl, mime);
  const currentKind = classifyCompletedRequest(details, mime, requestHeaders, headers);
  const kind = redirectKind !== "unknown" ? redirectKind : currentKind;
  if (kind === "unknown") return;
  const contentLength = Number(headers["content-length"] || 0);
  const resource = {
    url: details.url,
    resolved_url: redirectUrl || "",
    source: "webRequest",
    kind,
    mime,
    headers,
    request_type: details.type || "",
    method: details.method || "",
    status_code: details.statusCode || null,
    content_length: Number.isFinite(contentLength) && contentLength > 0 ? contentLength : null,
    initiator: details.initiator || "",
    frame_id: details.frameId ?? null,
    frame_url: details.documentUrl || "",
    page_url: details.documentUrl || details.initiator || "",
    time_stamp: details.timeStamp || Date.now(),
    request_headers: requestHeaders,
    request_body: requestBody || {},
    label: `${kind.toUpperCase()} redirect`
  };
  addResource(details.tabId, resource, false);
  addResolvedMediaResource(details.tabId, resource);
  notifyContextUpdated(details.tabId, "media");
}

function addResolvedMediaResource(tabId, resource = {}) {
  const resolvedUrl = String(resource.resolved_url || "").trim();
  if (!resolvedUrl || resolvedUrl === resource.url || isLocalLearnNoteTaskFile(resolvedUrl)) return;
  const resolvedKind = classify(resolvedUrl, resource.mime || "");
  if (!isDownloadableKind(resolvedKind)) return;
  addResource(tabId, {
    ...resource,
    url: resolvedUrl,
    resolved_url: "",
    source: "webRequestResolved",
    kind: resolvedKind,
    label: `${resolvedKind.toUpperCase()} final URL`,
    score: Math.min(100, Number(resource.score || scoreKind(resolvedUrl, "webRequestResolved", resolvedKind)) + 10),
    playback_match: resource.playback_match || "resolved-final-url"
  }, false);
}

function registerHeadersReceivedListener(options) {
  chrome.webRequest.onHeadersReceived.addListener(
    details => recordResponseMedia(details, peekRequestHeaders(details.requestId), peekRequestBody(details.requestId)),
    { urls: ["<all_urls>"] },
    options
  );
}

try {
  registerHeadersReceivedListener(["responseHeaders", "extraHeaders"]);
} catch {
  registerHeadersReceivedListener(["responseHeaders"]);
}

function registerBeforeRedirectListener(options) {
  chrome.webRequest.onBeforeRedirect.addListener(
    details => recordRedirectMedia(details, peekRequestHeaders(details.requestId), peekRequestBody(details.requestId)),
    { urls: ["<all_urls>"] },
    options
  );
}

try {
  registerBeforeRedirectListener(["responseHeaders", "extraHeaders"]);
} catch {
  registerBeforeRedirectListener(["responseHeaders"]);
}

chrome.webRequest.onCompleted.addListener(
  details => {
    const context = takeRequestContext(details.requestId);
    recordResponseMedia(details, context.headers, context.body);
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

chrome.webRequest.onErrorOccurred.addListener(
  details => takeRequestContext(details.requestId),
  { urls: ["<all_urls>"] }
);

chrome.tabs.onRemoved.addListener(tabId => {
  resourceByTab.delete(tabId);
  pageStateByTab.delete(tabId);
  clearCaptureLog(tabId);
  const timer = contextUpdateTimers.get(tabId);
  if (timer) clearTimeout(timer);
  contextUpdateTimers.delete(tabId);
});
if (chrome.tabs.onActivated?.addListener) {
  chrome.tabs.onActivated.addListener(activeInfo => {
    if (activeInfo?.tabId !== undefined) notifyContextUpdated(activeInfo.tabId, "tab-activated");
  });
}
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" || changeInfo.url) {
    resourceByTab.delete(tabId);
    pageStateByTab.delete(tabId);
    clearCaptureLog(tabId);
    const timer = contextUpdateTimers.get(tabId);
    if (timer) clearTimeout(timer);
    contextUpdateTimers.delete(tabId);
    notifyContextUpdated(tabId, "navigation");
  }
});
chrome.action.onClicked.addListener(tab => {
  const intent = {
    action: "summarize-current-video",
    tabId: tab?.id ?? null,
    createdAt: Date.now()
  };
  chrome.storage?.local?.set?.({ pendingSidePanelIntent: intent });
  chrome.runtime.sendMessage?.({ type: "sidepanel-action-intent", intent }).catch?.(() => {});
  if (chrome.sidePanel?.open) chrome.sidePanel.open({ tabId: tab.id });
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function tabForMessage(message = {}) {
  const targetTabId = Number(message.targetTabId ?? message.tabId);
  if (Number.isFinite(targetTabId) && targetTabId >= 0) {
    try {
      const tab = await chrome.tabs.get(targetTabId);
      if (tab?.id !== undefined) return tab;
    } catch {
      // The tab may have been closed; fall back to the active tab.
    }
  }
  return activeTab();
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
    for (const resource of page.resources || []) addResource(tab.id, resource, false);
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
          browser_subtitles: [],
          drm_detected: false,
          drm_signals: [],
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

globalThis.__learnnoteE2E = {
  async collectContextForTab(tabId) {
    const tab = await chrome.tabs.get(Number(tabId));
    const page = await collectPageData(tab);
    const captureLog = await loadCaptureLog(tab.id);
    const resources = mergeAndRankResources([
      ...(page.resources || []),
      ...(resourceByTab.get(tab.id) || []),
      ...(captureLog.resources || [])
    ], page, tab);
    return {
      tab: { id: tab.id, url: tab.url || "", title: tab.title || "", status: tab.status || "" },
      page,
      resources,
      capture_log: {
        total: Number(captureLog.resources?.length || 0),
        restored: Number(captureLog.resources?.length || 0)
      }
    };
  },
  async preflightCurrentPageForTab(tabId, backendUrl, selectedResources = [], probeLimit = 5) {
    const context = await globalThis.__learnnoteE2E.collectContextForTab(tabId);
    const tab = await chrome.tabs.get(Number(tabId));
    const page = context.page || {};
    const resources = mergeAndRankResources(
      Array.isArray(selectedResources) && selectedResources.length ? selectedResources : context.resources,
      page,
      tab,
      { preserveOrder: Array.isArray(selectedResources) && selectedResources.length > 0 }
    );
    const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
    const cookies = await cookiesForUrls(cookieUrlsForContext(page, tab, resources), partitionKeys);
    const res = await fetch(`${backendUrl}/api/media/preflight-current-page`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_url: page.page_url || tab.url,
        resources,
        cookies,
        probe_limit: probeLimit
      })
    });
    const payload = await backendJsonResponse(res, "当前页预检失败。");
    return {
      ...payload,
      e2e_resource_count: resources.length,
      e2e_cookie_count: cookies.length
    };
  },
  async inspectCookieContextForTab(tabId, selectedResources = []) {
    const context = await globalThis.__learnnoteE2E.collectContextForTab(tabId);
    const tab = await chrome.tabs.get(Number(tabId));
    const page = context.page || {};
    const resources = mergeAndRankResources(
      Array.isArray(selectedResources) && selectedResources.length ? selectedResources : context.resources,
      page,
      tab,
      { preserveOrder: Array.isArray(selectedResources) && selectedResources.length > 0 }
    );
    const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
    const urls = cookieUrlsForContext(page, tab, resources);
    const cookies = await cookiesForUrls(urls, partitionKeys);
    return cookieContextSummary(cookies, urls, partitionKeys);
  },
  async startCurrentPageTaskForTab(tabId, backendUrl, selectedResources = [], mode = "download_only", options = {}) {
    const context = await globalThis.__learnnoteE2E.collectContextForTab(tabId);
    const tab = await chrome.tabs.get(Number(tabId));
    const page = context.page || {};
    const resources = mergeAndRankResources(selectedResources, page, tab, { preserveOrder: Array.isArray(selectedResources) });
    const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
    const cookies = await cookiesForUrls(cookieUrlsForContext(page, tab, resources), partitionKeys);
    const res = await fetch(`${backendUrl}/api/tasks/from-current-page`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        page_url: page.page_url || tab.url,
        title: bestPageTitle(page.title, tab.title),
        page_text: page.page_text || "",
        active_video: page.active_video || null,
        browser_subtitles: page.browser_subtitles || [],
        drm_detected: Boolean(page.drm_detected),
        drm_signals: page.drm_signals || [],
        resources,
        cookies,
        options
      })
    });
    const payload = await backendJsonResponse(res, "当前页任务创建失败。");
    return {
      ...payload,
      e2e_resource_count: resources.length,
      e2e_cookie_count: cookies.length
    };
  }
};

function normalizedCookiePartitionKey(key = null) {
  if (!key || typeof key !== "object") return null;
  const normalized = {};
  if (typeof key.topLevelSite === "string" && key.topLevelSite) normalized.topLevelSite = key.topLevelSite;
  if (typeof key.hasCrossSiteAncestor === "boolean") normalized.hasCrossSiteAncestor = key.hasCrossSiteAncestor;
  return Object.keys(normalized).length ? normalized : null;
}

function cookiePartitionKeyId(key = null) {
  const normalized = normalizedCookiePartitionKey(key);
  return normalized ? JSON.stringify(normalized) : "";
}

function cookiePartitionPreference(partitionKeys = []) {
  const ranks = new Map();
  for (const partitionKey of partitionKeys || []) {
    const id = cookiePartitionKeyId(partitionKey);
    if (id && !ranks.has(id)) ranks.set(id, ranks.size);
  }
  return ranks;
}

async function cookiePartitionKeysForContext(page = {}, tab = {}, resources = []) {
  if (!chrome.cookies?.getPartitionKey || !Number.isFinite(tab.id)) return [];
  const frameIds = [];
  const addFrameId = value => {
    const frameId = Number(value);
    if (!Number.isFinite(frameId) || frameId < 0 || frameIds.includes(frameId)) return;
    frameIds.push(frameId);
  };
  addFrameId(0);
  addFrameId(page.active_video?.frame_id);
  for (const frame of page.frames || []) addFrameId(frame.frame_id);
  for (const resource of resources || []) addFrameId(resource.frame_id);

  const keys = [];
  const seen = new Set();
  for (const frameId of frameIds) {
    try {
      const key = normalizedCookiePartitionKey(await chrome.cookies.getPartitionKey({ tabId: tab.id, frameId }));
      if (!key) continue;
      const id = JSON.stringify(key);
      if (seen.has(id)) continue;
      seen.add(id);
      keys.push(key);
    } catch {
      // Older browsers or inaccessible frames can continue with unpartitioned cookies.
    }
  }
  return keys;
}

function cookieLookupDetailsForUrls(urls, partitionKeys = []) {
  const details = [];
  const seen = new Set();
  const add = detail => {
    const key = JSON.stringify(detail);
    if (seen.has(key)) return;
    seen.add(key);
    details.push(detail);
  };
  const addWithPartitions = detail => {
    for (const partitionKey of partitionKeys || []) {
      const normalized = normalizedCookiePartitionKey(partitionKey);
      if (normalized) add({ ...detail, partitionKey: normalized });
    }
    add(detail);
  };

  for (const raw of urls || []) {
    const url = cookieEligibleUrl(raw);
    if (!/^https?:\/\//i.test(url)) continue;
    addWithPartitions({ url });
    for (const domain of cookieDomainCandidates(url)) {
      addWithPartitions({ domain });
    }
  }
  return details;
}

async function cookiesForUrls(urls, partitionKeys = []) {
  const exactCookies = new Map();
  const partitionRanks = cookiePartitionPreference(partitionKeys);
  let ordinal = 0;
  for (const details of cookieLookupDetailsForUrls(urls, partitionKeys)) {
    try {
      const cookies = await chrome.cookies.getAll(details);
      for (const cookie of cookies) {
        const partitionKey = normalizedCookiePartitionKey(cookie.partitionKey) || normalizedCookiePartitionKey(details.partitionKey);
        const normalizedCookie = partitionKey ? { ...cookie, partitionKey } : { ...cookie };
        const partitionId = cookiePartitionKeyId(partitionKey);
        const key = `${normalizedCookie.domain}|${normalizedCookie.path}|${normalizedCookie.name}|${partitionId}`;
        if (!exactCookies.has(key)) {
          exactCookies.set(key, {
            cookie: normalizedCookie,
            partitionId,
            ordinal: ordinal++
          });
        }
      }
    } catch {
      // Ignore browser-internal, malformed, or unsupported cookie lookups.
    }
  }

  const grouped = new Map();
  const hasPreferredPartitions = partitionRanks.size > 0;
  for (const record of exactCookies.values()) {
    const cookie = record.cookie;
    const identity = `${cookie.domain}|${cookie.path}|${cookie.name}`;
    const partitionRank = partitionRanks.has(record.partitionId) ? partitionRanks.get(record.partitionId) : null;
    const partitionScore = partitionRank !== null
      ? 10000 - partitionRank
      : (record.partitionId ? 5000 : (hasPreferredPartitions ? 0 : 1000));
    const scored = { ...record, score: partitionScore };
    const previous = grouped.get(identity);
    if (!previous || scored.score > previous.score || (scored.score === previous.score && scored.ordinal < previous.ordinal)) {
      grouped.set(identity, scored);
    }
  }

  return [...grouped.values()]
    .sort((left, right) => left.ordinal - right.ordinal)
    .map(record => record.cookie);
}

function cookieContextSummary(cookies = [], urls = [], partitionKeys = []) {
  const domains = new Map();
  let partitioned = 0;
  for (const cookie of cookies || []) {
    const domain = String(cookie.domain || "").replace(/^\./, "") || "(host)";
    domains.set(domain, (domains.get(domain) || 0) + 1);
    if (cookie.partitionKey) partitioned += 1;
  }
  const domainSummary = [...domains.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 8)
    .map(([domain, count]) => ({ domain, count }));
  return {
    count: cookies.length,
    domain_count: domains.size,
    partitioned_count: partitioned,
    partition_key_count: partitionKeys.length,
    target_count: urls.length,
    domains: domainSummary
  };
}

function cookieUrlsForContext(page = {}, tab = {}, resources = []) {
  const urls = [];
  const add = value => {
    const url = cookieEligibleUrl(value);
    if (!url) return;
    if (!urls.includes(url)) urls.push(url);
  };

  add(page.page_url);
  add(tab.url);
  add(page.active_video?.src);
  add(page.active_video?.frame_url);
  for (const frame of page.frames || []) {
    add(frame.page_url);
  }

  for (const resource of resources || []) {
    add(resource.url);
    add(resource.resolved_url);
    add(resource.page_url);
    add(resource.frame_url);
    add(resource.initiator);
    add(resource.blob_url);
    const headers = resource.request_headers || {};
    for (const [name, value] of Object.entries(headers)) {
      if (/^(referer|origin)$/i.test(name)) add(value);
    }
    const responseHeaders = resource.headers || {};
    for (const [name, value] of Object.entries(responseHeaders)) {
      if (/^(location|content-location)$/i.test(name)) add(value);
    }
  }
  return urls;
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
      notifyContextUpdated(tabId, "page");
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "get-current-context") {
      const tab = await tabForMessage(message);
      const page = await collectPageData(tab);
      const activePage = page;
      const captureLog = await loadCaptureLog(tab.id);
      const resources = mergeAndRankResources([
        ...(page.resources || []),
        ...(resourceByTab.get(tab.id) || []),
        ...(captureLog.resources || [])
      ], activePage, tab).slice(0, 30);
      sendResponse({
        tab,
        page: activePage,
        resources,
        capture_log: {
          total: captureLog.resources.length,
          restored: captureLog.resources.length,
          updated_at: captureLog.updated_at
        }
      });
      return;
    }

    if (message.type === "inspect-cookie-context") {
      const tab = await tabForMessage(message);
      const page = message.page || await collectPageData(tab);
      const resources = mergeAndRankResources(message.resources, page, tab, { preserveOrder: Array.isArray(message.resources) });
      const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
      const urls = cookieUrlsForContext(page, tab, resources);
      const cookies = await cookiesForUrls(urls, partitionKeys);
      sendResponse({
        ok: true,
        cookie_context: cookieContextSummary(cookies, urls, partitionKeys)
      });
      return;
    }

    if (message.type === "start-current-task") {
      const tab = await tabForMessage(message);
      const page = message.page || await collectPageData(tab);
      const resources = mergeAndRankResources(message.resources, page, tab, { preserveOrder: Array.isArray(message.resources) });
      const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
      const cookies = await cookiesForUrls(cookieUrlsForContext(page, tab, resources), partitionKeys);
      const backendUrl = message.backendUrl || "http://127.0.0.1:8765";
      const res = await fetch(`${backendUrl}/api/tasks/from-current-page`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: message.mode || "video",
          page_url: page.page_url || tab.url,
          title: bestPageTitle(page.title, tab.title),
          page_text: page.page_text || "",
          page_preflight_report: message.pagePreflightReport || {},
          active_video: page.active_video || null,
          browser_subtitles: page.browser_subtitles || [],
          drm_detected: Boolean(page.drm_detected),
          drm_signals: page.drm_signals || [],
          resources,
          cookies,
          options: message.options || {}
        })
      });
      sendResponse(await backendJsonResponse(res, "预检候选资源失败。"));
      return;
    }

    if (message.type === "preflight-current-resource") {
      const tab = await tabForMessage(message);
      const page = message.page || await collectPageData(tab);
      const resource = mergeAndRankResources(message.resource ? [message.resource] : [], page, tab, { preserveOrder: true })[0];
      if (!resource?.url) {
        sendResponse({ error: "没有可预检的候选资源。" });
        return;
      }
      const partitionKeys = await cookiePartitionKeysForContext(page, tab, [resource]);
      const cookies = await cookiesForUrls(cookieUrlsForContext(page, tab, [resource]), partitionKeys);
      const backendUrl = message.backendUrl || "http://127.0.0.1:8765";
      const res = await fetch(`${backendUrl}/api/media/preflight`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_url: page.page_url || tab.url,
          resource,
          cookies
        })
      });
      sendResponse(await backendJsonResponse(res, "整页预检失败。"));
      return;
    }

    if (message.type === "preflight-current-page") {
      const tab = await tabForMessage(message);
      const page = message.page || await collectPageData(tab);
      const resources = mergeAndRankResources(message.resources, page, tab, { preserveOrder: Array.isArray(message.resources) });
      const partitionKeys = await cookiePartitionKeysForContext(page, tab, resources);
      const cookies = await cookiesForUrls(cookieUrlsForContext(page, tab, resources), partitionKeys);
      const backendUrl = message.backendUrl || "http://127.0.0.1:8765";
      const res = await fetch(`${backendUrl}/api/media/preflight-current-page`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_url: page.page_url || tab.url,
          active_video: page.active_video || null,
          resources,
          cookies,
          drm_detected: Boolean(page.drm_detected),
          probe_limit: message.probeLimit ?? 3
        })
      });
      sendResponse(await backendJsonResponse(res, "创建当前页任务失败。"));
      return;
    }

    if (message.type === "download-task-export") {
      const url = String(message.url || "");
      if (!LOCAL_EXPORT_RE.test(url)) {
        sendResponse({ ok: false, error: "只允许下载本地 LearnNote 导出文件。" });
        return;
      }
      if (!chrome.downloads?.download) {
        sendResponse({ ok: false, error: "当前浏览器不支持扩展直接下载。" });
        return;
      }
      chrome.downloads.download({ url, saveAs: false }, downloadId => {
        const error = chrome.runtime.lastError?.message;
        sendResponse(error ? { ok: false, error } : { ok: true, downloadId });
      });
      return;
    }
  })().catch(error => sendResponse({ error: String(error?.message || error) }));
  return true;
});
