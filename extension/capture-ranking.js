// Pure supplied-data projection: no Chrome API, storage, page hook or network access.
(function installModule(global) {
  "use strict";
  const { PLAYBACK_ENDPOINT_RE, classify, isSubtitleEndpointUrl, urlHost, normalizedFrameUrl } = global.LearnNoteCaptureClassification;

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
  if (resource.kind === "subtitle" || isSubtitleEndpointUrl(resource.url || "")) return 0;
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

function isImageResource(resource = {}) {
  return /^image\//i.test(String(resource.mime || resource.headers?.["content-type"] || "")) ||
    resource.kind === "image" ||
    /\.(?:avif|webp|jpe?g|png|gif|bmp|svg)(?:@[^/?#]*)?(?:[?#]|$)/i.test(String(resource.url || ""));
}

function isLearningFrameUrl(value = "") {
  return /(?:^|\.)chaoxing\.com$|(?:^|\.)xuexitong\.com$/i.test(urlHost(value));
}

function isActivityOrAdUrl(value = "") {
  const url = String(value || "");
  if (!url || isLearningFrameUrl(url)) return false;
  let host = "";
  let path = "";
  try {
    const parsed = new URL(url);
    host = parsed.hostname;
    path = parsed.pathname;
  } catch {
    return false;
  }
  return /(?:^|\.)obeebee\.com$/i.test(host) ||
    /(?:^|\.)activity\.hdslb\.com$/i.test(host) ||
    (/(?:^|\.)bilibili\.com$/i.test(host) && /\/(?:blackboard|activity|festival)(?:\/|$)/i.test(path)) ||
    /(?:^|[._-])ads?(?:[._-]|$)|advert/i.test(host) ||
    /\/(?:ads?|advert(?:isement)?|promo)(?:\/|$)/i.test(path);
}

function resourceContextUrl(resource = {}) {
  return resource.frame_url || resource.page_url || resource.initiator || resource.url || "";
}

function resourceVisibilityRank(resource = {}) {
  if (resource.frame_visible === false || resource.is_visible === false || ["hidden", "offscreen"].includes(resource.visibility)) return 0;
  if (resource.is_visible === true || resource.frame_visible === true || resource.visibility === "visible") return 2;
  return 1;
}

function isShortDecorativeVideo(resource = {}) {
  const duration = Number(resource.duration || 0);
  const area = Number(resource.visible_area || resource.frame_visible_area || 0);
  return duration > 0 && duration <= 45 && area > 0 && area <= 640 * 360;
}

function resourceContextRank(resource = {}) {
  if (isActivityOrAdUrl(resourceContextUrl(resource))) return 0;
  if (isShortDecorativeVideo(resource)) return 1;
  return 2;
}

function playbackSessionRank(resource = {}, page = {}, tab = {}) {
  if (resource.source === "activeVideo") return 3;
  const contextUrls = new Set([
    tab.url,
    page.page_url,
    page.active_video?.frame_url,
    ...(page.frames || []).map(frame => frame.page_url)
  ].map(normalizedFrameUrl).filter(Boolean));
  const resourceUrls = [resource.frame_url, resource.page_url]
    .map(normalizedFrameUrl)
    .filter(Boolean);
  if (resourceUrls.some(url => contextUrls.has(url))) return 3;

  const sameOriginButDifferentDocument = resourceUrls.some(resourceUrl => {
    try {
      const resourceOrigin = new URL(resourceUrl).origin;
      return [...contextUrls].some(contextUrl => new URL(contextUrl).origin === resourceOrigin);
    } catch {
      return false;
    }
  });
  if (sameOriginButDifferentDocument) return 0;

  const activeFrameId = page.active_video?.frame_id;
  if (activeFrameId !== null && activeFrameId !== undefined && resource.frame_id === activeFrameId) return 2;
  return 1;
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
    Number(a.playback_session_rank || 0),
    resourceContextRank(a),
    resourceVisibilityRank(a),
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
    Number(b.playback_session_rank || 0),
    resourceContextRank(b),
    resourceVisibilityRank(b),
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
  merged.visibility = incoming.visibility !== "unknown" ? incoming.visibility : previous.visibility || "unknown";
  merged.is_visible = incoming.is_visible ?? previous.is_visible ?? null;
  merged.visible_area = incoming.visible_area ?? previous.visible_area ?? null;
  merged.rendered_width = incoming.rendered_width ?? previous.rendered_width ?? null;
  merged.rendered_height = incoming.rendered_height ?? previous.rendered_height ?? null;
  merged.frame_visible = incoming.frame_visible ?? previous.frame_visible ?? null;
  merged.frame_visibility = incoming.frame_visibility !== "unknown" ? incoming.frame_visibility : previous.frame_visibility || "unknown";
  merged.frame_visible_area = incoming.frame_visible_area ?? previous.frame_visible_area ?? null;
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


  global.LearnNoteCaptureRanking = Object.freeze({
    scoreKind,
    scoreResource,
    isDownloadableKind,
    hasReplayableRequestBody,
    playableEndpointRank,
    isDirectResourceCandidate,
    isPlayableMediaEvidenceKind,
    kindRank,
    effectiveKindRank,
    playableEndpointScore,
    isImageResource,
    isLearningFrameUrl,
    isActivityOrAdUrl,
    resourceContextUrl,
    resourceVisibilityRank,
    isShortDecorativeVideo,
    resourceContextRank,
    playbackSessionRank,
    sourceRank,
    playbackMatchRank,
    compareResourceCandidates,
    mergeResource,
  });
})(globalThis);
