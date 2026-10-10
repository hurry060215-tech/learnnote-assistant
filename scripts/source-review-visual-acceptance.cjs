/* Synthetic notes, generated silence and local export only; no model calls. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process"), { chromium } = require("playwright");
(async () => {
  const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
  assert(base.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname));
  const out = path.resolve(process.argv[3] || "build/source-review-ui"); fs.mkdirSync(out, { recursive: true });
  const fixture = JSON.parse(execFileSync("python", ["scripts/seed-evidence-navigation.py", "--source-review"], { encoding: "utf8" }));
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const errors = []; page.on("pageerror", error => errors.push(error.message)); page.setDefaultTimeout(15000);
  const api = async (route, options) => {
    const response = await page.request.fetch(new URL(route, base).href, options);
    assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`); return response;
  };
  try {
    const editionRoute = `/api/tasks/editions/task/${fixture.task_id}`;
    const before = await (await api(editionRoute)).json();
    await page.goto(base.href); await page.locator(`[data-id="${fixture.task_id}"][data-kind="task"]`).first().click();
    const review = page.locator("#document [data-source-reviews]"); await review.waitFor();
    assert.equal(await review.evaluate(node => node.open), false);
    assert.equal(await page.locator("#document .source-review-link").count(), 40);
    assert.match(await review.locator("summary").innerText(), /40 条定位提示/);
    const bodyWarnings = await page.locator("#document strong").evaluateAll(nodes => nodes.filter(node =>
      node.textContent.includes("仅定位到来源") && !node.closest("code, pre, blockquote, a, h1, h2, h3, h4, h5, h6")).length);
    assert.equal(bodyWarnings, 0, "location-only prose notices are collected without changing literal code examples");
    await page.locator("#document strong").filter({ hasText: "未找到支持来源" }).waitFor();
    await page.locator("#document strong").filter({ hasText: "推断：需回源核对" }).waitFor();
    assert.match(await page.locator("#document code").last().innerText(), /仅定位到来源/, "literal code examples stay intact");
    if (await page.locator("#closeSource").isVisible()) await page.locator("#closeSource").click();
    await page.screenshot({ path: path.join(out, "note-review-collapsed.png"), fullPage: true });
    await page.locator("#document .source-review-link").nth(4).click();
    assert.equal(await review.evaluate(node => node.open), true);
    assert.match(await review.locator("section").nth(4).innerText(), /第5条合成表述/);
    await review.locator("section").nth(4).locator("button.time-link").click();
    await page.waitForFunction(() => document.querySelector("#player").readyState >= 1 && Math.abs(document.querySelector("#player").currentTime - 12) < 0.5);
    assert.match(await page.locator("#sourceContent .cue.active").innerText(), /Second synthetic window/);
    await page.screenshot({ path: path.join(out, "review-source-navigation.png"), fullPage: true });
    await page.locator("#closeSource").click(); await review.locator("summary").click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator("#document").evaluate(node => node.scrollWidth <= node.clientWidth + 1));
    await page.screenshot({ path: path.join(out, "review-mobile.png"), fullPage: true });
    const markdown = await (await api(editionRoute + "/exports/markdown")).text();
    assert.match(markdown, /来源核对 · 40 条定位提示/);
    assert.match(markdown, /\[来源 5\]\(#section-来源核对-5\)/);
    assert.match(markdown, /未找到支持来源/);
    const html = await (await api(`/api/tasks/${fixture.task_id}/exports/html`, {
      method: "POST", data: { format: "html", options: { include_toc: false, include_transcript: false } },
    })).text();
    const exported = await browser.newPage(); exported.on("pageerror", error => errors.push(error.message));
    await exported.setContent(html);
    const exportedReview = exported.locator("details.source-review");
    assert.equal(await exportedReview.evaluate(node => node.open), false);
    await exported.locator('a[href="#section-来源核对-5"]').first().click();
    assert.equal(await exportedReview.evaluate(node => node.open), true);
    await exported.locator('[id="section-来源核对-5"]').waitFor({ state: "visible" });
    await exported.screenshot({ path: path.join(out, "html-review-expanded.png"), fullPage: true });
    await exported.close();
    const after = await (await api(editionRoute)).json();
    assert.equal(after.text, before.text); assert.equal(after.revision, before.revision);
    assert.deepEqual(errors, []);
    const report = { passed: true, notices: 40, stored_note_unchanged: true, stronger_warnings_visible: true,
      source_navigation_seconds: 12, markdown_references: true, html_expand_on_reference: true, errors };
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
  } finally {
    await page.request.delete(new URL(`/api/study/cards/${fixture.card_id}?confirm=delete_card`, base).href).catch(() => {});
    await page.request.delete(new URL(`/api/tasks/${fixture.task_id}?confirm=delete_task`, base).href).catch(() => {});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
