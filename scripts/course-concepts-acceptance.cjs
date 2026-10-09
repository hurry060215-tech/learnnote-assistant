// Runs inside study-product-visual-acceptance on actual Windows Edge against
// the isolated local backend. Every imported source below is synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

module.exports = async function conceptAcceptance({ page, api, base, out, restoreMaterial }) {
  const materials = [], screenshots = [], marker = String(Date.now());
  let course;
  const close = async () => {
    if (await page.locator("#toolsDialog").evaluate(el => el.open)) await page.locator("#toolsDialog [data-close-tool]").click();
  };
  const compare = async () => {
    await page.locator("#compareQuery").fill("scale");
    const reply = page.waitForResponse(r => r.url().includes(`/api/courses/${course.id}/compare?`));
    await page.locator("#compareForm button").click();
    assert.equal((await reply).status(), 200);
    await page.waitForFunction(() => document.querySelector("#compareForm button")?.disabled === false);
    await page.locator('[data-concept-controls="true"]').waitFor();
  };
  const open = async () => {
    await close();
    await page.locator("#moreTools").click();
    await page.locator('[data-action="courses"]').click();
    await page.locator(`[data-course="${course.id}"]`).click();
    await page.getByText("对照不同来源", { exact: true }).click();
    await compare();
  };
  const submit = async action => {
    const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/api/courses/${course.id}/concepts`));
    const refresh = page.waitForResponse(r => r.url().includes(`/api/courses/${course.id}/compare?`));
    await page.locator(`[data-concept-action="${action}"]`).click();
    assert.equal((await response).status(), 200);
    assert.equal((await refresh).status(), 200);
    await page.waitForFunction(() => document.querySelector("#conceptGroupLabel0")?.value === "");
  };
  try {
    for (const [index, text] of ["A scale orders musical pitches.", "A scale measures the weight of an object.", "A scale contains ordered musical notes."].entries()) {
      materials.push((await api("/api/library/materials/import", { method: "POST", multipart: { file: {
        name: `concept-${marker}-${index}.md`, mimeType: "text/markdown", buffer: Buffer.from(`# Concept fixture ${index}\n\n${text}`),
      } } })).material);
    }
    course = (await api("/api/courses", { method: "POST", data: { title: `Concept fixture ${marker}`, sources: materials.map(item => ({ kind: "material", id: item.material_id })) } })).course;
    const anchors = await Promise.all(materials.map(item => api(`/api/library/materials/${item.material_id}/anchors`)));
    const ids = anchors.map(value => value.anchors.find(item => item.text.includes("scale")).evidence_id);
    await open();
    assert.equal(await page.locator(".relationship-edge").count(), 3);
    assert.equal(await page.locator('.relationship-edge[stroke-dasharray="6 4"]').count(), 3);
    assert.match(await page.locator("#compareResults").innerText(), /不代表同义、因果或观点一致/);
    await page.locator(`[data-concept-evidence="${ids[1]}"]`).check();
    const label = "Measurement 测量 " + "LongUnbrokenGroupLabel".repeat(4);
    await page.locator("#conceptGroupLabel0").fill(label);
    await page.locator('[data-concept-action="split"]').focus();
    await submit("split");
    assert.equal(await page.locator(".relationship-edge").count(), 1);
    const splitBackup = await api(`/api/courses/${course.id}/concepts/backup`);
    assert.equal(splitBackup.events.length, 1);
    const downloading = page.waitForEvent("download");
    await page.locator("[data-concept-backup]").click();
    const download = await downloading;
    assert.equal(download.suggestedFilename(), `concept-groups-${course.id}.json`);
    const backupPath = path.join(out, "concept-groups-backup.json");
    await download.saveAs(backupPath);
    assert.deepEqual(JSON.parse(fs.readFileSync(backupPath, "utf8")), splitBackup);
    await close(); await open();
    assert((await page.locator('[data-concept-controls="true"]').innerText()).includes(label));

    for (const width of [390, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      for (const dark of [false, true]) {
        await page.evaluate(dark => document.body.classList.toggle("dark", dark), dark);
        const field = page.locator('[data-concept-term="scale"]');
        await field.scrollIntoViewIfNeeded();
        const geometry = await field.evaluate(el => {
          const rect = el.getBoundingClientRect(), width = document.documentElement.clientWidth;
          return { left: rect.left, right: rect.right, width, overflow: document.documentElement.scrollWidth > width + 1,
            clipped: [...el.querySelectorAll("input,button")].some(control => { const b = control.getBoundingClientRect(); return b.left < -1 || b.right > width + 1; }) };
        });
        assert(!geometry.overflow && !geometry.clipped && geometry.left >= -1 && geometry.right <= width + 1, JSON.stringify(geometry));
        const file = `concept-groups-${width}-${dark ? "dark" : "light"}.png`;
        await page.screenshot({ path: path.join(out, file), fullPage: true }); screenshots.push(file);
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => document.body.classList.remove("dark"));
    for (const checkbox of await page.locator("[data-concept-group]").all()) await checkbox.check();
    await page.locator("#conceptGroupLabel0").fill("My organizational choice");
    await submit("merge");
    assert.equal(await page.locator(".relationship-edge").count(), 3);
    const restoreReply = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/api/courses/${course.id}/concepts/restore`));
    await page.locator("[data-concept-restore]").setInputFiles({ name: "older-groups.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(splitBackup)) });
    assert.equal((await restoreReply).status(), 200);
    assert.equal((await api(`/api/courses/${course.id}/concepts/backup`)).events.length, 2, "Older backup must preserve the later merge");
    await page.waitForFunction(() => document.querySelector("[data-concept-restore]")?.files.length === 0 && document.querySelectorAll("[data-concept-group]").length === 1);
    await api(`/api/knowledge/evidence/${ids[1]}`, { method: "DELETE" });
    await compare();
    assert.match(await page.locator("[data-concept-unresolved]").innerText(), /保留旧分组/);
    const unresolved = "concept-unresolved.png";
    await page.screenshot({ path: path.join(out, unresolved), fullPage: true }); screenshots.push(unresolved);
    await api(`/api/library/materials/${materials[1].material_id}/rebuild`, { method: "POST" });
    await compare();
    assert.equal(await page.locator("[data-concept-unresolved]").count(), 0);
    assert.equal(await page.locator(".relationship-edge").count(), 3);
    // Exercise the exact-source action from the new group control.
    await page.locator(`[data-concept-evidence="${ids[1]}"]`).locator("..").locator("..").getByRole("button", { name: "核对出处", exact: true }).click();
    await page.locator(`#sourceContent [data-evidence-id="${ids[1]}"]`).waitFor({ state: "visible" });
    await page.locator("#closeSource").click();
    return { passed: true, actual_backend: true, synthetic_sources: true, screenshots, checks: ["split, reopen, merge", "lossless JSON download", "old backup preserves later edit", "missing evidence stays unresolved", "rebuild retains identity", "exact source navigation", "390/1024 light/dark layout"] };
  } finally {
    await close();
    if (course) await page.request.delete(new URL(`/api/courses/${course.id}`, base).href);
    for (const material of materials) await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`, base).href);
    await page.goto(base);
    await page.locator(`[data-id="${restoreMaterial.material_id}"][data-kind="material"]`).first().click();
  }
};
