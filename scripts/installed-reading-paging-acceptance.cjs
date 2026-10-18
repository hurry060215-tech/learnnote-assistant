// Called only after the existing owned installed WebView2/API attachment guard.
// Actual bundled UI and HTTP responses, no response interception or source backend.
const assert = require('node:assert/strict');
const { readOutlineHeading, assertOutlineHeadingVisible, waitForOutlineScroll } = require('./note-controls-visual-acceptance.cjs');
const { assertClaimFollowVisibility } = require('./claim-follow-visibility-acceptance.cjs');
const { pagingViewportState } = require('./community-question-api-acceptance.cjs');
const TITLE = 'Synthetic installed reading', HEADING = 'Synthetic deep heading';
function validateFeatureFixture(value, taskId) {
  assert(value && Object.keys(value).sort().join(',') === 'community_task_id,reading');
  assert.equal(value.community_task_id, taskId);
  const r = value.reading;
  assert(r && /^[A-Za-z0-9_-]{1,128}$/.test(r.task_id) && r.task_id !== taskId);
  assert.equal(r.title, TITLE); assert.equal(r.deep_heading, HEADING);
  for (const key of ['claim_id', 'oversized_claim_id']) assert(/^claim-[a-f0-9]{20}$/.test(r[key]));
  for (const key of ['edition_revision', 'media_sha256']) assert(/^[a-f0-9]{64}$/.test(r[key]));
  return value;
}
function assertPage(value, offset, count, taskId) {
  assert.equal(value.task_id, taskId); assert.equal(value.enabled, true);
  assert.equal(value.total_count, 501); assert.equal(value.limit, 500);
  assert.equal(value.offset, offset); assert.equal(value.returned_count, count); assert.equal(value.items.length, count);
  assert.equal(value.groups_scope, 'current_page_only'); assert.equal(value.has_more, offset === 0);
  assert.equal(Boolean(value.next_cursor), offset === 0); assert.equal(Boolean(value.previous_cursor), offset !== 0);
}
function assertPreview(value, last, taskId) {
  assert.deepEqual(value.selected_item_ids, [last.item_id]); assert.equal(value.persisted, false);
  assert.equal(value.task_id, taskId); assert.equal(value.model_request_performed, false);
  assert.equal(value.can_submit, true);
  assert.equal(value.opinions.length, 1); assert.equal(value.opinions[0].text, last.text);
  assert.equal(value.opinions[0].item_id, last.item_id);
  assert.equal(value.opinions[0].source_uri, last.source_uri);
  assert.equal(value.opinions[0].timestamp_seconds, last.timestamp_seconds);
  assert.equal(last.task_id, taskId); assert.equal(last.source_uri, 'https://example.com/synthetic-rollback');
  assert(value.original_sources.length > 0 && value.original_sources.length <= 24);
  assert.deepEqual(Object.fromEntries(['opinion_items', 'opinion_characters', 'original_source_items', 'original_source_characters'].map(key => [key, value.limits[key]])),
    { opinion_items: 20, opinion_characters: 20000, original_source_items: 24, original_source_characters: 12000 });
}
async function runInstalledFeatures(page, { origin, taskId, fixture, read, capture, out, report }) {
  validateFeatureFixture(fixture, taskId);
  const state = { passed: false, installed_bundled_assets: true, api_mocked: false,
    native_window_viewport: true, native_browser_zoom_tested: false, community: {}, outline: [], follow: [], writes: [] };
  report.features = state;
  const record = request => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
      const route = new URL(request.url()).pathname;
      state.writes.push({ method: request.method(), route,
        ...(route === '/api/study/activity' ? { body: request.postDataJSON() } : {}) });
    }
  };
  page.on('request', record);
  try {
    await page.goto(`${origin}/web/index.html?task=${taskId}`);
    await page.locator('#document h1').waitFor();
    assert.equal(await page.locator('#breadcrumb').innerText(), 'Synthetic rollback captions');
    await page.locator('#readerOptions > summary').click(); await page.locator('#moreTools').click();
    await page.locator('[data-action="community"]').click();
    const route = `/api/tasks/${taskId}/community-context/page`;
    const first = await read(route + '?limit=500'); assertPage(first, 0, 500, taskId);
    const lastPage = await read(route + '?' + new URLSearchParams({ limit: '500', cursor: first.next_cursor }));
    assertPage(lastPage, 500, 1, taskId);
    const last = lastPage.items[0];
    const transcript = await read(`/api/tasks/${taskId}/transcript`);
    assert(!first.items.some(item => item.item_id === last.item_id));
    const rows = page.locator('#communityRows blockquote'), status = page.locator('#communityPageStatus');
    await status.getByText(/1–500.*501/).waitFor(); assert.equal(await rows.count(), 500);
    assert.deepEqual(await rows.locator('[data-item-id]').evaluateAll(nodes => nodes.map(node => node.dataset.itemId)), first.items.map(item => item.item_id));
    assert.equal(await page.locator('[data-opinion-id]').count(), 500);
    assert(await page.locator('#communityPrevious').isDisabled());
    await page.locator('#communityText').fill('Synthetic unsubmitted import draft');
    async function flip(id, expression, count) {
      const response = page.waitForResponse(r => new URL(r.url()).pathname === route && r.request().method() === 'GET');
      await page.locator(id).focus(); await page.keyboard.press('Enter');
      const value = await (await response).json(); assertPage(value, count === 1 ? 500 : 0, count, taskId);
      await status.getByText(expression).waitFor(); assert.equal(await rows.count(), count);
      assert(await status.evaluate(node => document.activeElement === node));
      assert.deepEqual(await page.locator('#toolsDialog').evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
      assert.equal(await page.locator('#communityText').inputValue(), 'Synthetic unsubmitted import draft');
    }
    await flip('#communityNext', /501–501.*501/, 1);
    assert(await page.locator('#communityNext').isDisabled());
    assert.equal(await rows.locator('p').innerText(), last.text);
    assert.equal(await rows.locator('[data-item-id]').getAttribute('data-item-id'), last.item_id);
    await capture('installed-community-501.png');
    async function preview() {
      const details = page.locator('#communityQuestionSlot details.section-review');
      if (!(await details.evaluate(node => node.open))) await details.locator('summary').click();
      await page.locator('#communityQuestionRoute').getByText(/synthetic-local/).waitFor();
      await page.locator('#communityQuestionText').fill('Which original source supports this synthetic opinion?');
      await page.locator(`[data-opinion-id="${last.item_id}"]`).check();
      const response = page.waitForResponse(r => new URL(r.url()).pathname === `/api/tasks/${taskId}/qa/preview`);
      await page.locator('#communityQuestionPreview').click();
      const value = await (await response).json(); assertPreview(value, last, taskId);
      assert.deepEqual(value.original_sources, transcript.segments.map((cue, index) => ({ source_id: `E${index + 1}`, text: cue.text, start: cue.start, end: cue.end })));
      await page.locator('#communityQuestionConsent').waitFor(); assert(!(await page.locator('#communityQuestionConsent').isChecked()));
      await page.locator('#communityQuestionConsent').check();
      return value;
    }
    const value = await preview();
    await page.locator('#communityQuestionCancel').click();
    assert.equal(await page.locator('#communityQuestionConsent').count(), 0);
    assert.equal(await page.locator('[data-opinion-id]:checked').count(), 0);
    assert.equal(await page.locator('#communityQuestionText').inputValue(), '');
    await preview(); await flip('#communityPrevious', /1–500.*501/, 500);
    assert.equal(await page.locator('#communityQuestionConsent').count(), 0);
    assert.equal(await page.locator('[data-opinion-id]:checked').count(), 0);
    assert.equal(await page.locator('#communityQuestionText').inputValue(), '');
    await capture('installed-community-first-page.png');
    await page.locator('[data-close-tool]').click();
    assert(!(await page.locator('#toolsDialog').evaluate(node => node.open)));
    state.community = { passed: true, total: 501, pages: [500, 1, 500],
      last_item_id: last.item_id, last_text: last.text, task_id: taskId, source_uri: last.source_uri,
      limits: value.limits, cancel_resets_consent: true, previous_resets_consent: true, model_answer_requests: 0 };

    const reading = fixture.reading, task = (await read(`/api/tasks/${reading.task_id}`)).task;
    assert.equal(task.title, TITLE); assert.equal(task.source_type, 'local'); assert.equal(task.summary_source, 'text-llm');
    assert.equal(task.status, 'success'); assert(task.source_media_path);
    const edition = await read(`/api/tasks/editions/task/${reading.task_id}`);
    assert.equal(edition.revision, reading.edition_revision);
    const mapped = await read(`/api/tasks/${reading.task_id}/claims`);
    assert.equal(mapped.source_revision, edition.revision);
    for (const id of [reading.claim_id, reading.oversized_claim_id]) {
      const claim = mapped.claims.find(row => row.claim_id === id); assert(claim && claim.verification === 'direct' && claim.evidence_ids.length);
    }
    await page.goto(`${origin}/web/index.html?task=${reading.task_id}`);
    const target = page.locator('#document h4').filter({ hasText: HEADING }); await target.waitFor();
    const headingId = await target.getAttribute('id');
    const startId = await page.locator('#document h2').first().getAttribute('id');
    // Native viewport and shipped motion settings are retained. No style/CSS or
    // scroll-margin injection; only the real outline controls navigate.
    for (let repeat = 0; repeat < 2; repeat++) {
      await page.locator('#openOutline').click();
      await page.locator('#outlineDialog .outline-tree button').first().click();
      await waitForOutlineScroll(page, startId);
      const before = await page.evaluate(() => scrollY);
      await page.locator('#openOutline').click();
      await page.locator('#outlineDialog').getByRole('button', { name: HEADING, exact: true }).click();
      await waitForOutlineScroll(page, headingId);
      const geometry = await page.evaluate(readOutlineHeading, headingId);
      assertOutlineHeadingVisible(geometry);
      assert(Math.abs(geometry.scrollY - before) > 100);
      assert(Math.abs(geometry.stickyOffset - geometry.headerBottom) <= 1);
      assert(Math.abs(geometry.scrollMargin - Math.max(140, geometry.stickyOffset + 12)) <= 1);
      assert.equal(geometry.editorHidden, true);
      state.outline.push({ repeat, ...geometry });
      await capture(`installed-outline-h4-${repeat}.png`);
    }
    await page.locator(`.note-claim-marker[data-claim-id="${reading.claim_id}"]`).click();
    await page.waitForFunction(taskId => {
      const player = document.querySelector('#player'), source = document.querySelector('#sourcePanel');
      return player.readyState >= 1 && player.dataset.sourceTaskId === taskId && !player.hidden &&
        !source.hidden && source.dataset.sourceTaskId === taskId && source.dataset.contentMode === 'transcript';
    }, reading.task_id);
    assert(await page.locator('#followNote').isVisible());
    assert.equal(await page.locator('#pinSource').getAttribute('aria-pressed'), 'false');
    assert.equal(await page.locator('#player').evaluate(node => node.paused), true);
    await assertClaimFollowVisibility(page, { claimId: reading.claim_id, oversizedClaimId: reading.oversized_claim_id,
      out, name: 'installed-follow-native-viewport', records: state.follow, listTextLimit: 4096 });
    for (const item of state.follow[0].cases) report.screenshots.push(item.capture);
    const previews = state.writes.filter(row => row.route === `/api/tasks/${taskId}/qa/preview`);
    const readingEvents = state.writes.filter(row => row.route === '/api/study/activity');
    assert.equal(previews.length, 2); assert.equal(readingEvents.length, 2);
    assert.equal(state.writes.length, 4); assert(state.writes.every(row => row.method === 'POST'));
    assert.deepEqual(readingEvents.map(row => row.body), [
      { kind: 'reading', source_id: `task:${taskId}` }, { kind: 'reading', source_id: `task:${reading.task_id}` }]);
    state.intentional_mutations = ['Two existing reading activity records from opening the two synthetic tasks'];
    state.no_model_dispatch_or_source_mutation = true;
    state.passed = true;
  } finally { page.off('request', record); }
  return state;
}
module.exports = { validateFeatureFixture, assertPage, assertPreview, runInstalledFeatures };
