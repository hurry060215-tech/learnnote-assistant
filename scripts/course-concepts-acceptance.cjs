// Runs inside study-product-visual-acceptance on actual Windows Edge against
// the isolated local backend. Every imported source below is synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

module.exports = async function conceptAcceptance({ page, api, base, out, restoreMaterial }) {
  const materials = [], screenshots = [], marker = String(Date.now());
  const hostileText = '<img src="snapshot-fixture-invalid" onerror="window.__snapshotFixtureExecuted=true"><script>window.__snapshotFixtureExecuted=true</script>';
  const completeText = `A scale orders musical pitches. ${"This is synthetic full-length evidence retained beyond the comparison excerpt. ".repeat(16)}END OF COMPLETE SNAPSHOT EVIDENCE ${hostileText}`;
  const snapshotPath = `/api/courses/graph-snapshot/preview`;
  const deletedMaterials = new Set();
  let course, courseDeleted = false, catalogRoute, oversizeRoute, observedRequests;
  const close = async () => {
    if (await page.locator("#toolsDialog").evaluate(el => el.open)) await page.locator("#toolsDialog [data-close-tool]").click();
  };
  const compare = async ({ query = "scale", sourceKind = "", sourceId = "", start = "", end = "" } = {}) => {
    await page.locator("#compareQuery").fill(query);
    await page.locator("#compareSourceKind").selectOption(sourceKind);
    await page.locator("#compareSourceId").selectOption(sourceId);
    await page.locator("#compareStart").fill(start);
    await page.locator("#compareEnd").fill(end);
    const reply = page.waitForResponse(r => r.url().includes(`/api/courses/${course.id}/compare?`));
    await page.locator("#compareForm button").click();
    const response = await reply;
    assert.equal(response.status(), 200);
    await page.waitForFunction(() => document.querySelector("#compareForm button")?.disabled === false);
    await page.locator('[data-concept-controls="true"]').waitFor();
    return response.json();
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
  const exportSnapshot = async name => {
    const reply = page.waitForResponse(r => r.request().method() === "GET" && new URL(r.url()).pathname === `/api/courses/${course.id}/graph-snapshot`);
    const downloading = page.waitForEvent("download");
    await page.locator("[data-graph-snapshot-export]").click();
    const response = await reply;
    assert.equal(response.status(), 200);
    const download = await downloading;
    const file = path.join(out, name);
    await download.saveAs(file);
    const snapshot = JSON.parse(fs.readFileSync(file, "utf8"));
    assert.deepEqual(snapshot, await response.json(), "Download preserves the complete API snapshot");
    return { snapshot, request: new URL(response.url()) };
  };
  const openSnapshotImport = async () => {
    await close();
    await page.locator("#moreTools").click();
    await page.locator('[data-action="courses"]').click();
    await page.locator("[data-graph-snapshot-import]").click();
    await page.locator("[data-graph-snapshot-file]").waitFor({ state: "attached" });
  };
  const importSnapshot = async (snapshot, raw = JSON.stringify(snapshot)) => {
    const reply = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === snapshotPath);
    await page.locator("[data-graph-snapshot-file]").setInputFiles({ name: "filtered-comparison.json", mimeType: "application/json", buffer: Buffer.from(raw) });
    return reply;
  };
  try {
    for (const [index, text] of [completeText, "A scale measures the weight of an object.", "A scale contains ordered musical notes."].entries()) {
      materials.push((await api("/api/library/materials/import", { method: "POST", multipart: { file: {
        name: `concept-${marker}-${index}.md`, mimeType: "text/markdown", buffer: Buffer.from(`# Concept fixture ${index}\n\n${text}`),
      } } })).material);
    }
    course = (await api("/api/courses", { method: "POST", data: { title: `Concept fixture ${marker}`, sources: materials.map(item => ({ kind: "material", id: item.material_id })) } })).course;
    const anchors = await Promise.all(materials.map(item => api(`/api/library/materials/${item.material_id}/anchors`)));
    const ids = anchors.map(value => value.anchors.find(item => item.text.includes("scale")).evidence_id);
    // API seeding bypasses the reader import flow's refresh. Load the complete
    // fixture into the reader before testing its canonical source resolver;
    // otherwise this depends on the unrelated five-second library poll.
    await page.goto(base);
    for (const item of [restoreMaterial, ...materials]) {
      await page.locator(`#notes [data-kind="material"][data-id="${item.material_id}"]`).waitFor({ state: "attached" });
    }
    await page.locator(`#notes [data-kind="material"][data-id="${restoreMaterial.material_id}"]`).click();
    await page.waitForFunction(id => document.querySelector("#document")?.dataset.readerSource === `material:${id}`, restoreMaterial.material_id);
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

    // Export exactly the displayed comparison, including whitespace and the
    // chosen filters, even when the form has since been edited without submit.
    await open();
    const query = "  SCALE   scale  ";
    const comparison = await compare({ query, sourceKind: "material" });
    const history = await api(`/api/courses/${course.id}/concepts/backup`);
    assert.equal(comparison.edges.length, 3);
    assert(!comparison.matches.find(item => item.evidence_id === ids[0]).excerpt.includes("END OF COMPLETE SNAPSHOT EVIDENCE"));
    await page.locator("#compareQuery").fill("unsent form edits");
    await page.locator("#compareSourceKind").selectOption("task");
    await page.locator("#compareSourceId").selectOption(materials[1].material_id);
    await page.locator("#compareStart").fill("100");
    await page.locator("#compareEnd").fill("200");
    const exported = await exportSnapshot("filtered-comparison.json");
    const snapshot = exported.snapshot;
    assert.equal(snapshot.format, "learnnote.filtered-comparison");
    assert.equal(snapshot.schema_version, 1);
    assert.equal(snapshot.course.id, course.id);
    assert.equal(snapshot.course.revision, course.revision);
    assert.equal(snapshot.scope.query, query);
    assert.deepEqual(snapshot.scope.terms, ["scale"]);
    assert.deepEqual(snapshot.scope.filters, { source_id: "", source_kind: "material", start: null, end: null });
    assert.equal(exported.request.searchParams.get("q"), query);
    assert.equal(exported.request.searchParams.get("revision"), String(course.revision));
    assert.equal(exported.request.searchParams.get("source_kind"), "material");
    assert.equal(exported.request.searchParams.get("source_id") || "", "");
    assert.equal(exported.request.searchParams.get("start"), null);
    assert.equal(exported.request.searchParams.get("end"), null);
    assert.deepEqual(snapshot.history, history);
    const embedded = snapshot.evidence.find(item => item.evidence_id === ids[0]);
    assert(embedded, "Snapshot embeds the matching evidence record");
    assert.equal(embedded.text, completeText);
    assert.equal(embedded.course_source.id, materials[0].material_id);
    assert.equal(snapshot.graph.edges.length, 3);
    assert(snapshot.graph.edges.every(edge => edge.citations.length === 2 && edge.citations.every(citation => snapshot.evidence.some(item => item.evidence_id === citation.evidence_id))));

    await compare({ query, sourceKind: "material", sourceId: materials[0].material_id, start: "0", end: "8.5" });
    const timed = await exportSnapshot("filtered-comparison-time-range.json");
    assert.equal(timed.snapshot.scope.query, query);
    assert.deepEqual(timed.snapshot.scope.filters, { source_id: materials[0].material_id, source_kind: "material", start: 0, end: 8.5 });
    assert.equal(timed.request.searchParams.get("source_id"), materials[0].material_id);
    assert.equal(timed.request.searchParams.get("start"), "0");
    assert.equal(timed.request.searchParams.get("end"), "8.5");
    assert.deepEqual(timed.snapshot.graph.matches, [], "Untimed documents do not acquire synthetic media timestamps");
    const retainedDocument = timed.snapshot.evidence.find(item => item.evidence_id === ids[0]);
    assert.equal(retainedDocument.text, completeText, "Grouping reconstruction retains the original document outside the time filter");
    assert.equal(retainedDocument.metadata.start, undefined);
    assert.equal(retainedDocument.metadata.end, undefined);
    assert.equal(timed.snapshot.graph.nodes.length, 0);
    assert.equal(timed.snapshot.graph.edges.length, 0);
    assert.deepEqual(await api(`/api/courses/${course.id}/concepts/backup`), history, "Export does not change grouping history");

    // Only this failure response is mocked. Successful exports and imported
    // snapshot validation above/below use the isolated real backend.
    const exportPattern = `**/api/courses/${course.id}/graph-snapshot?*`;
    oversizeRoute = route => route.fulfill({ status: 413, contentType: "application/json", body: JSON.stringify({ detail: { code: "graph_snapshot_too_large", message: "快照过大，请缩小筛选范围后重试。" } }) });
    await page.route(exportPattern, oversizeRoute);
    const oversized = page.waitForResponse(r => new URL(r.url()).pathname === `/api/courses/${course.id}/graph-snapshot`);
    await page.locator("[data-graph-snapshot-export]").click();
    assert.equal((await oversized).status(), 413);
    await page.locator('[data-graph-snapshot-controls] [role="status"]').getByText(/缩小.*范围/).waitFor();
    await page.unroute(exportPattern, oversizeRoute);
    oversizeRoute = null;

    // A portable import must stand alone when both its original course and
    // every original source have actually been removed from the local catalog.
    await close();
    assert((await page.request.delete(new URL(`/api/courses/${course.id}`, base).href)).ok());
    courseDeleted = true;
    for (const material of materials) {
      assert((await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`, base).href)).ok());
      deletedMaterials.add(material.material_id);
      assert.equal((await page.request.get(new URL(`/api/library/materials/${material.material_id}`, base).href)).status(), 404);
    }
    assert.equal((await page.request.get(new URL(`/api/courses/${course.id}`, base).href)).status(), 404);
    const readerBefore = await page.locator("#document").getAttribute("data-reader-source");
    const importedRequests = [];
    observedRequests = request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/")) importedRequests.push({ method: request.method(), path: url.pathname });
    };
    page.on("request", observedRequests);
    catalogRoute = route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Synthetic unavailable course catalog" }) });
    await page.route("**/api/courses", catalogRoute);
    await openSnapshotImport();
    const imported = await importSnapshot(snapshot);
    assert.equal(imported.status(), 200);
    const validated = await imported.json();
    assert.equal(validated.read_only, true);
    assert.deepEqual(validated.snapshot, snapshot);
    assert.deepEqual(validated.graph, snapshot.graph);
    const preview = page.locator("[data-graph-snapshot-preview]");
    await preview.waitFor();
    assert.match(await preview.innerText(), /只读快照 · 关键词共现 · 未验证来源真实性/);
    assert.equal(await preview.locator(".relationship-edge").count(), 3);
    assert.equal(await preview.locator("[data-concept-action], [data-concept-restore], [data-evidence]").count(), 0, "Preview offers no live grouping or source actions");
    await preview.locator(".relationship-graph > summary").click();
    await preview.getByText("关系列表（虚线为关键词共现；不表示事实关系）", { exact: true }).click();
    await preview.locator(`[data-snapshot-citation="${ids[0]}"]:visible`).first().click();
    const evidence = preview.locator(`[data-snapshot-evidence="${ids[0]}"]`);
    assert.equal(await evidence.evaluate(el => el.open), true);
    assert((await evidence.innerText()).includes(completeText), "Citation opens the embedded complete text, including text beyond the excerpt");
    assert((await evidence.innerText()).includes(embedded.locator));
    assert.equal(await preview.locator("script, img, iframe, object, embed").count(), 0, "Imported hostile markup remains literal text");
    assert.equal(await page.evaluate(() => window.__snapshotFixtureExecuted === true), false);
    assert.equal(await page.locator("#sourcePanel").isVisible(), false);
    assert.equal(await page.locator("#document").getAttribute("data-reader-source"), readerBefore);

    for (const width of [390, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      for (const dark of [false, true]) {
        await page.evaluate(dark => document.body.classList.toggle("dark", dark), dark);
        await preview.scrollIntoViewIfNeeded();
        const geometry = await preview.evaluate(el => {
          const rect = el.getBoundingClientRect(), width = document.documentElement.clientWidth;
          const controls = [...el.querySelectorAll("button,input,select,summary")].filter(control => control.getClientRects().length);
          return { left: rect.left, right: rect.right, width, overflow: document.documentElement.scrollWidth > width + 1,
            clipped: controls.some(control => { const b = control.getBoundingClientRect(); return b.left < -1 || b.right > width + 1; }) };
        });
        assert(!geometry.overflow && !geometry.clipped && geometry.left >= -1 && geometry.right <= width + 1, JSON.stringify(geometry));
        const file = `graph-snapshot-${width}-${dark ? "dark" : "light"}.png`;
        await page.screenshot({ path: path.join(out, file), fullPage: true }); screenshots.push(file);
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => document.body.classList.remove("dark"));
    const reexporting = page.waitForEvent("download");
    await page.locator("[data-graph-snapshot-reexport]").click();
    const reexported = await reexporting;
    const reexportPath = path.join(out, "filtered-comparison-reexport.json");
    await reexported.saveAs(reexportPath);
    assert.deepEqual(JSON.parse(fs.readFileSync(reexportPath, "utf8")), snapshot, "Reexport preserves the validated original snapshot losslessly");

    // Zero and integer-valued time bounds must survive the browser's JSON
    // number serialization and the server's digest validation as well.
    const importedTimed = await importSnapshot(timed.snapshot);
    assert.equal(importedTimed.status(), 200);
    await page.waitForFunction(() => document.querySelector('[data-graph-snapshot-preview]')?.textContent.includes("起点 0 秒"));
    assert.equal(await page.locator('[data-graph-snapshot-preview] .relationship-edge').count(), 0);
    assert.equal((await importedTimed.json()).snapshot.scope.filters.start, 0);

    // A changed record with the original digest must not become a preview.
    await openSnapshotImport();
    const tampered = JSON.parse(JSON.stringify(snapshot));
    tampered.evidence[0].text += " UNTRUSTED TAMPERED RECORD";
    const rejected = await importSnapshot(tampered);
    assert(rejected.status() >= 400 && rejected.status() < 500, "Tampered snapshot is rejected by validation");
    await page.waitForFunction(() => {
      const text = document.querySelector('[data-graph-snapshot-importer] > [role="status"]')?.textContent || "";
      return text.length > 0 && !text.includes("正在验证");
    });
    assert.equal(await page.locator("[data-graph-snapshot-preview]").count(), 0);
    assert(!(await page.locator("#toolBody").innerText()).includes("UNTRUSTED TAMPERED RECORD"));
    const duplicate = await importSnapshot(snapshot, '{"format":"hostile.first.value",' + JSON.stringify(snapshot).slice(1));
    assert.equal(duplicate.status(), 409, "The file's duplicate keys survive browser transport and are rejected by the real backend");
    assert.equal(await page.locator("[data-graph-snapshot-preview]").count(), 0);
    assert.deepEqual(importedRequests.filter(item => !["GET", "HEAD"].includes(item.method) && !(item.method === "POST" && item.path === snapshotPath)), [], "Import, citation navigation and reexport never write to live records");
    assert.deepEqual(importedRequests.filter(item => item.path.startsWith(`/api/courses/${course.id}`) || materials.some(material => item.path.startsWith(`/api/library/materials/${material.material_id}`)) || ids.some(id => item.path.startsWith(`/api/knowledge/evidence/${id}`))), [], "Imported citations never look up live course or source records");
    await page.unroute("**/api/courses", catalogRoute);
    catalogRoute = null;
    assert(!(await api("/api/courses")).courses.some(item => item.id === course.id), "Import does not recreate the removed course");
    return { passed: true, actual_backend: true, synthetic_sources: true, screenshots,
      graph_snapshot: { exact_captured_scope: true, source_and_time_filters: true, complete_embedded_text: true, portable_missing_course_and_sources: true, catalog_failure_import: true, local_citations: true, lossless_reexport: true, hostile_text_inert: true, tampered_rejected: true, read_only: true, mocked_failures: ["graph_snapshot_too_large", "course_catalog_unavailable"] },
      checks: ["split, reopen, merge", "lossless JSON grouping backup", "old backup preserves later edit", "missing evidence stays unresolved", "rebuild retains identity", "exact source navigation", "filtered graph snapshot export and read-only import", "390/1024 light/dark grouping and snapshot layout"] };
  } finally {
    if (observedRequests) page.off("request", observedRequests);
    if (catalogRoute) await page.unroute("**/api/courses", catalogRoute);
    if (oversizeRoute) await page.unroute(`**/api/courses/${course.id}/graph-snapshot?*`, oversizeRoute);
    await close();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => document.body.classList.remove("dark"));
    if (course && !courseDeleted) await page.request.delete(new URL(`/api/courses/${course.id}`, base).href);
    for (const material of materials) if (!deletedMaterials.has(material.material_id)) await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`, base).href);
    await page.goto(base);
    await page.locator(`[data-id="${restoreMaterial.material_id}"][data-kind="material"]`).first().click();
  }
};
