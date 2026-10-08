// Pure supplied-data projection: no Chrome API, storage, page hook or network access.
(function installModule(global) {
  "use strict";

const VIDEO_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const AUDIO_RE = /\.(m4a|mp3|aac|opus|ogg|oga|wav)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const PLAYBACK_ENDPOINT_RE = /m3u8|mpd|video|audio|media|subtitle|caption|stream|hls|dash|manifest|playlist|master|playback|player|download|attachment|ananas|objectid|dtoken|fileid|httpmd|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|(?:^|[/?&=._-])(?:source|sources|sourcelist|backup|backups|cdn|baseurl|base_url|base-url|host|domain)(?:[/?&=._-]|$)|\/play(?:[/?#]|$)/i;

function mediaKindFromMime(mime = "") {
  const type = String(mime || "").toLowerCase();
  if (type.includes("mpegurl") || type.includes("application/x-mpegurl")) return "hls";
  if (type.includes("dash+xml")) return "dash";
  if (type.includes("video/") || type.includes("application/mp4")) return "video";
  if (type.includes("audio/") || type.includes("application/ogg")) return "audio";
  if (type.includes("text/vtt") || type.includes("subrip")) return "subtitle";
  return "unknown";
}

function isSubtitleEndpointUrl(url = "") {
  try {
    const parsed = new URL(String(url || ""));
    return /(?:^|[/?&=._-])(?:subtitle|subtitles|caption|captions)(?:[/?&=._-]|$)/i.test(parsed.pathname);
  } catch {
    return /(?:^|[/?&=._-])(?:subtitle|subtitles|caption|captions)(?:[/?&=._-]|$)/i.test(String(url || ""));
  }
}

function classify(url, mime = "") {
  const lower = url.toLowerCase();
  const mimeKind = mediaKindFromMime(mime);
  if (lower.startsWith("blob:")) return "blob";
  if (String(mime || "").toLowerCase().startsWith("image/") || isClearlyNonMediaAssetUrl(lower)) return "unknown";
  if (!FRAGMENT_RE.test(lower) && lower.includes(".m3u8")) return "hls";
  if (!FRAGMENT_RE.test(lower) && lower.includes(".mpd")) return "dash";
  if (mimeKind !== "unknown") return mimeKind;
  if (isSubtitleEndpointUrl(lower)) return "subtitle";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  if (VIDEO_RE.test(lower)) return "video";
  if (AUDIO_RE.test(lower)) return "audio";
  if (SUBTITLE_RE.test(lower)) return "subtitle";
  return "unknown";
}

function isClearlyNonMediaAssetUrl(url = "") {
  let pathname = String(url || "").toLowerCase();
  try {
    pathname = new URL(String(url || "")).pathname.toLowerCase();
  } catch {
    // Keep the raw value for malformed URLs.
  }
  if (/\.(?:css|js|mjs|map|wasm|woff2?|ttf|otf|eot)(?:$|[?#])/i.test(pathname)) return true;
  if (/\.(?:jpe?g|png|gif|webp|avif|svg|ico)(?:$|[?#])/i.test(pathname)) return true;
  return /\.(?:jpe?g|png|gif|webp)(?:@|%40)[^/?#]*\.(?:avi|avif|webp)(?:$|[?#])/i.test(pathname);
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

function urlHost(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

function normalizedFrameUrl(value = "") {
  try {
    const parsed = new URL(value);
    parsed.hash = "";
    return parsed.href;
  } catch {
    return String(value || "").split("#")[0];
  }
}


  global.LearnNoteCaptureClassification = Object.freeze({
    VIDEO_RE,
    AUDIO_RE,
    FRAGMENT_RE,
    SUBTITLE_RE,
    PLAYBACK_ENDPOINT_RE,
    mediaKindFromMime,
    isSubtitleEndpointUrl,
    classify,
    isClearlyNonMediaAssetUrl,
    filenameFromContentDisposition,
    classifyContentDisposition,
    hasRangeEvidence,
    requestHasMediaDestination,
    requestHeaderArrayHasMediaDestination,
    responseContentLength,
    looksLikeLargeBinaryMediaEndpoint,
    looksLikeSmallBinaryPlaybackEndpoint,
    looksLikeTextPlayEndpoint,
    classifyCompletedRequest,
    inferManifestUrl,
    inferSiblingManifestUrls,
    urlHost,
    normalizedFrameUrl,
  });
})(globalThis);
