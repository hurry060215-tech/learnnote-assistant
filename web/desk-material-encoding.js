import { api, escapeHtml as esc } from "/web/desk-api.js";

export function canRedecodeMaterial(source) {
  return source?.kind === "material" && !source.linked_task_id && source.source_type !== "pdf"
    && /\.(txt|md|markdown|html|htm)$/i.test(source.filename || "");
}

// The request may finish after dismissal. Its result belongs to this dialog
// visit and reader navigation, never a later visit (even to the same source).
export function installMaterialEncoding({ state, dialog, show, status, refresh, generation }) {
  const pending = new Set();
  let navigation = 0, active = null;
  window.addEventListener("learnnote:navigation", () => {
    if (active?.ownsDialog()) dialog.close();
    navigation++;
    active = null;
  });
  dialog.addEventListener("cancel", () => { active = null; });

  return async function openEncoding() {
    const selected = { ...state.selected };
    if (!canRedecodeMaterial(selected)) return;
    const visit = navigation, epoch = state.epoch;
    const token = show("重新选择原文编码", '<p class="muted">正在读取当前资料…</p>');
    const session = { ownsDialog: () => active === session && dialog.open && token === generation(),
      current: () => session.ownsDialog() && visit === navigation && epoch === state.epoch
      && state.selected?.kind === "material" && state.selected?.id === selected.id };
    active = session;
    const path = `/api/library/materials/${encodeURIComponent(selected.id)}`;
    let material;
    try {
      material = (await api(path)).material;
      if (!session.current()) return;
      if (!canRedecodeMaterial({ ...material, kind: "material" })) throw new Error("只有本地 TXT、Markdown 和 HTML 资料可以重新选择编码。");
    } catch (error) {
      if (session.current()) status(error.message);
      return;
    }
    const encodings = [["utf-8", "UTF-8"], ["gb18030", "GB18030 / GBK"], ["big5", "Big5"],
      ["shift_jis", "Shift_JIS"], ["utf-16-le", "UTF-16 LE"], ["utf-16-be", "UTF-16 BE"]];
    document.getElementById("toolBody").innerHTML = `<form id="materialEncodingForm">
      <p><strong>${esc(material.title || material.filename)}</strong></p>
      <p id="materialCurrentEncoding"></p>
      <p>原始字节保留在本机，原文件不会被覆盖。重解码会更新资料文本和出处，请重新核对已有引用。</p>
      <label for="materialRedecodeEncoding">重新解码使用的编码</label>
      <select id="materialRedecodeEncoding">${encodings.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select>
      <footer><button type="button" data-close-tool>取消</button><button id="materialRedecodeSubmit" class="primary" type="submit">确认重新解码</button></footer>
      <p class="muted">提交后关闭窗口不会撤回已提交的操作；可重新打开资料查看结果。</p>
    </form>`;
    const form = document.getElementById("materialEncodingForm");
    const encoding = document.getElementById("materialRedecodeEncoding");
    const submit = document.getElementById("materialRedecodeSubmit");
    const current = document.getElementById("materialCurrentEncoding");
    function displayEncoding() {
      current.textContent = `当前编码：${material.metadata?.encoding || "未知"}`;
      const value = String(material.metadata?.decoding_hint || material.metadata?.encoding || "").toLowerCase();
      if (encodings.some(([key]) => key === value)) encoding.value = value;
    }
    displayEncoding();
    const disable = (value) => { submit.disabled = value; encoding.disabled = value; };
    if (pending.has(selected.id)) {
      disable(true);
      status("此资料的重解码仍在处理中，请稍后关闭并重新打开查看结果。");
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!session.current() || pending.has(selected.id)) return;
      const requested = encoding.value;
      if (!confirm(`将按 ${requested} 重新解码这份资料并更新出处。原文件保留不变；已有引用需要重新核对。继续？`)) return;
      pending.add(selected.id);
      disable(true);
      status("正在使用本机原始字节重新解码…");
      let committed = false;
      try {
        const result = await api(`${path}/redecode`, { method: "POST", body: JSON.stringify({
          encoding: requested, expected_updated_at: material.updated_at,
        }) });
        committed = true;
        if (!session.current()) return;
        material = result.material;
        displayEncoding();
        // A periodic refresh started before this write may contain old data.
        // Let it settle before requesting the newly committed version.
        if (state.refreshPromise) await state.refreshPromise;
        if (!session.current()) return;
        await refresh();
        if (session.current()) status("已重新解码，原文件保留不变。请关闭窗口核对原文与已有引用。");
      } catch (error) {
        if (session.current()) status(committed
          ? `重解码已保存，但阅读页刷新失败。请重新打开资料查看。${error.message}` : error.message);
      } finally {
        pending.delete(selected.id);
        if (session.current()) disable(false);
      }
    });
  };
}
