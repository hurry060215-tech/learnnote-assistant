// Actual Edge -> HTTP -> AsyncOpenAI -> local operations -> disk.
// Only model responses and read-only connection metadata are synthetic.
// The recovery test drops a REAL advance response after backend execution.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');

const root = path.resolve(__dirname, '..');
const out = path.resolve(process.argv[2] || 'build/assistant-runs-ui');
const sha256 = value => createHash('sha256').update(value).digest('hex');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await delay(50);
  }
  throw Error(`Timed out: ${description}`);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'backend.log'), '');
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'learnnote-runs-acceptance-'));
  const errors = [], blockedRequests = [], modelRequests = [], runs = [], downloads = [];
  const fixture = '# Bounded workflow synthetic source\n\nOriginal paragraph.\n\n```html\n<img data-run-probe src="about:blank" onerror="window.__runMarkupExecuted=true">\n```\n\nSynthetic source only.\n';
  const edited = fixture.replace('Original paragraph.', 'Edited by the actual bounded workflow.');
  const appended = edited + '\nRecovery appended exactly once.\n';
  const scenarios = new Map();
  let browser, page, backend, base, materialId, sourcePath, editionPath, delayed, dropped;
  let backendFailure, backendOutput = '', createdRequests = 0, advanceRequests = 0;
  const report = { ok: false, browser: 'Microsoft Edge', model_responses_mocked: true,
    connection_metadata_mocked: true, actual_api: false, actual_sdk: false, actual_disk: false,
    external_network_blocked: true, runs, downloads, model_requests: modelRequests, errors };
  const model = http.createServer(async (request, response) => {
    try {
      assert.equal(request.method, 'POST');
      assert.equal(request.url, '/v1/chat/completions');
      assert.match(request.headers['user-agent'], /^(?:Async)?OpenAI\/Python/);
      assert.equal(request.headers.authorization, 'Bearer local-no-key');
      report.actual_sdk = true;
      let body = '';
      for await (const chunk of request) {
        body += chunk;
        assert(body.length < 100000, 'Model request remains bounded');
      }
      const value = JSON.parse(body);
      assert.equal(value.model, 'mocked-acceptance-model');
      assert.equal(value.parallel_tool_calls, false);
      assert.equal(value.max_tokens, 3000);
      assert.deepEqual(value.tools.map(tool => tool.function.name).sort(), ['edit_note', 'export_note', 'read_note']);
      assert.equal(value.messages[0].role, 'system');
      const goal = JSON.parse(value.messages[1].content);
      const scenario = scenarios.get(goal.question);
      assert(scenario, 'Only a declared synthetic scenario may call the model');
      assert.equal(goal.source.id, materialId);
      const receipts = value.messages.slice(2).map(message => {
        assert.equal(message.role, 'user');
        return JSON.parse(message.content).actual_tool_receipt;
      });
      for (const receipt of receipts) {
        const stored = JSON.parse(fs.readFileSync(path.join(data, 'assistant-operations', receipt.operation_id + '.json'), 'utf8'));
        assert.equal(receipt.status, 'completed');
        assert.equal(stored.status, 'completed');
        assert.equal(receipt.tool, stored.tool);
        const expected = { ...stored.result };
        if (receipt.tool === 'read_note' && expected.revision !== goal.source.revision) {
          delete expected.text;
          expected.text_omitted = 'superseded_revision';
        }
        assert.deepEqual(receipt.result, expected, 'Prompt contains the actual persisted tool result');
      }
      const calls = ++scenario.calls;
      const observed = { scenario: scenario.name, call: calls, sdk: request.headers['user-agent'],
        receipt_tools: receipts.map(receipt => receipt.tool), receipt_ids: receipts.map(receipt => receipt.operation_id),
        current_read_sha256: receipts.filter(receipt => receipt.result.text !== undefined).map(receipt => sha256(receipt.result.text)) };
      modelRequests.push(observed);
      let tool, arguments_;
      if (!receipts.length) {
        assert.equal(calls, 1);
        tool = 'read_note'; arguments_ = { start_line: 1, line_count: 200 };
      } else if (scenario.edit && !receipts.some(receipt => receipt.tool === 'edit_note')) {
        assert.equal(receipts.length, 1);
        assert.equal(receipts[0].tool, 'read_note');
        assert.equal(receipts[0].result.text, scenario.before.trimEnd());
        tool = 'edit_note'; arguments_ = scenario.edit;
      } else {
        const actualRead = receipts.at(-1);
        assert.equal(actualRead.tool, 'read_note');
        assert.equal(actualRead.result.text, scenario.after.trimEnd());
        assert.equal(actualRead.result.revision, sha256(scenario.after));
        if (scenario.edit) {
          assert.equal(receipts.length, 3);
          assert.deepEqual(actualRead.verification, { revision: sha256(scenario.after),
            write_id: receipts[1].operation_id, text_sha256: sha256(scenario.after) });
          assert.equal(receipts[0].result.text, undefined, 'Superseded source text is not resent');
          observed.verified_readback_consumed = true;
        }
        tool = 'export_note'; arguments_ = { format: scenario.format };
      }
      observed.mocked_tool = tool;
      const send = () => {
        if (!response.destroyed) {
          response.writeHead(200, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ id: `mocked-${scenario.name}-${calls}`, object: 'chat.completion',
            created: 0, model: value.model, choices: [{ index: 0, finish_reason: 'tool_calls',
              message: { role: 'assistant', content: null, tool_calls: [{ id: `mocked-call-${calls}`,
                type: 'function', function: { name: tool, arguments: JSON.stringify(arguments_) } }] } }],
            usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } }));
        }
      };
      if (scenario.name === 'cancel' && calls === 2) {
        delayed = { release: send, closed: false };
        response.on('close', () => { delayed.closed = true; });
      } else send();
    } catch (error) {
      errors.push(`Mock model contract: ${error.message}`);
      response.writeHead(500); response.end('Synthetic model fixture contract failed');
    }
  });
  try {
    await new Promise(resolve => model.listen(0, '127.0.0.1', resolve));
    const modelBase = `http://127.0.0.1:${model.address().port}/v1`;
    // Whitelist process essentials: no inherited provider secrets, deployment,
    // proxy, saved connection or Python injection settings enter this backend.
    const env = {};
    for (const [key, value] of Object.entries(process.env)) {
      if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    }
    env.PYTHONUTF8 = '1'; env.PYTHONUNBUFFERED = '1'; env.PYTHONDONTWRITEBYTECODE = '1';
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || 'python',
      [path.join(__dirname, 'assistant-runs-fixture.py'), '--data-dir', data, '--model-base', modelBase],
      { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
    backend.on('error', error => {
      backendFailure = error;
      fs.appendFileSync(path.join(out, 'backend.log'), `${error.message}\n`);
    });
    backend.on('exit', (code, signal) => {
      backendFailure = Error(`Fixture backend exited (${code}, ${signal})`);
      fs.appendFileSync(path.join(out, 'backend.log'), `${backendFailure.message}\n`);
    });
    for (const stream of [backend.stdout, backend.stderr]) stream.on('data', chunk => {
      fs.appendFileSync(path.join(out, 'backend.log'), chunk);
      backendOutput += chunk.toString();
      const match = backendOutput.match(/\{"fixture_origin":\s*"(http:\/\/127\.0\.0\.1:\d+)"/);
      if (match) base = match[1];
    });
    await until(async () => {
      if (backendFailure) throw backendFailure;
      if (!base) return false;
      try { return (await fetch(base + '/health', { signal: AbortSignal.timeout(1000) })).ok; }
      catch { return false; }
    }, 'isolated backend health (see backend.log)', 60000);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
      reducedMotion: 'reduce', serviceWorkers: 'block', acceptDownloads: true });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) {
        blockedRequests.push({ origin: url.origin, path: url.pathname });
        return route.abort('blockedbyclient');
      }
      if (url.pathname === '/api/model/connection') {
        assert.equal(request.method(), 'GET', 'Never persist model settings or credentials');
        return route.fulfill({ json: { model: { provider: 'custom', base_url: modelBase,
          model: 'mocked-acceptance-model', use_saved_connection: false }, configured: true,
          storage: 'none', message: 'Mocked loopback model for synthetic acceptance only' } });
      }
      if (request.method() === 'POST' && url.pathname === '/api/assistant/runs') createdRequests++;
      if (request.method() === 'POST' && /\/api\/assistant\/runs\/[^/]+\/advance$/.test(url.pathname)) {
        advanceRequests++;
        if (scenarios.get('Synthetic recovery: append once and export html.')?.dropNext) {
          scenarios.get('Synthetic recovery: append once and export html.').dropNext = false;
          const actual = await route.fetch();
          assert(actual.ok(), await actual.text());
          dropped = { run: await actual.json(), request: request.postDataJSON(), url: request.url() };
          assert.equal(dropped.run.status, 'ready');
          assert.equal(dropped.run.steps[0].status, 'completed');
          await actual.dispose();
          return route.abort('failed'); // Lost transport only; no fabricated run state.
        }
      }
      return route.continue();
    });
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const api = async (pathname, options) => {
      const response = await page.request.fetch(base + pathname, options);
      assert(response.ok(), `${response.status()} ${pathname}: ${await response.text()}`);
      return response.json();
    };
    const imported = await api('/api/library/materials/import', { method: 'POST', multipart: {
      file: { name: 'bounded-synthetic.md', mimeType: 'text/markdown', buffer: Buffer.from(fixture) } } });
    materialId = imported.material.material_id;
    report.actual_api = true;
    sourcePath = path.join(data, 'materials', materialId, 'bounded-synthetic.md');
    editionPath = path.join(data, 'user-editions', sha256(`material:${materialId}`) + '.json');
    assert.equal(fs.readFileSync(sourcePath, 'utf8'), fixture);
    report.actual_disk = true;
    const edition = () => api(`/api/tasks/editions/material/${materialId}`);
    const diskEdition = () => fs.existsSync(editionPath) ? fs.readFileSync(editionPath, 'utf8') : null;
    const dialog = () => page.locator('#assistantRunsDialog');
    const card = () => dialog().locator('[data-run-card]');
    async function open() {
      await page.goto(base);
      await page.locator(`#notes [data-id="${materialId}"]`).click();
      await page.waitForFunction(() => document.querySelector('#document').textContent.includes('Synthetic source only.'));
      await page.waitForFunction(endpoint => JSON.parse(localStorage.getItem('learnnote.desk.model') || '{}').base_url === endpoint, modelBase);
      await page.locator('#aiAssistant').click();
      await page.locator('#assistantOperations').click();
      await page.locator('#assistantRuns').click();
      await dialog().waitFor();
    }
    async function status(text) {
      await page.waitForFunction(expected => document.querySelector('[data-run-card] h3')?.textContent === expected, text);
      await until(async () => !(await card().locator('[data-run-refresh]').isDisabled()), 'run controls ready');
    }
    function scenario(name, format, before, after = before, edit) {
      const question = `Synthetic ${name}: ${name === 'recovery' ? 'append once and export html.' : `read${edit ? ', edit once' : ''}, then export ${format}.`}`;
      const value = { name, format, before, after, edit, calls: 0, question };
      scenarios.set(question, value); return value;
    }
    async function start(value) {
      assert.equal(await dialog().locator('[data-run-share]').isChecked(), false, 'Each new run needs new explicit sharing');
      await dialog().locator('[data-run-question]').fill(value.question);
      await dialog().locator('[data-run-share]').check();
      await dialog().locator('[data-run-start]').click();
    }
    async function currentRun(value) {
      const list = await api('/api/assistant/runs');
      const found = list.runs.filter(run => run.question === value.question);
      assert.equal(found.length, 1);
      return found[0];
    }
    async function reviewedEdit(value, mobile = false) {
      await status('等待你确认差异');
      const pending = await currentRun(value);
      assert.equal(pending.model_attempts, 2);
      assert.equal(pending.steps.length, 2);
      assert.equal((await edition()).text, value.before);
      assert.equal(diskEdition(), value.diskBefore, 'No edition write before Apply');
      assert.equal(pending.pending_operation.status, 'prepared');
      const diff = pending.pending_operation.preview.diff;
      assert.match(diff, value.name === 'recovery' ? /\+Recovery appended exactly once/ : /-Original paragraph\.[\s\S]*\+Edited by the actual bounded workflow\./);
      assert.equal((await card().locator('pre').last().innerText()).trimEnd(), diff.trimEnd());
      assert.equal(await dialog().locator('[data-run-probe]').count(), 0);
      assert.equal(await page.evaluate(() => Boolean(window.__runMarkupExecuted)), false);
      if (mobile) {
        await page.setViewportSize({ width: 390, height: 844 });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        assert(await dialog().evaluate(node => node.scrollWidth <= node.clientWidth + 1), 'Dialog does not overflow horizontally');
        for (const selector of ['[data-run-source]', '[data-run-cancel]', '[data-run-approve]', '[data-run-close]']) {
          const control = dialog().locator(selector);
          await control.scrollIntoViewIfNeeded();
          assert(await control.isVisible());
          const box = await control.boundingBox();
          assert(box.x >= 0 && box.x + box.width <= 391, `${selector} fits narrow viewport`);
        }
        await card().locator('pre').last().scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(out, 'mobile-diff.png') });
        await page.setViewportSize({ width: 1440, height: 1000 });
      } else await page.screenshot({ path: path.join(out, 'desktop-diff.png') });
      await card().locator('[data-run-approve]').click();
    }
    async function completed(value) {
      await status('已生成并核对文件');
      const run = await currentRun(value);
      assert.equal(run.status, 'completed');
      assert.equal(run.model_attempts, value.edit ? 3 : 2);
      assert(run.model_attempts <= run.limits.model_decisions && run.steps.length <= run.limits.steps);
      assert(run.active_seconds < run.limits.active_seconds);
      assert.deepEqual(run.steps.map(step => step.tool), value.edit
        ? ['read_note', 'edit_note', 'read_note', 'export_note'] : ['read_note', 'export_note']);
      assert(run.steps.every(step => step.status === 'completed'));
      assert.equal((await edition()).text, value.after);
      if (value.edit) {
        const saved = JSON.parse(diskEdition());
        assert.equal(saved.text, value.after);
        assert.equal(saved.write_id, run.edit_operation_id);
        assert.equal(run.steps[2].readback, true);
        assert.equal(run.steps[2].verification.text_sha256, sha256(value.after));
        assert.equal(run.steps[2].verification.write_id, saved.write_id);
      }
      const downloadPromise = page.waitForEvent('download');
      await card().getByRole('link', { name: '下载已生成文件' }).click();
      const download = await downloadPromise;
      assert.equal(await download.failure(), null);
      const bytes = fs.readFileSync(await download.path());
      const artifact = run.steps.at(-1).result;
      assert.equal(bytes.length, artifact.bytes);
      assert.equal(sha256(bytes), artifact.sha256);
      assert.deepEqual(bytes, fs.readFileSync(path.join(data, 'assistant-operations', artifact.name)));
      if (value.format === 'pdf') assert.equal(bytes.subarray(0, 4).toString(), '%PDF');
      if (value.format === 'docx') assert.equal(bytes.subarray(0, 2).toString(), 'PK');
      if (['markdown', 'html'].includes(value.format)) assert.match(bytes.toString(), /Edited by the actual bounded workflow\./);
      assert.equal(fs.readFileSync(sourcePath, 'utf8'), fixture);
      downloads.push({ format: value.format, bytes: bytes.length, sha256: sha256(bytes), browser_download: true });
      runs.push({ scenario: value.name, id: run.id, model_attempts: run.model_attempts,
        steps: run.steps.map(step => ({ tool: step.tool, status: step.status, readback: Boolean(step.readback) })) });
      assert.equal(await dialog().locator('[data-run-share]').isChecked(), false);
      return run;
    }

    await open();
    assert.equal(await dialog().locator('[data-run-share]').isChecked(), false);
    await dialog().locator('[data-run-question]').fill('Must remain local until explicitly shared.');
    await dialog().locator('[data-run-start]').click();
    await page.waitForFunction(() => document.querySelector('[data-run-status]').textContent.includes('请明确允许'));
    assert.equal(createdRequests, 0); assert.equal(modelRequests.length, 0);
    const primary = scenario('markdown', 'markdown', fixture, edited,
      { mode: 'replace', old_text: 'Original paragraph.', text: 'Edited by the actual bounded workflow.' });
    primary.diskBefore = diskEdition();
    await start(primary); await reviewedEdit(primary); await completed(primary);
    await page.screenshot({ path: path.join(out, 'desktop-completed.png') });
    for (const format of ['html', 'docx', 'pdf']) {
      const value = scenario(format, format, edited);
      await start(value); await completed(value);
    }

    const cancel = scenario('cancel', 'markdown', edited, edited + '\nMust never be written.\n',
      { mode: 'append', old_text: '', text: 'Must never be written.' });
    const beforeCancel = diskEdition();
    await start(cancel);
    await until(() => delayed, 'mock model is holding the second decision');
    await dialog().locator('[data-run-cancel]').click();
    await status('已取消后续步骤');
    await until(() => delayed.closed, 'AsyncOpenAI cancelled its pending HTTP connection');
    delayed.release();
    const cancelled = await currentRun(cancel);
    assert.equal(cancelled.status, 'cancelled');
    assert.equal(cancelled.model_attempts, 2);
    assert.deepEqual(cancelled.steps.map(step => step.tool), ['read_note']);
    assert.equal(diskEdition(), beforeCancel);
    assert.equal(cancel.calls, 2);
    report.cancel_pending_model = { closed_http_request: true, no_next_tool_or_write: true };

    const recovery = scenario('recovery', 'html', edited, appended,
      { mode: 'append', old_text: '', text: 'Recovery appended exactly once.' });
    recovery.diskBefore = diskEdition(); recovery.dropNext = true;
    await start(recovery);
    await until(() => dropped, 'actual completed read response was dropped');
    await status('可以继续');
    assert.equal(recovery.calls, 1);
    assert.equal(diskEdition(), recovery.diskBefore);
    const pausedAdvances = advanceRequests;
    // A stale duplicate HTTP advance must be an idempotent read of current state.
    const replay = await page.request.post(dropped.url, { data: dropped.request });
    assert(replay.ok(), await replay.text());
    const replayed = await replay.json();
    assert.equal(replayed.version, dropped.run.version);
    assert.equal(replayed.steps.length, 1); assert.equal(recovery.calls, 1);
    await card().locator('[data-run-refresh]').click(); await status('可以继续');
    assert.equal(advanceRequests, pausedAdvances);
    // A full page reload must not restart the persisted workflow either.
    await open();
    await dialog().locator('summary').click();
    await dialog().locator('[data-run-history]').click();
    await dialog().locator('[data-run-records]').getByRole('button', { name: `可以继续 · ${materialId}`, exact: true }).click();
    await status('可以继续');
    assert.equal(recovery.calls, 1); assert.equal(advanceRequests, pausedAdvances);
    await card().locator('[data-run-continue]').click();
    await reviewedEdit(recovery, true); await completed(recovery);
    assert.equal((await edition()).text.split('Recovery appended exactly once.').length - 1, 1);
    report.recovery = { dropped_real_response: true, refresh_and_reload_do_not_advance: true,
      stale_retry_does_not_duplicate: true, explicit_continue_completes: true };
    const original = await page.request.get(`${base}/api/library/materials/${materialId}/source`);
    assert(original.ok()); assert.deepEqual(await original.body(), Buffer.from(fixture));
    report.original_source_sha256 = sha256(await original.body());
    const linkedRuns = (await api('/api/assistant/runs')).runs.filter(run => run.source?.id === materialId);
    const linkedOperations = (await api('/api/assistant/operations')).operations.filter(operation => operation.source?.id === materialId);
    assert.equal(linkedRuns.length, 6);
    assert((await page.request.delete(`${base}/api/library/materials/${materialId}?confirm=delete_material`)).ok());
    for (const run of linkedRuns) {
      assert.equal((await page.request.get(`${base}/api/assistant/runs/${run.id}`)).status(), 404);
      assert.equal(fs.existsSync(path.join(data, 'assistant-runs', run.id + '.json')), false);
    }
    for (const operation of linkedOperations) assert.equal((await page.request.get(`${base}/api/assistant/operations/${operation.id}`)).status(), 404);
    assert.equal(fs.existsSync(sourcePath), false); assert.equal(fs.existsSync(editionPath), false);
    assert.equal(cancel.calls, 2);
    assert.deepEqual(errors, []);
    report.ok = true;
    report.unchecked_sharing_blocks_start = true;
    report.diff_approval_before_disk_write = true;
    report.protected_text_rendered_safely = true;
    report.narrow_viewport_width = 390;
    report.source_deletion_removes_linked_runs = linkedRuns.length;
    report.blocked_external_requests = blockedRequests;
  } catch (error) {
    errors.push(error.stack || error.message);
    if (page) await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {});
    throw error;
  } finally {
    const cleanup = async work => {
      try { await work(); }
      catch (error) { errors.push(`Fixture cleanup: ${error.message}`); report.ok = false; process.exitCode = 1; }
    };
    await cleanup(async () => { if (browser) await browser.close(); });
    await cleanup(async () => {
      if (backend?.pid && backend.exitCode === null && backend.signalCode === null) {
        backend.kill();
        await until(() => backend.exitCode !== null || backend.signalCode !== null, 'owned fixture backend exits', 10000)
          .catch(async () => {
            backend.kill('SIGKILL');
            await until(() => backend.exitCode !== null || backend.signalCode !== null, 'owned fixture backend forced exit', 5000);
          });
      }
    });
    await cleanup(async () => {
      model.closeAllConnections();
      await new Promise(resolve => model.close(resolve));
    });
    await cleanup(() => fs.rmSync(data, { recursive: true, force: true }));
    report.temporary_data_removed = !fs.existsSync(data);
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
