/* Independent learning spaces. Sources are references; FSRS cards stay global. */
(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c]));
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    const text = await response.text();
    let value = {}; try { value = JSON.parse(text); } catch { value = { detail: text }; }
    if (!response.ok) throw new Error(value.detail?.message || value.detail || "请求失败");
    return value;
  };

  async function open({ currentSource, onOpenSource, onReview } = {}) {
    const previous = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "learning-space-dialog";
    document.body.append(dialog);
    let spaces = [], space = null, tab = "sources", proposals = [];
    const status = document.createElement("p"); status.className = "learning-space-status"; status.setAttribute("role", "status");
    const body = document.createElement("div"); body.className = "learning-space-body";
    const header = document.createElement("header"); header.className = "learning-space-header";
    const title = document.createElement("h2"); title.textContent = "学习空间";
    const close = document.createElement("button"); close.type = "button"; close.textContent = "×"; close.setAttribute("aria-label", "关闭学习空间");
    header.append(title, close); dialog.append(header, body, status);
    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => { dialog.remove(); previous?.focus?.(); });
    const call = async (work) => { try { status.textContent = ""; return await work(); } catch (error) { status.textContent = error.message || "操作失败，请重试。"; return null; } };
    const button = (label, handler, className = "") => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; if (className) b.className = className; b.onclick = () => call(handler); return b; };
    function listView() {
      title.textContent = "学习空间"; body.replaceChildren();
      const intro = document.createElement("p"); intro.className = "muted"; intro.textContent = "把已有笔记、字幕和资料按目标组织起来；来源更新时只提示刷新，不复制原文。";
      const create = button("＋ 新建学习空间", () => editView(null), "primary");
      const list = document.createElement("div"); list.className = "learning-space-list";
      for (const item of spaces) {
        const row = document.createElement("button"); row.type = "button"; row.className = "learning-space-row";
        row.innerHTML = `<strong>${esc(item.title)}</strong><small>${esc(item.goal || "未设置目标")} · ${item.paused ? "已暂停" : "学习中"}</small>`;
        row.onclick = () => loadSpace(item.id); list.append(row);
      }
      if (!spaces.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "还没有学习空间。"; list.append(empty); }
      body.append(intro, create, list);
    }
    async function loadSpaces(selected = "") {
      const result = await request("/api/learning-spaces"); spaces = result.spaces || [];
      if (selected) await loadSpace(selected); else listView();
    }
    async function loadSpace(id) {
      const result = await request(`/api/learning-spaces/${encodeURIComponent(id)}`);
      space = result.space;
      tab = "sources";
      await renderSpace();
    }
    function sourcePayload() { return (space?.sources || []).map((source) => ({ kind: source.kind, id: source.id, url: source.url || "", title: source.title || "" })); }
    async function saveSpace(fields) {
      const payload = { ...fields, sources: sourcePayload(), revision: space?.revision || 0 };
      const result = await request(space ? `/api/learning-spaces/${space.id}` : "/api/learning-spaces", { method: space ? "PUT" : "POST", body: JSON.stringify(payload) });
      space = result.space; await loadSpaces(space.id);
    }
    function editView(existing) {
      space = existing ? { ...existing } : null; title.textContent = existing ? "编辑学习空间" : "新建学习空间"; body.replaceChildren();
      const form = document.createElement("form"); form.className = "learning-space-form";
      const selectedTypes = new Set(existing?.question_types || ["short_answer"]);
      form.innerHTML = `<label>名称<input name="title" required maxlength="200" value="${esc(existing?.title || "")}"></label><label>学习目标<textarea name="goal" maxlength="1000" rows="2">${esc(existing?.goal || "")}</textarea></label><label>重点与范围<textarea name="focus" maxlength="2000" rows="3">${esc(existing?.focus || "")}</textarea></label><label>每日复习量<input name="daily_review_limit" type="number" min="1" max="200" value="${Number(existing?.daily_review_limit || 10)}"></label><fieldset><legend>练习题型</legend><label class="check"><input name="question_types" value="short_answer" type="checkbox" ${selectedTypes.has("short_answer") ? "checked" : ""}>简答题</label><label class="check"><input name="question_types" value="choice" type="checkbox" ${selectedTypes.has("choice") ? "checked" : ""}>选择题</label><label class="check"><input name="question_types" value="true_false" type="checkbox" ${selectedTypes.has("true_false") ? "checked" : ""}>判断题</label><label class="check"><input name="question_types" value="fill_blank" type="checkbox" ${selectedTypes.has("fill_blank") ? "checked" : ""}>填空题</label></fieldset><label class="check"><input name="paused" type="checkbox" ${existing?.paused ? "checked" : ""}>暂停复习提醒</label><footer><button type="button" data-back>取消</button><button class="primary">保存学习空间</button></footer>`;
      form.querySelector("[data-back]").onclick = () => existing ? renderSpace() : listView();
      form.onsubmit = (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(form)); const questionTypes = [...form.querySelectorAll('input[name="question_types"]:checked')].map((input) => input.value); return call(() => saveSpace({ title: data.title, goal: data.goal, focus: data.focus, daily_review_limit: Number(data.daily_review_limit), paused: form.elements.paused.checked, question_types: questionTypes })); };
      body.append(form);
    }
    function tabs() {
      const nav = document.createElement("nav"); nav.className = "learning-space-tabs";
      for (const [id, label] of [["sources", "资料"], ["practice", "练习"], ["plan", "复习计划"]]) {
        const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.setAttribute("aria-pressed", String(tab === id)); b.onclick = () => { tab = id; renderSpace(); }; nav.append(b);
      }
      return nav;
    }
    async function renderSpace() {
      if (!space) return listView();
      body.replaceChildren(); title.textContent = space.title;
      const toolbar = document.createElement("div"); toolbar.className = "learning-space-toolbar";
      toolbar.append(button("所有空间", () => loadSpaces()), button("编辑", () => editView(space)), button(space.paused ? "继续计划" : "暂停计划", () => saveSpace({ title: space.title, goal: space.goal, focus: space.focus, daily_review_limit: space.daily_review_limit, question_types: space.question_types, paused: !space.paused })));
      body.append(toolbar, tabs());
      const panel = document.createElement("section"); panel.className = "learning-space-panel"; body.append(panel);
      if (tab === "sources") await renderSources(panel);
      if (tab === "practice") await renderPractice(panel);
      if (tab === "plan") renderPlan(panel);
    }
    async function renderSources(panel) {
      const summary = await request(`/api/learning-spaces/${space.id}/summary`);
      panel.innerHTML = `<p class="muted">${summary.source_count} 个来源 · ${summary.evidence_count} 条证据 · ${summary.card_count} 张卡片 · 待复习 ${summary.due_count} 张</p>`;
      const add = button("加入当前资料", async () => { const source = currentSource?.(); if (!source) throw new Error("请先打开一篇已有笔记或资料。"); space.sources = [...(space.sources || []), source]; await saveSpace({ title: space.title, goal: space.goal, focus: space.focus, daily_review_limit: space.daily_review_limit, question_types: space.question_types, paused: space.paused }); });
      panel.append(add);
      const list = document.createElement("div"); list.className = "learning-space-sources";
      for (const source of summary.sources || []) {
        const row = document.createElement("article"); row.innerHTML = `<strong>${esc(source.title || source.url || source.id)}</strong><small>${source.status === "stale" ? "来源已更新，建议刷新材料" : source.status === "missing" ? "来源不可用" : source.kind === "url" ? "待添加任务" : "来源引用"}</small>`;
        if (source.kind !== "url") row.append(button("打开原文", () => onOpenSource?.({ kind: source.kind, id: source.id, title: source.title })));
        list.append(row);
      }
      panel.append(list);
    }
    async function renderPractice(panel) {
      panel.innerHTML = `<p class="muted">练习题单独保存，先预览、修改，再加入复习库；不会追加到普通笔记正文。</p>`;
      const generate = button("生成练习预览", async () => { const result = await request(`/api/learning-spaces/${space.id}/practice/proposals`, { method: "POST", body: JSON.stringify({ limit: 20 }) }); proposals = result.proposals || []; renderPracticePreview(panel); });
      panel.append(generate);
      const saved = await request(`/api/learning-spaces/${space.id}/practice`); if (saved.items?.length) { const note = document.createElement("p"); note.className = "muted"; note.textContent = `已保存 ${saved.items.length} 道练习。`; panel.append(note); }
    }
    function renderPracticePreview(panel) {
      const form = document.createElement("form"); form.className = "learning-space-practice";
      form.innerHTML = proposals.map((item, index) => `<article><label class="check"><input type="checkbox" data-index="${index}" checked>加入复习</label><label>问题<textarea data-question="${index}" rows="2">${esc(item.question)}</textarea></label><label>答案<textarea data-answer="${index}" rows="3">${esc(item.answer)}</textarea></label><small>${esc((item.source_evidence_ids || []).join("、"))}</small></article>`).join("") || "<p class=\"muted\">没有足够的来源证据。</p>";
      const submit = document.createElement("button"); submit.type = "submit"; submit.className = "primary"; submit.textContent = "保存练习并加入复习"; submit.disabled = !proposals.length; form.append(submit);
      form.onsubmit = (event) => { event.preventDefault(); const items = proposals.map((item, index) => ({ ...item, question: form.querySelector(`[data-question="${index}"]`).value, answer: form.querySelector(`[data-answer="${index}"]`).value })).filter((_, index) => form.querySelector(`[data-index="${index}"]`).checked); return call(async () => { await request(`/api/learning-spaces/${space.id}/practice`, { method: "POST", body: JSON.stringify({ items }) }); await request(`/api/learning-spaces/${space.id}/review-cards`, { method: "POST", body: JSON.stringify({ cards: items }) }); status.textContent = "练习已保存，FSRS 复习记录沿用现有卡片。"; }); };
      panel.replaceChildren(form);
    }
    function renderPlan(panel) {
      const form = document.createElement("form"); form.className = "learning-space-form"; form.innerHTML = `<label>学习目标<textarea name="goal" rows="3">${esc(space.goal || "")}</textarea></label><label>重点与范围<textarea name="focus" rows="4">${esc(space.focus || "")}</textarea></label><label>每日复习量<input name="daily_review_limit" type="number" min="1" max="200" value="${Number(space.daily_review_limit || 10)}"></label><footer><button class="primary">保存复习计划</button></footer>`;
      form.onsubmit = (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(form)); return call(() => saveSpace({ title: space.title, goal: data.goal, focus: data.focus, daily_review_limit: Number(data.daily_review_limit), question_types: space.question_types, paused: space.paused })); };
      const review = button("查看待复习卡片", async () => { const result = await request(`/api/learning-spaces/${space.id}/due?limit=20`); status.textContent = `当前待复习 ${result.cards?.length || 0} 张；评分继续使用现有 FSRS。`; });
      panel.append(form, review);
    }
    dialog.showModal();
    await call(() => loadSpaces());
  }
  globalThis.LearnNoteLearningSpaces = { open };
})();
