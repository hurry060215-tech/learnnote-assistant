const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;
const STATIC_MEDIA_ATTRS = [
  "src",
  "href",
  "data-src",
  "data-url",
  "data-video-url",
  "data-play-url",
  "data-media-url",
  "data-stream-url",
  "data-hls-url",
  "data-m3u8",
  "data-mpd",
  "data-file",
  "data-source",
  "data-sources",
  "value"
];
const STATIC_MEDIA_SELECTOR = STATIC_MEDIA_ATTRS.map(name => `[${name}]`).join(",");
const STATIC_FIELD_RE = /(["']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}["']?)\s*[:=]\s*["']([^"'<>\\\s]{4,})["']/gi;
const STATIC_MEDIA_KEY_RE = /(url|src|file|play|media|video|stream|source|hls|m3u8|dash|mpd|subtitle|caption)/i;
const VISIBLE_SUBTITLE_HINT_RE = /(subtitle|subtitles|caption|captions|closed.?caption|texttrack|danmu|danmaku|barrage|\bcc\b|字幕|弹幕)/i;
const VISIBLE_SUBTITLE_ROLE_RE = /^(log|status|marquee)$/i;
const B64ISH_RE = /^[A-Za-z0-9+/_=-]{16,}$/;
const boundVideos = new WeakSet();
const hookResources = [];
const drmSignals = [];
const drmByVideo = new WeakMap();
const observedMutationRoots = new WeakSet();
const DEEP_QUERY_LIMIT = 2500;
let pendingPushTimer = 0;
let lastPushAt = 0;
let lastSignature = "";
let watchersStarted = false;

function classify(url, mime = "") {
  const lower = String(url || "").toLowerCase();
  const type = String(mime || "").toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (FRAGMENT_RE.test(lower) && inferManifestUrl(url)) return "fragment";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || MEDIA_RE.test(lower)) return "video";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower)) return "subtitle";
  if (FRAGMENT_RE.test(lower)) return "fragment";
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
  else if (kind === "fragment") value += 15;
  else if (kind === "subtitle") value += 60;
  else if (kind === "blob") value += 5;
  if (source === "dom") value += 8;
  if (source === "activeVideo") value += 16;
  if (String(source || "").startsWith("pageHook")) value += 12;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
}

function absoluteUrl(url) {
  if (!url) return "";
  if (url.startsWith("blob:")) return url;
  try {
    return new URL(url, location.href).href;
  } catch {
    return "";
  }
}

function decodedValues(value) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  const values = [raw.replace(/&amp;/g, "&").replace(/\\\//g, "/")];
  try {
    const decoded = decodeURIComponent(values[0]);
    if (decoded && decoded !== values[0]) values.unshift(decoded);
  } catch {
    // Keep the raw value when percent decoding is invalid.
  }
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
        (MEDIA_RE.test(decoded) || SUBTITLE_RE.test(decoded) || decoded.includes(".m3u8") || decoded.includes(".mpd") || looksLikeMediaValue(decoded, "media"))
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
  if (text.includes("video") || text.includes("mp4") || text.includes("media") || text.includes("play") || text.includes("stream")) return "video/mp4";
  return "";
}

function looksLikeMediaValue(value, hint = "") {
  const text = String(value || "").trim();
  if (text.length < 4 || /\s/.test(text)) return false;
  if (MEDIA_RE.test(text) || SUBTITLE_RE.test(text) || text.includes(".m3u8") || text.includes(".mpd")) return true;
  if (/%2f|%3a|%3f|%3d|%26/i.test(text)) return STATIC_MEDIA_KEY_RE.test(hint) || MEDIA_RE.test(decodeURIComponentSafe(text));
  if (/^(https?:)?\/\//i.test(text) || text.startsWith("/")) return STATIC_MEDIA_KEY_RE.test(hint);
  return text.includes("/") && /[?=&]|api|play|media|video|stream|m3u8|mpd|hls|dash/i.test(text) && STATIC_MEDIA_KEY_RE.test(hint);
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
    if (!looksLikeMediaValue(candidate, hint || label)) continue;
    const item = resource(candidate, source, label, mimeFromHint(`${hint} ${label}`), video, isMainVideo, playbackMatch);
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
  return "unknown";
}

function performanceScore(kind, url) {
  let value = 0;
  if (kind === "hls" || kind === "dash") value = 95;
  else if (kind === "video") value = 88;
  else if (kind === "subtitle") value = 65;
  else if (kind === "fragment") value = 20;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
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
      request_headers: { ...(existing.request_headers || {}), ...(normalized.request_headers || {}) }
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

function collectStaticAttributeResources() {
  const resources = [];
  for (const element of deepQuerySelectorAll(STATIC_MEDIA_SELECTOR, document, 1200)) {
    const tag = String(element.tagName || "element").toLowerCase();
    for (const attr of STATIC_MEDIA_ATTRS) {
      const value = readAttribute(element, attr);
      if (!value) continue;
      const item = resourceFromHint(value, "domHint", `${tag} ${attr}`, attr);
      if (item) resources.push(item);
    }
  }
  return resources;
}

function collectInlineScriptResources() {
  const resources = [];
  const seen = new Set();
  for (const script of deepQuerySelectorAll("script", document, 400)) {
    const text = String(script.textContent || "").slice(0, 200000);
    if (!text || !STATIC_MEDIA_KEY_RE.test(text)) continue;
    STATIC_FIELD_RE.lastIndex = 0;
    for (const match of text.matchAll(STATIC_FIELD_RE)) {
      const key = String(match[1] || "").replace(/^["']|["']$/g, "");
      if (!STATIC_MEDIA_KEY_RE.test(key)) continue;
      const item = resourceFromHint(match[2], "scriptHint", `script ${key}`, key);
      if (!item || seen.has(item.url)) continue;
      seen.add(item.url);
      item.score = Math.max(item.score || 0, item.kind === "hls" || item.kind === "dash" ? 96 : item.kind === "video" ? 86 : 62);
      resources.push(item);
      if (resources.length >= 40) return resources;
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

function pickMainVideo(videos = collectVideos()) {
  const playing = videos.find(({ video }) => !video.paused && !video.ended && video.readyState >= 2);
  if (playing) return playing;
  return videos
    .filter(({ video }) => video.currentSrc || video.src || video.querySelector("source[src]"))
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
  return {
    src: absoluteUrl(video.currentSrc || video.src),
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

function collectVisibleSubtitleCues(limit = 200) {
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
  return cues;
}

function collectBrowserSubtitles(limit = 1200) {
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

function collectDomResources() {
  const resources = [...collectStaticAttributeResources(), ...collectInlineScriptResources()];
  const videos = collectVideos();
  const main = pickMainVideo(videos);
  for (const { video, index } of videos) {
    const isMain = main?.video === video;
    resources.push(resource(video.currentSrc || video.src, "activeVideo", `当前视频 #${index + 1}`, video.type || "", video, isMain, isMain ? "exact-src" : ""));
    for (const source of video.querySelectorAll("source")) {
      resources.push(resource(source.src, "dom", `video source #${index + 1}`, source.type || "", video, isMain, isMain ? "source-element" : ""));
    }
    for (const track of video.querySelectorAll("track[src]")) {
      const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
      resources.push(resource(track.src, "subtitleTrack", label || `subtitle #${index + 1}`, "text/vtt", video, isMain));
    }
  }
  for (const source of deepQuerySelectorAll("source[src]")) {
    resources.push(resource(source.src, "dom", "source", source.type || ""));
  }
  for (const track of deepQuerySelectorAll("track[src]")) {
    const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
    resources.push(resource(track.src, "subtitleTrack", label || "subtitle", "text/vtt"));
  }
  for (const iframe of deepQuerySelectorAll("iframe[src]")) {
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
    if (kind !== "unknown" || /m3u8|mpd|video|media|subtitle|caption/i.test(name)) {
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

function collectPageData() {
  const all = [...collectDomResources(), ...collectPerformanceResources(), ...collectHookResources()];
  const byUrl = new Map();
  for (const item of all) {
    const previous = byUrl.get(item.url);
    if (!previous || item.score > previous.score) byUrl.set(item.url, item);
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
    resources: [...byUrl.values()].sort((a, b) => b.score - a.score).slice(0, 30)
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
  for (const { video } of collectVideos()) bindVideo(video);
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
    observeOpenShadowRoots(observer);
    for (const mutation of mutations) {
      if (mutation.type === "attributes") {
        const target = mutation.target;
        if (target?.matches?.("video,source,track,iframe")) relevant = true;
      }
      for (const node of mutation.addedNodes || []) {
        if (isMediaNode(node)) {
          relevant = true;
        }
      }
    }
    if (!relevant) return;
    bindVideos();
    schedulePush(250, true);
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
        return performanceKind(entry) !== "unknown" || /m3u8|mpd|video|media|subtitle|caption/i.test(name);
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
