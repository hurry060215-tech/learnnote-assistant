(function () {
  if (window.__learnNotePageHookInstalled) return;
  window.__learnNotePageHookInstalled = true;

  const MEDIA_URL_RE = /(?:https?:)?\/\/[^\s"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:\/[^\s"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+\/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?/gi;
  const MEDIA_HINT_RE = /\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:[?#]|["'\s<>]|$)/i;
  const TEXT_TYPE_RE = /json|text|javascript|mpegurl|dash\+xml|xml|x-mpegurl/i;
  const JSON_MEDIA_KEY_RE = /(url|src|file|play|media|video|stream|source|hls|m3u8|dash|mpd|subtitle|caption)/i;
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
      if (decoded && decoded !== raw) values.unshift(decoded);
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

  function collectJsonMediaUrls(node, source, label, keys = [], parent = null, output = [], seen = new Set(), visited = new WeakSet()) {
    if (!node || output.length >= 40) return output;
    if (Array.isArray(node)) {
      for (let index = 0; index < Math.min(node.length, 120); index += 1) {
        let child = null;
        try {
          child = node[index];
        } catch {
          child = null;
        }
        collectJsonMediaUrls(child, source, label, [...keys, String(index)], node, output, seen, visited);
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
      if (typeof value === "string" && !JSON_MEDIA_KEY_RE.test(key) && keys.length < 12) {
        for (const candidateText of decodedMediaValues(value)) {
          const trimmed = String(candidateText || "").trim();
          if (!trimmed || trimmed.length > MAX_TEXT_BYTES) continue;
          if (!"{[".includes(trimmed[0]) && !MEDIA_HINT_RE.test(trimmed) && !JSON_MEDIA_KEY_RE.test(trimmed)) continue;
          const nested = collectMediaUrlsFromText(trimmed, source, `${label} nested ${nextKeys.slice(-3).join("/")}`, "", seen);
          output.push(...nested.slice(0, Math.max(0, 40 - output.length)));
          if (output.length >= 40) break;
        }
      }
      if (value && typeof value === "object") {
        collectJsonMediaUrls(value, source, label, nextKeys, node, output, seen, visited);
      }
      if (output.length >= 40) break;
    }
    return output;
  }

  function extractJsonMediaUrls(text, source, label, seen = new Set()) {
    const trimmed = String(text || "").trim();
    if (!trimmed || !"{[".includes(trimmed[0])) return [];
    try {
      return collectJsonMediaUrls(JSON.parse(trimmed), source, label, [], null, [], seen);
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

  function collectMediaUrlsFromText(text, source, label, mime = "", seen = new Set()) {
    if (!text) return [];
    const resources = extractJsonMediaUrls(text, source, label, seen);
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
    return resources;
  }

  function collectResponseTextResources(url, text, source, label, mime = "") {
    const seen = new Set();
    const resources = collectMediaUrlsFromText(text, source, label, mime, seen);
    const kind = manifestKindFromText(text, mime);
    const normalizedUrl = normalizeUrl(url);
    if (kind !== "unknown" && normalizedUrl && !seen.has(normalizedUrl)) {
      resources.unshift({
        url: normalizedUrl,
        source,
        kind,
        mime: mime || mimeForKind(kind),
        label: `${label} manifest`,
        score: 99
      });
    }
    return resources;
  }

  function extractUrlsFromText(text, source, label, mime = "", responseUrl = "") {
    emit(collectResponseTextResources(responseUrl, text, source, label, mime));
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

  function sourceCandidates(value, output = []) {
    if (!value) return output;
    if (typeof value === "string") {
      output.push(value);
      return output;
    }
    if (Array.isArray(value)) {
      for (const item of value) sourceCandidates(item, output);
      return output;
    }
    if (typeof value === "object") {
      for (const key of ["src", "url", "file", "source", "manifestUri"]) {
        try {
          if (typeof value[key] === "string") output.push(value[key]);
        } catch {
          // Some player source objects expose throwing getters.
        }
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

  function patchKnownPlayerLibraries() {
    patchHlsJs();
    patchDashJs();
    patchShakaPlayer();
    patchVideoJs();
  }

  function scanGlobalConfig() {
    try {
      emit(collectGlobalConfigResources());
    } catch {
      // Global player objects are best-effort evidence only.
    }
  }

  function shouldInspectResponse(response) {
    const type = response.headers?.get?.("content-type") || "";
    const length = Number(response.headers?.get?.("content-length") || 0);
    return shouldInspectTextPayload(response.url || "", type, length);
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
        try {
          response.clone().text()
            .then(text => extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch body", mime, url))
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
        const meta = blobMeta(this.url || "", mime, "pageHookBlob", "fetch blob source");
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
        emit(collectJsonMediaUrls(data, "pageHookBody", "fetch json"));
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
          extractUrlsFromText(String(text || "").slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch text", mime, url);
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
        if (!shouldInspectTextPayload(url, mime, 0)) return;
        if (this.responseType === "json") {
          if (this.response && typeof this.response === "object") {
            emit(collectJsonMediaUrls(this.response, "pageHookBody", "xhr json"));
          } else if (typeof this.response === "string") {
            extractUrlsFromText(this.response.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr json", mime, url);
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
        extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr body", mime, url);
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
  patchKnownPlayerLibraries();
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
