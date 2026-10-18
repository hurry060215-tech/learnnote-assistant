/* Actual controller + shipped CSS; scrolling below is precondition setup only. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");

function readClaimFollowGeometry(input) {
  const { claimId, listTextLimit = 1000 } = typeof input === "string" ? { claimId: input } : input;
  const marker = document.querySelector(`#document .note-claim-marker[data-claim-id="${claimId}"]`);
  const target = marker.closest("[data-note-start][data-note-end]"), style = getComputedStyle(target);
  const rect = target.getBoundingClientRect(), lines = [];
  const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
  for (let node; (node = walker.nextNode());) {
    if (node.parentElement.closest(".note-claim-marker") || !node.textContent.trim()) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    for (const box of range.getClientRects()) if (box.width && box.height) lines.push(box);
  }
  const text = lines.slice(0, 8).map(box => ({ top: box.top, bottom: box.bottom, left: box.left, right: box.right,
    unobscured: target.contains(document.elementFromPoint((box.left + box.right) / 2, (box.top + box.bottom) / 2)) }));
  const headers = [...document.querySelectorAll(".toolbar, .reader-strip")].filter(node => node.getClientRects().length);
  const list = document.querySelector(".claim-timeline-list");
  return { top: rect.top, bottom: rect.bottom, targetHeight: rect.height, text, textLineCount: lines.length,
    headerBottom: Math.max(0, ...headers.map(node => node.getBoundingClientRect().bottom)),
    stickyTop: parseFloat(style.getPropertyValue("--source-sticky-top")), margin: parseFloat(style.scrollMarginTop),
    width: innerWidth, height: document.documentElement.clientHeight, scrollY,
    scrollWidth: document.documentElement.scrollWidth, targetOverflow: target.scrollWidth - target.clientWidth,
    active: marker.getAttribute("aria-current") === "true", follow: document.querySelector("#followNote").checked,
    sourcePinned: document.querySelector("#sourcePanel").classList.contains("source-pinned"),
    sourceHidden: document.querySelector("#sourcePanel").hidden, editorHidden: document.querySelector("#editor").hidden,
    sourceHeight: document.querySelector("#sourcePanel").getBoundingClientRect().height,
    claimListHeight: list.getBoundingClientRect().height, claimListText: list.textContent.slice(0, listTextLimit), claimListTextLength: list.textContent.length,
    focusedControl: document.activeElement?.id,
    noteFocused: document.querySelector("#document").contains(document.activeElement),
    selectionCollapsed: !getSelection() || getSelection().isCollapsed };
}

function assertClaimFollowVisible(state, alignment) {
  assert(state.active && state.follow && !state.sourceHidden && state.editorHidden);
  assert(!state.sourcePinned, "This gate covers toolbar/strip clearance, not the optional pinned source overlay");
  assert(!state.noteFocused && state.selectionCollapsed, "Following must not be masked by an interaction guard");
  assert(Math.abs(state.stickyTop - state.headerBottom) <= 1, "Measured token must match actual sticky chrome");
  assert(Math.abs(state.margin - Math.max(140, state.stickyTop + 12)) <= 1);
  assert(state.top >= state.headerBottom, "Claim start must clear the actual sticky controls");
  assert(state.text.length > 0, "Claim must have rendered prose");
  const visibleText = alignment === "start" ? state.text.slice(0, 1) : state.text;
  for (const box of visibleText) {
    assert(box.top >= state.headerBottom && box.bottom <= state.height && box.left >= 0 && box.right <= state.width);
    assert(box.unobscured, "Claim text must pass actual point hit testing");
  }
  assert(state.scrollWidth <= state.width + 2 && state.targetOverflow <= 2, "Following must not hide horizontal content");
  if (alignment === "start") {
    assert(state.targetHeight > state.height - state.margin, "Oversized fixture must exceed the unobscured region");
    assert(Math.abs(state.top - state.margin) <= 2, "Oversized claim must align its start, not its center");
  } else {
    assert(state.bottom <= state.height, "A fitting claim must be entirely inside the unobscured region");
    if (alignment === "center") assert(Math.abs(state.top - (state.height + state.margin - state.targetHeight) / 2) <= 2,
      "Browser center alignment must use the shipped effective scroll margin");
  }
}

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function seekClaim(page, time, claimId) {
  await page.locator("#player").evaluate((node, time) => { node.pause(); node.currentTime = time; }, time);
  await page.waitForFunction(({ time, claimId }) => {
    const player = document.querySelector("#player");
    return !player.seeking && Math.abs(player.currentTime - time) < .005 &&
      document.querySelector(`.note-claim-marker[data-claim-id="${claimId}"]`)?.getAttribute("aria-current") === "true";
  }, { time, claimId });
  await settle(page);
}

async function assertClaimFollowVisibility(page, { claimId, oversizedClaimId, out, name, viewport, short = false, records = [], capture, listTextLimit = 1000 }) {
  assert(Number.isInteger(listTextLimit) && listTextLimit >= 1000 && listTextLimit <= 4096, "Synthetic source-list diagnostic bound");
  const report = { name, listTextLimit, trigger: "keyboard Follow activation on a populated paused-player claim", passed: false, cases: [], cleanupErrors: [] }; records.push(report);
  const savedViewport = page.viewportSize();
  let saved, focused, failure;
  const screenshot = async filename => {
    if (!capture) { await page.screenshot({ path: path.join(out, filename), timeout: 5000 }); return; }
    const result = await capture(path.join(out, filename));
    assert(result.sampled_colors > 1, "Owned-window capture must not be blank");
    return { width: result.width, height: result.height, sampledColors: result.sampled_colors };
  };
  const follow = page.locator("#followNote");
  async function setFollow(checked) {
    if (await follow.isChecked() !== checked) {
      // Keyboard activation works even in the deliberately short viewport.
      await follow.focus(); await page.keyboard.press("Space");
      assert.equal(await follow.isChecked(), checked);
    }
  }
  async function place(id, covered) {
    await page.evaluate(({ id, covered }) => {
      getSelection()?.removeAllRanges();
      const target = document.querySelector(`.note-claim-marker[data-claim-id="${id}"]`).closest("[data-note-start][data-note-end]");
      const header = Math.max(...[...document.querySelectorAll(".toolbar, .reader-strip")].map(node => node.getBoundingClientRect().bottom));
      // This sets up the manual-scroll position BEFORE Follow activation. No
      // locator focus, wheel or target scroll is allowed after the trigger.
      scrollBy({ top: target.getBoundingClientRect().top - (covered ? header / 3 : header + 2), behavior: "instant" });
    }, { id, covered });
    await settle(page);
  }
  try {
    saved = await page.evaluate(() => ({ follow: document.querySelector("#followNote").checked,
      time: document.querySelector("#player").currentTime, paused: document.querySelector("#player").paused, x: scrollX, y: scrollY }));
    assert(saved.paused, "Geometry fixture starts with paused local media");
    focused = await page.evaluateHandle(() => document.activeElement);
    if (viewport) await page.setViewportSize(viewport);
    await settle(page);
    for (const [kind, id, time, alignment] of [["covered", claimId, 12, "center"], ["already-visible", claimId, 12, "unchanged"], ["oversized", oversizedClaimId, 25.01, "start"]]) {
      const item = { kind }; report.cases.push(item);
      // Populate the real source list before positioning. Gap-to-active seeking
      // would resize that list above the note and confound the scroll decision.
      await setFollow(false); await seekClaim(page, time, id); await follow.focus();
      await place(id, kind !== "already-visible");
      item.before = await page.evaluate(readClaimFollowGeometry, { claimId: id, listTextLimit });
      assert(item.before.active && !item.before.follow && !item.before.sourcePinned);
      assert.equal(item.before.focusedControl, "followNote", "The checkbox is focused before positioning, never after it");
      assert(item.before.claimListTextLength <= listTextLimit, "Bounded synthetic source-list content must be fully recorded");
      if (kind === "already-visible") assert(item.before.top >= item.before.headerBottom && item.before.bottom <= item.before.height);
      else assert(item.before.top > 0 && item.before.top < item.before.headerBottom,
        "Manual-scroll precondition must actually place the target inside the viewport behind sticky chrome");
      await page.keyboard.press("Space");
      await settle(page);
      item.after = await page.evaluate(readClaimFollowGeometry, { claimId: id, listTextLimit });
      assert.equal(item.after.claimListText, item.before.claimListText, "Follow re-evaluation retains the populated source-list content");
      assert.equal(item.after.claimListTextLength, item.before.claimListTextLength);
      assert(Math.abs(item.after.sourceHeight - item.before.sourceHeight) <= 1 &&
        Math.abs(item.after.claimListHeight - item.before.claimListHeight) <= 1 &&
        Math.abs(item.after.top + item.after.scrollY - item.before.top - item.before.scrollY) <= 1,
      "Follow activation must not change source layout or the target document position");
      assertClaimFollowVisible(item.after, alignment);
      if (kind === "already-visible") assert(Math.abs(item.after.scrollY - item.before.scrollY) <= 1, "Already unobscured claim must not move");
      else assert(Math.abs(item.after.scrollY - item.before.scrollY) > 2, "Following must actually move the covered target");
      if (short && kind === "covered") assert((item.after.height - item.after.targetHeight) / 2 < item.after.headerBottom,
        "Short fixture must demonstrate why raw viewport centering is insufficient");
      item.capture = `${name}-${kind}.png`; item.nativeCapture = await screenshot(item.capture);
    }
    report.passed = true;
  } catch (error) {
    failure = error; report.error = String(error).slice(0, 1000);
    try { await screenshot(`${name}-failure.png`); } catch (captureError) { report.captureError = String(captureError).slice(0, 1000); }
    throw error;
  } finally {
    for (const [label, action] of [
      ["follow off", () => setFollow(false)],
      ["viewport", async () => { if (viewport && savedViewport) await page.setViewportSize(savedViewport); }],
      ["player position", async () => { if (saved) { await page.locator("#player").evaluate((node, time) => { node.currentTime = time; }, saved.time); await page.waitForFunction(() => !document.querySelector("#player").seeking); } }],
      ["follow preference", async () => { if (saved) await setFollow(saved.follow); }],
      ["focus", async () => { await focused?.evaluate(node => { if (node.isConnected) node.focus({ preventScroll: true }); }); }],
      ["scroll position", async () => { if (saved) await page.evaluate(saved => scrollTo({ left: saved.x, top: saved.y, behavior: "instant" }), saved); }],
      ["focus handle", async () => { await focused?.dispose(); }],
    ]) { try { await action(); } catch (error) { report.cleanupErrors.push(`${label}: ${String(error).slice(0, 500)}`); } }
    if (report.cleanupErrors.length) report.passed = false;
    try { fs.writeFileSync(path.join(out, `${name}-report.json`), JSON.stringify(report, null, 2)); }
    catch (error) { report.passed = false; report.writeError = String(error).slice(0, 1000); if (!failure) failure = error; else console.error("Claim-follow report write also failed:", error); }
    if (!failure && report.cleanupErrors.length) throw new Error(report.cleanupErrors.join("; "));
    if (failure && !report.error) throw failure;
  }
  return report;
}
module.exports = { readClaimFollowGeometry, assertClaimFollowVisible, assertClaimFollowVisibility };
