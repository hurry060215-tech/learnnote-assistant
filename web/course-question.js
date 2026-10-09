import { api, escapeHtml as esc } from "/web/desk-api.js";

// A reply belongs to one dialog visit, course revision and reader navigation.
export function installCourseQuestion({ state, dialog, show, status, generation, openEvidence, notice }) {
  const pending = new Set();
  let navigation = 0, active = null;
  window.addEventListener("learnnote:navigation", () => {
    if (active?.ownsDialog()) dialog.close();
    navigation++;
    active = null;
  });
  dialog.addEventListener("cancel", () => { active = null; });

  return async function openCourseQuestion(initialCourse) {
    const visit = navigation, epoch = state.epoch;
    const token = show("在课程中提问", '<p class="muted">正在读取课程范围…</p>');
    const session = { ownsDialog: () => active === session && dialog.open && token === generation(),
      current: () => session.ownsDialog() && visit === navigation && epoch === state.epoch };
    active = session;
    let courses;
    try {
      courses = (await api("/api/courses")).courses || [];
      if (!session.current()) return;
    } catch (error) {
      if (session.current()) status(error.message);
      return;
    }
    const body = document.getElementById("toolBody");
    body.innerHTML = `<form id="courseQuestionForm">
      <label for="courseQuestionScope">提问范围 · 选择课程</label>
      <select id="courseQuestionScope"><option value="">请选择课程</option>${courses.map(item => `<option value="${esc(item.id)}">${esc(item.title)}</option>`).join("")}</select>
      <button id="courseQuestionReload" type="button">刷新课程范围</button>
      <p id="courseQuestionScopeHint" class="muted"></p>
      <p class="muted">仅查找所选课程中的本地原文摘录，不使用 AI 综合生成答案。未整理或已删除的来源可能没有可用出处。</p>
      <label for="courseQuestionText">你的问题或关键词</label>
      <textarea id="courseQuestionText" required maxlength="1000" rows="3" placeholder="这门课程如何解释这个概念？"></textarea>
      <button id="courseQuestionSubmit" class="primary" type="submit" disabled>在所选课程中查找</button>
    </form><div id="courseQuestionResult" aria-live="polite"></div>`;
    const $ = id => document.getElementById(id);
    const form = $("courseQuestionForm"), selector = $("courseQuestionScope"), question = $("courseQuestionText");
    const submit = $("courseQuestionSubmit"), hint = $("courseQuestionScopeHint"), resultView = $("courseQuestionResult");
    let scope = null, sequence = 0;
    const current = serial => session.current() && serial === sequence;
    session.syncPending = () => {
      if (session.current()) submit.disabled = !scope || pending.has(scope.id);
    };
    async function selectCourse() {
      if (!session.current()) return;
      const serial = ++sequence, id = selector.value;
      scope = null;
      resultView.replaceChildren();
      submit.disabled = true;
      hint.textContent = "";
      status(id ? "正在确认课程来源…" : courses.length ? "请先选择课程。" : "还没有课程，请返回课程列表新建课程。");
      if (!id) return;
      try {
        const selected = (await api(`/api/courses/${encodeURIComponent(id)}`)).course;
        if (!current(serial)) return;
        if (selected?.id !== id || !Number.isInteger(selected.revision) || selected.revision < 1)
          throw new Error("课程范围暂不可用，请重新选择课程。");
        scope = { id, title: selected.title, revision: selected.revision };
        hint.textContent = `当前范围：${scope.title} · 仅此课程的原文出处`;
        status(pending.has(id) ? "此课程的上次查找仍在处理中，请稍候。" : "");
        session.syncPending();
      } catch (error) {
        if (current(serial)) status(`${error.message} 请刷新课程列表后重新选择。`);
      }
    }
    selector.addEventListener("change", selectCourse);
    $("courseQuestionReload").addEventListener("click", selectCourse);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      event.stopPropagation();
      if (!session.current() || !scope || pending.has(scope.id)) return;
      const text = question.value.trim();
      if (!text) { status("请输入问题或关键词。"); return; }
      const selected = { ...scope }, serial = sequence;
      pending.add(selected.id);
      session.syncPending();
      resultView.replaceChildren();
      status("正在查找这门课程的本地原文…");
      try {
        const result = await api(`/api/courses/${encodeURIComponent(selected.id)}/ask`, {
          method: "POST", body: JSON.stringify({ question: text, revision: selected.revision, limit: 6, mode: "lexical" }),
        });
        if (!current(serial)) return;
        if (result.scope?.kind !== "course" || result.scope.id !== selected.id || result.scope.revision !== selected.revision)
          throw new Error("返回的课程范围已变化，请重新选择课程后再提问。");
        const answer = document.createElement("p");
        answer.className = "answer";
        answer.textContent = result.answer || "这门课程中没有找到匹配原文。请换用更具体的关键词。";
        resultView.append(answer);
        for (const citation of result.citations || []) {
          if (!citation.evidence_id) continue;
          const source = document.createElement("button");
          source.type = "button";
          source.className = "tool-link";
          source.dataset.courseEvidence = citation.evidence_id;
          source.dataset.sourceKind = citation.source_kind || "";
          source.dataset.sourceId = citation.source_id || "";
          source.dataset.locator = citation.locator || "";
          if (citation.start != null) source.dataset.start = String(citation.start);
          if (citation.end != null) source.dataset.end = String(citation.end);
          source.textContent = `核对原文：${citation.title || "未命名来源"}${citation.locator ? ` · ${citation.locator}` : ""}`;
          source.addEventListener("click", async event => {
            event.stopPropagation();
            if (!current(serial)) return;
            dialog.close();
            try { await openEvidence(citation.evidence_id); }
            catch (error) { notice(error.message || "引用出处暂不可用。"); }
          });
          resultView.append(source);
        }
        status(result.grounded ? "已显示本地原文摘录，可逐条核对出处。" : "此课程中没有足够的原文证据，请调整关键词或检查课程来源。");
      } catch (error) {
        if (current(serial)) {
          scope = null;
          hint.textContent = "课程范围需要重新确认。";
          status(`${error.message} 请刷新课程范围或重新选择课程后再提问。`);
        }
      } finally {
        pending.delete(selected.id);
        active?.syncPending?.();
      }
    });
    selector.value = courses.some(item => item.id === initialCourse?.id) ? initialCourse.id : "";
    await selectCourse();
  };
}
