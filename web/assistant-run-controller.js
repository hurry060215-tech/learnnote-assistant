// The server owns tool decisions and receipts. This controller only advances a
// bounded run, preserves an uncertain request ID, and pauses for edit approval.
const root = "/api/assistant/runs";
const terminal = value => ["completed", "stopped", "cancelled", "failed"].includes(value?.status);
const sameSource = (a, b) => a && b && ["kind", "id", "revision"].every(key => a[key] === b[key]);

export function createAssistantRunController({ api, source, options, reload, render, report, busyChanged = () => {}, newId = () => crypto.randomUUID() }) {
  let active = null, creating = null, busy = false, visible = false, epoch = 0;
  const show = value => {
    if (creating?.run_id === value.id && terminal(value)) creating = null;
    if (active?.id === value.id && value.version < active.version) return active;
    active = value;
    if (visible) render(value);
    return value;
  };
  const check = value => {
    if (!sameSource(source(), value.source)) throw Error("当前笔记、保存版本或草稿已变化。流程已停止继续，请核对当前正文。");
  };
  async function requestCancel(id, version) {
    return api(`${root}/${id}/cancel`, { method: "POST", body: JSON.stringify({ expected_version: version ?? 1 }) });
  }
  async function guarded(work) {
    if (busy) return;
    busy = true; busyChanged(true);
    const token = epoch;
    try { return await work(() => visible && token === epoch); }
    catch (error) { if (visible && token === epoch) report(error.message); }
    finally { busy = false; busyChanged(false); }
  }
  async function refresh(id = creating?.run_id || active?.id) {
    if (!id) return;
    const value = await api(`${root}/${id}`);
    return show(value);
  }
  async function haltOnContextChange(value) {
    try { check(value); }
    catch (error) {
      try { show(await requestCancel(value.id, value.version)); }
      catch { /* Keep the original conflict; GET can reconcile the receipt. */ }
      throw error;
    }
  }
  async function advance(current) {
    let decisions = 0;
    while (current() && active?.status === "ready") {
      if (++decisions > 8) {
        show(await requestCancel(active.id, active.version));
        throw Error("已达到本次界面连续决策上限。后续步骤已停止，请核对实际记录。");
      }
      const before = active;
      await haltOnContextChange(before);
      if (!current()) return;
      let next;
      try {
        next = await api(`${root}/${before.id}/advance`, { method: "POST", body: JSON.stringify({ expected_version: before.version, options: options() }) });
      } catch (error) {
        // A lost response is never a reason to submit another model decision.
        try { await refresh(before.id); } catch { /* Preserve last known state. */ }
        throw error;
      }
      if (!current()) return;
      show(next);
      if (next.version <= before.version) return;
    }
  }
  return {
    get active() { return active; },
    get busy() { return busy; },
    open() { visible = true; epoch++; if (active) render(active); },
    close() {
      visible = false; epoch++;
      const id = creating?.run_id || active?.id;
      if (id && !terminal(active)) requestCancel(id, active?.version).then(value => {
        if (active?.id === id) show(value);
      }).catch(() => {});
    },
    start(question, shareSource) { return guarded(async current => {
      if (active && !terminal(active)) throw Error("请先完成或取消当前流程。");
      if (!shareSource) throw Error("请明确允许本次流程把选中正文发送给当前文字模型。");
      if (!question.trim()) throw Error("请填写要完成的读、改、导出要求。");
      if (!creating) creating = { run_id: newId(), question: question.trim(), source: source(), share_source: true };
      check(creating);
      const candidate = creating;
      let value;
      try {
        value = await api(root, { method: "POST", body: JSON.stringify({ ...candidate, options: options() }) });
      } catch (error) {
        try { value = await api(`${root}/${candidate.run_id}`); } catch { /* Retain the original stable create ID. */ }
        if (!value) throw error;
      }
      creating = null;
      if (!current()) { await requestCancel(value.id, value.version); return; }
      show(value);
      await advance(current);
    }); },
    continue() { return guarded(async current => {
      if (!active) return;
      await refresh();
      if (current()) await advance(current);
    }); },
    approve() { return guarded(async current => {
      const value = active;
      if (value?.status !== "awaiting_approval" || !value.pending_operation?.id) return;
      await haltOnContextChange(value);
      if (!current()) return;
      let result;
      try {
        result = await api(`${root}/${value.id}/approve`, { method: "POST", body: JSON.stringify({ expected_version: value.version, operation_id: value.pending_operation.id, confirm: true }) });
      } catch (error) {
        try { await refresh(value.id); } catch { /* Preserve uncertain status. */ }
        throw error;
      }
      if (!current()) return;
      show(result);
      if (!result.source) {
        report("当前本地操作仍在核对实际回执，后续步骤已停止；请刷新实际状态。");
        return;
      }
      if (result.source.revision !== value.source.revision || result.edit_operation_id) {
        // Do not replace a draft or another selected item while the request was in flight.
        try {
          if (!sameSource(source(), value.source)) throw Error("selection_changed");
          await reload(result.source);
        } catch {
          try { show(await requestCancel(result.id, result.version)); } catch { /* GET reconciles an uncertain cancel receipt. */ }
          throw Error("修改已提交，但当前打开的正文已变化。已停止后续步骤，请从操作记录核对；未覆盖当前草稿。");
        }
      }
      if (current()) await advance(current);
    }); },
    async cancel() {
      epoch++;
      const id = creating?.run_id || active?.id;
      if (!id) return;
      try {
        const result = await requestCancel(id, active?.version);
        if (active?.id === id || creating?.run_id === id) show(result);
      } catch (error) {
        if (error.status === 404 && (creating?.run_id === id || active?.id === id) && !busy) {
          if (creating?.run_id === id) creating = null;
          if (active?.id === id) active = null;
          if (visible) { render(null); report("此流程或来源已不可读取，可以重新选择来源开始。不会自动重发旧请求；已保留的操作副本可从操作记录核对。"); }
        } else if (visible) report(`取消结果尚未确认：${error.message}。请刷新实际状态。`);
      }
    },
    refresh() { return guarded(async () => refresh()); },
    select(id) { return guarded(async () => {
      if (active && !terminal(active) && active.id !== id) throw Error("请先取消当前流程，再查看其他记录。");
      await refresh(id);
    }); },
    async list() { return api(root); },
    forget() { return guarded(async current => {
      if (!active || !terminal(active)) throw Error("请先结束流程。");
      await api(`${root}/${active.id}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) });
      active = null;
      if (current()) { render(null); report("流程记录已删除；正文与独立操作记录保持现状。"); }
    }); },
  };
}
