(function () {
  if (window.__learnNotePageHookInstalled) return;
  window.__learnNotePageHookInstalled = true;

  const MEDIA_EXT_PATTERN = "mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa";
  const MEDIA_URL_RE = new RegExp(`(?:https?:)?//[^\\s"'<>\\\\]+\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?|(?:/[^\\s"'<>\\\\]+)\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\\.(?:${MEDIA_EXT_PATTERN})(?:\\?[^\\s"'<>\\\\]*)?`, "gi");
  const ENCODED_MEDIA_URL_RE = new RegExp(`https?%(?:25)*3A(?:(?:%(?:25)*2F)|/){2}[^\\s"'<>\\\\]+?(?:\\.|%(?:25)*2E)(?:${MEDIA_EXT_PATTERN})(?:[^\\s"'<>\\\\]*)?`, "gi");
  const MEDIA_HINT_RE = new RegExp(`\\.(?:${MEDIA_EXT_PATTERN})(?:[?#]|["'\\s<>]|$)`, "i");
  const FRAGMENT_RE = /\.(?:m4s|ts)(?:\?|#|$)/i;
  const TEXT_TYPE_RE = /json|text|javascript|mpegurl|dash\+xml|xml|x-mpegurl/i;
  const JSON_MEDIA_KEY_RE = /(url|uri|path|src|address|file|fileid|objectid|dtoken|download|httpmd|play|playlist|media|video|audio|stream|source|sourcelist|main|master|manifest|backup|backups|cdn|baseurl|base_url|host|domain|video.?list|audio.?list|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)/i;
  const JSON_MIME_KEY_RE = /(mime|type|format|content.?type|media.?type)/i;
  const GLOBAL_MEDIA_NAME_RE = /(^__.*(play|player|media|video|audio|stream|hls|dash|m3u8|mpd))|((play|player|media|video|audio|stream|hls|dash|m3u8|mpd).*(config|info|data|url|source|sources|list)$)/i;
  const GLOBAL_MEDIA_KEYS = [
    "__playInfo",
    "__playInfo__",
    "__playinfo",
    "__playinfo__",
    "__PLAYINFO__",
    "__playerConfig",
    "__playerConfig__",
    "__PLAYER_CONFIG__",
    "__player_config__",
    "__videoInfo",
    "__videoInfo__",
    "__videoData",
    "__videoData__",
    "__audioInfo",
    "__INITIAL_STATE__",
    "__NEXT_DATA__",
    "playInfo",
    "playerInfo",
    "playerConfig",
    "videoInfo",
    "videoData",
    "videoConfig",
    "audioInfo",
    "audioData",
    "audioConfig",
    "mediaInfo",
    "mediaData",
    "courseData",
    "lessonData",
    "__coursePlayer",
    "__coursePlayerConfig",
    "__lessonPlayer",
    "__lessonPlayerConfig",
    "coursePlayer",
    "coursePlayerConfig",
    "lessonPlayer",
    "lessonPlayerConfig",
    "ananasVideoInfo",
    "ananasPlayerConfig"
  ];
  const TEXT_MEDIA_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*["']((?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^"'<>\\\s]){4,})["']/gi;
  const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;
  const MAX_TEXT_BYTES = 2 * 1024 * 1024;
  const MAX_BLOB_URLS = 80;
  const MAX_REQUEST_BODY_BYTES = 64 * 1024;
  const REQUEST_BODY_REPLAY_METHODS = new Set(["POST", "PUT", "PATCH"]);
  const RESPONSE_HEADER_ALLOWLIST = ["accept-ranges", "content-disposition", "content-length", "content-range", "content-type"];
  const REQUEST_HEADER_ALLOWLIST = new Set([
    "accept",
    "accept-language",
    "authorization",
    "content-type",
    "origin",
    "range",
    "referer",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
    "x-requested-with"
  ]);
  const REQUEST_HEADER_CANONICAL = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "authorization": "Authorization",
    "content-type": "Content-Type",
    "origin": "Origin",
    "range": "Range",
    "referer": "Referer",
    "sec-fetch-dest": "Sec-Fetch-Dest",
    "sec-fetch-mode": "Sec-Fetch-Mode",
    "sec-fetch-site": "Sec-Fetch-Site",
    "user-agent": "User-Agent",
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
  const sourceBufferMimeByObject = new WeakMap();
  const sourceBufferAppendStats = new WeakMap();
  const mediaSourcePageIdentity = new WeakMap();
  const globalConfigIdentityByName = new Map();
  let patchingLatePlayerGlobal = false;
  let pageEpoch = 1;

  function currentPageUrl() {
    return String(location.href || "");
  }

  function currentPageIdentity() {
    return `${pageEpoch}:${currentPageUrl()}`;
  }

  function globalConfigMeta(name, value, forceCurrent = false) {
    const previous = globalConfigIdentityByName.get(name);
    if (!forceCurrent && previous && previous.value === value) return previous.meta;
    const meta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
    globalConfigIdentityByName.set(name, { value, meta });
    return meta;
  }

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

  function mediaKind(url, mime = "") {
    const lower = String(url || "").toLowerCase();
    const type = String(mime || "").toLowerCase();
    if (FRAGMENT_RE.test(lower)) return "fragment";
    if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
    if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
    if (type.includes("text/vtt") || type.includes("subrip") || /\.(vtt|srt|ass|ssa)(\?|#|$)/i.test(lower)) return "subtitle";
    if (type.includes("video/") || /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i.test(lower)) return "video";
    if (type.includes("audio/") || /\.(m4a|mp3|aac|opus|ogg|oga|wav)(\?|#|$)/i.test(lower)) return "audio";
    return "unknown";
  }

  function mediaKindFromContentDisposition(value = "", mime = "") {
    const header = String(value || "");
    let filename = "";
    for (const part of header.split(";")) {
      const [rawKey, ...rest] = part.trim().split("=");
      if (!rawKey || !rest.length) continue;
      const key = rawKey.toLowerCase();
      let raw = rest.join("=").trim().replace(/^"|"$/g, "");
      if (key === "filename*") {
        const marker = raw.indexOf("''");
        raw = marker >= 0 ? raw.slice(marker + 2) : raw;
      }
      if ((key === "filename" || key === "filename*") && raw) {
        try {
          filename = decodeURIComponent(raw);
        } catch {
          filename = raw;
        }
        if (filename) break;
      }
    }
    return filename ? mediaKind(filename.split(/[\\/]/).pop() || "", mime) : "unknown";
  }

  function responseMediaKind(url, mime = "", headers = {}) {
    const direct = mediaKind(url, mime);
    if (direct !== "unknown") return direct;
    const dispositionKind = mediaKindFromContentDisposition(headers?.["content-disposition"] || "", mime);
    if (dispositionKind !== "unknown") return dispositionKind;
    const type = String(mime || "").toLowerCase();
    const binaryLike = /octet-stream|binary|application\/x-mpegurl/i.test(type);
    const byteRangeEvidence = Boolean(headers?.["content-range"]) || String(headers?.["accept-ranges"] || "").toLowerCase().includes("bytes");
    if ((binaryLike || byteRangeEvidence) && mediaUrlHint(url)) {
      return endpointKindHint(url).kind;
    }
    return "unknown";
  }

  function bytesFromAppendBuffer(value, limit = 512) {
    try {
      if (value instanceof ArrayBuffer) return new Uint8Array(value, 0, Math.min(value.byteLength, limit));
      if (ArrayBuffer.isView?.(value)) {
        return new Uint8Array(value.buffer, value.byteOffset || 0, Math.min(value.byteLength || 0, limit));
      }
    } catch {
      return new Uint8Array();
    }
    return new Uint8Array();
  }

  function asciiFromBytes(bytes) {
    let text = "";
    for (const byte of bytes || []) {
      text += byte >= 32 && byte <= 126 ? String.fromCharCode(byte) : ".";
    }
    return text;
  }

  function appendMagic(bytes) {
    const head = asciiFromBytes(bytes || []);
    if (!head) return "";
    if (head.startsWith("#EXTM3U")) return "#EXTM3U";
    if (head.startsWith("WEBVTT")) return "WEBVTT";
    if (head.startsWith("ID3")) return "ID3";
    if (bytes?.[0] === 0x1a && bytes?.[1] === 0x45 && bytes?.[2] === 0xdf && bytes?.[3] === 0xa3) return "webm-ebml";
    for (const token of ["ftyp", "moof", "moov", "mdat", "styp"]) {
      if (head.slice(0, 64).includes(token)) return token;
    }
    return Array.from((bytes || []).slice(0, 8)).map(byte => byte.toString(16).padStart(2, "0")).join(" ");
  }

  function appendDetectedKind(magic, mime = "") {
    const type = String(mime || "").toLowerCase();
    if (type.includes("mpegurl") || magic === "#EXTM3U") return "hls";
    if (type.includes("dash+xml")) return "dash";
    if (type.includes("vtt") || type.includes("subtitle") || magic === "WEBVTT") return "subtitle";
    if (type.includes("video/") || ["ftyp", "moov", "webm-ebml"].includes(magic)) return "video";
    if (type.includes("audio/")) return "audio";
    if (["moof", "mdat", "styp", "ID3"].includes(magic)) return "fragment";
    return "blob";
  }

  function appendBufferEvidence(sourceBuffer, value) {
    const bytes = bytesFromAppendBuffer(value);
    const appendBytes = value instanceof ArrayBuffer
      ? value.byteLength
      : ArrayBuffer.isView?.(value)
        ? value.byteLength
        : 0;
    const previous = sourceBufferAppendStats.get(sourceBuffer) || { count: 0, total: 0 };
    const count = previous.count + 1;
    const total = previous.total + Math.max(0, appendBytes || 0);
    sourceBufferAppendStats.set(sourceBuffer, { count, total });
    const mime = sourceBufferMimeByObject.get(sourceBuffer) || "";
    const magic = appendMagic(bytes);
    return {
      mse_append_bytes: appendBytes || null,
      mse_append_total_bytes: total || null,
      mse_append_count: count,
      mse_append_magic: magic,
      mse_append_mime: mime,
      mse_append_detected_kind: appendDetectedKind(magic, mime)
    };
  }

  function manifestKindFromText(text, mime = "") {
    const head = String(text || "").slice(0, 4096).trimStart();
    const type = String(mime || "").toLowerCase();
    if (head.startsWith("#EXTM3U") || type.includes("mpegurl") || type.includes("x-mpegurl")) return "hls";
    if (/<MPD[\s>]/i.test(head)) return "dash";
    return "unknown";
  }

  function mediaUrlHint(url = "") {
    return /(^|[/?&=._-])(m3u8|mpd|hls|dash|manifest|playlist|master|main|backup|backups|source|sources|sourcelist|cdn|baseurl|base_url|base-url|host|domain|stream|play|video|audio|media|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|ananas|objectid|dtoken|fileid|httpmd)([/?&=._-]|$)/i.test(String(url || ""));
  }

  function endpointKindHint(url = "") {
    const text = String(url || "").toLowerCase();
    if (/(^|[/?&=._-])audio([/?&=._-]|$)/i.test(text)) return { kind: "audio", mime: "audio/mp4" };
    if (mediaUrlHint(text)) return { kind: "video", mime: "video/mp4" };
    return { kind: "unknown", mime: "" };
  }

  function post(resources = [], drm = [], navigation = false) {
    if (!navigation && !resources?.length && !drm?.length) return;
    window.postMessage({
      source: "learnnote-page-hook",
      resources,
      drm,
      navigation,
      page_url: currentPageUrl(),
      page_identity: currentPageIdentity()
    }, "*");
  }

  function resetForNavigation() {
    pageEpoch += 1;
    bufferedResources.length = 0;
    drmSignals.length = 0;
    blobSourceByUrl.clear();
    blobUrlOrder.length = 0;
    post([], [], true);
  }

  function emit(resources) {
    const deduped = [];
    const seen = new Set();
    for (const item of resources || []) {
      const pageIdentity = item.page_identity || currentPageIdentity();
      if (pageIdentity !== currentPageIdentity()) continue;
      const url = normalizeUrl(item.url);
      if (!url || seen.has(url) || /^image\//i.test(String(item.mime || ""))) continue;
      const kind = item.kind && item.kind !== "unknown"
        ? item.kind
        : responseMediaKind(url, item.mime || "", item.headers || {});
      if (kind === "unknown") continue;
      seen.add(url);
      deduped.push({
        url,
        source: item.source || "pageHook",
        kind,
        mime: item.mime || "",
        label: item.label || "page hook",
        score: item.score || scoreForKind(kind, { manifest: 96, video: 88, audio: 38, other: 62 }),
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
        request_body: item.request_body || {},
        audio_url: item.audio_url || "",
        audio_mime: item.audio_mime || "",
        mse_append_bytes: item.mse_append_bytes ?? null,
        mse_append_total_bytes: item.mse_append_total_bytes ?? null,
        mse_append_count: item.mse_append_count ?? null,
        mse_append_magic: item.mse_append_magic || "",
        mse_append_mime: item.mse_append_mime || "",
        mse_append_detected_kind: item.mse_append_detected_kind || "",
        visibility: item.visibility || "unknown",
        is_visible: item.is_visible ?? null,
        visible_area: item.visible_area ?? null,
        rendered_width: item.rendered_width ?? null,
        rendered_height: item.rendered_height ?? null,
        duration: item.duration ?? null,
        paused: item.paused ?? null,
        page_url: item.page_url || currentPageUrl(),
        page_identity: pageIdentity,
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
          request_headers: { ...(existing.request_headers || {}), ...(item.request_headers || {}) },
          request_body: { ...(existing.request_body || {}), ...(item.request_body || {}) },
          audio_url: item.audio_url || existing.audio_url || "",
          audio_mime: item.audio_mime || existing.audio_mime || "",
          mse_append_bytes: item.mse_append_bytes ?? existing.mse_append_bytes ?? null,
          mse_append_total_bytes: item.mse_append_total_bytes ?? existing.mse_append_total_bytes ?? null,
          mse_append_count: item.mse_append_count ?? existing.mse_append_count ?? null,
          mse_append_magic: item.mse_append_magic || existing.mse_append_magic || "",
          mse_append_mime: item.mse_append_mime || existing.mse_append_mime || "",
          mse_append_detected_kind: item.mse_append_detected_kind || existing.mse_append_detected_kind || "",
          visibility: item.visibility !== "unknown" ? item.visibility : existing.visibility || "unknown",
          is_visible: item.is_visible ?? existing.is_visible ?? null,
          visible_area: item.visible_area ?? existing.visible_area ?? null,
          rendered_width: item.rendered_width ?? existing.rendered_width ?? null,
          rendered_height: item.rendered_height ?? existing.rendered_height ?? null,
          duration: item.duration ?? existing.duration ?? null,
          paused: item.paused ?? existing.paused ?? null
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
      page_identity: currentPageIdentity(),
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
    if (kind === "audio") return "audio/mp4";
    return "";
  }

  function scoreForKind(kind, scores = {}) {
    if (kind === "hls" || kind === "dash") return scores.manifest ?? 97;
    if (kind === "video") return scores.video ?? 89;
    if (kind === "audio") return scores.audio ?? 38;
    if (kind === "subtitle") return scores.subtitle ?? 64;
    return scores.other ?? 64;
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
    const userAgent = cleanHeaderValue(typeof navigator !== "undefined" ? navigator.userAgent : "");
    return {
      ...(userAgent ? { "User-Agent": userAgent } : {}),
      ...normalizeRequestHeaderMap(input?.headers),
      ...normalizeRequestHeaderMap(init?.headers)
    };
  }

  function fetchRequestMethod(input, init = {}) {
    return String(init?.method || input?.method || "GET").toUpperCase();
  }

  function utf8ByteLength(value) {
    const text = String(value ?? "");
    try {
      if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(text).byteLength;
    } catch {
      // Fall through to URL-encoded byte estimate.
    }
    try {
      return unescape(encodeURIComponent(text)).length;
    } catch {
      return text.length;
    }
  }

  function requestBodyFromText(content, type = "text") {
    const text = String(content ?? "");
    if (!text) return {};
    if (utf8ByteLength(text) > MAX_REQUEST_BODY_BYTES) return {};
    return { type, content: text };
  }

  function requestBodyFromBuffer(value) {
    try {
      const view = ArrayBuffer.isView(value)
        ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
        : value instanceof ArrayBuffer
          ? new Uint8Array(value)
          : null;
      if (!view || view.byteLength > MAX_REQUEST_BODY_BYTES) return {};
      if (typeof TextDecoder === "undefined") return {};
      return requestBodyFromText(new TextDecoder("utf-8").decode(view), "bytes");
    } catch {
      return {};
    }
  }

  function requestBodyFromFormData(body) {
    try {
      const params = new URLSearchParams();
      for (const [name, value] of body.entries()) {
        if (typeof value !== "string") return {};
        params.append(name, value);
        if (utf8ByteLength(params.toString()) > MAX_REQUEST_BODY_BYTES) return {};
      }
      return requestBodyFromText(params.toString(), "form");
    } catch {
      return {};
    }
  }

  function requestBodyFromValue(method, body) {
    if (!REQUEST_BODY_REPLAY_METHODS.has(method)) return {};
    if (body === undefined || body === null) return {};
    if (typeof body === "string") return requestBodyFromText(body, "text");
    if (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) return requestBodyFromText(body.toString(), "form");
    if (typeof FormData !== "undefined" && body instanceof FormData) return requestBodyFromFormData(body);
    if (typeof ArrayBuffer !== "undefined" && (body instanceof ArrayBuffer || ArrayBuffer.isView(body))) return requestBodyFromBuffer(body);
    return {};
  }

  function fetchRequestBody(method, init = {}) {
    return requestBodyFromValue(method, init?.body);
  }

  function headerNumber(source, name) {
    try {
      const raw = source?.get?.(name) || source?.[name] || source?.[name.toLowerCase()] || "";
      const value = Number(raw || 0);
      return Number.isFinite(value) && value > 0 ? value : 0;
    } catch {
      return 0;
    }
  }

  function requestTextWithTimeout(request, timeoutMs = 800) {
    const read = request.text();
    if (typeof setTimeout !== "function") return read;
    return Promise.race([
      read,
      new Promise(resolve => setTimeout(() => resolve(""), timeoutMs))
    ]);
  }

  async function fetchRequestBodyFromInput(method, input, init = {}) {
    const explicit = fetchRequestBody(method, init);
    if (explicit.content) return explicit;
    if (!REQUEST_BODY_REPLAY_METHODS.has(method)) return {};
    if (!input || typeof input.clone !== "function") return {};
    const length = headerNumber(input.headers, "content-length");
    if (length > MAX_REQUEST_BODY_BYTES) return {};
    try {
      const clone = input.clone();
      if (typeof clone?.text !== "function") return {};
      const text = await requestTextWithTimeout(clone);
      return requestBodyFromText(text, "text");
    } catch {
      return {};
    }
  }

  function fetchResponseMeta(response, url = "", requestHeaders = {}, method = "", requestBody = {}) {
    const headers = safeResponseHeaders(name => response.headers?.get?.(name) || "");
    return {
      request_type: "fetch",
      method,
      status_code: response.status ?? null,
      content_length: numericHeader(headers, "content-length"),
      initiator: response.url || url || "",
      headers,
      request_headers: requestHeaders,
      request_body: requestBody,
      page_url: currentPageUrl(),
      page_identity: currentPageIdentity()
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
      request_headers: xhr.__learnNoteRequestHeaders || {},
      request_body: xhr.__learnNoteRequestBody || {},
      page_url: xhr.__learnNotePageUrl || currentPageUrl(),
      page_identity: xhr.__learnNotePageIdentity || currentPageIdentity()
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
      request_headers: { ...(item.request_headers || {}), ...(meta.request_headers || {}) },
      request_body: { ...(item.request_body || {}), ...(meta.request_body || {}) },
      page_url: item.page_url || meta.page_url || currentPageUrl(),
      page_identity: item.page_identity || meta.page_identity || currentPageIdentity()
    };
  }

  function looksLikeJsonUrlCandidate(value) {
    const text = String(value || "").trim();
    if (text.length < 4 || /\s/.test(text)) return false;
    if (/^(audio|video|application|text)\/[a-z0-9.+-]+$/i.test(text)) return false;
    if (/^(https?:)?\/\//i.test(text)) return true;
    if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return true;
    if (text.startsWith("/")) return true;
    return text.includes("/") && /[?=&]|api|ananas|play|media|video|audio|stream|vod|m3u8|mpd|hls|dash|objectid|dtoken|fileid|httpmd/i.test(text);
  }

  function looksLikeNestedMediaText(value) {
    const text = String(value || "").trim();
    if (text.length < 8) return false;
    if ("{[".includes(text[0])) {
      return JSON_MEDIA_KEY_RE.test(text) && (MEDIA_HINT_RE.test(text) || mediaUrlHint(text));
    }
    return JSON_MEDIA_KEY_RE.test(text) && (MEDIA_HINT_RE.test(text) || mediaUrlHint(text));
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
    const keyContext = keys.join(" ").toLowerCase();
    const mimeContext = jsonContextMime(parent).toLowerCase();
    if (keyContext.includes("mpegurl") || keyContext.includes("x-mpegurl") || keyContext.includes("m3u8") || keyContext.includes("hls")) {
      return { kind: "hls", mime: "application/vnd.apple.mpegurl" };
    }
    if (keyContext.includes("dash+xml") || keyContext.includes("mpd") || keyContext.includes("dash")) {
      return { kind: "dash", mime: "application/dash+xml" };
    }
    if (keyContext.includes("text/vtt") || keyContext.includes("subrip") || keyContext.includes("subtitle") || keyContext.includes("caption")) {
      return { kind: "subtitle", mime: "text/vtt" };
    }
    if (keyContext.includes("audio/") || keyContext.includes("m4a") || keyContext.includes("mp3") || keyContext.includes("aac") || keyContext.includes("opus") || keyContext.includes("audio")) {
      return { kind: "audio", mime: "audio/mp4" };
    }
    if (keyContext.includes("video/") || keyContext.includes("mp4") || keyContext.includes("video")) {
      return { kind: "video", mime: "video/mp4" };
    }
    if (mimeContext.includes("mpegurl") || mimeContext.includes("x-mpegurl") || mimeContext.includes("m3u8") || mimeContext.includes("hls")) {
      return { kind: "hls", mime: "application/vnd.apple.mpegurl" };
    }
    if (mimeContext.includes("dash+xml") || mimeContext.includes("mpd") || mimeContext.includes("dash")) {
      return { kind: "dash", mime: "application/dash+xml" };
    }
    if (mimeContext.includes("text/vtt") || mimeContext.includes("subrip") || mimeContext.includes("subtitle") || mimeContext.includes("caption")) {
      return { kind: "subtitle", mime: "text/vtt" };
    }
    if (mimeContext.includes("audio/") || mimeContext.includes("m4a") || mimeContext.includes("mp3") || mimeContext.includes("aac") || mimeContext.includes("opus") || mimeContext.includes("audio")) {
      return { kind: "audio", mime: "audio/mp4" };
    }
    if (mimeContext.includes("video/") || mimeContext.includes("mp4") || mimeContext.includes("video")) {
      return { kind: "video", mime: "video/mp4" };
    }
    const endpoint = endpointKindHint(url);
    if (JSON_MEDIA_KEY_RE.test(keyContext) && endpoint.kind !== "unknown") return endpoint;
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

  function isJsonBaseOnlyKey(key = "") {
    return /^(base.?url|base.?path|path.?prefix|cdn|host|domain|origin|endpoint|server|root|prefix|dir|directory)$/i.test(String(key || ""));
  }

  function currentLocationProtocol() {
    try {
      return location.protocol || new URL(location.href).protocol || "https:";
    } catch {
      return "https:";
    }
  }

  function currentLocationOrigin() {
    try {
      return location.origin || new URL(location.href).origin || "";
    } catch {
      return "";
    }
  }

  function normalizeJsonBaseUrl(value, key = "") {
    const raw = String(value || "").trim().replace(/^['"]|['"]$/g, "");
    if (!raw || /\s/.test(raw)) return "";
    const keyContext = String(key || "").toLowerCase();
    try {
      if (raw.startsWith("//")) return `${currentLocationProtocol()}${raw}`.replace(/\/?$/, "/");
      if (/^https?:\/\//i.test(raw)) return raw.replace(/\/?$/, "/");
      if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:\/.*)?$/.test(raw)) {
        return `${currentLocationProtocol()}//${raw}`.replace(/\/?$/, "/");
      }
      if (raw.startsWith("/") && /(base.?path|path.?prefix|root|prefix|dir|directory)/i.test(keyContext)) {
        return new URL(raw, location.href).href.replace(/\/?$/, "/");
      }
      if (raw.endsWith("/") && /(base.?path|path.?prefix|root|prefix|dir|directory)/i.test(keyContext)) {
        return new URL(raw, location.href).href.replace(/\/?$/, "/");
      }
    } catch {
      return "";
    }
    return "";
  }

  function jsonBaseUrls(node) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return [];
    const bases = [];
    const hostBases = [];
    const pathBases = [];
    const add = (url, bucket = null) => {
      if (!url || bases.includes(url)) return;
      bases.push(url);
      if (bucket && !bucket.includes(url)) bucket.push(url);
    };
    for (const [key, value] of safeObjectEntries(node)) {
      if (typeof value !== "string" || !isJsonBaseOnlyKey(key)) {
        continue;
      }
      for (const candidateValue of decodedMediaValues(value)) {
        const url = normalizeJsonBaseUrl(candidateValue, key);
        if (!url) continue;
        try {
          const parsed = new URL(url, location.href);
          const raw = String(candidateValue || "").trim().replace(/^['"]|['"]$/g, "");
          if (parsed.pathname.replace(/\/+$/, "") === "") add(url, hostBases);
          else if (raw.startsWith("/") && parsed.origin === currentLocationOrigin()) add(url, pathBases);
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
          // Invalid synthetic base combinations are ignored.
        }
      }
    }
    return bases
      .sort((a, b) => {
        try {
          const parsedA = new URL(a, location.href);
          const parsedB = new URL(b, location.href);
          const pathDelta = parsedB.pathname.length - parsedA.pathname.length;
          if (pathDelta) return pathDelta;
          const currentOrigin = currentLocationOrigin();
          return Number(parsedB.origin !== currentOrigin) - Number(parsedA.origin !== currentOrigin);
        } catch {
          return b.length - a.length;
        }
      })
      .slice(0, 8);
  }

  function looksLikeSplitMediaPath(value, keys, parent) {
    const text = String(value || "").trim().replace(/^['"]|['"]$/g, "");
    if (!text || /\s/.test(text)) return false;
    const decoded = decodeRepeatedUrlComponent(decodeJsStringEscapes(text));
    if (/^(?:https?:)?\/\//i.test(decoded)) return false;
    if (/^(audio|video|application|text)\/[a-z0-9.+-]+$/i.test(text)) return false;
    if (/^(?:https?:)?\/\//i.test(text)) return false;
    if (/^(data|blob|javascript):/i.test(text)) return false;
    if (MEDIA_HINT_RE.test(text)) return true;
    const context = keys.join(" ").toLowerCase();
    const mimeContext = jsonContextMime(parent).toLowerCase();
    return JSON_MEDIA_KEY_RE.test(context) && /video\/|mpegurl|dash\+xml|audio\//i.test(mimeContext);
  }

  function collectSplitBaseMediaUrls(node, source, label, keys, seen, meta, inheritedBases = []) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return [];
    const bases = jsonBaseUrls(node);
    for (const inherited of inheritedBases || []) {
      if (inherited && !bases.includes(inherited)) bases.push(inherited);
    }
    if (!bases.length) return [];
    const resources = [];
    for (const [key, value] of safeObjectEntries(node)) {
      if (typeof value !== "string" || !JSON_MEDIA_KEY_RE.test(key) || isJsonBaseOnlyKey(key)) continue;
      const nextKeys = [...keys, key];
      for (const candidateValue of decodedMediaValues(value)) {
        if (!looksLikeSplitMediaPath(candidateValue, nextKeys, node)) continue;
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
          if (!url || seen.has(url)) continue;
          const { kind, mime } = kindFromJsonContext(nextKeys, url, node);
          if (kind === "unknown") continue;
          seen.add(url);
          resources.push(applyResponseMeta({
            url,
            source,
            kind,
            mime,
            label: `${label} json combined ${nextKeys.slice(-3).join("/")}`,
            score: Math.min(100, scoreForKind(kind) + 18)
          }, meta));
          break;
        }
        if (resources.length >= 20) break;
      }
      if (resources.length >= 20) break;
    }
    return resources;
  }

  function attachSiblingAudioUrl(resources = []) {
    const audios = resources.filter(item => item?.kind === "audio" && item.url);
    const videos = resources.filter(item => item?.kind === "video" && item.url);
    if (audios.length !== 1 || videos.length !== 1) return;
    const [audio] = audios;
    const [video] = videos;
    if (video.audio_url) return;
    video.audio_url = audio.url;
    video.audio_mime = audio.mime || "audio/mp4";
    video.score = Math.min(100, Math.max(Number(video.score || 0), 92));
    video.label = `${video.label || "video"} + audio`;
  }

  function collectJsonMediaUrls(node, source, label, keys = [], parent = null, output = [], seen = new Set(), visited = new WeakSet(), meta = {}, inheritedBases = []) {
    if (!node || output.length >= 40) return output;
    if (Array.isArray(node)) {
      for (let index = 0; index < Math.min(node.length, 120); index += 1) {
        let child = null;
        try {
          child = node[index];
        } catch {
          child = null;
        }
        collectJsonMediaUrls(child, source, label, [...keys, String(index)], node, output, seen, visited, meta, inheritedBases);
        if (output.length >= 40) break;
      }
      return output;
    }
    if (typeof node !== "object") return output;
    if (visited.has(node)) return output;
    visited.add(node);
    const localBases = jsonBaseUrls(node);
    const childBases = [...(inheritedBases || [])];
    for (const base of localBases) {
      if (base && !childBases.includes(base)) childBases.push(base);
    }
    const siblingResources = [];
    const splitResources = collectSplitBaseMediaUrls(node, source, label, keys, seen, meta, childBases);
    output.push(...splitResources.slice(0, Math.max(0, 40 - output.length)));
    siblingResources.push(...splitResources);
    for (const [key, value] of safeObjectEntries(node)) {
      const nextKeys = [...keys, key];
      if (typeof value === "string" && JSON_MEDIA_KEY_RE.test(key) && !isJsonBaseOnlyKey(key)) {
        for (const candidateValue of decodedMediaValues(value)) {
          if (!looksLikeJsonUrlCandidate(candidateValue)) continue;
          const url = normalizeUrl(candidateValue);
          if (url && !seen.has(url)) {
            const { kind, mime } = kindFromJsonContext(nextKeys, url, node);
            if (kind !== "unknown") {
              seen.add(url);
              const item = applyResponseMeta({
                url,
                source,
                kind,
                mime,
                label: `${label} json ${nextKeys.slice(-3).join("/")}`,
                score: scoreForKind(kind)
              }, meta);
              output.push(item);
              siblingResources.push(item);
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
          const item = applyResponseMeta({
            url,
            source,
            kind,
            mime,
            label: `${label} json ${nextKeys.slice(-3).join("/")}`,
            score: scoreForKind(kind)
          }, meta);
          output.push(item);
          siblingResources.push(item);
          break;
        }
      }
      if (typeof value === "string" && keys.length < 12) {
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
        collectJsonMediaUrls(value, source, label, nextKeys, node, output, seen, visited, meta, childBases);
      }
      if (output.length >= 40) break;
    }
    attachSiblingAudioUrl(siblingResources);
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
      if (!JSON_MEDIA_KEY_RE.test(key) || isJsonBaseOnlyKey(key)) continue;
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
          score: scoreForKind(kind)
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
          score: scoreForKind(kind)
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
    const kind = responseMediaKind(normalizedUrl, mime || "");
    if (!normalizedUrl || kind === "unknown") return null;
    return {
      url: normalizedUrl,
      source,
      kind,
      mime: mime || "",
      label,
      score: scoreForKind(kind, { manifest: 98, video: 94, audio: 40, other: 66 })
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
    try {
      if (ArrayBuffer.isView?.(part) && part.buffer && typeof part.buffer === "object") {
        blobPartSourceByObject.set(part.buffer, meta);
      }
    } catch {
      // Some cross-realm typed array views expose restricted backing buffers.
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
    resources.push(...collectUrlParameterMediaUrls(text, source, label, seen, meta, Math.max(0, 40 - resources.length)));
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

  function collectUrlParameterMediaUrls(text, source, label, seen = new Set(), meta = {}, limit = 20) {
    const resources = [];
    if (!text || limit <= 0 || typeof URLSearchParams === "undefined") return resources;
    const raw = String(text || "").trim();
    if (!raw || raw.length > 8192 || (!raw.includes("?") && !raw.includes("#"))) return resources;
    let parsed = null;
    try {
      parsed = new URL(raw, location.href);
    } catch {
      return resources;
    }
    for (const [scope, rawChunk] of [["query", parsed.search], ["hash", parsed.hash]]) {
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
        for (const candidateValue of decodedMediaValues(value)) {
          const trimmed = String(candidateValue || "").trim();
          if (!trimmed || trimmed.length > MAX_TEXT_BYTES) continue;
          const direct = looksLikeJsonUrlCandidate(trimmed) ? normalizeUrl(trimmed) : "";
          if (direct && !seen.has(direct)) {
            const { kind, mime: detectedMime } = kindFromJsonContext([key], direct, { [key]: value });
            if (kind !== "unknown") {
              seen.add(direct);
              resources.push(applyResponseMeta({
                url: direct,
                source,
                kind,
                mime: detectedMime,
                label: paramLabel,
                score: scoreForKind(kind)
              }, meta));
              if (resources.length >= limit) break;
            }
          }
          if (!"{[".includes(trimmed[0]) && !MEDIA_HINT_RE.test(trimmed) && !JSON_MEDIA_KEY_RE.test(trimmed)) continue;
          const nested = collectMediaUrlsFromText(trimmed, source, `${paramLabel} payload`, "", seen, meta);
          resources.push(...nested.slice(0, Math.max(0, limit - resources.length)));
          if (resources.length >= limit) break;
        }
      }
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
        mime: mimeForKind(kind),
        label: `${label} manifest`,
        score: 99
      }, meta));
    }
    return resources;
  }

  function extractUrlsFromText(text, source, label, mime = "", responseUrl = "", meta = {}) {
    emit(collectResponseTextResources(responseUrl, text, source, label, mime, meta));
  }

  function binaryPayloadBytes(value, limit = MAX_TEXT_BYTES) {
    if (!value) return null;
    try {
      if (value instanceof ArrayBuffer) return new Uint8Array(value, 0, Math.min(value.byteLength, limit));
      if (ArrayBuffer.isView(value)) {
        const length = Math.min(value.byteLength, limit);
        return new Uint8Array(value.buffer, value.byteOffset, length);
      }
    } catch {
      return null;
    }
    return null;
  }

  function binaryPayloadLooksTextual(bytes, mime = "", totalBytes = 0) {
    if (!bytes?.length) return false;
    if (totalBytes && totalBytes > MAX_TEXT_BYTES) return false;
    if (TEXT_TYPE_RE.test(String(mime || ""))) return true;
    const head = bytes.slice(0, Math.min(bytes.length, 64));
    if (head.length >= 12) {
      const ftyp = String.fromCharCode(head[4] || 0, head[5] || 0, head[6] || 0, head[7] || 0);
      if (ftyp === "ftyp") return false;
    }
    const magic = String.fromCharCode(...head.slice(0, Math.min(head.length, 16)));
    if (/^(FLV|OggS|ID3)|^\x1aE\xdf\xa3/.test(magic)) return false;
    if (head.some(byte => byte === 0)) return false;
    const text = new TextDecoder("utf-8", { fatal: false }).decode(head).replace(/^\ufeff/, "").trimStart();
    return text.startsWith("{") ||
      text.startsWith("[") ||
      text.startsWith("#EXTM3U") ||
      /^<MPD(?:\s|>)/i.test(text) ||
      text.startsWith("WEBVTT");
  }

  function inspectBinaryTextPayload(value, source, label, mime = "", responseUrl = "", meta = {}) {
    try {
      if (typeof TextDecoder === "undefined") return;
      const bytes = binaryPayloadBytes(value);
      const totalBytes = value?.byteLength ?? bytes?.byteLength ?? 0;
      if (!binaryPayloadLooksTextual(bytes, mime, totalBytes)) return;
      const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
      extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), source, label, mime, responseUrl, meta);
    } catch {
      // Binary response sniffing is best-effort and must not affect page playback.
    }
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
        resources.push(...collectMediaUrlsFromText(value.slice(0, MAX_TEXT_BYTES), "pageHookGlobal", `global ${name}`, "", seen, globalConfigMeta(name, value)));
      } else if (value && typeof value === "object") {
        resources.push(...collectJsonMediaUrls(value, "pageHookGlobal", `global ${name}`, [name], null, [], seen, new WeakSet(), globalConfigMeta(name, value)));
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
      for (const key of [
        "src", "url", "uri", "path", "address", "file", "fileId", "file_id", "objectid", "objectId", "object_id",
        "dtoken", "downloadUrl", "download_url", "httpmd", "source", "manifestUri", "manifestUrl", "manifest_url",
        "playUrl", "playURL", "play_url", "videoUrl", "video_url", "audioUrl", "audio_url", "streamUrl", "stream_url",
        "mediaUrl", "media_url", "mainUrl", "main_url", "masterUrl", "master_url", "backupUrl", "backup_url",
        "flvUrl", "flv_url", "hlsUrl", "hls_url", "m3u8Url", "m3u8_url", "dashUrl", "dash_url", "mpdUrl", "mpd_url"
      ]) {
        try {
          if (typeof value[key] === "string") output.push(value[key]);
        } catch {
          // Some player source objects expose throwing getters.
        }
      }
      for (const [key, child] of safeObjectEntries(value, 80)) {
        if (!/^(video|videos|video.?list|audio|audios|audio.?list|media|medias|source|sources|source.?list|playlist|play.?list|file|fileid|file_id|objectid|object_id|dtoken|download|download_url|httpmd|url|uri|path|address|config|options|play|play_url|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|streams?|stream_url|segments?|manifest|manifest_url|master|master_url|main_url|backup_url|hls|hls_url|m3u8|m3u8_url|dash|dash_url|mpd|mpd_url)$/i.test(key)) continue;
        sourceCandidates(child, output, visited, depth + 1);
      }
    }
    return output;
  }

  function emitPlayerSources(value, fallbackKind, label, evidence = {}) {
    const resources = [];
    const seen = new Set();
    for (const candidate of sourceCandidates(value)) {
      const url = normalizeUrl(candidate);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const detectedKind = mediaKind(url, "");
      const endpoint = detectedKind === "unknown" && !fallbackKind ? endpointKindHint(url) : null;
      const kind = detectedKind === "unknown" ? (fallbackKind || endpoint?.kind || "") : detectedKind;
      if (!kind || kind === "unknown") continue;
      resources.push({
        url,
        source: "pageHookPlayer",
        kind,
        mime: endpoint?.mime || mimeForKind(kind),
        label,
        score: scoreForKind(kind, { manifest: 99, video: 92, audio: 40, other: 64 }),
        ...evidence
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

  function patchPlyr() {
    try {
      const Plyr = window.Plyr;
      if (!Plyr?.prototype) return;
      const descriptor = Object.getOwnPropertyDescriptor(Plyr.prototype, "source");
      if (descriptor?.set && !descriptor.set.__learnNotePlyrSourcePatched) {
        const originalSet = descriptor.set;
        const wrappedSet = function (value) {
          emitPlayerSources(value, "", "Plyr source");
          return originalSet.call(this, value);
        };
        try {
          Object.defineProperty(wrappedSet, "__learnNotePlyrSourcePatched", { value: true });
        } catch {
          // The wrapped setter still works if the marker cannot be written.
        }
        Object.defineProperty(Plyr.prototype, "source", {
          ...descriptor,
          set: wrappedSet
        });
      }
      patchPlayerConstructorOn(window, "Plyr", "Plyr constructor");
    } catch {
      // Plyr is optional and may be loaded late or expose a locked prototype.
    }
  }

  function patchGenericPlayerInstance(player, label) {
    if (!player || typeof player !== "object") return player;
    for (const method of [
      "src", "url", "source", "load", "setup",
      "attachSource", "setDataSource", "setMediaSource",
      "switchVideo", "switchUrl", "switchURL",
      "changeQuality", "changeVideo", "replaceVideo",
      "setSrc", "setUrl", "setVideoUrl", "setSource", "changeSource", "changeUrl",
      "loadUrl", "loadByUrl", "loadVideo", "loadVideoUrl", "loadVideoByUrl", "playUrl"
    ]) {
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
    patchPlayerConstructorOn(window, "VideoRoll", "VideoRoll constructor");
    patchPlayerConstructorOn(window, "videoRoll", "VideoRoll constructor");
    patchPlayerConstructorOn(window.xgplayer, "Player", "xgplayer Player constructor");
    patchPlayerConstructorOn(window.VideoRoll, "Player", "VideoRoll Player constructor");
    patchPlayerConstructorOn(window.videoRoll, "Player", "VideoRoll Player constructor");
  }

  function patchCreatePlayerFactory(target, label) {
    try {
      if (!target || typeof target.createPlayer !== "function") return;
      patchMethod(target, "createPlayer", original => function (mediaDataSource, ...rest) {
        emitPlayerSources(mediaDataSource, "video", `${label} createPlayer`);
        return patchGenericPlayerInstance(original.call(this, mediaDataSource, ...rest), label);
      });
    } catch {
      // flv.js/mpegts.js globals are often frozen or replaced by bundlers.
    }
  }

  function patchSegmentedLivePlayers() {
    patchCreatePlayerFactory(window.flvjs, "flv.js");
    patchCreatePlayerFactory(window.mpegts, "mpegts.js");
    patchCreatePlayerFactory(window.mpegtsjs, "mpegts.js");
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

  function mediaElementEvidence(element) {
    const media = isSourceElement(element) ? element?.parentElement : element;
    if (!isMediaElement(media)) return {};
    let rect = null;
    let style = null;
    try {
      rect = media.getBoundingClientRect?.() || null;
      style = typeof window.getComputedStyle === "function" ? window.getComputedStyle(media) : null;
    } catch {
      rect = null;
      style = null;
    }
    const width = Math.max(0, Number(rect?.width ?? media.clientWidth ?? media.videoWidth ?? 0));
    const height = Math.max(0, Number(rect?.height ?? media.clientHeight ?? media.videoHeight ?? 0));
    const hidden = Boolean(media.hidden || style?.display === "none" || style?.visibility === "hidden" || Number(style?.opacity ?? 1) <= 0);
    const area = hidden ? 0 : width * height;
    return {
      visibility: hidden ? "hidden" : area > 0 ? "visible" : "unknown",
      is_visible: hidden ? false : area > 0 ? true : null,
      visible_area: area || 0,
      rendered_width: width,
      rendered_height: height,
      duration: Number.isFinite(media.duration) ? Number(media.duration || 0) : null,
      paused: typeof media.paused === "boolean" ? media.paused : null
    };
  }

  function emitMediaElementSource(element, value, label) {
    if (!value) return;
    emitPlayerSources(value, mediaElementFallbackKind(element), label, mediaElementEvidence(element));
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

  function patchMediaUrlDescriptor(proto, property, label) {
    if (!proto) return false;
    try {
      const flag = `__learnNote${property}DescriptorPatched`;
      if (Object.prototype.hasOwnProperty.call(proto, flag)) return true;
      const descriptor = Object.getOwnPropertyDescriptor(proto, property);
      if (!descriptor?.get || !descriptor?.set || descriptor.configurable === false) return false;
      Object.defineProperty(proto, property, {
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
      Object.defineProperty(proto, flag, { value: true });
      return true;
    } catch {
      return false;
    }
  }

  function patchHtmlMediaElement() {
    try {
      patchMediaUrlDescriptor(window.HTMLMediaElement?.prototype, "src", "HTMLMediaElement src");
      patchMediaUrlDescriptor(window.HTMLVideoElement?.prototype, "src", "HTMLVideoElement src");
      patchMediaUrlDescriptor(window.HTMLAudioElement?.prototype, "src", "HTMLAudioElement src");
      patchMediaUrlDescriptor(window.HTMLSourceElement?.prototype, "src", "HTMLSourceElement src");
      patchMediaUrlDescriptor(window.HTMLMediaElement?.prototype, "currentSrc", "HTMLMediaElement currentSrc");
      patchMediaUrlDescriptor(window.HTMLVideoElement?.prototype, "currentSrc", "HTMLVideoElement currentSrc");
      patchMediaUrlDescriptor(window.HTMLAudioElement?.prototype, "currentSrc", "HTMLAudioElement currentSrc");
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
    patchPlyr();
    patchCommonChinesePlayers();
    patchSegmentedLivePlayers();
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

  function emitGlobalConfigValue(name, value) {
    try {
      const seen = new Set();
      const label = `global ${name}`;
      const meta = globalConfigMeta(name, value, true);
      if (typeof value === "string") {
        emit(collectMediaUrlsFromText(value.slice(0, MAX_TEXT_BYTES), "pageHookGlobal", label, "", seen, meta));
      } else if (value && typeof value === "object") {
        emit(collectJsonMediaUrls(value, "pageHookGlobal", label, [name], null, [], seen, new WeakSet(), meta));
      }
    } catch {
      // Runtime player configs are best-effort hints only.
    }
  }

  function watchLateGlobalConfig(name) {
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
          emitGlobalConfigValue(name, value);
        }
      });
    } catch {
      // Some pages disallow accessors on window globals; timed scans still run.
    }
  }

  function installLateGlobalConfigWatchers() {
    for (const name of GLOBAL_MEDIA_KEYS) {
      watchLateGlobalConfig(name);
    }
  }

  function installLatePlayerGlobalWatchers() {
    for (const name of [
      "Hls",
      "dashjs",
      "shaka",
      "videojs",
      "videoJs",
      "Plyr",
      "DPlayer",
      "Artplayer",
      "ArtPlayer",
      "XGPlayer",
      "Aliplayer",
      "TcPlayer",
      "VideoRoll",
      "videoRoll",
      "xgplayer",
      "flvjs",
      "mpegts",
      "mpegtsjs",
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

  function inspectRealtimeMessageData(data, source, label, responseUrl = "", meta = {}) {
    try {
      if (typeof data !== "string") return;
      const text = data.slice(0, MAX_TEXT_BYTES);
      if (!text || (!MEDIA_HINT_RE.test(text) && !JSON_MEDIA_KEY_RE.test(text) && !ENCODED_MEDIA_URL_RE.test(text))) return;
      extractUrlsFromText(text, source, label, "", responseUrl, meta);
    } catch {
      // Realtime message sniffing is best-effort and must not affect playback.
    }
  }

  function patchWebSocketMessages() {
    try {
      const OriginalWebSocket = window.WebSocket;
      if (typeof OriginalWebSocket !== "function" || OriginalWebSocket.__learnNotePatched) return;
      function LearnNoteWebSocket(...args) {
        const pageMeta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
        const socket = new OriginalWebSocket(...args);
        const endpoint = normalizeUrl(args[0] || "");
        try {
          socket.addEventListener?.("message", event => {
            inspectRealtimeMessageData(event?.data, "pageHookWebSocket", "websocket message", endpoint, pageMeta);
          });
        } catch {
          // Some WebSocket wrappers do not expose EventTarget methods.
        }
        return socket;
      }
      try {
        Object.setPrototypeOf(LearnNoteWebSocket, OriginalWebSocket);
        LearnNoteWebSocket.prototype = OriginalWebSocket.prototype;
      } catch {
        // Static constants are inherited only when the runtime allows prototype changes.
      }
      Object.defineProperty(LearnNoteWebSocket, "__learnNotePatched", { value: true });
      window.WebSocket = LearnNoteWebSocket;
    } catch {
      // Locked or cross-realm constructors should not block other hooks.
    }
  }

  function patchEventSourceMessages() {
    try {
      const OriginalEventSource = window.EventSource;
      if (typeof OriginalEventSource !== "function" || OriginalEventSource.__learnNotePatched) return;
      function LearnNoteEventSource(...args) {
        const pageMeta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
        const source = new OriginalEventSource(...args);
        const endpoint = normalizeUrl(args[0] || "");
        try {
          source.addEventListener?.("message", event => {
            inspectRealtimeMessageData(event?.data, "pageHookEventSource", "eventsource message", endpoint, pageMeta);
          });
        } catch {
          // Some EventSource wrappers do not expose EventTarget methods.
        }
        return source;
      }
      try {
        Object.setPrototypeOf(LearnNoteEventSource, OriginalEventSource);
        LearnNoteEventSource.prototype = OriginalEventSource.prototype;
      } catch {
        // A plain wrapper still preserves normal constructor behavior.
      }
      Object.defineProperty(LearnNoteEventSource, "__learnNotePatched", { value: true });
      window.EventSource = LearnNoteEventSource;
    } catch {
      // Locked or missing EventSource constructors are safe to ignore.
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

  function inspectCacheResponse(response, request, label, pageMeta = {}) {
    if (!response || typeof response !== "object") return;
    const url = response.url || requestUrl(request);
    const mime = response.headers?.get?.("content-type") || "";
    const meta = fetchResponseMeta(response, url, normalizeRequestHeaderMap(request?.headers));
    Object.assign(meta, pageMeta);
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
      const requestPageUrl = currentPageUrl();
      const requestPageIdentity = currentPageIdentity();
      const method = fetchRequestMethod(args[0], args[1] || {});
      const requestBody = await fetchRequestBodyFromInput(method, args[0], args[1] || {});
      const response = await originalFetch.apply(this, args);
      const url = response.url || requestUrl(args[0]);
      const mime = response.headers?.get?.("content-type") || "";
      const meta = fetchResponseMeta(response, url, fetchRequestHeaders(args[0], args[1] || {}), method, requestBody);
      meta.page_url = requestPageUrl;
      meta.page_identity = requestPageIdentity;
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
        inspectBinaryTextPayload(buffer, "pageHookBody", "fetch arrayBuffer", mime, this.url || "", responseMeta(this, this.url || ""));
      } catch {
        // Keep the host page's response consumption behavior unchanged.
      }
      return buffer;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.bytes) {
    const originalResponseBytes = Response.prototype.bytes;
    Response.prototype.bytes = async function (...args) {
      const bytes = await originalResponseBytes.apply(this, args);
      try {
        const mime = this.headers?.get?.("content-type") || "";
        const meta = responseBlobSourceMeta(this, this.url || "", mime, "pageHookBlob", "fetch bytes source");
        rememberBlobPartObject(bytes, meta);
        inspectBinaryTextPayload(bytes, "pageHookBody", "fetch bytes", mime, this.url || "", responseMeta(this, this.url || ""));
      } catch {
        // Keep the host page's response consumption behavior unchanged.
      }
      return bytes;
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
        const pageMeta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
        const response = await originalMatch.call(this, request, ...rest);
        try {
          inspectCacheResponse(response, request, "cache match", pageMeta);
        } catch {
          // Cache reads must stay transparent.
        }
        return response;
      };
    }
    if (typeof cache.matchAll === "function") {
      const originalMatchAll = cache.matchAll;
      cache.matchAll = async function (request, ...rest) {
        const pageMeta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
        const responses = await originalMatchAll.call(this, request, ...rest);
        try {
          for (const response of responses || []) inspectCacheResponse(response, request, "cache matchAll", pageMeta);
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
      const pageMeta = { page_url: currentPageUrl(), page_identity: currentPageIdentity() };
      const response = await originalCachesMatch.call(this, request, ...rest);
      try {
        inspectCacheResponse(response, request, "cache storage match", pageMeta);
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

  if (typeof window.Blob !== "undefined" && window.Blob.prototype && !window.Blob.prototype.__learnNoteBlobReadersPatched) {
    const blobPrototype = window.Blob.prototype;

    if (typeof blobPrototype.arrayBuffer === "function") {
      const originalBlobArrayBuffer = blobPrototype.arrayBuffer;
      blobPrototype.arrayBuffer = async function (...args) {
        const buffer = await originalBlobArrayBuffer.apply(this, args);
        try {
          rememberBlobPartObject(buffer, blobPartMeta(this));
        } catch {
          // Blob reader hooks must not affect host page media pipelines.
        }
        return buffer;
      };
    }

    if (typeof blobPrototype.stream === "function") {
      const originalBlobStream = blobPrototype.stream;
      blobPrototype.stream = function (...args) {
        const stream = originalBlobStream.apply(this, args);
        try {
          rememberStreamObject(stream, blobPartMeta(this));
        } catch {
          // Keep Blob.stream() transparent for pages with custom stream handling.
        }
        return stream;
      };
    }

    if (typeof blobPrototype.bytes === "function") {
      const originalBlobBytes = blobPrototype.bytes;
      blobPrototype.bytes = async function (...args) {
        const bytes = await originalBlobBytes.apply(this, args);
        try {
          rememberBlobPartObject(bytes, blobPartMeta(this));
        } catch {
          // Keep experimental Blob.bytes() behavior unchanged.
        }
        return bytes;
      };
    }

    try {
      Object.defineProperty(blobPrototype, "__learnNoteBlobReadersPatched", { value: true });
    } catch {
      blobPrototype.__learnNoteBlobReadersPatched = true;
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
        if (!mediaSourcePageIdentity.has(this)) {
          mediaSourcePageIdentity.set(this, { page_url: currentPageUrl(), page_identity: currentPageIdentity() });
        }
        sourceBufferMediaSource.set(sourceBuffer, this);
        sourceBufferMimeByObject.set(sourceBuffer, String(args[0] || ""));
      } catch {
        // Some SourceBuffer implementations are not extensible WeakMap keys.
      }
      return sourceBuffer;
    };
  }

  function rememberSourceBufferAppend(sourceBuffer, value, label = "MSE appendBuffer") {
    const evidence = appendBufferEvidence(sourceBuffer, value);
    const meta = blobPartMeta(value);
    const mediaSource = sourceBufferMediaSource.get(sourceBuffer);
    if (meta) {
      rememberMediaSourceMeta(mediaSource, { ...meta, ...evidence });
      return;
    }
    const blobUrl = mediaSourceUrlByObject.get(mediaSource);
    if (!blobUrl) return;
    emit([{
      url: blobUrl,
      source: "pageHookMediaSourceAppend",
      kind: evidence.mse_append_detected_kind || "blob",
      mime: evidence.mse_append_mime || "",
      label,
      blob_url: blobUrl,
      playback_match: "blob-source",
      score: evidence.mse_append_detected_kind === "video" || evidence.mse_append_detected_kind === "fragment" ? 82 : evidence.mse_append_detected_kind === "audio" ? 40 : 72,
      ...(mediaSourcePageIdentity.get(mediaSource) || {}),
      ...evidence
    }]);
  }

  if (typeof window.SourceBuffer !== "undefined" && window.SourceBuffer.prototype?.appendBuffer) {
    const originalAppendBuffer = window.SourceBuffer.prototype.appendBuffer;
    window.SourceBuffer.prototype.appendBuffer = function (...args) {
      try {
        rememberSourceBufferAppend(this, args[0], "MSE appendBuffer");
      } catch {
        // Keep MSE playback untouched if a page uses unusual buffer wrappers.
      }
      return originalAppendBuffer.apply(this, args);
    };
  }

  if (typeof window.SourceBuffer !== "undefined" && window.SourceBuffer.prototype?.appendBufferAsync) {
    const originalAppendBufferAsync = window.SourceBuffer.prototype.appendBufferAsync;
    window.SourceBuffer.prototype.appendBufferAsync = function (...args) {
      try {
        rememberSourceBufferAppend(this, args[0], "MSE appendBufferAsync");
      } catch {
        // Keep experimental async MSE playback untouched.
      }
      return originalAppendBufferAsync.apply(this, args);
    };
  }

  if (typeof window.SourceBuffer !== "undefined" && window.SourceBuffer.prototype?.changeType) {
    const originalChangeType = window.SourceBuffer.prototype.changeType;
    window.SourceBuffer.prototype.changeType = function (...args) {
      try {
        sourceBufferMimeByObject.set(this, String(args[0] || ""));
      } catch {
        // Some SourceBuffer implementations are not extensible WeakMap keys.
      }
      return originalChangeType.apply(this, args);
    };
  }

  if (typeof window.XMLHttpRequest === "function") {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__learnNoteUrl = url;
      this.__learnNoteMethod = method;
      this.__learnNotePageUrl = currentPageUrl();
      this.__learnNotePageIdentity = currentPageIdentity();
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
      try {
        this.__learnNoteRequestBody = requestBodyFromValue(String(this.__learnNoteMethod || "GET").toUpperCase(), args[0]);
      } catch {
        this.__learnNoteRequestBody = {};
      }
      this.addEventListener("loadend", () => {
        const url = this.responseURL || this.__learnNoteUrl || "";
        const mime = this.getResponseHeader?.("content-type") || "";
        const meta = xhrResponseMeta(this, url);
        emit([applyResponseMeta({ url, source: "pageHookRequest", label: "xhr", mime }, meta)]);
        if (typeof Blob !== "undefined" && this.response instanceof Blob) {
          rememberBlobObject(this.response, applyResponseMeta(blobMeta(url, this.response.type || mime, "pageHookBlob", "xhr blob source"), meta));
        }
        if (typeof ArrayBuffer !== "undefined" && this.response instanceof ArrayBuffer) {
          rememberBlobPartObject(this.response, applyResponseMeta(blobMeta(url, mime, "pageHookBlob", "xhr arrayBuffer source"), meta));
          inspectBinaryTextPayload(this.response, "pageHookBody", "xhr arrayBuffer", mime, url, meta);
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
  patchWebSocketMessages();
  patchEventSourceMessages();
  installLateGlobalConfigWatchers();
  installLatePlayerGlobalWatchers();
  scanGlobalConfig();
  setTimeout(patchKnownPlayerLibraries, 100);
  setTimeout(scanGlobalConfig, 500);
  setTimeout(patchKnownPlayerLibraries, 500);
  setTimeout(patchKnownPlayerLibraries, 1500);
  setTimeout(scanGlobalConfig, 2000);
  setTimeout(patchKnownPlayerLibraries, 3000);

  if (window.history) {
    for (const methodName of ["pushState", "replaceState"]) {
      const original = window.history[methodName];
      if (typeof original !== "function") continue;
      window.history[methodName] = function (...args) {
        const result = original.apply(this, args);
        resetForNavigation();
        return result;
      };
    }
  }
  window.addEventListener("popstate", resetForNavigation);
  window.addEventListener("hashchange", resetForNavigation);

  window.addEventListener("message", event => {
    if (event.source !== window || event.data?.source !== "learnnote-content-ready") return;
    scanGlobalConfig();
    post(bufferedResources, drmSignals, true);
  });
})();
