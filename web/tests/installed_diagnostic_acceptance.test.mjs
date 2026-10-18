import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { EventEmitter } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import acceptance from '../../scripts/installed-diagnostic-acceptance.cjs';

const { parseArgs, readInstalledJSON, verifyOwned, assertSyntheticTask, selectOwnedPage, ownedRequest, validateHostFailure, validateHostObservation, validateNativeCapture, nativeDialogScript, nativeDialogCommand, withNativeHelper, assertSavedBytes, noDownloadDuring, finish, bounded } = acceptance;
const args = ['output', '19223', 'http://127.0.0.1:8765', 'synthetic-task', '123', '--expected-version', '0.2.16'];
const task = { id: 'synthetic-task', title: 'Synthetic rollback captions', handoff_id: 'native-rollback-synthetic-caption',
  page_url: 'https://example.com/synthetic-rollback', status: 'success', summary_source: 'subtitle-extract' };

test('installed CLI requires explicit versions, separate loopback ports, exact task/PID and known harness flags', () => {
  assert.equal(parseArgs(args).expectedVersion, '0.2.16'); assert.equal(parseArgs(args).startupOnly, false);
  assert.equal(parseArgs([...args, '--startup-only']).startupOnly, true);
  assert.equal(parseArgs([...args.slice(0, 5), '--startup-only', '--expected-version', '0.2.15']).expectedVersion, '0.2.15');
  for (const changed of [args.slice(0, 5), [...args, '--unknown'], [...args, '--startup-only', '--startup-only'], [...args, '--expected-version', '0.2.17']]) assert.throws(() => parseArgs(changed));
  for (const [index, values] of [[1, ['0', '65536', '1;Stop-Process', '8765', '08765']], [2, ['https://127.0.0.1:8765', 'http://localhost:8765', 'http://remote.test:8765', 'http://127.0.0.1:8765/', 'http://x:y@127.0.0.1:8765']], [3, ['../task', 'task?secret=1']], [4, ['0', '-1', '12;Stop-Process']], [6, ['latest', '0.2.16;echo']]])
    for (const value of values) { const invalid = [...args]; invalid[index] = value; assert.throws(() => parseArgs(invalid)); }
});

test('only the exact retained synthetic task permits screenshot setup', () => {
  assertSyntheticTask(task, task.id);
  for (const field of Object.keys(task)) assert.throws(() => assertSyntheticTask({ ...task, [field]: 'other' }, task.id));
});

test('Windows ownership query binds both exact loopback listeners to the supplied app without broad process collection', () => {
  const binding = { owned_pid: 123, owned_start: '123456', api_port: 8765, api_pid: 123, debug_pid: 456, debug_start: '123457' };
  assert.deepEqual(verifyOwned(parseArgs(args), (file, command, options) => {
    assert.equal(file, 'powershell.exe'); assert.deepEqual(command.slice(0, 3), ['-NoProfile', '-NonInteractive', '-Command']);
    const script = command[3];
    assert.match(script, /\$ownedId=123; \$port=19223; \$apiPort=8765/);
    assert.match(script, /Get-NetTCPConnection -State Listen -LocalPort \$apiPort/);
    assert.match(script, /\$_.LocalAddress -notin @\('127\.0\.0\.1','::1'\) -or \$_.OwningProcess -ne \$ownedId/);
    assert.match(script, /Get-NetTCPConnection -State Listen -LocalPort \$port/);
    assert.match(script, /\$debug.Name -ne 'msedgewebview2.exe'/);
    assert.match(script, /\$cursor.ProcessId -eq \$ownedId/);
    assert.doesNotMatch(script, /CommandLine|ExecutablePath|Get-Process|Stop-Process/);
    assert.equal(options.timeout, 30000); assert.equal(options.windowsHide, true); assert.equal(options.shell, undefined);
    return JSON.stringify(binding);
  }), binding);
});

test('installed API reads use native fetch Response boolean status and reject invalid JSON or failed responses', async () => {
  const result = await readInstalledJSON('http://127.0.0.1:8765', '/health', async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8765/health');
    assert.equal(options.redirect, 'error'); assert(options.signal instanceof AbortSignal);
    return new Response(JSON.stringify({ app_version: '0.2.17' }), { status: 200 });
  });
  assert.deepEqual(result, { app_version: '0.2.17' });
  await assert.rejects(readInstalledJSON('http://127.0.0.1:8765', '/health', async () => new Response('{}', { status: 503 })), /Installed API \/health failed: 503/);
  await assert.rejects(readInstalledJSON('http://127.0.0.1:8765', '/health', async () => new Response('not JSON')), SyntaxError);
});

test('existing page selection is origin/path exact and refuses ambiguous app pages', () => {
  const page = url => ({ url: () => url }), good = page('http://127.0.0.1:8765/web/index.html?desktop=1');
  const browser = pages => ({ contexts: () => [{ pages: () => pages }] });
  assert.equal(selectOwnedPage(browser([page('about:blank'), page('http://other.test/'), good]), 'http://127.0.0.1:8765'), good);
  assert.equal(selectOwnedPage(browser([page('http://127.0.0.1:8765/web/classic.html')]), 'http://127.0.0.1:8765'), undefined);
  assert.throws(() => selectOwnedPage(browser([good, page('http://127.0.0.1:8765/')]), 'http://127.0.0.1:8765'));
});

test('network guard allows exact installed origin and blob/data while rejecting every other destination', () => {
  const origin = 'http://127.0.0.1:8765';
  for (const url of [origin + '/web/index.html', origin + '/api/tasks/id', 'blob:' + origin + '/id', 'data:text/plain,synthetic']) assert(ownedRequest(url, origin));
  for (const url of ['http://127.0.0.1:8766/api', 'https://example.com/', 'file:///private', 'http://localhost:8765', 'invalid']) assert.equal(ownedRequest(url, origin), false);
});

function fakeChild() {
  const child = new EventEmitter(); child.stdout = new EventEmitter(); child.stderr = new EventEmitter(); child.stdin = new EventEmitter();
  child.exitCode = null; child.kills = 0; child.writes = [];
  child.stdin.write = (value, callback) => { child.writes.push(value); callback?.(); };
  child.end = code => { child.exitCode = code; child.emit('close', code); };
  child.kill = () => { child.kills++; child.end(1); return true; };
  child.line = value => child.stdout.emit('data', Buffer.from(value + '\n'));
  return child;
}

test('native Save helper starts before the real click, awaits completion and signals completed actions', async () => {
  const child = fakeChild(); let clicked = false;
  const result = withNativeHelper(child, async () => {
    clicked = true; child.line('{"native_dialog":true,"saved":true}'); child.end(0);
  });
  assert.equal(clicked, false); child.line('READY');
  assert.deepEqual(await result, { native_dialog: true, saved: true });
  assert.deepEqual(child.writes, ['ACTION_COMPLETE\n']); assert.equal(child.kills, 0);
});

test('native helper startup and pre-click failures never trigger the real Save', async () => {
  for (const mode of ['launch', 'exit', 'ready-then-exit', 'invalid-output']) {
    const child = fakeChild(); let clicked = false;
    const result = withNativeHelper(child, () => { clicked = true; });
    if (mode === 'launch') { child.emit('error', new Error('local detail')); child.end(1); }
    else if (mode === 'invalid-output') child.line('unexpected raw native content');
    else { if (mode === 'ready-then-exit') child.line('READY'); child.end(1); }
    await assert.rejects(result, /Owned native|Unexpected owned/); assert.equal(clicked, false);
  }
});

test('native helper is reaped on click failure and preserves that failure if reap also fails', async () => {
  const primary = new Error('actual Save click failed');
  for (const brokenCleanup of [false, true]) {
    const child = fakeChild(); if (brokenCleanup) child.kill = () => { child.kills++; throw new Error('reap failed'); };
    const result = withNativeHelper(child, () => { throw primary; }); child.line('READY');
    await assert.rejects(result, error => error === primary); assert.equal(child.kills, 1);
    if (brokenCleanup) assert.equal(primary.native_helper_cleanup_failed, true);
  }
});

test('native helper failure interrupts a still-pending modal click and deadline reaps a held helper', async () => {
  const child = fakeChild();
  const result = withNativeHelper(child, () => { child.end(1); return new Promise(() => {}); }); child.line('READY');
  await assert.rejects(result, /Owned native Save helper failed/);
  const held = fakeChild(); let clicked = false;
  await assert.rejects(withNativeHelper(held, () => { clicked = true; }, { ready: 5 }), /Timed out: native helper readiness/);
  assert.equal(clicked, false); assert.equal(held.kills, 1);
});

test('native failures retain only an allowlisted phase and reject arbitrary diagnostic output', async () => {
  const child = fakeChild(), result = withNativeHelper(child, () => {});
  child.line('PHASE:filename-host'); child.end(1);
  await assert.rejects(result, error => error.native_stage === 'filename-host' && !error.message.includes('private'));
  const wrong = fakeChild(), rejected = withNativeHelper(wrong, () => {});
  wrong.line('PHASE:private-path-or-title'); await assert.rejects(rejected, /Unknown native helper phase/);
});

const hostFailureDetails = (count, subphase = 'match-count') => ({ subphase, host_count: count, host_count_capped: false });
const hostSnapshot = (elapsed, visibleHost = false) => ({ elapsed_ms: elapsed, truncated: false, foreign_nodes: 0,
  nodes: [{ parent: -1, depth: 0, type: 50032, cls: '#32770', id: '', pruned: false },
    ...(visibleHost ? [{ parent: 0, depth: 1, type: 50003, cls: 'AppControlHost', id: 'FileNameControlHost', pruned: false }] : [])] });
const hostObservation = () => ({ status: 'complete', snapshots: [hostSnapshot(5), hostSnapshot(260, true)],
  phase: 'complete', reason: 'complete', elapsed_ms: 260, exception_type: null });
const unavailableObservation = (phase = 'guard-before', exception_type = 'runtime') => ({ status: 'unavailable', snapshots: [],
  phase, reason: 'exception', elapsed_ms: 5, exception_type });
function emitHostFailure(child, details) {
  child.line('PHASE:filename-host'); child.line('SUBPHASE:' + details.subphase); child.line('HOSTFAIL:' + JSON.stringify(details));
}

test('host rejection records zero/multiple/provider failure separately; late matching evidence never retries Save', async () => {
  for (const details of [hostFailureDetails(0), hostFailureDetails(2), hostFailureDetails(null, 'query'), hostFailureDetails(1, 'host-validation'), hostFailureDetails(1, 'modern-ancestor')]) {
    const child = fakeChild(); let actions = 0;
    const result = withNativeHelper(child, () => {
      actions++; emitHostFailure(child, details); child.line('HOSTDIAG:' + JSON.stringify(hostObservation()));
      // Even an erroneous success exit/result cannot turn the rejection into acceptance.
      child.line('{"native_dialog":true,"saved":true}'); child.end(0);
    }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed');
      assert.deepEqual(error.native_host_failure, details); assert.equal(error.native_host_subphase, details.subphase);
      assert.deepEqual(error.native_host_observation, hostObservation()); return true;
    }); assert.equal(actions, 1);
  }
});

test('diagnostic capture failure, invalid content and timeouts preserve the original host rejection', async () => {
  for (const mode of ['missing', 'invalid', 'held']) {
    const child = fakeChild();
    const result = withNativeHelper(child, () => {
      emitHostFailure(child, hostFailureDetails(0));
      if (mode === 'invalid') child.line('HOSTDIAG:{"Name":"PRIVATE_TITLE","Value":"C:\\private"}');
      if (mode !== 'held') child.end(1); else return new Promise(() => {});
    }, { action: 5 }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed'); assert.equal(error.native_observation_unavailable, true);
      assert.equal(error.native_host_observation, undefined); assert(!JSON.stringify(error).includes('PRIVATE_TITLE'));
      return true;
    }); if (mode === 'held') assert.equal(child.kills, 1);
  }
});


test('every allowlisted observer failure remains secondary to the original native host rejection', async () => {
  const phases = ['initialization', 'guard-before', 'node-properties', 'first-child', 'next-sibling', 'guard-after'];
  const exceptions = ['element-unavailable', 'element-disabled', 'com', 'invalid-operation', 'method-invocation', 'runtime', 'other'];
  const observations = phases.flatMap(phase => exceptions.map(type => unavailableObservation(phase, type)));
  observations.push({ ...unavailableObservation('guard-after'), status: 'partial', snapshots: [hostSnapshot(5)],
    reason: 'budget', elapsed_ms: 1000, exception_type: null });
  observations.push({ ...unavailableObservation('initialization'), reason: 'unavailable', exception_type: null });
  for (const observation of observations) {
    validateHostObservation(observation);
    const child = fakeChild(); let actions = 0;
    const result = withNativeHelper(child, () => {
      actions++; emitHostFailure(child, hostFailureDetails(0));
      child.line('HOSTDIAG:' + JSON.stringify(observation)); child.end(1);
    }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed');
      assert.deepEqual(error.native_host_failure, hostFailureDetails(0));
      assert.deepEqual(error.native_host_observation, observation); return true;
    }); assert.equal(actions, 1);
  }
});

test('Windows observer fault injection exercises the actual function with synthetic types only', { skip: process.platform !== 'win32' }, () => {
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File',
    path.resolve('scripts/tests/native-observer-faults.ps1')], { encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert(!output.includes('PRIVATE_')); assert(!output.includes('C:\\private'));
  const cases = JSON.parse(output.trim());
  for (const { mode, observation } of cases.results) {
    validateHostObservation(observation);
    if (mode === 'success') {
      assert.equal(observation.status, 'complete'); assert.equal(observation.reason, 'complete');
      assert.equal(observation.snapshots.length, 2);
      for (const snapshot of observation.snapshots) {
        assert.equal(snapshot.nodes.length, 3); assert.equal(snapshot.foreign_nodes, 0);
        assert(snapshot.nodes[2].pruned); assert.equal(snapshot.nodes[2].cls, ''); assert.equal(snapshot.nodes[2].id, '');
      }
    } else if (mode === 'budget') {
      assert.equal(observation.reason, 'budget'); assert.equal(observation.exception_type, null);
      assert.equal(observation.status, 'partial'); assert.equal(observation.phase, 'guard-after');
      assert(observation.elapsed_ms >= 1000);
    } else {
      assert.equal(observation.reason, 'exception');
      const expected = mode === 'property' ? 'node-properties' : mode === 'guard-before-late' ? 'guard-before' : mode;
      assert.equal(observation.phase, expected);
      assert.equal(observation.snapshots.length, mode === 'guard-before-late' ? 1 : 0);
    }
  }
  assert.equal(cases.results.length, 8);
  assert.deepEqual(cases.exceptions, ['element-unavailable', 'element-disabled', 'com', 'invalid-operation', 'method-invocation', 'runtime', 'other']);
});

test('host metadata rejects unknown fields, paths, invalid ancestry and oversized primitive collections', () => {
  validateHostFailure(hostFailureDetails(0)); validateHostFailure({ ...hostFailureDetails(64), host_count_capped: true });
  for (const invalid of [{ ...hostFailureDetails(0), host_count: -1 }, { ...hostFailureDetails(0), host_count: 65 },
    { ...hostFailureDetails(0), host_count_capped: true }, { ...hostFailureDetails(0), subphase: 'other' }, { ...hostFailureDetails(0), Name: 'forbidden' }]) assert.throws(() => validateHostFailure(invalid));
  validateHostObservation(hostObservation()); validateHostObservation(unavailableObservation());
  const invalids = [value => { value.Name = 'forbidden'; },
    value => { value.phase = 'PRIVATE_TITLE'; }, value => { value.reason = 'C:\\private'; },
    value => { value.elapsed_ms = -1; }, value => { value.elapsed_ms = 35001; }, value => { value.elapsed_ms = 0.5; },
    value => { value.exception_type = 'PrivateException'; }, value => { value.reason = 'exception'; },
    value => { value.reason = 'budget'; }, value => { value.reason = 'unavailable'; },
    value => { delete value.phase; }, value => { value.snapshots.push(hostSnapshot(500)); },
    value => { value.snapshots[0].nodes[0].Value = 'forbidden'; }, value => { value.snapshots[0].nodes[0].cls = 'C:\\private'; },
    value => { value.snapshots[0].nodes[0].id = 'x'.repeat(65); }, value => { value.snapshots[0].nodes[0].parent = 0; },
    value => { value.snapshots[0].nodes[0].depth = 9; }, value => { value.snapshots[0].foreign_nodes = 64; },
    value => { value.snapshots[1].nodes[0].pruned = true; }, value => { value.snapshots[0].nodes = Array(65).fill(value.snapshots[0].nodes[0]); }];
  for (const mutate of invalids) { const value = hostObservation(); mutate(value); assert.throws(() => validateHostObservation(value)); }
});

test('failure observer is bounded, read-only, prunes content branches and checks ownership before and after every snapshot', () => {
  const observer = fs.readFileSync(new URL('../../scripts/installed-native-dialog-observation.ps1', import.meta.url), 'utf8');
  assert.match(observer, /sample -lt 2/); assert.match(observer, /walked -lt 64/); assert.match(observer, /entry.depth -ge 8/);
  assert.match(observer, /ElapsedMilliseconds -lt 1000/); assert.match(observer, /\$queue.Count\+\$walked\) -lt 64/);
  assert.match(observer, /\$node.Current.ProcessId -ne \$OwnedPid/); assert.equal(observer.match(/\[void\]\(& \$Guard\)/g).length, 2);
  for (const type of ['List', 'ListItem', 'Tree', 'TreeItem', 'DataGrid', 'DataItem', 'Document']) assert(observer.includes(`ControlType]::${type}`));
  assert.doesNotMatch(observer, /\.Current\.(?:Name|Value)|SetValue|\.Invoke\(|RootElement|GetWindowText|\.screenshot\(|CopyFromScreen|GetForegroundWindow/);
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  const branch = script.slice(script.indexOf('} catch {\n $original=$_;'), script.indexOf("Stage 'filename-edit';"));
  assert.match(branch, /\. \$c.observer/); assert.match(branch, /-Guard \{ Assert-Dialog \$dialog \}/);
  assert.match(branch, /catch \{ \}/); assert.match(branch, /throw \$original;/);
  assert.doesNotMatch(branch, /SetValue|\.Invoke\(|Start-Sleep/);
});


const savedCapture = () => ({ status: 'saved', reason: 'captured', file: 'installed-current-md-native-dialog.png', width: 900, height: 600 });
const unavailableCapture = () => ({ status: 'unavailable', reason: 'guard-after', file: null, width: null, height: null });
test('native screenshot evidence is fixed-name metadata and never replaces host rejection', async () => {
  for (const capture of [savedCapture(), unavailableCapture(), { ...savedCapture(), file: 'C:\\PRIVATE_PATH.png' }]) {
    const child = fakeChild(); let actions = 0;
    const result = withNativeHelper(child, () => {
      actions++; child.line('PHASE:dialog-capture'); child.line('CAPTURE:' + JSON.stringify(capture));
      emitHostFailure(child, hostFailureDetails(0)); child.end(1);
    }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed'); assert.deepEqual(error.native_host_failure, hostFailureDetails(0));
      if (capture.file?.includes('PRIVATE')) { assert.equal(error.native_capture_unavailable, true); assert.equal(error.native_dialog_capture, undefined); }
      else assert.deepEqual(error.native_dialog_capture, capture);
      assert(!JSON.stringify(error).includes('PRIVATE')); return true;
    }); assert.equal(actions, 1);
  }
  for (const capture of [savedCapture(), unavailableCapture()]) {
    const child = fakeChild(); const result = withNativeHelper(child, () => {
      child.line('PHASE:dialog-capture'); child.line('CAPTURE:' + JSON.stringify(capture));
      child.line('{"native_dialog":true,"saved":true}'); child.end(0);
    }); child.line('READY');
    assert.deepEqual((await result).native_dialog_capture, capture);
  }
});

test('native screenshot metadata rejects paths, raw errors, unexpected fields and unbounded dimensions', () => {
  validateNativeCapture(savedCapture()); validateNativeCapture(unavailableCapture());
  for (const change of [{ file: '../capture.png' }, { width: 4097 }, { height: 63 }, { width: 1.5 },
    { reason: 'PRIVATE_ERROR' }, { Name: 'PRIVATE_NAME' }, { status: 'unavailable' }])
    assert.throws(() => validateNativeCapture({ ...savedCapture(), ...change }));
  assert.throws(() => validateNativeCapture({ ...unavailableCapture(), file: 'installed-current-md-native-dialog.png' }));
});

test('native screenshot is synthetic-only, exact-window, guarded before and after, and precedes host traversal', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8');
  assert.match(source, /PrintWindow\(\$Dialog,\$dc,2\)/);
  assert.match(source, /GetWindowRect\(\$Dialog,\[ref\]\$before\)/);
  assert.match(source, /GetWindowRect\(\$Dialog,\[ref\]\$after\)/);
  assert(source.indexOf("$phase='guard-before'; [void](& $Guard)") < source.indexOf('PrintWindow($Dialog,$dc,2)'));
  assert(source.indexOf("$phase='guard-after'; [void](& $Guard)") > source.indexOf('PrintWindow($Dialog,$dc,2)'));
  assert(source.indexOf("$phase='guard-after'") < source.indexOf('[IO.File]::Open'));
  assert.match(source, /FileMode\]::CreateNew/); assert.match(source, /ReparsePoint/);
  assert.doesNotMatch(source, /CopyFromScreen|GetDesktopWindow|GetForegroundWindow|SendKeys|SetValue|\.Invoke\(|RootElement/);
  const config = { ...parseArgs(args), captureNativeDialog: true };
  const script = nativeDialogScript(config, { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  assert(script.indexOf("Stage 'dialog-capture'") < script.indexOf("Stage 'filename-host'"));
  assert(script.indexOf("Stage 'dialog-capture'") < script.indexOf('$element.FindAll'));
  assert.match(script, /-Guard \{ Assert-Dialog \$dialog \}/);
  nativeDialogCommand(script);
  const directory = 'D:\\a\\learnnote-assistant\\learnnote-assistant\\build\\release\\installed-upgrade\\local-native-exports-123456';
  nativeDialogCommand(nativeDialogScript({ ...config, ownedPid: 4294967295 }, { owned_start: '639278948132580890' },
    directory, directory + '\\learnnote-diagnostics.json'));
  const harness = fs.readFileSync(new URL('../../scripts/installed-diagnostic-acceptance.cjs', import.meta.url), 'utf8');
  assert.match(harness, /config.captureNativeDialog = syntheticVerified/);
  assert.match(harness, /config.captureNativeDialog === true && !observeOnly/);
});

test('Windows screenshot rejects unowned output paths before native rendering', { skip: process.platform !== 'win32' }, () => {
  const capture = fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8');
  const script = capture + "\n$script:calls=0; $result=Save-OwnedDialogCapture -Dialog ([IntPtr]1) -Directory 'C:\\synthetic-unowned' -Destination 'C:\\learnnote-diagnostics.md' -Guard { $script:calls++ }; @{capture=$result;calls=$script:calls} | ConvertTo-Json -Compress";
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '-'],
    { input: script, encoding: 'utf8', timeout: 15000, windowsHide: true });
  const value = JSON.parse(output.trim()); validateNativeCapture(value.capture);
  assert.equal(value.calls, 1); assert.equal(value.capture.status, 'unavailable'); assert.equal(value.capture.reason, 'destination');
});

test('native file equality reads stable exact UTF-8 bytes and retains the actual saved evidence', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'installed-native-bytes-')), file = path.join(root, 'report.md');
  const bytes = Buffer.from('\ufeff# 安全报告\r\ncafé 日本語 🧭\n');
  try {
    fs.writeFileSync(file, bytes.subarray(0, 4));
    const result = assertSavedBytes(file, bytes); setTimeout(() => fs.writeFileSync(file, bytes), 20);
    const proof = await result; assert.equal(proof.byte_equality, true); assert.equal(proof.native_saved_file, true);
    assert.equal(proof.bytes, bytes.length); assert.match(proof.sha256, /^[a-f0-9]{64}$/); assert(fs.readFileSync(file).equals(bytes));
    fs.writeFileSync(file, Buffer.alloc(bytes.length)); await assert.rejects(assertSavedBytes(file, bytes), /differ/);
    fs.writeFileSync(file, Buffer.alloc(bytes.length + 1)); await assert.rejects(assertSavedBytes(file, bytes), /exceeded/);
    fs.writeFileSync(file, 'short'); await assert.rejects(assertSavedBytes(file, bytes, 5), /did not stabilize/);
    await assert.rejects(assertSavedBytes(path.join(root, 'missing'), bytes, 5), /did not stabilize/);
    await assert.rejects(assertSavedBytes(root, bytes), /regular file/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('native dialog script is exact owned modern Save profile, fresh contained filename and one bounded invocation', () => {
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  assert.match(script, /CreationDate.ToUniversalTime\(\).Ticks.ToString\(\) -cne \$c.start/);
  assert.match(script, /\[OwnedSave\]::GetWindow\(\$dialog,4\)/);
  assert.match(script, /\[OwnedSave\]::Pid\(\$cursor\) -ne \$c.pid/);
  assert.match(script, /GetForegroundWindow\(\) -ne \$dialog/);
  assert.match(script, /AutomationId -ceq 'FileNameControlHost'/); assert.match(script, /ClassName -ceq 'AppControlHost'/);
  assert.match(script, /ClassName -ceq 'DUIViewWndClassName'/); assert.match(script, /AutomationId -ceq '1001'/);
  assert.match(script, /\[OwnedSave\]::GetDlgItem\(\$dialog,1\)/); assert.match(script, /AutomationId -cne '1'/);
  assert.match(script, /Current.Value -cne \[IO.Path\]::GetFileName\(\$c.destination\)/);
  assert.match(script, /\[IO.Path\]::GetDirectoryName\(\$file\) -cne \$dir/); assert.match(script, /ReparsePoint/);
  assert(script.includes("$dir -notmatch '^[A-Za-z]:\\\\'"));
  assert.equal(script.match(/\$invoke.Invoke\(\)/g).length, 1);
  assert.match(script, /Assert-Dialog \$dialog; Assert-BoundControls; Assert-Destination;\n\$invoke.Invoke/);
  assert.match(script, /Current.Value -cne \$c.destination/); assert.match(script, /ACTION_COMPLETE/);
  assert.doesNotMatch(script, /SendKeys|SendMessage|SetForegroundWindow|RootElement|\.Current.Name/);
  assert(['powershell.exe', ...nativeDialogCommand(script)].join(' ').length + 1 < 32767);
  assert.throws(() => nativeDialogCommand('x'.repeat(13000)), /command-line limit/);
});

test('Windows PowerShell parser validates the actual generated native helper without executing it', { skip: process.platform !== 'win32' }, () => {
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  const observer = fs.readFileSync(new URL('../../scripts/installed-native-dialog-observation.ps1', import.meta.url), 'utf8');
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '$source=[Console]::In.ReadToEnd(); $tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors); if ($errors.Count) { throw "Native helper parse failed" }; Write-Output "PARSED"'],
    { input: script + '\n' + observer + '\n' + fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8'), encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert.equal(output.trim(), 'PARSED');
});

test('Windows read-only observer redacts unsafe primitives and returns no evidence after ownership rejection', { skip: process.platform !== 'win32' }, () => {
  const observer = fs.readFileSync(new URL('../../scripts/installed-native-dialog-observation.ps1', import.meta.url), 'utf8');
  const script = `Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes;\n${observer}\n` +
    "$result=Get-OwnedDialogObservation -Element $null -OwnedPid 1 -Guard { throw 'synthetic ownership rejected' }; " +
    "@{observation=$result;safe=(ConvertTo-SafeNativeToken 'FileNameControlHost');redacted=(ConvertTo-SafeNativeToken 'C:\\synthetic-private')} | ConvertTo-Json -Depth 8 -Compress";
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '-'],
    { input: script, encoding: 'utf8', timeout: 15000, windowsHide: true });
  const value = JSON.parse(output.trim());
  validateHostObservation(value.observation);
  assert.equal(value.observation.status, 'unavailable'); assert.deepEqual(value.observation.snapshots, []);
  assert.equal(value.observation.phase, 'guard-before'); assert.equal(value.observation.reason, 'exception');
  assert.equal(value.observation.exception_type, 'runtime');
  assert.equal(value.safe, 'FileNameControlHost'); assert.equal(value.redacted, '<redacted>');
});

test('cancel observation rejects downloads and preserves transport errors', async () => {
  let clicked = false;
  await noDownloadDuring({ waitForEvent: async (name, options) => {
    assert.equal(name, 'download'); assert.equal(options.timeout, 1000); throw Object.assign(new Error('none'), { name: 'TimeoutError' });
  } }, () => { clicked = true; }); assert.equal(clicked, true);
  await assert.rejects(noDownloadDuring({ waitForEvent: async () => ({}) }, () => {}), /Cancellation initiated/);
  const failure = new Error('disconnected');
  await assert.rejects(noDownloadDuring({ waitForEvent: async () => { throw failure; } }, () => {}), error => error === failure);
});

test('cleanup preserves the primary failure while attempting detach, owned-process verification and report writing', async () => {
  const primary = new Error('preview failed'), calls = [], report = { passed: false, cleanup: { errors: [] } };
  await assert.rejects(finish(report, primary, {
    disconnect: () => { calls.push('disconnect'); throw new Error('detach failed'); },
    alive: () => { calls.push('alive'); throw new Error('app check failed'); },
    write: () => { calls.push('write'); throw new Error('write failed'); },
  }), error => error === primary);
  assert.deepEqual(calls, ['disconnect', 'alive', 'write']); assert.deepEqual(report.cleanup.errors, ['disconnect', 'owned_app_alive']);
});

test('cleanup errors fail an otherwise successful run; unestablished ownership is never reported verified', async () => {
  const report = { passed: true, cleanup: { errors: [] } };
  const failure = new Error('detach failed'); let wrote = false, checked = false;
  await assert.rejects(finish(report, undefined, { disconnect: () => { throw failure; }, alive: () => { checked = true; }, write: () => { wrote = true; } }), error => error === failure);
  assert(checked && wrote); assert.equal(report.passed, false);
  await finish(report, undefined, { disconnect: () => false, alive: () => false, write() {} });
  assert.equal(report.cleanup.disconnect, false); assert.equal(report.cleanup.owned_app_alive, false);
});

test('bounded setup and cleanup cannot wait forever', async () => {
  await assert.rejects(bounded(new Promise(() => {}), 'held operation', 5), /Timed out: held operation/);
});

test('installed helper uses actual shipped disclosure, cached response bytes and CDP attach only', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-diagnostic-acceptance.cjs', import.meta.url), 'utf8');
  const tools = fs.readFileSync(new URL('../desk-tools.js', import.meta.url), 'utf8');
  const product = fs.readFileSync(new URL('../task-diagnostic-export.js', import.meta.url), 'utf8');
  assert.match(tools, /<details><summary>诊断详情与安全报告<\/summary>/);
  assert.match(source, /getByText\('诊断详情与安全报告', \{ exact: true \}\)\.click\(\)/);
  assert.match(source, /noDefaults: true/);
  assert.match(source, /chromium\.connectOverCDP\(`http:\/\/127\.0\.0\.1:\$\{config.debugPort\}`/);
  assert.match(source, /assert\.deepEqual\(verifyOwned\(config\), binding/);
  assert.match(source, /const bytes = await bounded\(response.body\(\)/);
  assert.match(source, /actual cached|exact cached|cached preview bytes/);
  assert.match(product, /new Blob\(\[bytes\]/);
  assert.doesNotMatch(source, /\.launch(?:Server|PersistentContext)?\s*\(|\.newContext\s*\(|\.newPage\s*\(|\.fulfill\s*\(|download\.path\s*\(|context\.close\s*\(|page\.close\s*\(|send\(['"]Browser.close/);
  assert.match(source, /page.route\(url => !ownedRequest\(url, config.origin\)/);
  assert.match(source, /route.abort\('blockedbyclient'\)/); assert.doesNotMatch(source, /route.continue|route.fetch/);
  assert.match(source, /--startup-only/); assert.match(source, /previous-startup\.png/); assert.match(source, /installed-current-cancel-focus\.png/);
  assert.match(source, /当前运行版本：\$\{expectedVersion\}/);
  assert.doesNotMatch(source, /0\.2\.1[56]/);
});
