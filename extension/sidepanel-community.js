/* Optional local preview UI. Opening the panel never reads community text. */
(function (root) {
  "use strict";
  function mount({ document: doc, chrome, state, text: t, now = Date.now }) {
    const panel = doc.querySelector("#communityPanel");
    if (!panel) return { sync() {}, invalidate() {} };
    const find = id => doc.querySelector("#" + id);
    const status = find("communityStatus"), list = find("communityItems"), previewButton = find("communityPreview"), save = find("communitySave"), enable = find("communityEnable"), cancel = find("communityCancel");
    let generation = 0, sequence = 0, requestId = "", reviewed = null, busy = false, saving = false, saveUncertain = false, bound = "";
    const snapshot = () => {
      const value = state();
      return { taskId: value.currentTaskId, backendUrl: value.backendUrl, targetTabId: value.displayedIdentity?.tab_id, pageUrl: value.displayedIdentity?.canonical_page_url || "", siteEpoch: value.sitePermissionEpoch };
    };
    const key = value => JSON.stringify(value);
    const selected = () => [...list.querySelectorAll("input:checked")].map(input => input.value);
    function controls() { cancel.hidden = !busy && !reviewed; save.disabled = busy || !reviewed || !selected().length; previewButton.disabled = busy; enable.disabled = busy; panel.setAttribute("aria-busy", String(busy)); }
    function invalidate(message = "community_source_changed", uncertain = saving) {
      saveUncertain ||= uncertain; generation++;
      if (requestId || reviewed) chrome?.runtime?.sendMessage({ type: "community-cancel", requestId, previewId: reviewed?.preview_id }).catch(() => {});
      requestId = ""; reviewed = null; busy = false; saving = false; list.replaceChildren(); save.hidden = true; cancel.hidden = true;
      if (message) status.textContent = t(saveUncertain ? "community_save_uncertain" : message);
      controls();
    }
    function sync() {
      const next = snapshot(), nextKey = key(next);
      if (bound && bound !== nextKey) invalidate("community_source_changed");
      bound = nextKey;
      const ready = Boolean(next.taskId && root.LearnNoteCommunitySource?.canonicalPage(next.pageUrl) && Number.isSafeInteger(next.targetTabId));
      panel.hidden = !ready;
      const origin = root.LearnNoteCommunitySource.localOrigin(next.backendUrl);
      find("communityDestination").textContent = origin ? t("community_destination", { host: origin }) : t("community_invalid_destination");
    }
    async function send(type, body, context) {
      requestId = `community-${now()}-${++sequence}`;
      const result = await chrome.runtime.sendMessage({ type, ...context, ...body, requestId });
      if (result?.error) throw Error(result.error);
      return result;
    }
    const labels = { community_context_disabled: "community_disabled", community_permission_required: "community_permission_required", community_no_visible_items: "community_empty", community_source_changed: "community_source_changed", community_preview_expired: "community_source_changed" };
    async function run(kind) {
      if (busy) return;
      sync();
      const context = snapshot(), token = ++generation, contextKey = key(context);
      if (!context.taskId || !context.pageUrl) return;
      const active = () => token === generation && contextKey === key(snapshot()) && panel.open;
      saveUncertain = false; busy = true; saving = kind === "save"; cancel.hidden = false; controls();
      status.textContent = t(kind === "save" ? "community_saving" : "community_loading");
      try {
        if (kind === "enable") {
          await send("community-settings", { enabled: true }, context);
          if (active()) status.textContent = t("community_enabled");
        } else if (kind === "preview") {
          reviewed = null; list.replaceChildren(); save.hidden = true;
          const result = await send("community-preview", {}, context);
          if (!active()) return;
          reviewed = result;
          for (const item of result.items) {
            const label = doc.createElement("label"); label.className = "community-item";
            const checkbox = doc.createElement("input"); checkbox.type = "checkbox"; checkbox.value = item.item_id; checkbox.checked = false;
            const content = doc.createElement("span"), meta = doc.createElement("small"), words = doc.createElement("span");
            meta.textContent = t(item.kind === "danmaku" ? "community_danmaku" : "community_comment") + " · " + (item.timestamp_seconds === null ? t("community_time_unknown") : t("community_seconds", { seconds: item.timestamp_seconds }));
            words.textContent = item.text; content.append(meta, words); label.append(checkbox, content); list.append(label);
          }
          save.hidden = !result.items.length;
          status.textContent = result.items.length ? t("community_review", { count: result.items.length }) : t("community_empty");
          if (result.truncated) status.textContent += " " + t("community_limited");
        } else if (kind === "save" && reviewed) {
          const ids = selected(); if (!ids.length) return;
          const result = await send("community-save", { previewId: reviewed.preview_id, fingerprint: reviewed.fingerprint, selectedItemIds: ids }, context);
          if (!active()) return;
          reviewed = null; list.replaceChildren(); save.hidden = true;
          status.textContent = t("community_saved", { count: result.stored_count });
        }
      } catch (error) {
        if (!active()) return;
        status.textContent = t(kind === "save" ? "community_save_uncertain" : labels[error.message] || "community_failed");
        if (kind === "save") { saveUncertain = true; reviewed = null; list.replaceChildren(); save.hidden = true; }
      } finally {
        if (token === generation) { busy = false; saving = false; requestId = ""; controls(); }
      }
    }
    previewButton.addEventListener("click", () => run("preview"));
    enable.addEventListener("click", () => run("enable"));
    save.addEventListener("click", () => run("save"));
    cancel.addEventListener("click", () => invalidate("community_cancelled", saving));
    list.addEventListener("change", controls);
    panel.addEventListener("toggle", () => { if (!panel.open) invalidate("community_cancelled", saving); else sync(); });
    panel.addEventListener("keydown", event => { if (event.key === "Escape") { event.preventDefault(); invalidate("community_cancelled", saving); panel.open = false; panel.querySelector("summary").focus(); } });
    chrome?.runtime?.onMessage?.addListener(message => {
      if (message.type === "site-permission-revoked" || (message.type === "current-context-updated" && ["navigation", "tab-activated"].includes(message.reason))) invalidate("community_source_changed", saving);
    });
    sync(); controls();
    return { sync, invalidate, run };
  }
  root.LearnNoteCommunityPanel = Object.freeze({ mount });
  if (root.document?.querySelector("#communityPanel") && root.__learnnoteSidepanel) {
    root.LearnNoteCommunityPanel = mount({ document, chrome: root.chrome, state: () => root.__learnnoteSidepanel.getState(), text: (key, values) => root.LearnNoteI18n.message(key, values) });
  }
})(globalThis);
