// Shared local/CI JavaScript gate. Native Windows dialogs remain explicit.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const NATIVE_TEST = 'web/tests/installed_diagnostic_acceptance.test.mjs';

function filesUnder(root, relative) {
  return fs.readdirSync(path.join(root, relative), { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name))
    .flatMap(entry => {
      const name = `${relative}/${entry.name}`;
      return entry.isDirectory() ? filesUnder(root, name) : entry.isFile() ? [name] : [];
    });
}

function commands(root = ROOT, native = false) {
  if (native) {
    if (!fs.statSync(path.join(root, NATIVE_TEST)).isFile()) throw new Error('Native test entry is missing');
    return [[NATIVE_TEST]];
  }
  const files = ['extension', 'web'].flatMap(directory => filesUnder(root, directory));
  const syntax = files.filter(file => /\.(?:js|mjs|cjs)$/.test(file));
  const tests = files.filter(file => /\/tests\/[^/]+\.test\.mjs$/.test(file) && file !== NATIVE_TEST);
  if (!syntax.length || !tests.length) throw new Error('JavaScript gate found no source files or tests');
  return [...syntax.map(file => ['--check', file]), ...tests.map(file => [file])];
}

function runChecks({ root = ROOT, native = false, run = spawnSync } = {}) {
  for (const args of commands(root, native)) {
    const result = run(process.execPath, args, { cwd: root, stdio: 'inherit', windowsHide: true });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      console.error(`JavaScript gate failed: ${args.join(' ')}`);
      return Number.isInteger(result.status) && result.status > 0 ? result.status : 1;
    }
  }
  return 0;
}

if (require.main === module) {
  const flags = process.argv.slice(2);
  if (flags.length && (flags.length !== 1 || flags[0] !== '--native')) {
    console.error('Usage: node scripts/check-javascript.cjs [--native]');
    process.exitCode = 2;
  } else {
    process.exitCode = runChecks({ native: flags[0] === '--native' });
  }
}

module.exports = { commands, runChecks, NATIVE_TEST };
