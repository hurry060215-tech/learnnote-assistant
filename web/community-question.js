import { api } from "/web/desk-api.js";
import { assistantStream } from "/web/desk-chat-stream.js";

const UNVERIFIED = "观点辅助回答 · 整体未经事实验证";
const routeKey = value => JSON.stringify([value?.base_url, value?.model]);
const sourceKey = state => JSON.stringify([state.epoch, state.selected?.kind, state.selected?.id,
  state.selected?.control_generation, state.selected?.source_identity, state.selected?.transcript_path,
  state.selected?.summary_source, state.selected?.status, state.selected?.updated_at,
  state.selected?.page_url, state.selected?.source_type, state.selected?.source_task_id, state.selected?.learning_range]);

// Only the current community dialog owns this state. Never use assistant history,
// drafts, evidence actions or the ordinary answer renderer for this mixed output.
export function installCommunityQuestion({ state, dialog, generation }) {
  let active = null;
  const invalidate = () => { active?.clear(); active = null; };
  window.addEventListener("learnnote:navigation", () => {
    const owned = active?.owns(); invalidate(); if (owned) dialog.close();
  });
  window.addEventListener("learnnote:settings", () => active?.changed("模型设置已变化，请刷新模型并重新选择观点。", true));
  window.addEventListener("learnnote:metadata", () => {
    if (active && !active.sameSource()) active.changed("来源已变化，请关闭后重新打开社区观点。", true, true);
  });
  dialog.addEventListener("cancel", invalidate);
  dialog.addEventListener("close", () => { if (!dialog.open) invalidate(); });
  return { invalidate, async mount(root, source, community) {
    invalidate();
    if (!community.enabled || !community.items?.length) return;
    const token = generation(), identity = sourceKey(state);
    const section = document.createElement("details"); section.className = "section-review";
    root.append(section);
    const add = (tag, text, parent = section) => {
      const element = document.createElement(tag); element.textContent = text; parent.append(element); return element;
    };
    const summary = add("summary", "用所选观点提问（可选，需另行确认发送）");
    add("p", "先输入问题，再选择本次使用的已保存观点。默认全部不选；修改问题会清空选择。预览只在本机准备，不调用模型。回答整体未经验证，不保存到笔记或聊天历史。");
    const form = add("form", ""); form.id = "communityQuestionForm";
    const label = add("label", "本次问题", form); label.htmlFor = "communityQuestionText";
    const question = add("textarea", "", form); question.id = "communityQuestionText"; question.required = true; question.maxLength = 1000; question.rows = 3;
    const picker = add("div", "", form); picker.className = "source-picker";
    const choices = community.items.map(item => {
      const row = add("label", "", picker); row.className = "tool-choice";
      const input = add("input", "", row); input.type = "checkbox"; input.checked = false; input.dataset.opinionId = item.item_id;
      add("span", `${item.kind === "danmaku" ? "弹幕" : "评论"}：${item.text}`, row); return input;
    });
    const routeLabel = add("p", "正在读取已保存的模型…", form); routeLabel.id = "communityQuestionRoute";
    const reload = add("button", "刷新所选模型", form); reload.type = "button"; reload.id = "communityQuestionReload";
    const previewButton = add("button", "本地预览发送范围", form); previewButton.type = "submit"; previewButton.className = "primary"; previewButton.id = "communityQuestionPreview";
    const status = add("p", ""); status.id = "communityQuestionStatus"; status.setAttribute("role", "status");
    const review = add("section", ""); review.id = "communityQuestionReview";
    const result = add("section", ""); result.id = "communityQuestionResult"; result.setAttribute("aria-live", "polite");
    const cancel = add("button", "取消本次提问"); cancel.type = "button"; cancel.id = "communityQuestionCancel";
    add("p", "取消或关闭会清空本次选择与结果。未发送的预览只从此窗口丢弃，服务器令牌会到期；已发送的资料不能撤回，远端处理或计费可能继续。");
    let sequence = 0, route = null, approved = null, controller = null, expiry = null, busy = false, blocked = false;
    const session = { owns: () => active === session && token === generation() && dialog.open,
      sameSource: () => sourceKey(state) === identity,
      clear: () => clear(true, true), changed(message, resetRoute = false, block = false) {
        clear(true, true); if (resetRoute) route = null; blocked ||= block; status.textContent = message; sync();
      } };
    active = session;
    const current = serial => session.owns() && session.sameSource() && serial === sequence;
    const selected = () => choices.filter(input => input.checked).map(input => input.dataset.opinionId);
    function sync() {
      previewButton.disabled = blocked || busy || !route || !question.value.trim() || !selected().length;
      reload.disabled = blocked || busy;
      choices.forEach(input => { input.disabled = blocked; }); question.disabled = blocked;
      routeLabel.textContent = route ? `已保存的接收方：${route.model} · ${route.base_url}` : "请先连接模型，或刷新已保存的模型。";
    }
    function clear(clearChoices = false, clearQuestion = false) {
      sequence++; controller?.abort(); controller = null; clearTimeout(expiry); expiry = null;
      approved = null; busy = false; review.replaceChildren(); result.replaceChildren();
      if (clearChoices) choices.forEach(input => { input.checked = false; });
      if (clearQuestion) question.value = "";
      sync();
    }
    question.addEventListener("input", () => { clear(true); status.textContent = "问题已变化，请重新选择本次观点。"; });
    choices.forEach(input => input.addEventListener("change", () => { clear(); status.textContent = "选择已变化，请重新预览。"; }));
    cancel.addEventListener("click", () => { clear(true, true); status.textContent = "本次提问已取消；如已发送，远端处理或计费可能继续。"; question.focus(); });
    section.addEventListener("toggle", () => { if (!section.open) { clear(true, true); } });
    async function loadRoute() {
      clear(true, true); route = null; sync(); const serial = sequence;
      controller = new AbortController();
      try {
        const value = await api("/api/model/connection", { signal: controller.signal });
        if (!current(serial)) return;
        route = value.configured ? value.model : null; sync();
      } catch (error) { if (current(serial)) status.textContent = error.message; }
    }
    reload.addEventListener("click", loadRoute);
    function details(parent, title, value) {
      const element = add("details", "", parent); add("summary", title, element); add("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2), element);
    }
    function scopes(parent, value) {
      for (const [title, items, opinion] of [["本次参考的原始字幕摘录（不证明回答为真）", value.original_sources, false], ["本次选择的独立观点（非事实证据）", value.opinions, true]]) {
        const group = add("details", "", parent); add("summary", title, group);
        for (const item of items || []) {
          const timing = opinion ? (Number.isFinite(item.timestamp_seconds) ? ` · ${item.timestamp_seconds} 秒（保存的时间标记，未核实）` : "")
            : (Number.isFinite(item.start) && Number.isFinite(item.end) ? `${item.start}–${item.end} 秒` : "未标注时间的原始文本");
          add("p", opinion ? `${item.origin_label || "采集方式未记录，原始出处未核实"} · ${item.kind === "danmaku" ? "弹幕" : "评论"}${timing}` : `${item.source_id} · ${timing}`, group);
          if (opinion && item.source_uri) add("p", `保存的出处链接：${item.source_uri}`, group);
          add("pre", item.text, group);
        }
      }
    }
    async function send(value, serial, consent, button) {
      if (!current(serial) || approved !== value || !consent.checked || busy || blocked) return;
      approved = null; clearTimeout(expiry); busy = true; button.disabled = consent.disabled = true; sync();
      controller = new AbortController(); status.textContent = `${UNVERIFIED}。正在发送已确认的内容…`;
      try {
        const saved = await api("/api/model/connection", { signal: controller.signal });
        if (!current(serial)) return;
        if (!saved.configured || routeKey(saved.model) !== routeKey(value.connection)) throw new Error("接收方已变化，请刷新模型并重新预览。");
        const answer = await assistantStream(`/api/tasks/${encodeURIComponent(source.id)}/qa/stream`, {
          question: value.question, skill_id: "note.qa", selected_opinions: {
            preview_id: value.preview_id, fingerprint: value.fingerprint, selected_item_ids: value.selected_item_ids,
            base_url: value.connection.base_url, model: value.connection.model, confirm_send: true,
          },
        }, { signal: controller.signal, onStatus: () => { if (current(serial)) status.textContent = `${UNVERIFIED}。正在等待完整回答与范围校验…`; } });
        if (!current(serial)) return;
        if (answer.source !== "selected-opinions-unverified" || answer.fact_verified !== false || answer.evidence_eligible !== false || answer.persisted !== false || !Array.isArray(answer.citations) || answer.citations.length || JSON.stringify(answer.opinions) !== JSON.stringify(value.opinions) || JSON.stringify(answer.original_sources) !== JSON.stringify(value.original_sources)) throw new Error("返回结果缺少未验证边界，已丢弃。请重新预览。");
        review.replaceChildren();
        const heading = add("h3", UNVERIFIED, result); heading.tabIndex = -1;
        add("p", "包括引用原文后的推论在内，整段回答均未经事实验证；不会写入历史、笔记、复习或证据。", result);
        const text = add("p", answer.answer || "未返回回答。", result); text.className = "answer";
        scopes(result, answer); add("p", answer.warning || "请独立核对原始内容。", result);
        choices.forEach(input => { input.checked = false; }); status.textContent = "本次临时回答已返回。再次提问需重新选择、预览并确认。";
        heading.focus({ preventScroll: true }); heading.scrollIntoView({ block: "start" });
      } catch (error) {
        if (current(serial)) { review.replaceChildren(); status.textContent = `${error.message} 不会自动重新发送；请重新预览后再决定。`; }
      } finally { if (current(serial)) { busy = false; controller = null; sync(); } }
    }
    form.addEventListener("submit", async event => {
      event.preventDefault(); event.stopPropagation();
      if (!session.owns() || !session.sameSource() || busy || blocked || !route || !question.value.trim() || !selected().length) return;
      const ids = selected(), recipient = { ...route }, text = question.value.trim();
      clear(); const serial = sequence; busy = true; sync(); controller = new AbortController();
      status.textContent = "正在本机准备预览，尚未调用模型…";
      try {
        const value = await api(`/api/tasks/${encodeURIComponent(source.id)}/qa/preview`, { method: "POST", signal: controller.signal,
          body: JSON.stringify({ question: text, selected_item_ids: ids, base_url: recipient.base_url, model: recipient.model }) });
        if (!current(serial)) return;
        if (routeKey(value.connection) !== routeKey(recipient) || JSON.stringify(value.selected_item_ids) !== JSON.stringify(ids) || value.persisted !== false || typeof value.question !== "string" || !Array.isArray(value.original_sources) || !Array.isArray(value.messages) || !Array.isArray(value.opinions) || JSON.stringify(value.opinions.map(item => item.item_id)) !== JSON.stringify(ids)) throw new Error("预览范围或接收方不一致，请重新预览。");
        const heading = add("h3", "审阅本次发送范围", review); heading.tabIndex = -1;
        add("p", `接收方：${value.connection.model} · ${value.connection.base_url}。本机网关也可能转发，费用金额未知。`, review);
        add("p", `将发送的问题：${value.question}`, review);
        scopes(review, value); details(review, "实际完整发送内容（系统要求与用户内容）", value.messages);
        details(review, "本次限制与覆盖范围", { limits: value.limits, coverage: value.coverage });
        add("p", value.warning || "将生成一个整体未经验证的回答；沿用现有有界兼容重试，可能发生多次 HTTP 尝试和费用。", review);
        add("p", `预览有效期：${value.expires_in_seconds ?? 0} 秒。请检查遮盖后的文字；自动遮盖并非完整隐私检查。`, review);
        if (value.can_submit !== true) { status.textContent = "没有足够可用原始字幕，或当前范围不可发送；未调用模型。"; }
        else {
          if (!value.preview_id || !value.fingerprint || (!Number.isFinite(value.expires_in_seconds) || value.expires_in_seconds <= 0 || value.expires_in_seconds > 300)) throw new Error("预览许可不可用，请重新预览。");
          approved = value;
          const row = add("label", "", review); row.className = "tool-choice";
          const consent = add("input", "", row); consent.id = "communityQuestionConsent"; consent.type = "checkbox"; consent.checked = false;
          add("span", "仅本次同意发送上方问题、原始字幕摘录和所选观点到上述接收方，可能产生费用。回答整体未经验证且不保存。", row);
          const button = add("button", "确认发送本次提问", review); button.id = "communityQuestionSend"; button.type = "button"; button.className = "primary"; button.disabled = true;
          consent.addEventListener("change", () => { button.disabled = !consent.checked || approved !== value || !current(serial); });
          button.addEventListener("click", () => send(value, serial, consent, button));
          expiry = setTimeout(() => { if (current(serial) && approved === value) { clear(); status.textContent = "本次预览已到期，请重新预览并确认。"; } }, value.expires_in_seconds * 1000);
          status.textContent = "尚未调用模型。请核对完整内容与接收方，再勾选本次许可。";
        }
        heading.focus({ preventScroll: true }); heading.scrollIntoView({ block: "start" });
      } catch (error) { if (current(serial)) { review.replaceChildren(); status.textContent = error.message; } }
      finally { if (current(serial)) { busy = false; controller = null; sync(); } }
    });
    await loadRoute();
    return summary;
  } };
}
