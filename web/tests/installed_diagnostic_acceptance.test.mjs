import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import acceptance from '../../scripts/installed-diagnostic-acceptance.cjs';
import observationHelpers from '../../scripts/installed-download-observation.cjs';
const { fileObservation, downloadObservation, attachDownloadObservation } = observationHelpers;

const { parseArgs, readInstalledJSON, verifyOwned, assertSyntheticTask, selectOwnedPage, ownedRequest, validateHostFailure, validateControlFailure, validateHostObservation, validateWin32Observation, validateNativeCapture, validateForegroundEvidence, nativeDialogScript, nativeDialogCommand, withNativeHelper, assertSavedBytes, noDownloadDuring, finish, bounded } = acceptance;
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

function nativeBootstrap() {
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' },
    'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  return script.slice(script.indexOf('Add-Type -AssemblyName UIAutomationClient;'),
    script.indexOf(". (Join-Path (Split-Path $c.observer) 'installed-native-dialog-guards.ps1');"));
}

test('standard proxies initialize exactly once through a managed frame before readiness or discovery', () => {
  for (const observeOnly of [false, true]) {
    const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' },
      'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md', observeOnly);
    assert.match(script, /MethodImpl\(System.Runtime.CompilerServices.MethodImplOptions.NoInlining\)/);
    assert.match(script, /var providers=new System.Windows.Automation.ClientSideProviderDescription\[0\];/);
    assert.match(script, /RegisterClientSideProviders\(providers\);\n  GC.KeepAlive\(providers\);/);
    assert.equal(script.match(/RegisterClientSideProviders\(/g).length, 1);
    assert.equal(script.match(/\[OwnedSave\]::InitializeAutomation\(\)/g).length, 1);
    const initialized = script.indexOf('[OwnedSave]::InitializeAutomation()');
    assert(initialized < script.indexOf("Stage 'ownership'"));
    assert(initialized < script.indexOf("WriteLine('READY')"));
    assert(initialized < script.indexOf('[Windows.Automation.AutomationElement]::FromHandle'));
    assert.match(script, /ReferencedAssemblies @\(\[Windows.Automation.AutomationElement\].Assembly.Location,\[Windows.Automation.AutomationIdentifier\].Assembly.Location\)/);
    assert.doesNotMatch(nativeBootstrap(), /catch|RegisterClientSideProviderAssembly|LoadFrom|LoadFile|GetType\(|Invoke\(/);
    nativeDialogCommand(script);
  }
});

test('proxy initialization failure is retained before readiness and never clicks Save', async () => {
  const child = fakeChild(); let actions = 0;
  const result = withNativeHelper(child, () => { actions++; });
  child.line('PHASE:uia-initialization'); child.end(1);
  await assert.rejects(result, error => error.native_stage === 'uia-initialization' && error.message === 'Owned native Save helper failed');
  assert.equal(actions, 0); assert.deepEqual(child.writes, []);
});

test('Windows actual initializer propagates registration failure without retry or readiness', { skip: process.platform !== 'win32' }, () => {
  const bootstrap = nativeBootstrap();
  const method = bootstrap.match(/ \[System.Runtime.CompilerServices.MethodImpl[^]*?\n \}/)[0];
  const script = `$ErrorActionPreference='Stop'; Add-Type @'
using System;
namespace System.Windows.Automation {
 public struct ClientSideProviderDescription { }
 public static class ClientSettings {
  public static int Calls; public static readonly Exception Failure=new InvalidOperationException("synthetic initialization failure");
  public static void RegisterClientSideProviders(ClientSideProviderDescription[] providers) {
   Calls++; if (providers == null || providers.Length != 0) throw new Exception("wrong registration"); throw Failure;
  }
 }
}
public static class OwnedSave { ${method} }
'@;
$ready=$false; $same=$false;
try { [OwnedSave]::InitializeAutomation(); $ready=$true } catch {
 $errorObject=$_.Exception;
 for ($i=0; $i -lt 4 -and $errorObject; $i++) {
  if ([Object]::ReferenceEquals($errorObject,[Windows.Automation.ClientSettings]::Failure)) { $same=$true; break }
  $errorObject=$errorObject.InnerException;
 }
}
@{calls=[Windows.Automation.ClientSettings]::Calls;ready=$ready;original=$same} | ConvertTo-Json -Compress`;
  const output = execFileSync('powershell.exe', nativeDialogCommand(script), { encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert.deepEqual(JSON.parse(output.trim()), { calls: 1, ready: false, original: true });
});

test('Windows actual bootstrap exposes typed Value and Invoke patterns on owned synthetic WinForms controls', { skip: process.platform !== 'win32' }, () => {
  const script = `$ErrorActionPreference='Stop';\n${nativeBootstrap()}
Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;
Add-Type -ReferencedAssemblies @([Windows.Forms.Form].Assembly.Location,[Drawing.Point].Assembly.Location) -TypeDefinition @'
using System; using System.Threading; using System.Windows.Forms;
public static class SyntheticProxyControls {
 static Thread worker; static Form form; static readonly ManualResetEvent ready=new ManualResetEvent(false);
 static Exception failure; public static IntPtr Edit, Button;
 public static void Start() {
  worker=new Thread(() => {
   try {
    using (form=new Form()) using (var edit=new TextBox()) using (var button=new Button()) {
     edit.Name="SyntheticEdit"; edit.Text="synthetic proxy fixture"; button.Name="SyntheticButton";
     form.Controls.Add(edit); form.Controls.Add(button);
     var root=form.Handle; Edit=edit.Handle; Button=button.Handle;
     ready.Set(); Application.Run();
    }
   } catch (Exception error) { failure=error; ready.Set(); }
  });
  worker.IsBackground=true; worker.SetApartmentState(ApartmentState.STA); worker.Start();
  if (!ready.WaitOne(5000)) throw new TimeoutException("synthetic controls not ready");
  if (failure != null) throw failure;
 }
 public static void Stop() {
  if (worker == null || !worker.IsAlive) return;
  form.BeginInvoke(new Action(() => Application.ExitThread()));
  if (!worker.Join(5000)) throw new TimeoutException("synthetic controls did not close");
 }
}
'@;
$failure=$null;
try {
 [SyntheticProxyControls]::Start();
 $edit=[Windows.Automation.AutomationElement]::FromHandle([SyntheticProxyControls]::Edit);
 $button=[Windows.Automation.AutomationElement]::FromHandle([SyntheticProxyControls]::Button);
 $ec=$edit.get_Current(); $bc=$button.get_Current();
 $value=$edit.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern);
 $invoke=$button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern);
 $client=[Windows.Automation.AutomationElement].Assembly.GetName();
 $providers=@([AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -ceq 'UIAutomationClientsideProviders' });
 $assemblyMatches=$providers.Count -eq 1;
 if ($assemblyMatches) {
  $actual=$providers[0].GetName();
  $assemblyMatches=$actual.Version -eq $client.Version -and $actual.CultureInfo.Name -ceq $client.CultureInfo.Name -and
   [Convert]::ToBase64String($actual.GetPublicKeyToken()) -ceq [Convert]::ToBase64String($client.GetPublicKeyToken());
 }
 @{edit_type=$ec.ControlType.Id;button_type=$bc.ControlType.Id;value_pattern=($value -is [Windows.Automation.ValuePattern]);
   invoke_pattern=($invoke -is [Windows.Automation.InvokePattern]);writable=(!$value.Current.IsReadOnly);
   synthetic_value=($value.Current.Value -ceq 'synthetic proxy fixture');assembly_matches=$assemblyMatches;
   owned=($ec.ProcessId -eq $PID -and $bc.ProcessId -eq $PID);
   exact_handles=([IntPtr]$ec.NativeWindowHandle -eq [SyntheticProxyControls]::Edit -and [IntPtr]$bc.NativeWindowHandle -eq [SyntheticProxyControls]::Button)} | ConvertTo-Json -Compress;
} catch { $failure=$_; throw } finally {
 try { [SyntheticProxyControls]::Stop() } catch { if (!$failure) { throw } }
}`;
  const output = execFileSync('powershell.exe', nativeDialogCommand(script), { encoding: 'utf8', timeout: 15000, windowsHide: true });
  const lines = output.trim().split(/\r?\n/);
  assert.equal(lines.shift(), 'PHASE:uia-initialization'); assert.equal(lines.length, 1);
  assert.deepEqual(JSON.parse(lines[0]), { edit_type: 50004, button_type: 50000, value_pattern: true,
    invoke_pattern: true, writable: true, synthetic_value: true, assembly_matches: true, owned: true, exact_handles: true });
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
  phase: 'complete', reason: 'complete', elapsed_ms: 260, exception_type: null, guard_failure: null });
const unavailableObservation = (phase = 'guard-before', exception_type = 'runtime') => ({ status: 'unavailable', snapshots: [],
  phase, reason: 'exception', elapsed_ms: 5, exception_type, guard_failure: ['guard-before', 'guard-after'].includes(phase) ? { reason: 'unclassified', facts: null } : null });
function emitHostFailure(child, details) {
  child.line('PHASE:filename-host'); child.line('SUBPHASE:' + details.subphase); child.line('HOSTFAIL:' + JSON.stringify(details));
}

const unavailableControls = () => ({ subphase: 'edit-initial-name', observation: { status: 'unavailable',
  phase: 'guard-after', reason: 'exception', exception_type: 'runtime', elapsed_ms: 5, edit: null, save: null } });

test('control failure facts stay bounded, preserve strict rejection and reject raw native properties', async () => {
  validateControlFailure(unavailableControls());
  for (const mutate of [value => { value.Value = 'PRIVATE'; }, value => { value.subphase = 'PRIVATE'; },
    value => { value.observation.elapsed_ms = 35001; }, value => { value.observation.exception_type = 'PRIVATE'; },
    value => { value.observation.edit = { Value: 'PRIVATE' }; }]) {
    const value = unavailableControls(); mutate(value); assert.throws(() => validateControlFailure(value));
  }
  for (const mode of ['valid', 'invalid', 'oversized', 'late-success', 'held']) {
    const child = fakeChild(); let actions = 0;
    const result = withNativeHelper(child, () => {
      actions++; child.line('PHASE:filename-edit');
      child.line('CONTROLFAIL:' + (mode === 'invalid' ? '{"Value":"PRIVATE"}' : mode === 'oversized' ? 'x'.repeat(8193) : JSON.stringify(unavailableControls())));
      if (mode === 'held') return new Promise(() => {});
      if (mode === 'late-success') child.line('{"native_dialog":true,"saved":true}');
      child.end(mode === 'late-success' ? 0 : 1);
    }, { action: 5 }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed'); assert.equal(error.native_stage, 'filename-edit');
      if (['invalid', 'oversized'].includes(mode)) {
        assert.equal(error.native_control_observation_unavailable, true); assert.equal(error.native_control_failure, undefined);
      } else assert.deepEqual(error.native_control_failure, unavailableControls());
      assert(!JSON.stringify(error).includes('PRIVATE')); return true;
    }); assert.equal(actions, 1);
  }
});

test('adjacent control validation keeps exact names, strict controls and action-time destination/readback guards', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-native-save-controls.ps1', import.meta.url), 'utf8');
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  assert.match(source, /\$expected -cin @\('learnnote-diagnostics.md','learnnote-diagnostics.json'\)/);
  assert.match(source, /\$Name -ceq \$expected -or \$Name -ceq \[IO.Path\]::GetFileNameWithoutExtension\(\$expected\)/);
  assert.match(source, /\$value.Current.IsReadOnly -or !\(Test-InitialNativeFilename \$value.Current.Value \$c.destination\)/);
  assert.doesNotMatch(source, /-like|-match|StartsWith|SetValue|\.Invoke\(|SendKeys|SendMessage|SetForeground|RootElement|GetWindowText/);
  assert.match(source, /ElapsedMilliseconds -ge 1000/); assert.match(source, /\$editFacts=\$null; \$saveFacts=\$null/);
  assert.match(source, /if \(\$facts.control_valid -eq \$false\) \{ throw \}/);
  assert.match(source, /GetRuntimeId\(\) -join ','\) -cne \$binding.runtime/);
  assert.match(source, /throw \$original/); assert.match(script, /installed-native-save-controls.ps1/);
  assert.match(script, /Assert-Dialog \$dialog; Assert-BoundControls; Assert-Destination;\n\$value.SetValue\(\$c.destination\)/);
  assert.match(script, /Current.Value -cne \$c.destination/);
  assert.match(script, /Assert-Dialog \$dialog; Assert-BoundControls; Assert-Destination;\n\$invoke.Invoke\(\)/);
  nativeDialogCommand(script);
  const originalValidation = text => {
    const canonical = text.replace(/\r\n/g, '\n'), start = canonical.indexOf("Stage 'filename-edit';");
    return canonical.slice(start, canonical.indexOf('} catch {', start))
      .replace(/^\$controlSubphase='[^']*';\n/gm, '').replace(" $controlSubphase='edit-control';", '')
      .replace('!(Test-InitialNativeFilename $value.Current.Value $c.destination)', '$value.Current.Value -cne [IO.Path]::GetFileName($c.destination)');
  };
  const expected = 'a97e8cacafb84f941c2f8071f480a2d6d3d3d8cceb2696e464ed7b5317514130';
  for (const text of [source.replace(/\r\n/g, '\n'), source.replace(/\r\n/g, '\n').replace(/\n/g, '\r\n')]) {
    assert.equal(createHash('sha256').update(originalValidation(text)).digest('hex'), expected);
    assert.notEqual(createHash('sha256').update(originalValidation(text.replaceAll("AutomationId -ceq '1001'", "AutomationId -ceq '1002'"))).digest('hex'), expected);
  }
});

test('Windows extracted control validation accepts only exact initial names and retains both targets through faults', { skip: process.platform !== 'win32' }, () => {
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File', path.resolve('scripts/tests/native-save-control-faults.ps1')],
    { encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert(!output.includes('PRIVATE')); const cases = JSON.parse(output.trim()); assert.equal(cases.length, 25);
  for (const row of cases) {
    const success = ['md-name', 'md-stem', 'json-name', 'json-stem'].includes(row.mode);
    assert.equal(row.passed, success, row.mode);
    if (success) { assert.equal(row.metadata, null, row.mode); assert.equal(row.stage, 'save-button', row.mode); continue; }
    assert.equal(row.primary_preserved, true, row.mode);
    if (row.mode === 'format-fault') { assert.equal(row.metadata, null); continue; }
    validateControlFailure(row.metadata);
    const observation = row.metadata.observation;
    if (['edit-control', 'save-control', 'guard-before', 'guard-after', 'runtime-race', 'budget'].includes(row.mode)) {
      assert.equal(observation.status, 'unavailable', row.mode); assert.equal(observation.edit, null); assert.equal(observation.save, null);
      if (['edit-control', 'save-control'].includes(row.mode)) { assert.equal(row.original, true); assert.equal(row.save_patterns, 0); }
      if (row.mode === 'edit-control') assert.equal(row.value_reads, 0);
      if (row.mode === 'runtime-race') assert.equal(observation.reason, 'runtime-changed');
      if (row.mode === 'budget') assert.equal(observation.reason, 'budget');
    } else {
      assert.equal(observation.status, 'complete', row.mode);
      if (row.mode.startsWith('edit-')) assert.equal(observation.save.pattern_available, true, row.mode);
      if (row.mode === 'readonly') assert.equal(observation.edit.read_only, true);
      if (['wrong-stem', 'wrong-extension', 'wrong-case', 'path', 'empty'].includes(row.mode)) {
        assert.equal(observation.edit.expected_basename, false, row.mode); assert.equal(observation.edit.expected_stem, false, row.mode);
      }
      if (row.mode === 'value-pattern') { assert.equal(row.original, true); assert.equal(observation.edit.pattern_available, false); assert.equal(observation.save.pattern_available, true); }
      if (row.mode === 'invoke-pattern') { assert.equal(row.original, true); assert.equal(observation.save.pattern_available, false); }
    }
  }
});

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
    reason: 'budget', elapsed_ms: 1000, exception_type: null, guard_failure: null });
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
  assert.deepEqual(cases.getter_probe, { member_null: true, member_caught: false, explicit_caught: true, reads: 2, throws: 2 });
  const getterFaults = ['property', 'process-id', 'control-type', 'type-id', 'class-name', 'automation-id'];
  const invalidProperties = ['null-current', 'invalid-process', 'missing-type', 'invalid-type-id', 'null-class', 'null-id'];
  for (const { mode, observation, reads } of cases.results) {
    assert.doesNotThrow(() => validateHostObservation(observation), `${mode}: valid bounded observation`);
    assert.equal(reads.throws, getterFaults.includes(mode) ? 1 : 0, `${mode}: actual CLR getter throw count`);
    for (const field of ['hidden', 'pruned_class', 'pruned_id', 'forbidden']) assert.equal(reads[field], 0, `${mode}: ${field}`);
    if (mode === 'success') {
      assert.equal(observation.status, 'complete', mode); assert.equal(observation.reason, 'complete', mode);
      assert.equal(observation.snapshots.length, 2, mode);
      for (const field of ['root', 'host', 'pruned']) assert.equal(reads[field], 2, `${mode}: one Current read per node per snapshot`);
      for (const snapshot of observation.snapshots) {
        assert.equal(snapshot.nodes.length, 3, mode); assert.equal(snapshot.foreign_nodes, 0, mode);
        assert(snapshot.nodes[2].pruned, mode); assert.equal(snapshot.nodes[2].cls, '', mode); assert.equal(snapshot.nodes[2].id, '', mode);
      }
    } else if (mode === 'budget') {
      assert.equal(observation.reason, 'budget', mode); assert.equal(observation.exception_type, null, mode);
      assert.equal(observation.status, 'partial', mode); assert.equal(observation.phase, 'guard-after', mode);
      assert(observation.elapsed_ms >= 1000, mode);
    } else {
      assert.equal(observation.reason, 'exception', `${mode}: reason`);
      const propertyFailure = getterFaults.includes(mode) || invalidProperties.includes(mode);
      const expected = propertyFailure ? 'node-properties' : mode === 'guard-before-late' ? 'guard-before' : mode;
      assert.equal(observation.phase, expected, `${mode}: phase`);
      assert.equal(observation.snapshots.length, mode === 'guard-before-late' ? 1 : 0, `${mode}: retained snapshots`);
      assert.equal(observation.status, mode === 'guard-before-late' ? 'partial' : 'unavailable', `${mode}: status`);
      if (propertyFailure) assert.equal(reads.root, 1, `${mode}: one Current read before rejection`);
    }
  }
  assert.equal(cases.results.length, 19);
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
  assert.match(observer, /\$processId -ne \$OwnedPid/); assert.equal(observer.match(/\[void\]\(& \$Guard\)/g).length, 2);
  assert.equal(observer.match(/\$node\.get_Current\(\)/g).length, 1);
  for (const getter of ['ProcessId', 'ControlType', 'ClassName', 'AutomationId']) assert(observer.includes(`$current.get_${getter}()`));
  assert.match(observer, /\$type\.get_Id\(\)/); assert.match(observer, /\$null -eq \$current/);
  assert.match(observer, /\$processId -isnot \[int\]/); assert.match(observer, /\$typeId -isnot \[int\]/);
  assert.match(observer, /\$className -isnot \[string\] -or \$automationId -isnot \[string\]/);
  assert.doesNotMatch(observer, /\$node\.Current|\$current\.(?:ProcessId|ControlType|ClassName|AutomationId)\b/);
  for (const type of ['List', 'ListItem', 'Tree', 'TreeItem', 'DataGrid', 'DataItem', 'Document']) assert(observer.includes(`ControlType]::${type}`));
  assert.doesNotMatch(observer, /\.Current\.(?:Name|Value)|get_(?:Name|Value)\(|SetValue|\.Invoke\(|RootElement|GetWindowText|\.screenshot\(|CopyFromScreen|GetForegroundWindow/);
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  const branch = script.slice(script.indexOf('} catch {\n $original=$_;'), script.indexOf(". (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');"));
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
  assert(source.indexOf("$phase='guard-before'; [void](& $Guard $GuardContext)") < source.indexOf('PrintWindow($Dialog,$dc,2)'));
  assert(source.indexOf("$phase='guard-after'; [void](& $Guard $GuardContext)") > source.indexOf('PrintWindow($Dialog,$dc,2)'));
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

test('Windows repeated captures reuse the exact loaded pixel type without invoking native methods', { skip: process.platform !== 'win32' }, () => {
  const capture = fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8');
  const definition = capture.match(/Add-Type @'\r?\n([\s\S]+?)\r?\n'@/)[1];
  const script = "$ErrorActionPreference='Stop'; $source=[Console]::In.ReadToEnd(); " +
    'function Load-PixelType([string]$text) { Add-Type -TypeDefinition $text }; ' +
    'Load-PixelType $source; $first=[OwnedDialogPixels]; $assembly=$first.Assembly; ' +
    'Load-PixelType $source; $second=[OwnedDialogPixels]; ' +
    'if (![Object]::ReferenceEquals($first,$second) -or ![Object]::ReferenceEquals($assembly,$second.Assembly)) { throw "Pixel type was not reused" }; ' +
    'if (!$second.GetMethod("PrintWindow") -or !$second.GetNestedType("RECT")) { throw "Pixel type contract missing" }; Write-Output "REUSED"';
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
    { input: definition, encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert.equal(output.trim(), 'REUSED');
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

test('expected-file diagnostics distinguish missing, short, changing, busy and access denied without retaining paths', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'installed-file-evidence-')), file = path.join(root, 'private-canary-name');
  const bytes = Buffer.from('synthetic reviewed bytes');
  try {
    for (const [prepare, state] of [[() => {}, 'missing'], [() => fs.writeFileSync(file, 'short'), 'regular']]) {
      prepare();
      await assert.rejects(assertSavedBytes(file, bytes, 5), error => {
        const evidence = error.native_file_observation;
        assert.equal(evidence.outcome, 'byte_check_failed'); assert.equal(evidence.last.state, state);
        assert.equal(evidence.last.length, state === 'missing' ? 'unknown' : 'short');
        assert.equal(evidence.expected_bytes, bytes.length); assert(!JSON.stringify(evidence).includes(file)); return true;
      });
    }
    fs.writeFileSync(file, bytes);
    const original = fs.lstatSync;
    try {
      for (const code of ['EBUSY', 'EACCES', 'EIO']) {
        const primary = Object.assign(new Error('private error-message canary'), { code });
        fs.lstatSync = () => { throw primary; };
        await assert.rejects(assertSavedBytes(file, bytes, 5), error => {
          if (code === 'EIO') assert.equal(error, primary);
          assert.equal(error.native_file_observation.last.state, { EBUSY: 'busy', EACCES: 'access_denied', EIO: 'other_io_error' }[code]);
          assert(!JSON.stringify(error.native_file_observation).includes('canary')); return true;
        });
      }
      const stat = original(file); let tick = 0;
      fs.lstatSync = () => ({ ...stat, mtimeMs: ++tick, isFile: () => true, isSymbolicLink: () => false });
      await assert.rejects(assertSavedBytes(file, bytes, 120), error => {
        assert.equal(error.native_file_observation.last.length, 'exact');
        assert.equal(error.native_file_observation.last.stable_with_previous, false); return true;
      });
    } finally { fs.lstatSync = original; }
    const evidence = fileObservation(bytes.length);
    await assertSavedBytes(file, bytes, 10000, evidence);
    assert.equal(evidence.report.outcome, 'verified'); assert.equal(evidence.report.last.stable_with_previous, true);
    fs.writeFileSync(file, Buffer.alloc(bytes.length));
    await assert.rejects(assertSavedBytes(file, bytes), error => {
      assert.match(error.message, /differ/); assert.equal(error.native_file_observation.last.length, 'exact'); return true;
    });
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('file observations are bounded, fixed-category and safe when diagnostic stat access fails', () => {
  const observation = fileObservation(10);
  for (let i = 0; i < 3000; ++i) observation.stat({ size: i % 2 ? 1e12 : 1, mtimeMs: i, isFile: () => true, isSymbolicLink: () => false });
  assert.equal(observation.report.samples, 1000); assert.equal(observation.report.transitions.length, 12);
  assert.equal(observation.report.counts_capped, true); assert.equal(observation.report.transitions_dropped, 1000); assert.equal(observation.report.last.bytes, 262145);
  assert.equal(observation.report.last.bytes_capped, true);
  observation.stat({ get size() { throw new Error('private-canary'); } });
  assert.equal(observation.report.unavailable, true);
  observation.error({ code: 'constructor', message: 'private-contents-canary' });
  assert.equal(observation.report.last.state, 'other_io_error');
  assert.doesNotMatch(JSON.stringify(observation.report), /canary|mtime|path|contents/);
});

test('passive download evidence correlates only owned Blob GUIDs, both formats and fixed terminal outcomes', () => {
  const observation = downloadObservation('http://127.0.0.1:8765');
  for (const [format, state] of [['md', 'completed'], ['json', 'canceled']]) {
    observation.active(format);
    observation.begin({ guid: `private-${format}`, url: 'blob:http://127.0.0.1:8765/private-url', suggestedFilename: `learnnote-diagnostics.${format}` });
    observation.progress({ guid: `private-${format}`, state: 'inProgress', receivedBytes: 3, totalBytes: 20 });
    observation.progress({ guid: `private-${format}`, state, receivedBytes: 20, totalBytes: 20 });
  }
  assert.deepEqual(observation.report.downloads.map(item => [item.format, item.expected_name_matches, item.state]), [['md', true, 'completed'], ['json', true, 'canceled']]);
  observation.begin({ guid: 'foreign', url: 'blob:https://private.example/token', suggestedFilename: 'private-name' });
  observation.progress({ guid: 'foreign', state: 'completed', receivedBytes: 10, totalBytes: 10 });
  assert.equal(observation.report.ignored_events, 2);
  assert.doesNotMatch(JSON.stringify(observation.report), /private|blob:|127\.0\.0\.1|guid|suggestedFilename/);
  observation.active('cancel');
  observation.begin({ guid: 'cancel-guid', url: 'blob:http://127.0.0.1:8765/private-url', suggestedFilename: 'private-name' });
  observation.progress({ guid: 'cancel-guid', state: 'canceled', receivedBytes: 0, totalBytes: -1 });
  assert.equal(observation.report.downloads[2].format, 'cancel'); assert.equal(observation.report.downloads[2].expected_name_matches, null);
  assert.equal(observation.report.downloads[2].state, 'canceled'); assert.equal(observation.report.downloads[2].total_bytes, null);
  observation.close(); const closed = JSON.stringify(observation.report);
  observation.begin({}); observation.progress({}); assert.equal(JSON.stringify(observation.report), closed);
});

test('download metadata caps bytes, records and counts and rejects malformed/unbound events', () => {
  const observation = downloadObservation('http://127.0.0.1:8765'); observation.active('md');
  for (let i = 0; i < 2000; ++i) observation.begin({ guid: String(i), url: 'blob:http://127.0.0.1:8765/private', suggestedFilename: 'wrong-private-name' });
  assert.equal(observation.report.downloads.length, 4); assert.equal(observation.report.begins, 1000); assert.equal(observation.report.dropped_downloads, 1000);
  observation.progress({ guid: '0', state: 'completed', receivedBytes: 1e12, totalBytes: 1e12 });
  assert.equal(observation.report.downloads[0].received_bytes, 262145); assert.equal(observation.report.downloads[0].bytes_capped, true);
  for (const event of [null, {}, { guid: '0', state: 'private-status', receivedBytes: 1, totalBytes: 1 }, { guid: '0', state: 'completed', receivedBytes: NaN, totalBytes: -1 }]) observation.progress(event);
  observation.begin({ guid: '0', url: 'blob:http://127.0.0.1:8765/private' });
  observation.begin({ guid: 'oversized', url: 'x'.repeat(4097) });
  assert(observation.report.invalid_events >= 4); assert.equal(observation.report.downloads[0].state, 'completed');
  assert.equal(observation.report.downloads[0].expected_name_matches, false);
  assert.doesNotMatch(JSON.stringify(observation.report), /private|NaN/);
});

test('passive attachment sends only Page.enable and retains outcomes when detach or setup fails', async () => {
  const session = new EventEmitter(), commands = []; let detached = 0;
  session.send = async command => { commands.push(command); }; session.detach = async () => { detached++; };
  const page = { context: () => ({ newCDPSession: target => { assert.equal(target, page); return session; } }) };
  const observation = await attachDownloadObservation(page, 'http://127.0.0.1:8765', bounded);
  assert.deepEqual(commands, ['Page.enable']); observation.active('md');
  session.emit('Page.downloadWillBegin', { guid: 'own', url: 'blob:http://127.0.0.1:8765/id', suggestedFilename: 'learnnote-diagnostics.md' });
  session.emit('Page.downloadProgress', { guid: 'own', state: 'canceled', receivedBytes: 0, totalBytes: 20 });
  await observation.close(); assert.equal(detached, 1); assert.equal(session.listenerCount('Page.downloadProgress'), 0);
  assert.equal(observation.report.status, 'events_observed'); assert.equal(observation.report.downloads[0].state, 'canceled');
  session.detach = async () => { throw new Error('private detach'); };
  const empty = await attachDownloadObservation(page, 'http://127.0.0.1:8765', bounded); await empty.close();
  assert.equal(empty.report.status, 'no_events_observed'); assert.equal(empty.report.detach_failed, true);
  session.send = async () => { throw new Error('private enable'); };
  const unavailable = await attachDownloadObservation(page, 'http://127.0.0.1:8765', bounded); await unavailable.close();
  assert.equal(unavailable.report.status, 'unavailable'); assert.equal(unavailable.report.setup_failure, 'enable');
  const missing = await attachDownloadObservation({ context() { throw new Error('private attach'); } }, 'http://127.0.0.1:8765', bounded);
  await missing.close(); assert.equal(missing.report.setup_failure, 'attach');
  assert.doesNotMatch(JSON.stringify([unavailable.report, missing.report]), /private/);
});

test('late passive attachment is detached after its bounded setup expires', async () => {
  const session = new EventEmitter(); let resolve, detached = 0;
  session.detach = async () => { detached++; };
  const page = { context: () => ({ newCDPSession: () => new Promise(value => { resolve = value; }) }) };
  const observation = await attachDownloadObservation(page, 'http://127.0.0.1:8765', (promise, label) => bounded(promise, label, 5));
  assert.equal(observation.report.status, 'unavailable'); resolve(session);
  await new Promise(done => setTimeout(done, 10)); assert.equal(detached, 1); await observation.close();
});

test('actual native attempt retains the original failure and one expected-file sample before byte checking', async () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-diagnostic-acceptance.cjs', import.meta.url), 'utf8');
  const start = source.indexOf('        const observation = fileObservation(expected.length);');
  const end = source.indexOf('        assert.equal(report.diagnostic_requests, gets,', start);
  const run = new (Object.getPrototypeOf(async function() {}).constructor)('fileObservation', 'report', 'downloadObserver', 'format', 'expected', 'nativeDialog', 'config', 'binding', 'nativeDirectory', 'destination', 'save', 'assert', 'assertSavedBytes', source.slice(start, end));
  const primary = new Error('native primary'); const report = { native_save_attempts: [], downloads: [] };
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'native-attempt-evidence-'));
  try {
    await assert.rejects(run(fileObservation, report, { active() {} }, 'md', Buffer.from('reviewed'), async () => { throw primary; }, {}, {}, root, path.join(root, 'missing'), {}, assert, assertSavedBytes), error => error === primary);
    assert.equal(report.native_save_attempts.length, 1); const attempt = report.native_save_attempts[0];
    assert.equal(attempt.native_dialog_completed, false); assert.equal(attempt.file.outcome, 'native_step_failed'); assert.equal(attempt.file.last.state, 'missing');
    assert.equal(report.downloads.length, 0);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
  const observer = fs.readFileSync(new URL('../../scripts/installed-download-observation.cjs', import.meta.url), 'utf8');
  assert.doesNotMatch(observer, /setDownloadBehavior|Browser\.cancelDownload|saveAs|revokeObjectURL|readFile|readdir/);
  assert.match(source, /assertSavedBytes\(destination, expected, 10000, observation\)/);
  assert(source.indexOf('await downloadObserver.close()') < source.indexOf('await finish(report, failure'));
});

test('actual final cleanup still writes the original failure if passive-observer cleanup throws', async () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-diagnostic-acceptance.cjs', import.meta.url), 'utf8');
  const start = source.indexOf('    try { if (downloadObserver) await downloadObserver.close(); }');
  const end = source.indexOf('\n  }\n}', start);
  const run = new (Object.getPrototypeOf(async function() {}).constructor)('downloadObserver', 'report', 'failure', 'finish', 'browser', 'binding', 'verifyOwned', 'config', 'fs', 'path', source.slice(start, end));
  const primary = new Error('original primary'); const report = { passed: false, cleanup: { errors: [] } }; let wrote = false;
  await assert.rejects(run({ close() { throw new Error('observer secondary'); } }, report, primary, finish, undefined, undefined, () => {}, {}, { writeFileSync() { wrote = true; } }, { join() { return 'owned'; } }), error => error === primary);
  assert(wrote); assert.equal(report.download_observation_cleanup_failed, true);
  assert.equal(report.cleanup.disconnect, false); assert.equal(report.cleanup.owned_app_alive, false);
});

test('native dialog script is exact owned modern Save profile, fresh contained filename and one bounded invocation', () => {
  let script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  script = script.replace(". (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');", fs.readFileSync(new URL('../../scripts/installed-native-save-controls.ps1', import.meta.url), 'utf8'));
  const guards = fs.readFileSync(new URL('../../scripts/installed-native-dialog-guards.ps1', import.meta.url), 'utf8');
  assert.match(script, /installed-native-dialog-guards\.ps1/);
  assert.match(guards, /CreationDate.ToUniversalTime\(\).Ticks.ToString\(\) -cne \$c.start/);
  assert.match(guards, /\[OwnedSave\]::GetWindow\(\$dialog,4\)/);
  assert.match(guards, /\[OwnedSave\]::Pid\(\$cursor\) -ne \$c.pid/);
  assert.match(guards, /GetForegroundWindow\(\) -ne \$dialog/);
  assert.match(script, /AutomationId -ceq 'FileNameControlHost'/); assert.match(script, /ClassName -ceq 'AppControlHost'/);
  assert.match(script, /ClassName -ceq 'DUIViewWndClassName'/); assert.match(script, /AutomationId -ceq '1001'/);
  assert.match(script, /\[OwnedSave\]::GetDlgItem\(\$dialog,1\)/); assert.match(script, /AutomationId -cne '1'/);
  assert.match(script, /Test-InitialNativeFilename \$value.Current.Value \$c.destination/);
  assert.match(script, /\[IO.Path\]::GetDirectoryName\(\$file\) -cne \$dir/); assert.match(script, /ReparsePoint/);
  assert(script.includes("$dir -notmatch '^[A-Za-z]:\\\\'"));
  assert.equal(script.match(/\$invoke.Invoke\(\)/g).length, 1);
  assert.match(script, /Assert-Dialog \$dialog; Assert-BoundControls; Assert-Destination;\n\$invoke.Invoke/);
  assert.match(script, /Current.Value -cne \$c.destination/); assert.match(script, /ACTION_COMPLETE/);
  assert.doesNotMatch(script, /SendKeys|SendMessage|SetForegroundWindow|RootElement|\.Current.Name/);
  nativeDialogCommand(nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md'));
  assert.throws(() => nativeDialogCommand('x'.repeat(13000)), /command-line limit/);
});

test('Windows PowerShell parser validates the actual generated native helper without executing it', { skip: process.platform !== 'win32' }, () => {
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\owned\local-native-exports-fresh', 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md');
  const observer = fs.readFileSync(new URL('../../scripts/installed-native-dialog-observation.ps1', import.meta.url), 'utf8');
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '$source=[Console]::In.ReadToEnd(); $tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors); if ($errors.Count) { throw "Native helper parse failed" }; Write-Output "PARSED"'],
    { input: script + '\n' + observer + '\n' + ['guards', 'win32'].map(name => fs.readFileSync(new URL(`../../scripts/installed-native-dialog-${name}.ps1`, import.meta.url), 'utf8')).join('\n') + '\n' + fs.readFileSync(new URL('../../scripts/installed-native-foreground-evidence.ps1', import.meta.url), 'utf8') + '\n' + fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8') + '\n' + fs.readFileSync(new URL('../../scripts/installed-native-save-controls.ps1', import.meta.url), 'utf8'), encoding: 'utf8', timeout: 15000, windowsHide: true });
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

const win32Observation = () => ({ status: 'complete', phase: 'complete', reason: 'complete', elapsed_ms: 5,
  exception_type: null, guard_failure: null, truncated: false, nodes: [
    { parent: -1, depth: 0, cls: '#32770', id: 0, pruned: false },
    { parent: 0, depth: 1, cls: 'ComboBox', id: 1148, pruned: false },
  ] });
const guardFacts = () => Object.fromEntries([
  ...['binding_matches', 'process_exists', 'process_name_matches', 'process_start_matches', 'root_exists', 'root_visible',
    'root_pid_matches', 'root_ownerless', 'root_class_matches', 'root_title_matches', 'dialog_exists', 'dialog_visible',
    'dialog_pid_matches', 'dialog_class_matches', 'visible_set_matches'].map(key => [key, true]),
  ['foreground', 'dialog'], ['owner_chain', 'root'], ['visible_count', 2],
]);

test('guard reasons and identity facts reject arbitrary text, handles, fields and unbounded counts', () => {
  for (const reason of ['process-identity', 'root-identity', 'foreground', 'dialog-identity', 'owner-process', 'owner-root', 'popup-set', 'unclassified']) {
    const value = unavailableObservation(); value.guard_failure = { reason, facts: guardFacts() };
    validateHostObservation(value);
  }
  const mutations = [value => { value.guard_failure.reason = 'PRIVATE_ERROR'; },
    value => { value.guard_failure.Message = 'PRIVATE_ERROR'; }, value => { value.guard_failure.facts.foreground = 'HWND:123'; },
    value => { value.guard_failure.facts.owner_chain = 'PRIVATE_TITLE'; }, value => { value.guard_failure.facts.visible_count = 65; },
    value => { value.guard_failure.facts.process_start_matches = 'PRIVATE_DATE'; }, value => { value.guard_failure.facts.pid = 123; }];
  for (const mutate of mutations) {
    const value = unavailableObservation(); value.guard_failure = { reason: 'foreground', facts: guardFacts() };
    mutate(value); assert.throws(() => validateHostObservation(value));
  }
});

test('Win32 structure is bounded and cannot replace the original host rejection, including invalid metadata', async () => {
  for (const invalid of [false, true]) {
    const child = fakeChild(); let actions = 0;
    const result = withNativeHelper(child, () => {
      actions++; emitHostFailure(child, hostFailureDetails(0));
      child.line('HOSTDIAG:' + JSON.stringify(unavailableObservation()));
      child.line('WIN32DIAG:' + JSON.stringify(invalid ? { ...win32Observation(), title: 'PRIVATE_TITLE' } : win32Observation()));
      child.line('{"native_dialog":true,"saved":true}'); child.end(0);
    }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed'); assert.deepEqual(error.native_host_failure, hostFailureDetails(0));
      assert.deepEqual(error.native_host_observation, unavailableObservation());
      if (invalid) { assert.equal(error.native_win32_unavailable, true); assert.equal(error.native_win32_observation, undefined); }
      else assert.deepEqual(error.native_win32_observation, win32Observation());
      assert(!JSON.stringify(error).includes('PRIVATE')); return true;
    }); assert.equal(actions, 1);
  }
  for (const mutate of [value => { value.nodes[1].parent = 1; }, value => { value.nodes[1].depth = 9; },
    value => { value.nodes[0].pruned = true; }, value => { value.nodes[1].cls = 'C:\\PRIVATE'; },
    value => { value.nodes[1].id = 2147483648; }, value => { value.nodes[1].id = 1.5; },
    value => { value.nodes[1].text = 'PRIVATE'; }, value => { value.nodes = Array(65).fill(value.nodes[0]); },
    value => { value.status = 'unavailable'; }, value => { value.reason = 'budget'; },
    value => { value.guard_failure = { reason: 'foreground', facts: null }; }]) {
    const value = win32Observation(); mutate(value); assert.throws(() => validateWin32Observation(value));
  }
});

test('Win32 evidence uses independent exact proof, only owned child structure, and retains the primary error', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-native-dialog-win32.ps1', import.meta.url), 'utf8');
  assert.equal(source.match(/Assert-BoundDialog \$Binding/g).length, 2);
  assert(source.indexOf('Assert-BoundDialog $Binding') < source.indexOf('GetWindow($winHandle,5)'));
  for (const pattern of [/winNodes.Count -lt 64/, /winSeen.Count -lt 64/, /winEntry.depth -ge 8/, /ElapsedMilliseconds -lt 500/,
    /Pid\(\$winChild\) -ne \$Binding.config.pid/, /GetParent\(\$winChild\) -ne \$winHandle/, /winNodes.Clear\(\)/]) assert.match(source, pattern);
  assert.doesNotMatch(source, /GetWindowText|::Title|SendMessage|SendKeys|SetValue|\.Invoke\(|EnumWindows|EnumChildWindows|GetForegroundWindow|RootElement|GetDesktopWindow/);
  const script = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  const branch = script.slice(script.indexOf('} catch {\n $original=$_;'), script.indexOf(". (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');"));
  assert.match(branch, /Get-OwnedDialogWin32Observation \$bound/); assert.match(branch, /throw \$original;/);
  assert.doesNotMatch(branch, /SetValue|\.Invoke\(/);
  const guards = fs.readFileSync(new URL('../../scripts/installed-native-dialog-guards.ps1', import.meta.url), 'utf8');
  assert.match(guards, /\$c=\$Binding.config; \$root=\$Binding.root; \$rootClass=\$Binding.rootClass; \$dialog=\$Binding.dialog/);
  assert.equal(guards.match(/Stop-OwnedGuard '/g).length, 7);
  assert.match(guards, /learnnote_guard_reason/);
});

test('Windows actual extracted guards execute inside observer scope and independently bound Win32 proof', { skip: process.platform !== 'win32' }, () => {
  const generated = nativeDialogScript(parseArgs(args), { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  const start = generated.indexOf('} catch {\n $original=$_;') + '} catch {'.length;
  const body = generated.slice(start, generated.indexOf(". (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');", start)).replace(/}\s*$/, '');
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File',
    path.resolve('scripts/tests/native-guard-evidence-faults.ps1'), '-HostFailureBody', Buffer.from(body).toString('base64')], { encoding: 'utf8', timeout: 30000, maxBuffer: 1024 * 1024, windowsHide: true });
  assert(!output.includes('PRIVATE')); assert(!output.includes('C:\\'));
  const lines = output.trim().split(/\r?\n/);
  for (const line of lines.slice(0, -1)) {
    if (line.startsWith('HOSTFAIL:')) validateHostFailure(JSON.parse(line.slice(9)));
    else if (line.startsWith('HOSTDIAG:')) validateHostObservation(JSON.parse(line.slice(9)));
    else if (line.startsWith('WIN32DIAG:')) validateWin32Observation(JSON.parse(line.slice(10)));
    else assert.fail('Unexpected native fixture output');
  }
  const { results, primary } = JSON.parse(lines.at(-1)); assert.equal(results.length, 35);
  assert.deepEqual(primary, [{ mode: 'guard', preserved: true }, { mode: 'observer-load', preserved: true }, { mode: 'format', preserved: true }]);
  const reasons = {
    'process-missing': 'process-identity', 'process-name': 'process-identity', 'process-start': 'process-identity',
    'root-gone': 'root-identity', 'root-hidden': 'root-identity', 'root-pid': 'root-identity', 'root-owner': 'root-identity', 'root-class': 'root-identity', 'root-title': 'root-identity',
    'foreground-root': 'foreground', 'foreground-none': 'foreground', 'foreground-other': 'foreground',
    'dialog-gone': 'dialog-identity', 'dialog-hidden': 'dialog-identity', 'dialog-pid': 'dialog-identity', 'dialog-class': 'dialog-identity',
    'owner-process': 'owner-process', 'owner-missing': 'owner-root', 'owner-cycle': 'owner-root', 'popup-extra': 'popup-set', 'popup-missing': 'popup-set',
    'binding-config': 'process-identity', 'binding-root': 'root-identity', 'binding-dialog': 'foreground', 'binding-runtime': 'unclassified', 'uia-guard-after': 'foreground',
  };
  for (const { mode, uia, win32, uia_reads, child_reads, forbidden_reads } of results) {
    assert.doesNotThrow(() => validateHostObservation(uia), `${mode}: UIA schema`);
    assert.doesNotThrow(() => validateWin32Observation(win32), `${mode}: Win32 schema`);
    assert.equal(forbidden_reads, 0, `${mode}: no foreign/content/title read`);
    if (reasons[mode]) {
      assert.equal(uia.status, 'unavailable', mode); assert.equal(uia.reason, 'exception', mode);
      assert.equal(uia.phase, mode === 'uia-guard-after' ? 'guard-after' : 'guard-before', mode);
      assert.equal(uia.guard_failure.reason, reasons[mode], mode);
      assert.equal(uia_reads, mode === 'uia-guard-after' ? 1 : 0, `${mode}: no property read before verified guard`);
      assert.equal(uia.guard_failure.facts.binding_matches, !mode.startsWith('binding-'), mode);
      if (!mode.startsWith('binding-')) {
        assert.equal(win32.status, 'unavailable', mode); assert.equal(win32.phase, 'guard-before', mode);
        assert.equal(win32.guard_failure.reason, reasons[mode], mode); assert.equal(child_reads, 0, mode);
      } else {
        // The independent proof uses originals, never the shadowed callback scope.
        assert.equal(win32.status, 'complete', mode); assert.equal(win32.nodes.length, 4, mode);
      }
    } else {
      assert.equal(uia.status, 'complete', mode); assert.equal(uia_reads, 2, mode);
      if (mode === 'win-guard-after' || mode.startsWith('child-')) {
        assert.equal(win32.status, 'unavailable', mode); assert.deepEqual(win32.nodes, [], mode);
        assert.equal(win32.phase, mode === 'win-guard-after' ? 'guard-after' : 'children', mode);
        if (mode === 'win-guard-after') assert.equal(win32.guard_failure.reason, 'foreground', mode);
      } else {
        assert.equal(win32.status, 'complete', mode);
        if (mode === 'tree-limit') { assert.equal(win32.nodes.length, 64, mode); assert.equal(win32.truncated, true, mode); }
        else if (mode === 'tree-depth') { assert.equal(win32.nodes.length, 9, mode); assert.equal(win32.truncated, true, mode); }
        else if (mode === 'tree-budget') assert.equal(win32.reason, 'budget', mode);
        else { assert.equal(win32.nodes.length, 4, mode); assert.equal(win32.nodes[2].pruned, true, mode); }
        if (mode === 'class-private') assert.equal(win32.nodes[1].cls, '<redacted>', mode);
      }
    }
  }
});

// Canonical SHA-256 of the two guard blocks at base 77d81144, before tagging.
// This freezes predicate evaluation and rejection ordering, including short-circuiting.
test('extracted action guards preserve the exact original predicates and evaluation order', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-native-dialog-guards.ps1', import.meta.url), 'utf8');
  const guardHash = text => {
    const canonical = text.replace(/\r\n/g, '\n'); // Git's Windows checkout changes line endings only.
    const original = canonical.slice(canonical.indexOf('function Assert-Process {'), canonical.indexOf('# Independent evidence proof'))
      .replace(/Stop-OwnedGuard '[a-z-]+' ('[^']*')/g, 'throw $1').trim();
    return createHash('sha256').update(original).digest('hex');
  };
  const baseline = '771f17736daa01cc218b923001ef0324e2c45c9768d6ed892ec5efd5e2b03510';
  const lf = source.replace(/\r\n/g, '\n');
  for (const text of [lf, lf.replace(/\n/g, '\r\n')]) {
    assert.equal(guardHash(text), baseline);
    assert.notEqual(guardHash(text.replace('GetForegroundWindow() -ne', 'GetForegroundWindow() -eq')), baseline);
  }
  const ci = fs.readFileSync(new URL('../../.github/workflows/ci.yml', import.meta.url), 'utf8');
  const release = fs.readFileSync(new URL('../../.github/workflows/desktop-release.yml', import.meta.url), 'utf8');
  assert.doesNotMatch(ci.slice(0, ci.indexOf('permissions:')), /paths(?:-ignore)?:/);
  assert(ci.includes('Get-ChildItem web/tests/*.test.mjs'));
  assert(release.includes('node web/tests/installed_diagnostic_acceptance.test.mjs'));
});

const foregroundEvidence = () => ({ scope: 'read-only-owned-foreground', status: 'complete', phase: 'complete',
  reason: 'complete', elapsed_ms: 25, exception_type: null, guard_failure: null, foreground_is_save: false,
  windows: [{ role: 'save', cls: '#32770', owners: ['root'] }, { role: 'foreground', cls: '#32770', owners: ['save', 'root'] }],
  capture: { ...savedCapture(), file: 'installed-current-md-native-foreground.png' } });

test('owned foreground evidence has exact bounded topology and cannot replace the primary host rejection', async () => {
  validateForegroundEvidence(foregroundEvidence());
  for (const mutate of [v => { v.scope = 'input-approved'; }, v => { v.windows[0].title = 'PRIVATE'; },
    v => { v.windows[0].cls = 'C:\\PRIVATE'; }, v => { v.windows[0].owners = Array(17).fill('root'); },
    v => { v.windows[0].owners = ['root', 'root']; }, v => { v.windows[1].owners = ['foreground', 'root']; },
    v => { v.windows[0].owners = ['PRIVATE']; }, v => { v.windows.push(v.windows[0]); },
    v => { v.windows[0].hwnd = 123; }, v => { v.capture.file = savedCapture().file; },
    v => { v.elapsed_ms = 35001; }, v => { v.status = 'unavailable'; }, v => { v.exception_type = 'PRIVATE'; },
    v => { v.foreground_is_save = true; }, v => { v.foreground_is_save = 'PRIVATE'; }]) {
    const value = foregroundEvidence(); mutate(value); assert.throws(() => validateForegroundEvidence(value));
  }
  for (const variant of ['valid', 'invalid', 'oversized']) {
    const child = fakeChild();
    const result = withNativeHelper(child, () => {
      emitHostFailure(child, hostFailureDetails(0));
      const value = foregroundEvidence(); if (variant !== 'valid') value.private = variant === 'oversized' ? 'x'.repeat(8200) : 'PRIVATE';
      child.line('FOREGROUND:' + JSON.stringify(value)); child.end(1);
    }); child.line('READY');
    await assert.rejects(result, error => {
      assert.equal(error.message, 'Owned native Save helper failed'); assert.deepEqual(error.native_host_failure, hostFailureDetails(0));
      if (variant === 'valid') assert.deepEqual(error.native_foreground_evidence, foregroundEvidence());
      else { assert.equal(error.native_foreground_unavailable, true); assert.equal(error.native_foreground_evidence, undefined); }
      assert(!JSON.stringify(error).includes('PRIVATE')); return true;
    });
  }
});

test('foreground proof is read-only, independently bound, class/topology stable and clears failed evidence', () => {
  const source = fs.readFileSync(new URL('../../scripts/installed-native-foreground-evidence.ps1', import.meta.url), 'utf8');
  assert.match(source, /\$step -lt 16/); assert.match(source, /HashSet\[IntPtr\]/);
  assert.match(source, /Pid\(\$window\) -ne \$c.pid/); assert.match(source, /Pid\(\$cursor\) -ne \$c.pid/);
  assert.match(source, /current.foreground_class -cne \$Proof.state.foreground_class/);
  assert.match(source, /current\[\$key\]\[\$index\] -ne \$Proof.state\[\$key\]\[\$index\]/);
  assert.match(source, /-GuardContext \$proof -Guard \{ param\(\$boundProof\) Assert-OwnedForegroundEvidence \$boundProof \}/);
  assert.match(source, /if \(\$capture.status -eq 'saved'\)/);
  assert.doesNotMatch(source, /::Title|GetWindowText|FindAll|EnumWindows|GetDesktopWindow|CopyFromScreen|SetForeground|SendMessage|SendKeys|SetValue|\.Invoke\(/);
  const capture = fs.readFileSync(new URL('../../scripts/installed-native-dialog-capture.ps1', import.meta.url), 'utf8');
  assert.equal(capture.match(/\[void\]\(& \$Guard \$GuardContext\)/g).length, 3);
  assert.match(capture, /ValidateSet\('dialog','foreground'\)/);
  assert(capture.indexOf("$phase='guard-after'") < capture.indexOf('[IO.File]::Open'));
  const script = nativeDialogScript({ ...parseArgs(args), captureNativeDialog: true }, { owned_start: '123456' }, 'D:\\owned\\local-native-exports-fresh', 'D:\\owned\\local-native-exports-fresh\\learnnote-diagnostics.md');
  const branch = script.slice(script.indexOf('} catch {\n $original=$_;'), script.indexOf(". (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');"));
  assert.match(branch, /if \(\$c.capture\)/); assert.match(branch, /Get-OwnedForegroundEvidence \$bound \$c.directory \$c.destination/);
  assert.match(branch, /throw \$original;/);
});

test('Windows actual foreground proof rejects ownership and capture races without pixels or native input', { skip: process.platform !== 'win32' }, () => {
  const output = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File',
    path.resolve('scripts/tests/native-foreground-evidence-faults.ps1')], { encoding: 'utf8', timeout: 15000, windowsHide: true });
  assert(!output.includes('PRIVATE')); assert(!output.includes('C:\\'));
  const { results } = JSON.parse(output.trim()); assert.equal(results.length, 31);
  for (const { mode, evidence, captures, guards, persisted, forbidden } of results) {
    assert.doesNotThrow(() => validateForegroundEvidence(evidence), mode); assert.equal(forbidden, 0, mode);
    if (['success', 'sibling', 'foreground-save', 'private-class'].includes(mode)) {
      assert.equal(evidence.status, 'complete', mode); assert.equal(captures, 1, mode); assert.equal(guards, 2, mode); assert.equal(persisted, 1, mode);
      assert.equal(evidence.foreground_is_save, mode === 'foreground-save', mode);
      assert.deepEqual(evidence.windows[1].owners, mode === 'sibling' || mode === 'foreground-save' ? ['root'] : ['save', 'root'], mode);
      if (mode === 'private-class') assert.equal(evidence.windows[1].cls, '<redacted>', mode);
    } else {
      assert.equal(evidence.status, 'unavailable', mode); assert.deepEqual(evidence.windows, [], mode); assert.equal(persisted, 0, mode);
      assert.equal(evidence.capture.file, null, mode);
      if (mode.startsWith('race-') || mode.startsWith('capture-')) { assert.equal(captures, 1, mode); assert.equal(evidence.reason, 'capture-unavailable', mode); }
      else { assert.equal(captures, 0, mode); assert.equal(evidence.phase, 'guard-before', mode); assert.equal(evidence.reason, 'exception', mode); }
    }
  }
});
