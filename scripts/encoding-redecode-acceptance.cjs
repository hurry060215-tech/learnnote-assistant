const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const base = process.argv[2] || "http://127.0.0.1:8765/web/classic.html";
  const output = path.resolve(process.argv[3] || "build/encoding-redecode-ui");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(base, { waitUntil: "networkidle" });
    if (await page.locator("#skipOnboardingButton").isVisible()) await page.locator("#skipOnboardingButton").click();
    if (await page.locator("#confirmReleaseNotesButton").isVisible()) await page.locator("#confirmReleaseNotesButton").click();
    await page.locator("#settingsNav").click();
    await page.locator('[data-settings-tab="connection"]').click();
    await page.locator("#knowledgeImportEncoding").selectOption("big5");

    const raw = Buffer.from("bfceb3ccb1e0c2ebd1f9b1bea3bad1a7cfb0c2cabef6b6a8b2bdb3a4a1a3", "hex");
    const sourceHash = crypto.createHash("sha256").update(raw).digest("hex");
    const importResponseEvent = page.waitForResponse(response => response.url().endsWith("/api/library/materials/import") && response.request().method() === "POST");
    const chooserEvent = page.waitForEvent("filechooser");
    await page.locator("#knowledgeImportButton").click();
    await (await chooserEvent).setFiles({ name: "legacy-gb18030.txt", mimeType: "text/plain", buffer: raw });
    const importResponse = await importResponseEvent;
    const importText = await importResponse.text();
    assert.equal(importResponse.status(), 200, importText);
    const imported = JSON.parse(importText).material;
    assert.equal(imported.metadata.encoding, "big5");
    assert.equal(imported.metadata.raw_sha256, sourceHash);
    await page.waitForSelector(".material-reader");
    const before = await page.locator(".material-reader").innerText();
    assert.doesNotMatch(before, /学习率决定步长/);

    const rawResponse = await page.request.get(new URL(`/api/library/materials/${imported.material_id}/source`, base).href);
    assert.equal(rawResponse.status(), 200);
    assert.equal(crypto.createHash("sha256").update(await rawResponse.body()).digest("hex"), sourceHash);

    const panel = page.locator(".material-redecode-panel");
    await panel.locator("summary").click();
    await page.locator("#materialRedecodeEncoding").selectOption("gb18030");
    const redecodeResponseEvent = page.waitForResponse(response => response.url().endsWith(`/api/library/materials/${imported.material_id}/redecode`) && response.request().method() === "POST");
    await page.locator("#materialRedecodeButton").click();
    const redecodeResponse = await redecodeResponseEvent;
    const redecodeText = await redecodeResponse.text();
    assert.equal(redecodeResponse.status(), 200, redecodeText);
    await page.waitForFunction(() => document.querySelector(".material-reader")?.innerText.includes("学习率决定步长"));

    const updated = (await (await page.request.get(new URL(`/api/library/materials/${imported.material_id}`, base).href)).json()).material;
    assert.equal(updated.metadata.encoding, "gb18030");
    assert.equal(updated.metadata.redecoded, true);
    assert.equal(updated.metadata.raw_sha256, sourceHash);
    assert.equal(updated.material_id, imported.material_id);
    const anchors = (await (await page.request.get(new URL(`/api/library/materials/${imported.material_id}/anchors`, base).href)).json()).anchors;
    assert(anchors.some(item => item.text.includes("学习率决定步长")));
    const sourceAfter = await page.request.get(new URL(`/api/library/materials/${imported.material_id}/source`, base).href);
    assert.equal(crypto.createHash("sha256").update(await sourceAfter.body()).digest("hex"), sourceHash);
    await page.screenshot({ path: path.join(output, "redecoded-material.png") });
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({ ok: true, materialId: updated.material_id, sourceSha256: sourceHash, initialEncoding: "big5", finalEncoding: updated.metadata.encoding, anchorCount: anchors.length, errors }));
  } finally {
    await browser.close();
  }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exit(1); });
