const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { safePath, observe, captureFailure, runWithEvidence } = require('../chat-stream-diagnostics.cjs');
(async () => {
  assert.equal(safePath('http://127.0.0.1:8765/web/desk.js?v=secret#fragment'), '/web/desk.js');
  assert.equal(safePath('https://private.example/a?secret'), '[non-loopback]');
  assert.equal(safePath('http://127.0.0.1/api/tasks/secret'), '[other-local-path]');
  assert.equal(safePath('http://127.0.0.1/web/' + 'a'.repeat(1000000) + '.js'), '[other-local-path]');
  const page = new EventEmitter();
  const evidence = observe(page);
  const req = { method: () => 'GET', url: () => 'http://127.0.0.1/web/desk.js?token=secret', resourceType: () => 'script', failure: () => ({ errorText: 'net::ERR_FAILED' }) };
  for (let i = 0; i < 100; i++) {
    page.emit('request', req); page.emit('requestfailed', req);
    page.emit('response', { status: () => 502, request: () => req });
    page.emit('pageerror', new Error('module http://127.0.0.1/web/desk.js?secret'));
  }
  for (const [key, values] of Object.entries(evidence)) if (key !== "dropped") { assert.equal(values.length, 80); assert.equal(evidence.dropped[key], 20); }
  page.emit("request", { ...req, resourceType: () => "image" });
  assert.equal(evidence.dropped.requests, 20, "Image traffic cannot crowd out module evidence");
  assert(!JSON.stringify(evidence).includes('secret'));
  assert.equal(evidence.bad_responses[0].status, 502);
  const timeout = new Error('locator.click: Timeout 30000ms exceeded');
  for (const captureFails of [false, true]) for (const writeFails of [false, true]) for (const cleanupFails of [false, true]) {
    const cleanup = [], writes = [];
    const p = {
      url: () => 'http://localhost:1234/?secret',
      evaluate: async fn => { assert(fn.toString().includes('ready_state')); assert(fn.toString().includes('url.pathname.length <= 256')); if (captureFails) throw new Error('evaluate failed'); return { ready_state: 'complete', assistant_count: 0, toolbar_count: 1, module_scripts: ['/web/desk.js'] }; },
      screenshot: async options => { assert.equal(options.timeout, 5000); if (captureFails) throw new Error('screenshot failed'); },
    };
    await assert.rejects(runWithEvidence(async () => { throw timeout; }, error => captureFailure(p, evidence, error, '/synthetic', (...args) => { writes.push(args); if (writeFails) throw new Error('write failed'); }), [
      async () => { cleanup.push('release'); if (cleanupFails) throw new Error('release failed'); },
      async () => { cleanup.push('browser'); if (cleanupFails) throw new Error('browser close failed'); },
      async () => { cleanup.push('server'); if (cleanupFails) throw new Error('server close failed'); },
    ]), error => error === timeout);
    assert.deepEqual(cleanup, ['release', 'browser', 'server']);
    assert.equal(writes.length, 1);
    const report = JSON.parse(writes[0][1]);
    assert.equal(report.passed, false); assert.equal(report.page_path, '/');
    assert.equal(report.diagnostic_errors.length, captureFails ? 2 : 0);
  }
  let captures = 0; const cleanup = [];
  assert.equal(await runWithEvidence(async () => 42, async () => captures++, [async () => cleanup.push('browser'), async () => cleanup.push('server')]), 42);
  assert.equal(captures, 0); assert.deepEqual(cleanup, ['browser', 'server']);
  const closeError = new Error('close'); let serverClosed = false;
  await assert.rejects(runWithEvidence(async () => 42, async () => captures++, [async () => { throw closeError; }, async () => { serverClosed = true; }]), error => error === closeError);
  assert(serverClosed);
  const launchError = new Error('browser launch'); serverClosed = false;
  let noPageReport;
  await captureFailure(undefined, {}, launchError, '/synthetic', (_, body) => { noPageReport = JSON.parse(body); });
  assert.equal(noPageReport.page_state, 'not-created');
  assert.equal(noPageReport.failure, 'browser launch');
  await assert.rejects(runWithEvidence(async () => { throw launchError; }, async () => {}, [async () => {}, async () => { serverClosed = true; }]), error => error === launchError);
  assert(serverClosed);
  console.log('diagnostic fault cases passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
