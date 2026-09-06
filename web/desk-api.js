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
