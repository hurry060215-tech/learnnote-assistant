import { formatTimestamp } from "./core.mjs";

interface PersonalAnnotation {
  id: string;
  text: string;
  quote?: string;
  revision?: string;
  anchor?: Record<string, unknown>;
  anchor_status?: Record<string, unknown>;
}

interface AnnotationSnapshot {
  schema_version: number;
  task_id: string;
  annotations: PersonalAnnotation[];
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}

export function annotationSnapshot(raw: string, taskId: string): { key: string; json: string; markdown: string; count: number } {
  const value = JSON.parse(raw) as AnnotationSnapshot;
  if (!value || value.schema_version !== 2 || value.task_id !== taskId || !Array.isArray(value.annotations)
    || value.annotations.length > 500) throw new Error("personal_annotations_invalid");
  const ids = new Set<string>();
  for (const item of value.annotations) {
    if (!item || typeof item.id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(item.id) || ids.has(item.id)
      || typeof item.text !== "string" || (item.quote !== undefined && typeof item.quote !== "string")) {
      throw new Error("personal_annotations_invalid");
    }
    ids.add(item.id);
    // current_revision is derived from generated content; it is not a user
    // revision and must not create another snapshot on every regeneration.
    if (item.anchor_status && typeof item.anchor_status === "object") delete item.anchor_status.current_revision;
  }
  const json = JSON.stringify(canonical(value), null, 2) + "\n";
  // This is a filename hint, not an integrity check. The importer compares
  // complete contents and uses another filename on every collision or edit.
  let hash = 2166136261;
  for (let index = 0; index < json.length; index++) hash = Math.imul(hash ^ json.charCodeAt(index), 16777619);
  const key = (hash >>> 0).toString(16).padStart(8, "0");
  const lines = ["# 个人批注", "", "这是 LearnNote 个人批注的本地快照。同步保留历史版本和本地修改；本地修改不会回传。", "",
    `任务：${taskId}`, "", `完整 ID、原文和锚点：[[annotations-${key}.json|JSON 映射]]`, ""];
  if (!value.annotations.length) lines.push("本次快照没有批注。此前导入的版本仍然保留。", "");
  for (const item of value.annotations) {
    const status = item.anchor_status || {};
    const resolution = status.resolution;
    const label = resolution === "exact" ? "原位置匹配" : resolution === "migrated" ? "已重新定位"
      : resolution === "orphaned" ? "未定位，请人工核对原文" : "位置未验证";
    lines.push(`## 批注 ${item.id}`, "", `- 版本：${item.revision ?? "历史记录"}`, `- 位置：${label}${status.stale ? "（来源已变更）" : ""}`);
    const anchor = item.anchor || {};
    if (anchor.kind === "transcript" && typeof anchor.start === "number") {
      lines.push(`- 字幕时间：${formatTimestamp(anchor.start)}${typeof anchor.end === "number" ? ` – ${formatTimestamp(anchor.end)}` : ""}`);
    }
    lines.push("", item.text, "");
    if (item.quote) lines.push("### 引用原文", "", item.quote, "");
    lines.push("### 锚点映射", "", "```json", JSON.stringify({ anchor, anchor_status: status }, null, 2), "```", "");
  }
  return { key, json, markdown: lines.join("\n"), count: value.annotations.length };
}
