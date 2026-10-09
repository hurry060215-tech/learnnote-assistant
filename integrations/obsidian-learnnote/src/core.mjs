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

function utf8Bytes(value) {
  let bytes = 0;
  for (const character of value) {
    const point = character.codePointAt(0);
    bytes += point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
  }
  return bytes;
}

export function sanitizeVaultSegment(value, fallback = "LearnNote", maxBytes = 180) {
  const cleaned = String(value || "").normalize("NFC")
    .replace(/[\\/:*?"<>|#^[\]]+/g, " ")
    .replace(/[\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim();
  let result = "", count = 0, bytes = 0;
  for (const character of cleaned || fallback) {
    const size = utf8Bytes(character);
    if (count >= 90 || bytes + size > maxBytes) break;
    result += character; count++; bytes += size;
  }
  return result || fallback;
}

export function taskFolderPath(root, title, taskId) {
  const base = String(root || "LearnNote")
    .replace(/\\/g, "/")
    .split("/")
    .filter(part => part && part !== "." && part !== "..")
    .map(part => sanitizeVaultSegment(part))
    .join("/") || "LearnNote";
  const identity = sanitizeVaultSegment(taskId, "task");
  return `${base}/${sanitizeVaultSegment(title, "LearnNote", 240 - utf8Bytes(identity) - 2)}--${identity}`;
}

export function taskFolderCandidates(root, title, taskId) {
  const current = taskFolderPath(root, title, taskId);
  // Read existing old names without renaming or stranding personal annotations.
  // This legacy path is only adopted when its LearnNote.md already exists.
  const legacySegment = (value, fallback = "LearnNote") => (String(value || "")
    .replace(/[\\/:*?"<>|#^[\]]+/g, " ").replace(/[\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ").replace(/[. ]+$/g, "").trim() || fallback).slice(0, 90);
  const base = String(root || "LearnNote").replace(/\\/g, "/").split("/")
    .filter(part => part && part !== "." && part !== "..").map(part => legacySegment(part)).join("/") || "LearnNote";
  const legacy = `${base}/${legacySegment(title)}--${legacySegment(taskId, "task")}`;
  return [...new Set([current, legacy])];
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
  const personalIndex = current.search(/^## 我的补充[^\S\r\n]*\r?$/m);
  const beforePersonal = index => index >= 0 && (personalIndex < 0 || index < personalIndex);
  let personal = "";
  const markerPairs = [
    [GENERATED_START, GENERATED_END],
    [LEGACY_GENERATED_START, LEGACY_GENERATED_END]
  ];
  for (const [startMarker, endMarker] of markerPairs) {
    const start = current.indexOf(startMarker);
    const end = current.indexOf(endMarker);
    if (beforePersonal(start) && end > start && beforePersonal(end)) {
      // Only the delimited region is generated. Migrate any text before it
      // into the personal section too, so the next marker-free sync keeps it.
      const prefix = current.slice(0, start).replace(/^---[^\S\r\n]*\r?\n[\s\S]*?\r?\n---[^\S\r\n]*(?:\r?\n|$)/, "");
      const remainder = current.slice(end + endMarker.length);
      personal = prefix.trim()
        ? `${PERSONAL_SECTION}\n\n${prefix}${remainder}`
        : remainder;
      if (!/^## 我的补充[^\S\r\n]*\r?$/m.test(personal)) {
        personal = `${PERSONAL_SECTION}\n\n${personal}`;
      }
      break;
    }
  }
  if (!personal && current) {
    const hasDamagedMarkers = markerPairs.some(([start, end]) => beforePersonal(current.indexOf(start)) || beforePersonal(current.indexOf(end)));
    // An unrecognized or damaged note has no safely replaceable region.
    // Keep its body as personal material rather than guessing what to erase.
    personal = personalIndex >= 0 && !hasDamagedMarkers
      ? current.slice(personalIndex)
      : `${PERSONAL_SECTION}\n\n${current.replace(/^---[^\S\r\n]*\r?\n[\s\S]*?\r?\n---[^\S\r\n]*(?:\r?\n|$)/, "")}`;
  }
  if (!personal) personal = `${PERSONAL_SECTION}\n\n`;
  return `${frontmatter}\n\n${body}\n\n${personal}`;
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
