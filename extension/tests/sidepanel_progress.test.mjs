import test from 'node:test';
import assert from 'node:assert/strict';
import { harness, section, flush } from './progressive_harness.mjs';

// Deterministic DOM/transport contracts. Real browser selection is also covered in Edge CI.
test('drafts stay literal and unverified; unchanged sections and selection nodes survive insertion', async () => {
  const h = await harness();
  const hostile = '<img src=x onerror="globalThis.pwned=true">\n**原文** cafe\u0301 🧭 {model}';
  h.state.partial.sections = [section('b', hostile), section('c')]; await h.start();
  const original = h.sections.children[0], text = original.children[1], writes = text.writes;
  assert.equal(text.textContent, hostile); assert.equal(text.children.length, 0); assert.equal(original.children[0].textContent, 'progress_draft');
  h.sections.scrollTop = 10;
  h.state.partial.sections.unshift(section('a'));
  h.streams[0].event(3); await flush();
  assert.equal(h.sections.children[1], original); assert.equal(original.children[1], text); assert.equal(text.writes, writes);
  assert.equal(h.sections.scrollTop, 110, 'preserves visible section offset when an earlier section arrives');
  assert.equal(h.status.textContent, 'progress_draft');
  h.state.partial.sections[1].revision = 'metadata-only'; h.streams[0].event(4); await flush();
  assert.equal(text.writes, writes, 'metadata changes cannot replace unchanged literal text');
  h.reader.destroy();
});

test('events reject duplicate/out-of-order/malformed IDs and rejoin after the maximum accepted cursor', async () => {
  const h = await harness(); await h.start(); const s = h.streams[0];
  s.event(9); await flush(); const count = h.calls.length;
  for (const id of [9, 8, 'NaN', '3.2', '9007199254740992']) s.event(id);
  s.event(10, { schema_version: 99 }); s.event(10, { task_id: 'other' });
  s.emit('partial_section_ready', { lastEventId: '10', data: '{bad' }); await flush();
  assert.equal(h.calls.length, count);
  s.fail(); assert(s.closed); await h.tick();
  assert.match(h.streams.at(-1).url, /after=9$/);
  const oldCount = h.calls.length; s.event(11); await flush(); assert.equal(h.calls.length, oldCount);
  h.reader.destroy();
});

test('switching task, source or backend aborts old reads and releases streams without rebinding', async () => {
  const h = await harness(); await h.start(); const s = h.streams[0];
  let finish; h.state.override = url => url.endsWith('/partial-note') ? new Promise(resolve => { finish = resolve; }) : null;
  s.event(1); await flush(); const old = h.calls.at(-1);
  h.state.override = null; h.state.task.id = h.state.partial.task_id = 'two';
  await h.start('two', 'http://localhost:9999', 'new-source');
  assert(s.closed); assert(old.options.signal.aborted); assert(h.calls.at(-1).url.startsWith('http://localhost:9999/'));
  finish({ ok: true, json: async () => ({ ...h.state.partial, sections: [section('stale')] }) }); await flush();
  assert.equal(h.sections.children[0].dataset.sectionId, 'a');
  const node = h.sections.children[0]; await h.start('two', 'http://localhost:9999', 'another-source');
  assert.notEqual(h.sections.children[0], node);
  h.reader.destroy(); assert(h.streams.every(item => item.closed)); assert.equal(h.timers.size, 0);
});

test('hidden panel has no reads or streams; resume resyncs and rejects delayed hidden responses', async () => {
  const h = await harness(); await h.start(); const s = h.streams[0]; s.event(7); await flush();
  const count = h.calls.length; h.doc.hidden = true; h.doc.emit('visibilitychange');
  assert(s.closed); assert.equal(h.timers.size, 0); s.event(8); await flush(); assert.equal(h.calls.length, count);
  h.state.partial.sections.push(section('b')); h.doc.hidden = false; h.doc.emit('visibilitychange'); await flush();
  assert.equal(h.sections.children.length, 2); assert.match(h.streams.at(-1).url, /after=7$/);
  h.reader.destroy();
});

test('connection attempts and failing fallback are bounded; explicit retry can recover', async () => {
  const h = await harness(); await h.start();
  for (let i = 0; i < 3; i++) { h.streams.at(-1).fail(); await h.tick(); }
  assert.equal(h.streams.length, 3); assert.equal(h.timers.size, 1);
  await h.tick(); assert.equal(h.streams.length, 3, 'polling cannot create an unbounded reconnect loop');
  h.state.override = () => { throw Error('offline'); };
  for (let i = 0; i < 5; i++) await h.tick();
  assert.equal(h.timers.size, 0); assert.equal(h.status.textContent, 'progress_paused'); assert.equal(h.retry.hidden, false);
  h.state.override = null; h.retry.emit('click'); await flush(); assert.equal(h.status.textContent, 'progress_draft');
  h.reader.destroy();
});

test('cancel and failure stop progress updates; retained sections never become verified', async () => {
  for (const terminal of ['cancelled', 'failed', 'cancelling']) {
    const h = await harness(); await h.start(); let finish;
    h.state.override = url => url.endsWith('/partial-note') ? new Promise(resolve => { finish = resolve; }) : null;
    h.streams[0].event(2); await flush(); const request = h.calls.at(-1);
    h.state.task.status = terminal; h.streams[0].event(3, { status: terminal }, 'task_updated'); await flush();
    assert(request.options.signal.aborted); assert.equal(h.timers.size, 0); assert(h.streams[0].closed);
    const count = h.calls.length;
    finish({ ok: true, json: async () => ({ ...h.state.partial, sections: [section('late')] }) }); await flush();
    h.reader.resume(); h.streams[0].event(4); await flush();
    assert.equal(h.calls.length, count); assert.equal(h.sections.children[0].dataset.sectionId, 'a');
    assert.equal(h.status.textContent, terminal === 'cancelled' ? 'progress_cancelled' : terminal === 'cancelling' ? 'progress_cancelling' : 'progress_failed');
    assert.equal(h.finals.length, 0); h.reader.destroy();
  }
});

test('terminal ID equal to last event is accepted and only success uses the existing final handler', async () => {
  const h = await harness(); await h.start(); h.streams[0].event(4); await flush();
  h.state.task.status = 'success'; h.streams[0].event(4, { task_id: 'one', status: 'success' }, 'task_terminal'); await flush();
  assert.equal(h.finals.length, 1); assert.equal(h.status.textContent, 'progress_complete');
  assert.equal(h.sections.children[0].children[0].textContent, 'progress_draft'); assert.equal(h.timers.size, 0);
  h.reader.destroy();
});

test('attempt/source changes replace only their own projection; task changes during reads cannot repaint', async () => {
  const h = await harness(); await h.start(); const old = h.sections.children[0];
  h.state.partial.attempt_id = 'attempt2'; h.state.partial.source_revision = 'source2';
  h.streams[0].event(2); await flush(); assert.notEqual(h.sections.children[0], old);
  let taskReads = 0;
  h.state.override = url => { if (!url.endsWith('/partial-note') && ++taskReads === 2) { h.state.task.updated_at = 'v2'; h.state.task.retry_count = 1; } return null; };
  h.state.partial.sections = [section('stale-attempt')]; h.streams[0].event(3); await flush();
  assert.equal(h.sections.children.length, 0, 'a changed retry must invalidate old sections while refreshing');
  h.state.override = null; h.state.partial.task_updated_at = 'v2'; h.state.partial.sections = [section('current')];
  await h.tick(); assert.equal(h.sections.children[0].dataset.sectionId, 'current'); h.reader.destroy();
});

test('future/malformed projections and optimistic verified sections fail closed', async () => {
  const h = await harness(); h.state.partial.sections.push({ ...section('bad'), verified: true }); await h.start();
  assert.equal(h.sections.children.length, 1);
  h.state.partial.schema_version = 99; h.state.partial.sections = [section('future')];
  h.streams[0].event(1); await flush(); assert.equal(h.sections.children[0].dataset.sectionId, 'a');
  h.reader.reset(); assert.equal(h.sections.children.length, 0); assert.equal(h.card.hidden, true); h.reader.destroy();
});

test('page suspension releases resources and resumes the cursor but cannot revive a cancelled reader', async () => {
  const h = await harness(); await h.start(); h.streams[0].event(6); await flush();
  h.reader.suspend(); assert(h.streams[0].closed); assert.equal(h.timers.size, 0);
  h.reader.resume(); await flush(); assert.match(h.streams.at(-1).url, /after=6$/);
  h.state.task.status = 'cancelling'; h.streams.at(-1).event(7, { status: 'cancelling' }, 'task_updated'); await flush();
  const count = h.calls.length; h.reader.suspend(); h.reader.resume(); await flush();
  assert.equal(h.calls.length, count); assert.equal(h.status.textContent, 'progress_cancelling'); h.reader.destroy();
});

test('events during a pending read coalesce, discard stale snapshots and render the newest document', async () => {
  const h = await harness(); await h.start(); let release;
  const old = structuredClone(h.state.partial); old.sections = [section('outdated')];
  h.state.override = url => url.endsWith('/partial-note') ? new Promise(resolve => { release = resolve; }) : null;
  h.streams[0].event(1); await flush();
  h.state.partial.sections = [section('latest')];
  for (let id = 2; id < 20; id++) h.streams[0].event(id);
  const count = h.calls.length; h.state.override = null;
  release({ ok: true, json: async () => old }); await flush();
  assert.equal(h.sections.children[0].dataset.sectionId, 'a'); assert.equal(h.calls.length, count);
  await h.tick(); assert.equal(h.sections.children[0].dataset.sectionId, 'latest');
  h.reader.destroy();
});

test('publication races preserve the current draft DOM; old or corrupt drafts get a distinct unavailable notice', async () => {
  const h = await harness(); await h.start(); const original = h.sections.children[0];
  h.state.partial.status = 'unavailable'; h.state.partial.reason = 'publication_pending'; h.state.partial.sections = [];
  h.streams[0].event(1); await flush();
  assert.equal(h.sections.children[0], original); assert.equal(h.status.textContent, 'progress_syncing');
  h.state.partial.reason = 'snapshot_changed';
  h.streams[0].event(2); await flush(); assert.equal(h.sections.children[0], original, 'verified same source/generation can preserve the draft');
  h.state.partial.source_revision = ''; h.state.partial.generation_revision = '';
  h.streams[0].event(3); await flush(); assert.equal(h.sections.children.length, 0, 'same attempt without current-source proof cannot preserve a raced source');
  h.state.partial.attempt_id = 'new-attempt'; h.streams[0].event(4); await flush(); assert.equal(h.sections.children.length, 0);
  h.state.partial.reason = 'legacy_unproven'; h.streams[0].event(5); await flush(); assert.equal(h.status.textContent, 'progress_legacy');
  h.state.partial.reason = 'invalid_artifact'; h.streams[0].event(6); await flush(); assert.equal(h.status.textContent, 'progress_unavailable');
  h.state.partial.reason = 'not_ready'; h.streams[0].event(7); await flush(); assert.equal(h.status.textContent, 'progress_waiting'); h.reader.destroy();
});

test('a same-attempt source change invalidates retained content even during publication', async () => {
  const h = await harness(); await h.start();
  h.state.partial.status = 'unavailable'; h.state.partial.reason = 'publication_pending'; h.state.partial.sections = [];
  h.state.partial.source_revision = 'different-source'; h.streams[0].event(1); await flush();
  assert.equal(h.sections.children.length, 0); assert.equal(h.status.textContent, 'progress_syncing'); h.reader.destroy();
});

test('the existing temporal outline appears before model output and keeps its literal nodes when generated sections arrive', async () => {
  const h = await harness(); const literal = '<script>原文 cafe\u0301 🧭 {model}</script>';
  const outline = { id: 'draft-time-0', revision: 'outline1', kind: 'temporal_outline', status: 'draft', verified: false, summary_generated: false, excerpts: [{ start: 0, end: 5, source_cue_index: 0, text: literal }] };
  h.state.partial.sections = [outline]; h.state.partial.generation_revision = '';
  h.state.task.artifact_status = { draft_available: true, partial_draft_available: false }; await h.start();
  const node = h.sections.children[0]; assert.equal(node.children[0].textContent, 'progress_excerpt'); assert.equal(node.children[1].textContent, literal);
  h.state.task.artifact_status.partial_draft_available = true;
  h.state.partial.generation_revision = 'generated'; h.state.partial.status = 'unavailable';
  h.state.partial.reason = 'publication_pending'; h.state.partial.sections = [];
  h.streams[0].event(1); await flush(); assert.equal(h.sections.children[0], node);
  h.state.partial.status = 'draft'; h.state.partial.reason = 'ready'; h.state.partial.sections = [outline, section('generated')];
  h.streams[0].event(2); await flush(); assert.equal(h.sections.children[0], node); assert.equal(h.sections.children.length, 2);
  h.state.partial.sections = [outline]; h.state.partial.generation_revision = '';
  for (const [index, reason] of ['legacy_unproven', 'invalid_artifact', 'attempt_mismatch', 'source_mismatch'].entries()) {
    h.state.partial.reason = reason; h.streams[0].event(3 + index); await flush();
    assert.equal(h.sections.children[0], node); assert.equal(h.sections.children.length, 1);
    assert.equal(h.status.textContent, reason === 'legacy_unproven' ? 'progress_legacy' : 'progress_unavailable');
  }
  h.reader.destroy();
});

test('terminal artifact recovery runs once with a frozen binding and is aborted on source change', async () => {
  const h = await harness(); let recovery;
  h.state.stopOverride = async binding => { recovery = binding; await new Promise(() => {}); };
  h.state.task.status = 'failed'; await h.start();
  assert.equal(recovery.taskId, 'one'); assert.match(recovery.base, /^http:\/\/127\.0\.0\.1:8765\//);
  assert.equal(h.streams.length, 0); assert.equal(h.stops.length, 1);
  h.reader.resume(); await flush(); assert.equal(h.stops.length, 1);
  const oldRecovery = recovery; h.state.stopOverride = null; h.state.task.id = h.state.partial.task_id = 'two'; h.state.task.status = 'running';
  await h.start('two', 'http://localhost:8888', 'new');
  assert(oldRecovery.signal.aborted); assert.equal(oldRecovery.isCurrent(), false);
  h.reader.destroy(); assert.equal(h.timers.size, 0);
});

test('completed sections become readable during continuous delayed progress events', async () => {
  const h = await harness(); await h.start(); let eventId = 20;
  h.state.partial.sections.push(section('completed-during-progress'));
  h.state.override = async url => {
    // Each delayed task/partial read overlaps another non-content progress update.
    await Promise.resolve();
    h.state.task.updated_at = h.state.partial.task_updated_at = `progress-${eventId}`;
    h.streams.at(-1).event(eventId++, { status: 'running', phase: 'summarizing' }, 'task_updated');
    return null;
  };
  h.streams[0].event(eventId++, {}, 'partial_section_ready'); await flush();
  for (let step = 0; step < 4 && !h.sections.children.some(node => node.dataset.sectionId === 'completed-during-progress'); step++) await h.tick();
  assert(h.sections.children.some(node => node.dataset.sectionId === 'completed-during-progress'), 'progress-only updates must not indefinitely starve completed section publication');
  h.reader.destroy();
});

test('historical failure/cancel/missing frames refresh current snapshots instead of stopping a retried task', async () => {
  const h = await harness(); await h.start();
  h.streams[0].event(1, { status: 'failed' }, 'task_updated'); await flush();
  assert.equal(h.stops.length, 0); assert.equal(h.status.textContent, 'progress_draft');
  h.streams[0].event(2, { status: 'cancelled' }, 'task_updated'); await flush(); assert.equal(h.stops.length, 0);
  h.streams[0].event(2, {}, 'task_missing'); await flush();
  assert.equal(h.stops.length, 0); assert.equal(h.status.textContent, 'progress_draft');
  h.state.task.status = 'success';
  h.streams.at(-1).event(3, { status: 'cancelled' }, 'task_terminal'); await flush();
  assert.deepEqual(h.stops, ['success']); assert.equal(h.finals.length, 1); h.reader.destroy();
});

test('a same-attempt source change during a partial read removes old-source sections immediately', async () => {
  const h = await harness(); h.state.task.source_identity = { media_sha256: 'old-source' }; await h.start();
  let release; h.state.override = url => url.endsWith('/partial-note') ? new Promise(resolve => { release = resolve; }) : null;
  h.streams[0].event(1); await flush();
  h.state.task.source_identity = { media_sha256: 'new-source' }; h.state.task.transcript_path = 'new-owned-transcript';
  const raced = { ...h.state.partial, status: 'unavailable', reason: 'snapshot_changed', source_revision: '', generation_revision: '', sections: [] };
  h.state.override = null; release({ ok: true, json: async () => raced }); await flush();
  assert.equal(h.sections.children.length, 0); assert.equal(h.status.textContent, 'progress_syncing');
  h.state.partial.source_revision = 'new-source'; h.state.partial.sections = [section('new-source-section')];
  await h.tick(); assert.equal(h.sections.children[0].dataset.sectionId, 'new-source-section'); h.reader.destroy();
});
