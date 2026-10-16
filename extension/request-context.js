// Request policy: normalize explicit headers/bodies and redact persisted evidence; no capture or I/O.
(function (root) {
const { classify, PLAYBACK_ENDPOINT_RE, requestHeaderArrayHasMediaDestination } = root.LearnNoteCaptureClassification;
const MAX_REQUEST_BODY_BYTES = 64 * 1024;
const RESPONSE_HEADER_ALLOWLIST = new Set(["accept-ranges", "content-disposition", "content-length", "content-location", "content-range", "content-type", "location"]);
const REQUEST_HEADER_CANONICAL = {
  "accept": "Accept",
  "accept-language": "Accept-Language",
  "authorization": "Authorization",
  "content-type": "Content-Type",
  "origin": "Origin",
  "range": "Range",
  "referer": "Referer",
  "sec-ch-ua": "Sec-CH-UA",
  "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
  "sec-ch-ua-platform": "Sec-CH-UA-Platform",
  "sec-fetch-dest": "Sec-Fetch-Dest",
  "sec-fetch-mode": "Sec-Fetch-Mode",
  "sec-fetch-site": "Sec-Fetch-Site",
  "user-agent": "User-Agent",
  "x-requested-with": "X-Requested-With"
};
const REQUEST_HEADER_ALLOWLIST = new Set(Object.keys(REQUEST_HEADER_CANONICAL));
const PERSISTED_REQUEST_HEADER_DENYLIST = new Set(["authorization", "cookie", "proxy-authorization"]);

function requestRangeHeader(resource = {}) {
  const headers = resource.request_headers || {};
  for (const [name, value] of Object.entries(headers)) {
    if (String(name).toLowerCase() === "range") return String(value || "");
  }
  return "";
}

function hasByteRangeRequest(resource = {}) {
  return /^bytes=\d*-\d*$/i.test(requestRangeHeader(resource).trim());
}

function originForUrl(value = "") {
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

function requestHeadersForUrl(resource = {}, url = "") {
  const headers = { ...(resource.request_headers || {}) };
  const origins = [resource.url, url].map(value => {
    try {
      if (!/^https?:\/\/[^/?#\\\s@]+(?:[/?#]|$)/i.test(value || "") || /[\u0000-\u0020\\]/.test(value)) return "";
      return new URL(value).origin;
    } catch {
      return "";
    }
  });
  if (!origins[0] || origins[0] !== origins[1]) {
    for (const name of Object.keys(headers)) {
      if (name.toLowerCase() === "authorization") delete headers[name];
    }
  }
  return headers;
}

function addActiveVideoRequestContext(resource = {}, page = {}, tab = {}) {
  if (resource.source !== "activeVideo") return resource;
  if (!/^https?:\/\//i.test(String(resource.url || ""))) return resource;
  const headers = { ...(resource.request_headers || {}) };
  const referer = resource.frame_url || page.active_video?.frame_url || page.page_url || tab.url || "";
  const normalized = normalizeRequestHeaders([
    { name: "Referer", value: headers.Referer || referer },
    { name: "Origin", value: headers.Origin || originForUrl(referer) },
    ...Object.entries(headers).map(([name, value]) => ({ name, value }))
  ]);
  return { ...resource, request_headers: normalized };
}

function safePersistedRequestHeaders(headers = {}) {
  const safe = {};
  for (const [name, value] of Object.entries(headers || {})) {
    const lower = String(name || "").toLowerCase();
    if (PERSISTED_REQUEST_HEADER_DENYLIST.has(lower)) continue;
    const cleaned = String(value || "").replace(/[\r\n]+/g, " ").trim();
    if (cleaned) safe[name] = cleaned.slice(0, 512);
  }
  return safe;
}

function requestBodyHasContent(details = {}) {
  const requestBody = details.requestBody || {};
  if (requestBody.formData && Object.keys(requestBody.formData || {}).length) return true;
  return Array.isArray(requestBody.raw) && requestBody.raw.some(part => part?.bytes);
}

function safePersistedRequestBody(resource = {}) {
  const body = resource.request_body || {};
  const type = String(body.type || "").trim();
  const content = String(body.content || "");
  if (type === "dropped") {
    return {
      type: "dropped",
      reason: String(body.reason || "too_large_or_binary").slice(0, 80)
    };
  }
  if (!type || !content) return {};
  const method = String(resource.method || "").toUpperCase();
  const kind = resource.kind || classify(resource.url || "", resource.mime || "");
  const replayable = ["POST", "PUT", "PATCH"].includes(method) && (
    ["video", "hls", "dash"].includes(kind) || PLAYBACK_ENDPOINT_RE.test(resource.url || "")
  );
  if (!replayable) return {};
  if (!["form", "text"].includes(type) || content.length > MAX_REQUEST_BODY_BYTES) {
    return { type: "dropped", reason: "too_large_or_binary" };
  }
  return { type, content };
}

function looksLikeMediaRequest(details) {
  const url = details?.url || "";
  if (details?.type === "media") return true;
  if (classify(url, "") !== "unknown") return true;
  if (/^(xmlhttprequest|fetch)$/i.test(String(details?.type || ""))) {
    const hasRange = (details.requestHeaders || []).some(header =>
      String(header.name || "").toLowerCase() === "range" && /^bytes=/i.test(String(header.value || "").trim())
    );
    if (hasRange) return true;
    if (requestHeaderArrayHasMediaDestination(details.requestHeaders || [])) return true;
  }
  return PLAYBACK_ENDPOINT_RE.test(url);
}

function normalizeRequestHeaders(requestHeaders = []) {
  const headers = {};
  for (const header of requestHeaders || []) {
    const lower = String(header.name || "").toLowerCase();
    if (!REQUEST_HEADER_ALLOWLIST.has(lower)) continue;
    const value = String(header.value || "").replace(/[\r\n]+/g, " ").trim();
    if (!value) continue;
    headers[REQUEST_HEADER_CANONICAL[lower] || header.name] = value;
  }
  return headers;
}

function requestBodyFromFormData(formData = {}) {
  const params = new URLSearchParams();
  for (const [name, values] of Object.entries(formData || {})) {
    for (const value of Array.isArray(values) ? values : [values]) {
      params.append(name, String(value ?? ""));
      if (params.toString().length > MAX_REQUEST_BODY_BYTES) return null;
    }
  }
  const content = params.toString();
  return content ? { type: "form", content } : null;
}

function requestBodyFromRaw(raw = []) {
  const chunks = [];
  let total = 0;
  for (const part of raw || []) {
    if (!part?.bytes) continue;
    const bytes = new Uint8Array(part.bytes);
    total += bytes.byteLength;
    if (total > MAX_REQUEST_BODY_BYTES) return null;
    chunks.push(bytes);
  }
  if (!chunks.length) return null;
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  if (merged.some(byte => byte === 0)) return null;
  const content = new TextDecoder("utf-8", { fatal: false }).decode(merged).trim();
  if (!content || /[\u0000-\u0008\u000e-\u001f]/.test(content)) return null;
  return { type: "text", content };
}

function responseHeadersObject(responseHeaders = []) {
  const headers = {};
  for (const header of responseHeaders || []) {
    const lower = String(header.name || "").toLowerCase();
    if (RESPONSE_HEADER_ALLOWLIST.has(lower)) {
      const value = String(header.value || "").replace(/[\r\n]+/g, " ").trim();
      if (value) headers[lower] = value;
    }
  }
  return headers;
}

function responseResolvedUrl(url = "", headers = {}) {
  const raw = headers.location || headers["content-location"] || "";
  if (!raw) return "";
  try {
    return new URL(raw, url).href;
  } catch {
    return "";
  }
}

function requestContextUrl(details = {}, requestHeaders = {}) {
  const referer = String(requestHeaders.Referer || requestHeaders.referer || "").trim();
  if (/^https?:\/\//i.test(referer)) return referer;
  return details.documentUrl || details.initiator || "";
}

function responseResource(details, headers, requestHeaders, requestBody, kind, resolvedUrl, label, now) {
  const contentLength = Number(headers["content-length"] || 0);
  const contextUrl = requestContextUrl(details, requestHeaders);
  return {
    url: details.url,
    resolved_url: resolvedUrl,
    source: "webRequest",
    kind,
    mime: headers["content-type"] || "",
    headers,
    request_type: details.type || "",
    method: details.method || "",
    status_code: details.statusCode || null,
    content_length: Number.isFinite(contentLength) && contentLength > 0 ? contentLength : null,
    initiator: details.initiator || "",
    frame_id: details.frameId ?? null,
    frame_url: contextUrl,
    page_url: contextUrl,
    time_stamp: details.timeStamp || now(),
    request_headers: requestHeaders,
    request_body: requestBody || {},
    label
  };
}

root.LearnNoteRequestContext = Object.freeze({
  hasByteRangeRequest,
  requestHeadersForUrl,
  addActiveVideoRequestContext,
  safePersistedRequestHeaders,
  requestBodyHasContent,
  safePersistedRequestBody,
  looksLikeMediaRequest,
  normalizeRequestHeaders,
  requestBodyFromFormData,
  requestBodyFromRaw,
  responseHeadersObject,
  responseResolvedUrl,
  requestContextUrl,
  responseResource,
});
})(globalThis);
