// Caller owns the already verified installed WebView2. No browser launch, API
// response substitution, CSS changes or source backend is permitted here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const sha256 = value => createHash('sha256').update(value).digest('hex');

function validateFixture(value) {
  assert.equal(value?.schema_version, 1); assert.equal(value.material_count, 105);
  assert.deepEqual(Object.keys(value).sort(), ['schema_version', 'prefix', 'material_count', 'material_ids', 'target', 'course_id', 'retry', 'model_endpoint'].sort());
  assert(/^Synthetic architecture [a-f0-9]{12}$/.test(value.prefix));
  assert(Array.isArray(value.material_ids) && value.material_ids.length === 105 && new Set(value.material_ids).size === 105);
  assert(value.material_ids.every(id => /^[A-Za-z0-9_-]{1,128}$/.test(id)) && value.material_ids.includes(value.target?.id));
  for (const id of [value.target?.id, value.course_id, value.retry?.task_id]) assert(/^[A-Za-z0-9_-]{1,128}$/.test(id));
  assert(new RegExp('^' + value.prefix + ' \\d{3}$').test(value.target.title));
  // This retry uses the deterministic reading-model fixture, whose title must
  // match the title carried by its transcript source for grounding validation.
  assert.equal(value.retry.title, 'Synthetic installed reading');
  for (const digest of [value.target.source_sha256, value.retry.transcript_sha256]) assert(/^[a-f0-9]{64}$/.test(digest));
  const endpoint = new URL(value.model_endpoint);
  assert.equal(endpoint.protocol, 'http:'); assert.equal(endpoint.hostname, '127.0.0.1');
  assert(endpoint.port && endpoint.pathname === '/v1' && !endpoint.username && !endpoint.password && !endpoint.search && !endpoint.hash);
  return value;
}

function validateCatalog(value) {
  assert.equal(value.schema_version, 1); assert.equal(value.total, value.tasks.length);
  const fields = ['id', 'source_task_id', 'title', 'source_type', 'mode', 'status', 'summary_source', 'created_at', 'updated_at', 'awaiting_confirmation', 'control_generation', 'catalog'].sort();
  for (const row of value.tasks) { assert.equal(row.catalog, true); assert.deepEqual(Object.keys(row).sort(), fields); }
}

// Hold an authentic response after the installed server has handled the POST.
// continueResponse forwards it untouched; this helper never creates a response.
async function holdResponse(session, url, work, timeout = 15000) {
  let release, reject, paused, timer, failure;
  const ready = new Promise((yes, no) => { release = yes; reject = no; });
  const receive = event => {
    if (event.request?.url !== url || event.request?.method !== 'POST' || !event.responseStatusCode) {
      reject(new Error('Unexpected paused request in the exact response gate')); return;
    }
    paused = event; release(event);
  };
  session.on('Fetch.requestPaused', receive);
  try {
    await session.send('Fetch.enable', { patterns: [{ urlPattern: url, requestStage: 'Response' }] });
    timer = setTimeout(() => reject(new Error('Timed out awaiting the actual installed response')), timeout);
    return await work(ready, async () => {
      assert(paused, 'No response may be resumed before its actual pause');
      await session.send('Fetch.continueResponse', { requestId: paused.requestId }); paused = null;
    });
  } catch (error) { failure = error; throw error; }
  finally {
    clearTimeout(timer);
    let cleanup;
    try { if (paused) await session.send('Fetch.continueResponse', { requestId: paused.requestId }); } catch (error) { cleanup = error; }
    session.off('Fetch.requestPaused', receive);
    try { await session.send('Fetch.disable'); } catch (error) { cleanup ||= error; }
    if (cleanup) { if (failure) failure.response_gate_cleanup_failed = true; else throw cleanup; }
  }
}

async function runInstalledArchitecture(page, { origin, fixture, read, capture, out, report, request = fetch }) {
  validateFixture(fixture);
  const state = { passed: false, installed_bundled_assets: true, api_mocked: false, native_viewport_preserved: true,
    cases: [], writes: [], api_mutations: [], race: null };
  report.architecture = state;
  const reads = [], failures = [], target = fixture.target;
  const record = req => {
    const url = new URL(req.url()); if (url.origin !== origin) return;
    if (req.method() === 'GET') reads.push(url.pathname);
    else if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method())) {
      const row = { method: req.method(), route: url.pathname };
      if (url.pathname === '/api/study/activity') {
        const body = req.postDataJSON(); row.activity = { kind: body.kind, source_id: body.source_id };
      }
      state.writes.push(row);
    }
  };
  const errors = error => failures.push(error.message);
  const bytes = async route => {
    const response = await request(origin + route, { signal: AbortSignal.timeout(15000), redirect: 'error' });
    assert(response.ok); const value = Buffer.from(await response.arrayBuffer()); assert(value.length <= 256 * 1024); return value;
  };
  async function freshHome() {
    if (!await page.locator('#welcome').isVisible()) {
      await page.locator('.brand').click();
      await page.locator('#welcome').waitFor({ state: 'visible' });
    }
    if (await page.locator('#search').inputValue()) await page.locator('#search').fill('');
    await page.waitForFunction(() => document.querySelector('#homeLibraryCount')?.textContent.includes('份内容'));
    await page.waitForFunction(() => document.querySelectorAll('#notes [data-kind="material"]').length >= 100);
    if (await page.locator('#menu').getAttribute('aria-expanded') !== 'true') await page.locator('#menu').click();
  }
  async function loadMaterialPages() {
    while (await page.locator('#moreMaterials').isVisible()) {
      const before = await page.locator('#notes [data-kind="material"]').count();
      await page.locator('#moreMaterials').click();
      await page.waitForFunction(count => document.querySelectorAll('#notes [data-kind="material"]').length > count, before);
    }
  }
  async function openTask(taskId, title) {
    await loadMaterialPages();
    const task = page.locator(`#notes [data-kind="task"][data-id="${taskId}"]`);
    await task.waitFor({ state: 'visible' }); await task.click();
    await page.locator('#breadcrumb').filter({ hasText: title }).waitFor();
  }
  async function openCourse() {
    await openTask(fixture.retry.task_id, fixture.retry.title);
    await page.locator('#readerOptions > summary').click(); await page.locator('#moreTools').click();
    await page.locator('[data-action="courses"]').click();
    await page.locator(`[data-course="${fixture.course_id}"]`).click();
  }
  page.on('request', record); page.on('pageerror', errors);
  let cdp, failure;
  try {
    const catalog = await read('/api/tasks/catalog'); validateCatalog(catalog);
    assert(catalog.tasks.some(row => row.id === fixture.retry.task_id));
    const first = await read('/api/library/materials?standalone=true&limit=100');
    assert(first.has_more); assert.equal(first.materials.length, 100); assert(first.total >= fixture.material_count);
    assert(!first.materials.some(row => row.material_id === target.id));
    const connection = await read('/api/model/connection');
    assert.equal(connection.model.base_url, fixture.model_endpoint);
    assert.equal(sha256(await bytes(`/api/library/materials/${target.id}/source`)), target.source_sha256);
    await freshHome();
    await page.waitForFunction(() => document.querySelectorAll('#notes [data-kind="material"]').length === 100);
    assert.equal(await page.locator('#homeLibraryCount').textContent(), `${first.total + catalog.total} 份内容`);
    const focused = await page.locator('#notes [data-kind="material"]').first().elementHandle();
    await focused.focus();
    await page.waitForTimeout(5600);
    assert(await focused.evaluate(node => node.isConnected && document.activeElement === node));
    await capture('installed-architecture-first-page.png');
    await loadMaterialPages();
    assert.equal(await page.locator('#notes [data-kind="material"]').count(), first.total);
    state.cases.push('catalog uses the exact summary contract; first-page count, complete total, polling focus and subsequent pages');
    const form = new FormData(), title = fixture.prefix + ' 105';
    form.append('file', new Blob([`# ${title}\n\nSynthetic installed catalog evidence 105.\n`], { type: 'text/markdown' }), title + '.md');
    const imported = await request(origin + '/api/library/materials/import', { method: 'POST', body: form, signal: AbortSignal.timeout(15000), redirect: 'error' });
    assert(imported.ok);
    const added = (await imported.json()).material; assert.equal(added.title, title);
    state.api_mutations.push({ method: 'POST', route: '/api/library/materials/import', synthetic_count: 1, material_id: added.material_id });
    await page.locator('#refresh').click();
    await page.waitForFunction(count => document.querySelectorAll('#notes [data-kind="material"]').length === count, first.total + 1);
    await page.locator('#search').fill(target.title);
    await page.waitForFunction(id => document.querySelectorAll('#notes [data-kind="material"]').length === 1 && document.querySelector('#notes [data-kind="material"]')?.dataset.id === id, target.id);
    assert.equal(await page.locator('#homeLibraryCount').textContent(), `${first.total + 1 + catalog.total} 份内容`);
    await capture('installed-architecture-search.png');
    state.cases.push('import refresh retains all loaded pages; full-catalog search finds the exact omitted source');
    await freshHome();
    assert.equal(await page.locator(`#notes [data-id="${target.id}"]`).count(), 0);
    await page.goto(`${origin}/web/index.html#material/${target.id}`);
    await page.locator('#document h1').filter({ hasText: target.title }).waitFor();
    assert(reads.includes(`/api/library/materials/${target.id}`));
    await page.locator('#source').click(); await page.locator('#sourcePanel').waitFor({ state: 'visible' });
    // Opening the native source panel is synchronous, its ID-addressed content
    // read is asynchronous. Do not mistake the loading placeholder for a failed
    // outside-page lookup when measuring the real installed API response.
    await page.waitForFunction(title => document.querySelector('#sourceContent')?.textContent?.includes(title), target.title);
    assert((await page.locator('#sourceContent').textContent()).includes(target.title));
    await capture('installed-architecture-outside-source.png');
    await page.locator('#closeSource').click();
    await freshHome(); await openCourse();
    await page.locator('[data-action="edit-course"]').click();
    assert(await page.locator(`#courseForm [data-source="${target.id}"]`).isChecked());
    await page.locator('#courseForm button.primary').click();
    await page.locator('[data-open-source="0"]').waitFor();
    const course = (await read(`/api/courses/${fixture.course_id}`)).course;
    assert.deepEqual(course.sources.map(row => [row.kind, row.id]), [['material', target.id]]);
    await page.locator('[data-open-source="0"]').click();
    await page.locator('#document h1').filter({ hasText: target.title }).waitFor();
    state.cases.push('out-of-page hash, original source and saved course membership resolve the canonical ID');

    await freshHome(); await openTask(fixture.retry.task_id, fixture.retry.title);
    assert.equal(sha256(await bytes(`/api/tasks/${fixture.retry.task_id}/transcript`)), fixture.retry.transcript_sha256);
    cdp = await page.context().newCDPSession(page);
    const retryUrl = `${origin}/api/tasks/${fixture.retry.task_id}/retry-summary`;
    const response = page.waitForResponse(item => item.url() === retryUrl && item.request().method() === 'POST');
    response.catch(() => {}); // Cleanup must retain an earlier primary failure.
    const started = performance.now();
    state.race = { mechanism: 'CDP pauses actual response; continueResponse forwards unchanged bytes', response_status: null, home_before_release: false, task_id: fixture.retry.task_id };
    await holdResponse(cdp, retryUrl, async (ready, resume) => {
      page.once('dialog', dialog => dialog.accept());
      await page.locator('#readerOptions > summary').click(); await page.locator('#moreTools').click();
      await page.locator('[data-action="regenerate"]').click();
      const paused = await ready; assert.equal(paused.responseStatusCode, 200);
      state.race.response_status = paused.responseStatusCode; state.race.response_paused_ms = performance.now() - started;
      await page.locator('.brand').click(); await page.locator('#welcome').waitFor({ state: 'visible' });
      assert.equal(new URL(page.url()).hash, '');
      state.race.home_before_release = true; state.race.home_ms = performance.now() - started;
      await capture('installed-architecture-pending-home.png');
      await resume(); state.race.response_released_ms = performance.now() - started;
    });
    const accepted = await response; assert.equal(accepted.status(), 200);
    assert.equal((await accepted.json()).task_id, fixture.retry.task_id);
    await page.waitForFunction(() => !document.querySelector('#regenerate').disabled);
    assert(await page.locator('#welcome').isVisible()); assert.equal(new URL(page.url()).hash, '');
    const deadline = Date.now() + 90000;
    let task;
    do {
      task = (await read(`/api/tasks/${fixture.retry.task_id}`)).task;
      if (['success', 'failed', 'cancelled'].includes(task.status)) break;
      assert(Date.now() < deadline, 'Real loopback retry did not finish'); await page.waitForTimeout(200);
    } while (true);
    assert.equal(task.status, 'success'); assert.equal(task.summary_source, 'text-llm');
    assert.equal(sha256(await bytes(`/api/tasks/${fixture.retry.task_id}/transcript`)), fixture.retry.transcript_sha256);
    assert(await page.locator('#welcome').isVisible());
    state.race.task_status = task.status; state.race.summary_source = task.summary_source;
    state.cases.push('real retry response is delivered after explicit Home navigation; exactly one accepted retry completes through loopback without stealing navigation');
    const writes = state.writes.filter(row => row.route !== '/api/study/activity');
    assert.deepEqual(writes, [{ method: 'PUT', route: `/api/courses/${fixture.course_id}` }, { method: 'POST', route: `/api/tasks/${fixture.retry.task_id}/retry-summary` }]);
    assert(state.writes.filter(row => row.route === '/api/study/activity').every(row => row.method === 'POST' && row.activity.kind === 'reading'
      && [`material:${target.id}`, `task:${fixture.retry.task_id}`].includes(row.activity.source_id)));
    assert(!reads.includes('/api/tasks')); assert.deepEqual(failures, []);
    state.catalog_reads = reads.filter(route => route === '/api/tasks/catalog').length;
    state.retained_transcript_sha256 = fixture.retry.transcript_sha256; state.passed = true;
  } catch (error) { failure = error; state.failure = error.message; }
  finally {
    try { if (cdp) await cdp.detach(); } catch (error) { failure ||= error; state.passed = false; state.cleanup_failed = true; }
    page.off('request', record); page.off('pageerror', errors);
    try { fs.writeFileSync(path.join(out, 'installed-architecture-report.json'), JSON.stringify(state, null, 2) + '\n'); }
    catch (error) { failure ||= error; }
  }
  if (failure) throw failure;
  return state;
}
module.exports = { validateFixture, validateCatalog, holdResponse, runInstalledArchitecture };
