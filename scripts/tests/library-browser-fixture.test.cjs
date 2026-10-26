const assert = require('node:assert/strict');
const test = require('node:test');
const { fixtureTaskCatalog, fixtureMaterialPage, waitForTaskReader } = require('../library-browser-fixture.cjs');

test('catalog omits task payloads while preserving identity, linked ownership and stable generation', () => {
  const detail = { id: 'child', source_task_id: 'parent', title: 'Synthetic source', status: 'running',
    created_at: '2026-10-26', updated_at: '2026-10-26', options: { api_key: 'must-not-escape' },
    note_path: 'private/note.md', visual_windows: [{ text: 'full evidence' }], progress: 12 };
  const before = structuredClone(detail), catalog = fixtureTaskCatalog([detail]);
  assert.deepEqual(detail, before);
  assert.equal(catalog.schema_version, 1); assert.equal(catalog.total, 1);
  assert.deepEqual(Object.keys(catalog.tasks[0]).sort(), ['id', 'source_task_id', 'title', 'source_type', 'mode', 'status',
    'summary_source', 'created_at', 'updated_at', 'awaiting_confirmation', 'control_generation', 'catalog'].sort());
  assert.equal(catalog.tasks[0].source_task_id, 'parent'); assert.equal(catalog.tasks[0].catalog, true);
  assert.equal(catalog.tasks[0].control_generation, fixtureTaskCatalog([{ ...detail, progress: 85, status: 'success' }]).tasks[0].control_generation);
  assert.notEqual(catalog.tasks[0].control_generation, fixtureTaskCatalog([{ ...detail, retry_count: 1 }]).tasks[0].control_generation);
  assert(!JSON.stringify(catalog).includes('must-not-escape'));
});

test('standalone pages retain totals, deterministic cursor order and full-library title search', () => {
  const records = Array.from({ length: 103 }, (_, index) => ({ material_id: String(index).padStart(4, '0'),
    title: index === 0 ? 'Target outside first page' : `Synthetic ${index}`, updated_at: '2026-10-26', linked_task_id: '' }));
  records.push({ material_id: 'linked', title: 'Linked task material', linked_task_id: 'parent' });
  const before = structuredClone(records), first = fixtureMaterialPage(records, '?standalone=true&limit=100&q=');
  assert.equal(first.materials.length, 100); assert.equal(first.total, 103); assert.equal(first.matched_total, 103);
  assert(first.has_more); assert(first.next_cursor); assert.equal(first.materials[0].material_id, '0102');
  const last = fixtureMaterialPage(records, '?standalone=true&limit=100&q=&cursor=' + encodeURIComponent(first.next_cursor));
  assert.equal(last.materials.length, 3); assert.equal(last.has_more, false); assert.equal(last.next_cursor, '');
  assert.equal(new Set([...first.materials, ...last.materials].map(item => item.material_id)).size, 103);
  const search = fixtureMaterialPage(records, '?standalone=true&limit=100&q=TARGET');
  assert.equal(search.total, 103); assert.equal(search.matched_total, 1); assert.equal(search.materials[0].material_id, '0000');
  assert.throws(() => fixtureMaterialPage(records, '?standalone=true&limit=100&q=other&cursor=' + first.next_cursor));
  assert.throws(() => fixtureMaterialPage(records, '?standalone=true&limit=101'));
  assert.throws(() => fixtureMaterialPage(records, '?standalone=true&unknown=true'));
  assert.deepEqual(records, before);
  assert.deepEqual(fixtureMaterialPage(records, '?limit=500'), { materials: records });
});

test('same-document navigation cannot pass readiness on the previous reader heading', async () => {
  let resolveTarget, completed = false;
  const targetRendered = new Promise(resolve => { resolveTarget = resolve; });
  const page = { locator(selector) {
    // The previous document already has an h1; only the target owner is pending.
    assert.equal(selector, '#document[data-reader-source="task:next-task"] h1');
    return { waitFor: () => targetRendered };
  } };
  const wait = waitForTaskReader(page, 'next-task').then(() => { completed = true; });
  await Promise.resolve(); assert.equal(completed, false);
  resolveTarget(); await wait; assert.equal(completed, true);
  await assert.rejects(waitForTaskReader(page, 'bad"selector'), /plain route identifier/);
});
