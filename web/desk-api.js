export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  const text = await response.text();
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    value = text;
  }
  if (!response.ok)
    throw new Error(
      (Array.isArray(value?.detail)
        ? value.detail
            .map((item) => `${(item.loc || []).join(".")}: ${item.msg}`)
            .join("\n")
        : "") ||
        value?.detail?.message ||
        value?.detail ||
        `请求失败 (${response.status})`,
    );
  return value;
}
export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
export const timestamp = (value) => {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return seconds >= 3600
    ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`
    : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

// Plain model references use brackets even when Markdown links are disabled.
// Return positions only; the renderer creates buttons without injecting HTML.
export function timestampRanges(text) {
  const parse = (value) => {
    const parts = value.split(":").map(Number);
    if (parts.at(-1) >= 60 || (parts.length === 3 && parts[1] >= 60))
      return null;
    return parts.length === 3
      ? parts[0] * 3600 + parts[1] * 60 + parts[2]
      : parts[0] * 60 + parts[1];
  };
  return [
    ...String(text).matchAll(
      /\[(\d{1,3}:\d{2}(?::\d{2})?)\s*[–—~～-]\s*(\d{1,3}:\d{2}(?::\d{2})?)\]/g,
    ),
  ]
    .map((match) => ({
      index: match.index,
      label: match[0],
      start: parse(match[1]),
      end: parse(match[2]),
    }))
    .filter(
      (range) =>
        range.start !== null && range.end !== null && range.end >= range.start,
    );
}

export function taskAsset(value, taskId) {
  try {
    const url = new URL(value, location.origin);
    return ["frames", "assets"].some((kind) =>
      url.pathname.startsWith(`/api/tasks/${taskId}/${kind}/`),
    )
      ? url.pathname
      : "";
  } catch {
    return "";
  }
}
