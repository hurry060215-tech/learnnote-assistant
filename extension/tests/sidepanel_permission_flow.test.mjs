import assert from "node:assert/strict";
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
