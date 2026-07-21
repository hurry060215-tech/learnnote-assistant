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
  "data-playurl",
  "data-play-url-hd",
  "data-path",
  "data-uri",
  "data-media-url",
  "data-main-url",
  "data-master-url",
  "data-manifest-url",
  "data-stream-url",
  "data-hls-url",
  "data-m3u8-url",
  "data-dash-url",
  "data-mpd-url",
  "data-backup-url",
  "data-download-url",
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
const STATIC_MEDIA_KEY_RE = /(url|uri|path|src|address|file|fileid|objectid|dtoken|download|httpmd|play|playlist|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|host|domain|video.?list|audio.?list|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
const STATIC_ATTRIBUTE_KEY_RE = /(url|uri|path|src|address|file|objectid|dtoken|download|httpmd|play|playlist|player|config|option|param|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|host|domain|video.?list|audio.?list|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
const VISIBLE_SUBTITLE_HINT_RE = /(subtitle|subtitles|caption|captions|closed.?caption|text[-_ ]?track|texttrack|\bcue(?:s)?\b|vtt|\bcc\b|字幕|ytp-caption|vjs-text-track|jw-text-track|plyr__captions|shaka-text-container|xgplayer[-_ ].*(text|subtitle|caption)|dplayer[-_ ].*subtitle|bilibili.*subtitle|bpx.*subtitle|ananas.*(subtitle|caption|texttrack)|chaoxing.*(subtitle|caption|texttrack))/i;
const VISIBLE_SUBTITLE_ATTR_RE = /^(data-|aria-|role$|lang$|srclang$|class$|id$|title$)/i;
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
const STATIC_SCAN_TTL_MS = 30000;
const COURSE_TEXT_TTL_MS = 30000;
const PERIODIC_SCAN_MS = 15000;
const MAX_VISIBLE_SUBTITLE_HISTORY = 1200;
const visibleSubtitleHistory = [];
let pendingPushTimer = 0;
let lastPushAt = 0;
let lastSignature = "";
let watchersStarted = false;
let pageIdentity = `content:1:${String(location.href || "")}`;
let performanceNavigationStart = 0;
let cachedStableDomResources = [];
let stableDomResourcesAt = 0;
let cachedCourseText = "";
let courseTextAt = 0;

function resetPageResources(nextIdentity = "") {
  pageIdentity = nextIdentity || `content:${Date.now()}:${String(location.href || "")}`;
  hookResources.length = 0;
  drmSignals.length = 0;
  visibleSubtitleHistory.length = 0;
  lastSignature = "";
  cachedStableDomResources = [];
  stableDomResourcesAt = 0;
  cachedCourseText = "";
  courseTextAt = 0;
  performanceNavigationStart = Number(performance.now?.() || 0);
}

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
  return text.includes("/") && /[?=&]|api|play|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|cdn|m3u8|mpd|hls|dash/i.test(text) && STATIC_MEDIA_KEY_RE.test(hint);
}

function looksLikePlaybackEndpointValue(value, hint = "") {
  const text = decodeURIComponentSafe(decodeJsStringEscapes(String(value || ""))).trim();
  if (!text || !STATIC_MEDIA_KEY_RE.test(hint)) return false;
  if (!/^(https?:)?\/\//i.test(text) && !text.startsWith("/") && !text.includes("/")) return false;
  if (MEDIA_RE.test(text) || FRAGMENT_RE.test(text) || SUBTITLE_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return false;
  return /(^|[/?&=._-])(api|ananas|play|player|stream|video|audio|media|source|sources|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|base-url|host|domain|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|dash|playlist|m3u8|mpd|objectid|dtoken)([/?&=._-]|$)/i.test(text);
}

function decodeURIComponentSafe(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function isStaticBaseOnlyKey(key = "") {
  const normalized = String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return [
    "baseurl",
    "basepath",
    "pathprefix",
    "cdn",
    "host",
    "domain",
    "origin",
    "endpoint",
    "server",
    "root",
    "prefix",
    "dir",
    "directory"
  ].includes(normalized);
}

function normalizeStaticBaseUrl(value, key = "") {
  const raw = String(value || "").trim().replace(/^['"]|['"]$/g, "");
  if (!raw || /\s/.test(raw)) return "";
  const keyContext = String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  try {
    const current = new URL(location.href);
    if (raw.startsWith("//")) return `${current.protocol}${raw}`.replace(/\/?$/, "/");
    if (/^https?:\/\//i.test(raw)) return raw.replace(/\/?$/, "/");
    if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:\/.*)?$/.test(raw)) {
      return `${current.protocol}//${raw}`.replace(/\/?$/, "/");
    }
    if (raw.startsWith("/") && /^(basepath|pathprefix|root|prefix|dir|directory)$/.test(keyContext)) {
      return new URL(raw, location.href).href.replace(/\/?$/, "/");
    }
    if (raw.endsWith("/") && /^(basepath|pathprefix|root|prefix|dir|directory)$/.test(keyContext)) {
      return new URL(raw, location.href).href.replace(/\/?$/, "/");
    }
  } catch {
    return "";
  }
  return "";
}

function staticJsonBaseUrls(node) {
  if (!node || typeof node !== "object" || Array.isArray(node)) return [];
  const bases = [];
  const hostBases = [];
  const pathBases = [];
  let currentOrigin = "";
  try {
    currentOrigin = new URL(location.href).origin;
  } catch {
    currentOrigin = "";
  }
  const add = (url, bucket = null) => {
    if (!url || bases.includes(url)) return;
    bases.push(url);
    if (bucket && !bucket.includes(url)) bucket.push(url);
  };
  for (const [key, value] of Object.entries(node).slice(0, 120)) {
    if (typeof value !== "string" || !isStaticBaseOnlyKey(key)) continue;
    for (const candidateValue of decodedValues(value)) {
      const url = normalizeStaticBaseUrl(candidateValue, key);
      if (!url) continue;
      try {
        const parsed = new URL(url, location.href);
        const raw = String(candidateValue || "").trim().replace(/^['"]|['"]$/g, "");
        if (parsed.pathname.replace(/\/+$/, "") === "") add(url, hostBases);
        else if (raw.startsWith("/") && parsed.origin === currentOrigin) add(url, pathBases);
        else add(url);
      } catch {
        add(url);
      }
    }
  }
  for (const hostBase of hostBases) {
    for (const pathBase of pathBases) {
      try {
        const host = new URL(hostBase, location.href);
        const path = new URL(pathBase, location.href);
        add(`${host.origin}${path.pathname}`.replace(/\/?$/, "/"));
      } catch {
        // Ignore invalid synthetic bases.
      }
    }
  }
  return sortStaticBaseUrls(bases, currentOrigin).slice(0, 8);
}

function sortStaticBaseUrls(bases = [], currentOrigin = "") {
  let origin = currentOrigin;
  if (!origin) {
    try {
      origin = new URL(location.href).origin;
    } catch {
      origin = "";
    }
  }
  return bases.sort((a, b) => {
    try {
      const parsedA = new URL(a, location.href);
      const parsedB = new URL(b, location.href);
      const pathDelta = parsedB.pathname.length - parsedA.pathname.length;
      if (pathDelta) return pathDelta;
      return Number(parsedB.origin !== origin) - Number(parsedA.origin !== origin);
    } catch {
      return b.length - a.length;
    }
  });
}

function staticJsonMimeContext(node) {
  if (!node || typeof node !== "object" || Array.isArray(node)) return "";
  return Object.entries(node)
    .filter(([key, value]) => /(mime|type|format|content.?type|media.?type)/i.test(key) && typeof value === "string")
    .map(([, value]) => value)
    .join(" ");
}

function looksLikeStaticSplitMediaPath(value, key, node) {
  const text = String(value || "").trim().replace(/^['"]|['"]$/g, "");
  if (!text || /\s/.test(text)) return false;
  const decoded = decodeURIComponentSafe(decodeJsStringEscapes(text));
  if (/^(?:https?:)?\/\//i.test(decoded)) return false;
  if (/^(audio|video|application|text)\/[a-z0-9.+-]+$/i.test(text)) return false;
  if (/^(?:https?:)?\/\//i.test(text)) return false;
  if (/^(data|blob|javascript):/i.test(text)) return false;
  if (MEDIA_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return true;
  return STATIC_MEDIA_KEY_RE.test(key) && /video\/|mpegurl|dash\+xml|audio\//i.test(staticJsonMimeContext(node));
}

function staticSplitCandidateValues(value) {
  const raw = decodeJsStringEscapes(String(value || "").trim()).replace(/&amp;/g, "&");
  const values = raw ? [raw] : [];
  appendRepeatedUrlDecodes(values, raw);
  for (const item of decodedValues(value)) {
    if (item && !values.includes(item)) values.push(item);
  }
  return values;
}

function mimeForStaticSplit(key, value, node) {
  return mimeFromHint(`${key} ${value} ${staticJsonMimeContext(node)}`);
}

function collectStaticSplitBaseResourcesFromNode(node, source, label, seen, limit, inheritedBases = [], visited = new WeakSet()) {
  const resources = [];
  if (!node || typeof node !== "object" || resources.length >= limit) return resources;
  if (visited.has(node)) return resources;
  visited.add(node);
  if (Array.isArray(node)) {
    for (const child of node.slice(0, 120)) {
      resources.push(...collectStaticSplitBaseResourcesFromNode(child, source, label, seen, limit - resources.length, inheritedBases, visited));
      if (resources.length >= limit) break;
    }
    return resources;
  }
  const bases = staticJsonBaseUrls(node);
  for (const inherited of inheritedBases || []) {
    if (inherited && !bases.includes(inherited)) bases.push(inherited);
  }
  sortStaticBaseUrls(bases);
  for (const [key, value] of Object.entries(node).slice(0, 160)) {
    if (typeof value === "string" && STATIC_MEDIA_KEY_RE.test(key) && !isStaticBaseOnlyKey(key)) {
      for (const candidateValue of staticSplitCandidateValues(value)) {
        if (!looksLikeStaticSplitMediaPath(candidateValue, key, node)) continue;
        for (const base of bases) {
          let url = "";
          try {
            const path = String(candidateValue || "").startsWith("/")
              ? String(candidateValue || "")
              : String(candidateValue || "").replace(/^\/+/, "");
            url = new URL(path, base).href;
          } catch {
            continue;
          }
          const item = resource(url, source, `${label} json combined ${key}`, mimeForStaticSplit(key, candidateValue, node));
          if (!item || item.kind === "unknown" || seen.has(item.url)) continue;
          seen.add(item.url);
          item.score = Math.max(item.score || 0, scoreForKind(item.kind, { manifest: 96, video: 84, audio: 38, other: 62 }));
          resources.push(item);
          break;
        }
        if (resources.length >= limit) break;
      }
    }
    if (value && typeof value === "object") {
      resources.push(...collectStaticSplitBaseResourcesFromNode(value, source, label, seen, limit - resources.length, bases, visited));
    }
    if (resources.length >= limit) break;
  }
  return resources;
}

function collectStaticSplitBaseResources(text, source, label, seen = new Set(), limit = 40) {
  const trimmed = String(text || "").trim();
  if (!trimmed || !"{[".includes(trimmed[0])) return [];
  try {
    return collectStaticSplitBaseResourcesFromNode(JSON.parse(trimmed), source, label, seen, limit);
  } catch {
    return [];
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
  const visibility = video ? elementVisibilityEvidence(video) : {};
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
    ...visibility,
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
    for (const item of collectStaticSplitBaseResources(text, source, `${label} nested`, seen, Math.max(0, limit - resources.length))) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
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
  const endpointRe = /(^|[/?&=._-])(api|ananas|play|player|stream|video|audio|media|source|sources|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|base-url|host|domain|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|dash|playlist|m3u8|mpd|objectid|dtoken|fileid|httpmd|subtitle|caption)([/?&=._-]|$)/i;
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
  if (item?.page_identity && item.page_identity !== pageIdentity) return;
  if (/^image\//i.test(String(item?.mime || ""))) return;
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
  normalized.visibility = item.visibility || normalized.visibility || "unknown";
  normalized.is_visible = item.is_visible ?? normalized.is_visible ?? null;
  normalized.visible_area = item.visible_area ?? normalized.visible_area ?? null;
  normalized.rendered_width = item.rendered_width ?? normalized.rendered_width ?? null;
  normalized.rendered_height = item.rendered_height ?? normalized.rendered_height ?? null;
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
      audio_mime: normalized.audio_mime || existing.audio_mime || "",
      visibility: normalized.visibility !== "unknown" ? normalized.visibility : existing.visibility || "unknown",
      is_visible: normalized.is_visible ?? existing.is_visible ?? null,
      visible_area: normalized.visible_area ?? existing.visible_area ?? null,
      rendered_width: normalized.rendered_width ?? existing.rendered_width ?? null,
      rendered_height: normalized.rendered_height ?? existing.rendered_height ?? null
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
    const incomingIdentity = String(event.data.page_identity || "");
    if (incomingIdentity && incomingIdentity !== pageIdentity) resetPageResources(incomingIdentity);
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

function chaoxingStatusResourceFromIframe(iframe) {
  const frameSrc = readAttribute(iframe, "src");
  const marker = [
    frameSrc,
    readAttribute(iframe, "class"),
    readAttribute(iframe, "data")
  ].join(" ");
  if (!/ananas\/modules\/video|ans-insertvideo|chaoxing|xuexitong/i.test(marker)) return null;

  let objectId = readAttribute(iframe, "objectid") || readAttribute(iframe, "data-objectid");
  if (!objectId) {
    const data = readAttribute(iframe, "data");
    const match = String(data || "").match(/["']objectid["']\s*:\s*["']([A-Za-z0-9_-]{8,128})["']/i);
    objectId = match?.[1] || "";
  }
  if (!/^[A-Za-z0-9_-]{8,128}$/.test(objectId)) return null;

  try {
    const frameUrl = new URL(frameSrc || location.href, location.href);
    const endpoint = new URL(`/ananas/status/${encodeURIComponent(objectId)}`, frameUrl.origin);
    endpoint.searchParams.set("k", "");
    endpoint.searchParams.set("flag", "normal");
    const item = resource(endpoint.href, "domHint", "Chaoxing object status", "video/mp4", null, true, "objectid-status");
    if (!item) return null;
    item.frame_url = frameUrl.href;
    item.page_url = location.href;
    item.request_headers = { Referer: location.href };
    return item;
  } catch {
    return null;
  }
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
  const limit = 60;
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
      if (!STATIC_MEDIA_KEY_RE.test(key) || isStaticBaseOnlyKey(key)) continue;
      const item = resourceFromHint(match[2], "scriptHint", `script ${key}`, key);
      if (item && !seen.has(item.url)) {
        seen.add(item.url);
        item.score = Math.max(item.score || 0, scoreForKind(item.kind));
        resources.push(item);
        if (resources.length >= limit) return resources;
      }
      for (const nestedItem of collectNestedFieldResources(match[2], "scriptHint", `script ${key}`, seen, limit - resources.length)) {
        resources.push(nestedItem);
        if (resources.length >= limit) return resources;
      }
    }
    for (const item of collectKeyedContainerResources(text, "scriptHint", "script", seen, limit - resources.length)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
    for (const item of collectTextMediaResources(text, "scriptHint", "script media url", seen)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
    for (const item of collectEncodedTextResources(text, "scriptHint", "script encoded url", seen)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
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
  for (const item of collectStaticSplitBaseResources(body, source, label, seen, limit - resources.length)) {
    resources.push(item);
    if (resources.length >= limit) return resources;
  }
  for (const match of body.matchAll(STATIC_FIELD_RE)) {
    const key = String(match[1] || "").replace(/^["']|["']$/g, "");
    if (!STATIC_MEDIA_KEY_RE.test(key) || isStaticBaseOnlyKey(key)) continue;
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
  const resources = [
    ...collectUrlParameterResources(url, source, label, seen, 40)
  ];
  if (resources.length < 40) {
    resources.push(...collectTextMediaResources(url, source, `${label} media url`, seen));
  }
  if (resources.length < 40) {
    resources.push(...collectEncodedTextResources(url, source, `${label} encoded url`, seen));
  }
  return resources;
}

function collectUrlParameterResources(url, source = "domHint", label = "page url", seen = new Set(), limit = 30) {
  const resources = [];
  if (!url || limit <= 0) return resources;
  let parsed = null;
  try {
    parsed = new URL(url, location.href);
  } catch {
    return resources;
  }
  const chunks = [
    ["query", parsed.search],
    ["hash", parsed.hash]
  ];
  for (const [scope, rawChunk] of chunks) {
    let chunk = String(rawChunk || "").replace(/^[?#]/, "");
    if (!chunk) continue;
    const nestedQueryIndex = chunk.indexOf("?");
    if (nestedQueryIndex >= 0) chunk = chunk.slice(nestedQueryIndex + 1);
    if (!/[=&]/.test(chunk)) continue;
    let params = null;
    try {
      params = new URLSearchParams(chunk);
    } catch {
      continue;
    }
    for (const [key, value] of Array.from(params.entries()).slice(0, 80)) {
      if (!value || resources.length >= limit) break;
      const paramLabel = `${label} ${scope} ${key} param`;
      const direct = resourceFromHint(value, source, paramLabel, key);
      if (direct && !seen.has(direct.url)) {
        seen.add(direct.url);
        direct.score = Math.max(direct.score || 0, scoreForKind(direct.kind, { manifest: 96, video: 84, audio: 38, other: 62 }));
        resources.push(direct);
        if (resources.length >= limit) break;
      }
      for (const item of collectRawUrlParameterPayloadResources(value, source, paramLabel, seen, limit - resources.length)) {
        resources.push(item);
        if (resources.length >= limit) break;
      }
      for (const item of collectNestedFieldResources(value, source, paramLabel, seen, limit - resources.length)) {
        resources.push(item);
        if (resources.length >= limit) break;
      }
    }
  }
  return resources;
}

function rawUrlParameterPayloads(value) {
  const raw = decodeJsStringEscapes(String(value || "").trim()).replace(/&amp;/g, "&");
  const values = raw ? [raw] : [];
  appendRepeatedUrlDecodes(values, raw);
  return values
    .map(item => String(item || "").trim())
    .filter((item, index, list) => item && list.indexOf(item) === index && (item[0] === "{" || item[0] === "["));
}

function collectRawUrlParameterPayloadResources(value, source, label, seen = new Set(), limit = 20) {
  const resources = [];
  for (const payload of rawUrlParameterPayloads(value)) {
    for (const item of collectStaticSplitBaseResources(payload, source, `${label} payload`, seen, limit - resources.length)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
    for (const item of collectHtmlTextResources(payload, source, `${label} payload`, seen, limit - resources.length, 1)) {
      resources.push(item);
      if (resources.length >= limit) return resources;
    }
  }
  return resources;
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

function elementVisibilityEvidence(element) {
  if (!element) return {
    visibility: "unknown",
    is_visible: null,
    visible_area: null,
    rendered_width: null,
    rendered_height: null
  };
  let rect = null;
  try {
    rect = element.getBoundingClientRect?.() || null;
  } catch {
    rect = null;
  }
  const width = Math.max(0, Number(rect?.width ?? element.clientWidth ?? element.videoWidth ?? 0));
  const height = Math.max(0, Number(rect?.height ?? element.clientHeight ?? element.videoHeight ?? 0));
  let style = null;
  try {
    style = typeof window.getComputedStyle === "function" ? window.getComputedStyle(element) : null;
  } catch {
    style = null;
  }
  const explicitlyHidden = Boolean(
    element.hidden ||
    readAttribute(element, "aria-hidden") === "true" ||
    style?.display === "none" ||
    style?.visibility === "hidden" ||
    Number(style?.opacity ?? 1) <= 0
  );
  const viewportWidth = Math.max(0, Number(window.innerWidth || document.documentElement?.clientWidth || width));
  const viewportHeight = Math.max(0, Number(window.innerHeight || document.documentElement?.clientHeight || height));
  const hasRectPosition = rect && Number.isFinite(Number(rect.left)) && Number.isFinite(Number(rect.top));
  const intersectionWidth = hasRectPosition
    ? Math.max(0, Math.min(Number(rect.right ?? (rect.left + width)), viewportWidth) - Math.max(Number(rect.left), 0))
    : width;
  const intersectionHeight = hasRectPosition
    ? Math.max(0, Math.min(Number(rect.bottom ?? (rect.top + height)), viewportHeight) - Math.max(Number(rect.top), 0))
    : height;
  const visibleArea = explicitlyHidden ? 0 : intersectionWidth * intersectionHeight;
  const isVisible = !explicitlyHidden && width > 0 && height > 0 && visibleArea > 0;
  return {
    visibility: explicitlyHidden ? "hidden" : isVisible ? "visible" : hasRectPosition ? "offscreen" : "unknown",
    is_visible: isVisible,
    visible_area: visibleArea,
    rendered_width: width,
    rendered_height: height
  };
}

function collectFrameElementEvidence() {
  return deepQuerySelectorAll("iframe").map((iframe, index) => ({
    index,
    src: absoluteUrl(iframe.src || readAttribute(iframe, "src")),
    title: readAttribute(iframe, "title") || iframe.name || "",
    ...elementVisibilityEvidence(iframe)
  })).filter(item => item.src);
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
  return videos
    .filter(({ video }) => hasVideoSourceSignal(video))
    .sort((a, b) => {
      const evidenceA = elementVisibilityEvidence(a.video);
      const evidenceB = elementVisibilityEvidence(b.video);
      const rankA = [
        evidenceA.is_visible ? 1 : 0,
        !a.video.paused && !a.video.ended && a.video.readyState >= 2 ? 1 : 0,
        Number(evidenceA.visible_area || 0),
        Number(a.video.videoWidth || 0) * Number(a.video.videoHeight || 0)
      ];
      const rankB = [
        evidenceB.is_visible ? 1 : 0,
        !b.video.paused && !b.video.ended && b.video.readyState >= 2 ? 1 : 0,
        Number(evidenceB.visible_area || 0),
        Number(b.video.videoWidth || 0) * Number(b.video.videoHeight || 0)
      ];
      for (let index = 0; index < rankA.length; index += 1) {
        if (rankA[index] !== rankB[index]) return rankB[index] - rankA[index];
      }
      return a.index - b.index;
    })[0] || null;
}

function activeVideoInfo() {
  const videos = collectVideos();
  const withSource = pickMainVideo(videos);
  if (!withSource) return null;
  const { video, index } = withSource;
  const drm = drmByVideo.get(video) || {};
  const srcObject = videoSrcObjectInfo(video);
  const visibility = elementVisibilityEvidence(video);
  return {
    src: absoluteUrl(video.currentSrc || video.src),
    poster_url: absoluteUrl(video.poster || readAttribute(video, "poster")),
    ...srcObject,
    current_time: Number(video.currentTime || 0),
    duration: Number.isFinite(video.duration) ? Number(video.duration || 0) : 0,
    paused: Boolean(video.paused),
    width: Number(video.videoWidth || video.clientWidth || 0),
    height: Number(video.videoHeight || video.clientHeight || 0),
    ...visibility,
    frame_id: 0,
    frame_url: location.href,
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
  for (const [name, value] of elementAttributeEntries(element)) {
    const hint = `${name} ${value}`.slice(0, 220);
    if (VISIBLE_SUBTITLE_ATTR_RE.test(name) || VISIBLE_SUBTITLE_HINT_RE.test(hint)) {
      values.push(hint);
    }
  }
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

function collectStableDomResources(force = false) {
  const now = Date.now();
  if (!force && stableDomResourcesAt && now - stableDomResourcesAt < STATIC_SCAN_TTL_MS) {
    return cachedStableDomResources.map(item => ({ ...item }));
  }
  const resources = [
    ...collectUrlEmbeddedResources(location.href, "locationHint", "current page URL"),
    ...collectIframeEmbeddedResources(),
    ...collectStaticAttributeResources(),
    ...collectDeclaredMediaResources(),
    ...collectInlineScriptResources()
  ];
  for (const source of deepQuerySelectorAll("source")) {
    resources.push(resource(mediaElementUrl(source), "dom", "source", source.type || ""));
  }
  for (const track of deepQuerySelectorAll("track")) {
    const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
    resources.push(resource(mediaElementUrl(track), "subtitleTrack", label || "subtitle", "text/vtt"));
  }
  for (const iframe of deepQuerySelectorAll("iframe[src]")) {
    const chaoxingStatus = chaoxingStatusResourceFromIframe(iframe);
    if (chaoxingStatus) resources.push(chaoxingStatus);
    resources.push(...collectUrlEmbeddedResources(iframe.src, "domHint", "iframe URL"));
    if (/chaoxing|xuexitong|video|player|course|m3u8|mpd/i.test(iframe.src)) {
      resources.push(resource(iframe.src, "dom", "iframe"));
    }
  }
  cachedStableDomResources = resources.filter(Boolean).map(item => ({ ...item }));
  stableDomResourcesAt = now;
  return cachedStableDomResources.map(item => ({ ...item }));
}

function collectDomResources(forceFullScan = false) {
  const stableResources = collectStableDomResources(forceFullScan);
  const resources = [];
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
  return [...resources, ...stableResources].filter(Boolean);
}

function collectPerformanceResources() {
  const resources = [];
  for (const entry of performance.getEntriesByType("resource")) {
    if (performanceNavigationStart > 0 && Number.isFinite(Number(entry.startTime)) && Number(entry.startTime) < performanceNavigationStart) continue;
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

function collectCourseText(force = false) {
  const now = Date.now();
  if (!force && courseTextAt && now - courseTextAt < COURSE_TEXT_TTL_MS) return cachedCourseText;
  const candidates = [
    ...deepQuerySelectorAll("h1,h2,h3,.course-title,.chapter-title,.ans-job-icon,.title,.name")
  ];
  const headings = candidates.map(el => el.textContent?.trim()).filter(Boolean).slice(0, 40).join("\n");
  const body = document.body?.innerText || "";
  const shadowText = collectShadowTexts();
  cachedCourseText = [headings, body, shadowText].filter(Boolean).join("\n\n").slice(0, 60000);
  courseTextAt = now;
  return cachedCourseText;
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
    audio_mime: primary.audio_mime || secondary.audio_mime || "",
    visibility: primary.visibility !== "unknown" ? primary.visibility : secondary.visibility || "unknown",
    is_visible: primary.is_visible ?? secondary.is_visible ?? null,
    visible_area: primary.visible_area ?? secondary.visible_area ?? null,
    rendered_width: primary.rendered_width ?? secondary.rendered_width ?? null,
    rendered_height: primary.rendered_height ?? secondary.rendered_height ?? null
  };
}

function collectPageData(forceFullScan = false) {
  const all = [...collectDomResources(forceFullScan), ...collectPerformanceResources(), ...collectHookResources()];
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
    page_text: collectCourseText(forceFullScan),
    active_video: active,
    browser_subtitles: browserSubtitles,
    drm_detected: Boolean(active?.drm_detected || drm.length),
    drm_signals: drm,
    resources: [...byUrl.values()]
      .filter(item => !item.page_identity || item.page_identity === pageIdentity)
      .map(item => ({ ...item, page_url: item.page_url || location.href, page_identity: pageIdentity }))
      .sort(comparePageResources)
      .slice(0, 80),
    page_identity: pageIdentity,
    frame_elements: collectFrameElementEvidence()
  };
}

function pageSignature(data) {
  const active = data.active_video || {};
  const topResources = (data.resources || []).slice(0, 12).map(item => `${item.url}|${item.kind}|${item.score}`).join(";");
  const frames = (data.frame_elements || []).map(item => `${item.src}|${item.visibility}|${Math.round(item.visible_area || 0)}`).join(";");
  const drm = (data.drm_signals || []).map(item => `${item.source}|${item.key_system}|${item.init_data_type}`).join(";");
  const subtitleTail = (data.browser_subtitles || []).slice(-3).map(item => `${Math.floor(item.start || 0)}|${item.text}`).join(";");
  return [
    location.href,
    active.src || "",
    active.src_object ? `srcObject:${active.src_object_type || "MediaStream"}:${active.src_object_video_tracks || 0}:${active.src_object_audio_tracks || 0}` : "",
    Math.floor((active.current_time || 0) / 15),
    active.paused ? "paused" : "playing",
    active.visibility || "unknown",
    Math.round(active.visible_area || 0),
    frames,
    subtitleTail,
    data.drm_detected ? "drm" : "",
    drm,
    topResources
  ].join("|");
}

function pushDetectedMedia(force = false, forceFullScan = false) {
  const data = collectPageData(forceFullScan);
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
      characterData: false,
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

function observeAddedShadowRoots(observer, node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
  if (node.shadowRoot) observeRoot(observer, node.shadowRoot);
  for (const host of safeQueryAll(node, "*")) {
    if (host?.shadowRoot) observeRoot(observer, host.shadowRoot);
  }
}

function installMutationObserver() {
  if (!document.documentElement) return;
  const observer = new MutationObserver(mutations => {
    let relevant = false;
    let subtitleRelevant = false;
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
        observeAddedShadowRoots(observer, node);
        if (isMediaNode(node)) {
          relevant = true;
        }
        if (isVisibleSubtitleNode(node)) {
          subtitleRelevant = true;
        }
      }
    }
    if (!relevant && !subtitleRelevant) return;
    if (relevant) {
      stableDomResourcesAt = 0;
      bindVideos();
    }
    if (subtitleRelevant) courseTextAt = 0;
    schedulePush(subtitleRelevant ? 300 : 500);
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
  sendResponse(collectPageData(true));
});

function startWatchers() {
  if (watchersStarted) return;
  watchersStarted = true;
  bindVideos();
  installMutationObserver();
  installPerformanceObserver();
  setTimeout(() => pushDetectedMedia(true, true), 800);
  setInterval(() => {
    if (document.hidden) return;
    bindVideos();
    schedulePush(400);
  }, PERIODIC_SCAN_MS);
}

window.addEventListener("popstate", () => {
  resetPageResources();
  schedulePush(120, true);
});
window.addEventListener("hashchange", () => {
  resetPageResources();
  schedulePush(120, true);
});

installPageHookBridge();
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startWatchers, { once: true });
  setTimeout(startWatchers, 1000);
} else {
  startWatchers();
}
