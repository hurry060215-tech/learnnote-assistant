import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import http from 'node:http';
import diagnostic from '../../scripts/installed-diagnostic-acceptance.cjs';
import architecture from '../../scripts/installed-architecture-acceptance.cjs';

function manifestFixture(work) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'learnnote-manifest-'));
  const file = path.join(root, 'architecture-fixture.json');
  try { return work(file, root); }
  finally {
    assert.equal(path.dirname(root), os.tmpdir());
    for (const name of fs.readdirSync(root)) fs.unlinkSync(path.join(root, name));
    fs.rmdirSync(root);
  }
}

test('fixture JSON uses one descriptor and never reads more than 8193 bytes', () => {
  manifestFixture(file => {
    fs.writeFileSync(file, JSON.stringify({ synthetic: true }));
    let opened = 0, closed = 0, requested = 0;
    const io = { ...fs, openSync(...args) { opened++; return fs.openSync(...args); },
      readSync(fd, buffer, offset, length, position) { requested = Math.max(requested, position + length); return fs.readSync(fd, buffer, offset, length, position); },
      closeSync(fd) { closed++; fs.closeSync(fd); } };
    assert.deepEqual(diagnostic.readFixtureManifest(file, io), { synthetic: true });
    assert.equal(opened, 1); assert.equal(closed, 1); assert.equal(requested, 8193);
    fs.writeFileSync(file, ' '.repeat(256 * 1024));
    assert.throws(() => diagnostic.readFixtureManifest(file, io), /Bounded synthetic/);
    assert.equal(opened, 2); assert.equal(closed, 2); assert.equal(requested, 8193);
  });
});

test('fixture rejects malformed JSON, alternate filenames and nonlocal paths before reading', () => {
  manifestFixture(file => {
    fs.writeFileSync(file, '{');
    assert.throws(() => diagnostic.readFixtureManifest(file), SyntaxError);
    let opened = 0;
    const io = { ...fs, openSync() { opened++; throw new Error('unexpected open'); } };
    for (const candidate of ['architecture-fixture.json', '\\\\server\\share\\architecture-fixture.json', file + ':secret', path.join(path.dirname(file), 'private.json')]) {
      assert.throws(() => diagnostic.readFixtureManifest(candidate, io));
    }
    assert.equal(opened, 0);
  });
});

test('fixture rejects replacement and mutation after open and closes its descriptor', () => {
  manifestFixture(file => {
    fs.writeFileSync(file, '{"value":1}');
    let closed = 0, reads = 0;
    const replacement = { ...fs, openSync(...args) {
      const fd = fs.openSync(...args); fs.renameSync(file, file + '.retained'); fs.writeFileSync(file, '{"value":2}'); return fd;
    }, readSync(...args) { reads++; return fs.readSync(...args); }, closeSync(fd) { closed++; fs.closeSync(fd); } };
    assert.throws(() => diagnostic.readFixtureManifest(file, replacement), /Fixture path changed/);
    assert.equal(reads, 0); assert.equal(closed, 1);
    const growing = { ...fs, readSync(...args) {
      const count = fs.readSync(...args); if (args[4] === 0) fs.appendFileSync(file, ' '); return count;
    } };
    assert.throws(() => diagnostic.readFixtureManifest(file, growing), /Fixture changed/);
  });
});

test('fixture refuses symlink identities and linked ancestors even on platforms without O_NOFOLLOW', () => {
  manifestFixture(file => {
    fs.writeFileSync(file, '{}');
    const linked = { ...fs, lstatSync(...args) { const stat = fs.lstatSync(...args); stat.isSymbolicLink = () => true; return stat; } };
    assert.throws(() => diagnostic.readFixtureManifest(file, linked), /ordinary file/);
    assert.throws(() => diagnostic.readFixtureManifest(file, { ...fs, realpathSync: () => path.join(path.dirname(file), 'other.json') }), /must not traverse links/);
    assert.throws(() => diagnostic.readFixtureManifest(file, { ...fs, fstatSync(fd) { const stat = fs.fstatSync(fd); stat.isFile = () => false; return stat; } }), /ordinary file/);
  });
});

test('installed request accepts only the exact loopback origin and reviewed route/method pairs', async () => {
  const calls = [], origin = 'http://127.0.0.1:43123';
  const request = architecture.installedRequest(origin, async (...args) => { calls.push(args); return { ok: true }; });
  for (const bad of ['https://127.0.0.1:43123', 'http://localhost:43123', 'http://example.com:43123', origin + '/path', origin + '#fragment', 'http://user@127.0.0.1:43123', 'http://127.0.0.1']) {
    assert.throws(() => architecture.installedRequest(bad));
  }
  for (const route of ['https://example.com/api', '//example.com/api', '/api/tasks/../secret/transcript', '/api/tasks/%2e%2e/transcript', '/api/tasks/id/transcript?secret=file', '/api/tasks/id/transcript#fragment', '/api/tasks/id/transcript\\other', '/api/tasks/id']) {
    assert.throws(() => request(route));
  }
  assert.throws(() => request('/api/tasks/id/transcript', { method: 'POST', body: 'data' }));
  assert.throws(() => request('/api/library/materials/import', { method: 'POST', body: 'data' }));
  assert.equal(calls.length, 0);
  await request('/api/tasks/id/transcript');
  await request('/api/library/materials/id/source');
  await request('/api/library/materials/import', { method: 'POST', body: new FormData() });
  assert.equal(calls.length, 3);
  assert(calls.every(([url, options]) => new URL(url).origin === origin && options.redirect === 'error'));
});

test('installed request rejects a real redirect without sending the source route to a second listener', async () => {
  let escaped = 0;
  const destination = http.createServer((_req, res) => { escaped++; res.end('unexpected'); });
  await new Promise(resolve => destination.listen(0, '127.0.0.1', resolve));
  const server = http.createServer((_req, res) => { res.writeHead(302, { Location: `http://127.0.0.1:${destination.address().port}/outside` }); res.end(); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const request = architecture.installedRequest(`http://127.0.0.1:${server.address().port}`);
    await assert.rejects(request('/api/tasks/owned/transcript'));
    assert.equal(escaped, 0);
  } finally { await Promise.all([new Promise(resolve => server.close(resolve)), new Promise(resolve => destination.close(resolve))]); }
});

test('network source IDs must come from matching live installed catalog records', async () => {
  const fixture = { target: { id: 'material-104', title: 'Synthetic title' }, retry: { task_id: 'retry', title: 'Synthetic retry' } };
  const catalog = { tasks: [{ id: 'retry', title: 'Synthetic retry' }] };
  const first = { materials: [], has_more: true, next_cursor: 'server cursor' }, calls = [];
  const read = async route => { calls.push(route); return { materials: [{ material_id: 'material-104', title: 'Synthetic title' }], has_more: false }; };
  assert.deepEqual(await architecture.installedSourceIds(read, fixture, catalog, first), { materialId: 'material-104', taskId: 'retry' });
  assert.deepEqual(calls, ['/api/library/materials?standalone=true&limit=100&cursor=server%20cursor']);
  await assert.rejects(architecture.installedSourceIds(read, fixture, { tasks: [] }, first), /owned installed catalog/);
  await assert.rejects(architecture.installedSourceIds(async () => ({ materials: [], has_more: false }), fixture, catalog, first), /owned installed catalog/);
  await assert.rejects(architecture.installedSourceIds(async () => first, fixture, catalog, first), /did not advance/);
});
