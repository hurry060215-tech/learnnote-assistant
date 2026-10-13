// Shared by the settings form and the local assistant. No backend or permission APIs.
export const READING_STORAGE_KEY = "learnnote.reading.preferences";
export const LEGACY_THEME_KEY = "learnnote.desk.theme";
const META = "__learnnoteReading";
const LOCK = "learnnote.reading.settings";
const RECEIPT_LIMIT = 64;
let revisionSequence = 0;
export const READING_ALLOWED = Object.freeze(Object.fromEntries(Object.entries({
  theme: ["light", "dark"],
  size: [15, 16, 17, 18, 20],
  font: ["sans", "serif", "mono"],
  width: ["760", "940", "1120"],
  leading: ["1.65", "1.85", "2.1"],
  weight: ["400", "500", "600"],
  density: ["comfortable", "compact"],
  accent: ["neutral", "teal", "blue", "plum"],
}).map(([key, values]) => [key, Object.freeze(values)])));
export const READING_DEFAULTS = Object.freeze({
  size: 17, density: "comfortable", font: "sans", width: "940",
  leading: "1.65", weight: "500", accent: "neutral", autoOpen: false, notify: false,
});
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const validId = value => typeof value === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
const failure = (code, message) => ({ ok: false, status: code === "cancelled" ? "cancelled" : "failed", error: { code, message } });
const issue = (code, message) => Object.assign(new Error(message), { code });
// A content fingerprint detects older direct writers retaining our revision token.
// This is a change detector, not an authentication token; no preference payload is
// exposed in the public opaque revision (including the two manual-only booleans).
function revisionFor(token, settings, autoOpen, notify) {
  let hash = 14695981039346656037n;
  for (const char of JSON.stringify([settings, autoOpen, notify])) {
    hash = BigInt.asUintN(64, (hash ^ BigInt(char.charCodeAt(0))) * 1099511628211n);
  }
  return token + ":" + hash.toString(16);
}

// Legacy/manual values are normalized exactly as the existing settings form was.
export function normalizeReading(value) {
  const p = object(value) ? value : {};
  return Object.fromEntries(Object.entries(READING_DEFAULTS).map(([key, fallback]) => {
    const value = key === "size" ? Number(p[key]) : String(p[key]);
    return [key, typeof fallback === "boolean" ? p[key] === true : READING_ALLOWED[key].includes(value) ? value : fallback];
  }));
}

// Agent patches are deliberately stricter than legacy normalization: no coercion.
export function validateReadingPatch(patch) {
  if (!object(patch) || !Object.keys(patch).length) throw issue("invalid_patch", "请提供要修改的阅读与外观选项。");
  const result = {};
  for (const key of Object.keys(patch)) {
    if (!Object.hasOwn(READING_ALLOWED, key) || !READING_ALLOWED[key].includes(patch[key])) {
      throw issue("invalid_patch", "包含不支持的阅读与外观选项。");
    }
  }
  for (const key of Object.keys(READING_ALLOWED)) if (Object.hasOwn(patch, key)) result[key] = patch[key];
  return result;
}

export function applyReadingAppearance(value, { document, preview } = {}) {
  const p = normalizeReading(value);
  const fonts = {
    sans: "var(--ui-font)",
    serif: '"Noto Serif SC", "Noto Serif CJK SC", "Songti SC", "SimSun", serif',
    mono: 'Consolas, "Microsoft YaHei", monospace',
  };
  const colors = { neutral: "#303832", teal: "#087b83", blue: "#4057a0", plum: "#79516f" };
  const darkColors = { neutral: "#d5d9d6", teal: "#81d6d5", blue: "#abbdff", plum: "#d9aed0" };
  const style = document.documentElement.style;
  style.setProperty("--reader-size", p.size + "px");
  style.setProperty("--reader-font", fonts[p.font]);
  style.setProperty("--reader-width", p.width + "px");
  style.setProperty("--reader-leading", p.leading);
  style.setProperty("--reader-weight", p.weight);
  style.setProperty("--chosen-accent", colors[p.accent]);
  style.setProperty("--chosen-accent-dark", darkColors[p.accent]);
  document.body.classList.toggle("compact-density", p.density === "compact");
  if (READING_ALLOWED.theme.includes(value?.theme)) document.body.classList.toggle("dark", value.theme === "dark");
  if (preview) Object.assign(preview.style, {
    fontFamily: fonts[p.font], fontSize: p.size + "px", lineHeight: p.leading, fontWeight: p.weight,
  });
}

/**
 * Inject browser dependencies for deterministic tests. read/operation are sync;
 * patch/undo/saveManual are async. Only read/patch/undo/operation/recentOperations
 * belong on the assistant boundary; saveManual also accepts the two existing
 * manual-only task preferences. See docs/reading-settings-api.md.
 */
export function createReadingSettingsAdapter({
  storage, document, preview, locks, events, isDirty = () => false,
  onChange = () => {}, onError = () => {},
  newRevision = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${++revisionSequence}-${Math.random().toString(36).slice(2)}`,
} = {}) {
  const safeSettings = value => Object.fromEntries(Object.keys(READING_ALLOWED).map(key => [key, value[key]]));
  const safeReceipt = receipt => ({
    ok: true, operationId: receipt.operationId, status: receipt.status,
    ...(receipt.targetOperationId ? { targetOperationId: receipt.targetOperationId } : {}),
    before: safeSettings(receipt.before), after: safeSettings(receipt.after), revision: receipt.revision,
  });
  function load() {
    let raw, legacy;
    try { raw = storage.getItem(READING_STORAGE_KEY); legacy = storage.getItem(LEGACY_THEME_KEY); }
    catch { throw issue("storage_unavailable", "无法读取本机阅读设置；原配置未改变。"); }
    let record;
    try { record = raw === null ? {} : JSON.parse(raw); }
    catch { throw issue("invalid_storage", "已保存的阅读设置无法解析；原配置未改变。"); }
    if (!object(record)) throw issue("invalid_storage", "已保存的阅读设置格式不正确；原配置未改变。");
    const preferences = normalizeReading(record);
    const settings = safeSettings({ ...preferences, theme: READING_ALLOWED.theme.includes(record.theme) ? record.theme : legacy === "dark" ? "dark" : "light" });
    const meta = record[META];
    if (meta !== undefined && (!object(meta) || meta.version !== 1 || !validId(meta.revision) || !Array.isArray(meta.operations) || meta.operations.length > RECEIPT_LIMIT)) {
      throw issue("invalid_storage", "阅读设置的操作记录无法验证；原配置未改变。");
    }
    const operations = meta?.operations || [], ids = new Set();
    for (const op of operations) {
      if (!object(op) || !validId(op.operationId) || ids.has(op.operationId) || !["applied", "undone"].includes(op.status)
        || typeof op.signature !== "string" || op.signature.length > 4096 || typeof op.revision !== "string" || op.revision.length > 2048
        || !object(op.before) || !object(op.after)
        || Object.keys(READING_ALLOWED).some(key => !READING_ALLOWED[key].includes(op.before[key]) || !READING_ALLOWED[key].includes(op.after[key]))
        || (op.status === "undone" && !validId(op.targetOperationId))) {
        throw issue("invalid_storage", "阅读设置的操作记录无法验证；原配置未改变。");
      }
      ids.add(op.operationId);
    }
    const revision = revisionFor(meta?.revision || "legacy", settings, preferences.autoOpen, preferences.notify);
    return { raw, legacy, record, preferences, settings, revision, operations };
  }
  const caught = error => failure(error.code || "operation_failed", error.code ? error.message : "阅读设置操作未完成，请重试。");
  function read() {
    try { const current = load(); return { ok: true, settings: current.settings, revision: current.revision }; }
    catch (error) { return caught(error); }
  }
  function operation(operationId) {
    if (!validId(operationId)) return failure("invalid_operation", "操作编号无效。");
    try {
      const current = load(), found = current.operations.find(op => op.operationId === operationId);
      return found ? { ...safeReceipt(found), current: current.settings, currentRevision: current.revision, replayed: true }
        : failure("operation_unknown", "本机没有保留此操作记录，请读取当前设置后重新确认。");
    } catch (error) { return caught(error); }
  }
  function recentOperations() {
    try { return { ok: true, operations: load().operations.map(safeReceipt) }; }
    catch (error) { return caught(error); }
  }
  function display(current, source) {
    if (document) applyReadingAppearance({ ...current.preferences, ...current.settings }, { document, preview });
    onChange({ settings: current.settings, preferences: current.preferences, revision: current.revision, source });
  }
  function sync() {
    try { const current = load(); display(current, "sync"); return { ok: true, settings: current.settings, revision: current.revision }; }
    catch (error) { const result = caught(error); onError(result); return result; }
  }
  async function mutate(kind, request = {}) {
    let patch, signature;
    try {
      request = { ...request, ...(kind === "manual" ? { preferences: { ...request.preferences } } : {}) };
      if (typeof request.expectedRevision !== "string" || !request.expectedRevision) throw issue("revision_required", "请先读取当前阅读设置再执行操作。");
      if (kind !== "manual" && !validId(request.operationId)) throw issue("invalid_operation", "操作编号无效。");
      if (kind === "undo") {
        if (!validId(request.targetOperationId)) throw issue("invalid_operation", "要撤销的操作编号无效。");
      } else if (kind === "manual") {
        if (!object(request.preferences) || Object.keys(request.preferences).some(key => !Object.hasOwn(READING_DEFAULTS, key) && key !== "theme")) throw issue("invalid_patch", "包含不支持的阅读选项。");
        const normalized = normalizeReading(request.preferences);
        patch = validateReadingPatch(Object.fromEntries(Object.keys(request.preferences).filter(key => Object.hasOwn(READING_ALLOWED, key)).map(key => [key, key === "theme" ? request.preferences[key] : normalized[key]])));
      } else patch = validateReadingPatch(request.patch);
      signature = JSON.stringify({ kind, expectedRevision: request.expectedRevision, ...(kind === "undo" ? { targetOperationId: request.targetOperationId } : { patch }) });
    } catch (error) { return caught(error); }
    const commit = () => {
      let current, didWrite = false;
      try {
        current = load();
        const prior = kind === "manual" ? null : current.operations.find(op => op.operationId === request.operationId);
        if (prior) {
          if (prior.signature !== signature) throw issue("operation_conflict", "此操作编号已用于其他请求，未重复执行。");
          // A retry also repairs a previous render failure, without another write.
          try { if (!isDirty()) display(current, "replay"); }
          catch { return { ...failure("apply_failed", "设置已经保存，但界面仍未能更新。请重新加载。"), persisted: true, revision: current.revision }; }
          return { ...safeReceipt(prior), current: current.settings, currentRevision: current.revision, replayed: true };
        }
        if (request.signal?.aborted) throw issue("cancelled", "操作已取消，设置未改变。");
        if (kind !== "manual" && isDirty()) throw issue("unsaved_settings", "设置中还有未保存的修改，请先保存或取消。");
        if (current.revision !== request.expectedRevision) throw issue("revision_conflict", "阅读设置已改变，请读取最新设置后重新确认。");
        if (kind === "undo") {
          const target = current.operations.find(op => op.operationId === request.targetOperationId && op.status === "applied");
          if (!target) throw issue("operation_unknown", "原操作记录已不可用，未撤销设置。");
          if (!equal(current.settings, target.after)) throw issue("undo_conflict", "原操作后阅读设置已改变，未覆盖后续修改。");
          patch = target.before;
        }
        const after = safeSettings({ ...current.settings, ...patch });
        const token = newRevision();
        if (!validId(token) || token === current.record[META]?.revision) throw issue("revision_unavailable", "无法生成新的设置版本，设置未改变。");
        const manual = kind === "manual" ? request.preferences : {};
        const autoOpen = Object.hasOwn(manual, "autoOpen") ? manual.autoOpen === true : current.preferences.autoOpen;
        const notify = Object.hasOwn(manual, "notify") ? manual.notify === true : current.preferences.notify;
        const revision = revisionFor(token, after, autoOpen, notify);
        const receipt = kind === "manual" ? null : {
          operationId: request.operationId, signature, status: kind === "undo" ? "undone" : "applied",
          ...(kind === "undo" ? { targetOperationId: request.targetOperationId } : {}),
          before: current.settings, after, revision,
        };
        let operations = receipt ? [...current.operations, receipt] : current.operations;
        // Pin the newest patch so its undo/reload receipt survives later undos.
        const lastPatch = [...operations].reverse().find(op => op.status === "applied");
        operations = operations.slice(-RECEIPT_LIMIT);
        if (lastPatch && !operations.includes(lastPatch)) operations = [lastPatch, ...operations.slice(1)];
        const next = { ...current.record, ...patch, [META]: { version: 1, revision: token, operations } };
        if (kind === "manual") for (const key of ["autoOpen", "notify"]) {
          if (Object.hasOwn(request.preferences, key)) next[key] = request.preferences[key] === true;
        }
        // Lock-cooperating tabs serialize. Recheck direct/legacy writers too.
        if (storage.getItem(READING_STORAGE_KEY) !== current.raw || storage.getItem(LEGACY_THEME_KEY) !== current.legacy) throw issue("revision_conflict", "其他窗口已改变阅读设置，请重新确认。");
        if (request.signal?.aborted) throw issue("cancelled", "操作已取消，设置未改变。");
        const encoded = JSON.stringify(next);
        try { storage.setItem(READING_STORAGE_KEY, encoded); didWrite = true; }
        catch { throw issue("storage_write_failed", "无法保存到本机，原配置未改变。"); }
        // Never roll back another tab's newer write or report a lost write as applied.
        const saved = load();
        if (saved.raw !== encoded) return failure("commit_conflict", "保存期间设置被其他窗口改变，请读取当前设置。");
        try { display(saved, kind); }
        catch { return { ...failure("apply_failed", "设置已保存，但界面未能更新。重新加载后可恢复。"), persisted: true, revision }; }
        return receipt ? safeReceipt(receipt) : { ok: true, status: "applied", before: current.settings, after, revision };
      } catch (error) {
        return didWrite ? { ...failure("commit_unverified", "设置已写入，但无法验证当前保存结果。请重新读取后确认。"), persisted: true } : caught(error);
      }
    };
    if (request.signal?.aborted) return failure("cancelled", "操作已取消，设置未改变。");
    if (!locks?.request) return kind === "manual" ? commit() : failure("locking_unavailable", "当前环境不支持安全的跨窗口设置操作，请使用阅读与外观设置面板。");
    try { return await locks.request(LOCK, { mode: "exclusive", ...(request.signal ? { signal: request.signal } : {}) }, commit); }
    catch (error) { return request.signal?.aborted ? failure("cancelled", "操作已取消，设置未改变。") : caught(error); }
  }
  const handleStorage = event => {
    if (event.storageArea && event.storageArea !== storage) return;
    if (event.key === null || [READING_STORAGE_KEY, LEGACY_THEME_KEY].includes(event.key)) sync();
  };
  events?.addEventListener("storage", handleStorage);
  return {
    read, operation, recentOperations, sync,
    patch: request => mutate("patch", request), undo: request => mutate("undo", request),
    saveManual: request => mutate("manual", request),
    dispose: () => events?.removeEventListener("storage", handleStorage),
  };
}
