// Read-only progress for one explicitly selected task and its original backend.
(function () {
  "use strict";
  const EVENTS = ["task_created", "task_updated", "pipeline_attempt_started", "stage_timing", "draft_ready", "partial_section_ready", "task_event"];
  // Progress timestamps/timings change independently of completed content.
  const taskIdentity = task => JSON.stringify([task.id, task.created_at, task.status, task.retry_count,
    task.source_identity, task.options, task.mode, task.note_path, task.transcript_path, task.summary_source]);
  const sourceIdentity = task => JSON.stringify([task.id, task.created_at, task.retry_count,
    task.source_identity, task.options, task.mode, task.transcript_path]);

  function create({ card, status, sections, retry, document, t, fetch: read = globalThis.fetch,
    connect = url => new globalThis.EventSource(url), onTask = () => {}, onStop = () => {}, onProgress = () => {},
    setTimer = setTimeout, clearTimer = clearTimeout }) {
    let binding = null, epoch = 0, cursor = 0, source = null, timer = 0, request = null, requestTimeout = 0;
    let terminal = false, disposed = false, failures = 0, joins = 0, dirty = false, serial = 0;
    let provenance = "", snapshotIdentity = "", nodes = new Map();
    const current = token => token === epoch && binding && !disposed && !document.hidden;
    const message = key => { const value = t(key); if (status.textContent !== value) status.textContent = value; };
    const close = () => { source?.close(); source = null; };
    function release() {
      epoch += 1; close(); clearTimer(timer); timer = 0;
      clearTimer(requestTimeout); requestTimeout = 0;
      request?.abort(); request = null; dirty = false;
    }
    function clearSections() { sections.replaceChildren(); nodes = new Map(); provenance = ""; }
    function stop(state) {
      terminal = true; release(); retry.hidden = true;
      message(state === "cancelling" ? "progress_cancelling" : state === "cancelled" ? "progress_cancelled" : state === "failed" ? "progress_failed" : "progress_complete");
      if (state === "success") { onStop(state); return; }
      // Retain the existing terminal transcript recovery, once, without
      // reviving progress. Closing/switching also aborts this bounded read.
      const token = epoch, controller = new AbortController();
      request = controller;
      const timeout = setTimer(() => controller.abort(), 10000); requestTimeout = timeout;
      Promise.resolve().then(() => {
        if (current(token)) return onStop(state, { ...binding, signal: controller.signal, isCurrent: () => current(token) && terminal });
      }).catch(() => {}).finally(() => { clearTimer(timeout); if (request === controller) request = null; });
    }
    function schedule(delay) {
      clearTimer(timer);
      if (!binding || disposed || document.hidden || terminal) return;
      timer = setTimer(() => { timer = 0; sync(); }, delay);
    }
    function render(payload) {
      const key = JSON.stringify([payload.attempt_id, payload.source_revision, payload.generation_revision]);
      const previous = provenance && JSON.parse(provenance);
      if (previous && (previous[0] !== payload.attempt_id || previous[1] !== payload.source_revision)) clearSections();
      provenance = key;
      const top = sections.scrollTop;
      const viewport = sections.getBoundingClientRect().top;
      const anchor = [...sections.children].find(node => node.getBoundingClientRect().bottom > viewport);
      const offset = anchor?.getBoundingClientRect().top;
      const seen = new Set();
      for (const item of payload.sections) {
        const outline = item?.kind === "temporal_outline";
        const body = outline && Array.isArray(item.excerpts) && item.excerpts.every(excerpt => typeof excerpt?.text === "string")
          ? item.excerpts.map(excerpt => excerpt.text).join("\n\n") : item?.markdown;
        if (!item || typeof item.id !== "string" || !item.id || seen.has(item.id)
          || typeof item.revision !== "string" || typeof body !== "string" || item.verified !== false
          || (outline ? item.status !== "draft" || item.summary_generated !== false : item.status !== "evidence_pending")) continue;
        seen.add(item.id);
        let entry = nodes.get(item.id);
        if (!entry) {
          const node = document.createElement("article"), badge = document.createElement("p"), text = document.createElement("pre");
          node.dataset.sectionId = item.id; node.className = "progress-section";
          badge.className = "progress-draft-label"; badge.textContent = t(outline ? "progress_excerpt" : "progress_draft");
          node.append(badge, text); entry = { node, text, kind: item.kind }; nodes.set(item.id, entry);
        }
        // Never replace an unchanged text node, even when metadata advances.
        if (entry.text.textContent !== body) entry.text.textContent = body;
        const index = seen.size - 1;
        if (sections.children[index] !== entry.node) sections.insertBefore(entry.node, sections.children[index] || null);
      }
      for (const [id, entry] of nodes) if (!seen.has(id)) { entry.node.remove(); nodes.delete(id); }
      sections.scrollTop = top + (anchor?.isConnected ? anchor.getBoundingClientRect().top - offset : 0);
    }
    function acceptProjection(payload) {
      if (payload.status === "draft") {
        render(payload);
        if (payload.reason === "legacy_unproven") return "progress_legacy";
        if (["invalid_artifact", "source_mismatch", "attempt_mismatch"].includes(payload.reason)) return "progress_unavailable";
        return nodes.size ? "progress_draft" : "progress_waiting";
      }
      const key = JSON.stringify([payload.attempt_id, payload.source_revision, payload.generation_revision]);
      const previous = provenance && JSON.parse(provenance);
      const sameAttempt = previous && previous[0] === payload.attempt_id;
      if (payload.reason === "publication_pending" && sameAttempt && previous[1] === payload.source_revision) {
        if (provenance !== key) for (const [id, entry] of nodes) if (entry.kind !== "temporal_outline") { entry.node.remove(); nodes.delete(id); }
        provenance = key; return "progress_syncing";
      }
      if (payload.reason === "snapshot_changed" && sameAttempt && payload.source_revision
        && previous[1] === payload.source_revision && previous[2] === payload.generation_revision) return "progress_syncing";
      clearSections();
      if (payload.reason === "not_ready") return "progress_waiting";
      if (["publication_pending", "snapshot_changed"].includes(payload.reason)) return "progress_syncing";
      return payload.reason === "legacy_unproven" ? "progress_legacy" : "progress_unavailable";
    }
    function join() {
      if (source || joins >= 3 || terminal || !binding || document.hidden) return;
      const token = epoch;
      joins += 1;
      try { source = connect(`${binding.base}/events/stream?after=${cursor}`); }
      catch { source = null; return; }
      const stream = source;
      const active = () => current(token) && source === stream && !terminal;
      function receive(event, end = false, contentChanged = false) {
        if (!active()) return;
        let payload;
        try { payload = JSON.parse(event.data); } catch { return; }
        if (!payload || (payload.task_id && payload.task_id !== binding.taskId)) return;
        const raw = String(event.lastEventId || ""), id = Number(raw);
        if (!/^\d+$/.test(raw) || !Number.isSafeInteger(id) || id < cursor || (!end && id <= cursor)) return;
        if (!end && payload.schema_version !== 1) return;
        cursor = Math.max(cursor, id);
        const terminalHint = end || ["failed", "cancelled", "cancelling"].includes(payload.status);
        if (end) close();
        if (terminalHint || contentChanged) serial += 1;
        // Replayed statuses may belong to an earlier attempt. Prioritize a
        // fresh snapshot, and stop only when that snapshot confirms it.
        if (terminalHint && request) {
          request.abort(); request = null; clearTimer(requestTimeout); requestTimeout = 0;
        }
        dirty = true;
        if (!request) sync();
      }
      for (const name of EVENTS) stream.addEventListener(name, event => receive(event, false,
        ["pipeline_attempt_started", "draft_ready", "partial_section_ready"].includes(name)));
      stream.addEventListener("task_terminal", event => receive(event, true));
      stream.addEventListener("task_missing", event => receive(event, true));
      stream.onerror = () => {
        if (!active()) return;
        close(); message("progress_reconnecting"); schedule(Math.min(5000, 1000 * 2 ** (joins - 1)));
      };
    }
    async function sync() {
      if (!binding || disposed || document.hidden || terminal) return;
      if (request) { dirty = true; return; }
      clearTimer(timer); timer = 0; dirty = false;
      const token = epoch, version = serial, selected = binding, controller = new AbortController();
      request = controller;
      const timeout = setTimer(() => controller.abort(), 10000);
      requestTimeout = timeout;
      const isCurrent = () => current(token) && !terminal && version === serial;
      async function json(path) {
        const response = await read(selected.base + path, { signal: controller.signal, redirect: "error", cache: "no-store" });
        if (!response.ok) throw new Error();
        return response.json();
      }
      try {
        const result = await json("");
        if (!isCurrent()) return;
        const task = result?.task || result;
        if (task.id !== selected.taskId) throw new Error();
        const identity = sourceIdentity(task);
        if (snapshotIdentity && snapshotIdentity !== identity) { clearSections(); message("progress_syncing"); }
        snapshotIdentity = identity;
        if (["failed", "cancelled", "cancelling"].includes(task.status)) { stop(task.status); return; }
        if (task.status === "success") {
          // Existing final artifact handling remains the only final-note path.
          await onTask(task, { ...selected, signal: controller.signal, isCurrent });
          if (isCurrent()) stop("success");
          return;
        }
        onProgress(task);
        let notice = "progress_waiting";
        if (task.artifact_status?.draft_available || task.artifact_status?.partial_draft_available || nodes.size) {
          const payload = await json("/partial-note");
          if (!isCurrent()) return;
          const latest = await json("");
          if (!isCurrent()) return;
          const confirmed = latest?.task || latest;
          if (confirmed.id === selected.taskId && ["failed", "cancelled", "cancelling"].includes(confirmed.status)) { stop(confirmed.status); return; }
          if (payload.task_id !== selected.taskId || taskIdentity(confirmed) !== taskIdentity(task)) {
            if (sourceIdentity(confirmed) !== identity) { clearSections(); message("progress_syncing"); }
            dirty = true; return;
          }
          if (payload.schema_version !== 1 || payload.verified !== false || !Array.isArray(payload.sections)) throw new Error();
          notice = acceptProjection(payload);
        }
        if (!isCurrent()) return;
        failures = 0; retry.hidden = true;
        message(notice);
        join();
      } catch {
        if (!current(token) || terminal || request !== controller) return;
        failures += 1;
        message(failures >= 5 ? "progress_paused" : "progress_reconnecting");
        if (failures >= 5) { close(); retry.hidden = false; }
      } finally {
        clearTimer(timeout);
        if (request === controller) {
          request = null;
          if (current(token) && !terminal && failures < 5) schedule(dirty ? 500 : source ? 15000 : 5000);
        }
      }
    }
    function resume() {
      if (!binding || disposed || document.hidden || terminal) return;
      failures = 0; joins = 0; retry.hidden = true; sync();
    }
    function start(selection) {
      release(); binding = null; clearSections(); snapshotIdentity = ""; cursor = 0; serial = 0; terminal = false; failures = 0; joins = 0;
      const url = new URL(selection.backendUrl);
      if (!/^http:\/\/(?:127\.0\.0\.1|localhost)(?::\d{1,5})?\/?$/i.test(url.href) || !selection.taskId) throw new Error();
      binding = { ...selection, base: `${url.origin}/api/tasks/${encodeURIComponent(selection.taskId)}` };
      card.hidden = false; retry.hidden = true; message("progress_waiting"); resume();
    }
    function reset() { release(); binding = null; terminal = false; clearSections(); card.hidden = true; }
    function visibility() { if (document.hidden) release(); else resume(); }
    function destroy() { reset(); disposed = true; document.removeEventListener("visibilitychange", visibility); }
    retry.addEventListener("click", resume);
    document.addEventListener("visibilitychange", visibility);
    return { start, reset, destroy, resume, suspend: release };
  }
  globalThis.LearnNoteProgressive = { create };
})();
