// Supplied media hints only: page URL is read through the caller; no DOM, capture or network access.
(function (root) {
function createMediaHints({ getPageUrl }) {
const types = root.LearnNoteCaptureClassification;
const { VIDEO_RE, AUDIO_RE, FRAGMENT_RE, SUBTITLE_RE } = types;
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd)(\?|#|$)/i;

const MEDIA_EXT_PATTERN = "mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa";

const IMAGE_URL_RE = /\.(?:avif|webp|jpe?g|png|gif|bmp|svg)(?:@[^/?#]*)?(?:[?#]|$)/i;

const STATIC_MEDIA_KEY_RE = /(url|uri|path|src|address|file|fileid|objectid|dtoken|download|httpmd|play|playlist|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|host|domain|video.?list|audio.?list|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;

const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;

function isSubtitleEndpointUrl(url) { return types.isSubtitleEndpointUrl(url, getPageUrl()); }


function classify(url, mime = "") {
  const lower = String(url || "").toLowerCase();
  const type = String(mime || "").toLowerCase();
  if (IMAGE_URL_RE.test(lower)) return "unknown";
  if (lower.startsWith("blob:")) return "blob";
  if (type.startsWith("image/") || isClearlyNonMediaAssetUrl(lower)) return "unknown";
  if (type.includes("mpegurl")) return "hls";
  if (type.includes("dash+xml")) return "dash";
  if (!FRAGMENT_RE.test(lower) && lower.includes(".m3u8")) return "hls";
  if (!FRAGMENT_RE.test(lower) && lower.includes(".mpd")) return "dash";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower) || isSubtitleEndpointUrl(lower)) return "subtitle";
  if (type.includes("video/") || VIDEO_RE.test(lower)) return "video";
  if (type.includes("audio/") || AUDIO_RE.test(lower)) return "audio";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  return "unknown";
}


function isClearlyNonMediaAssetUrl(url) { return types.isClearlyNonMediaAssetUrl(url, getPageUrl()); }



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
    return new URL(decodeRepeatedUrlComponent(stripUrlTail(url)), getPageUrl()).href;
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
  if (/^(?:video|audio|application|text)\/[a-z0-9.+-]+(?:\s*;\s*codecs?=.+)?$/i.test(text)) return false;
  if (isClearlyNonMediaAssetUrl(text)) return false;
  if (MEDIA_RE.test(text) || FRAGMENT_RE.test(text) || SUBTITLE_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return true;
  if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return STATIC_MEDIA_KEY_RE.test(hint) || MEDIA_RE.test(decodeURIComponentSafe(text));
  if (/^(https?:)?\/\//i.test(text) || text.startsWith("/")) return STATIC_MEDIA_KEY_RE.test(hint);
  return text.includes("/") && /[?=&]|api|play|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|cdn|m3u8|mpd|hls|dash/i.test(text) && STATIC_MEDIA_KEY_RE.test(hint);
}


function looksLikePlaybackEndpointValue(value, hint = "") {
  const text = decodeURIComponentSafe(decodeJsStringEscapes(String(value || ""))).trim();
  if (!text || !STATIC_MEDIA_KEY_RE.test(hint)) return false;
  if (isSubtitleEndpointUrl(text)) return false;
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
    const current = new URL(getPageUrl());
    if (raw.startsWith("//")) return `${current.protocol}${raw}`.replace(/\/?$/, "/");
    if (/^https?:\/\//i.test(raw)) return raw.replace(/\/?$/, "/");
    if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:\/.*)?$/.test(raw)) {
      return `${current.protocol}//${raw}`.replace(/\/?$/, "/");
    }
    if (raw.startsWith("/") && /^(basepath|pathprefix|root|prefix|dir|directory)$/.test(keyContext)) {
      return new URL(raw, getPageUrl()).href.replace(/\/?$/, "/");
    }
    if (raw.endsWith("/") && /^(basepath|pathprefix|root|prefix|dir|directory)$/.test(keyContext)) {
      return new URL(raw, getPageUrl()).href.replace(/\/?$/, "/");
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
    currentOrigin = new URL(getPageUrl()).origin;
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
        const parsed = new URL(url, getPageUrl());
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
        const host = new URL(hostBase, getPageUrl());
        const path = new URL(pathBase, getPageUrl());
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
      origin = new URL(getPageUrl()).origin;
    } catch {
      origin = "";
    }
  }
  return bases.sort((a, b) => {
    try {
      const parsedA = new URL(a, getPageUrl());
      const parsedB = new URL(b, getPageUrl());
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


return Object.freeze({
  MEDIA_RE,
  FRAGMENT_RE,
  SUBTITLE_RE,
  MEDIA_EXT_PATTERN,
  IMAGE_URL_RE,
  STATIC_MEDIA_KEY_RE,
  isSubtitleEndpointUrl,
  classify,
  score,
  scoreForKind,
  absoluteUrl,
  appendRepeatedUrlDecodes,
  decodeJsStringEscapes,
  decodedValues,
  mimeFromHint,
  looksLikeMediaValue,
  looksLikePlaybackEndpointValue,
  isStaticBaseOnlyKey,
  staticJsonBaseUrls,
  sortStaticBaseUrls,
  looksLikeStaticSplitMediaPath,
  staticSplitCandidateValues,
  mimeForStaticSplit,
});
}
root.LearnNoteContentMediaHints = Object.freeze({ createMediaHints });
})(globalThis);
