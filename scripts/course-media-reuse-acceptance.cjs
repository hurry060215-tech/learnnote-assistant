// Production UI/API with locally seeded synthetic evidence, no model/media calls.
const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

module.exports = async function courseMediaReuseAcceptance(context, base, out) {
  const fixture = JSON.parse(execFileSync("python", ["scripts/seed-course-media-reuse.py"], { encoding: "utf8" }));
  const page = await context.newPage(), courses = [fixture.owner_id, fixture.legacy_id], errors = [];
  let submissions = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.method() === "POST" && request.url().includes("/api/tasks/from-current-page")) submissions++; });
  const api = async (route, options) => {
    const response = await page.request.fetch(new URL(route, base).href, options);
    assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const evidence = async id => (await api(`/api/courses/${id}/compare?q=Synthetic`)).matches.map(item => item.evidence_id).sort();
  const navigateCourse = async id => {
    await page.locator('[data-action="courses"]').click();
    await page.locator(`[data-course="${id}"]`).click();
    await page.locator('[data-action="batch"]').waitFor();
  };
  try {
    const fresh = (await api("/api/courses", { method: "POST", data: { title: "Synthetic newly reused course", sources: [{ kind: "url", url: fixture.url }] } })).course;
    courses.push(fresh.id);
    const ids = await evidence(fixture.owner_id); assert(ids.length > 0);
    const beforeTask = (await api(`/api/tasks/${fixture.task_id}`)).task;
    await page.goto(base);
    await page.locator(`[data-id="${fixture.task_id}"][data-kind="task"]`).first().click();
    await page.locator("#document").getByText(/Synthetic shared evidence remains stable/).waitFor();
    await page.locator("#moreTools").click();
    await page.locator('[data-action="add-to-course"]').click();
    await page.locator(`[data-add-course="${fixture.owner_id}"]`).click();
    for (const id of [fixture.legacy_id, fresh.id]) {
      await navigateCourse(id);
      assert.match(await page.locator("#toolBody").innerText(), /已完成/);
      for (let repeat = 0; repeat < 2; repeat++) {
        await page.locator('[data-action="batch"]').click();
        await page.locator("#toolStatus").getByText(/没有待提交分集/).waitFor();
      }
      const snapshot = await api(`/api/courses/${id}`);
      assert.equal(snapshot.episodes[0].task_id, fixture.task_id);
      assert.deepEqual(await evidence(id), ids);
    }
    await page.screenshot({ path: path.join(out, "course-shared-evidence.png"), fullPage: true });
    await navigateCourse(fixture.owner_id);
    await page.locator('[data-action="delete-course"]').click();
    const child = page.locator(`[data-delete-course-task="${fixture.task_id}"]`);
    assert(await child.isDisabled()); assert.equal(await child.isChecked(), false);
    await page.locator("#confirmCourseDeletion").click();
    await page.locator("#toolStatus").getByText(/删除了 0 个子任务/).waitFor();
    for (const id of [fixture.legacy_id, fresh.id]) {
      assert.equal((await api(`/api/courses/${id}`)).episodes[0].task_id, fixture.task_id);
      assert.deepEqual(await evidence(id), ids);
    }
    assert.deepEqual((await api(`/api/tasks/${fixture.task_id}`)).task, beforeTask);
    assert.equal(submissions, 0); assert.deepEqual(errors, []);
    return { cross_course_task_reused: true, repeated_batch_submissions: submissions, stable_evidence_count: ids.length,
      shared_deletion_protected: true, legacy_adoption_persisted: true, page_errors: errors };
  } finally {
    for (const id of courses) await page.request.delete(new URL(`/api/courses/${id}`, base).href).catch(() => {});
    await page.request.delete(new URL(`/api/tasks/${fixture.task_id}`, base).href).catch(() => {});
    await page.close();
  }
};
