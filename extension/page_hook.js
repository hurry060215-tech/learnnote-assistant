(function () {
  if (window.__learnNotePageHookInstalled) return;
  window.__learnNotePageHookInstalled = true;

  const MEDIA_URL_RE = /(?:https?:)?\/\/[^\s"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:\/[^\s"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+\/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?/gi;
  const MEDIA_HINT_RE = /\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:[?#]|["'\s<>]|$)/i;
  const TEXT_TYPE_RE = /json|text|javascript|mpegurl|dash\+xml|xml|x-mpegurl/i;
  const JSON_MEDIA_KEY_RE = /(url|src|file|play|media|video|stream|source|hls|m3u8|dash|mpd|subtitle|caption)/i;
  const JSON_MIME_KEY_RE = /(mime|type|format|content.?type|media.?type)/i;
  const TEXT_MEDIA_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*["']([^"'<>\\\s]{4,})["']/gi;
  const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;
  const MAX_TEXT_BYTES = 2 * 1024 * 1024;
  const MAX_BLOB_URLS = 80;
  const bufferedResources = [];
  const drmSignals = [];
  const blobSourceByObject = new WeakMap();
  const blobPartSourceByObject = new WeakMap();
  const blobSourceByUrl = new Map();
  const blobUrlOrder = [];
  const streamSourceByObject = new WeakMap();
  const streamReaderSourceByObject = new WeakMap();
  const mediaSourceMetaByObject = new WeakMap();
  const mediaSourceUrlByObject = new WeakMap();
  const sourceBufferMediaSource = new WeakMap();

  function normalizeUrl(raw) {
    if (!raw) return "";
    const cleaned = String(raw)
      .replace(/\\\//g, "/")
      .replace(/\\u0026/g, "&")
      .replace(/&amp;/g, "&")
      .trim();
    try {
      return new URL(cleaned, location.href).href;
    } catch {
      return "";
    }
  }

  function mediaKind(url, mime = "") {
    const lower = String(url || "").toLowerCase();
    const type = String(mime || "").toLowerCase();
    if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
    if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
    if (type.includes("text/vtt") || type.includes("subrip") || /\.(vtt|srt|ass|ssa)(\?|#|$)/i.test(lower)) return "subtitle";
    if (type.includes("video/") || /\.(mp4|m4v|webm|mov|mkv)(\?|#|$)/i.test(lower)) return "video";
    return "unknown";
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
          blob_url: item.blob_url || existing.blob_url || ""
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

  function looksLikeJsonUrlCandidate(value) {
    const text = String(value || "").trim();
    if (text.length < 4 || /\s/.test(text)) return false;
    if (/^(https?:)?\/\//i.test(text)) return true;
    if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return true;
    if (text.startsWith("/")) return true;
    return text.includes("/") && /[?=&]|api|play|media|video|stream|m3u8|mpd|hls|dash/i.test(text);
  }

  function decodedMediaValues(value) {
    const raw = String(value || "").trim();
    if (!raw) return [];
    const values = [raw];
    try {
      const decoded = decodeURIComponent(raw);
      if (decoded && decoded !== raw) values.push(decoded);
    } catch {
      // Keep the raw value when percent decoding is invalid.
    }

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
          (looksLikeJsonUrlCandidate(text) || MEDIA_HINT_RE.test(text))
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

  function collectJsonMediaUrls(node, source, label, keys = [], parent = null, output = [], seen = new Set()) {
    if (!node || output.length >= 40) return output;
    if (Array.isArray(node)) {
      for (let index = 0; index < Math.min(node.length, 120); index += 1) {
        collectJsonMediaUrls(node[index], source, label, [...keys, String(index)], node, output, seen);
        if (output.length >= 40) break;
      }
      return output;
    }
    if (typeof node !== "object") return output;
    for (const [key, value] of Object.entries(node)) {
      const nextKeys = [...keys, key];
      if (typeof value === "string" && JSON_MEDIA_KEY_RE.test(key)) {
        for (const candidateValue of decodedMediaValues(value)) {
          if (!looksLikeJsonUrlCandidate(candidateValue)) continue;
          const url = normalizeUrl(candidateValue);
          if (url && !seen.has(url)) {
            const { kind, mime } = kindFromJsonContext(nextKeys, url, node);
            if (kind !== "unknown") {
              seen.add(url);
              output.push({
                url,
                source,
                kind,
                mime,
                label: `${label} json ${nextKeys.slice(-3).join("/")}`,
                score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
              });
              break;
            }
          }
        }
      }
      if (value && typeof value === "object") {
        collectJsonMediaUrls(value, source, label, nextKeys, node, output, seen);
      }
      if (output.length >= 40) break;
    }
    return output;
  }

  function extractJsonMediaUrls(text, source, label) {
    const trimmed = String(text || "").trim();
    if (!trimmed || !"{[".includes(trimmed[0])) return [];
    try {
      return collectJsonMediaUrls(JSON.parse(trimmed), source, label);
    } catch {
      return [];
    }
  }

  function extractFieldMediaUrls(text, source, label, seen = new Set()) {
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
        output.push({
          url,
          source,
          kind,
          mime,
          label: `${label} field ${key}`,
          score: kind === "hls" || kind === "dash" ? 97 : kind === "video" ? 89 : 64
        });
        break;
      }
      if (output.length >= 40) break;
    }
    return output;
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

  function extractUrlsFromText(text, source, label, mime = "") {
    if (!text) return;
    const resources = extractJsonMediaUrls(text, source, label);
    const seen = new Set(resources.map(item => item.url));
    resources.push(...extractFieldMediaUrls(text, source, label, seen));
    if (MEDIA_HINT_RE.test(text)) {
      for (const match of text.matchAll(MEDIA_URL_RE)) {
        const url = normalizeUrl(match[0]);
        if (!url || seen.has(url)) continue;
        resources.push({ url, source, label, mime });
        seen.add(url);
        if (resources.length >= 40) break;
      }
    }
    emit(resources);
  }

  function shouldInspectResponse(response) {
    const type = response.headers?.get?.("content-type") || "";
    const length = Number(response.headers?.get?.("content-length") || 0);
    if (length && length > MAX_TEXT_BYTES) return false;
    return TEXT_TYPE_RE.test(type);
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

  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
      const response = await originalFetch.apply(this, args);
      const url = response.url || requestUrl(args[0]);
      const mime = response.headers?.get?.("content-type") || "";
      emit([{ url, source: "pageHookRequest", label: "fetch", mime }]);
      try {
        rememberStreamObject(response.body, blobMeta(url, mime, "pageHookStream", "fetch stream source"));
      } catch {
        // Accessing body can throw for some synthetic responses.
      }
      if (shouldInspectResponse(response)) {
        response.clone().text()
          .then(text => extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch body", mime))
          .catch(() => {});
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
        const meta = blobMeta(this.url || "", mime, "pageHookBlob", "fetch blob source");
        rememberBlobObject(blob, meta);
      } catch {
        // Keep the host page's response consumption behavior unchanged.
      }
      return blob;
    };
  }

  if (typeof window.Response !== "undefined" && Response.prototype?.arrayBuffer) {
    const originalResponseArrayBuffer = Response.prototype.arrayBuffer;
    Response.prototype.arrayBuffer = async function (...args) {
      const buffer = await originalResponseArrayBuffer.apply(this, args);
      try {
        const mime = this.headers?.get?.("content-type") || "";
        const meta = blobMeta(this.url || "", mime, "pageHookBlob", "fetch arrayBuffer source");
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
        rememberStreamReader(reader, streamMeta(this));
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
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__learnNoteUrl = url;
      this.__learnNoteMethod = method;
      return originalOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      this.addEventListener("loadend", () => {
        const url = this.responseURL || this.__learnNoteUrl || "";
        const mime = this.getResponseHeader?.("content-type") || "";
        emit([{ url, source: "pageHookRequest", label: "xhr", mime }]);
        if (typeof Blob !== "undefined" && this.response instanceof Blob) {
          const meta = blobMeta(url, this.response.type || mime, "pageHookBlob", "xhr blob source");
          rememberBlobObject(this.response, meta);
        }
        if (typeof ArrayBuffer !== "undefined" && this.response instanceof ArrayBuffer) {
          const meta = blobMeta(url, mime, "pageHookBlob", "xhr arrayBuffer source");
          rememberBlobPartObject(this.response, meta);
        }
        if (!TEXT_TYPE_RE.test(mime)) return;
        if (this.responseType && this.responseType !== "text") return;
        let text = "";
        try {
          text = typeof this.response === "string" ? this.response : this.responseText;
        } catch {
          text = "";
        }
        if (typeof text !== "string") return;
        extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr body", mime);
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

  window.addEventListener("message", event => {
    if (event.source !== window || event.data?.source !== "learnnote-content-ready") return;
    post(bufferedResources, drmSignals);
  });
})();
