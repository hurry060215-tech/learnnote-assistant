(function () {
  if (window.__learnNotePageHookInstalled) return;
  window.__learnNotePageHookInstalled = true;

  const MEDIA_URL_RE = /(?:https?:)?\/\/[^\s"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:\/[^\s"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+\/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?/gi;
  const ENCODED_MEDIA_URL_RE = /https?%(?:25)*3A(?:(?:%(?:25)*2F)|\/){2}[^\s"'<>\\]+?(?:\.|%(?:25)*2E)(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:[^\s"'<>\\]*)?/gi;
  const MEDIA_HINT_RE = /\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:[?#]|["'\s<>]|$)/i;
  const FRAGMENT_RE = /\.(?:m4s|ts)(?:\?|#|$)/i;
  const TEXT_TYPE_RE = /json|text|javascript|mpegurl|dash\+xml|xml|x-mpegurl/i;
  const JSON_MEDIA_KEY_RE = /(url|src|file|fileid|objectid|dtoken|download|httpmd|play|media|video|stream|source|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
  const JSON_MIME_KEY_RE = /(mime|type|format|content.?type|media.?type)/i;
  const GLOBAL_MEDIA_NAME_RE = /(^__.*(play|player|media|video|stream|hls|dash|m3u8|mpd))|((play|player|media|video|stream|hls|dash|m3u8|mpd).*(config|info|data|url|source|sources|list)$)/i;
  const GLOBAL_MEDIA_KEYS = [
    "__playInfo",
    "__playerConfig",
    "__videoInfo",
    "__videoData",
    "__INITIAL_STATE__",
    "__NEXT_DATA__",
    "playInfo",
    "playerInfo",
    "playerConfig",
    "videoInfo",
    "videoData",
    "videoConfig",
    "mediaInfo",
    "mediaData",
    "courseData",
    "lessonData"
  ];
  const TEXT_MEDIA_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*["']((?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^"'<>\\\s]){4,})["']/gi;
  const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;
  const MAX_TEXT_BYTES = 2 * 1024 * 1024;
  const MAX_BLOB_URLS = 80;
  const RESPONSE_HEADER_ALLOWLIST = ["accept-ranges", "content-disposition", "content-length", "content-range", "content-type"];
  const REQUEST_HEADER_ALLOWLIST = new Set([
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "range",
    "referer",
    "x-requested-with"
  ]);
  const REQUEST_HEADER_CANONICAL = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "content-type": "Content-Type",
    "origin": "Origin",
    "range": "Range",
    "referer": "Referer",
    "x-requested-with": "X-Requested-With"
  };
  const bufferedResources = [];
  const drmSignals = [];
  const blobSourceByObject = new WeakMap();
  const blobPartSourceByObject = new WeakMap();
  const blobSourceByUrl = new Map();
  const blobUrlOrder = [];
  const streamSourceByObject = new WeakMap();
  const streamReaderSourceByObject = new WeakMap();
  const responseMetaByObject = new WeakMap();
  const mediaSourceMetaByObject = new WeakMap();
  const mediaSourceUrlByObject = new WeakMap();
  const sourceBufferMediaSource = new WeakMap();
  let patchingLatePlayerGlobal = false;

  function normalizeUrl(raw) {
    if (!raw) return "";
    const cleaned = decodeRepeatedUrlComponent(decodeJsStringEscapes(stripUrlTail(raw))
      .replace(/&amp;/g, "&")
      .trim());
    try {
      return new URL(cleaned, location.href).href;
    } catch {
      return "";
    }
  }

  function stripUrlTail(value) {
    let text = String(value || "").trim();
    if (/^blob:https?:\/\//i.test(text)) return text;
    const absoluteIndex = text.search(/https?:\/\//i);
    if (absoluteIndex > 0) text = text.slice(absoluteIndex);
    if (!/^(https?:)?\/\//i.test(text)) {
      const rootRelativeIndex = text.search(/\/[^\s"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:[?#]|$)/i);
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

  function mediaKind(url, mime = "") {
    const lower = String(url || "").toLowerCase();
    const type = String(mime || "").toLowerCase();
    if (FRAGMENT_RE.test(lower)) return "fragment";
    if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
    if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
    if (type.includes("text/vtt") || type.includes("subrip") || /\.(vtt|srt|ass|ssa)(\?|#|$)/i.test(lower)) return "subtitle";
    if (type.includes("video/") || /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i.test(lower)) return "video";
    return "unknown";
  }

  function manifestKindFromText(text, mime = "") {
    const head = String(text || "").slice(0, 4096).trimStart();
    const type = String(mime || "").toLowerCase();
    if (head.startsWith("#EXTM3U") || type.includes("mpegurl") || type.includes("x-mpegurl")) return "hls";
    if (/<MPD[\s>]/i.test(head)) return "dash";
    return "unknown";
  }

  function mediaUrlHint(url = "") {
    return /(^|[/?&=._-])(m3u8|mpd|hls|dash|manifest|playlist|master|stream|play|video|media)([/?&=._-]|$)/i.test(String(url || ""));
  }

  function post(resources = [], drm = []) {
    if (!resources?.length && !drm?.length) return;
    window.postMessage({ source: "learnnote-page-hook", resources, drm }, "*");
  }

  function emit(resources) {
    const deduped = [];
    const seen = new Set();
    for (const item of resources || []) {
      const url = normalizeUrl(item.url);
      if (!url || seen.has(url)) continue;
      const kind = item.kind || mediaKind(url, item.mime || "");
      if (kind === "unknown") continue;
      seen.add(url);
      deduped.push({
        url,
        source: item.source || "pageHook",
        kind,
        mime: item.mime || "",
        label: item.label || "page hook",
        score: item.score || (kind === "hls" || kind === "dash" ? 96 : kind === "video" ? 88 : 62),
        playback_match: item.playback_match || "",
        is_main_video: Boolean(item.is_main_video),
        blob_url: item.blob_url ? normalizeUrl(item.blob_url) : "",
        request_type: item.request_type || "",
        method: item.method || "",
        status_code: item.status_code ?? null,
        content_length: item.content_length ?? null,
        initiator: item.initiator || "",
        headers: item.headers || {},
        request_headers: item.request_headers || {},
        time_stamp: Date.now()
      });
    }
    if (!deduped.length) return;
    for (const item of deduped) {
      const existing = bufferedResources.find(resource => resource.url === item.url);
      if (existing) {
        Object.assign(existing, item, {
          score: Math.max(existing.score || 0, item.score || 0),
          playback_match: existing.playback_match || item.playback_match || "",
          is_main_video: Boolean(existing.is_main_video || item.is_main_video),
          blob_url: item.blob_url || existing.blob_url || "",
          request_type: item.request_type || existing.request_type || "",
          method: item.method || existing.method || "",
          status_code: item.status_code ?? existing.status_code ?? null,
          content_length: item.content_length ?? existing.content_length ?? null,
          initiator: item.initiator || existing.initiator || "",
          headers: { ...(existing.headers || {}), ...(item.headers || {}) },
          request_headers: { ...(existing.request_headers || {}), ...(item.request_headers || {}) }
        });
      } else {
        bufferedResources.unshift(item);
      }
    }
    bufferedResources.splice(100);
    post(deduped);
  }

  function rememberDrmSignal(signal = {}) {
    const normalized = {
      source: signal.source || "pageHookEme",
      key_system: String(signal.key_system || ""),
      init_data_type: String(signal.init_data_type || ""),
      label: signal.label || "encrypted media",
      page_url: location.href,
      time_stamp: Date.now()
    };
    const signature = [normalized.source, normalized.key_system, normalized.init_data_type, normalized.label].join("|");
    const existing = drmSignals.find(item => [item.source, item.key_system, item.init_data_type, item.label].join("|") === signature);
    if (existing) {
      existing.time_stamp = normalized.time_stamp;
    } else {
      drmSignals.unshift(normalized);
    }
    drmSignals.splice(20);
    post([], [normalized]);
  }

  function mimeForKind(kind) {
    if (kind === "hls") return "application/vnd.apple.mpegurl";
    if (kind === "dash") return "application/dash+xml";
    if (kind === "subtitle") return "text/vtt";
    if (kind === "video") return "video/mp4";
    return "";
  }

  function cleanHeaderValue(value) {
    return String(value || "").replace(/[\r\n]+/g, " ").trim();
  }

  function safeResponseHeaders(getHeader) {
    const headers = {};
    for (const name of RESPONSE_HEADER_ALLOWLIST) {
      let value = "";
      try {
        value = cleanHeaderValue(getHeader(name));
      } catch {
        value = "";
      }
      if (value) headers[name] = value;
    }
    return headers;
  }

  function numericHeader(headers, name) {
    const value = Number(headers?.[name] || 0);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  function normalizeRequestHeaderMap(source) {
    const headers = {};
    const add = (name, value) => {
      const lower = String(name || "").toLowerCase();
      if (!REQUEST_HEADER_ALLOWLIST.has(lower)) return;
      const cleaned = cleanHeaderValue(value);
      if (cleaned) headers[REQUEST_HEADER_CANONICAL[lower] || name] = cleaned;
    };
    try {
      if (source?.forEach) {
        source.forEach((value, name) => add(name, value));
      } else if (Array.isArray(source)) {
        for (const pair of source) {
          if (Array.isArray(pair)) add(pair[0], pair[1]);
          else add(pair?.name, pair?.value);
        }
      } else if (source && typeof source === "object") {
        for (const [name, value] of Object.entries(source)) add(name, value);
      }
    } catch {
      // Some Headers-like objects can throw while enumerating.
    }
    return headers;
  }

  function fetchRequestHeaders(input, init = {}) {
    return {
      ...normalizeRequestHeaderMap(input?.headers),
      ...normalizeRequestHeaderMap(init?.headers)
    };
  }

  function fetchResponseMeta(response, url = "", requestHeaders = {}) {
    const headers = safeResponseHeaders(name => response.headers?.get?.(name) || "");
    return {
      request_type: "fetch",
      status_code: response.status ?? null,
      content_length: numericHeader(headers, "content-length"),
      initiator: response.url || url || "",
      headers,
      request_headers: requestHeaders
    };
  }

  function rememberResponseMeta(response, meta) {
    if (!response || typeof response !== "object" || !meta) return;
    try {
      responseMetaByObject.set(response, meta);
    } catch {
      // Synthetic response wrappers may not be WeakMap-compatible.
    }
  }

  function responseMeta(response, url = "") {
    try {
      return responseMetaByObject.get(response) || fetchResponseMeta(response, url);
    } catch {
      return fetchResponseMeta(response, url);
    }
  }

  function xhrResponseMeta(xhr, url = "") {
    const headers = safeResponseHeaders(name => xhr.getResponseHeader?.(name) || "");
    return {
      request_type: "xmlhttprequest",
      method: xhr.__learnNoteMethod || "",
      status_code: xhr.status ?? null,
      content_length: numericHeader(headers, "content-length"),
      initiator: xhr.responseURL || url || "",
      headers,
      request_headers: xhr.__learnNoteRequestHeaders || {}
    };
  }

  function applyResponseMeta(item, meta = {}) {
    if (!item || !meta) return item;
    return {
      ...item,
      request_type: item.request_type || meta.request_type || "",
      method: item.method || meta.method || "",
      status_code: item.status_code ?? meta.status_code ?? null,
      content_length: item.content_length ?? meta.content_length ?? null,
      initiator: item.initiator || meta.initiator || "",
      headers: { ...(item.headers || {}), ...(meta.headers || {}) },
      request_headers: { ...(item.request_headers || {}), ...(meta.request_headers || {}) }
    };
  }

  function looksLikeJsonUrlCandidate(value) {
    const text = String(value || "").trim();
    if (text.length < 4 || /\s/.test(text)) return false;
    if (/^(https?:)?\/\//i.test(text)) return true;
    if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return true;
    if (text.startsWith("/")) return true;
    return text.includes("/") && /[?=&]|api|play|media|video|stream|m3u8|mpd|hls|dash/i.test(text);
  }

  function looksLikeNestedMediaText(value) {
    const text = String(value || "").trim();
    if (text.length < 8) return false;
    if ("{[".includes(text[0])) {
      return JSON_MEDIA_KEY_RE.test(text) && (MEDIA_HINT_RE.test(text) || mediaUrlHint(text));
    }
    return JSON_MEDIA_KEY_RE.test(text) && MEDIA_HINT_RE.test(text);
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

  function decodedMediaValues(value) {
    const raw = String(value || "").trim();
    if (!raw) return [];
    const values = [decodeJsStringEscapes(raw)];
    appendRepeatedUrlDecodes(values, values[0]);

    const compact = raw.replace(/\s+/g, "");
    if (B64ISH_RE.test(compact)) {
      const padded = compact + "=".repeat((4 - (compact.length % 4)) % 4);
      try {
        const decoded = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
        const text = decodeURIComponent(escape(decoded)).trim();
        if (
          text &&
          !values.includes(text) &&
          !/[\u0000-\u0008\u000e-\u001f]/.test(text) &&
          (looksLikeJsonUrlCandidate(text) || MEDIA_HINT_RE.test(text) || looksLikeNestedMediaText(text))
        ) {
          values.push(text);
        }
      } catch {
        // Ignore non-text or non-base64 fields.
      }
    }

    return values.filter((item, index) => item && values.indexOf(item) === index);
  }

  function jsonContextMime(node) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return "";
    const parts = [];
    for (const [key, value] of Object.entries(node)) {
      if (JSON_MIME_KEY_RE.test(key) && typeof value === "string") parts.push(value);
    }
    return parts.join(" ");
  }

  function kindFromJsonContext(keys, url, parent) {
    const urlKind = mediaKind(url, "");
    if (urlKind !== "unknown") return { kind: urlKind, mime: mimeForKind(urlKind) };
    const context = [...keys, jsonContextMime(parent)].join(" ").toLowerCase();
    if (context.includes("mpegurl") || context.includes("x-mpegurl") || context.includes("m3u8") || context.includes("hls")) {
      return { kind: "hls", mime: "application/vnd.apple.mpegurl" };
    }
    if (context.includes("dash+xml") || context.includes("mpd") || context.includes("dash")) {
      return { kind: "dash", mime: "application/dash+xml" };
    }
    if (context.includes("text/vtt") || context.includes("subrip") || context.includes("subtitle") || context.includes("caption")) {
      return { kind: "subtitle", mime: "text/vtt" };
    }
    if (context.includes("video/") || context.includes("mp4") || context.includes("video")) {
      return { kind: "video", mime: "video/mp4" };
    }
    return { kind: "unknown", mime: "" };
  }

  function safeObjectEntries(node, limit = 160) {
    const entries = [];
    let keys = [];
    try {
      keys = Object.keys(node || {}).slice(0, limit);
    } catch {
      return entries;
    }
    for (const key of keys) {
      try {
        entries.push([key, node[key]]);
      } catch {
        // Some player objects expose throwing getters.
      }
    }
    return entries;
  }

  function collectJsonMediaUrls(node, source, label, keys = [], parent = null, output = [], seen = new Set(), visited = new WeakSet(), meta = {}) {
    if (!node || output.length >= 40) return output;
    if (Array.isArray(node)) {
      for (let index = 0; index < Math.min(node.length, 120); index += 1) {
        let child = null;
        try {
          child = node[index];
        } catch {
          child = null;
        }
        collectJsonMediaUrls(child, source, label, [...keys, String(index)], node, output, seen, visited, meta);
        if (output.length >= 40) break;
      }
      return output;
    }
    if (typeof node !== "object") return output;
    if (visited.has(node)) return output;
    visited.add(node);
    for (const [key, value] of safeObjectEntries(node)) {
      const nextKeys = [...keys, key];
      if (typeof value === "string" && JSON_MEDIA_KEY_RE.test(key)) {
        for (const candidateValue of decodedMediaValues(value)) {
          if (!looksLikeJsonUrlCandidate(candidateValue)) continue;
          const url = normalizeUrl(candidateValue);
          if (url && !seen.has(url)) {
            const { kind, mime } = kindFromJsonContext(nextKeys, url, node);
            if (kind !== "unknown") {
              seen.add(url);
              output.push(applyResponseMeta({
                url,
                source,
                kind,
                mime,
                label: `${label} json ${nextKeys.slice(-3).join("/")}`,
                score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
              }, meta));
              break;
            }
          }
        }
      }
      if (typeof value === "string" && !JSON_MEDIA_KEY_RE.test(key)) {
        for (const candidateValue of decodedMediaValues(value)) {
          if (!looksLikeJsonUrlCandidate(candidateValue)) continue;
          const url = normalizeUrl(candidateValue);
          if (!url || seen.has(url)) continue;
          const { kind, mime } = kindFromJsonContext(nextKeys, url, node);
          if (kind === "unknown") continue;
          seen.add(url);
          output.push(applyResponseMeta({
            url,
            source,
            kind,
            mime,
            label: `${label} json ${nextKeys.slice(-3).join("/")}`,
            score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
          }, meta));
          break;
        }
      }
      if (typeof value === "string" && !JSON_MEDIA_KEY_RE.test(key) && keys.length < 12) {
        for (const candidateText of decodedMediaValues(value)) {
          const trimmed = String(candidateText || "").trim();
          if (!trimmed || trimmed.length > MAX_TEXT_BYTES) continue;
          if (!"{[".includes(trimmed[0]) && !MEDIA_HINT_RE.test(trimmed) && !JSON_MEDIA_KEY_RE.test(trimmed)) continue;
          const nested = collectMediaUrlsFromText(trimmed, source, `${label} nested ${nextKeys.slice(-3).join("/")}`, "", seen, meta);
          output.push(...nested.slice(0, Math.max(0, 40 - output.length)));
          if (output.length >= 40) break;
        }
      }
      if (value && typeof value === "object") {
        collectJsonMediaUrls(value, source, label, nextKeys, node, output, seen, visited, meta);
      }
      if (output.length >= 40) break;
    }
    return output;
  }

  function extractJsonMediaUrls(text, source, label, seen = new Set(), meta = {}) {
    const trimmed = String(text || "").trim();
    if (!trimmed || !"{[".includes(trimmed[0])) return [];
    try {
      return collectJsonMediaUrls(JSON.parse(trimmed), source, label, [], null, [], seen, new WeakSet(), meta);
    } catch {
      return [];
    }
  }

  function extractFieldMediaUrls(text, source, label, seen = new Set(), meta = {}) {
    const output = [];
    TEXT_MEDIA_FIELD_RE.lastIndex = 0;
    for (const match of String(text || "").matchAll(TEXT_MEDIA_FIELD_RE)) {
      const key = String(match[1] || "").replace(/^["']|["']$/g, "");
      if (!JSON_MEDIA_KEY_RE.test(key)) continue;
      for (const rawUrl of decodedMediaValues(match[2] || "")) {
        if (!looksLikeJsonUrlCandidate(rawUrl)) continue;
        const url = normalizeUrl(rawUrl);
        if (!url || seen.has(url)) continue;
        const { kind, mime } = kindFromJsonContext([key], url, {});
        if (kind === "unknown") continue;
        seen.add(url);
        output.push(applyResponseMeta({
          url,
          source,
          kind,
          mime,
          label: `${label} field ${key}`,
          score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
        }, meta));
        break;
      }
      if (output.length >= 40) break;
    }
    return output;
  }

  function extractEncodedMediaUrls(text, source, label, seen = new Set(), meta = {}) {
    const output = [];
    for (const match of String(text || "").matchAll(ENCODED_MEDIA_URL_RE)) {
      for (const rawUrl of decodedMediaValues(match[0] || "")) {
        const url = normalizeUrl(rawUrl);
        if (!url || seen.has(url)) continue;
        const kind = mediaKind(url, "");
        if (kind === "unknown") continue;
        seen.add(url);
        output.push(applyResponseMeta({
          url,
          source,
          kind,
          mime: mimeForKind(kind),
          label: `${label} encoded url`,
          score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
        }, meta));
        break;
      }
      if (output.length >= 40) break;
    }
    return output;
  }

  function isJsEscapedMediaFragmentMatch(text, index) {
    if (!Number.isFinite(index) || index <= 0) return false;
    const prefix = String(text || "").slice(Math.max(0, index - 6), index);
    return /\\(?:u[0-9a-fA-F]{0,4}|x[0-9a-fA-F]{0,2})?$/.test(prefix);
  }

  function blobMeta(url, mime, source, label) {
    const normalizedUrl = normalizeUrl(url);
    const kind = mediaKind(normalizedUrl, mime || "");
    if (!normalizedUrl || kind === "unknown") return null;
    return {
      url: normalizedUrl,
      source,
      kind,
      mime: mime || "",
      label,
      score: kind === "hls" || kind === "dash" ? 98 : kind === "video" ? 94 : 66
    };
  }

  function rememberBlobObject(blob, meta) {
    if (!blob || !meta?.url) return;
    try {
      blobSourceByObject.set(blob, meta);
      emit([meta]);
    } catch {
      // Some host pages wrap Blob objects with restricted proxies.
    }
  }

  function rememberBlobPartObject(part, meta) {
    if (!part || typeof part !== "object" || !meta?.url) return;
    try {
      blobPartSourceByObject.set(part, meta);
    } catch {
      // Primitive values and some host objects cannot be WeakMap keys.
    }
  }

  function rememberStreamObject(stream, meta) {
    if (!stream || typeof stream !== "object" || !meta?.url) return;
    try {
      streamSourceByObject.set(stream, meta);
      emit([meta]);
    } catch {
      // Some streams may be host objects from restricted realms.
    }
  }

  function streamMeta(stream) {
    if (!stream || typeof stream !== "object") return null;
    return streamSourceByObject.get(stream) || null;
  }

  function rememberStreamReader(reader, meta) {
    if (!reader || typeof reader !== "object" || !meta?.url) return;
    try {
      streamReaderSourceByObject.set(reader, meta);
    } catch {
      // Keep stream consumption unchanged for pages with unusual reader wrappers.
    }
  }

  function streamReaderMeta(reader) {
    if (!reader || typeof reader !== "object") return null;
    return streamReaderSourceByObject.get(reader) || null;
  }

  function wrapStreamReaderInstance(reader, meta) {
    if (!reader || typeof reader !== "object" || typeof reader.read !== "function") return;
    if (reader.__learnNoteReadInstancePatched) return;
    const originalRead = reader.read;
    const wrappedRead = async function (...args) {
      const result = await originalRead.apply(this, args);
      try {
        const sourceMeta = streamReaderMeta(this) || meta;
        if (result?.value) rememberBlobPartObject(result.value, sourceMeta);
      } catch {
        // Keep custom stream reader consumption unchanged.
      }
      return result;
    };
    try {
      Object.defineProperty(reader, "read", {
        configurable: true,
        writable: true,
        value: wrappedRead
      });
      Object.defineProperty(reader, "__learnNoteReadInstancePatched", { value: true });
    } catch {
      try {
        reader.read = wrappedRead;
        reader.__learnNoteReadInstancePatched = true;
      } catch {
        // Some custom readers are non-extensible; prototype patching may still cover them.
      }
    }
  }

  function blobPartMeta(part) {
    if (!part || typeof part !== "object") return null;
    const direct = blobPartSourceByObject.get(part) || blobSourceByObject.get(part);
    if (direct) return direct;
    if (ArrayBuffer.isView?.(part)) {
      return blobPartSourceByObject.get(part.buffer) || null;
    }
    return null;
  }

  function rememberBlobUrl(blobUrl, blob) {
    const meta = blobSourceByObject.get(blob);
    if (!meta) return;
    blobSourceByUrl.set(blobUrl, meta);
    blobUrlOrder.push(blobUrl);
    while (blobUrlOrder.length > MAX_BLOB_URLS) {
      const oldest = blobUrlOrder.shift();
      if (oldest) blobSourceByUrl.delete(oldest);
    }
    emit([{
      ...meta,
      source: "pageHookBlobSource",
      label: "blob source",
      blob_url: blobUrl,
      playback_match: "blob-source",
      score: Math.max(meta.score || 0, 98)
    }]);
  }

  function isMediaSourceObject(value) {
    if (!value || typeof value !== "object") return false;
    try {
      if (typeof window.MediaSource !== "undefined" && value instanceof window.MediaSource) return true;
    } catch {
      // Cross-realm MediaSource checks can throw on some pages.
    }
    return typeof value.addSourceBuffer === "function" && typeof value.readyState === "string";
  }

  function rememberMediaSourceMeta(mediaSource, meta) {
    if (!isMediaSourceObject(mediaSource) || !meta?.url) return;
    try {
      const current = mediaSourceMetaByObject.get(mediaSource);
      if (!current || (meta.score || 0) >= (current.score || 0)) {
        mediaSourceMetaByObject.set(mediaSource, meta);
      }
      const blobUrl = mediaSourceUrlByObject.get(mediaSource);
      if (!blobUrl) return;
      emit([{
        ...meta,
        source: "pageHookMediaSource",
        label: "media source",
        blob_url: blobUrl,
        playback_match: "blob-source",
        score: Math.max(meta.score || 0, 98)
      }]);
    } catch {
      // MediaSource objects may come from restricted or cross-realm wrappers.
    }
  }

  function collectMediaUrlsFromText(text, source, label, mime = "", seen = new Set(), meta = {}) {
    if (!text) return [];
    const resources = extractJsonMediaUrls(text, source, label, seen, meta);
    resources.push(...extractFieldMediaUrls(text, source, label, seen, meta));
    resources.push(...extractEncodedMediaUrls(text, source, label, seen, meta));
    const body = String(text || "");
    const decodedBody = decodeJsStringEscapes(body);
    for (const searchable of [body, decodedBody].filter((item, index, values) => item && values.indexOf(item) === index)) {
      if (!MEDIA_HINT_RE.test(searchable)) continue;
      for (const match of searchable.matchAll(MEDIA_URL_RE)) {
        if (isJsEscapedMediaFragmentMatch(searchable, match.index ?? -1)) continue;
        const url = normalizeUrl(match[0]);
        if (!url || seen.has(url)) continue;
        resources.push(applyResponseMeta({ url, source, label, mime }, meta));
        seen.add(url);
        if (resources.length >= 40) break;
      }
      if (resources.length >= 40) break;
    }
    return resources;
  }

  function collectResponseTextResources(url, text, source, label, mime = "", meta = {}) {
    const seen = new Set();
    const resources = collectMediaUrlsFromText(text, source, label, mime, seen, meta);
    const kind = manifestKindFromText(text, mime);
    const normalizedUrl = normalizeUrl(url);
    if (kind !== "unknown" && normalizedUrl && !seen.has(normalizedUrl)) {
      resources.unshift(applyResponseMeta({
        url: normalizedUrl,
        source,
        kind,
        mime: mime || mimeForKind(kind),
        label: `${label} manifest`,
        score: 99
      }, meta));
    }
    return resources;
  }

  function extractUrlsFromText(text, source, label, mime = "", responseUrl = "", meta = {}) {
    emit(collectResponseTextResources(responseUrl, text, source, label, mime, meta));
  }

  function collectGlobalConfigResources() {
    const resources = [];
    const seen = new Set();
    const names = [];
    const addName = name => {
      if (name && !names.includes(name)) names.push(name);
    };
    for (const name of GLOBAL_MEDIA_KEYS) addName(name);
    try {
      for (const name of Object.keys(window).slice(0, 1200)) {
        if (GLOBAL_MEDIA_NAME_RE.test(name)) addName(name);
        if (names.length >= 90) break;
      }
    } catch {
      // Some pages restrict global enumeration.
    }

    for (const name of names.slice(0, 90)) {
      let value;
      try {
        value = window[name];
      } catch {
        continue;
      }
      if (typeof value === "string") {
        resources.push(...collectMediaUrlsFromText(value.slice(0, MAX_TEXT_BYTES), "pageHookGlobal", `global ${name}`, "", seen));
      } else if (value && typeof value === "object") {
        resources.push(...collectJsonMediaUrls(value, "pageHookGlobal", `global ${name}`, [name], null, [], seen));
      }
      if (resources.length >= 60) break;
    }
    return resources.slice(0, 60);
  }

  function sourceCandidates(value, output = [], visited = new WeakSet(), depth = 0) {
    if (!value) return output;
    if (typeof value === "string") {
      output.push(value);
      return output;
    }
    if (Array.isArray(value)) {
      for (const item of value) sourceCandidates(item, output, visited, depth + 1);
      return output;
    }
    if (typeof value === "object") {
      if (visited.has(value) || depth > 4) return output;
      visited.add(value);
      for (const key of ["src", "url", "file", "fileId", "objectid", "objectId", "dtoken", "downloadUrl", "httpmd", "source", "manifestUri", "playUrl", "videoUrl", "flvUrl", "hlsUrl"]) {
        try {
          if (typeof value[key] === "string") output.push(value[key]);
        } catch {
          // Some player source objects expose throwing getters.
        }
      }
      for (const [key, child] of safeObjectEntries(value, 80)) {
        if (!/^(video|media|source|sources|playlist|file|fileid|objectid|dtoken|download|httpmd|url|config|play|quality|qualities|streams?|hls|dash)$/i.test(key)) continue;
        sourceCandidates(child, output, visited, depth + 1);
      }
    }
    return output;
  }

  function emitPlayerSources(value, fallbackKind, label) {
    const resources = [];
    const seen = new Set();
    for (const candidate of sourceCandidates(value)) {
      const url = normalizeUrl(candidate);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const detectedKind = mediaKind(url, "");
      const kind = detectedKind === "unknown" ? fallbackKind : detectedKind;
      if (!kind || kind === "unknown") continue;
      resources.push({
        url,
        source: "pageHookPlayer",
        kind,
        mime: mimeForKind(kind),
        label,
        score: kind === "hls" || kind === "dash" ? 99 : 92
      });
    }
    emit(resources);
  }

  function patchMethod(target, name, wrap) {
    if (!target || typeof target[name] !== "function") return false;
    const marker = `__learnNote${name[0].toUpperCase()}${name.slice(1)}Patched`;
    try {
      if (target[marker]) return true;
      const original = target[name];
      target[name] = wrap(original);
      Object.defineProperty(target, marker, { value: true });
      return true;
    } catch {
      return false;
    }
  }

  function patchHlsJs() {
    try {
      const Hls = window.Hls;
      if (!Hls?.prototype) return;
      patchMethod(Hls.prototype, "loadSource", original => function (source, ...rest) {
        emitPlayerSources(source, "hls", "hls.js loadSource");
        return original.call(this, source, ...rest);
      });
    } catch {
      // hls.js may not be present or may lock its prototype.
    }
  }

  function patchDashPlayer(player) {
    if (!player || typeof player !== "object") return player;
    patchMethod(player, "attachSource", original => function (source, ...rest) {
      emitPlayerSources(source, "dash", "dash.js attachSource");
      return original.call(this, source, ...rest);
    });
    patchMethod(player, "initialize", original => function (view, source, ...rest) {
      if (source) emitPlayerSources(source, "dash", "dash.js initialize");
      return original.call(this, view, source, ...rest);
    });
    return player;
  }

  function patchDashJs() {
    try {
      const dash = window.dashjs;
      if (!dash || typeof dash.MediaPlayer !== "function" || dash.MediaPlayer.__learnNoteMediaPlayerPatched) return;
      const originalMediaPlayer = dash.MediaPlayer;
      function LearnNoteMediaPlayer(...args) {
        const factory = originalMediaPlayer.apply(this, args);
        if (factory && typeof factory.create === "function" && !factory.__learnNoteCreatePatched) {
          const originalCreate = factory.create;
          factory.create = function (...createArgs) {
            return patchDashPlayer(originalCreate.apply(this, createArgs));
          };
          try {
            Object.defineProperty(factory, "__learnNoteCreatePatched", { value: true });
          } catch {
            // Factory patch still works even if the marker cannot be written.
          }
        }
        return factory;
      }
      try {
        Object.setPrototypeOf(LearnNoteMediaPlayer, originalMediaPlayer);
        LearnNoteMediaPlayer.prototype = originalMediaPlayer.prototype;
      } catch {
        // A plain wrapper is enough for typical dash.js factory usage.
      }
      Object.defineProperty(LearnNoteMediaPlayer, "__learnNoteMediaPlayerPatched", { value: true });
      dash.MediaPlayer = LearnNoteMediaPlayer;
    } catch {
      // dash.js may be loaded later; the polling installer retries.
    }
  }

  function patchShakaPlayer() {
    try {
      const Player = window.shaka?.Player;
      if (!Player?.prototype) return;
      patchMethod(Player.prototype, "load", original => function (assetUri, ...rest) {
        emitPlayerSources(assetUri, "", "shaka Player.load");
        return original.call(this, assetUri, ...rest);
      });
    } catch {
      // shaka may not be present or may lock its prototype.
    }
  }

  function patchVideoJs() {
    try {
      const playerProto = window.videojs?.Player?.prototype || window.videoJs?.Player?.prototype;
      if (!playerProto) return;
      patchMethod(playerProto, "src", original => function (source, ...rest) {
        if (source) emitPlayerSources(source, "", "video.js src");
        return original.call(this, source, ...rest);
      });
    } catch {
      // video.js is optional and best-effort.
    }
  }

  function patchGenericPlayerInstance(player, label) {
    if (!player || typeof player !== "object") return player;
    for (const method of ["src", "url", "load", "setup", "switchVideo", "switchUrl", "switchURL", "changeQuality", "setSrc", "setUrl", "setVideoUrl"]) {
      patchMethod(player, method, original => function (...args) {
        for (const arg of args) emitPlayerSources(arg, "", `${label} ${method}`);
        return original.apply(this, args);
      });
    }
    return player;
  }

  function patchPlayerConstructorOn(target, name, label) {
    try {
      const Original = target?.[name];
      if (typeof Original !== "function" || Original.__learnNoteConstructorPatched) return;
      const Wrapped = new Proxy(Original, {
        construct(constructor, args, newTarget) {
          for (const arg of args) emitPlayerSources(arg, "", label);
          return patchGenericPlayerInstance(Reflect.construct(constructor, args, newTarget), label);
        },
        apply(constructor, thisArg, args) {
          for (const arg of args) emitPlayerSources(arg, "", label);
          return patchGenericPlayerInstance(Reflect.apply(constructor, thisArg, args), label);
        }
      });
      try {
        Object.setPrototypeOf(Wrapped, Original);
        Wrapped.prototype = Original.prototype;
      } catch {
        // Proxy construct/apply traps are enough for typical global players.
      }
      Object.defineProperty(Wrapped, "__learnNoteConstructorPatched", { value: true });
      target[name] = Wrapped;
    } catch {
      // Some player globals are read-only or cross-realm wrappers.
    }
  }

  function patchCommonChinesePlayers() {
    patchPlayerConstructorOn(window, "DPlayer", "DPlayer constructor");
    patchPlayerConstructorOn(window, "Artplayer", "ArtPlayer constructor");
    patchPlayerConstructorOn(window, "ArtPlayer", "ArtPlayer constructor");
    patchPlayerConstructorOn(window, "XGPlayer", "xgplayer constructor");
    patchPlayerConstructorOn(window, "Aliplayer", "Aliplayer constructor");
    patchPlayerConstructorOn(window, "TcPlayer", "TcPlayer constructor");
    patchPlayerConstructorOn(window.xgplayer, "Player", "xgplayer Player constructor");
  }

  function patchJwPlayer() {
    try {
      const original = window.jwplayer;
      if (typeof original !== "function" || original.__learnNoteJwplayerPatched) return;
      function LearnNoteJwplayer(...args) {
        const player = original.apply(this, args);
        return patchGenericPlayerInstance(player, "jwplayer");
      }
      try {
        Object.setPrototypeOf(LearnNoteJwplayer, original);
        LearnNoteJwplayer.prototype = original.prototype;
      } catch {
        // A plain function wrapper works for jwplayer(id).setup(...).
      }
      Object.defineProperty(LearnNoteJwplayer, "__learnNoteJwplayerPatched", { value: true });
      window.jwplayer = LearnNoteJwplayer;
    } catch {
      // jwplayer is optional and may lock its global.
    }
  }

  function mediaElementTag(element) {
    try {
      return String(element?.tagName || "").toLowerCase();
    } catch {
      return "";
    }
  }

  function isMediaElement(element) {
    try {
      if (window.HTMLMediaElement && element instanceof window.HTMLMediaElement) return true;
    } catch {
      // Cross-realm or locked constructors can make instanceof throw.
    }
    const tag = mediaElementTag(element);
    return tag === "video" || tag === "audio";
  }

  function isSourceElement(element) {
    return mediaElementTag(element) === "source";
  }

  function mediaElementFallbackKind(element) {
    const tag = mediaElementTag(element);
    let parentTag = "";
    try {
      parentTag = mediaElementTag(element?.parentElement);
    } catch {
      parentTag = "";
    }
    if (tag === "video" || parentTag === "video") return "video";
    return "";
  }

  function emitMediaElementSource(element, value, label) {
    if (!value) return;
    emitPlayerSources(value, mediaElementFallbackKind(element), label);
  }

  function collectMediaElementCurrentSources(element) {
    const sources = [];
    try {
      if (element.currentSrc) sources.push(element.currentSrc);
    } catch {
      // Some custom elements expose throwing media-like getters.
    }
    try {
      if (element.src) sources.push(element.src);
    } catch {
      // Keep playback untouched if a getter is not readable.
    }
    try {
      const children = element.querySelectorAll?.("source[src]") || [];
      for (const source of children) {
        const src = source.getAttribute?.("src") || source.src;
        if (src) sources.push(src);
      }
    } catch {
      // Child source scanning is best-effort.
    }
    return sources;
  }

  function patchSrcDescriptor(proto, label) {
    if (!proto) return false;
    try {
      if (Object.prototype.hasOwnProperty.call(proto, "__learnNoteSrcDescriptorPatched")) return true;
      const descriptor = Object.getOwnPropertyDescriptor(proto, "src");
      if (!descriptor?.get || !descriptor?.set || descriptor.configurable === false) return false;
      Object.defineProperty(proto, "src", {
        configurable: descriptor.configurable,
        enumerable: descriptor.enumerable,
        get() {
          return descriptor.get.call(this);
        },
        set(value) {
          emitMediaElementSource(this, value, label);
          return descriptor.set.call(this, value);
        }
      });
      Object.defineProperty(proto, "__learnNoteSrcDescriptorPatched", { value: true });
      return true;
    } catch {
      return false;
    }
  }

  function patchHtmlMediaElement() {
    try {
      patchSrcDescriptor(window.HTMLMediaElement?.prototype, "HTMLMediaElement src");
      patchSrcDescriptor(window.HTMLVideoElement?.prototype, "HTMLVideoElement src");
      patchSrcDescriptor(window.HTMLAudioElement?.prototype, "HTMLAudioElement src");
      patchSrcDescriptor(window.HTMLSourceElement?.prototype, "HTMLSourceElement src");
    } catch {
      // Native media prototypes vary by browser and page isolation mode.
    }

    try {
      patchMethod(window.Element?.prototype, "setAttribute", original => function (name, value, ...rest) {
        const attr = String(name || "").toLowerCase();
        if (attr === "src" && (isMediaElement(this) || isSourceElement(this))) {
          emitMediaElementSource(this, value, `${mediaElementTag(this) || "media"} setAttribute src`);
        }
        return original.call(this, name, value, ...rest);
      });
    } catch {
      // If Element.prototype is locked, the src descriptor/load hooks can still catch most cases.
    }

    try {
      patchMethod(window.HTMLMediaElement?.prototype, "load", original => function (...args) {
        const sources = collectMediaElementCurrentSources(this);
        if (sources.length) emitMediaElementSource(this, sources, "HTMLMediaElement load");
        return original.apply(this, args);
      });
    } catch {
      // Loading should continue even if inspection fails.
    }
  }

  function patchKnownPlayerLibraries() {
    patchHlsJs();
    patchDashJs();
    patchShakaPlayer();
    patchVideoJs();
    patchCommonChinesePlayers();
    patchJwPlayer();
  }

  function watchLatePlayerGlobal(name) {
    try {
      if (!name || Object.prototype.hasOwnProperty.call(window, name)) return;
      let current;
      Object.defineProperty(window, name, {
        configurable: true,
        enumerable: true,
        get() {
          return current;
        },
        set(value) {
          current = value;
          if (!value || patchingLatePlayerGlobal) return;
          patchingLatePlayerGlobal = true;
          try {
            patchKnownPlayerLibraries();
          } finally {
            patchingLatePlayerGlobal = false;
          }
        }
      });
    } catch {
      // Some pages disallow accessors on window globals; timed retries still run.
    }
  }

  function installLatePlayerGlobalWatchers() {
    for (const name of [
      "Hls",
      "dashjs",
      "shaka",
      "videojs",
      "videoJs",
      "DPlayer",
      "Artplayer",
      "ArtPlayer",
      "XGPlayer",
      "Aliplayer",
      "TcPlayer",
      "xgplayer",
      "jwplayer"
    ]) {
      watchLatePlayerGlobal(name);
    }
  }

  function scanGlobalConfig() {
    try {
      emit(collectGlobalConfigResources());
    } catch {
      // Global player objects are best-effort evidence only.
    }
  }

  function shouldInspectResponse(response, fallbackUrl = "") {
    const type = response.headers?.get?.("content-type") || "";
    const length = Number(response.headers?.get?.("content-length") || 0);
    return shouldInspectTextPayload(response.url || fallbackUrl || "", type, length);
  }

  function shouldInspectTextPayload(url, contentType = "", contentLength = 0) {
    if (contentLength && contentLength > MAX_TEXT_BYTES) return false;
    if (TEXT_TYPE_RE.test(contentType)) return true;
    return /octet-stream|binary|application\/x-mpegurl/i.test(String(contentType || "")) && mediaUrlHint(url);
  }

  function requestUrl(input) {
    try {
      if (typeof input === "string") return input;
      if (input && typeof input.url === "string") return input.url;
    } catch {
      return "";
    }
    return "";
  }

  function responseSourceUrl(response, fallbackUrl = "") {
    const meta = responseMeta(response, fallbackUrl);
    return response?.url || meta?.initiator || fallbackUrl || "";
  }

  function responseBlobSourceMeta(response, fallbackUrl, mime, source, label) {
    const meta = responseMeta(response, fallbackUrl);
    const sourceUrl = responseSourceUrl(response, fallbackUrl);
    return applyResponseMeta(blobMeta(sourceUrl, mime, source, label), meta);
  }

  function inspectCacheResponse(response, request, label) {
    if (!response || typeof response !== "object") return;
    const url = response.url || requestUrl(request);
    const mime = response.headers?.get?.("content-type") || "";
    const meta = fetchResponseMeta(response, url, normalizeRequestHeaderMap(request?.headers));
    rememberResponseMeta(response, meta);
    emit([applyResponseMeta({ url: responseSourceUrl(response, url), source: "pageHookCache", label, mime }, meta)]);
    try {
      rememberStreamObject(response.body, blobMeta(responseSourceUrl(response, url), mime, "pageHookCache", "cache response stream"));
    } catch {
      // Cache responses may expose locked or synthetic bodies.
    }
    if (shouldInspectResponse(response, url)) {
      try {
        response.clone().text()
          .then(text => extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookCache", `${label} body`, mime, responseSourceUrl(response, url), meta))
          .catch(() => {});
      } catch {
        // Cache response clones are optional and can fail for opaque responses.
      }
    }
  }

  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
      const response = await originalFetch.apply(this, args);
      const url = response.url || requestUrl(args[0]);
      const mime = response.headers?.get?.("content-type") || "";
      const meta = fetchResponseMeta(response, url, fetchRequestHeaders(args[0], args[1] || {}));
      rememberResponseMeta(response, meta);
      emit([applyResponseMeta({ url, source: "pageHookRequest", label: "fetch", mime }, meta)]);
      try {
        rememberStreamObject(response.body, blobMeta(url, mime, "pageHookStream", "fetch stream source"));
      } catch {
        // Accessing body can throw for some synthetic responses.
      }
      if (shouldInspectResponse(response)) {
        try {
          response.clone().text()
            .then(text => extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch body", mime, url, meta))
            .catch(() => {});
        } catch {
          // Some wrapped responses cannot be cloned; Response.json() remains patched below.
        }
      }
      return response;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.blob) {
    const originalResponseBlob = Response.prototype.blob;
    Response.prototype.blob = async function (...args) {
      const blob = await originalResponseBlob.apply(this, args);
      try {
        const mime = blob?.type || this.headers?.get?.("content-type") || "";
        const meta = responseBlobSourceMeta(this, this.url || "", mime, "pageHookBlob", "fetch blob source");
        rememberBlobObject(blob, meta);
      } catch {
        // Keep the host page's response consumption behavior unchanged.
      }
      return blob;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.json) {
    const originalResponseJson = Response.prototype.json;
    Response.prototype.json = async function (...args) {
      const data = await originalResponseJson.apply(this, args);
      try {
        emit(collectJsonMediaUrls(data, "pageHookBody", "fetch json", [], null, [], new Set(), new WeakSet(), responseMeta(this, this.url || "")));
      } catch {
        // Keep host page JSON consumption unchanged.
      }
      return data;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.text) {
    const originalResponseText = Response.prototype.text;
    Response.prototype.text = async function (...args) {
      const text = await originalResponseText.apply(this, args);
      try {
        const mime = this.headers?.get?.("content-type") || "";
        const url = this.url || "";
        if (shouldInspectTextPayload(url, mime, String(text || "").length)) {
          extractUrlsFromText(String(text || "").slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch text", mime, url, responseMeta(this, url));
        }
      } catch {
        // Keep host page text consumption unchanged.
      }
      return text;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.arrayBuffer) {
    const originalResponseArrayBuffer = Response.prototype.arrayBuffer;
    Response.prototype.arrayBuffer = async function (...args) {
      const buffer = await originalResponseArrayBuffer.apply(this, args);
      try {
        const mime = this.headers?.get?.("content-type") || "";
        const meta = responseBlobSourceMeta(this, this.url || "", mime, "pageHookBlob", "fetch arrayBuffer source");
        rememberBlobPartObject(buffer, meta);
      } catch {
        // Keep the host page's response consumption behavior unchanged.
      }
      return buffer;
    };
  }

  if (typeof window.ReadableStream !== "undefined" && window.ReadableStream.prototype?.getReader) {
    const originalGetReader = window.ReadableStream.prototype.getReader;
    window.ReadableStream.prototype.getReader = function (...args) {
      const reader = originalGetReader.apply(this, args);
      try {
        const meta = streamMeta(this);
        rememberStreamReader(reader, meta);
        wrapStreamReaderInstance(reader, meta);
      } catch {
        // Keep stream reader creation transparent.
      }
      return reader;
    };
  }

  function patchStreamReaderRead(ReaderCtor) {
    if (!ReaderCtor?.prototype?.read || ReaderCtor.prototype.__learnNoteReadPatched) return;
    const originalRead = ReaderCtor.prototype.read;
    ReaderCtor.prototype.read = async function (...args) {
      const result = await originalRead.apply(this, args);
      try {
        const meta = streamReaderMeta(this);
        if (result?.value) rememberBlobPartObject(result.value, meta);
      } catch {
        // Keep stream consumption behavior unchanged.
      }
      return result;
    };
    try {
      Object.defineProperty(ReaderCtor.prototype, "__learnNoteReadPatched", { value: true });
    } catch {
      // Non-extensible prototypes still use the patched read above.
    }
  }

  patchStreamReaderRead(window.ReadableStreamDefaultReader);
  patchStreamReaderRead(window.ReadableStreamBYOBReader);

  function patchCacheInstance(cache) {
    if (!cache || typeof cache !== "object" || cache.__learnNoteCachePatched) return cache;
    if (typeof cache.put === "function") {
      const originalPut = cache.put;
      cache.put = function (request, response, ...rest) {
        try {
          inspectCacheResponse(response, request, "cache put");
        } catch {
          // Cache writes must stay transparent.
        }
        return originalPut.call(this, request, response, ...rest);
      };
    }
    if (typeof cache.match === "function") {
      const originalMatch = cache.match;
      cache.match = async function (request, ...rest) {
        const response = await originalMatch.call(this, request, ...rest);
        try {
          inspectCacheResponse(response, request, "cache match");
        } catch {
          // Cache reads must stay transparent.
        }
        return response;
      };
    }
    if (typeof cache.matchAll === "function") {
      const originalMatchAll = cache.matchAll;
      cache.matchAll = async function (request, ...rest) {
        const responses = await originalMatchAll.call(this, request, ...rest);
        try {
          for (const response of responses || []) inspectCacheResponse(response, request, "cache matchAll");
        } catch {
          // Cache reads must stay transparent.
        }
        return responses;
      };
    }
    if (typeof cache.add === "function") {
      const originalAdd = cache.add;
      cache.add = function (request, ...rest) {
        const url = requestUrl(request);
        if (url) emit([{ url, source: "pageHookCache", label: "cache add" }]);
        return originalAdd.call(this, request, ...rest);
      };
    }
    if (typeof cache.addAll === "function") {
      const originalAddAll = cache.addAll;
      cache.addAll = function (requests, ...rest) {
        try {
          emit(Array.from(requests || []).map(request => ({ url: requestUrl(request), source: "pageHookCache", label: "cache addAll" })));
        } catch {
          // Keep cache population untouched for non-iterable inputs.
        }
        return originalAddAll.call(this, requests, ...rest);
      };
    }
    try {
      Object.defineProperty(cache, "__learnNoteCachePatched", { value: true });
    } catch {
      cache.__learnNoteCachePatched = true;
    }
    return cache;
  }

  if (typeof window.Cache !== "undefined" && window.Cache.prototype) {
    patchCacheInstance(window.Cache.prototype);
  }

  if (window.caches?.open && !window.caches.__learnNoteOpenPatched) {
    const originalCachesOpen = window.caches.open;
    window.caches.open = async function (...args) {
      const cache = await originalCachesOpen.apply(this, args);
      return patchCacheInstance(cache);
    };
    try {
      Object.defineProperty(window.caches, "__learnNoteOpenPatched", { value: true });
    } catch {
      window.caches.__learnNoteOpenPatched = true;
    }
  }

  if (window.caches?.match && !window.caches.__learnNoteMatchPatched) {
    const originalCachesMatch = window.caches.match;
    window.caches.match = async function (request, ...rest) {
      const response = await originalCachesMatch.call(this, request, ...rest);
      try {
        inspectCacheResponse(response, request, "cache storage match");
      } catch {
        // CacheStorage reads must stay transparent.
      }
      return response;
    };
    try {
      Object.defineProperty(window.caches, "__learnNoteMatchPatched", { value: true });
    } catch {
      window.caches.__learnNoteMatchPatched = true;
    }
  }

  if (typeof window.Blob === "function" && !window.Blob.__learnNoteOriginalBlob) {
    const OriginalBlob = window.Blob;
    function LearnNoteBlob(parts = [], options = {}) {
      const blob = new OriginalBlob(parts, options);
      try {
        const sourceMeta = Array.from(parts || []).map(blobPartMeta).find(Boolean);
        if (sourceMeta) {
          rememberBlobObject(blob, {
            ...sourceMeta,
            mime: blob.type || options?.type || sourceMeta.mime || "",
            source: sourceMeta.source || "pageHookBlob",
            label: sourceMeta.label || "constructed blob source"
          });
        }
      } catch {
        // Blob construction must remain transparent to the host page.
      }
      return blob;
    }
    try {
      Object.setPrototypeOf(LearnNoteBlob, OriginalBlob);
      LearnNoteBlob.prototype = OriginalBlob.prototype;
      Object.defineProperty(LearnNoteBlob, "__learnNoteOriginalBlob", { value: OriginalBlob });
      window.Blob = LearnNoteBlob;
    } catch {
      // Some pages lock constructors. Response.blob() and XHR blob tracking still work.
    }
  }

  if (window.URL?.createObjectURL) {
    const originalCreateObjectURL = URL.createObjectURL;
    URL.createObjectURL = function (...args) {
      const blobUrl = originalCreateObjectURL.apply(this, args);
      try {
        rememberBlobUrl(blobUrl, args[0]);
        if (isMediaSourceObject(args[0])) {
          mediaSourceUrlByObject.set(args[0], blobUrl);
          rememberMediaSourceMeta(args[0], mediaSourceMetaByObject.get(args[0]));
        }
      } catch {
        // Ignore non-Blob/MediaSource objects and cross-realm edge cases.
      }
      return blobUrl;
    };
  }

  if (window.URL?.revokeObjectURL) {
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.revokeObjectURL = function (...args) {
      blobSourceByUrl.delete(args[0]);
      return originalRevokeObjectURL.apply(this, args);
    };
  }

  if (typeof window.MediaSource !== "undefined" && window.MediaSource.prototype?.addSourceBuffer) {
    const originalAddSourceBuffer = window.MediaSource.prototype.addSourceBuffer;
    window.MediaSource.prototype.addSourceBuffer = function (...args) {
      const sourceBuffer = originalAddSourceBuffer.apply(this, args);
      try {
        sourceBufferMediaSource.set(sourceBuffer, this);
      } catch {
        // Some SourceBuffer implementations are not extensible WeakMap keys.
      }
      return sourceBuffer;
    };
  }

  if (typeof window.SourceBuffer !== "undefined" && window.SourceBuffer.prototype?.appendBuffer) {
    const originalAppendBuffer = window.SourceBuffer.prototype.appendBuffer;
    window.SourceBuffer.prototype.appendBuffer = function (...args) {
      try {
        const meta = blobPartMeta(args[0]);
        const mediaSource = sourceBufferMediaSource.get(this);
        rememberMediaSourceMeta(mediaSource, meta);
      } catch {
        // Keep MSE playback untouched if a page uses unusual buffer wrappers.
      }
      return originalAppendBuffer.apply(this, args);
    };
  }

  if (typeof window.XMLHttpRequest === "function") {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__learnNoteUrl = url;
      this.__learnNoteMethod = method;
      this.__learnNoteRequestHeaders = {};
      return originalOpen.call(this, method, url, ...rest);
    };
    if (typeof originalSetRequestHeader === "function") {
      XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        try {
          const normalized = normalizeRequestHeaderMap({ [name]: value });
          this.__learnNoteRequestHeaders = { ...(this.__learnNoteRequestHeaders || {}), ...normalized };
        } catch {
          // Keep host XHR untouched if header inspection fails.
        }
        return originalSetRequestHeader.call(this, name, value);
      };
    }
    XMLHttpRequest.prototype.send = function (...args) {
      this.addEventListener("loadend", () => {
        const url = this.responseURL || this.__learnNoteUrl || "";
        const mime = this.getResponseHeader?.("content-type") || "";
        const meta = xhrResponseMeta(this, url);
        emit([applyResponseMeta({ url, source: "pageHookRequest", label: "xhr", mime }, meta)]);
        if (typeof Blob !== "undefined" && this.response instanceof Blob) {
          const meta = blobMeta(url, this.response.type || mime, "pageHookBlob", "xhr blob source");
          rememberBlobObject(this.response, meta);
        }
        if (typeof ArrayBuffer !== "undefined" && this.response instanceof ArrayBuffer) {
          const meta = blobMeta(url, mime, "pageHookBlob", "xhr arrayBuffer source");
          rememberBlobPartObject(this.response, meta);
        }
        if (!shouldInspectTextPayload(url, mime, 0)) return;
        if (this.responseType === "json") {
          if (this.response && typeof this.response === "object") {
            emit(collectJsonMediaUrls(this.response, "pageHookBody", "xhr json", [], null, [], new Set(), new WeakSet(), meta));
          } else if (typeof this.response === "string") {
            extractUrlsFromText(this.response.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr json", mime, url, meta);
          }
          return;
        }
        if (this.responseType && this.responseType !== "text") return;
        let text = "";
        try {
          text = typeof this.response === "string" ? this.response : this.responseText;
        } catch {
          text = "";
        }
        if (typeof text !== "string") return;
        extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr body", mime, url, meta);
      });
      return originalSend.apply(this, args);
    };
  }

  function installEmeDetection() {
    try {
      if (navigator.requestMediaKeySystemAccess && !navigator.__learnNoteRequestMediaKeySystemAccess) {
        const originalRequestMediaKeySystemAccess = navigator.requestMediaKeySystemAccess.bind(navigator);
        Object.defineProperty(navigator, "__learnNoteRequestMediaKeySystemAccess", { value: originalRequestMediaKeySystemAccess });
        navigator.requestMediaKeySystemAccess = function (keySystem, supportedConfigurations) {
          rememberDrmSignal({
            source: "pageHookEme",
            key_system: keySystem,
            label: "requestMediaKeySystemAccess"
          });
          return originalRequestMediaKeySystemAccess(keySystem, supportedConfigurations);
        };
      }
    } catch {
      // Some pages lock navigator methods. The encrypted event listener below still provides a DRM signal.
    }

    try {
      const proto = window.HTMLMediaElement?.prototype;
      if (proto?.setMediaKeys && !proto.__learnNoteSetMediaKeys) {
        const originalSetMediaKeys = proto.setMediaKeys;
        Object.defineProperty(proto, "__learnNoteSetMediaKeys", { value: originalSetMediaKeys });
        proto.setMediaKeys = function (...args) {
          rememberDrmSignal({
            source: "pageHookEme",
            label: "setMediaKeys"
          });
          return originalSetMediaKeys.apply(this, args);
        };
      }
    } catch {
      // Keep playback untouched if the page prevents patching the media prototype.
    }

    document.addEventListener("encrypted", event => {
      rememberDrmSignal({
        source: "pageHookEme",
        init_data_type: event.initDataType || "",
        label: "encrypted event"
      });
    }, true);
  }

  installEmeDetection();
  patchHtmlMediaElement();
  patchKnownPlayerLibraries();
  installLatePlayerGlobalWatchers();
  scanGlobalConfig();
  setTimeout(patchKnownPlayerLibraries, 100);
  setTimeout(scanGlobalConfig, 500);
  setTimeout(patchKnownPlayerLibraries, 500);
  setTimeout(patchKnownPlayerLibraries, 1500);
  setTimeout(scanGlobalConfig, 2000);
  setTimeout(patchKnownPlayerLibraries, 3000);

  window.addEventListener("message", event => {
    if (event.source !== window || event.data?.source !== "learnnote-content-ready") return;
    scanGlobalConfig();
    post(bufferedResources, drmSignals);
  });
})();
