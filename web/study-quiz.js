/* Shared local cloze UI. A reveal is not an answer; self-ratings never score it. */
(() => {
  function mount({container, cardId, request, isCurrent = () => true, onSource, onQuestionState = () => {}}) {
    const root = document.createElement("section"); root.className = "objective-quiz proposal";
    const title = document.createElement("h4"); title.textContent = "原文填空 · 本机核对";
    const hint = document.createElement("p"); hint.className = "muted";
    hint.textContent = "按原文填入术语；忽略大小写，去除首尾空白并合并连续空白。近义表达不计匹配，结果不代表理解程度。";
    const status = document.createElement("p"); status.setAttribute("role", "status"); status.textContent = "正在检查可核对的原文…";
    root.append(title, hint, status); container.append(root);
    let disposed = false, revealed = false, pending = false, completed = false, submission = null;
    const current = () => !disposed && root.isConnected && isCurrent();
    const path = `/api/study/cards/${encodeURIComponent(cardId)}`;
    const viewKey = globalThis.crypto.randomUUID();
    const post = body => ({method: "POST", body: JSON.stringify(body)});
    const view = request("/api/study/activity", post({kind: "reading", source_id: `card:${cardId}`, idempotency_key: viewKey})).catch(() => {});
    let input, submit;
    const reveal = () => {
      revealed = true;
      if (input) input.disabled = true;
      if (submit) submit.disabled = true;
      if (!completed && !pending && current()) status.textContent = "已查看答案或跳过填空，本次未记录客观作答。";
      onQuestionState(false);
    };
    const ready = request(`${path}/quiz`).then(question => {
      if (!current() || revealed) return;
      if (!question.available) {
        status.textContent = "没有可精确核对的填空题；可继续自我解释与自评，不计客观正确率。";
        onQuestionState(false); return;
      }
      onQuestionState(true);
      const prompt = document.createElement("p"); prompt.className = "quiz-question source-excerpt"; prompt.textContent = question.question;
      const form = document.createElement("form"); form.className = "quiz-answer-form";
      const label = document.createElement("label"); label.textContent = "原文中的术语";
      input = document.createElement("input"); input.type = "text"; input.maxLength = 128; input.required = true; input.autocomplete = "off"; input.setAttribute("aria-label", "原文中的术语");
      submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "核对填空";
      label.append(input); form.append(label, submit); root.insertBefore(prompt, status); root.insertBefore(form, status); status.textContent = "";
      form.onsubmit = async event => {
        event.preventDefault();
        if (!current() || pending || completed || revealed) return;
        if (!input.value.trim()) { status.textContent = "请填入术语，或继续下方自我解释。"; return; }
        // A retry keeps both the logical submission key and original answer.
        submission ||= {question_revision: question.question_revision, answer: input.value, idempotency_key: globalThis.crypto.randomUUID()};
        pending = true; input.disabled = true; submit.disabled = true; status.textContent = "正在本机核对…";
        try {
          const {attempt} = await request(`${path}/answer`, post(submission));
          if (!current()) return;
          completed = true;
          status.textContent = `${attempt.correct ? "填空正确" : "填空未匹配原文"}；原文答案：${attempt.expected_answer}。已单独保存本次作答，下方记忆评分仍由你自评。`;
          onQuestionState(false);
          for (const id of attempt.source_evidence_ids || []) {
            const source = document.createElement("button"); source.type = "button"; source.textContent = "回原文核对";
            source.onclick = () => onSource?.(id); root.append(source);
          }
        } catch (error) {
          if (!current()) return;
          status.textContent = error?.message || "核对响应未确认；可重试同一次作答，或关闭后查看学习记录。";
          if (!revealed) { submit.disabled = false; submit.textContent = "重试此次作答"; }
        } finally { pending = false; }
      };
    }).catch(error => {
      if (!current()) return;
      status.textContent = error?.message || "填空题暂不可用；仍可自我解释与自评。";
      onQuestionState(false);
    });
    return {reveal, ready, view, dispose: () => { disposed = true; }};
  }

  function measuresText(measures = {}) {
    return `全部本地累计记录：阅读/看过 ${Number(measures.reading_events || 0)} 次 · 客观填空 ${Number(measures.correct_answers || 0)} / ${Number(measures.objective_attempts || 0)} 次匹配原文 · 自我解释 ${Number(measures.self_explanations || 0)} 次 · 记忆自评 ${Number(measures.self_ratings || 0)} 次。历史未评分作答 ${Number(measures.unscored_answer_events || 0)} 次，正确性未知。`;
  }
  globalThis.LearnNoteQuiz = {mount, measuresText};
})();
