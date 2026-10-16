/* Called by the evidence-source Edge gate after opening its synthetic media task. */
const assert = require("node:assert/strict"), path = require("node:path");
async function readTranscriptCueAccessibility(page, cues, index) {
  const session = await page.context().newCDPSession(page);
  try {
    const { root } = await session.send("DOM.getDocument");
    const selector = `#sourceContent .cue[data-cue-index="${index}"][aria-current="time"]`;
    const { nodeId } = await session.send("DOM.querySelector", { nodeId: root.nodeId, selector });
    assert(nodeId, "The semantic current cue exists in the browser DOM");
    const { node } = await session.send("DOM.describeNode", { nodeId });
    const { nodes } = await session.send("Accessibility.getPartialAXTree", { backendNodeId: node.backendNodeId, fetchRelatives: false });
    const accessible = nodes.find(item => item.backendDOMNodeId === node.backendNodeId);
    assert(accessible && !accessible.ignored, "The current cue is exposed in the browser accessibility tree");
    assert.equal(accessible.role?.value, "button");
    const seconds = Math.max(0, Math.floor(Number(cues[index].start) || 0));
    const clock = seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`
      : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    const expectedName = `${index + 1}/${cues.length} · ${clock} · ${String(cues[index].text || "")}`;
    assert.equal(accessible.name?.value, expectedName, "Accessible name includes cue position, source time and exact text");
    const focusable = accessible.properties?.find(property => property.name === "focusable")?.value?.value;
    assert.equal(focusable, true, "The browser exposes the cue as keyboard-focusable");
    // CDP's AXPropertyName does not expose aria-current; verify that state in DOM.
    assert.equal(await page.locator(selector).getAttribute("aria-current"), "time");
    return { cue_index: index, role: accessible.role.value, name: accessible.name.value, focusable, aria_current: "time" };
  } finally {
    await session.detach();
  }
}
async function assertTranscriptKeyboardAcceptance(page, { taskId, out }) {
  const response = await page.request.get(new URL(`/api/tasks/${taskId}/transcript`, page.url()).href);
  assert(response.ok(), "Synthetic transcript is available");
  const { segments: cues } = await response.json();
  assert(cues.length > 160, "Keyboard acceptance must exercise virtualization");
  const transcript = page.locator("#sourceTranscript"), follow = page.locator("#followTranscript");
  const rows = page.locator("#sourceContent .cue"), semantic = page.locator('#sourceContent .cue[aria-current="time"]');
  const player = page.locator("#player"), outside = page.locator("#followNote");
  const previous = await player.evaluate(node => ({ time: node.currentTime, rate: node.playbackRate, muted: node.muted }));
  const previousFollow = await follow.isChecked(), accessibility = [];
  const seek = async time => {
    await player.evaluate((node, value) => { node.currentTime = value; }, time);
    await page.waitForFunction(value => Math.abs(document.querySelector("#player").currentTime - value) < .1, time);
  };
  const expectedIndex = time => cues.findLastIndex(cue => Number(cue.start) <= time);
  const assertBounded = async () => assert(await rows.count() < 80, "Focused and keyboard windows keep bounded DOM rows");
  const assertCurrent = async index => {
    await page.waitForFunction(index => document.querySelector('#sourceContent .cue[aria-current="time"]')?.dataset.cueIndex === String(index), index);
    assert.equal(await semantic.count(), 1, "Exactly one mounted cue exposes current time");
    assert.equal(await page.locator("#sourceContent .cue.active").count(), 1);
    assert.equal(await semantic.evaluate(node => node.classList.contains("active")), true);
    assert.match(await semantic.getAttribute("aria-label"), new RegExp(`^${index + 1}/${cues.length} · `));
  };
  const assertFocused = async index => {
    await page.waitForFunction(index => document.activeElement?.dataset.cueIndex === String(index), index);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(() => document.activeElement?.dataset.cueIndex), String(index),
      "Keyboard focus survives deferred scroll events and layout");
    await assertBounded();
  };
  try {
    if (!await transcript.evaluate(node => node.open)) await transcript.locator("summary").click();
    await follow.check();
    await seek(.05); await assertCurrent(0);
    accessibility.push(await readTranscriptCueAccessibility(page, cues, 0));
    const first = page.locator('#sourceContent .cue[data-cue-index="0"]');
    await first.focus();
    const focusedHandle = await first.elementHandle();
    const initialScroll = await page.locator("#sourceContent").evaluate(node => node.scrollTop);
    // The generated 31-second silence has 200 dense captions from 25s to 30s.
    // Real timeupdate events traverse many complete virtual windows while cue 0 owns focus.
    await player.evaluate(async node => { node.currentTime = 24.95; node.muted = true; node.playbackRate = 2; await node.play(); });
    await page.waitForFunction(() => document.querySelector("#player").currentTime >= 29.25);
    await player.evaluate(node => node.pause());
    const latestTime = await player.evaluate(node => node.currentTime), latestIndex = expectedIndex(latestTime);
    assert(latestIndex > 160, "Real playback crossed a large virtual transcript window");
    assert.equal(await focusedHandle.evaluate(node => node.isConnected && document.activeElement === node), true,
      "Real playback retains the exact focused cue DOM node");
    assert.equal(await page.locator("#sourceContent").evaluate(node => node.scrollTop), initialScroll,
      "Focused playback does not move the reader's scroll position");
    assert.equal(await semantic.count(), 0, "An off-window current cue must not be falsely announced on a mounted row");
    assert.equal(await page.locator("#sourceContent .cue.active").count(), 0);
    await assertBounded();
    await page.screenshot({ path: path.join(out, "transcript-focused-playback.png") });

    await outside.focus(); await assertCurrent(latestIndex);
    accessibility.push(await readTranscriptCueAccessibility(page, cues, latestIndex));
    assert.equal(await outside.evaluate(node => document.activeElement === node), true, "Follow catches up without stealing focus");
    assert.equal(await follow.isChecked(), true, "Temporary focus pause leaves Follow enabled");
    assert(await semantic.evaluate(node => {
      const row = node.getBoundingClientRect(), panel = document.querySelector("#sourceContent").getBoundingClientRect();
      return row.top >= panel.top - 1 && row.bottom <= panel.bottom + 1;
    }), "Focusout makes the latest playing cue visible");
    await semantic.focus(); await page.keyboard.press("End"); await assertFocused(cues.length - 1);
    await page.keyboard.press("Home"); await assertFocused(0);
    await page.keyboard.press("ArrowDown"); await assertFocused(1);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => Math.abs(document.querySelector("#player").currentTime - 10) < .1 && !document.querySelector("#player").seeking);
    await assertCurrent(1); await assertFocused(1);
    assert.equal(await player.evaluate(node => node.paused), true, "Enter seeks the cue without implicitly starting playback");
    await page.keyboard.press("ArrowUp"); await assertFocused(0);
    await page.screenshot({ path: path.join(out, "transcript-home-keyboard.png") });

    await follow.uncheck();
    await rows.first().focus(); await page.keyboard.press("Home"); await assertFocused(0);
    const disabledScroll = await page.locator("#sourceContent").evaluate(node => node.scrollTop);
    await seek(28);
    await outside.focus();
    await page.waitForFunction(() => document.querySelector("#player").seeking === false);
    assert.equal(await follow.isChecked(), false);
    assert.equal(await page.locator("#sourceContent").evaluate(node => node.scrollTop), disabledScroll,
      "Focusout respects the user's disabled Follow choice");
    assert.equal(await semantic.count(), 0);

    await first.focus();
    const manuallyScrolledCue = await first.elementHandle();
    await page.locator("#sourceContent").hover(); await page.mouse.wheel(0, 1500);
    await page.waitForFunction(() => Number(document.querySelector("#sourceContent .cue")?.dataset.cueIndex) > 0);
    assert.equal(await manuallyScrolledCue.evaluate(node => document.activeElement === node), false,
      "User scroll does not restore focus to an unmounted cue");
    await assertBounded();
    await page.screenshot({ path: path.join(out, "transcript-manual-scroll.png") });
    return { cue_count: cues.length, real_playback_focus_node_preserved: true, focused_scroll_preserved: true,
      follow_resumes_latest_on_focusout: true, disabled_follow_respected: true, manual_scroll_does_not_restore_focus: true,
      home_end_arrow_navigation: true, enter_seeks_without_autoplay: true, deferred_scroll_focus_preserved: true, aria_current_time: true, bounded_dom: true, accessibility_tree: accessibility };
  } finally {
    await outside.focus();
    await player.evaluate((node, saved) => { node.pause(); node.playbackRate = saved.rate; node.muted = saved.muted; }, previous);
    await follow.setChecked(previousFollow);
    await seek(previous.time);
  }
}
module.exports = { assertTranscriptKeyboardAcceptance };
if (process.argv.includes("--self-test")) console.log("Transcript keyboard acceptance helper loaded; real Edge playback is required by its caller");
