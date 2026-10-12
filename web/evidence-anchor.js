/* Resolve only canonical source IDs; never infer identity from a title or URL. */
function canonicalSource(kind, id, items) {
  if (!["task", "material"].includes(kind) || typeof id !== "string" || !id) return null;
  const matches = items.filter(item => item.kind === kind && item.id === id);
  return matches.length === 1 ? matches[0] : null;
}
const timeValue = value => (typeof value === "number" || typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value)) && Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value) : undefined;
export function evidenceAnchor(evidence, items) {
  if (evidence?.task_id && evidence?.metadata?.material_id) return null;
  const kind = evidence?.task_id ? "task" : evidence?.metadata?.material_id ? "material" : "";
  const id = kind === "task" ? evidence.task_id : evidence?.metadata?.material_id;
  const source = canonicalSource(kind, id, items);
  if (!source) return null;
  const range = String(evidence.locator || "").match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s$/);
  const start = timeValue(evidence.metadata?.start ?? range?.[1]);
  const rawEnd = timeValue(evidence.metadata?.end ?? range?.[2]);
  const end = rawEnd !== undefined && rawEnd >= (start ?? 0) ? rawEnd : undefined;
  return { source, start, end, locator: String(evidence.locator || "") };
}

export function claimEvidenceAnchor(evidence, taskId, items) {
  if (!evidence || !evidence.evidence_id) return null;
  return evidenceAnchor(evidence.kind === "document"
    ? { metadata: { material_id: evidence.material_id }, locator: evidence.locator }
    : { task_id: taskId, metadata: { start: evidence.start, end: evidence.end }, locator: evidence.locator }, items);
}

export function citationAnchor(citation, messageSource, items) {
  // Older source-scoped QA records retain the exact source ID on the message.
  // Partial citation identity must never borrow another field from that source.
  const identified = citation?.source_kind != null || citation?.source_id != null;
  const source = canonicalSource(identified ? citation.source_kind : messageSource?.kind,
    identified ? citation.source_id : messageSource?.id, items);
  if (!source) return null;
  const start = timeValue(citation.start), end = timeValue(citation.end);
  if (source.kind === "task" && (start === undefined || citation.end != null && (end === undefined || end < start))) return null;
  return { source, start, end, locator: String(citation.time_range || citation.label || "") };
}
