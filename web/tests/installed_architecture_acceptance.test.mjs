import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import checks from '../../scripts/installed-architecture-acceptance.cjs';
import diagnostic from '../../scripts/installed-diagnostic-acceptance.cjs';
const fixture = () => ({ schema_version: 1, prefix: 'Synthetic architecture abcdef123456', material_count: 105,
  material_ids: Array.from({ length: 105 }, (_, index) => `material-${index}`),
  target: { id: 'material-104', title: 'Synthetic architecture abcdef123456 104', source_sha256: 'a'.repeat(64) },
  course_id: 'owned-course', retry: { task_id: 'owned-retry', title: 'Synthetic installed reading', transcript_sha256: 'b'.repeat(64) },
  model_endpoint: 'http://127.0.0.1:12345/v1' });
class Session extends EventEmitter { calls = []; async send(method, payload) { this.calls.push({ method, payload }); } }
const url = 'http://127.0.0.1:1234/api/tasks/owned/retry-summary';
const paused = { requestId: 'authentic-response', request: { url, method: 'POST' }, responseStatusCode: 200 };

test('architecture fixture binds all 105 IDs, the outside source and the exact keyless loopback model', () => {
  checks.validateFixture(fixture());
  for (const mutate of [v => v.material_ids.pop(), v => v.material_ids[104] = v.material_ids[0],
    v => v.target.id = 'not-seeded', v => v.model_endpoint = 'https://example.com/v1',
    v => v.model_endpoint = 'http://key@127.0.0.1:1234/v1', v => v.extra = true]) {
    const value = fixture(); mutate(value); assert.throws(() => checks.validateFixture(value));
  }
});

test('architecture phase is an explicit addition to the existing full native feature gate', () => {
  const args = ['out', '1234', 'http://127.0.0.1:1235', 'caption', '42', '--expected-version', '0.2.17', '--feature-fixture', 'features.json'];
  assert(diagnostic.parseArgs([...args, '--architecture-fixture', 'architecture.json']).architectureFixture);
  assert.throws(() => diagnostic.parseArgs([...args.slice(0, -2), '--architecture-fixture', 'architecture.json']));
  assert.throws(() => diagnostic.parseArgs([...args, '--architecture-fixture', 'architecture.json', '--startup-only']));
  assert.throws(() => diagnostic.parseArgs([...args, '--architecture-fixture', 'one', '--architecture-fixture', 'two']));
  assert.throws(() => diagnostic.parseArgs([...args, '--architecture-fixture']));
});

test('response delay preserves the real response and releases it only after the caller changed navigation', async () => {
  const session = new Session(), steps = [];
  await checks.holdResponse(session, url, async (ready, resume) => {
    session.emit('Fetch.requestPaused', paused); const actual = await ready;
    assert.equal(actual, paused); assert.equal(session.calls.length, 1);
    steps.push('home'); await resume(); steps.push('released');
  });
  assert.deepEqual(steps, ['home', 'released']);
  assert.deepEqual(session.calls, [
    { method: 'Fetch.enable', payload: { patterns: [{ urlPattern: url, requestStage: 'Response' }] } },
    { method: 'Fetch.continueResponse', payload: { requestId: paused.requestId } },
    { method: 'Fetch.disable', payload: undefined },
  ]);
  assert.equal(session.listenerCount('Fetch.requestPaused'), 0);
});

test('a failed navigation resumes the authentic response and removes interception before propagating failure', async () => {
  const session = new Session(), failure = new Error('navigation failed');
  await assert.rejects(checks.holdResponse(session, url, async ready => {
    session.emit('Fetch.requestPaused', paused); await ready; throw failure;
  }), error => error === failure);
  assert.deepEqual(session.calls.map(call => call.method), ['Fetch.enable', 'Fetch.continueResponse', 'Fetch.disable']);
  assert.equal(session.listenerCount('Fetch.requestPaused'), 0);
});

test('missing or unexpected authentic responses fail instead of synthesizing a success', async () => {
  const session = new Session();
  await assert.rejects(checks.holdResponse(session, url, ready => ready, 5), /Timed out/);
  assert.deepEqual(session.calls.map(call => call.method), ['Fetch.enable', 'Fetch.disable']);
  const other = new Session();
  await assert.rejects(checks.holdResponse(other, url, async ready => {
    other.emit('Fetch.requestPaused', { ...paused, request: { url: url + '/other', method: 'POST' } }); await ready;
  }), /Unexpected/);
  assert.deepEqual(other.calls.map(call => call.method), ['Fetch.enable', 'Fetch.disable']);
});

test('response cleanup failures never replace the original navigation failure', async () => {
  const session = new Session(), failure = new Error('navigation failed'), original = session.send.bind(session);
  session.send = async (method, payload) => { await original(method, payload); if (method === 'Fetch.continueResponse') throw new Error('detached'); };
  await assert.rejects(checks.holdResponse(session, url, async ready => {
    session.emit('Fetch.requestPaused', paused); await ready; throw failure;
  }), error => error === failure && error.response_gate_cleanup_failed === true);
  assert.equal(session.calls.at(-1).method, 'Fetch.disable');
});

test('catalog validation rejects full detail payloads and missing source lineage', () => {
  const row = Object.fromEntries(['id', 'source_task_id', 'title', 'source_type', 'mode', 'status', 'summary_source', 'created_at', 'updated_at', 'awaiting_confirmation', 'control_generation'].map(key => [key, 'synthetic']));
  row.catalog = true;
  checks.validateCatalog({ schema_version: 1, tasks: [row], total: 1 });
  assert.throws(() => checks.validateCatalog({ schema_version: 1, tasks: [{ ...row, transcript: [] }], total: 1 }));
  const missing = { ...row }; delete missing.source_task_id;
  assert.throws(() => checks.validateCatalog({ schema_version: 1, tasks: [missing], total: 1 }));
});
