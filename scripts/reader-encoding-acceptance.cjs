/* Called by the Windows/Edge default-reader gate; synthetic local bytes only. */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");

module.exports = async function readerEncodingAcceptance({ page, api, base, out, restoreMaterial }) {
  const marker = String(Date.now());
  const raw = Buffer.concat([Buffer.from(`Reader encoding ${marker}\n\n`),
    Buffer.from("bfceb3ccb1e0c2ebd1f9b1bea3bad1a7cfb0c2cabef6b6a8b2bdb3a4a1a3", "hex")]);
  const hash = crypto.createHash("sha256").update(raw).digest("hex");
  const material = (await api("/api/library/materials/import", { method: "POST", multipart: {
    encoding: "big5", file: { name: `reader-encoding-${marker}.txt`, mimeType: "text/plain", buffer: raw },
  } })).material;
  const endpoint = `/api/library/materials/${material.material_id}/redecode`;
  const submissions = [], confirmations = [];
  const onRequest = request => { if (request.method() === "POST" && request.url().endsWith(endpoint)) submissions.push(request); };
  const onDialog = dialog => confirmations.push(dialog.message());
  page.on("request", onRequest); page.on("dialog", onDialog);
  const open = async () => {
    await page.locator("#moreTools").click();
    await page.locator('[data-action="material-encoding"]').click();
    await page.locator("#materialEncodingForm").waitFor();
  };
  const reply = () => page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith(endpoint));
  const close = () => page.locator("#materialEncodingForm [data-close-tool]").click();
  let release, heldRoute;
  try {
    await page.goto(base);
    await page.locator(`[data-id="${material.material_id}"][data-kind="material"]`).first().click();
    await page.locator(".encoding-provenance-note").waitFor();
    assert.doesNotMatch(await page.locator("#document").innerText(), /学习率决定步长/);
    await open(); assert.match(await page.locator("#materialCurrentEncoding").innerText(), /big5/);
    assert.match(await page.locator("#materialEncodingForm").innerText(), /原始字节保留在本机/);
    await close(); await open(); await page.keyboard.press("Escape");
    assert.equal(await page.locator("#toolsDialog").evaluate(el => el.open), false);
    assert.equal(submissions.length, 0, "Cancel and Escape before submit do not write");

    await open(); await page.locator("#materialRedecodeEncoding").selectOption("utf-8");
    let response = reply(); await page.locator("#materialRedecodeSubmit").click();
    assert.equal((await response).status(), 422);
    await page.locator("#toolStatus").getByText(/当前资料未改变/).waitFor();
    assert.equal((await api(`/api/library/materials/${material.material_id}`)).material.metadata.encoding, "big5");
    await page.locator("#materialRedecodeEncoding").selectOption("gb18030");
    response = reply(); await page.locator("#materialRedecodeSubmit").click();
    assert.equal((await response).status(), 200);
    await page.locator("#toolStatus").getByText(/已重新解码/).waitFor();
    assert.match(await page.locator("#materialCurrentEncoding").innerText(), /gb18030/);
    assert.match(await page.locator("#document").innerText(), /学习率决定步长/);
    assert(confirmations.some(text => text.includes("已有引用需要重新核对")));
    const updated = (await api(`/api/library/materials/${material.material_id}`)).material;
    assert.equal(updated.metadata.raw_sha256, hash); assert.deepEqual(updated.evidence_ids, material.evidence_ids);
    const anchors = (await api(`/api/library/materials/${material.material_id}/anchors`)).anchors;
    assert(anchors.some(item => item.text.includes("学习率决定步长")));
    const original = await page.request.get(new URL(`/api/library/materials/${material.material_id}/source`, base).href);
    assert(original.ok()); assert.deepEqual(await original.body(), raw);
    await page.screenshot({ path: path.join(out, "reader-encoding-recovered.png"), fullPage: true });

    // An already open panel cannot overwrite a newer backend version.
    await api(endpoint, { method: "POST", data: { encoding: "gb18030", expected_updated_at: updated.updated_at } });
    response = reply(); await page.locator("#materialRedecodeSubmit").click();
    assert.equal((await response).status(), 409);
    await page.locator("#toolStatus").getByText(/未覆盖当前版本/).waitFor();
    await close(); await open();

    // Hold a real response after committing. Dismissal and a newer selection
    // must win, including against repeated keyboard/programmatic submission.
    const gate = new Promise(resolve => { release = resolve; });
    heldRoute = async route => { const result = await route.fetch(); await gate; await route.fulfill({ response: result }); };
    await page.route(`**${endpoint}`, heldRoute);
    const beforeCount = submissions.length;
    response = reply();
    const sent = page.waitForRequest(request => request.method() === "POST" && request.url().endsWith(endpoint));
    await page.locator("#materialRedecodeSubmit").click(); await sent;
    assert(await page.locator("#materialRedecodeSubmit").isDisabled());
    await page.locator("#materialEncodingForm").evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    assert.equal(submissions.length, beforeCount + 1);
    await page.keyboard.press("Escape");
    await page.locator(`[data-id="${restoreMaterial.material_id}"][data-kind="material"]`).first().click();
    await page.locator("#document").getByText(/Learning rate controls/).waitFor();
    release(); await (await response).finished();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.locator("#toolsDialog").evaluate(el => el.open), false);
    assert.match(await page.locator("#document").innerText(), /Learning rate controls/);
    assert.equal(new URL(page.url()).hash, `#material/${restoreMaterial.material_id}`);
    return { default_reader: true, current_encoding: updated.metadata.encoding, raw_bytes_unchanged: true,
      evidence_ids_preserved: true, invalid_encoding_rejected: true, stale_version_rejected: true,
      cancel_escape_no_write: true, repeated_submit_blocked: true, late_response_keeps_new_selection: true };
  } finally {
    release?.();
    if (heldRoute) await page.unroute(`**${endpoint}`, heldRoute);
    page.off("request", onRequest); page.off("dialog", onDialog);
    await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`, base).href);
  }
};
