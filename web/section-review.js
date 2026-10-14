import { api, escapeHtml as esc } from "/web/desk-api.js";

// A read-only model opinion for one visible chapter/batch, with fresh consent.
export function installSectionReview({ state, dialog, show, status, generation }) {
  let active = null;
  const pending = new Set();
  function invalidate(message) {
    if (!active?.current()) return;
    active.sequence++; active.preview = null;
    document.getElementById("sectionReviewPreview")?.replaceChildren();
    document.getElementById("sectionReviewResult")?.replaceChildren();
    if (message) status(message);
  }
  window.addEventListener("learnnote:navigation", () => { if (active?.owns()) dialog.close(); active = null; });
  window.addEventListener("learnnote:settings", () => invalidate("模型设置已变化，请重新打开核对窗口。"));
  dialog.addEventListener("cancel", () => { active = null; });
  return async function openSectionReview() {
    const selected = state.selected;
    if (selected?.kind !== "task" || state.edition?.edited || state.editing) {
      status("此入口核对当前生成稿；请先退出编辑，个人修改稿暂不支持。"); return;
    }
    const taskId = selected.id, revision = state.revision, epoch = state.epoch;
    const token = show("核对章节概括", '<p class="muted">正在读取当前章节与模型设置…</p>');
    const session = { sequence: 0, preview: null,
      owns: () => active === session && dialog.open && generation() === token,
      current: () => session.owns() && state.epoch === epoch && state.selected?.id === taskId && state.revision === revision };
    active = session;
    const endpoint = `/api/tasks/${encodeURIComponent(taskId)}/section-review`;
    let chapters, route;
    try { [chapters, route] = await Promise.all([api(`${endpoint}?revision=${encodeURIComponent(revision)}`), api("/api/model/connection")]); }
    catch (error) { if (session.current()) { document.getElementById("toolBody").textContent = "当前章节暂不可用，请关闭后重新打开。"; status(error.message); } return; }
    if (!session.current()) return;
    if (!route.configured || !chapters.sections?.length) { document.getElementById("toolBody").textContent = "没有可核对的生成章节或已保存的模型连接。"; status("请先确认当前生成稿和模型设置，再重新打开。"); return; }
    const body = document.getElementById("toolBody");
    body.innerHTML = `<div class="section-review"><p class="muted">查看原文是否支持本章概括。模型判断仅供回源参考，正文保持原样。</p>
      <label for="sectionReviewChapter">章节</label><select id="sectionReviewChapter">${chapters.sections.map(item => `<option value="${esc(item.id)}">${esc(item.title)}</option>`).join("")}</select>
      <p class="muted">先预览，再确认发送；可能产生模型费用。</p>
      <details class="section-review-limits"><summary>范围、预算与关闭说明</summary>
      <p class="muted">仅核对本次选取的文字，不读取画面，不验证课程本身真假。每次最多 12 条结论、6,000 结论字符、12,000 原文字符、2,000 输出 token、1 次请求；单次模型请求 30 秒超时。金额未知，不会自动处理下一批。</p>
      <p class="muted">关闭窗口不撤回已经发送的请求；远端可能继续处理或计费。结果只在本窗口显示，不改动原文和原有核对记录。</p></details>
      <button id="sectionReviewPrepare" class="primary" type="button">预览本次发送内容</button>
      <div id="sectionReviewPreview"></div><div id="sectionReviewResult" aria-live="polite"></div></div>`;
    const $ = id => document.getElementById(id), selector = $("sectionReviewChapter"), button = $("sectionReviewPrepare");
    let offset = 0, nextOffset = null;
    const current = serial => session.current() && serial === session.sequence;
    function paragraph(parent, text, tag = "p") { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; }
    function sync() { if (session.current()) button.disabled = pending.has(taskId); }
    session.sync = sync;
    function resultView(value, serial) {
      const host = $("sectionReviewResult"); host.replaceChildren();
      paragraph(host, "模型核对结果 · 仅针对本次原文，仍可能判断有误");
      const labels = { supported: "模型判断支持", contradicted: "模型判断矛盾", insufficient: "本次原文不足以判断" };
      for (const item of value.judgments) {
        const section = document.createElement("details"), claim = value.claims.find(claim => claim.claim_alias === item.claim_alias);
        paragraph(section, `${labels[item.verdict]}：${claim?.text || item.claim_alias}`, "summary");
        paragraph(section, item.reason);
        for (const citation of item.citations) {
          const source = value.evidence.find(source => source.source_alias === citation.source_alias);
          paragraph(section, `来源 ${citation.source_alias} · ${source?.locator || "原文"}`);
          paragraph(section, citation.quote, "pre");
        }
        host.append(section);
      }
      paragraph(host, `已请求 1 次 · 输入 token ${value.usage?.input_tokens ?? "未知"} · 输出 token ${value.usage?.output_tokens ?? "未知"} · 金额未知`);
      nextOffset = value.coverage.next_offset;
      if (nextOffset !== null) {
        const next = paragraph(host, "预览下一批（需另行确认）", "button"); next.type = "button";
        next.addEventListener("click", () => { if (current(serial)) { offset = nextOffset; prepare(); } });
      }
    }
    async function confirm(value, serial, consent, send) {
      if (!current(serial) || session.preview !== value || !consent.checked || pending.has(taskId)) return;
      session.preview = null; pending.add(taskId); send.disabled = true; consent.disabled = true; sync();
      status("正在发送本次已确认的核对请求…");
      try {
        const result = await api(`${endpoint}/confirm`, { method: "POST", body: JSON.stringify({ preview_id: value.preview_id,
          fingerprint: value.fingerprint, share_source: true }) });
        if (!current(serial)) return;
        if (result.task_id !== taskId || result.revision !== revision || result.fingerprint !== value.fingerprint) throw new Error("返回版本已变化，请重新预览。");
        $("sectionReviewPreview").replaceChildren(); resultView(result, serial); status("本次核对已返回，正文保持原样。");
      } catch (error) { if (current(serial)) { $("sectionReviewPreview").replaceChildren(); status(`${error.message} 未自动重试，请重新预览后决定是否再次发送。`); } }
      finally { pending.delete(taskId); active?.sync?.(); }
    }
    async function prepare() {
      if (!session.current() || pending.has(taskId)) return;
      invalidate(); const serial = session.sequence;
      pending.add(taskId); sync(); status("正在准备本地预览，尚未调用模型…");
      try {
        const value = await api(`${endpoint}/preview`, { method: "POST", body: JSON.stringify({ revision, section_id: selector.value,
          offset, base_url: route.model.base_url, model: route.model.model }) });
        if (!current(serial)) return;
        if (value.task_id !== taskId || value.revision !== revision || value.section_id !== selector.value || value.offset !== offset ||
            value.connection.base_url !== route.model.base_url || value.connection.model !== route.model.model) throw new Error("预览范围或模型已变化，请重新预览。");
        const host = $("sectionReviewPreview");
        paragraph(host, `发送目标：${value.connection.model} · ${value.connection.base_url}`);
        paragraph(host, `本章共 ${value.coverage.claim_count} 条正文结论，本次第 ${offset + 1}–${offset + value.coverage.selected_claims} 条。原文只含 ${value.coverage.selected_sources}/${value.coverage.candidate_sources} 条候选及相邻上下文，不代表完整课程。${value.coverage.source_truncated ? "部分原文因预算未纳入，未截断单条原句。" : ""}`);
        paragraph(host, `本次 ${value.coverage.literal_matches} 条与原文字面一致，其余仍需核对；字面一致也不代表事实核验。`);
        for (const claim of value.claims) paragraph(host, `${claim.claim_alias} · ${claim.text}`);
        const sources = document.createElement("details"); paragraph(sources, "查看全部将发送的原文", "summary");
        for (const source of value.evidence) { paragraph(sources, `${source.source_alias} · ${source.locator}`); paragraph(sources, source.text, "pre"); } host.append(sources);
        paragraph(host, value.warning);
        if (!value.can_submit) { status("当前结论或原文超出预算/不足，未发送。请换一个较短章节。"); return; }
        const label = document.createElement("label"); label.className = "tool-choice";
        const consent = document.createElement("input"); consent.type = "checkbox"; consent.id = "sectionReviewConsent";
        label.append(consent, document.createTextNode("我同意把以上结论和原文发送到这个模型，可能产生费用")); host.append(label);
        const send = paragraph(host, "确认发送一次核对请求", "button"); send.type = "button"; send.id = "sectionReviewSend"; send.disabled = true;
        session.preview = value;
        consent.addEventListener("change", () => { send.disabled = !consent.checked || pending.has(taskId) || !current(serial); });
        send.addEventListener("click", () => confirm(value, serial, consent, send)); status("请查看发送内容后决定是否继续。");
      } catch (error) { if (current(serial)) status(error.message); }
      finally { pending.delete(taskId); active?.sync?.(); }
    }
    selector.addEventListener("change", () => { offset = 0; nextOffset = null; invalidate("章节已变化，请重新预览。"); });
    button.addEventListener("click", prepare); sync(); status("先预览；不会自动调用模型。");
  };
}
