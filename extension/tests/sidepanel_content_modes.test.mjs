import assert from "node:assert/strict";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const noSubtitles = videoContext({ subtitle: false });
const subtitles = await createSidepanelHarness({
  contexts: [noSubtitles], stored: { processingMode: "quick" }
});
assert.match(subtitles.elements.get("#modeDescription").textContent, /不下载视频.*不调用模型/);
assert.equal(subtitles.sentMessages.some(message => message.type === "preflight-current-page"), false);
assert.equal(await subtitles.api.sendToClient(), true);
const subtitleRequest = subtitles.sentMessages.find(message => message.type === "start-current-task");
assert.equal(subtitleRequest.mode, "video", "the platform lookup uses the URL task path when no complete browser captions exist");
assert.equal(subtitleRequest.options.content_mode, "subtitles", "missing subtitles must not silently enable transcription or summarization");
assert.equal(subtitleRequest.defer, true);
assert.equal(subtitleRequest.resources.length, 0);
assert.equal(subtitles.sentMessages.some(message => message.type === "preflight-current-page"), false);
assert.equal(subtitles.api.getState().selectedProcessingMode, "quick");

const shortVideo = videoContext();
shortVideo.page.active_video.duration = 5;
shortVideo.page.browser_subtitles = [{ start: 0, end: 4.8, text: "短视频也有完整的一句字幕。" }];
assert.equal(subtitles.api.hasReliableBrowserSubtitles(shortVideo), true, "short complete captions must not be rejected by a fixed minimum segment count");
shortVideo.page.browser_subtitles[0].end = 1;
assert.equal(subtitles.api.hasReliableBrowserSubtitles(shortVideo), false, "a single visible line is not a complete track just because the video is short");
const collisions = videoContext();
collisions.page.browser_subtitles = Array.from({ length: 8 }, (_, i) => ({ start: 0, end: 631, text: `播放器文字 ${i}` }));
assert.equal(subtitles.api.hasReliableBrowserSubtitles(collisions), false, "repeated timing windows are not a reliable caption track even with apparent full coverage");

const complete = videoContext();
complete.page.browser_subtitles = Array.from({ length: 12 }, (_, i) => ({ start: i * 55, end: i * 55 + 50, text: `字幕 ${i}` }));
const extraction = await createSidepanelHarness({ contexts: [complete], stored: { processingMode: "quick" } });
assert.equal(await extraction.elements.get("#sendButton").dispatch("click"), true);
const extractionRequest = extraction.sentMessages.find(message => message.type === "start-current-task");
assert.equal(extractionRequest.mode, "subtitle_only");
assert.equal(extractionRequest.options.content_mode, "subtitles");
assert.equal(extractionRequest.options.visual_understanding, false);
assert.equal(extractionRequest.defer, false);
assert.equal(extractionRequest.resources.length, 0);

extraction.api.setProcessingMode("study");
assert.equal(extraction.api.getState().currentTaskId, "", "choosing another mode allows a new task instead of leaving the send button disabled");
assert.equal(extraction.storageWrites.at(-1).processingMode, "study");
assert.match(extraction.elements.get("#modeDescription").textContent, /文字模型.*不下载视频/);
assert.equal(await extraction.api.sendToClient(), true);
assert.equal(extraction.sentMessages.filter(message => message.type === "start-current-task").at(-1).options.content_mode, "text");

const visual = await createSidepanelHarness({ contexts: [complete], stored: { processingMode: "deep" } });
assert.match(visual.elements.get("#modeDescription").textContent, /视觉模型/);
assert.equal(await visual.api.sendToClient(), true);
const visualRequest = visual.sentMessages.find(message => message.type === "start-current-task");
assert.equal(visualRequest.mode, "video", "visual mode still needs video even with complete subtitles");
assert.equal(visualRequest.options.content_mode, "visual");
assert.equal(visualRequest.options.visual_understanding, true);
assert.equal(visualRequest.defer, true);
assert.ok(visualRequest.resources.length > 0);

console.log("Explicit subtitle/text/visual modes preserve the chosen scope, skip needless video probes and retain preferences");
