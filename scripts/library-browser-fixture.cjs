// Synthetic transports share the production catalog/page shape. Full task
// projections stay on their separate detail routes; no fixture mutates inputs.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');

function fixtureTaskCatalog(records) {
  return { schema_version: 1, total: records.length, tasks: records.map(task => ({
    id: task.id, source_task_id: task.source_task_id || '', title: task.title || '',
    source_type: task.source_type || '', mode: task.mode || 'video', status: task.status,
    summary_source: task.summary_source || '', created_at: task.created_at || '', updated_at: task.updated_at || '',
    awaiting_confirmation: Boolean(task.awaiting_confirmation),
    // A stable synthetic admission token, independent of status/progress updates.
    control_generation: task.control_generation || createHash('sha256').update(JSON.stringify([task.id, task.created_at, task.retry_count || 0, task.mode])).digest('hex'),
    catalog: true,
  })) };
}

function fixtureMaterialPage(records, search = '') {
  const params = new URLSearchParams(search);
  if (!params.has('standalone')) return { materials: [...records] };
  assert.equal(params.get('standalone'), 'true');
  for (const key of params.keys()) assert(['standalone', 'limit', 'q', 'cursor'].includes(key), `Unexpected material query: ${key}`);
  const limit = Number(params.get('limit') || '100');
  assert(Number.isInteger(limit) && limit >= 1 && limit <= 100);
  const query = (params.get('q') || '').trim().slice(0, 200);
  const standalone = records.filter(item => !item.linked_task_id);
  let matched = standalone.filter(item => item.title.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : a.material_id < b.material_id ? 1 : a.material_id > b.material_id ? -1 : 0);
  const matched_total = matched.length;
  if (params.get('cursor')) {
    const marker = JSON.parse(Buffer.from(params.get('cursor'), 'base64url').toString('utf8'));
    assert(Array.isArray(marker) && marker.length === 3 && marker.every(value => typeof value === 'string'));
    assert.equal(marker[0], query, 'Cursor belongs to a different material query');
    matched = matched.filter(item => item.updated_at < marker[1] || (item.updated_at === marker[1] && item.material_id < marker[2]));
  }
  const materials = matched.slice(0, limit), has_more = matched.length > limit, last = materials.at(-1);
  return { schema_version: 1, materials, total: standalone.length, matched_total, has_more,
    next_cursor: has_more ? Buffer.from(JSON.stringify([query, last.updated_at, last.material_id])).toString('base64url') : '' };
}

async function waitForTaskReader(page, taskId) {
  assert(/^[a-zA-Z0-9_-]+$/.test(taskId), 'Synthetic task identity must be a plain route identifier');
  // A hash navigation can leave the previous heading visible until the new
  // detail/edition request finishes. Bind readiness to the rendered owner.
  await page.locator(`#document[data-reader-source="task:${taskId}"] h1`).waitFor();
}

module.exports = { fixtureTaskCatalog, fixtureMaterialPage, waitForTaskReader };
