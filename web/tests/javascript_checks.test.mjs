import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import checks from '../../scripts/check-javascript.cjs';

function fixture(action) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'javascript-gate-'));
  try {
    for (const name of ['extension/new-module.js', 'extension/tests/example.test.mjs',
      'web/nested/new-view.js', 'web/tests/view.test.mjs', checks.NATIVE_TEST]) {
      fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
      fs.writeFileSync(path.join(root, name), '');
    }
    action(root);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
}

test('new source files and tests join the default gate without updating an allowlist', () => fixture(root => {
  const commands = checks.commands(root);
  assert(commands.some(args => args[0] === '--check' && args[1] === 'web/nested/new-view.js'));
  assert(commands.some(args => args[0] === 'extension/tests/example.test.mjs'));
  assert(commands.some(args => args[0] === 'web/tests/view.test.mjs'));
  assert(!commands.some(args => args[0] === checks.NATIVE_TEST));
  assert.deepEqual(checks.commands(root, true), [[checks.NATIVE_TEST]]);
}));

test('syntax or test failure propagates its exit status and prevents later commands', () => fixture(root => {
  const observed = [];
  const status = checks.runChecks({ root, run(executable, args, options) {
    assert.equal(executable, process.execPath);
    assert.equal(options.cwd, root);
    assert.equal(options.windowsHide, true);
    observed.push(args);
    return { status: observed.length === 2 ? 7 : 0 };
  } });
  assert.equal(status, 7);
  assert.equal(observed.length, 2);
}));

test('missing or unlaunchable test dependencies fail the gate visibly', () => fixture(root => {
  fs.unlinkSync(path.join(root, checks.NATIVE_TEST));
  assert.throws(() => checks.commands(root, true), /ENOENT/);
  const error = new Error('synthetic missing runtime');
  assert.throws(() => checks.runChecks({ root, run: () => ({ error }) }), value => value === error);
}));
