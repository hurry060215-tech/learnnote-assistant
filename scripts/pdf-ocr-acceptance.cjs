/* Default reader and real persisted synthetic cache; no OCR model is started. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
async function main() {
  const { chromium } = require("playwright");
  const base = process.argv[2] || "http://127.0.0.1:8765", out = path.resolve(process.argv[3] || "build/pdf-ocr-ui");
  fs.mkdirSync(out, { recursive: true });
  const seed = args => JSON.parse(execFileSync("python", ["scripts/seed-pdf-ocr-fixture.py", ...args], { encoding: "utf8" }));
  const fixture = seed([]), id = fixture.material.material_id;
  const browser = await chromium.launch({ channel: "msedge", headless: true }), page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const errors = []; page.on("pageerror", error => errors.push(error.message)); page.setDefaultTimeout(15000);
  let attempts = 0, release, completed, started;
  const continuationStarted = new Promise(resolve => { started = resolve; });
  try {
    await page.route(`**/api/library/materials/${id}/ocr`, async route => {
      if (route.request().method() !== "POST") return route.continue();
      attempts++;
      if (attempts === 1) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { code: "pdf_ocr_unavailable", message: "Synthetic optional OCR unavailable" } }) });
      await new Promise(resolve => { release = resolve; started(); });
      const result = seed(["--complete", id]);
      completed = result;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) });
    });
    page.on("dialog", dialog => dialog.accept());
    await page.goto(base);
    await page.locator(`[data-id="${id}"][data-kind="material"]`).first().click();
    const reader = page.locator("#document .material-ocr-panel");
    await reader.getByText("第 1 页 · 识别器平均置信度 82% · 未核验", { exact: true }).waitFor();
    await reader.locator("summary").first().click();
    assert.match(await reader.innerText(), /识别器置信度 92% · 未核验/);
    assert.match(await reader.innerText(), /识别器置信度 72% · 未核验/);
    assert.match(await reader.innerText(), /第 2 页 · 识别器平均置信度 未知 · 未核验/);
    await reader.getByRole("button", { name: /继续识别未完成页面/ }).click();
    await reader.getByText(/Synthetic optional OCR unavailable/).waitFor();
    assert.equal(await reader.locator("details").count(), 2, "Prior confidence remains available after failure");
    await page.screenshot({ path: path.join(out, "partial-confidence-retry.png"), fullPage: true });
    await page.locator("#moreTools").click();
    await page.locator('[data-action="run-material-ocr"]').click();
    const tools = page.locator("#toolsDialog");
    await tools.getByRole("button", { name: /继续识别未完成页面/ }).click();
    await continuationStarted;
    assert.equal(attempts, 2);
    await tools.locator("[data-close-tool]").click();
    // Closing a dialog does not cancel server work or reopen it after completion.
    const response = page.waitForResponse(response => response.url().endsWith(`/materials/${id}/ocr`) && response.request().method() === "POST");
    assert(release); release(); await response;
    assert.equal(await tools.isVisible(), false);
    await page.reload();
    await page.locator(`[data-id="${id}"][data-kind="material"]`).first().click();
    await reader.getByText("第 3 页 · 识别器平均置信度 93% · 未核验", { exact: true }).waitFor();
    assert.equal(await reader.getByRole("button", { name: /继续识别/ }).count(), 0);
    const original = await page.request.get(new URL(`/api/library/materials/${id}/source`, base).href);
    assert.equal(crypto.createHash("sha256").update(await original.body()).digest("hex"), fixture.material.sha256);
    assert.deepEqual(completed.material.evidence_ids.slice(0, 2), fixture.material.evidence_ids);
    await page.screenshot({ path: path.join(out, "completed-confidence.png"), fullPage: true });
    assert.deepEqual(errors, []);
    const report = { passed: true, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), browser: browser.version(), synthetic_cache_only: true, recognizer_executed: false, retry_preserves_cache: true, close_during_continuation: true, confidence_unknown_preserved: true, original_sha256: fixture.material.sha256, page_errors: errors, native_webview_tested: false };
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
  } finally {
    release?.();
    await page.request.delete(new URL(`/api/library/materials/${id}?confirm=delete_material`, base).href).catch(() => {});
    await browser.close();
  }
}
if (process.argv.includes("--self-test")) console.log("Synthetic PDF OCR acceptance loaded; Windows Edge exercises the reader and cache without models");
else main().catch(error => { console.error(error); process.exitCode = 1; });
