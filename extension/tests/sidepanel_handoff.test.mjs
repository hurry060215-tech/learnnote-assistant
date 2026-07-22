import assert from "node:assert/strict";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const page = videoContext();
const harness = await createSidepanelHarness({ contexts: [page, page, page] });
const sent = await harness.api.sendToClient();

assert.equal(sent, true);
const preflightMessages = harness.sentMessages.filter(item => item.type === "preflight-current-page");
const startMessage = harness.sentMessages.find(item => item.type === "start-current-task");
assert.ok(preflightMessages.length >= 2, "initial and send-time preflight should both run");
assert.ok(startMessage, "task handoff should be sent");
assert.equal(startMessage.defer, true);
assert.equal(startMessage.targetTabId, 7);
assert.equal(startMessage.sourceIdentity.tab_id, 7);
assert.equal(startMessage.sourceIdentity.canonical_page_url, "https://www.bilibili.com/video/BV1ABCDEF123?p=1");
assert.equal(startMessage.sourceIdentity.platform, "bilibili");
assert.equal(startMessage.sourceIdentity.platform_video_id, "BV1ABCDEF123");
assert.equal(startMessage.sourceIdentity.BVID, "BV1ABCDEF123");
assert.equal(startMessage.sourceIdentity.page_title, "示例课程");
assert.match(startMessage.sourceIdentity.active_video.current_src, /video\.m4s/);
assert.match(startMessage.sourceIdentity.resource_fingerprint, /^[0-9a-f]{8}$/);
assert.match(startMessage.sourceIdentity.captured_at, /^\d{4}-\d{2}-\d{2}T/);
assert.equal(harness.elements.get("#handoffProgress").getAttribute("aria-valuenow"), "100");
assert.equal(harness.progressBar.style.width, "100%");
assert.equal(harness.elements.get("#handoffStatus").textContent, "已发送，等待在客户端确认。");
assert.equal(harness.elements.get("#openTaskButton").hidden, false);

const switched = videoContext({ bvid: "BV9SWITCHED99", title: "另一节课" });
const staleHarness = await createSidepanelHarness({ contexts: [page, switched] });
const staleSent = await staleHarness.api.sendToClient();
assert.equal(staleSent, false);
assert.equal(staleHarness.sentMessages.some(item => item.type === "start-current-task"), false);
assert.equal(staleHarness.elements.get("#handoffProgress").getAttribute("aria-valuenow"), "0");
assert.match(staleHarness.elements.get("#handoffStatus").textContent, /页面或播放内容已切换/);
assert.match(staleHarness.elements.get("#preflightMessage").textContent, /旧预检已清除|旧预检结果/);
