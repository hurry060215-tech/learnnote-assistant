/* Real default UI, local HTTP assets and generated silence; no model calls. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process");
async function main() {
  const { chromium } = require("playwright"), base = process.argv[2] || "http://127.0.0.1:8765";
  const out = path.resolve(process.argv[3] || "build/evidence-source-ui"); fs.mkdirSync(out, { recursive: true });
  const fixture = JSON.parse(execFileSync("python", ["scripts/seed-evidence-navigation.py"], { encoding: "utf8" }));
  const browser = await chromium.launch({ channel: "msedge", headless: true }), page = await browser.newPage();
  const errors = []; page.on("pageerror", error => errors.push(error.message)); page.setDefaultTimeout(15000);
  const api = async (route, options) => { const response = await page.request.fetch(new URL(route, base).href, options); assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`); return response.json(); };
  let course;
  const marker = id => page.locator(`#document .note-claim-marker[data-claim-id="${id}"]`);
  const seek = async time => {
    await page.locator("#player").evaluate((player, time) => { player.currentTime = time; }, time);
    await page.waitForFunction(time => Math.abs(document.querySelector("#player").currentTime - time) < .1, time);
  };
  try {
    course = (await api("/api/courses", { method: "POST", data: { title: "Synthetic frame course", sources: [{ kind: "task", id: fixture.task_id }] } })).course;
    await page.goto(base); await page.locator(`[data-id="${fixture.task_id}"][data-kind="task"]`).first().click();
    await page.locator('#sourceWindow figure[data-window-id="window-1"]').waitFor();
    await page.waitForFunction(() => document.querySelector("#player").readyState >= 1);
    await marker(fixture.claim_ids[0]).waitFor();
    assert.equal(await page.locator("#followNote").isChecked(), false);
    const playbackWrites = [];
    const recordWrite = request => { if (["POST", "PUT", "PATCH"].includes(request.method())) playbackWrites.push(request.url()); };
    page.on("request", recordWrite);
    await page.locator("#player").evaluate(async player => { player.currentTime = 9.8; player.muted = true; player.playbackRate = 2; await player.play(); });
    await page.waitForFunction(id => document.querySelector(`.note-claim-marker[data-claim-id="${id}"]`)?.getAttribute("aria-current") === "true", fixture.claim_ids[1]);
    await page.locator("#player").evaluate(player => player.pause());
    page.off("request", recordWrite); assert.deepEqual(playbackWrites, [], "Playback position is not sent as telemetry");
    await seek(12);
    await page.waitForFunction(id => document.querySelector(`.note-claim-marker[data-claim-id="${id}"]`)?.getAttribute("aria-current") === "true", fixture.claim_ids[1]);
    assert.equal(await marker(fixture.claim_ids[0]).getAttribute("aria-current"), null);
    assert(await page.locator("#sourceContent .cue").count() < 80, "Long transcript remains virtualized");
    await seek(24);
    await page.waitForFunction(() => !document.querySelector("#document .note-claim-marker[aria-current]"));
    await seek(21);
    for (const id of [fixture.claim_ids[0], fixture.claim_ids[2]]) {
      await page.waitForFunction(id => document.querySelector(`.note-claim-marker[data-claim-id="${id}"]`)?.getAttribute("aria-current") === "true", id);
    }
    await marker(fixture.claim_ids[1]).focus(); await page.keyboard.press("Enter");
    await page.waitForFunction(() => Math.abs(document.querySelector("#player").currentTime - 10) < .1);
    assert.equal(await marker(fixture.claim_ids[1]).evaluate(node => node === document.activeElement), true, "Claim navigation preserves keyboard focus");
    await page.locator("#followNote").check();
    await marker(fixture.claim_ids[1]).focus(); await seek(12);
    assert.equal(await marker(fixture.claim_ids[1]).evaluate(node => node === document.activeElement), true, "Playback never takes keyboard focus");
    assert.match(await page.locator("#sourceClaims").innerText(), /推断 · 待核对/);
    assert.match(await page.locator("#sourceClaims").innerText(), /候选来源/);
    await page.locator('#sourceWindow figure[data-window-id="window-2"]').waitFor();
    await page.waitForFunction(() => { const image = document.querySelector("#sourceWindow img"); return image?.complete && image.naturalWidth === 480; });
    await page.locator("#closeSource").click();
    await page.locator("#moreTools").click(); await page.locator('[data-action="add-to-course"]').click();
    await page.locator(`[data-add-course="${course.id}"]`).click(); await page.locator('[data-action="course-review"]').click();
    await page.locator('[data-action="start-review"]').click(); await page.locator("#skipReflection").click();
    await page.locator(`#reviewSources [data-evidence="${fixture.evidence_id}"]`).click();
    await page.locator('#sourceWindow figure[data-window-id="window-2"]').waitFor();
    await page.waitForFunction(() => Math.abs(document.querySelector("#player").currentTime - 10) < 0.5);
    assert.match(await page.locator("#sourceContent .cue.active").innerText(), /Second synthetic window/);
    await page.screenshot({ path: path.join(out, "card-to-window.png"), fullPage: true });
    await page.locator("#aiAssistant").click();
    await page.locator('#assistantHistory [data-citation="0"]').last().click();
    await page.locator('#sourceWindow figure[data-window-id="window-2"]').waitFor();
    await page.waitForFunction(() => Math.abs(document.querySelector("#player").currentTime - 10) < .5);
    await page.locator("#closeAssistant").click();
    const layouts = [];
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator("#sourceClaims").scrollIntoViewIfNeeded();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), `No horizontal overflow at ${width}`);
      assert(await page.locator("#sourceClaims button").first().isVisible());
      await page.screenshot({ path: path.join(out, `claim-timeline-${width}.png`), fullPage: true });
      layouts.push(width);
    }
    await page.evaluate(() => document.body.style.zoom = "2");
    await page.locator("#sourceClaims").scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), "No horizontal overflow at 200% CSS zoom");
    await page.screenshot({ path: path.join(out, "claim-timeline-200-percent.png"), fullPage: true });
    await page.evaluate(() => document.body.style.zoom = "");
    await page.locator("#edit").click();
    assert.equal(await page.locator("#document .note-claim-marker").count(), 0);
    await page.locator("#noteText").fill("# Edited synthetic note\n\nThis revision has no matching saved claim spans.");
    await page.locator("#save").click();
    await page.waitForFunction(() => document.querySelector("#sourceClaims")?.textContent.includes("已停用"));
    assert.equal(await page.locator("#document .note-claim-marker").count(), 0);
    await page.locator(`[data-id="${fixture.subtitle_task_id}"][data-kind="task"]`).first().click();
    await marker(fixture.subtitle_claim_ids[1]).waitFor();
    await marker(fixture.subtitle_claim_ids[1]).click();
    assert.equal(await page.locator("#player").isVisible(), false);
    assert.match(await page.locator("#sourceContent .cue.active").innerText(), /Second synthetic window/);
    await page.screenshot({ path: path.join(out, "subtitle-only-claim.png"), fullPage: true });
    // A delayed old map must not insert markers into a newer source, even when its prose is identical.
    let releaseMap, intercepted;
    const interceptedMap = new Promise(resolve => intercepted = resolve);
    const mapRoute = `**/api/tasks/${fixture.task_id}/claims`;
    await page.route(mapRoute, async route => {
      intercepted(); await new Promise(resolve => releaseMap = resolve); await route.continue();
    });
    await page.locator(`[data-id="${fixture.task_id}"][data-kind="task"]`).first().click();
    await interceptedMap;
    await page.locator(`[data-id="${fixture.subtitle_task_id}"][data-kind="task"]`).first().click();
    const oldMapReturned = page.waitForResponse(response => response.url().endsWith(`/api/tasks/${fixture.task_id}/claims`));
    releaseMap(); await oldMapReturned; await page.unroute(mapRoute);
    await marker(fixture.subtitle_claim_ids[1]).waitFor();
    assert.equal(await marker(fixture.claim_ids[1]).count(), 0);

    assert.deepEqual(errors, []);
    const report = { passed: true, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), browser: browser.version(), playback_window_follow: true, claim_note_follow: true, real_local_playback: true, playback_writes: playbackWrites, repeated_disjoint_intervals: true, edited_note_rejected: true, stale_map_navigation_rejected: true, subtitle_only_claim: true, question_shared_anchor: true, keyboard_focus_preserved: true, layouts, css_zoom_percent: 200, card_window_id: "window-2", card_timestamp: 10, asset_width: 480, page_errors: errors, native_webview_tested: false };
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
  } finally {
    await page.request.delete(new URL(`/api/study/cards/${fixture.card_id}?confirm=delete_card`, base).href).catch(() => {});
    if (course) await page.request.delete(new URL(`/api/courses/${course.id}`, base).href).catch(() => {});
    for (const id of [fixture.task_id, fixture.subtitle_task_id]) await page.request.delete(new URL(`/api/tasks/${id}?confirm=delete_task`, base).href).catch(() => {});
    await browser.close();
  }
}
if (process.argv.includes("--self-test")) { console.log("Evidence source acceptance script loaded; browser flow runs in isolated Windows CI"); }
else main().catch(error => { console.error(error); process.exitCode = 1; });
