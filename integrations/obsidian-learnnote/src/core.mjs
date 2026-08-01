export const PERSONAL_SECTION = "## 我的补充";
const GENERATED_START = "%% learnnote:generated:start %%";
const GENERATED_END = "%% learnnote:generated:end %%";
const LEGACY_GENERATED_START = "<!-- learnnote:generated:start -->";
const LEGACY_GENERATED_END = "<!-- learnnote:generated:end -->";

export function normalizeBackendUrl(value) {
  const input = String(value || "").trim().replace(/\/+$/, "");
  const parsed = new URL(input || "http://127.0.0.1:8765");
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("LearnNote 地址必须使用 http 或 https");
  }
  const host = parsed.hostname.toLowerCase();
  if (!["127.0.0.1", "localhost", "::1"].includes(host)) {
    throw new Error("当前插件只连接本机 LearnNote 服务");
  }
  parsed.pathname = parsed.pathname.replace(/\/+$/, "");
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

export function sanitizeVaultSegment(value, fallback = "LearnNote") {
  const cleaned = String(value || "")
    .replace(/[\\/:*?"<>|#^[\]]+/g, " ")
    .replace(/[\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim();
  return (cleaned || fallback).slice(0, 90);
}

export function taskFolderPath(root, title, taskId) {
  const base = String(root || "LearnNote")
    .replace(/\\/g, "/")
    .split("/")
    .filter(part => part && part !== "." && part !== "..")
    .map(part => sanitizeVaultSegment(part))
    .join("/") || "LearnNote";
  return `${base}/${sanitizeVaultSegment(title)}--${sanitizeVaultSegment(taskId, "task")}`;
}

export function yamlString(value) {
  return JSON.stringify(String(value ?? ""));
}

export function noteFrontmatter(task, syncedAt) {
  const sourceUrl = task.page_url || task.source?.page_url || "";
  return [
    "---",
    `title: ${yamlString(task.title || "LearnNote")}`,
    `learnnote_task_id: ${yamlString(task.id)}`,
    `learnnote_status: ${yamlString(task.status || "")}`,
    `learnnote_source_type: ${yamlString(task.source_type || "")}`,
    `learnnote_source_url: ${yamlString(sourceUrl)}`,
    `learnnote_synced_at: ${yamlString(syncedAt)}`,
    "tags:",
    "  - learnnote",
    "  - video-note",
    "---"
  ].join("\n");
}

export function mergeGeneratedNote(existing, frontmatter, generated) {
  const body = String(generated || "").trim();
  const current = String(existing || "");
  let personal = `${PERSONAL_SECTION}\n\n`;
  const markerPairs = [
    [GENERATED_START, GENERATED_END],
    [LEGACY_GENERATED_START, LEGACY_GENERATED_END]
  ];
  for (const [startMarker, endMarker] of markerPairs) {
    const start = current.indexOf(startMarker);
    const end = current.indexOf(endMarker);
    if (start >= 0 && end > start) {
      const remainder = current.slice(end + endMarker.length).trim();
      personal = remainder || personal;
      break;
    }
  }
  if (!current.includes(GENERATED_START) && !current.includes(LEGACY_GENERATED_START)) {
    const personalIndex = current.search(/^## 我的补充\s*$/m);
    if (personalIndex >= 0) personal = current.slice(personalIndex).trim();
  }
  return `${frontmatter}\n\n${body}\n\n${personal}\n`;
}

export function importedTaskId(markdown) {
  const match = String(markdown || "").match(/^learnnote_task_id:\s*["']?([^\n"']+)/m);
  return match ? match[1].trim() : "";
}

export function safeArchivePath(value) {
  const normalized = String(value || "").replace(/\\/g, "/").replace(/^\.\//, "");
  if (!normalized || normalized.startsWith("/") || normalized.includes("\0")) return "";
  const parts = normalized.split("/");
  if (parts.some(part => !part || part === "." || part === "..")) return "";
  return parts.join("/");
}

export function formatTimestamp(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours, minutes, secs].map(value => String(value).padStart(2, "0")).join(":");
}
