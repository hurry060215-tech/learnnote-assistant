import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const page = videoContext({ subtitle: false });
const offline = await createSidepanelHarness({
  contexts: [page],
  health: new Error("client offline"),
  permissions: { granted: false }
});
assert.equal(await offline.api.sendToClient(), false);
assert.deepEqual(offline.permissionRequests, [], "an offline workbench must not trigger a site permission prompt");

const denied = await createSidepanelHarness({
  contexts: [page],
  permissions: { granted: false, requestResult: false }
});
assert.equal(
  denied.sentMessages.some(message => message.type === "preflight-current-page"),
  false,
  "an ungranted site must not send page candidates to the local backend for preflight"
);
assert.match(denied.elements.get("#preflightMessage").textContent, /授权/);
assert.equal(await denied.api.sendToClient(), false);
assert.deepEqual(denied.permissionRequests, [{ origins: ["https://www.bilibili.com/*"] }]);
assert.equal(
  denied.sentMessages.some(message => message.type === "start-current-task"),
  false,
  "denying site access must not create a task"
);

const allowed = await createSidepanelHarness({
  contexts: [page, page],
  permissions: { granted: false, requestResult: true }
});
assert.equal(await allowed.api.sendToClient(), true);
assert.deepEqual(allowed.permissionRequests, [{ origins: ["https://www.bilibili.com/*"] }]);
assert.equal(
  allowed.sentMessages.some(message => message.type === "start-current-task"),
  true,
  "an explicit grant allows the user-triggered task handoff"
);

const revoked = await createSidepanelHarness({ contexts: [page] });
assert.equal(revoked.api.getState().displayedIdentity.canonical_page_url, "https://www.bilibili.com/video/BV1ABCDEF123?p=1");
revoked.emit({ type: "site-permission-revoked", origin: "https://www.bilibili.com/*" });
assert.equal(revoked.api.getState().currentContext, null);
assert.equal(revoked.api.getState().displayedIdentity, null);
assert.equal(revoked.api.getState().sitePermissionEpoch, 1);
assert.match(revoked.elements.get("#preflightMessage").textContent, /授权已撤销/);

assert.equal(
  allowed.api.sitePermissionPattern("https://www.bilibili.com:8443/video/BV1ABCDEF123"),
  "https://www.bilibili.com/*"
);
assert.equal(
  allowed.api.permissionPatternMatchesPage(
    "https://www.bilibili.com/*",
    "https://www.bilibili.com:8443/video/BV1ABCDEF123"
  ),
  true
);

console.log("Permission denial blocks preflight and task creation; grants send the task; revocation clears active cues.");

// Revoking while a refresh is pending must clear its result and unlock Refresh.
let finishRefresh;
const refreshRace = await createSidepanelHarness({
  contexts: [page, () => new Promise(resolve => { finishRefresh = resolve; })]
});
const refresh = refreshRace.api.collectContext(true);
assert.equal(refreshRace.elements.get("#refreshButton").disabled, true);
refreshRace.emit({ type: "site-permission-revoked", origin: "https://www.bilibili.com/*" });
assert.equal(refreshRace.elements.get("#refreshButton").disabled, false);
finishRefresh(page);
assert.equal(await refresh, null);
assert.equal(refreshRace.api.getState().currentContext, null);

// An old preflight cannot repopulate the panel after revoke and re-read of the same video.
let finishPreflight;
const preflightRace = await createSidepanelHarness({
  contexts: [page],
  preflight: () => new Promise(resolve => { finishPreflight = resolve; })
});
preflightRace.emit({ type: "site-permission-revoked", origin: "https://www.bilibili.com/*" });
await preflightRace.api.collectContext(true);
finishPreflight({ report: { ready: true, message: "stale preflight" } });
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(preflightRace.api.getState().preflightReport, null);
console.log("Revocation releases a pending Refresh and rejects stale preflights after re-grant");

// Extension APIs can throw before returning a promise (for example after reload).
const syncFailure = await createSidepanelHarness({ contexts: [page] });
syncFailure.context.resetSourceState();
syncFailure.context.chrome.runtime.sendMessage = () => { throw new Error("Extension context invalidated"); };
assert.equal(await syncFailure.context.runPreflight(), null);
assert.match(syncFailure.elements.get("#preflightMessage").textContent, /Extension context invalidated/);
assert.equal(await syncFailure.context.runPreflight(), null, "a synchronous failure must not leave a pending request");
console.log("Synchronous preflight API failures remain recoverable");

// An accepted task survives revocation, while every page-bound source is cleared.
// Load the actual companion module so renderContext also cancels its reviewed preview.
const accepted = await createSidepanelHarness({ contexts: [videoContext(), videoContext()],
  beforeLoad(context, {elements}) {
    for (const id of ['communityPanel', 'communityStatus', 'communityItems', 'communityPreview', 'communitySave', 'communityEnable', 'communityCancel', 'communityDestination']) {
      elements.set('#' + id, context.document.createElement('div'));
    }
    elements.get('#communityPanel').open = true;
    elements.get('#communityItems').querySelectorAll = () => []; // No items are selected in this regression.
  }
});
assert.equal(await accepted.api.sendToClient(), true);
const acceptedTask = accepted.api.getState().currentTaskId;
const originalKey = accepted.api.sourceContinuityKey(accepted.api.getState().displayedIdentity);
assert(originalKey);
assert.equal(accepted.api.sourceContinuityKey(null), '');
assert.equal(accepted.api.sourceContinuityKey(undefined), '');
assert.equal(accepted.api.sourceContinuityKey(), '');
assert.notEqual(originalKey, accepted.api.sourceContinuityKey(null));
assert.equal(accepted.api.sourceContinuityKey({tab_id: 7, canonical_page_url: 'https://example.test/lesson',
  platform: 'generic', platform_video_id: 'video-id', active_video: {current_src: 'https://cdn.example.test/video.mp4'}}),
  ['7', 'https://example.test/lesson', 'generic', 'video-id', 'https://cdn.example.test/video.mp4'].join('\u001f'));
const baseSend = accepted.context.chrome.runtime.sendMessage, communityCalls = [];
accepted.context.chrome.runtime.sendMessage = async message => {
  if (!message.type.startsWith('community-')) return baseSend(message);
  communityCalls.push(message);
  if (message.type === 'community-cancel') return {ok: true};
  assert.equal(message.type, 'community-preview');
  return {preview_id: 'a'.repeat(64), fingerprint: 'b'.repeat(64), items: [
    {item_id: 'c'.repeat(32), kind: 'comment', text: 'Synthetic reviewed perspective', timestamp_seconds: null}
  ]};
};
for (const name of ['community-source.js', 'sidepanel-community.js']) {
  vm.runInContext(await readFile(new URL('../' + name, import.meta.url), 'utf8'), accepted.context);
}
await accepted.context.LearnNoteCommunityPanel.run('preview');
assert.equal(accepted.elements.get('#communityItems').children.length, 1);
const messagesBeforeRevoke = accepted.sentMessages.length;
assert.doesNotThrow(() => accepted.emit({type: 'site-permission-revoked', origin: 'https://www.bilibili.com/*'}));
const cleared = accepted.api.getState();
assert.equal(cleared.currentTaskId, acceptedTask, 'Previously accepted task remains accessible');
assert.equal(cleared.currentContext, null); assert.equal(cleared.displayedIdentity, null);
assert.equal(cleared.preflightReport, null); assert.equal(cleared.sitePermissionEpoch, 1);
assert.equal(accepted.elements.get('#sendButton').disabled, true);
assert.equal(accepted.elements.get('#openTaskButton').hidden, false);
assert.equal(accepted.elements.get('#quickResultCard').hidden, true);
assert.equal(accepted.elements.get('#progressiveCard').hidden, true);
assert.equal(accepted.elements.get('#communityPanel').hidden, true);
assert.equal(accepted.elements.get('#communityItems').children.length, 0);
assert(communityCalls.some(message => message.type === 'community-cancel' && message.previewId === 'a'.repeat(64)));
assert.match(accepted.elements.get('#preflightMessage').textContent, /授权已撤销/);
assert.doesNotThrow(() => accepted.emit({type: 'site-permission-revoked', origin: 'https://www.bilibili.com/*'}));
assert.equal(accepted.api.getState().sitePermissionEpoch, 1, 'Repeated event has no source left to invalidate');
assert.equal(await accepted.api.sendToClient(), false);
assert.equal(await accepted.api.runPreflight(), null);
assert.equal(await accepted.api.openClient('task', acceptedTask, 'note'), true);
assert(accepted.openedTabs.at(-1).url.includes(acceptedTask), 'Accepted task remains openable after source invalidation');
assert.equal(accepted.sentMessages.length, messagesBeforeRevoke, 'Revocation cannot recollect or resend the old page');
assert.deepEqual(accepted.permissionRequests, []);

for (const outcome of ['answer', 'error']) {
  let release, reject, arrived;
  const arrival = new Promise(resolve => { arrived = resolve; });
  const pending = await createSidepanelHarness({ contexts: [videoContext(), videoContext()],
    fetchOverride(url) {
      if (!url.endsWith('/qa')) return null;
      return new Promise((resolve, fail) => { release = resolve; reject = fail; arrived(); });
    }
  });
  assert.equal(await pending.api.sendToClient(), true);
  pending.elements.get('#quickAskQuestion').value = 'Synthetic question';
  const question = pending.elements.get('#quickAskForm').dispatch('submit');
  let timer;
  try {
    await Promise.race([arrival, new Promise((_, fail) => { timer = setTimeout(() => fail(Error('Synthetic Q&A request did not arrive')), 3000); })]);
    assert.doesNotThrow(() => pending.emit({type: 'site-permission-revoked', origin: 'https://www.bilibili.com/*'}));
  } finally {
    clearTimeout(timer);
    if (outcome === 'answer') release?.({ok: true, json: async () => ({answer: 'STALE_ANSWER_AFTER_REVOKE'})});
    else reject?.(Error('STALE_ERROR_AFTER_REVOKE'));
  }
  await question;
  assert(!pending.elements.get('#quickAskConversation').children.some(item => /STALE_/.test(item.innerHTML)));
  assert.equal(pending.elements.get('#quickAskQuestion').value, '');
  assert.equal(pending.elements.get('#quickAskForm').getAttribute('aria-busy'), 'false');
  assert.equal(pending.api.getState().displayedIdentity, null);
  assert.deepEqual(pending.permissionRequests, []);
}
console.log('Accepted-task revocation cancels community preview and settles stale Q&A without source reuse or null identity errors');
