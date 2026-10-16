/* Actual official Obsidian, actual compiled plugin, actual local backend.
 * Synthetic vault/profile only; no API replacement or sandbox disabling.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const {spawn, execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const option = (key, fallback) => { const i = process.argv.indexOf(key); return i < 0 ? fallback : process.argv[i + 1]; };
const output = path.resolve(option('--output', 'build/obsidian-native'));
const executable = option('--executable', '');
const python = option('--python', 'python3');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
async function waitFor(fn, label) {
  const deadline = Date.now() + 90000;
  let last;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch (error) { last = error; }
    await pause(300);
  }
  throw new Error(`${label}: ${last || 'timeout'}`);
}
async function stop(process) {
  if (!process || process.exitCode !== null) return;
  process.kill('SIGTERM');
  await Promise.race([new Promise(resolve => process.once('exit', resolve)), pause(10000)]);
  if (process.exitCode === null) process.kill('SIGKILL');
}
async function main() {
  assert.equal(process.platform, 'darwin', 'Official macOS app required');
  assert.ok(executable, '--executable is required');
  await fs.mkdir(output, {recursive: true});
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'learnnote-obsidian-'));
  const vault = path.join(temporary, 'Synthetic vault');
  const profile = path.join(temporary, 'profile');
  const pluginDir = path.join(vault, '.obsidian/plugins/learnnote-assistant');
  await fs.mkdir(pluginDir, {recursive: true});
  await fs.mkdir(profile, {recursive: true});
  for (const name of ['main.js', 'manifest.json', 'styles.css']) {
    await fs.copyFile(path.join(root, 'integrations/obsidian-learnnote', name), path.join(pluginDir, name));
  }
  // These files belong only to the disposable vault, never an existing vault.
  await fs.writeFile(path.join(vault, '.obsidian/community-plugins.json'), JSON.stringify(['learnnote-assistant']));
  await fs.writeFile(path.join(vault, '.obsidian/app.json'), JSON.stringify({safeMode: false, defaultViewMode: 'preview'}));
  await fs.writeFile(path.join(profile, 'obsidian.json'), JSON.stringify({vaults: {learnnotesynthetic: {path: vault, ts: Date.now(), open: true}}, updateDisabled: true}));
  const port = await freePort(), debugPort = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  await fs.writeFile(path.join(pluginDir, 'data.json'), JSON.stringify({backendUrl: origin, includeManifest: true, openAfterImport: true}));
  const env = {...process.env};
  for (const key of Object.keys(env)) if (/^(LEARNNOTE_|OPENAI_|LLM_|ANTHROPIC_)/.test(key)) delete env[key];
  const fixture = JSON.parse(execFileSync(python, ['scripts/personal-anchors-fixture.py'], {cwd: root, env, encoding: 'utf8'}).trim().split('\n').pop());
  let backend, obsidian, browser;
  const logs = [];
  const report = {status: 'failed', commit: process.env.GITHUB_SHA || 'local', official_app: true, synthetic_vault: true, api_mocked: false, checks: []};
  try {
    backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
      cwd: root, env: {...env, PYTHONPATH: path.join(root, 'backend'), LEARNNOTE_DATA_DIR: fixture.data_dir, LEARNNOTE_BACKEND_ORIGIN: origin, HF_HUB_OFFLINE: '1'}});
    backend.stdout.on('data', b => logs.push(b.toString())); backend.stderr.on('data', b => logs.push(b.toString()));
    await waitFor(async () => (await fetch(origin + '/health')).ok, 'backend health');
    const annotation = await fetch(`${origin}/api/personal/task/${fixture.task_id}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: 'Native annotation café 日本語 🧭', quote: 'An exact generated claim.'})});
    assert.equal(annotation.status, 200, await annotation.text());
    obsidian = spawn(executable, [`--user-data-dir=${profile}`, `--remote-debugging-address=127.0.0.1`, `--remote-debugging-port=${debugPort}`], {env, cwd: temporary});
    obsidian.stdout.on('data', b => logs.push(b.toString())); obsidian.stderr.on('data', b => logs.push(b.toString()));
    await waitFor(async () => (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).ok, 'Obsidian CDP');
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`);
    const page = await waitFor(async () => {
      for (const context of browser.contexts()) for (const candidate of context.pages()) {
        if (await candidate.evaluate(() => Boolean(window.app?.vault?.getName && window.app.vault.getName() === 'Synthetic vault')).catch(() => false)) return candidate;
      }
    }, 'synthetic vault window');
    // Obsidian deliberately asks before loading a vault's first plugin. Accept
    // the native prompt only for this run's disposable vault and our sole plugin.
    const openedVault = await page.evaluate(() => app.vault.adapter.getBasePath());
    assert.equal(await fs.realpath(openedVault), await fs.realpath(vault));
    assert.deepEqual(await fs.readdir(path.join(vault, '.obsidian/plugins')), ['learnnote-assistant']);
    const trustButton = page.getByRole('button', {name: 'Trust author and enable plugins', exact: true});
    await waitFor(async () => await trustButton.isVisible() || await page.evaluate(() => Boolean(app.plugins.plugins['learnnote-assistant'])), 'native plugin trust prompt');
    if (await trustButton.isVisible()) {
      await page.screenshot({path: path.join(output, 'native-vault-trust-prompt.png'), fullPage: true});
      await trustButton.click();
      report.checks.push('native_trust_prompt_for_own_plugin_in_disposable_vault');
    }
    await page.waitForFunction(() => Boolean(window.app.plugins.plugins['learnnote-assistant']), undefined, {timeout: 60000});
    report.obsidian_version = await page.evaluate(() => require('obsidian').apiVersion);
    report.checks.push('official_native_app_and_real_plugin_loaded');
    const imported = await page.evaluate(async taskId => {
      const plugin = app.plugins.plugins['learnnote-assistant'];
      return plugin.importer.importTask(await plugin.api.task(taskId));
    }, fixture.task_id);
    assert.equal(imported.created, true);
    const notePath = path.join(vault, imported.notePath);
    assert.match(await fs.readFile(notePath, 'utf8'), /An exact generated claim/);
    const metadataPath = path.join(vault, imported.folderPath, '_learnnote.json');
    const firstMeta = JSON.parse(await fs.readFile(metadataPath, 'utf8'));
    assert.ok(firstMeta.annotation_snapshot);
    const snapshotPath = path.join(vault, imported.folderPath, firstMeta.annotation_snapshot);
    assert.match(await fs.readFile(snapshotPath, 'utf8'), /Native annotation café 日本語 🧭/);
    report.checks.push('real_backend_bundle_import_and_annotation_snapshot');
    await page.evaluate(async ({note, snapshot}) => {
      const file = app.vault.getAbstractFileByPath(note);
      await app.vault.modify(file, (await app.vault.read(file)) + '\nPersonal local edit café 🧭\n');
      const annotation = app.vault.getAbstractFileByPath(snapshot);
      await app.vault.modify(annotation, (await app.vault.read(annotation)) + '\nLocally edited snapshot 日本語\n');
    }, {note: imported.notePath, snapshot: `${imported.folderPath}/${firstMeta.annotation_snapshot}`});
    await fs.appendFile(fixture.note_path, '\nNative regenerated content v2.\n');
    const updated = await page.evaluate(async taskId => {
      const plugin = app.plugins.plugins['learnnote-assistant'];
      return plugin.importer.importTask(await plugin.api.task(taskId));
    }, fixture.task_id);
    assert.equal(updated.created, false);
    const updatedNote = await fs.readFile(notePath, 'utf8');
    assert.match(updatedNote, /Native regenerated content v2/);
    assert.match(updatedNote, /Personal local edit café 🧭/);
    assert.match(await fs.readFile(snapshotPath, 'utf8'), /Locally edited snapshot 日本語/);
    const secondMeta = JSON.parse(await fs.readFile(metadataPath, 'utf8'));
    assert.notEqual(secondMeta.annotation_snapshot, firstMeta.annotation_snapshot);
    report.checks.push('native_update_preserves_personal_text_and_edited_snapshot_conflict');
    await page.evaluate(async () => {
      const leaf = app.workspace.getMostRecentLeaf();
      await leaf.setViewState({...leaf.getViewState(), state: {...leaf.getViewState().state, mode: 'preview'}});
    });
    await page.getByRole('link', {name: '带时间戳字幕', exact: true}).click();
    await page.waitForFunction(expected => app.workspace.getActiveFile()?.path === expected, `${imported.folderPath}/Transcript.md`);
    assert.match(await page.locator('.workspace-leaf.mod-active').innerText(), /First overlapping caption/);
    await page.screenshot({path: path.join(output, 'native-transcript-link.png'), fullPage: true});
    report.checks.push('rendered_internal_source_link_opens_actual_transcript');
    await page.evaluate(async note => app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath(note)), imported.notePath);
    await page.screenshot({path: path.join(output, 'native-updated-note.png'), fullPage: true});
    await fs.copyFile(notePath, path.join(output, 'synthetic-imported-note.md'));
    report.status = 'pass';
    report.not_tested = ['real_video_platform_seek', 'reverse_sync', 'user_vault', 'store_install'];
  } catch (error) {
    report.error = String(error.stack || error);
    if (browser) for (const context of browser.contexts()) for (const page of context.pages()) await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    throw error;
  } finally {
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    await fs.writeFile(path.join(output, 'process.log'), logs.join(''));
    if (browser) await browser.close().catch(() => {});
    await stop(obsidian); await stop(backend);
    await fs.rm(temporary, {recursive: true, force: true});
  }
  console.log(JSON.stringify(report, null, 2));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
