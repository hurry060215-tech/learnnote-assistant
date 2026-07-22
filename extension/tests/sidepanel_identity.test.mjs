import assert from "node:assert/strict";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const first = videoContext();
const harness = await createSidepanelHarness({ contexts: [first] });
const identity = harness.api.buildSourceIdentity(first, Date.UTC(2026, 6, 22, 4, 0, 0));

assert.deepEqual(Object.keys(identity), [
  "tab_id", "canonical_page_url", "platform", "platform_video_id", "BVID", "page_title",
  "active_video", "resource_fingerprint", "captured_at"
]);
assert.equal(identity.tab_id, 7);
assert.equal(identity.canonical_page_url, "https://www.bilibili.com/video/BV1ABCDEF123?p=1");
assert.equal(identity.platform, "bilibili");
assert.equal(identity.platform_video_id, "BV1ABCDEF123");
assert.equal(identity.BVID, "BV1ABCDEF123");
assert.equal(identity.page_title, "示例课程");
assert.match(identity.active_video.current_src, /video\.m4s/);
assert.equal(identity.captured_at, "2026-07-22T04:00:00.000Z");

const renewedTokens = videoContext({
  resource: "https://cdn.example.com/video.m4s?token=renewed"
});
renewedTokens.resources[1].url = "https://cdn.example.com/audio.m4s?token=renewed";
assert.equal(harness.api.resourceFingerprint(first.page, first.resources), harness.api.resourceFingerprint(renewedTokens.page, renewedTokens.resources));

const switched = videoContext({ bvid: "BV9SWITCHED99", title: "另一节课" });
assert.equal(harness.api.sameSourceIdentity(identity, harness.api.buildSourceIdentity(switched)), false);
assert.equal(harness.integrityItems.get("video").strong.textContent, "已检测");
assert.equal(harness.integrityItems.get("audio").strong.textContent, "已检测");
assert.equal(harness.integrityItems.get("subtitle").strong.textContent, "已检测");

const activated = videoContext({ tabId: 9, bvid: "BV9SWITCHED99", title: "另一标签页" });
const activationHarness = await createSidepanelHarness({ contexts: [first, activated] });
activationHarness.emit({ type: "current-context-updated", reason: "tab-activated", tabId: 9 });
await new Promise(resolve => setTimeout(resolve, 520));
const activationCollect = activationHarness.sentMessages.filter(item => item.type === "get-current-context").at(-1);
assert.equal(activationCollect.targetTabId, 9);
assert.equal(activationHarness.api.getState().displayedIdentity.tab_id, 9);
