const VIDEO_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const AUDIO_RE = /\.(m4a|mp3|aac|opus|ogg|oga|wav)(\?|#|$)/i;
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const MEDIA_EXT_PATTERN = "mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa";
const MEDIA_URL_RE = new RegExp(`(?:https?:)?//[^\\s"'<>\\\\]+\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?|(?:/[^\\s"'<>\\\\]+)\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?`, "gi");
const ENCODED_MEDIA_URL_RE = new RegExp(`https?%(?:25)*3A(?:(?:%(?:25)*2F)|/){2}[^\\s"'<>\\\\]+?(?:\\.|%(?:25)*2E)(?:${MEDIA_EXT_PATTERN})(?:[^\\s"'<>\\\\]*)?`, "gi");
const STATIC_MEDIA_ATTRS = [
  "src",
  "href",
  "data-src",
  "data-url",
  "data-video-url",
  "data-audio-url",
  "data-play-url",
  "data-path",
  "data-uri",
  "data-media-url",
  "data-stream-url",
  "data-hls-url",
  "data-player",
  "data-player-config",
  "data-config",
  "data-options",
  "data-param",
  "data-params",
  "data-info",
  "data-other",
  "data-otherinfo",
  "data-objectid",
  "data-dtoken",
  "data-m3u8",
  "data-mpd",
  "data-file",
  "data-source",
  "data-sources",
  "onclick",
  "value"
];
const STATIC_MEDIA_SELECTOR = STATIC_MEDIA_ATTRS.map(name => `[${name}]`).join(",");
const STATIC_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*["']((?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^"'<>\\\s]){4,})["']/gi;
const STATIC_CONTAINER_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*[\[{]/gi;
const STATIC_QUOTED_VALUE_RE = /["']((?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^"'<>\\\s]){4,})["']/gi;
const STATIC_MEDIA_KEY_RE = /(url|uri|path|src|file|fileid|objectid|dtoken|download|httpmd|play|media|video|audio|stream|source|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
const STATIC_ATTRIBUTE_KEY_RE = /(url|uri|path|src|file|objectid|dtoken|download|httpmd|play|player|config|option|param|media|video|audio|stream|source|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
const VISIBLE_SUBTITLE_HINT_RE = /(subtitle|subtitles|caption|captions|closed.?caption|texttrack|danmu|danmaku|barrage|\bcc\b|字幕|弹幕)/i;
const VISIBLE_SUBTITLE_ROLE_RE = /^(log|status|marquee)$/i;
const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;
const boundVideos = new WeakSet();
const boundTextTracks = new WeakSet();
const boundTextTrackLists = new WeakSet();
const hookResources = [];
const drmSignals = [];
const drmByVideo = new WeakMap();
const observedMutationRoots = new WeakSet();
const DEEP_QUERY_LIMIT = 2500;
const MAX_VISIBLE_SUBTITLE_HISTORY = 1200;
const visibleSubtitleHistory = [];
let pendingPushTimer = 0;
let lastPushAt = 0;
let lastSignature = "";
let watchersStarted = false;

function classify(url, mime = "") {
  const lower = String(url || "").toLowerCase();
  const type = String(mime || "").toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || VIDEO_RE.test(lower)) return "video";
  if (type.includes("audio/") || AUDIO_RE.test(lower)) return "audio";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower)) return "subtitle";
  return "unknown";
}

function inferManifestUrl(url) {
  try {
    const parsed = new URL(url, location.href);
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

function score(url, mime, source) {
  const kind = classify(url, mime);
  let value = 0;
  if (kind === "hls" || kind === "dash") value += 95;
  else if (kind === "video") value += 85;
  else if (kind === "audio") value += 35;
  else if (kind === "fragment") value += 15;
  else if (kind === "subtitle") value += 60;
  else if (kind === "blob") value += 5;
  if (source === "dom") value += 8;
  if (source === "activeVideo") value += 16;
  if (String(source || "").startsWith("pageHook")) value += 12;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
}

function scoreForKind(kind, scores = {}) {
  if (kind === "hls" || kind === "dash") return scores.manifest ?? 96;
  if (kind === "video") return scores.video ?? 86;
  if (kind === "audio") return scores.audio ?? 38;
  if (kind === "subtitle") return scores.subtitle ?? 62;
  return scores.other ?? 62;
}

function absoluteUrl(url) {
  if (!url) return "";
  if (url.startsWith("blob:")) return url;
  try {
    return new URL(decodeRepeatedUrlComponent(stripUrlTail(url)), location.href).href;
  } catch {
    return "";
  }
}

function stripUrlTail(value) {
  let text = String(value || "").trim();
  const absoluteIndex = text.search(/https?:\/\//i);
  if (absoluteIndex > 0) text = text.slice(absoluteIndex);
  if (!/^(https?:)?\/\//i.test(text)) {
    const rootRelativeIndex = text.search(new RegExp(`/[^\\s"'<>\\\\]+\\.(?:${MEDIA_EXT_PATTERN})(?:[?#]|$)`, "i"));
    if (rootRelativeIndex > 0) text = text.slice(rootRelativeIndex);
  }
  while (/[;,]/.test(text.at(-1) || "")) text = text.slice(0, -1);
  const pairs = { ")": "(", "]": "[", "}": "{" };
  while (text) {
    const close = text.at(-1);
    const open = pairs[close];
    if (!open) break;
    const opens = text.split(open).length - 1;
    const closes = text.split(close).length - 1;
    if (closes <= opens) break;
    text = text.slice(0, -1);
  }
  return text;
}

function decodeRepeatedUrlComponent(value, limit = 3) {
  let current = String(value || "");
  for (let index = 0; index < limit; index += 1) {
    try {
      const next = decodeURIComponent(current);
      if (!next || next === current) break;
      current = next;
    } catch {
      break;
    }
  }
  return current;
}

function appendRepeatedUrlDecodes(values, value, limit = 3) {
  let current = String(value || "");
  const decoded = [];
  for (let index = 0; index < limit; index += 1) {
    try {
      const next = decodeURIComponent(current);
      if (!next || next === current) break;
      decoded.push(next);
      current = next;
    } catch {
      break;
    }
  }
  for (const item of decoded) {
    if (!values.includes(item)) values.unshift(item);
  }
}

function decodeJsStringEscapes(value) {
  return String(value || "")
    .replace(/\\u([0-9a-fA-F]{4})/g, (match, hex) => {
      const char = String.fromCharCode(parseInt(hex, 16));
      return /[\u0000-\u0008\u000e-\u001f]/.test(char) ? match : char;
    })
    .replace(/\\x([0-9a-fA-F]{2})/g, (match, hex) => {
      const char = String.fromCharCode(parseInt(hex, 16));
      return /[\u0000-\u0008\u000e-\u001f]/.test(char) ? match : char;
    })
    .replace(/\\\//g, "/")
    .replace(/\\&/g, "&")
    .replace(/\\\?/g, "?")
    .replace(/\\=/g, "=");
}

function decodedValues(value) {
  const raw = stripUrlTail(value);
  if (!raw) return [];
  const values = [decodeJsStringEscapes(raw).replace(/&amp;/g, "&")];
  appendRepeatedUrlDecodes(values, values[0]);
  const compact = raw.replace(/\s+/g, "");
  if (B64ISH_RE.test(compact)) {
    const padded = compact + "=".repeat((4 - (compact.length % 4)) % 4);
    try {
      const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
      const decoded = decodeURIComponent(escape(binary)).trim().replace(/&amp;/g, "&").replace(/\\\//g, "/");
      if (
        decoded &&
        !values.includes(decoded) &&
        !/[\u0000-\u0008\u000e-\u001f]/.test(decoded) &&
        (MEDIA_RE.test(decoded) || FRAGMENT_RE.test(decoded) || SUBTITLE_RE.test(decoded) || decoded.includes(".m3u8") || decoded.includes(".mpd") || looksLikeMediaValue(decoded, "media"))
      ) {
        values.push(decoded);
      }
    } catch {
      // Ignore non-text or non-base64 values.
    }
  }
  return values.filter((item, index) => item && values.indexOf(item) === index);
}

function mimeFromHint(hint = "") {
  const text = String(hint || "").toLowerCase();
  if (text.includes("m3u8") || text.includes("hls") || text.includes("mpegurl")) return "application/vnd.apple.mpegurl";
  if (text.includes("mpd") || text.includes("dash")) return "application/dash+xml";
  if (text.includes("subtitle") || text.includes("caption") || text.includes("vtt") || text.includes("srt")) return "text/vtt";
  if (text.includes("audio/") || text.includes("m4a") || text.includes("mp3") || text.includes("aac") || text.includes("opus") || text.includes("audio")) return "audio/mp4";
  if (text.includes("video") || text.includes("mp4") || text.includes("media") || text.includes("play") || text.includes("stream")) return "video/mp4";
  return "";
}

function looksLikeMediaValue(value, hint = "") {
  const text = String(value || "").trim();
  if (text.length < 4 || /\s/.test(text)) return false;
  if (MEDIA_RE.test(text) || FRAGMENT_RE.test(text) || SUBTITLE_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return true;
  if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return STATIC_MEDIA_KEY_RE.test(hint) || MEDIA_RE.test(decodeURIComponentSafe(text));
  if (/^(https?:)?\/\//i.test(text) || text.startsWith("/")) return STATIC_MEDIA_KEY_RE.test(hint);
  return text.includes("/") && /[?=&]|api|play|media|video|audio|stream|m3u8|mpd|hls|dash/i.test(text) && STATIC_MEDIA_KEY_RE.test(hint);
}

function looksLikePlaybackEndpointValue(value, hint = "") {
  const text = decodeURIComponentSafe(decodeJsStringEscapes(String(value || ""))).trim();
  if (!text || !STATIC_MEDIA_KEY_RE.test(hint)) return false;
  if (!/^(https?:)?\/\//i.test(text) && !text.startsWith("/") && !text.includes("/")) return false;
  if (MEDIA_RE.test(text) || FRAGMENT_RE.test(text) || SUBTITLE_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return false;
  return /(^|[/?&=._-])(api|ananas|play|player|stream|video|audio|media|vod|hls|dash|manifest|playlist|master|m3u8|mpd|objectid|dtoken)([/?&=._-]|$)/i.test(text);
}

function decodeURIComponentSafe(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function resourceFromHint(value, source, label, hint = "", video = null, isMainVideo = false, playbackMatch = "") {
  for (const candidate of decodedValues(value)) {
    const trimmed = String(candidate || "").trim();
    if (trimmed[0] === "{" || trimmed[0] === "[") continue;
    if (!looksLikeMediaValue(candidate, hint || label)) continue;
    const endpointMime = looksLikePlaybackEndpointValue(candidate, `${hint} ${label}`) ? "video/mp4" : "";
    const item = resource(candidate, source, label, mimeFromHint(`${hint} ${label}`) || endpointMime, video, isMainVideo, playbackMatch);
    if (item && item.kind !== "unknown") return item;
  }
  return null;
}

function resource(url, source, label, mime = "", video = null, isMainVideo = false, playbackMatch = "") {
  const absolute = absoluteUrl(url);
  if (!absolute) return null;
  const effectiveMime = mime || mimeFromPlaybackElementContext(absolute, source, label, video, playbackMatch);
  const kind = classify(absolute, effectiveMime);
  return {
    url: absolute,
    source,
    kind,
    mime: effectiveMime,
    label,
    score: score(absolute, effectiveMime, source),
    is_main_video: isMainVideo,
    playback_match: playbackMatch,
    blob_url: "",
    current_time: video ? Number(video.currentTime || 0) : null,
    duration: video && Number.isFinite(video.duration) ? Number(video.duration || 0) : null,
    width: video ? Number(video.videoWidth || video.clientWidth || 0) : null,
    height: video ? Number(video.videoHeight || video.clientHeight || 0) : null,
    time_stamp: Date.now()
  };
}

function collectEncodedTextResources(text, source, label, seen = new Set()) {
  const resources = [];
  ENCODED_MEDIA_URL_RE.lastIndex = 0;
  for (const match of String(text || "").matchAll(ENCODED_MEDIA_URL_RE)) {
    for (const candidate of decodedValues(match[0] || "")) {
      const item = resource(candidate, source, label, mimeFromHint(candidate));
      if (!item || item.kind === "unknown" || seen.has(item.url)) continue;
      seen.add(item.url);
      item.score = Math.max(item.score || 0, scoreForKind(item.kind));
      resources.push(item);
      break;
    }
    if (resources.length >= 40) break;
  }
  ENCODED_MEDIA_URL_RE.lastIndex = 0;
  return resources;
}

function isJsEscapedMediaFragmentMatch(text, index) {
  if (!Number.isFinite(index) || index <= 0) return false;
  const prefix = String(text || "").slice(Math.max(0, index - 6), index);
  return /\\(?:u[0-9a-fA-F]{0,4}|x[0-9a-fA-F]{0,2})?$/.test(prefix);
}

function collectTextMediaResources(text, source, label, seen = new Set()) {
  const resources = [];
  const body = String(text || "");
  const decodedBody = decodeJsStringEscapes(body);
  for (const searchable of [body, decodedBody].filter((item, index, values) => item && values.indexOf(item) === index)) {
    MEDIA_URL_RE.lastIndex = 0;
    for (const match of searchable.matchAll(MEDIA_URL_RE)) {
      if (isJsEscapedMediaFragmentMatch(searchable, match.index ?? -1)) continue;
      for (const candidate of decodedValues(match[0] || "")) {
        const item = resource(candidate, source, label, mimeFromHint(candidate));
        if (!item || item.kind === "unknown" || seen.has(item.url)) continue;
        seen.add(item.url);
        item.score = Math.max(item.score || 0, scoreForKind(item.kind));
        resources.push(item);
        break;
      }
      if (resources.length >= 40) break;
    }
    if (resources.length >= 40) break;
  }
  MEDIA_URL_RE.lastIndex = 0;
  return resources;
}

function nestedMediaTextCandidates(value) {
  const candidates = [];
  for (const candidate of decodedValues(value)) {
    const text = String(candidate || "").trim();
    if (!text || text.length > 300000) continue;
    if (
      text[0] === "{" ||
      text[0] === "[" ||
      (STATIC_MEDIA_KEY_RE.test(text) && (MEDIA_RE.test(text) || FRAGMENT_RE.test(text) || SUBTITLE_RE.test(text) || ENCODED_MEDIA_URL_RE.test(text) || MEDIA_URL_RE.test(text)))
    ) {
      candidates.push(text);
    }
    ENCODED_MEDIA_URL_RE.lastIndex = 0;
    MEDIA_URL_RE.lastIndex = 0;
  }
  return candidates;
}

function collectNestedFieldResources(value, source, label, seen = new Set(), limit = 40) {
  const resources = [];
  for (const text of nestedMediaTextCandidates(value)) {
    for (const item of collectHtmlTextResources(text, source, `${label} nested`, seen, Math.max(0, limit - resources.length), 1)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
  }
  return resources;
}

function collectKeyedContainerResources(text, source, label, seen = new Set(), limit = 40) {
  const resources = [];
  const body = String(text || "");
  STATIC_CONTAINER_FIELD_RE.lastIndex = 0;
  for (const match of body.matchAll(STATIC_CONTAINER_FIELD_RE)) {
    const key = String(match[1] || "").replace(/^["']|["']$/g, "");
    if (!STATIC_MEDIA_KEY_RE.test(key)) continue;
    const chunk = body.slice(match.index || 0, Math.min(body.length, (match.index || 0) + 2400));
    STATIC_QUOTED_VALUE_RE.lastIndex = 0;
    for (const valueMatch of chunk.matchAll(STATIC_QUOTED_VALUE_RE)) {
      const item = resourceFromHint(valueMatch[1], source, `${label} ${key} container`, key);
      if (item && !seen.has(item.url)) {
        seen.add(item.url);
        item.score = Math.max(item.score || 0, scoreForKind(item.kind, { manifest: 96, video: 84, audio: 38, other: 62 }));
        resources.push(item);
        if (resources.length >= limit) return resources;
      }
      for (const nestedItem of collectNestedFieldResources(valueMatch[1], source, `${label} ${key} container`, seen, limit - resources.length)) {
        resources.push(nestedItem);
        if (resources.length >= limit) return resources;
      }
    }
  }
  STATIC_CONTAINER_FIELD_RE.lastIndex = 0;
  STATIC_QUOTED_VALUE_RE.lastIndex = 0;
  return resources;
}

function mimeFromPlaybackElementContext(url, source, label, video = null, playbackMatch = "") {
  if (!video || !/^https?:\/\//i.test(url) || classify(url, "") !== "unknown") return "";
  if (source === "activeVideo") return "video/mp4";
  if (source === "dom" && /video source/i.test(label)) return "video/mp4";
  if (playbackMatch === "source-element") return "video/mp4";
  return "";
}

function performanceKind(entry = {}) {
  const name = entry.name || "";
  const kind = classify(name, "");
  if (kind !== "unknown") return kind;
  const initiator = String(entry.initiatorType || "").toLowerCase();
  if (initiator === "video" || initiator === "audio") return "video";
  if (initiator === "track") return "subtitle";
  if ((initiator === "fetch" || initiator === "xmlhttprequest") && performanceLooksLikeMediaEndpoint(name)) return "video";
  return "unknown";
}

function performanceLooksLikeMediaEndpoint(url = "") {
  const raw = String(url || "");
  const endpointRe = /(^|[/?&=._-])(api|ananas|play|player|stream|video|audio|media|vod|hls|dash|manifest|playlist|master|m3u8|mpd|objectid|dtoken|fileid|httpmd|subtitle|caption)([/?&=._-]|$)/i;
  try {
    const parsed = new URL(raw, location.href);
    const queryKeys = [...parsed.searchParams.keys()].join("&");
    return endpointRe.test(`${parsed.pathname} ${queryKeys}`) || /\.(m3u8|mpd|mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|vtt|srt|ass|ssa)([?#]|$)/i.test(raw);
  } catch {
    return endpointRe.test(raw);
  }
}

function performanceScore(kind, url) {
  let value = 0;
  if (kind === "hls" || kind === "dash") value = 95;
  else if (kind === "video") value = 88;
  else if (kind === "audio") value = 35;
  else if (kind === "subtitle") value = 65;
  else if (kind === "fragment") value = 20;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
}

function pageResourceKindRank(kind = "") {
  return ({ hls: 6, dash: 6, video: 5, audio: 3, subtitle: 2, fragment: 1, blob: 0 })[kind] ?? 0;
}

function pageResourcePlaybackRank(match = "") {
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

function comparePageResources(a = {}, b = {}) {
  const left = [
    a.is_main_video ? 1 : 0,
    pageResourcePlaybackRank(a.playback_match),
    pageResourceKindRank(a.kind),
    Number(a.score || 0),
    Number(a.time_stamp || 0),
    Number(a.content_length || 0)
  ];
  const right = [
    b.is_main_video ? 1 : 0,
    pageResourcePlaybackRank(b.playback_match),
    pageResourceKindRank(b.kind),
    Number(b.score || 0),
    Number(b.time_stamp || 0),
    Number(b.content_length || 0)
  ];
  for (let index = 0; index < left.length; index += 1) {
    if (right[index] !== left[index]) return right[index] - left[index];
  }
  return String(a.url || "").localeCompare(String(b.url || ""));
}

function rememberHookResource(item) {
  const normalized = resource(item.url, item.source || "pageHook", item.label || "page hook", item.mime || "");
  if (!normalized) return;
  normalized.kind = item.kind || normalized.kind;
  normalized.score = Math.max(normalized.score, Number(item.score || 0));
  normalized.is_main_video = Boolean(item.is_main_video || normalized.is_main_video);
  normalized.playback_match = item.playback_match || normalized.playback_match || "";
  normalized.blob_url = absoluteUrl(item.blob_url || "") || "";
  normalized.request_type = item.request_type || "";
  normalized.method = item.method || "";
  normalized.status_code = item.status_code ?? null;
  normalized.content_length = item.content_length ?? null;
  normalized.initiator = item.initiator || "";
  normalized.time_stamp = item.time_stamp ?? normalized.time_stamp ?? Date.now();
  normalized.headers = item.headers || {};
  normalized.request_headers = item.request_headers || {};
  normalized.request_body = item.request_body || {};
  normalized.audio_url = absoluteUrl(item.audio_url || "") || "";
  normalized.audio_mime = item.audio_mime || "";
  const existing = hookResources.find(entry => entry.url === normalized.url);
  if (existing) {
    Object.assign(existing, normalized, {
      score: Math.max(existing.score || 0, normalized.score || 0),
      is_main_video: Boolean(existing.is_main_video || normalized.is_main_video),
      playback_match: existing.playback_match || normalized.playback_match || "",
      blob_url: normalized.blob_url || existing.blob_url || "",
      request_type: normalized.request_type || existing.request_type || "",
      method: normalized.method || existing.method || "",
      status_code: normalized.status_code ?? existing.status_code ?? null,
      content_length: normalized.content_length ?? existing.content_length ?? null,
      initiator: normalized.initiator || existing.initiator || "",
      time_stamp: Math.max(existing.time_stamp || 0, normalized.time_stamp || 0) || null,
      headers: { ...(existing.headers || {}), ...(normalized.headers || {}) },
      request_headers: { ...(existing.request_headers || {}), ...(normalized.request_headers || {}) },
      request_body: { ...(existing.request_body || {}), ...(normalized.request_body || {}) },
      audio_url: normalized.audio_url || existing.audio_url || "",
      audio_mime: normalized.audio_mime || existing.audio_mime || ""
    });
  } else {
    hookResources.unshift(normalized);
  }
  hookResources.splice(40);
}

function collectHookResources() {
  return hookResources.slice(0, 40);
}

function rememberDrmSignal(signal = {}, video = null) {
  const normalized = {
    source: signal.source || "contentEncrypted",
    key_system: String(signal.key_system || ""),
    init_data_type: String(signal.init_data_type || ""),
    label: signal.label || "encrypted media",
    page_url: location.href,
    time_stamp: signal.time_stamp ?? Date.now()
  };
  if (video) {
    const previous = drmByVideo.get(video) || {};
    drmByVideo.set(video, {
      ...previous,
      ...normalized,
      encrypted_events: Number(previous.encrypted_events || 0) + 1
    });
  }
  const signature = [normalized.source, normalized.key_system, normalized.init_data_type, normalized.label].join("|");
  const existing = drmSignals.find(item => [item.source, item.key_system, item.init_data_type, item.label].join("|") === signature);
  if (existing) {
    existing.time_stamp = normalized.time_stamp;
  } else {
    drmSignals.unshift(normalized);
  }
  drmSignals.splice(20);
}

function collectDrmSignals() {
  return drmSignals.slice(0, 20);
}

function installPageHookBridge() {
  window.addEventListener("message", event => {
    if (event.source !== window || event.data?.source !== "learnnote-page-hook") return;
    for (const item of event.data.resources || []) rememberHookResource(item);
    for (const item of event.data.drm || []) rememberDrmSignal(item);
    if ((event.data.resources || []).length || (event.data.drm || []).length) schedulePush(120, true);
  });
  window.postMessage({ source: "learnnote-content-ready" }, "*");
  setTimeout(() => window.postMessage({ source: "learnnote-content-ready" }, "*"), 250);
  setTimeout(() => window.postMessage({ source: "learnnote-content-ready" }, "*"), 1000);
}

function safeQueryAll(root, selector) {
  try {
    return [...root.querySelectorAll(selector)];
  } catch {
    return [];
  }
}

function deepQuerySelectorAll(selector, root = document, limit = DEEP_QUERY_LIMIT) {
  const results = [];
  const seenRoots = new Set();
  const seenElements = new WeakSet();

  function add(elements) {
    for (const element of elements) {
      if (!element || seenElements.has(element)) continue;
      seenElements.add(element);
      results.push(element);
      if (results.length >= limit) return false;
    }
    return true;
  }

  function visit(searchRoot) {
    if (!searchRoot || seenRoots.has(searchRoot) || results.length >= limit) return;
    seenRoots.add(searchRoot);
    if (!add(safeQueryAll(searchRoot, selector))) return;
    for (const host of safeQueryAll(searchRoot, "*")) {
      if (host?.shadowRoot) visit(host.shadowRoot);
      if (results.length >= limit) return;
    }
  }

  visit(root);
  return results;
}

function readAttribute(element, name) {
  try {
    if (typeof element.getAttribute === "function") return element.getAttribute(name) || "";
  } catch {
    return "";
  }
  return element[name] || "";
}

function elementAttributeEntries(element) {
  const attrs = element?.attributes || [];
  if (typeof attrs[Symbol.iterator] === "function") {
    return [...attrs]
      .map(attr => [String(attr.name || ""), String(attr.value || "")])
      .filter(([name, value]) => name && value);
  }
  if (attrs instanceof Map) {
    return [...attrs.entries()].map(([name, value]) => [String(name || ""), String(value || "")]).filter(([name, value]) => name && value);
  }
  return Object.entries(attrs)
    .map(([name, value]) => [String(name || ""), String(value || "")])
    .filter(([name, value]) => name && value && name !== "textContent");
}

function attributeMayContainMedia(name, value) {
  const hint = `${name} ${String(value || "").slice(0, 160)}`;
  if (STATIC_ATTRIBUTE_KEY_RE.test(hint)) return true;
  if (MEDIA_RE.test(value) || FRAGMENT_RE.test(value) || SUBTITLE_RE.test(value)) return true;
  if (String(value || "").includes(".m3u8") || String(value || "").includes(".mpd")) return true;
  if (ENCODED_MEDIA_URL_RE.test(value) || MEDIA_URL_RE.test(value)) {
    ENCODED_MEDIA_URL_RE.lastIndex = 0;
    MEDIA_URL_RE.lastIndex = 0;
    return true;
  }
  ENCODED_MEDIA_URL_RE.lastIndex = 0;
  MEDIA_URL_RE.lastIndex = 0;
  return false;
}

function collectStaticAttributeResources() {
  const resources = [];
  const seen = new Set();
  for (const element of deepQuerySelectorAll(STATIC_MEDIA_SELECTOR, document, 1200)) {
    const tag = String(element.tagName || "element").toLowerCase();
    for (const attr of STATIC_MEDIA_ATTRS) {
      const value = readAttribute(element, attr);
      if (!value) continue;
      const item = resourceFromHint(value, "domHint", `${tag} ${attr}`, attr);
      if (item && !seen.has(item.url)) {
        seen.add(item.url);
        resources.push(item);
      }
      for (const textItem of collectTextMediaResources(value, "domHint", `${tag} ${attr} media url`, seen)) {
        resources.push(textItem);
      }
      for (const encodedItem of collectEncodedTextResources(value, "domHint", `${tag} ${attr} encoded url`, seen)) {
        resources.push(encodedItem);
      }
    }
  }
  for (const element of deepQuerySelectorAll("*", document, 1200)) {
    const tag = String(element.tagName || "element").toLowerCase();
    for (const [attr, value] of elementAttributeEntries(element)) {
      const attrName = attr.toLowerCase();
      if (STATIC_MEDIA_ATTRS.includes(attrName) || !attributeMayContainMedia(attrName, value)) continue;
      const item = resourceFromHint(value, "domHint", `${tag} ${attr}`, attr);
      if (item && !seen.has(item.url)) {
        seen.add(item.url);
        resources.push(item);
      }
      for (const textItem of collectTextMediaResources(value, "domHint", `${tag} ${attr} media url`, seen)) {
        resources.push(textItem);
      }
      for (const encodedItem of collectEncodedTextResources(value, "domHint", `${tag} ${attr} encoded url`, seen)) {
        resources.push(encodedItem);
      }
    }
  }
  return resources;
}

function declaredMediaHint(element) {
  const tag = String(element?.tagName || "").toLowerCase();
  if (tag === "link") {
    const rel = readAttribute(element, "rel").toLowerCase();
    const as = readAttribute(element, "as").toLowerCase();
    const type = readAttribute(element, "type");
    const href = readAttribute(element, "href");
    if (!href || !/(^|\s)(preload|prefetch|modulepreload|prerender)(\s|$)/i.test(rel)) return null;
    if (/^(video|audio)$/i.test(as)) {
      return { value: href, hint: `${rel} ${as} ${type} media`, label: `link ${rel} as=${as}` };
    }
    if (/mpegurl|dash\+xml|video\/|audio\//i.test(type)) {
      return { value: href, hint: `${rel} ${type}`, label: `link ${rel} ${type}` };
    }
    if (as === "fetch" && /api|play|player|stream|video|audio|media|hls|dash|manifest|playlist|master|m3u8|mpd/i.test(href)) {
      return { value: href, hint: `${rel} fetch play media`, label: `link ${rel} as=fetch` };
    }
  }
  if (tag === "meta") {
    const key = [
      readAttribute(element, "property"),
      readAttribute(element, "name"),
      readAttribute(element, "itemprop")
    ].join(" ");
    const content = readAttribute(element, "content");
    if (!content || !/(og:video|og:audio|twitter:player:stream|twitter:player|video|media|stream|hls|dash|m3u8|mpd)/i.test(key)) return null;
    return { value: content, hint: `${key} media`, label: `meta ${key}` };
  }
  if (tag === "object") {
    const value = readAttribute(element, "data");
    const type = readAttribute(element, "type");
    if (!value || !/video\/|audio\/|mpegurl|dash\+xml|media|player|stream/i.test(`${type} ${value}`)) return null;
    return { value, hint: `${type} object media`, label: "object data" };
  }
  if (tag === "embed") {
    const value = readAttribute(element, "src");
    const type = readAttribute(element, "type");
    if (!value || !/video\/|audio\/|mpegurl|dash\+xml|media|player|stream/i.test(`${type} ${value}`)) return null;
    return { value, hint: `${type} embed media`, label: "embed src" };
  }
  if (["video", "audio", "source", "track"].includes(tag)) {
    const value = mediaElementUrl(element);
    const type = readAttribute(element, "type") || element?.type || "";
    const kind = readAttribute(element, "kind") || element?.kind || "";
    if (!value) return null;
    if (tag === "track") {
      const labelHint = kind || type || "src";
      return { value, hint: `${tag} ${kind} ${type} subtitle caption`, label: `${tag} ${labelHint}` };
    }
    const labelHint = type || "src";
    return { value, hint: `${tag} ${type} media video audio`, label: `${tag} ${labelHint}` };
  }
  return null;
}

function collectDeclaredMediaResources() {
  const resources = [];
  const seen = new Set();
  for (const element of deepQuerySelectorAll("link[href],meta[content],object[data],embed[src],video, audio, source, track", document, 500)) {
    const hint = declaredMediaHint(element);
    if (!hint) continue;
    const item = resourceFromHint(hint.value, "domHint", hint.label, hint.hint);
    if (item && !seen.has(item.url)) {
      seen.add(item.url);
      item.score = Math.max(item.score || 0, scoreForKind(item.kind, { manifest: 96, video: 88, audio: 38, other: 62 }));
      resources.push(item);
    }
    for (const textItem of collectTextMediaResources(hint.value, "domHint", `${hint.label} media url`, seen)) {
      resources.push(textItem);
    }
    for (const encodedItem of collectEncodedTextResources(hint.value, "domHint", `${hint.label} encoded url`, seen)) {
      resources.push(encodedItem);
    }
  }
  return resources;
}

function collectInlineScriptResources() {
  const resources = [];
  const seen = new Set();
  for (const script of deepQuerySelectorAll("script", document, 400)) {
    const text = String(script.textContent || "").slice(0, 200000);
    ENCODED_MEDIA_URL_RE.lastIndex = 0;
    MEDIA_URL_RE.lastIndex = 0;
    if (!text || (!STATIC_MEDIA_KEY_RE.test(text) && !ENCODED_MEDIA_URL_RE.test(text) && !MEDIA_URL_RE.test(text))) continue;
    ENCODED_MEDIA_URL_RE.lastIndex = 0;
    MEDIA_URL_RE.lastIndex = 0;
    STATIC_FIELD_RE.lastIndex = 0;
    for (const match of text.matchAll(STATIC_FIELD_RE)) {
      const key = String(match[1] || "").replace(/^["']|["']$/g, "");
      if (!STATIC_MEDIA_KEY_RE.test(key)) continue;
      const item = resourceFromHint(match[2], "scriptHint", `script ${key}`, key);
      if (item && !seen.has(item.url)) {
        seen.add(item.url);
        item.score = Math.max(item.score || 0, scoreForKind(item.kind));
        resources.push(item);
        if (resources.length >= 40) return resources;
      }
      for (const nestedItem of collectNestedFieldResources(match[2], "scriptHint", `script ${key}`, seen, 40 - resources.length)) {
        resources.push(nestedItem);
        if (resources.length >= 40) return resources;
      }
    }
    for (const item of collectKeyedContainerResources(text, "scriptHint", "script", seen, 40 - resources.length)) {
      resources.push(item);
      if (resources.length >= 40) return resources;
    }
    for (const item of collectTextMediaResources(text, "scriptHint", "script media url", seen)) {
      resources.push(item);
      if (resources.length >= 40) return resources;
    }
    for (const item of collectEncodedTextResources(text, "scriptHint", "script encoded url", seen)) {
      resources.push(item);
      if (resources.length >= 40) return resources;
    }
  }
  return resources;
}

function collectHtmlTextResources(text, source, label, seen = new Set(), limit = 40, depth = 0) {
  const resources = [];
  const body = String(text || "").slice(0, 300000);
  ENCODED_MEDIA_URL_RE.lastIndex = 0;
  MEDIA_URL_RE.lastIndex = 0;
  if (!body || (!STATIC_MEDIA_KEY_RE.test(body) && !ENCODED_MEDIA_URL_RE.test(body) && !MEDIA_URL_RE.test(body))) return resources;
  ENCODED_MEDIA_URL_RE.lastIndex = 0;
  MEDIA_URL_RE.lastIndex = 0;
  STATIC_FIELD_RE.lastIndex = 0;
  for (const match of body.matchAll(STATIC_FIELD_RE)) {
    const key = String(match[1] || "").replace(/^["']|["']$/g, "");
    if (!STATIC_MEDIA_KEY_RE.test(key)) continue;
    const item = resourceFromHint(match[2], source, `${label} ${key}`, key);
    if (item && !seen.has(item.url)) {
      seen.add(item.url);
      item.score = Math.max(item.score || 0, scoreForKind(item.kind));
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
    if (depth < 1) {
      for (const nestedItem of collectNestedFieldResources(match[2], source, `${label} ${key}`, seen, limit - resources.length)) {
        resources.push(nestedItem);
        if (resources.length >= limit) return resources;
      }
    }
  }
  for (const item of collectKeyedContainerResources(body, source, label, seen, limit - resources.length)) {
    resources.push(item);
    if (resources.length >= limit) return resources;
  }
  for (const item of collectTextMediaResources(body, source, `${label} media url`, seen)) {
    resources.push(item);
    if (resources.length >= limit) return resources;
  }
  for (const item of collectEncodedTextResources(body, source, `${label} encoded url`, seen)) {
    resources.push(item);
    if (resources.length >= limit) return resources;
  }
  return resources;
}

function iframeDocumentText(iframe) {
  try {
    const doc = iframe?.contentDocument || iframe?.contentWindow?.document || null;
    if (!doc) return "";
    return [
      doc.documentElement?.outerHTML,
      doc.body?.innerText,
      doc.body?.textContent
    ].filter(Boolean).join("\n").slice(0, 300000);
  } catch {
    return "";
  }
}

function collectIframeEmbeddedResources() {
  const resources = [];
  const seen = new Set();
  for (const iframe of deepQuerySelectorAll("iframe", document, 160)) {
    const label = readAttribute(iframe, "title") || readAttribute(iframe, "name") || "iframe";
    const srcdoc = readAttribute(iframe, "srcdoc");
    for (const item of collectHtmlTextResources(srcdoc, "iframeHint", `${label} srcdoc`, seen, 24)) {
      resources.push(item);
    }
    for (const item of collectHtmlTextResources(iframeDocumentText(iframe), "iframeHint", `${label} document`, seen, 24)) {
      resources.push(item);
    }
    if (resources.length >= 40) break;
  }
  return resources;
}

function collectUrlEmbeddedResources(url, source = "domHint", label = "page url") {
  if (!url) return [];
  const seen = new Set();
  return [
    ...collectTextMediaResources(url, source, `${label} media url`, seen),
    ...collectEncodedTextResources(url, source, `${label} encoded url`, seen)
  ];
}

function collectShadowTexts(limit = 20000) {
  const texts = [];
  const seenRoots = new Set();

  function visit(root, includeText = false) {
    if (!root || seenRoots.has(root)) return;
    seenRoots.add(root);
    if (includeText) {
      const text = String(root.innerText || root.textContent || "").trim();
      if (text) texts.push(text);
    }
    for (const host of safeQueryAll(root, "*")) {
      if (host?.shadowRoot) visit(host.shadowRoot, true);
      if (texts.join("\n").length >= limit) return;
    }
  }

  visit(document);
  return texts.join("\n").slice(0, limit);
}

function collectVideos() {
  return deepQuerySelectorAll("video").map((video, index) => ({ video, index }));
}

function mediaElementUrl(element) {
  return element?.currentSrc ||
    element?.src ||
    readAttribute(element, "currentSrc") ||
    readAttribute(element, "src") ||
    readAttribute(element, "data-src") ||
    readAttribute(element, "data-url") ||
    "";
}

function videoSrcObjectInfo(video) {
  let srcObject = null;
  try {
    srcObject = video?.srcObject || null;
  } catch {
    srcObject = null;
  }
  if (!srcObject) {
    return {
      src_object: false,
      src_object_type: "",
      src_object_track_count: 0,
      src_object_video_tracks: 0,
      src_object_audio_tracks: 0
    };
  }
  let tracks = [];
  try {
    tracks = typeof srcObject.getTracks === "function" ? Array.from(srcObject.getTracks() || []) : [];
  } catch {
    tracks = [];
  }
  return {
    src_object: true,
    src_object_type: srcObject.constructor?.name || "MediaStream",
    src_object_track_count: tracks.length,
    src_object_video_tracks: tracks.filter(track => track?.kind === "video").length,
    src_object_audio_tracks: tracks.filter(track => track?.kind === "audio").length
  };
}

function hasVideoSourceSignal(video) {
  return Boolean(video.currentSrc || video.src || video.querySelector("source[src]") || videoSrcObjectInfo(video).src_object);
}

function pickMainVideo(videos = collectVideos()) {
  const playing = videos.find(({ video }) => !video.paused && !video.ended && video.readyState >= 2);
  if (playing) return playing;
  return videos
    .filter(({ video }) => hasVideoSourceSignal(video))
    .sort((a, b) => {
      const areaA = Number(a.video.videoWidth || a.video.clientWidth || 0) * Number(a.video.videoHeight || a.video.clientHeight || 0);
      const areaB = Number(b.video.videoWidth || b.video.clientWidth || 0) * Number(b.video.videoHeight || b.video.clientHeight || 0);
      return areaB - areaA;
    })[0] || null;
}

function activeVideoInfo() {
  const videos = collectVideos();
  const withSource = pickMainVideo(videos);
  if (!withSource) return null;
  const { video, index } = withSource;
  const drm = drmByVideo.get(video) || {};
  const srcObject = videoSrcObjectInfo(video);
  return {
    src: absoluteUrl(video.currentSrc || video.src),
    ...srcObject,
    current_time: Number(video.currentTime || 0),
    duration: Number.isFinite(video.duration) ? Number(video.duration || 0) : 0,
    paused: Boolean(video.paused),
    width: Number(video.videoWidth || video.clientWidth || 0),
    height: Number(video.videoHeight || video.clientHeight || 0),
    frame_id: 0,
    label: `video#${index + 1}`,
    drm_detected: Boolean(drm.encrypted_events || drmSignals.length || video.mediaKeys),
    drm_key_system: drm.key_system || "",
    encrypted_events: Number(drm.encrypted_events || 0),
    time_stamp: Date.now()
  };
}

function cuesToArray(cues) {
  const items = [];
  if (!cues) return items;
  try {
    for (let index = 0; index < cues.length; index += 1) {
      const cue = cues[index];
      if (cue) items.push(cue);
    }
  } catch {
    return [];
  }
  return items;
}

function ensureReadableTextTrack(track) {
  try {
    if (track?.mode === "disabled") track.mode = "hidden";
  } catch {
    // Some browser/player wrappers expose read-only track modes.
  }
}

function collectVideoSubtitleCues(video, limit = 1000) {
  const subtitles = [];
  if (limit <= 0) return subtitles;
  const seen = new Set();
  const tracks = [];
  try {
    for (let index = 0; index < (video.textTracks?.length || 0); index += 1) {
      const track = video.textTracks[index];
      if (track) tracks.push(track);
    }
  } catch {
    return subtitles;
  }

  for (const track of tracks) {
    ensureReadableTextTrack(track);
    const cueSources = [];
    try {
      if (track.cues) cueSources.push(track.cues);
    } catch {
      // Cross-origin or unloaded tracks may deny cue access.
    }
    try {
      if (track.activeCues) cueSources.push(track.activeCues);
    } catch {
      // Active cue access can fail independently of the full cue list.
    }

    for (const cueSource of cueSources) {
      for (const cue of cuesToArray(cueSource)) {
        const text = String(cue.text || "").replace(/\s+/g, " ").trim();
        if (!text) continue;
        const start = Number(cue.startTime ?? cue.start ?? 0);
        const end = Number(cue.endTime ?? cue.end ?? start);
        if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
        const key = `${Math.round(start * 1000)}|${Math.round(end * 1000)}|${text}`;
        if (seen.has(key)) continue;
        seen.add(key);
        subtitles.push({
          start: Math.max(0, start),
          end: Math.max(start, end),
          text
        });
        if (subtitles.length >= limit) return subtitles;
      }
    }
  }
  return subtitles;
}

function elementText(element) {
  return String(element?.innerText || element?.textContent || "").replace(/\s+/g, " ").trim();
}

function elementHintText(element) {
  const values = [
    element?.className,
    element?.id,
    readAttribute(element, "class"),
    readAttribute(element, "id"),
    readAttribute(element, "role"),
    readAttribute(element, "aria-live"),
    readAttribute(element, "aria-label"),
    readAttribute(element, "title")
  ];
  return values.filter(Boolean).join(" ");
}

function looksLikeVisibleSubtitleElement(element) {
  const tag = String(element?.tagName || "").toLowerCase();
  if (!element || ["script", "style", "video", "audio", "source", "track", "iframe"].includes(tag)) return false;
  const text = elementText(element);
  if (text.length < 2 || text.length > 260) return false;
  const hint = elementHintText(element);
  if (VISIBLE_SUBTITLE_HINT_RE.test(hint)) return true;
  const role = readAttribute(element, "role");
  const ariaLive = readAttribute(element, "aria-live");
  return VISIBLE_SUBTITLE_ROLE_RE.test(role) || Boolean(ariaLive && ariaLive !== "off");
}

function rememberVisibleSubtitleCues(cues) {
  for (const cue of cues || []) {
    const text = String(cue?.text || "").replace(/\s+/g, " ").trim();
    const start = Number(cue?.start ?? 0);
    const end = Number(cue?.end ?? start);
    if (!text || !Number.isFinite(start) || !Number.isFinite(end)) continue;
    const nearby = visibleSubtitleHistory.find(item =>
      item.text === text && (
        Math.abs(item.start - start) <= 2 ||
        Math.abs(item.end - start) <= 8 ||
        Math.abs(item.end - end) <= 2
      )
    );
    if (nearby) {
      nearby.start = Math.min(nearby.start, Math.max(0, start));
      nearby.end = Math.max(nearby.end, Math.max(start, end));
    } else {
      visibleSubtitleHistory.push({
        start: Math.max(0, start),
        end: Math.max(start, end),
        text
      });
    }
  }
  visibleSubtitleHistory.sort((a, b) => a.start - b.start || a.end - b.end || a.text.localeCompare(b.text));
  if (visibleSubtitleHistory.length > MAX_VISIBLE_SUBTITLE_HISTORY) {
    visibleSubtitleHistory.splice(0, visibleSubtitleHistory.length - MAX_VISIBLE_SUBTITLE_HISTORY);
  }
}

function collectVisibleSubtitleCues(limit = 200) {
  if (limit <= 0) return [];
  const active = activeVideoInfo();
  const base = Number(active?.current_time || 0);
  const start = Math.max(0, base - 1.5);
  const end = Math.max(start + 0.5, base + 4.5);
  const cues = [];
  const seen = new Set();
  for (const element of deepQuerySelectorAll("*", document, 1600)) {
    if (!looksLikeVisibleSubtitleElement(element)) continue;
    const text = elementText(element);
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cues.push({ start, end, text });
    if (cues.length >= limit) break;
  }
  rememberVisibleSubtitleCues(cues);
  return visibleSubtitleHistory.slice(-limit);
}

function isVisibleSubtitleNode(node) {
  if (!node) return false;
  if (node.nodeType === 3) return looksLikeVisibleSubtitleElement(node.parentElement || node.parentNode);
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  if (looksLikeVisibleSubtitleElement(node)) return true;
  try {
    return deepQuerySelectorAll("*", node, 40).some(looksLikeVisibleSubtitleElement);
  } catch {
    return false;
  }
}

function collectBrowserSubtitles(limit = 1200) {
  if (limit <= 0) return [];
  const videos = collectVideos();
  const main = pickMainVideo(videos);
  const ordered = main ? [main, ...videos.filter(item => item.video !== main.video)] : videos;
  const all = [];
  const seen = new Set();
  for (const { video } of ordered) {
    for (const cue of collectVideoSubtitleCues(video, limit - all.length)) {
      const key = `${Math.round(cue.start * 1000)}|${Math.round(cue.end * 1000)}|${cue.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      all.push(cue);
      if (all.length >= limit) return all.sort((a, b) => a.start - b.start || a.end - b.end);
    }
  }
  for (const cue of collectVisibleSubtitleCues(limit - all.length)) {
    const key = `${Math.round(cue.start * 1000)}|${Math.round(cue.end * 1000)}|${cue.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    all.push(cue);
    if (all.length >= limit) break;
  }
  return all.sort((a, b) => a.start - b.start || a.end - b.end);
}

function bindTextTrack(track) {
  if (!track || boundTextTracks.has(track)) return;
  boundTextTracks.add(track);
  ensureReadableTextTrack(track);
  try {
    track.addEventListener?.("cuechange", () => schedulePush(120, true));
  } catch {
    // Some player-provided TextTrack objects are not EventTargets.
  }
}

function bindTextTrackList(trackList) {
  if (!trackList || boundTextTrackLists.has(trackList)) return;
  boundTextTrackLists.add(trackList);
  try {
    trackList.addEventListener?.("addtrack", event => {
      bindTextTrack(event?.track);
      schedulePush(180, true);
    });
    trackList.addEventListener?.("removetrack", () => schedulePush(180, true));
    trackList.addEventListener?.("change", () => schedulePush(180, true));
  } catch {
    // Older Chromium wrappers may expose TextTrackList without listener methods.
  }
}

function bindVideoTextTracks(video) {
  let tracks = null;
  try {
    tracks = video?.textTracks || null;
  } catch {
    return;
  }
  bindTextTrackList(tracks);
  try {
    for (let index = 0; index < (tracks?.length || 0); index += 1) {
      bindTextTrack(tracks[index]);
    }
  } catch {
    // Track enumeration can fail for detached or cross-realm media elements.
  }
}

function collectDomResources() {
  const resources = [
    ...collectUrlEmbeddedResources(location.href, "locationHint", "current page URL"),
    ...collectIframeEmbeddedResources(),
    ...collectStaticAttributeResources(),
    ...collectDeclaredMediaResources(),
    ...collectInlineScriptResources()
  ];
  const videos = collectVideos();
  const main = pickMainVideo(videos);
  for (const { video, index } of videos) {
    const isMain = main?.video === video;
    resources.push(resource(mediaElementUrl(video), "activeVideo", `当前视频 #${index + 1}`, video.type || "", video, isMain, isMain ? "exact-src" : ""));
    for (const source of video.querySelectorAll("source")) {
      resources.push(resource(mediaElementUrl(source), "dom", `video source #${index + 1}`, source.type || "", video, isMain, isMain ? "source-element" : ""));
    }
    for (const track of video.querySelectorAll("track")) {
      const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
      resources.push(resource(mediaElementUrl(track), "subtitleTrack", label || `subtitle #${index + 1}`, "text/vtt", video, isMain));
    }
  }
  for (const source of deepQuerySelectorAll("source")) {
    resources.push(resource(mediaElementUrl(source), "dom", "source", source.type || ""));
  }
  for (const track of deepQuerySelectorAll("track")) {
    const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
    resources.push(resource(mediaElementUrl(track), "subtitleTrack", label || "subtitle", "text/vtt"));
  }
  for (const iframe of deepQuerySelectorAll("iframe[src]")) {
    resources.push(...collectUrlEmbeddedResources(iframe.src, "domHint", "iframe URL"));
    if (/chaoxing|xuexitong|video|player|course|m3u8|mpd/i.test(iframe.src)) {
      resources.push(resource(iframe.src, "dom", "iframe"));
    }
  }
  return resources.filter(Boolean);
}

function collectPerformanceResources() {
  const resources = [];
  for (const entry of performance.getEntriesByType("resource")) {
    const name = entry.name || "";
    const kind = performanceKind(entry);
    if (kind !== "unknown" || performanceLooksLikeMediaEndpoint(name)) {
      const item = resource(name, "performance", "performance");
      if (!item) continue;
      item.kind = kind !== "unknown" ? kind : item.kind;
      item.request_type = entry.initiatorType || "";
      item.content_length = Number(entry.encodedBodySize || entry.transferSize || 0) || null;
      item.score = Math.max(item.score || 0, performanceScore(item.kind, item.url));
      resources.push(item);
    }
  }
  return resources.filter(Boolean);
}

function collectCourseText() {
  const candidates = [
    ...deepQuerySelectorAll("h1,h2,h3,.course-title,.chapter-title,.ans-job-icon,.title,.name")
  ];
  const headings = candidates.map(el => el.textContent?.trim()).filter(Boolean).slice(0, 40).join("\n");
  const body = document.body?.innerText || "";
  const shadowText = collectShadowTexts();
  return [headings, body, shadowText].filter(Boolean).join("\n\n").slice(0, 60000);
}

function mergePageResource(previous, incoming) {
  if (!previous) return incoming;
  const primary = Number(incoming.score || 0) > Number(previous.score || 0) ? incoming : previous;
  const secondary = primary === incoming ? previous : incoming;
  return {
    ...secondary,
    ...primary,
    score: Math.max(Number(previous.score || 0), Number(incoming.score || 0)),
    is_main_video: Boolean(previous.is_main_video || incoming.is_main_video),
    playback_match: primary.playback_match || secondary.playback_match || "",
    blob_url: primary.blob_url || secondary.blob_url || "",
    request_type: primary.request_type || secondary.request_type || "",
    method: primary.method || secondary.method || "",
    status_code: primary.status_code ?? secondary.status_code ?? null,
    content_length: primary.content_length ?? secondary.content_length ?? null,
    resolved_url: primary.resolved_url || secondary.resolved_url || "",
    initiator: primary.initiator || secondary.initiator || "",
    current_time: primary.current_time ?? secondary.current_time ?? null,
    duration: primary.duration ?? secondary.duration ?? null,
    width: primary.width ?? secondary.width ?? null,
    height: primary.height ?? secondary.height ?? null,
    time_stamp: Math.max(previous.time_stamp || 0, incoming.time_stamp || 0) || null,
    headers: { ...(secondary.headers || {}), ...(primary.headers || {}) },
    request_headers: { ...(secondary.request_headers || {}), ...(primary.request_headers || {}) },
    request_body: { ...(secondary.request_body || {}), ...(primary.request_body || {}) },
    audio_url: primary.audio_url || secondary.audio_url || "",
    audio_mime: primary.audio_mime || secondary.audio_mime || ""
  };
}

function collectPageData() {
  const all = [...collectDomResources(), ...collectPerformanceResources(), ...collectHookResources()];
  const byUrl = new Map();
  for (const item of all) {
    byUrl.set(item.url, mergePageResource(byUrl.get(item.url), item));
  }
  const active = activeVideoInfo();
  const drm = collectDrmSignals();
  const browserSubtitles = collectBrowserSubtitles();
  return {
    title: document.title,
    page_url: location.href,
    page_text: collectCourseText(),
    active_video: active,
    browser_subtitles: browserSubtitles,
    drm_detected: Boolean(active?.drm_detected || drm.length),
    drm_signals: drm,
    resources: [...byUrl.values()].sort(comparePageResources).slice(0, 60)
  };
}

function pageSignature(data) {
  const active = data.active_video || {};
  const topResources = (data.resources || []).slice(0, 12).map(item => `${item.url}|${item.kind}|${item.score}`).join(";");
  const drm = (data.drm_signals || []).map(item => `${item.source}|${item.key_system}|${item.init_data_type}`).join(";");
  const subtitleTail = (data.browser_subtitles || []).slice(-3).map(item => `${Math.floor(item.start || 0)}|${item.text}`).join(";");
  return [
    location.href,
    active.src || "",
    active.src_object ? `srcObject:${active.src_object_type || "MediaStream"}:${active.src_object_video_tracks || 0}:${active.src_object_audio_tracks || 0}` : "",
    Math.floor(active.current_time || 0),
    active.paused ? "paused" : "playing",
    subtitleTail,
    data.drm_detected ? "drm" : "",
    drm,
    topResources
  ].join("|");
}

function pushDetectedMedia(force = false) {
  const data = collectPageData();
  if (!data.resources.length && !data.active_video && !data.drm_detected) return;
  const signature = pageSignature(data);
  if (!force && signature === lastSignature) return;
  lastSignature = signature;
  lastPushAt = Date.now();
  chrome.runtime.sendMessage({ type: "page-media-detected", page: data }).catch(() => {});
}

function schedulePush(delay = 300, force = false) {
  if (pendingPushTimer) clearTimeout(pendingPushTimer);
  const elapsed = Date.now() - lastPushAt;
  const wait = force || elapsed > 1200 ? delay : Math.max(delay, 1200 - elapsed);
  pendingPushTimer = setTimeout(() => {
    pendingPushTimer = 0;
    pushDetectedMedia(force);
  }, wait);
}

function bindVideo(video) {
  if (!video || boundVideos.has(video)) return;
  boundVideos.add(video);
  for (const eventName of ["play", "playing", "loadedmetadata", "durationchange", "canplay", "emptied", "error"]) {
    video.addEventListener(eventName, () => schedulePush(eventName === "play" ? 80 : 250), { passive: true });
  }
  bindVideoTextTracks(video);
  video.addEventListener("encrypted", event => {
    rememberDrmSignal({
      source: "contentEncrypted",
      init_data_type: event.initDataType || "",
      label: "encrypted event"
    }, video);
    schedulePush(80, true);
  }, { passive: true });
}

function bindVideos() {
  for (const { video } of collectVideos()) {
    bindVideo(video);
    bindVideoTextTracks(video);
  }
}

function isMediaNode(node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
  const selector = `video,source,track,iframe,script,${STATIC_MEDIA_SELECTOR}`;
  if (node.matches?.(selector)) return true;
  if (node.querySelector?.(selector)) return true;
  return Boolean(node.shadowRoot && deepQuerySelectorAll(selector, node.shadowRoot, 20).length);
}

function observeRoot(observer, root) {
  if (!root || observedMutationRoots.has(root)) return;
  try {
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeFilter: [...STATIC_MEDIA_ATTRS, "currentSrc", "type", "poster", "crossorigin"]
    });
    observedMutationRoots.add(root);
  } catch {
    // Some roots can disappear while the page is mutating.
  }
}

function observeOpenShadowRoots(observer) {
  for (const host of deepQuerySelectorAll("*")) {
    if (host?.shadowRoot) observeRoot(observer, host.shadowRoot);
  }
}

function installMutationObserver() {
  if (!document.documentElement) return;
  const observer = new MutationObserver(mutations => {
    let relevant = false;
    let subtitleRelevant = false;
    observeOpenShadowRoots(observer);
    for (const mutation of mutations) {
      if (mutation.type === "attributes") {
        const target = mutation.target;
        if (target?.matches?.("video,source,track,iframe")) relevant = true;
        if (isVisibleSubtitleNode(target)) subtitleRelevant = true;
      }
      if (mutation.type === "characterData" && isVisibleSubtitleNode(mutation.target)) {
        subtitleRelevant = true;
      }
      for (const node of mutation.addedNodes || []) {
        if (isMediaNode(node)) {
          relevant = true;
        }
        if (isVisibleSubtitleNode(node)) {
          subtitleRelevant = true;
        }
      }
    }
    if (!relevant && !subtitleRelevant) return;
    if (relevant) bindVideos();
    schedulePush(subtitleRelevant ? 160 : 250, true);
  });
  observeRoot(observer, document.documentElement);
  observeOpenShadowRoots(observer);
}

function installPerformanceObserver() {
  if (typeof PerformanceObserver === "undefined") return;
  try {
    const observer = new PerformanceObserver(list => {
      const hasMedia = list.getEntries().some(entry => {
        const name = entry.name || "";
        return performanceKind(entry) !== "unknown" || performanceLooksLikeMediaEndpoint(name);
      });
      if (hasMedia) schedulePush(500);
    });
    observer.observe({ type: "resource", buffered: true });
  } catch {
    // Older pages may not support buffered resource observation.
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "collect-page-data") return;
  bindVideos();
  sendResponse(collectPageData());
});

function startWatchers() {
  if (watchersStarted) return;
  watchersStarted = true;
  bindVideos();
  installMutationObserver();
  installPerformanceObserver();
  setTimeout(() => pushDetectedMedia(true), 800);
  setInterval(() => {
    bindVideos();
    schedulePush(400);
  }, 5000);
}

installPageHookBridge();
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startWatchers, { once: true });
  setTimeout(startWatchers, 1000);
} else {
  startWatchers();
}
