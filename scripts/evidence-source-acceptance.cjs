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
  try {
    course = (await api("/api/courses", { method: "POST", data: { title: "Synthetic frame course", sources: [{ kind: "task", id: fixture.task_id }] } })).course;
    await page.goto(base); await page.locator(`[data-id="${fixture.task_id}"][data-kind="task"]`).first().click();
    await page.locator('#sourceWindow figure[data-window-id="window-1"]').waitFor();
    await page.waitForFunction(() => document.querySelector("#player").readyState >= 1);
    await page.locator("#player").evaluate(player => { player.currentTime = 12; });
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
    assert.deepEqual(errors, []);
    const report = { passed: true, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), browser: browser.version(), playback_window_follow: true, card_window_id: "window-2", card_timestamp: 10, asset_width: 480, page_errors: errors, native_webview_tested: false };
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
  } finally {
    await page.request.delete(new URL(`/api/study/cards/${fixture.card_id}?confirm=delete_card`, base).href).catch(() => {});
    if (course) await page.request.delete(new URL(`/api/courses/${course.id}`, base).href).catch(() => {});
    await page.request.delete(new URL(`/api/tasks/${fixture.task_id}?confirm=delete_task`, base).href).catch(() => {});
    await browser.close();
  }
}
if (process.argv.includes("--self-test")) { console.log("Evidence source acceptance script loaded; browser flow runs in isolated Windows CI"); }
else main().catch(error => { console.error(error); process.exitCode = 1; });
