// Real production UI + API acceptance, called by the existing Windows/Edge gate.
// All resources are synthetic and owned by this run. Deferred tasks never start
// a media download or a model call.
const assert = require("node:assert/strict");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

module.exports = async function courseDeletionAcceptance(context, base, out) {
  const page = await context.newPage();
  await page.setViewportSize({ width: 1024, height: 900 });
  const marker = randomUUID(), tasks = [], courses = [], errors = [];
  let material;
  page.on("pageerror", error => errors.push(error.message));
  const api = async (route, options) => {
    const response = await page.request.fetch(new URL(route, base).href, options);
    assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const task = async (name, { active = false, url = "https://example.com/synthetic-course-deletion/" + marker, handoff = "" } = {}) => {
    const result = await api("/api/tasks/from-current-page?defer=true", { method: "POST", data: { title: `${name} ${marker}`, page_url: url, handoff_id: handoff, options: { content_mode: "text", visual_understanding: false } } });
    tasks.push(result.task_id);
    if (!active) await api(`/api/tasks/${result.task_id}/cancel`, { method: "POST" });
    return result.task_id;
  };
  const course = async (name, sources) => {
    const result = await api("/api/courses", { method: "POST", data: { title: `${name} ${marker}`, sources } });
    courses.push(result.course.id);
    return result;
  };
  const taskSource = id => ({ kind: "task", id });
  const openCourse = async id => {
    if (await page.locator("#toolsDialog").evaluate(el => el.open)) await page.locator("[data-close-tool]").click();
    await page.locator("#moreTools").click();
    await page.locator('[data-action="add-to-course"]').click();
    await page.locator(`[data-add-course="${id}"]`).click();
    await page.locator('[data-action="delete-course"]').click();
    await page.locator("#confirmCourseDeletion").waitFor();
  };
  const checkbox = id => page.locator(`[data-delete-course-task="${id}"]`);
  try {
    material = (await api("/api/library/materials/import", { method: "POST", multipart: { file: {
      name: `course-deletion-${marker}.md`, mimeType: "text/markdown", buffer: Buffer.from(`# Independent document ${marker}\n\nThis document must survive course deletion.`),
    } } })).material;
    const chosen = await task("Chosen child"), kept = await task("Kept child"), shared = await task("Shared child"), active = await task("Active child", { active: true }), missing = await task("Missing child");
    const target = await course("Selected deletion", [chosen, kept, shared, active, missing].map(taskSource).concat([{ kind: "url", url: "https://www.youtube.com/watch?v=abcdefghijk" }, { kind: "material", id: material.material_id }]));
    const episode = target.episodes.find(item => item.source_kind === "url");
    await api(`/api/courses/${target.course.id}/episodes/${episode.episode_id}/prepare`, { method: "POST" });
    const linked = await task("URL child", { url: episode.url, handoff: episode.handoff_id });
    await api(`/api/courses/${target.course.id}/episodes/${episode.episode_id}/bind`, { method: "POST", data: { task_id: linked } });
    await course("Shared owner", [taskSource(shared)]);
    await api(`/api/tasks/${missing}`, { method: "DELETE" });
    await page.goto(base);
    await page.locator(`[data-id="${material.material_id}"][data-kind="material"]`).first().click();
    await page.locator("#document").getByText(/This document must survive/).waitFor();
    await openCourse(target.course.id);
    assert.equal(await page.locator("[data-delete-course-task]:checked").count(), 0);
    assert(await checkbox(shared).isDisabled()); assert(await checkbox(active).isDisabled()); assert(await checkbox(missing).isDisabled());
    assert.match(await page.locator("#courseDeletionCount").innerText(), /0 个子任务/);
    await checkbox(chosen).check(); await checkbox(linked).check();
    assert.match(await page.locator("#confirmCourseDeletion").innerText(), /2 个子任务/);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(out, "course-deletion-review.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(out, "course-deletion-review-mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1024, height: 900 });
    const before = (await api(`/api/tasks/${chosen}`)).task;
    await page.locator('[data-action="cancel-delete-course"]').click();
    await page.locator('[data-action="edit-course"]').waitFor();
    assert.deepEqual((await api(`/api/tasks/${chosen}`)).task, before);
    await page.locator('[data-action="delete-course"]').click(); await page.locator("#confirmCourseDeletion").waitFor();
    await checkbox(chosen).check(); await page.keyboard.press("Escape");
    assert.equal(await page.locator("#toolsDialog").evaluate(el => el.open), false);
    assert.deepEqual((await api(`/api/tasks/${chosen}`)).task, before);
    await openCourse(target.course.id);
    await checkbox(chosen).check();
    const current = (await api(`/api/courses/${target.course.id}`)).course;
    await api(`/api/courses/${current.id}`, { method: "PUT", data: { title: current.title + " updated", sources: current.sources, revision: current.revision, paused: current.paused } });
    const staleReply = page.waitForResponse(response => response.request().method() === "DELETE" && response.url().endsWith(`/api/courses/${current.id}`));
    await page.locator("#confirmCourseDeletion").click(); assert.equal((await staleReply).status(), 409);
    await page.locator("#toolStatus").getByText(/未执行删除/).waitFor();
    assert.deepEqual((await api(`/api/tasks/${chosen}`)).task, before);
    await page.locator('[data-action="delete-course"]').click(); await page.locator("#confirmCourseDeletion").waitFor();
    assert.equal(await page.locator("[data-delete-course-task]:checked").count(), 0);
    await checkbox(chosen).check(); await checkbox(linked).check();
    const deletedReply = page.waitForResponse(response => response.request().method() === "DELETE" && response.url().endsWith(`/api/courses/${current.id}`));
    await page.locator("#confirmCourseDeletion").click();
    const deleted = await deletedReply; assert.equal(deleted.status(), 200);
    assert.deepEqual(new Set((await deleted.json()).deleted_task_ids), new Set([chosen, linked]));
    await page.locator("#toolStatus").getByText(/删除了 2 个子任务/).waitFor();
    for (const id of [chosen, linked]) assert.equal((await page.request.get(new URL(`/api/tasks/${id}`, base).href)).status(), 404);
    for (const id of [kept, shared, active]) assert.equal((await api(`/api/tasks/${id}`)).task.id, id);
    assert.equal((await api(`/api/tasks/${active}`)).task.status, "queued");
    assert.deepEqual((await api(`/api/library/materials/${material.material_id}`)).material.evidence_ids, material.evidence_ids);
    const defaultChild = await task("Default retained child");
    const defaultCourse = await course("Default preservation", [taskSource(defaultChild)]);
    await openCourse(defaultCourse.course.id);
    const keepReply = page.waitForResponse(response => response.request().method() === "DELETE" && response.url().endsWith(`/api/courses/${defaultCourse.course.id}`));
    await page.locator("#confirmCourseDeletion").click();
    const keep = await keepReply; assert.equal(keep.status(), 200); assert.deepEqual((await keep.json()).deleted_task_ids, []);
    await page.locator("#toolStatus").getByText(/删除了 0 个子任务/).waitFor();
    assert.equal((await api(`/api/tasks/${defaultChild}`)).task.id, defaultChild);
    assert.deepEqual(errors, []);
    return { default_preserved: true, selected_deleted: 2, shared_protected: true, active_protected: true, missing_protected: true, cancel_preserved: true, stale_rejected: true, independent_document_preserved: true };
  } finally {
    // Cleanup is bounded to IDs created above, including failures mid-flow.
    for (const id of courses) await page.request.delete(new URL(`/api/courses/${id}`, base).href).catch(() => {});
    for (const id of tasks) {
      await page.request.post(new URL(`/api/tasks/${id}/cancel`, base).href).catch(() => {});
      await page.request.delete(new URL(`/api/tasks/${id}`, base).href).catch(() => {});
    }
    if (material) await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`, base).href).catch(() => {});
    await page.close();
  }
};
