/* Resolve only canonical source IDs; never infer identity from a title or URL. */
export function evidenceAnchor(evidence, items) {
  const kind = evidence?.task_id ? "task" : evidence?.metadata?.material_id ? "material" : "";
  const id = kind === "task" ? evidence.task_id : evidence?.metadata?.material_id;
  const source = items.find(item => item.kind === kind && item.id === id);
  if (!source) return null;
  const range = String(evidence.locator || "").match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s$/);
  const rawStart = evidence.metadata?.start ?? range?.[1];
  const rawEnd = evidence.metadata?.end ?? range?.[2];
  const start = rawStart !== undefined && Number.isFinite(Number(rawStart)) && Number(rawStart) >= 0 ? Number(rawStart) : undefined;
  const end = rawEnd !== undefined && Number.isFinite(Number(rawEnd)) && Number(rawEnd) >= (start ?? 0) ? Number(rawEnd) : undefined;
  return { source, start, end, locator: String(evidence.locator || "") };
}
