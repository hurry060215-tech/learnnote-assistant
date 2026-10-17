/* Independent local community handoff. No media capture, cookies, or model calls. */
(function (root) {
  "use strict";
  function create({ chrome, fetch, pairingHeaders, now = Date.now, setTimeout, clearTimeout, AbortController }) {
    const epochs = new Map(), operations = new Map(), previews = new Map();
    let permissionEpoch = 0;
    const canonical = value => root.LearnNoteCommunitySource.canonicalPage(value);
    const epoch = tab => epochs.get(tab) || 0;
    const fail = code => { throw Error(code); };
    function invalidate(tab) {
      epochs.set(tab, epoch(tab) + 1);
      for (const [id, operation] of operations) if (operation.tab === tab) { operation.controller.abort(); operations.delete(id); }
      for (const [id, preview] of previews) if (preview.tab === tab) previews.delete(id);
    }
    const localBase = value => root.LearnNoteCommunitySource.localOrigin(value) || fail("community_local_backend_required");
    async function verify(scope, operation) {
      if (operation && operations.get(operation.id) !== operation) fail("community_cancelled");
      if (scope.permissionEpoch !== permissionEpoch || epoch(scope.tab) !== scope.epoch) fail("community_source_changed");
      let tab;
      try { tab = await chrome.tabs.get(scope.tab); } catch { fail("community_source_changed"); }
      if (!tab || canonical(tab.url) !== scope.page) fail("community_source_changed");
      const origin = new URL(tab.url).origin + "/*";
      if (!chrome.permissions?.contains || !(await chrome.permissions.contains({ origins: [origin] }))) fail("community_permission_required");
      if (scope.permissionEpoch !== permissionEpoch || epoch(scope.tab) !== scope.epoch || (operation && operations.get(operation.id) !== operation)) fail("community_source_changed");
    }
    async function request(scope, operation, path, method, body) {
      const headers = await pairingHeaders(scope.base, { "Content-Type": "application/json" });
      await verify(scope, operation);
      const response = await fetch(scope.base + path, { method, headers, redirect: "error", signal: operation.controller.signal, ...(body ? { body: JSON.stringify(body) } : {}) });
      const value = await response.json();
      await verify(scope, operation);
      if (!response.ok) fail(value?.detail?.code || "community_local_request_failed");
      return value;
    }
    async function handle(message, sender) {
      if (sender?.id !== chrome.runtime.id || sender.tab || sender.url?.split(/[?#]/)[0] !== chrome.runtime.getURL("sidepanel.html")) fail("community_sender_rejected");
      if (message.type === "community-cancel") {
        const operation = operations.get(message.requestId);
        operation?.controller.abort(); operations.delete(message.requestId);
        if (message.previewId) previews.delete(message.previewId);
        return { ok: true };
      }
      if (!Number.isSafeInteger(message.targetTabId) || message.targetTabId < 0 || !/^[A-Za-z0-9_-]{1,128}$/.test(message.taskId || "") || !/^[A-Za-z0-9_-]{1,128}$/.test(message.requestId || "")) fail("community_source_changed");
      const scope = { tab: message.targetTabId, page: canonical(message.pageUrl), task: message.taskId, base: localBase(message.backendUrl), epoch: epoch(message.targetTabId), permissionEpoch };
      if (!scope.page || operations.has(message.requestId) || operations.size >= 8) fail("community_source_changed");
      const operation = { id: message.requestId, tab: scope.tab, controller: new AbortController() };
      operations.set(operation.id, operation);
      const timer = setTimeout(() => { operation.controller.abort(); operations.delete(operation.id); }, 15000);
      try {
        await verify(scope, operation);
        if (message.type === "community-settings") {
          if (message.enabled !== undefined && typeof message.enabled !== "boolean") fail("community_invalid_request");
          return await request(scope, operation, "/api/study/community/settings", message.enabled === undefined ? "GET" : "PUT", message.enabled === undefined ? null : { enabled: message.enabled });
        }
        const route = `/api/tasks/${encodeURIComponent(scope.task)}/community-context`;
        if (message.type === "community-preview") {
          // Check opt-in before reading any community text.
          const settings = await request(scope, operation, "/api/study/community/settings", "GET");
          if (settings.enabled !== true) fail("community_context_disabled");
          await verify(scope, operation);
          await chrome.scripting.executeScript({ target: { tabId: scope.tab, frameIds: [0] }, files: ["community-source.js", "content-community.js"] });
          await verify(scope, operation);
          const result = await chrome.scripting.executeScript({ target: { tabId: scope.tab, frameIds: [0] }, func: expected => globalThis.LearnNoteCommunityDOM.collect({ document, view: window, pageUrl: location.href, expectedPageUrl: expected }), args: [scope.page] });
          await verify(scope, operation);
          const snapshot = result?.[0]?.result;
          if (!snapshot || canonical(snapshot.page_url) !== scope.page || !Array.isArray(snapshot.items) || snapshot.items.length > 20 || snapshot.items.some(item => typeof item.text !== "string" || item.text.length > 2000) || snapshot.items.reduce((sum, item) => sum + item.text.length, 0) > 20000) fail("community_invalid_snapshot");
          if (!snapshot.items.length) fail("community_no_visible_items");
          const preview = await request(scope, operation, route + "/preview", "POST", { page_url: scope.page, items: snapshot.items });
          if (!preview.preview_id || !preview.fingerprint || !Array.isArray(preview.items)) fail("community_invalid_preview");
          for (const [id, saved] of previews) if (saved.until <= now()) previews.delete(id);
          if (previews.size >= 32) previews.delete(previews.keys().next().value);
          previews.set(preview.preview_id, { ...scope, fingerprint: preview.fingerprint, until: now() + 300000 });
          return { ...preview, truncated: snapshot.truncated };
        }
        if (message.type === "community-save") {
          const saved = previews.get(message.previewId);
          if (!saved || saved.until <= now() || saved.fingerprint !== message.fingerprint || ["tab", "page", "task", "base", "epoch", "permissionEpoch"].some(key => saved[key] !== scope[key])) fail("community_preview_expired");
          if (!Array.isArray(message.selectedItemIds) || !message.selectedItemIds.length || message.selectedItemIds.length > 20) fail("community_selection_required");
          previews.delete(message.previewId);
          return await request(scope, operation, route + "/save", "POST", { preview_id: message.previewId, fingerprint: message.fingerprint, selected_item_ids: message.selectedItemIds });
        }
        fail("community_invalid_request");
      } finally { clearTimeout(timer); operations.delete(operation.id); }
    }
    return { handle, invalidate, revoke() { permissionEpoch++; for (const operation of operations.values()) operation.controller.abort(); operations.clear(); previews.clear(); } };
  }
  root.LearnNoteCommunityTransport = Object.freeze({ create });
  if (root.chrome?.runtime?.id) {
    const transport = create({ chrome, fetch: (...args) => fetch(...args), pairingHeaders: (...args) => root.pairingHeaders(...args), setTimeout, clearTimeout, AbortController });
    chrome.runtime.onMessage.addListener((message, sender, respond) => {
      if (!["community-settings", "community-preview", "community-save", "community-cancel"].includes(message?.type)) return;
      transport.handle(message, sender).then(respond, error => respond({ error: /^community_[a-z_]+$/.test(error?.message) ? error.message : "community_request_failed" }));
      return true;
    });
    chrome.tabs.onUpdated.addListener((id, change) => { if (change.status === "loading" || change.url) transport.invalidate(id); });
    chrome.tabs.onRemoved.addListener(id => transport.invalidate(id));
    for (const event of [chrome.webNavigation?.onCommitted, chrome.webNavigation?.onHistoryStateUpdated]) event?.addListener(details => { if (details.frameId === 0) transport.invalidate(details.tabId); });
    chrome.permissions?.onRemoved?.addListener(() => transport.revoke());
  }
})(globalThis);
