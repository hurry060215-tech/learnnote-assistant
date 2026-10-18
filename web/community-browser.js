import { escapeHtml as esc } from "/web/desk-api.js";

const sourceKey = state => JSON.stringify([state.epoch, state.selected?.kind, state.selected?.id,
  state.selected?.control_generation, state.selected?.source_identity, state.selected?.transcript_path,
  state.selected?.summary_source, state.selected?.status, state.selected?.updated_at,
  state.selected?.page_url, state.selected?.source_type, state.selected?.source_task_id, state.selected?.learning_range]);

// A single bounded page owns both the displayed rows and the optional QA picker.
export function installCommunityBrowser({ state, dialog, show, api, generation, question }) {
  let active = null;
  function invalidate() {
    active?.abort(); active = null; question.invalidate();
  }
  window.addEventListener("learnnote:navigation", () => {
    const owned = active?.owns(); invalidate(); if (owned) dialog.close();
  });
  window.addEventListener("learnnote:metadata", () => {
    if (active && !active.sameSource()) { invalidate(); dialog.close(); }
  });
  dialog.addEventListener("cancel", invalidate);
  dialog.addEventListener("close", () => { if (!dialog.open) invalidate(); });

  async function open() {
    if (!state.selected) throw new Error("请先打开一份笔记。");
    const source = { ...state.selected }, identity = sourceKey(state);
    const token = show("社区观点", "");
    dialog.dataset.sourceId = source.id;
    const root = document.getElementById("toolBody");
    const path = `/api/tasks/${encodeURIComponent(source.id)}/community-context`;
    let controller = null, serial = 0, page = null, busy = false;
    const session = { owns: () => active === session && token === generation() && dialog.open,
      sameSource: () => sourceKey(state) === identity, abort: () => { serial++; controller?.abort(); },
      changing: () => {
        session.abort(); question.invalidate(); picker.replaceChildren();
        busy = false; page = null; sync(); status.textContent = "正在更新观点；如操作失败，可刷新列表重新读取。";
      }, failed: message => {
        if (!session.owns() || !session.sameSource()) return;
        status.textContent = `${message} 请点击“刷新列表”重新读取。`;
        status.focus({ preventScroll: true }); status.scrollIntoView({ block: "center" });
      } };
    active = session;
    root.innerHTML = `<p class="muted">评论与弹幕是独立观点，不作为课程事实或复习证据。分类仅按本页关键词提示，不代表事实判断。不会自动抓取网站内容；作者身份默认省略，明显联系方式与推广内容会过滤。</p>
      <div id="communityControls"></div>
      <div class="tool-actions"><a class="tool-link" href="${path}/export" download>单独导出社区观点 ↗</a></div>
      <p>每页最多 500 条。翻页或刷新会清空本次临时问题、观点选择、发送许可与结果；已发送内容不能撤回。</p>
      <p id="communityPageStatus" role="status" tabindex="-1"></p>
      <div class="tool-actions"><button type="button" id="communityPrevious">上一页</button><button type="button" id="communityNext">下一页</button><button type="button" id="communityRefresh">刷新列表</button></div>
      <div id="communityQuestionSlot"></div><div id="communityRows" class="tool-list"></div>
      <button class="danger" data-action="clear-community">清空本任务观点</button>`;
    const $ = id => root.querySelector(`#${id}`);
    const controls = $("communityControls"), status = $("communityPageStatus"), rows = $("communityRows"), picker = $("communityQuestionSlot");
    const previous = $("communityPrevious"), next = $("communityNext"), refresh = $("communityRefresh");
    for (const button of [previous, next, refresh]) button.style.minHeight = "44px";
    function sync() {
      previous.disabled = busy || !page?.previous_cursor;
      next.disabled = busy || !page?.has_more;
      refresh.disabled = busy;
    }
    const current = request => session.owns() && session.sameSource() && request === serial;
    async function load(cursor = "", focus = false) {
      if (!session.owns() || !session.sameSource() || busy) return;
      question.invalidate(); picker.replaceChildren(); rows.replaceChildren();
      controller?.abort(); controller = new AbortController(); const request = ++serial;
      busy = true; page = null; sync(); status.textContent = "正在读取本页观点…";
      try {
        const result = await api(`${path}/page?${new URLSearchParams({ limit: "500", cursor })}`, { signal: controller.signal });
        if (!current(request)) return;
        if (result.task_id !== source.id || !Array.isArray(result.items) || result.items.length > 500
            || result.returned_count !== result.items.length || !Number.isInteger(result.total_count)
            || !Number.isInteger(result.offset) || result.offset < 0 || result.total_count < result.offset + result.items.length
            || result.has_more !== (result.offset + result.items.length < result.total_count)
            || Boolean(result.next_cursor) !== result.has_more || Boolean(result.previous_cursor) !== (result.offset > 0)
            || result.groups_scope !== "current_page_only") throw new Error("分页范围不一致，请刷新列表。");
        page = result;
        // Keep an unsaved manual-import draft when browsing existing pages.
        if (!controls.children.length || controls.dataset.enabled !== String(result.enabled)) {
          controls.dataset.enabled = String(result.enabled);
          controls.innerHTML = `<button data-action="toggle-community" data-enabled="${result.enabled}">${result.enabled ? "关闭观点层" : "启用观点层"}</button>
            ${result.enabled ? '<form id="communityForm"><label for="communityText">粘贴要保留的观点 · 每行一条</label><textarea id="communityText" required maxlength="20000"></textarea><button>保存观点</button></form>' : ""}`;
        }
        status.textContent = result.total_count ? `显示第 ${result.offset + 1}–${result.offset + result.items.length} 条，共 ${result.total_count} 条。${result.has_more ? "还有下一页。" : "已到最后一页。"}` : "尚未保存社区观点。";
        const questions = new Set(result.groups?.questions || []), disagreements = new Set(result.groups?.disagreements || []);
        rows.innerHTML = result.items.map(item => `<blockquote><small>${questions.has(item.item_id) ? "观众问题" : disagreements.has(item.item_id) ? "可能存在分歧" : "观众观点"} · ${item.kind === "danmaku" ? "弹幕" : "评论"}${item.timestamp_seconds === null ? "" : " · " + Number(item.timestamp_seconds) + " 秒"}</small><p>${esc(item.text)}</p><button data-action="delete-community-item" data-item-id="${esc(item.item_id)}">删除这条观点</button></blockquote>`).join("");
        busy = false; controller = null; sync();
        if (focus) { status.focus({ preventScroll: true }); status.scrollIntoView({ block: "center" }); }
        await question.mount(picker, source, result);
      } catch (error) {
        if (current(request)) {
          page = null; question.invalidate(); picker.replaceChildren(); rows.replaceChildren();
          status.textContent = `${error.message} 请点击“刷新列表”重新读取；本次临时选择与许可已清空。`;
        }
      } finally { if (current(request)) { busy = false; controller = null; sync(); } }
    }
    previous.addEventListener("click", () => load(page?.previous_cursor, true));
    next.addEventListener("click", () => load(page?.next_cursor, true));
    refresh.addEventListener("click", () => load("", true));
    await load();
  }
  return { open, invalidate, beginMutation: () => active?.changing(), mutationFailed: message => active?.failed(message),
    refresh: () => active?.owns() && active.sameSource() ? open() : undefined };
}
