/* Shipped asset contracts only. No browser, socket, extension or model is started. */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const {extensionAsset} = require('../core-output-acceptance.cjs');
const {asset} = require('../extension-locale-visual-acceptance.cjs');
const ROOT = path.resolve(__dirname, '../..');
const source = name => fs.readFileSync(path.join(ROOT, 'scripts', name), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'extension/sidepanel.html'), 'utf8');
const references = [...html.matchAll(/<(script|link|img)\b[^>]*\b(?:src|href)="([^"]+)"/g)].map(match => match[2]);

// The captions fixture has its own inline, root-contained static server. Exercise
// its actual callback without refactoring that unrelated helper or opening a port.
function captionsAsset(url) {
  const callback = source('captions-panel-acceptance.cjs').match(/http\.createServer\((\(req,res\)=>\{[^\n]+\})\);/);
  assert(callback, 'Audit the captions asset server if its implementation changes');
  let streamed = null, status = 200;
  const fakeFs = {...fs, createReadStream(file) { streamed = file; return {pipe() {}}; }};
  const handler = vm.runInNewContext(`(${callback[1]})`, {root: ROOT, path, fs: fakeFs, URL});
  handler({url}, {writeHead(value) {status = value;}, setHeader() {}, end() {}});
  return status === 200 ? streamed : null;
}

test('Every shipped sidepanel script, stylesheet and image resolves through each hosted serving path', () => {
  assert(references.length >= 8, 'Parse the actual sidepanel assets, including cache-busted script URLs');
  assert(references.includes('community-source.js'));
  assert(references.includes('sidepanel-community.js'));
  for (const reference of ['sidepanel.html', ...references]) {
    const expected = path.join(ROOT, 'extension', new URL(reference, 'http://localhost/').pathname);
    assert(fs.statSync(expected).isFile(), `Missing shipped asset ${reference}`);
    assert.equal(extensionAsset(`http://127.0.0.1:8765/__extension/${reference}`), expected, `Core output: ${reference}`);
    assert.equal(extensionAsset(`/__extension/${reference}`), expected, `Core relative URL: ${reference}`);
    assert.equal(asset(`/extension/${reference}`), expected, `Shared locale/server: ${reference}`);
    assert.equal(captionsAsset(`/extension/${reference}`), expected, `Captions server: ${reference}`);
  }
});

test('Core output retains a finite asset set and rejects traversal, aliases, unknown and unrelated files', () => {
  for (const url of [
    '/__extension/unknown.js', '/__extension/manifest.json', '/__extension/background.js',
    '/__extension/content-community.js', '/__extension/tests/fixtures/community/visible-page.html',
    '/__extension/icons/icon999.png', '/__extension/icon48.png', '/__extension/nested/sidepanel.js',
    '/__extension/../backend/app/main.py', '/__extension/../__extension/sidepanel.js',
    '/__extension/./sidepanel.js', '/__extension/%2e%2e/__extension/sidepanel.js',
    '/__extension/%252e%252e/sidepanel.js', '/__extension/%73idepanel.js',
    '/__extension/icons%2ficon48.png', '/__extension/..\\__extension\\sidepanel.js',
    '/extension/sidepanel.html', '/backend/app/main.py', 'http://[invalid'
  ]) assert.equal(extensionAsset(url), null, url);
  // Query strings are cache metadata, never another asset path.
  assert.equal(extensionAsset('/__extension/unknown.js?file=sidepanel.js'), null);
  assert.equal(extensionAsset('/__extension/sidepanel.js?v=0.2.15'), path.join(ROOT, 'extension/sidepanel.js'));
});

test('Shared and captions servers still reject absent files and out-of-root paths', () => {
  for (const resolve of [asset, captionsAsset]) {
    for (const url of ['/extension/unknown-fixture-asset.js', '/extension/../../etc/passwd',
      '/extension/%2e%2e/%2e%2e/etc/passwd', '/extension/%252e%252e/etc/passwd']) {
      assert.equal(resolve(url), null, url);
    }
  }
  assert.equal(asset('/extension/../../backend/app/main.py'), null);
});

test('All hosted sidepanel helpers are covered by the serving-path inventory', () => {
  const hosts = fs.readdirSync(path.join(ROOT, 'scripts')).filter(name => name.endsWith('.cjs') && source(name).includes('sidepanel.html')).sort();
  assert.deepEqual(hosts, ['captions-panel-acceptance.cjs', 'community-capture-visual-acceptance.cjs',
    'core-output-acceptance.cjs', 'extension-locale-visual-acceptance.cjs', 'extension-store-visual-fixtures.cjs',
    'range-platform-browser-acceptance.cjs', 'sidepanel-progressive-acceptance.cjs']);
  for (const name of ['community-capture-visual-acceptance.cjs', 'range-platform-browser-acceptance.cjs', 'sidepanel-progressive-acceptance.cjs']) {
    assert.match(source(name), /\{[^}]*\basset\b[^}]*\}\s*=\s*require\(['"]\.\/extension-locale-visual-acceptance\.cjs['"]\)/, name);
    assert.match(source(name), /asset\((?:req|request)\.url\)/, name);
  }
  assert.match(source('extension-locale-visual-acceptance.cjs'), /asset\(req\.url\)/);
  assert.match(source('extension-locale-visual-acceptance.cjs'), /captureStoreCandidates\(\{browser,origin:/);
  assert.match(source('core-output-acceptance.cjs'), /extensionAsset\(route\.request\(\)\.url\(\)\)/);
});
