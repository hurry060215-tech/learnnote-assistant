const assert = require("node:assert/strict");
const TIMEOUT = 15000;

async function completedAction(page, method, url, action) {
  let timer;
  try {
    return await Promise.race([(async () => {
      const [response] = await Promise.all([
        page.waitForResponse(item => item.url() === url && item.request().method() === method, { timeout: TIMEOUT }), action(),
      ]);
      assert(response.ok(), `${method} ${url}: ${response.status()}`);
      assert.equal(await response.finished(), null, `${method} ${url} did not finish`);
      return response;
    })(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out completing ${method} ${url}`)), TIMEOUT); })]);
  } finally { clearTimeout(timer); }
}

async function retryCourseReady(page, { url, retrySelector, readySelector, title }) {
  const oldControl = await page.locator(retrySelector).elementHandle(); assert(oldControl);
  try {
    await completedAction(page, "POST", url, () => page.locator(retrySelector).click());
    await page.waitForFunction(control => !control.isConnected, oldControl, { timeout: TIMEOUT });
    await page.locator(readySelector).waitFor({ state: "visible", timeout: TIMEOUT });
    assert(await page.locator(readySelector).isEnabled());
    assert.equal(await page.locator("#toolsDialog h2").innerText(), title);
    assert.equal(await page.locator("#toolStatus").innerText(), "");
  } finally { await oldControl.dispose(); }
}

async function openChildReady(page, { base, id, title }) {
  await completedAction(page, "GET", `${base}/api/tasks/editions/task/${encodeURIComponent(id)}`,
    () => page.locator(`[data-open-upgrade="${id}"]`).click());
  await page.waitForURL(url => url.hash === `#task/${encodeURIComponent(id)}`, { timeout: TIMEOUT });
  await page.waitForFunction(() => !document.getElementById("toolsDialog").open, null, { timeout: TIMEOUT });
  const reader = page.locator(`#document[data-reader-source="task:${id}"]`);
  await reader.waitFor({ state: "visible", timeout: TIMEOUT });
  assert.equal(await reader.locator("h1").innerText(), title);
  assert.match(await page.locator("#taskStatus .task-status-heading strong").innerText(), /^排队中/);
}

async function cleanupFixture(actions, primaryError) {
  const errors = [];
  for (const [label, action] of Object.entries(actions)) {
    try { await action(); } catch (error) { errors.push(new Error(`Fixture cleanup ${label}: ${error.message}`, { cause: error })); }
  }
  if (!errors.length) return;
  if (primaryError) primaryError.cleanupErrors = errors;
  else throw new AggregateError(errors, "Fixture cleanup failed");
}

module.exports = { completedAction, retryCourseReady, openChildReady, cleanupFixture };
