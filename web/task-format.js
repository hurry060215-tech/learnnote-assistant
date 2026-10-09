// Pure task presentation: no DOM, storage, model or network access.
(function installModule(global) {
  "use strict";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function semverParts(value) {
  const match = String(value || "").match(/^(\d+)\.(\d+)\.(\d+)$/);
  return match ? match.slice(1).map(Number) : null;
}

function isNewerVersion(latest, current) {
  const left = semverParts(latest);
  const right = semverParts(current);
  if (!left || !right) return false;
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] > right[index];
  }
  return false;
}

function compactUrl(value, limit = 88) {
  const text = String(value || "").trim();
  if (!text || text.length <= limit) return text;
  const head = Math.max(24, Math.floor(limit * 0.42));
  const tail = Math.max(24, limit - head - 3);
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

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

function hostFromUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    return parsed.hostname || "";
  } catch {
    const match = /^https?:\/\/([^/?#]+)/i.exec(text);
    return match ? match[1] : "";
  }
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}

function seekTimeValue(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function seekTimeButton(seconds, className = "time-seek") {
  return `<button type="button" class="${escapeHtml(className)}" data-media-seek-time="${seekTimeValue(seconds)}" title="跳到 ${escapeHtml(fmt(seconds))}"><time>${escapeHtml(fmt(seconds))}</time></button>`;
}

function frameTimestampText(window, limit = 4) {
  const values = (window?.frame_timestamps || []).slice(0, limit).map(value => fmt(value));
  if (!values.length) return "";
  const suffix = (window.frame_timestamps || []).length > values.length ? "..." : "";
  return `${values.join(" / ")}${suffix}`;
}

function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function contentDispositionFilename(value = "") {
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

function contentDispositionHint(value = "") {
  const filename = contentDispositionFilename(value);
  return filename ? `filename ${filename}` : "";
}

function safeHeaderNames(names) {
  return (names || [])
    .map(name => String(name || "").trim())
    .filter(name => !/cookie|authorization/i.test(name))
    .sort()
    .join(", ");
}

function requestHeaderNames(resource) {
  return safeHeaderNames(Object.keys(resource?.request_headers || {})) || "-";
}

function attemptHeaderNames(attempt) {
  return safeHeaderNames(attempt?.request_header_names) || "-";
}

function requestBodySummary(resource) {
  const body = resource?.request_body || {};
  const content = String(body.content || "");
  if (!content) return "";
  const method = String(resource.method || "POST").toUpperCase();
  const type = String(body.type || "body");
  if (content === "<redacted>") return `${method} ${type} body 已捕获`;
  return `${method} ${type} body ${fmtBytes(content.length) || `${content.length} B`}`;
}

function mseAppendEvidence(resource) {
  if (!resource?.mse_append_count && !resource?.mse_append_magic && !resource?.mse_append_total_bytes) return "";
  return [
    resource.mse_append_count ? `MSE append ${resource.mse_append_count}x` : "MSE append",
    resource.mse_append_magic || "",
    fmtBytes(resource.mse_append_total_bytes),
    resource.mse_append_mime || "",
    resource.mse_append_detected_kind ? `detected ${resource.mse_append_detected_kind}` : ""
  ].filter(Boolean).join(" ");
}

function hasRangeRequestHeader(resource) {
  return Object.keys(resource?.request_headers || {}).some(name => String(name).toLowerCase() === "range");
}

function compactIdList(values, limit = 3) {
  const ids = (values || []).map(value => String(value || "").trim()).filter(Boolean);
  if (!ids.length) return "";
  const suffix = ids.length > limit ? ` 等 ${ids.length} 个` : "";
  return `${ids.slice(0, limit).join(", ")}${suffix}`;
}


  global.LearnNoteTaskFormat = Object.freeze({
    escapeHtml,
    semverParts,
    isNewerVersion,
    compactUrl,
    isUnreadableTitle,
    hostFromUrl,
    fmt,
    seekTimeValue,
    seekTimeButton,
    frameTimestampText,
    fmtBytes,
    contentDispositionFilename,
    contentDispositionHint,
    safeHeaderNames,
    requestHeaderNames,
    attemptHeaderNames,
    requestBodySummary,
    mseAppendEvidence,
    hasRangeRequestHeader,
    compactIdList,
  });
})(globalThis);
