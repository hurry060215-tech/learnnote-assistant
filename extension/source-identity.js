// Source identity policy: explicit tab/page/resource inputs; no browser I/O or storage.
(function (root) {
function isUnreadableTitle(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  const compact = text.replace(/\s+/g, "");
  if (!compact) return true;
  if (/^[?？\uFFFD]+$/.test(compact)) return true;
  if (compact.length >= 4) {
    const suspectCount = (compact.match(/[?？\uFFFD]/g) || []).length;
    if (suspectCount / compact.length >= 0.65) return true;
  }
  return false;
}

function bestPageTitle(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text && !isUnreadableTitle(text)) return text;
  }
  return "";
}

function canonicalSourcePageUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    url.hostname = url.hostname.toLowerCase();
    const keep = new Set(["v", "p", "list", "index", "courseId", "clazzid", "knowledgeId", "chapterId", "objectid"]);
    for (const key of [...url.searchParams.keys()]) {
      if (!keep.has(key)) url.searchParams.delete(key);
    }
    if ((url.protocol === "https:" && url.port === "443") || (url.protocol === "http:" && url.port === "80")) url.port = "";
    url.pathname = url.pathname.replace(/\/{2,}/g, "/");
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/$/, "");
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0].trim();
  }
}

function sourceHostnameMatches(hostname = "", domain = "") {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  const root = String(domain || "").toLowerCase().replace(/\.$/, "");
  return host === root || host.endsWith(`.${root}`);
}

function sourcePlatformIdentity(urlValue = "", page = {}) {
  const url = String(urlValue || "");
  const bilibili = /(?:bilibili\.com\/video\/|b23\.tv\/)(BV[0-9A-Za-z]+)/i.exec(url);
  if (bilibili) return { platform: "bilibili", platformVideoId: bilibili[1] };
  try {
    const parsed = new URL(url);
    if (sourceHostnameMatches(parsed.hostname, "youtube.com") || sourceHostnameMatches(parsed.hostname, "youtu.be")) {
      const id = sourceHostnameMatches(parsed.hostname, "youtu.be") ? parsed.pathname.split("/").filter(Boolean)[0] : parsed.searchParams.get("v");
      return { platform: "youtube", platformVideoId: id || "" };
    }
    if (sourceHostnameMatches(parsed.hostname, "chaoxing.com") || /xuexitong/i.test(parsed.hostname)) {
      const active = page.active_video || {};
      const id = parsed.searchParams.get("objectid") || parsed.searchParams.get("knowledgeId") || active.objectid || page.objectid || "";
      return { platform: "chaoxing", platformVideoId: String(id) };
    }
    return { platform: parsed.hostname.replace(/^www\./, "") || "web", platformVideoId: "" };
  } catch {
    return { platform: "web", platformVideoId: "" };
  }
}

function stableSourceMediaUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    const volatile = /^(?:token|sign|signature|expires?|deadline|auth|auth_key|wsSecret|wsTime|timestamp|ts|t|rnd|random|callback)$/i;
    for (const key of [...url.searchParams.keys()]) {
      if (volatile.test(key)) url.searchParams.delete(key);
    }
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0];
  }
}

function sourceFingerprintHash(value = "") {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function sourceResourceFingerprint(page = {}, resources = []) {
  const stable = [];
  const active = page.active_video || {};
  const activeSrc = active.current_src || active.currentSrc || active.src || "";
  if (activeSrc) stable.push(`active:${stableSourceMediaUrl(activeSrc)}`);
  const ranked = [...(resources || [])]
    .filter(item => item?.url && !/subtitle|caption|vtt|srt/i.test(String(item.kind || "")))
    .sort((left, right) => Number(right.score || 0) - Number(left.score || 0));
  for (const item of ranked) {
    const url = stableSourceMediaUrl(item.resolved_url || item.url);
    if (!url) continue;
    const key = `${String(item.kind || "media").toLowerCase()}:${url}`;
    if (!stable.includes(key)) stable.push(key);
    if (stable.length >= 12) break;
  }
  return sourceFingerprintHash(stable.sort().join("\n") || "no-media");
}

function buildSourceIdentity(tab = {}, page = {}, resources = [], capturedAt = Date.now()) {
  const pageUrl = page.page_url || tab.url || "";
  const platform = sourcePlatformIdentity(pageUrl, page);
  const active = page.active_video || {};
  const platformVideoId = platform.platformVideoId || "";
  return {
    tab_id: Number.isFinite(Number(tab.id)) ? Number(tab.id) : null,
    canonical_page_url: canonicalSourcePageUrl(pageUrl),
    platform: platform.platform,
    platform_video_id: platformVideoId,
    BVID: platform.platform === "bilibili" ? platformVideoId : "",
    page_title: bestPageTitle(page.title, tab.title),
    active_video: { current_src: String(active.current_src || active.currentSrc || active.src || "").trim() },
    resource_fingerprint: sourceResourceFingerprint(page, resources),
    captured_at: new Date(capturedAt).toISOString()
  };
}

function sourceIdentityKey(identity = {}) {
  return [
    identity.tab_id ?? "",
    identity.canonical_page_url || "",
    identity.platform || "",
    identity.platform_video_id || identity.BVID || "",
    identity.page_title || "",
    identity.active_video?.current_src || "",
    identity.resource_fingerprint || ""
  ].join("\u001f");
}

function sourceIdentityMatches(expected, actual) {
  if (!expected || !actual) return false;
  const expectedTab = Number(expected.tab_id);
  const actualTab = Number(actual.tab_id);
  if (Number.isFinite(expectedTab) && Number.isFinite(actualTab) && expectedTab !== actualTab) return false;
  const expectedUrl = String(expected.canonical_page_url || "");
  const actualUrl = String(actual.canonical_page_url || "");
  if (expectedUrl && actualUrl && expectedUrl !== actualUrl) return false;
  const expectedVideoId = String(expected.platform_video_id || expected.BVID || "");
  const actualVideoId = String(actual.platform_video_id || actual.BVID || "");
  if (expectedVideoId && actualVideoId && expectedVideoId !== actualVideoId) return false;
  const expectedSrc = stableSourceMediaUrl(expected.active_video?.current_src || "");
  const actualSrc = stableSourceMediaUrl(actual.active_video?.current_src || "");
  if (!expectedVideoId && !actualVideoId && expectedSrc && actualSrc && expectedSrc !== actualSrc) return false;
  return Boolean(expectedUrl || actualUrl || expectedVideoId || actualVideoId || expectedSrc || actualSrc);
}

root.LearnNoteSourceIdentity = Object.freeze({
  bestPageTitle,
  buildSourceIdentity,
  sourceIdentityMatches,
});
})(globalThis);
