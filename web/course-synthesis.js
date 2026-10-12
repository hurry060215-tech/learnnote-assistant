import { api, escapeHtml as esc } from "/web/desk-api.js";

// Each consent belongs to one dialog, question, course and saved model route.
export function installCourseSynthesis({ state, dialog, show, status, generation, openEvidence, notice }) {
  const pending = new Set();
  let active = null, navigation = 0;
  window.addEventListener("learnnote:navigation", () => {
    if (active?.owns()) dialog.close();
    navigation++; active = null;
  });
  window.addEventListener("learnnote:settings", () => active?.invalidate?.("模型设置可能已变化，请刷新所选模型并重新预览。"));
  dialog.addEventListener("cancel", () => { active = null; });
  return async function openCourseSynthesis(initial, initialQuestion = "") {
    const epoch = state.epoch, visit = navigation;
    const token = show("课程 AI 综合 · 先预览", '<p class="muted">正在读取课程与已保存的模型…</p>');
    const session = { owns: () => active === session && dialog.open && token === generation(),
      current: () => session.owns() && epoch === state.epoch && visit === navigation };
    active = session;
    let courses, route;
    try {
      const [list, selected] = await Promise.all([api("/api/courses"), api("/api/model/connection")]);
      if (!session.current()) return;
      courses = list.courses || []; route = selected.configured ? selected.model : null;
    } catch (error) { if (session.current()) status(error.message); return; }
    const body = document.getElementById("toolBody");
    body.innerHTML = `<form id="courseSynthesisForm">
      <label for="courseSynthesisScope">课程范围</label><select id="courseSynthesisScope"><option value="">请选择课程</option>${courses.map(item => `<option value="${esc(item.id)}">${esc(item.title)}</option>`).join("")}</select>
      <label for="courseSynthesisMode">综合范围</label><select id="courseSynthesisMode"><option value="question">依据最多 6 条匹配原文回答</option><option value="summary">概括全部可用原文（超出范围则停止）</option></select>
      <label for="courseSynthesisQuestion">问题或概括要求</label><textarea id="courseSynthesisQuestion" required maxlength="1000" rows="3"></textarea>
      <p id="courseSynthesisRoute" class="muted"></p><button type="button" id="courseSynthesisReload">刷新课程与所选模型</button>
      <p class="muted">本地摘录查找仍可免费离线使用。此操作需另外确认分享：最多 6 条原文、24,000 字符、1 次模型请求、3,000 输出 token；模型等待上限 30 秒，随后本地校验和用量记录可能仍需时间。可能产生费用，金额未知，本机网关也可能转发。</p>
      <button id="courseSynthesisPreview" class="primary" type="submit" disabled>预览将发送的原文</button>
    </form><div id="courseSynthesisReview" aria-live="polite"></div><div id="courseSynthesisResult" aria-live="polite"></div>
    <p class="muted">关闭仅隐藏窗口；已经发送的请求可能继续处理或计费，不会因关闭而撤回。</p>`;
    const $ = id => document.getElementById(id);
    const form = $("courseSynthesisForm"), selector = $("courseSynthesisScope"), mode = $("courseSynthesisMode"), question = $("courseSynthesisQuestion");
    const previewButton = $("courseSynthesisPreview"), review = $("courseSynthesisReview"), results = $("courseSynthesisResult");
    let sequence = 0, scope = null, approved = null;
    const current = serial => session.current() && serial === sequence;
    const routeKey = value => value ? JSON.stringify([value.base_url, value.model]) : "";
    const memberStatus = { ready: "可用", unindexed: "尚未索引", excluded: "已排除（来源不可用于本次综合）", missing: "来源已缺失", scan_incomplete: "扫描超过上限", not_scanned: "尚未扫描" };
    function routeLabel() { $("courseSynthesisRoute").textContent = route ? `已保存的模型：${route.model} · ${route.base_url}` : "尚无有效的已保存模型连接，请先在设置中连接模型。"; }
    session.sync = () => {
      if (session.current()) previewButton.disabled = !scope || !route || pending.has(scope.id);
    };
    session.invalidate = message => {
      if (!session.current()) return;
      sequence++; approved = null; review.replaceChildren(); results.replaceChildren();
      if (message) status(message);
      session.sync();
    };
    question.value = initialQuestion;
    question.addEventListener("input", () => session.invalidate("问题已变化，请重新预览。"));
    mode.addEventListener("change", () => session.invalidate("综合范围已变化，请重新预览。"));
    async function selectCourse(refreshModel = false) {
      session.invalidate();
      const serial = sequence, id = selector.value;
      scope = null; session.sync();
      try {
        if (refreshModel) {
          const selected = await api("/api/model/connection");
          if (!current(serial)) return;
          route = selected.configured ? selected.model : null; routeLabel();
        }
        if (!id) { status("请先选择课程。"); return; }
        const value = (await api(`/api/courses/${encodeURIComponent(id)}`)).course;
        if (!current(serial)) return;
        if (value?.id !== id || !Number.isInteger(value.revision) || value.revision < 1) throw new Error("课程范围不可用。");
        scope = { id, revision: value.revision, title: value.title };
        status(pending.has(id) ? "此课程的上次请求仍在处理中，请稍候。" : "预览只读取本地原文，不调用模型。");
      } catch (error) { if (current(serial)) status(error.message); }
      finally { if (current(serial)) session.sync(); }
    }
    selector.addEventListener("change", () => selectCourse());
    $("courseSynthesisReload").addEventListener("click", () => selectCourse(true));
    function paragraph(parent, text, className = "") {
      const element = document.createElement("p"); element.className = className; element.textContent = text; parent.append(element); return element;
    }
    function sourceButton(parent, citation, serial) {
      const button = document.createElement("button"); button.type = "button"; button.className = "tool-link";
      button.dataset.synthesisEvidence = citation.evidence_id;
      button.textContent = `核对原文 ${citation.source_alias}：${citation.title || "来源"}${citation.locator ? ` · ${citation.locator}` : ""}`;
      button.addEventListener("click", async event => {
        event.stopPropagation(); if (!current(serial)) return; dialog.close();
        try { await openEvidence(citation.evidence_id); } catch (error) { notice(error.message || "原文暂不可用。"); }
      });
      parent.append(button);
    }
    function renderAnswer(result, serial) {
      results.replaceChildren();
      paragraph(results, result.status === "insufficient_evidence" ? "原文不足，模型未给出可支持的结论。" : "AI 综合 · 待核对（出处校验不验证推论真假）");
      if (result.mode === "summary") paragraph(results, "概括要求引用每条已选原文；引用覆盖不保证事实完整或推论正确。", "muted");
      for (const claim of result.claims || []) {
        const section = document.createElement("section");
        paragraph(section, claim.kind === "direct_quote" ? `原文直接引用：${claim.text}` : `AI 综合 · 待核对：${claim.text}`, "answer");
        for (const support of claim.supports || []) {
          paragraph(section, `支持原句：${support.quote}`, "muted");
          if (support.citation?.evidence_id) sourceButton(section, support.citation, serial);
        }
        results.append(section);
      }
      const usage = result.usage || {};
      paragraph(results, `请求：${result.request_count || 1} 次 · 输入 token：${usage.input_tokens ?? "未知"} · 输出 token：${usage.output_tokens ?? "未知"} · 总 token：${usage.total_tokens ?? "未知"} · 金额未知`, "muted");
    }
    async function confirm(serial, value, consent, confirmButton) {
      if (!current(serial) || approved !== value || !consent.checked || !scope || pending.has(scope.id)) return;
      const selected = { ...scope };
      pending.add(selected.id); approved = null; confirmButton.disabled = true; consent.disabled = true; session.sync();
      status("正在发送一次已确认的模型请求…");
      try {
        const saved = await api("/api/model/connection");
        if (!current(serial)) return;
        if (!saved.configured || routeKey(saved.model) !== routeKey(value.connection)) throw new Error("所选模型已变化，请刷新并重新预览。");
        const result = await api(`/api/courses/${encodeURIComponent(selected.id)}/synthesis/answer`, { method: "POST", body: JSON.stringify({ preview_id: value.preview_id, fingerprint: value.fingerprint, share_source: true }) });
        if (!current(serial)) return;
        if (result.scope?.id !== selected.id || result.scope?.revision !== selected.revision || result.fingerprint !== value.fingerprint) throw new Error("返回范围已变化，本次结果不再显示。");
        review.replaceChildren(); renderAnswer(result, serial); status(result.warning || "AI 综合已返回，请核对每条原句。");
      } catch (error) { if (current(serial)) { review.replaceChildren(); status(`${error.message} 不会自动重试；请重新预览后决定是否再次发送。`); } }
      finally { pending.delete(selected.id); active?.sync?.(); }
    }
    form.addEventListener("submit", async event => {
      event.preventDefault(); event.stopPropagation();
      if (!session.current() || !scope || !route || pending.has(scope.id)) return;
      const text = question.value.trim(); if (!text) { status("请输入问题或概括要求。"); return; }
      session.invalidate(); const serial = sequence, selected = { ...scope };
      pending.add(selected.id); session.sync(); status("正在准备本地原文预览…");
      try {
        const value = await api(`/api/courses/${encodeURIComponent(selected.id)}/synthesis/preview`, { method: "POST", body: JSON.stringify({ question: text, revision: selected.revision, mode: mode.value || "question", base_url: route.base_url, model: route.model }) });
        if (!current(serial)) return;
        if (value.scope?.id !== selected.id || value.scope.revision !== selected.revision || routeKey(value.connection) !== routeKey(route)) throw new Error("预览范围或模型已变化，请刷新后重试。");
        paragraph(review, `发送目标：${value.connection.model} · ${value.connection.base_url}`);
        paragraph(review, `将发送的问题：${value.question}`);
        paragraph(review, `本次选择 ${value.coverage.selected_anchors} 条原文 / ${value.coverage.selected_characters} 字符；课程可用索引共 ${value.coverage.eligible_anchors ?? "未知"} 条 / ${value.coverage.eligible_characters ?? "未知"} 字符。${value.coverage.all_eligible_included ? "已包括全部可用索引原文。" : "仅包括匹配原文，不代表完整课程。"}`);
        for (const member of value.members || []) if (member.status !== "ready" || member.excluded || member.missing)
          paragraph(review, `课程成员 ${member.position + 1} · ${member.title}：${memberStatus[member.status] || "状态未知"}；可用 ${member.eligible ?? "未知"}，排除 ${member.excluded ?? "未知"}，缺失 ${member.missing ?? "未知"}`, "muted");
        for (const item of value.evidence || []) {
          paragraph(review, `${item.source_alias} · ${item.title} · ${item.locator || "原文"}`);
          const excerpt = document.createElement("pre"); excerpt.textContent = item.text; review.append(excerpt);
        }
        paragraph(review, value.warning, "muted");
        if (!value.can_submit) {
          status(value.blocking_reason === "course_scan_overflow" ? "本地索引扫描超过 10,000 行限制，完整数量与覆盖范围未知，未调用模型。请选择更小课程。" : value.blocking_reason?.includes("overflow") ? "全部原文超过本次限制，未抽样生成概括。请选择更小课程或使用问题检索。" : "没有足够可用原文，未调用模型。"); return;
        }
        approved = value;
        const label = document.createElement("label"), consent = document.createElement("input");
        consent.type = "checkbox"; consent.id = "courseSynthesisConsent";
        label.append(consent, document.createTextNode("我同意把上方问题和原文发送到所选地址，发起 1 次可能收费的请求（金额未知）。"));
        const confirmButton = document.createElement("button"); confirmButton.type = "button"; confirmButton.id = "courseSynthesisConfirm"; confirmButton.className = "primary"; confirmButton.disabled = true; confirmButton.textContent = "确认分享并生成一次";
        consent.addEventListener("change", () => { confirmButton.disabled = !consent.checked || approved !== value || !current(serial); });
        confirmButton.addEventListener("click", () => confirm(serial, value, consent, confirmButton));
        review.append(label, confirmButton); status("请核对原文、发送地址与费用说明，再确认一次请求。");
      } catch (error) { if (current(serial)) status(error.message); }
      finally { pending.delete(selected.id); active?.sync?.(); }
    });
    selector.value = courses.some(item => item.id === initial?.id) ? initial.id : "";
    routeLabel(); await selectCourse();
  };
}
