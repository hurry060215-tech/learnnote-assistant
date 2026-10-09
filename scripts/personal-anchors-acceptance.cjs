/* Actual Edge + actual backend. All task files come from our bounded fixture. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18930";
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname));
  const output = path.resolve(__dirname, "../build/personal-anchors-acceptance");
  const fixture = JSON.parse(fs.readFileSync(path.join(output, "fixture.json"), "utf8"));
  assert.equal(fixture.synthetic, true);
  assert.match(fixture.task_id, /^[a-f0-9]{12}$/);
  assert.equal(path.resolve(fixture.data_dir), path.join(output, "data"));
  const notePath = path.join(output, "data/tasks", fixture.task_id, "note.md");
  const transcriptPath = path.join(output, "data/tasks", fixture.task_id, "transcript.json");
  assert.equal(path.resolve(fixture.note_path), notePath);
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 1000 }, reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => new URL(route.request().url()).origin === new URL(base).origin
    ? route.continue() : route.abort());
  const endpoint = `${base}/api/personal/task/${fixture.task_id}`;
  const read = async () => {
    const response = await page.request.get(endpoint); assert.equal(response.status(), 200);
    return (await response.json()).annotations;
  };
  const save = async () => {
    const response = page.waitForResponse(r => r.url() === endpoint && r.request().method() === "POST");
    await page.locator("#saveAnnotation").click();
    assert.equal((await response).status(), 200);
    await page.waitForFunction(() => !document.querySelector("#annotationText").disabled);
  };
  const choose = async kind => {
    await page.locator("#annotationAnchorPicker > summary").click();
    await page.locator("#annotationAnchorKind").selectOption(kind);
    await page.waitForFunction(() => document.querySelector("#annotationAnchorTarget").options.length > 0);
    await page.locator("#applyAnnotationAnchor").click();
  };
  try {
    await page.goto(`${base}/#task/${fixture.task_id}`);
    await page.locator("#document").getByText("An exact generated claim.", { exact: true }).waitFor();
    const literal = '\n\n  const cafe\u0301 = "🧭";\n\treturn x;\n\n';
    await choose("claim");
    await page.locator("#annotationText").fill(literal); await save();
    let items = await read(); const claim = items[0];
    assert.equal(claim.text, literal); assert.equal(claim.anchor.kind, "claim");
    assert.equal(await page.locator("#annotationList [data-user-content]").textContent(), literal);
    assert.equal(await page.locator("#annotationList span").getAttribute("data-user-content"), "");

    await choose("transcript");
    const options = await page.locator("#annotationAnchorTarget option").allTextContents();
    assert.equal(options.length, 2); assert.match(options[1], /3–7s/);
    await page.locator("#annotationAnchorTarget").selectOption({ index: 1 });
    await page.locator("#applyAnnotationAnchor").click();
    await page.locator("#annotationText").fill("Overlapping caption stays exact."); await save();
    items = await read(); assert.equal(items[1].anchor.start, 3); assert.equal(items[1].anchor.end, 7);
    await choose("visual");
    await page.locator("#annotationText").fill("Synthetic visual annotation."); await save();
    items = await read(); assert.equal(items[2].anchor.window_id, "synthetic-window");

    await choose("transcript");
    await page.locator("#annotationAnchorEnd").selectOption({ index: 1 });
    const intervalResponse = page.waitForResponse(r => r.url() === `${endpoint}/transcript-interval`);
    await page.locator("#applyAnnotationAnchor").click();
    assert.equal((await intervalResponse).status(), 200);
    await page.waitForFunction(() => !document.querySelector("#applyAnnotationAnchor").disabled);
    const intervalText = "  Multi-cue cafe\u0301 🧭\n\tKeep original boundaries.\n\n";
    await page.locator("#annotationText").fill(intervalText); await save();
    const interval = (await read()).find(a => a.text === intervalText);
    assert.equal(interval.anchor.start, 1); assert.equal(interval.anchor.end, 7);
    assert.deepEqual(interval.anchor.cues.map(cue => [cue.start, cue.end]), [[1, 5], [3, 7]]);
    assert.equal(interval.anchor_status.resolution, "exact");
    const invalidRange = await page.request.post(endpoint, { data: {
      text: "Must not silently narrow", anchor: { ...items[1].anchor, start: 1 },
    } });
    assert.equal(invalidRange.status(), 409);

    // Change only the generated fixture. The saved personal record must remain.
    fs.appendFileSync(notePath, "\nGenerated fixture changed.\n", "utf8");
    await page.reload();
    const edit = page.locator(`[data-annotation-edit="${claim.id}"]`);
    await edit.waitFor(); assert.equal(await edit.textContent(), "修复出处");
    await edit.click(); assert.equal(await page.locator("#annotationText").inputValue(), literal);
    await choose("transcript"); await save();
    const repaired = (await read()).find(a => a.id === claim.id);
    assert.equal(repaired.text, literal); assert.equal(repaired.anchor.kind, "transcript");
    assert.equal(repaired.anchor_status.stale, false);

    // Another tab edits after this editor loaded: a 409 retains its draft.
    await page.locator(`[data-annotation-edit="${claim.id}"]`).click();
    const external = await page.request.post(endpoint, { data: { id: claim.id, text: "Other tab saved.", revision: repaired.revision } });
    assert.equal(external.status(), 200);
    await page.locator("#annotationText").fill("Unsaved stale draft.");
    const conflict = page.waitForResponse(r => r.url() === endpoint && r.request().method() === "POST");
    await page.locator("#saveAnnotation").click(); assert.equal((await conflict).status(), 409);
    await page.waitForFunction(() => !document.querySelector("#annotationText").disabled);
    assert.equal(await page.locator("#annotationText").inputValue(), "Unsaved stale draft.");
    await page.locator("#cancelAnnotationEdit").click();
    assert.equal(await page.locator("#annotationText").inputValue(), "");

    // Simulate a lost successful response, then retry the same payload.
    let drop = true;
    await page.route(`**/api/personal/task/${fixture.task_id}`, async route => {
      if (drop && route.request().method() === "POST") {
        drop = false; await route.fetch(); return route.abort();
      }
      return route.continue();
    });
    await page.locator("#annotationText").fill("Retry keeps one annotation.");
    await page.locator("#saveAnnotation").click();
    await page.waitForFunction(() => !document.querySelector("#annotationText").disabled);
    assert.equal(await page.locator("#annotationText").inputValue(), "Retry keeps one annotation.");
    await save();
    assert.equal((await read()).filter(a => a.text === "Retry keeps one annotation.").length, 1);

    // A changed interior cue must orphan the whole interval, retaining its ID,
    // text and original boundaries until the user explicitly chooses a repair.
    const transcript = JSON.parse(fs.readFileSync(transcriptPath, "utf8"));
    transcript.segments[1].text += " Changed synthetic caption.";
    fs.writeFileSync(transcriptPath, JSON.stringify(transcript), "utf8");
    await page.reload();
    const intervalEdit = page.locator(`[data-annotation-edit="${interval.id}"]`);
    await intervalEdit.waitFor(); assert.equal(await intervalEdit.textContent(), "修复出处");
    const orphan = (await read()).find(a => a.id === interval.id);
    assert.equal(orphan.text, intervalText); assert.deepEqual(orphan.anchor, interval.anchor);
    assert.equal(orphan.anchor_status.resolution, "orphaned");
    await intervalEdit.click(); await choose("transcript");
    await page.locator("#annotationAnchorEnd").selectOption({ index: 1 });
    const repairResponse = page.waitForResponse(r => r.url() === `${endpoint}/transcript-interval`);
    await page.locator("#applyAnnotationAnchor").click(); assert.equal((await repairResponse).status(), 200);
    await page.waitForFunction(() => !document.querySelector("#applyAnnotationAnchor").disabled);
    await save();
    const fixed = (await read()).find(a => a.id === interval.id);
    assert.equal(fixed.text, intervalText); assert.equal(fixed.anchor_status.resolution, "exact");
    assert.deepEqual(fixed.anchor.cues.map(cue => [cue.start, cue.end]), [[1, 5], [3, 7]]);
    await page.screenshot({ path: path.join(output, "personal-anchors.png"), fullPage: true });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, "report.json"), JSON.stringify({ status: "pass", browser: "msedge", actual_backend: true,
      synthetic_only: true, checks: ["claim-caption-visual", "overlapping-ranges", "multi-cue-interval", "altered-range-rejected", "interval-orphan-repair", "orphan-repair", "stale-edit", "lost-response-retry", "literal-text", "user-content-boundary"] }, null, 2));
    console.log("Personal anchors: actual Edge/backend acceptance passed");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
