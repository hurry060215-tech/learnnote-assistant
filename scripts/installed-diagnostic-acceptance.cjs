// Existing owned installed WebView2 only. No browser launch, context replacement,
// response mocks, source backend or persisted raw diagnostic/download contents.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync, spawn } = require('node:child_process');
const { fileObservation, attachDownloadObservation } = require('./installed-download-observation.cjs');
const TIMEOUT = 15000, MAX_BYTES = 256 * 1024;
const SYNTHETIC_TITLE = 'Synthetic rollback captions';
const HOST_SUBPHASES = ['query', 'match-count', 'host-validation', 'modern-ancestor'];
const OBSERVER_PHASES = ['initialization', 'guard-before', 'node-properties', 'first-child', 'next-sibling', 'guard-after', 'complete'];
const OBSERVER_EXCEPTIONS = ['element-unavailable', 'element-disabled', 'com', 'invalid-operation', 'method-invocation', 'runtime', 'other'];
const NATIVE_PHASES = ['uia-initialization', 'ownership', 'destination', 'dialog-wait', 'dialog-capture', 'filename-host', 'filename-edit', 'save-button', 'filename-set', 'save-invoke', 'save-completion', 'cancel-observation'];
const CONTROL_SUBPHASES = ['edit-query', 'edit-count', 'edit-control', 'edit-value-pattern', 'edit-initial-name',
  'save-handle', 'save-control', 'save-profile', 'save-invoke-pattern', 'runtime-ids'];

function parseArgs(args) {
  assert(args.length >= 7, 'Expected output-dir debug-port api-origin task-id owned-app-pid --expected-version VERSION [--startup-only]');
  const [output, port, origin, taskId, pid] = args;
  let startupOnly = false, expectedVersion, privateLocationEvidence = false;
  for (let i = 5; i < args.length; i++) {
    if (args[i] === '--private-location-evidence' && !privateLocationEvidence) privateLocationEvidence = true;
    else if (args[i] === '--startup-only' && !startupOnly) startupOnly = true;
    else if (args[i] === '--expected-version' && !expectedVersion) expectedVersion = args[++i];
    else throw new Error('Unknown or repeated acceptance option');
  }
  assert(/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(expectedVersion || ''), 'Explicit expected version is required');
  assert(/^\d{1,5}$/.test(port) && Number(port) > 0 && Number(port) < 65536, 'Invalid debug port');
  assert(/^[1-9]\d{0,9}$/.test(pid) && Number(pid) <= 0xffffffff, 'Invalid owned app PID');
  const url = new URL(origin);
  assert.equal(url.protocol, 'http:'); assert.equal(url.hostname, '127.0.0.1');
  assert.equal(url.origin, origin, 'API origin must not include credentials, path, query or fragment');
  assert(url.port && Number(url.port) !== Number(port), 'API and debug ports must be distinct');
  assert(/^[A-Za-z0-9_-]{1,128}$/.test(taskId), 'Invalid synthetic task ID');
  assert(output && !output.startsWith('--'), 'Output directory is required');
  return { output: path.resolve(output), debugPort: Number(port), apiPort: Number(url.port), origin, taskId, ownedPid: Number(pid), startupOnly, expectedVersion, ...(privateLocationEvidence ? { privateLocationEvidence: true } : {}) };
}

async function bounded(promise, label, timeout = TIMEOUT) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), timeout); })]); }
  finally { clearTimeout(timer); }
}

async function readInstalledJSON(origin, route, request = fetch) {
  const response = await request(origin + route, { signal: AbortSignal.timeout(TIMEOUT), redirect: 'error' });
  assert(response.ok, `Installed API ${route} failed: ${response.status}`);
  return bounded(response.json(), 'installed API JSON');
}

// Query only the supplied port/process and its ancestor chain. No command lines,
// environment variables, user profile paths or unrelated window contents leave it.
function verifyOwned(config, execute = execFileSync) {
  const script = `$ErrorActionPreference='Stop'; $ownedId=${config.ownedPid}; $port=${config.debugPort}; $apiPort=${config.apiPort};
    $owned=Get-CimInstance Win32_Process -Filter "ProcessId = $ownedId";
    if (!$owned -or $owned.Name -ne 'LearnNote.exe') { throw 'Owned LearnNote process is unavailable' }
    $apiListeners=@(Get-NetTCPConnection -State Listen -LocalPort $apiPort -ErrorAction Stop);
    if ($apiListeners.Count -eq 0 -or @($apiListeners | Where-Object {
      $_.LocalAddress -notin @('127.0.0.1','::1') -or $_.OwningProcess -ne $ownedId
    }).Count) { throw 'API listener must be loopback-only and owned by the supplied LearnNote process' }
    $deadline=[DateTime]::UtcNow.AddSeconds(20); $listeners=@();
    do { $listeners=@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue);
      if ($listeners.Count -eq 0) { Start-Sleep -Milliseconds 100 }
    } while ($listeners.Count -eq 0 -and [DateTime]::UtcNow -lt $deadline);
    if ($listeners.Count -eq 0) { throw 'Owned debug listener did not start' }
    if (@($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1','::1') }).Count) { throw 'Debug listener is not loopback-only' }
    $owners=@($listeners.OwningProcess | Select-Object -Unique);
    if ($owners.Count -ne 1) { throw 'Debug listener ownership is ambiguous' }
    $debug=Get-CimInstance Win32_Process -Filter "ProcessId = $($owners[0])";
    if (!$debug -or $debug.Name -ne 'msedgewebview2.exe') { throw 'Expected owned WebView2 debug listener' }
    $cursor=$debug; $matched=$false; $seen=@{};
    for ($i=0; $i -lt 24 -and $cursor; $i++) {
      if ($cursor.ProcessId -eq $ownedId) { $matched=$true; break }
      if ($seen.ContainsKey([string]$cursor.ProcessId)) { break }; $seen[[string]$cursor.ProcessId]=$true;
      $cursor=Get-CimInstance Win32_Process -Filter "ProcessId = $($cursor.ParentProcessId)";
    }
    if (!$matched) { throw 'Debug listener is not a descendant of the owned app' }
    @{owned_pid=$ownedId;owned_start=$owned.CreationDate.ToUniversalTime().Ticks.ToString();api_port=$apiPort;api_pid=$ownedId;
      debug_pid=[int]$debug.ProcessId;debug_start=$debug.CreationDate.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json -Compress`;
  return JSON.parse(execute('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
    { encoding: 'utf8', timeout: 30000, windowsHide: true, maxBuffer: 65536 }).trim());
}

function assertSyntheticTask(task, taskId) {
  assert(task.id === taskId && task.title === SYNTHETIC_TITLE, 'Expected exact owned synthetic task identity');
  assert(task.handoff_id === 'native-rollback-synthetic-caption', 'Expected synthetic handoff identity');
  assert(task.page_url === 'https://example.com/synthetic-rollback', 'Expected synthetic source URL');
  assert(task.status === 'success' && task.summary_source === 'subtitle-extract', 'Expected retained synthetic caption task');
}

function selectOwnedPage(browser, origin) {
  const pages = browser.contexts().flatMap(context => context.pages()).filter(page => {
    try { const url = new URL(page.url()); return url.origin === origin && ['/', '/web/index.html'].includes(url.pathname); }
    catch { return false; }
  });
  assert(pages.length <= 1, 'More than one matching installed app page');
  return pages[0];
}

function ownedRequest(url, origin) {
  try { const target = new URL(url); return ['blob:', 'data:'].includes(target.protocol) || target.origin === origin; }
  catch { return false; }
}

// Accept only bounded structural diagnostics; native labels and values never cross this boundary.
function exactKeys(value, keys) {
  assert(value && typeof value === 'object' && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort());
}
function validateHostFailure(value) {
  exactKeys(value, ['subphase', 'host_count', 'host_count_capped']);
  assert(HOST_SUBPHASES.includes(value.subphase));
  assert(value.host_count === null || Number.isInteger(value.host_count) && value.host_count >= 0 && value.host_count <= 64);
  assert(typeof value.host_count_capped === 'boolean');
  assert(!value.host_count_capped || value.host_count === 64);
  return value;
}
function validateControlFailure(value) {
  exactKeys(value, ['subphase', 'observation']); assert(CONTROL_SUBPHASES.includes(value.subphase));
  const observation = value.observation;
  exactKeys(observation, ['status', 'phase', 'reason', 'exception_type', 'elapsed_ms', 'edit', 'save']);
  assert(['complete', 'unavailable'].includes(observation.status));
  assert(['guard-before', 'edit', 'save', 'guard-after', 'complete'].includes(observation.phase));
  assert(['complete', 'exception', 'budget', 'runtime-changed'].includes(observation.reason));
  assert(observation.exception_type === null || OBSERVER_EXCEPTIONS.includes(observation.exception_type));
  assert(Number.isInteger(observation.elapsed_ms) && observation.elapsed_ms >= 0 && observation.elapsed_ms <= 35000);
  if (observation.status === 'unavailable') {
    assert.notEqual(observation.phase, 'complete'); assert.notEqual(observation.reason, 'complete');
    assert.equal(observation.edit, null); assert.equal(observation.save, null); return value;
  }
  assert.equal(observation.phase, 'complete'); assert.equal(observation.reason, 'complete'); assert.equal(observation.exception_type, null);
  const booleans = ['control_valid', 'native_identity', 'pattern_available', 'runtime_present', 'runtime_stable',
    'read_only', 'expected_basename', 'expected_stem', 'handle_present', 'direct_child', 'profile_matches'];
  for (const role of ['edit', 'save']) {
    const facts = observation[role]; exactKeys(facts, ['phase', 'reason', 'exception_type', 'count', 'count_capped', ...booleans]);
    assert(['query', 'count', 'handle', 'control', 'pattern', 'value', 'complete'].includes(facts.phase));
    assert(['complete', 'rejected', 'exception'].includes(facts.reason));
    assert(facts.exception_type === null || OBSERVER_EXCEPTIONS.includes(facts.exception_type));
    assert(facts.count === null || Number.isInteger(facts.count) && facts.count >= 0 && facts.count <= 64);
    assert(typeof facts.count_capped === 'boolean'); assert(!facts.count_capped || facts.count === 64);
    for (const key of booleans) assert(facts[key] === null || typeof facts[key] === 'boolean');
    assert.equal(facts.phase === 'complete', facts.reason === 'complete');
    if (facts.reason !== 'exception') assert.equal(facts.exception_type, null);
    if (facts.runtime_present === true) assert.equal(facts.runtime_stable, true); else assert.equal(facts.runtime_stable, null);
    if (role === 'edit') {
      for (const key of ['handle_present', 'direct_child', 'profile_matches']) assert.equal(facts[key], null);
      assert(!(facts.expected_basename && facts.expected_stem));
    } else {
      assert.equal(facts.count, null); assert.equal(facts.count_capped, false);
      for (const key of ['read_only', 'expected_basename', 'expected_stem']) assert.equal(facts[key], null);
    }
  }
  return value;
}
const GUARD_REASONS = ['process-identity', 'root-identity', 'foreground', 'dialog-identity', 'owner-process', 'owner-root', 'popup-set', 'unclassified'];
const GUARD_FACT_BOOLEANS = ['binding_matches', 'process_exists', 'process_name_matches', 'process_start_matches',
  'root_exists', 'root_visible', 'root_pid_matches', 'root_ownerless', 'root_class_matches', 'root_title_matches',
  'dialog_exists', 'dialog_visible', 'dialog_pid_matches', 'dialog_class_matches', 'visible_set_matches'];
function validateGuardFailure(value, expected) {
  if (!expected) { assert.equal(value, null); return; }
  exactKeys(value, ['reason', 'facts']); assert(GUARD_REASONS.includes(value.reason));
  if (value.facts === null) return;
  exactKeys(value.facts, [...GUARD_FACT_BOOLEANS, 'foreground', 'owner_chain', 'visible_count']);
  for (const key of GUARD_FACT_BOOLEANS) assert(value.facts[key] === null || typeof value.facts[key] === 'boolean');
  assert(['dialog', 'root', 'none', 'other', 'unavailable'].includes(value.facts.foreground));
  assert(['root', 'foreign', 'missing', 'limit', 'unavailable'].includes(value.facts.owner_chain));
  assert(value.facts.visible_count === null || Number.isInteger(value.facts.visible_count) && value.facts.visible_count >= 0 && value.facts.visible_count <= 64);
}
function validateWin32Observation(value) {
  exactKeys(value, ['status', 'phase', 'reason', 'elapsed_ms', 'exception_type', 'guard_failure', 'truncated', 'nodes']);
  assert(['complete', 'unavailable'].includes(value.status));
  assert(['guard-before', 'children', 'guard-after', 'complete'].includes(value.phase));
  assert(['complete', 'budget', 'exception'].includes(value.reason));
  assert(Number.isInteger(value.elapsed_ms) && value.elapsed_ms >= 0 && value.elapsed_ms <= 35000);
  assert(value.reason === 'exception' ? OBSERVER_EXCEPTIONS.includes(value.exception_type) : value.exception_type === null);
  validateGuardFailure(value.guard_failure, value.reason === 'exception' && ['guard-before', 'guard-after'].includes(value.phase));
  assert.equal(value.status === 'complete', value.phase === 'complete');
  assert.equal(value.status === 'unavailable', value.reason === 'exception');
  assert(value.reason !== 'budget' || value.elapsed_ms >= 500);
  assert(typeof value.truncated === 'boolean'); assert(Array.isArray(value.nodes) && value.nodes.length <= 64);
  if (value.status === 'unavailable') { assert.equal(value.nodes.length, 0); assert.equal(value.truncated, false); }
  for (const [index, node] of value.nodes.entries()) {
    exactKeys(node, ['parent', 'depth', 'cls', 'id', 'pruned']);
    assert(Number.isInteger(node.parent) && node.parent >= -1 && node.parent < index);
    assert(Number.isInteger(node.depth) && node.depth >= 0 && node.depth <= 8);
    assert(node.parent === -1 ? index === 0 && node.depth === 0 : node.depth === value.nodes[node.parent].depth + 1);
    assert(typeof node.cls === 'string' && (node.cls === '<redacted>' || /^[A-Za-z0-9_#.-]{0,64}$/.test(node.cls)));
    assert(Number.isInteger(node.id) && node.id >= -2147483648 && node.id <= 2147483647);
    assert(typeof node.pruned === 'boolean');
    if (node.parent >= 0) assert.equal(value.nodes[node.parent].pruned, false);
  }
  return value;
}

function validateHostObservation(value) {
  exactKeys(value, ['status', 'snapshots', 'phase', 'reason', 'elapsed_ms', 'exception_type', 'guard_failure']);
  validateGuardFailure(value.guard_failure, value.reason === 'exception' && ['guard-before', 'guard-after'].includes(value.phase));
  assert(OBSERVER_PHASES.includes(value.phase));
  assert(['complete', 'exception', 'budget', 'unavailable'].includes(value.reason));
  assert(Number.isInteger(value.elapsed_ms) && value.elapsed_ms >= 0 && value.elapsed_ms <= 35000);
  assert(value.reason === 'exception' ? OBSERVER_EXCEPTIONS.includes(value.exception_type) : value.exception_type === null);
  assert(value.phase !== 'complete' || value.reason === 'complete');
  assert(value.reason !== 'complete' || value.phase === 'complete' && value.status === 'complete');
  assert(value.reason !== 'budget' || value.elapsed_ms >= 1000);
  assert(value.reason !== 'unavailable' || value.phase === 'initialization' && value.status === 'unavailable');
  assert(['complete', 'partial', 'unavailable'].includes(value.status));
  assert(Array.isArray(value.snapshots) && value.snapshots.length <= 2);
  for (const snapshot of value.snapshots) {
    exactKeys(snapshot, ['elapsed_ms', 'truncated', 'foreign_nodes', 'nodes']);
    assert(Number.isInteger(snapshot.elapsed_ms) && snapshot.elapsed_ms >= 0 && snapshot.elapsed_ms <= 35000);
    assert(typeof snapshot.truncated === 'boolean');
    assert(Number.isInteger(snapshot.foreign_nodes) && snapshot.foreign_nodes >= 0 && snapshot.foreign_nodes <= 64);
    assert(Array.isArray(snapshot.nodes) && snapshot.nodes.length + snapshot.foreign_nodes <= 64);
    for (const [index, node] of snapshot.nodes.entries()) {
      exactKeys(node, ['parent', 'depth', 'type', 'cls', 'id', 'pruned']);
      assert(Number.isInteger(node.parent) && node.parent >= -1 && node.parent < index);
      assert(Number.isInteger(node.depth) && node.depth >= 0 && node.depth <= 8);
      assert(node.parent === -1 ? index === 0 && node.depth === 0 : node.depth === snapshot.nodes[node.parent].depth + 1);
      assert(Number.isInteger(node.type) && node.type >= 50000 && node.type <= 50100);
      for (const key of ['cls', 'id']) assert(typeof node[key] === 'string' &&
        (node[key] === '<redacted>' || /^[A-Za-z0-9_#.-]{0,64}$/.test(node[key])));
      assert(typeof node.pruned === 'boolean');
      if (node.pruned) assert(node.cls === '' && node.id === '');
      if (node.parent >= 0) assert.equal(snapshot.nodes[node.parent].pruned, false);
    }
  }
  assert(value.status !== 'complete' || value.snapshots.length === 2 && value.reason === 'complete');
  assert(value.status !== 'partial' || value.snapshots.length === 1);
  assert(value.status !== 'unavailable' || value.snapshots.length === 0);
  return value;
}

function validateNativeCapture(value, surface = 'dialog') {
  assert(['dialog', 'foreground'].includes(surface));
  exactKeys(value, ['status', 'reason', 'file', 'width', 'height']);
  assert(['saved', 'unavailable'].includes(value.status));
  assert(['captured', 'guard-before', 'destination', 'bounds', 'render', 'guard-after', 'persist', 'unavailable'].includes(value.reason));
  if (value.status === 'saved') {
    assert.equal(value.reason, 'captured');
    assert(['md', 'json'].map(format => `installed-current-${format}-native-${surface}.png`).includes(value.file));
    for (const key of ['width', 'height']) assert(Number.isInteger(value[key]) && value[key] >= 64 && value[key] <= 4096);
  } else {
    assert.notEqual(value.reason, 'captured'); assert.equal(value.file, null);
    assert.equal(value.width, null); assert.equal(value.height, null);
  }
  return value;
}

function validateForegroundEvidence(value) {
  exactKeys(value, ['scope', 'status', 'phase', 'reason', 'elapsed_ms', 'exception_type', 'guard_failure', 'foreground_is_save', 'windows', 'capture']);
  assert.equal(value.scope, 'read-only-owned-foreground');
  assert(['complete', 'unavailable'].includes(value.status));
  assert(['guard-before', 'capture', 'complete'].includes(value.phase));
  assert(['complete', 'exception', 'capture-unavailable'].includes(value.reason));
  assert(Number.isInteger(value.elapsed_ms) && value.elapsed_ms >= 0 && value.elapsed_ms <= 35000);
  assert(value.reason === 'exception' ? OBSERVER_EXCEPTIONS.includes(value.exception_type) : value.exception_type === null);
  validateGuardFailure(value.guard_failure, value.reason === 'exception');
  validateNativeCapture(value.capture, 'foreground');
  assert(Array.isArray(value.windows));
  if (value.status === 'complete') {
    assert.equal(typeof value.foreground_is_save, 'boolean');
    assert.equal(value.phase, 'complete'); assert.equal(value.reason, 'complete'); assert.equal(value.capture.status, 'saved');
    assert.deepEqual(value.windows.map(window => window.role), ['save', 'foreground']);
    for (const window of value.windows) {
      exactKeys(window, ['role', 'cls', 'owners']);
      assert(typeof window.cls === 'string' && (window.cls === '<redacted>' || /^[A-Za-z0-9_#.-]{1,64}$/.test(window.cls)));
      assert(Array.isArray(window.owners) && window.owners.length >= 1 && window.owners.length <= 16);
      assert.equal(window.owners.at(-1), 'root');
      assert(window.owners.slice(0, -1).every(role => ['save', 'foreground', 'other-owned'].includes(role) && role !== window.role));
    }
    assert.equal(value.windows[0].cls, '#32770');
    if (value.foreground_is_save) {
      assert.equal(value.windows[1].cls, value.windows[0].cls); assert.deepEqual(value.windows[1].owners, value.windows[0].owners);
    }
  } else {
    assert.equal(value.foreground_is_save, null);
    assert.notEqual(value.phase, 'complete'); assert.notEqual(value.reason, 'complete');
    assert.equal(value.capture.status, 'unavailable'); assert.equal(value.windows.length, 0);
    if (value.reason === 'capture-unavailable') assert.equal(value.phase, 'capture');
  }
  return value;
}

// Native common Save dialog only: no browser download override or global keys.
// Initialize Framework defaults from a compiled frame before dynamic PowerShell UIA calls.
function nativeDialogScript(config, binding, directory, destination, observeOnly = false) {
  const payload = Buffer.from(JSON.stringify({ pid: config.ownedPid, start: binding.owned_start,
    directory, destination, observeOnly,
    capture: config.captureNativeDialog === true && !observeOnly, observer: path.join(__dirname, 'installed-native-dialog-observation.ps1') })).toString('base64');
  return String.raw`$ErrorActionPreference='Stop';
$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${payload}')) | ConvertFrom-Json;
Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes;
Add-Type -ReferencedAssemblies @([Windows.Automation.AutomationElement].Assembly.Location,[Windows.Automation.AutomationIdentifier].Assembly.Location) -TypeDefinition @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class OwnedSave {
 [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
 public static void InitializeAutomation() {
  var providers=new System.Windows.Automation.ClientSideProviderDescription[0];
  System.Windows.Automation.ClientSettings.RegisterClientSideProviders(providers);
  GC.KeepAlive(providers);
 }
 public delegate bool Callback(IntPtr h, IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback cb, IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint kind);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
 [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder b, int n);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder b, int n);
 public static uint Pid(IntPtr h) { uint p; GetWindowThreadProcessId(h,out p); return p; }
 public static string Class(IntPtr h) { var b=new StringBuilder(256); GetClassName(h,b,256); return b.ToString(); }
 public static string Title(IntPtr h) { var b=new StringBuilder(256); GetWindowText(h,b,256); return b.ToString(); }
 public static IntPtr[] Visible(uint pid) { var list=new List<IntPtr>(); EnumWindows((h,p)=>{if(Pid(h)==pid && IsWindowVisible(h)) list.Add(h);return true;},IntPtr.Zero); return list.ToArray(); }
}
'@;
function Stage([string]$name) { [Console]::Out.WriteLine('PHASE:'+$name); [Console]::Out.Flush() }
Stage 'uia-initialization'; [OwnedSave]::InitializeAutomation();
. (Join-Path (Split-Path $c.observer) 'installed-native-dialog-guards.ps1');
Stage 'ownership';
function Assert-Destination {
 $dir=[IO.Path]::GetFullPath($c.directory); $file=[IO.Path]::GetFullPath($c.destination);
 if ($dir -notmatch '^[A-Za-z]:\\' -or [IO.Path]::GetFileName($dir) -notlike 'local-native-exports-*' -or
   [IO.Path]::GetFileName($file) -cnotin @('learnnote-diagnostics.md','learnnote-diagnostics.json') -or
   $dir -cne $c.directory -or $file -cne $c.destination -or [IO.Path]::GetDirectoryName($file) -cne $dir -or
   !(Test-Path -LiteralPath $dir -PathType Container) -or ((Get-Item -LiteralPath $dir).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
   (Test-Path -LiteralPath $file)) { throw 'Native save destination must be fresh and directly contained in the owned directory' }
}
Assert-Process;
$windows=@([OwnedSave]::Visible($c.pid));
$roots=@($windows | Where-Object { [OwnedSave]::GetWindow($_,4) -eq [IntPtr]::Zero });
if ($roots.Count -ne 1 -or $windows.Count -ne 1) { throw 'Expected exactly one owned app root and no preexisting popup' }
$root=[IntPtr]$roots[0]; $rootClass=[OwnedSave]::Class($root);
if ([OwnedSave]::Title($root) -cne 'LearnNote - Video Learning Notes' -or ![OwnedSave]::Class($root).StartsWith('WindowsForms10.Window.')) { throw 'Unexpected owned app root' }
function Assert-Control($node,$dialogElement) {
 if ($node.Current.ProcessId -ne $c.pid -or !$node.Current.IsEnabled -or $node.Current.IsOffscreen) { throw 'Native control ownership or visibility changed' }
 $cursor=$node; $reached=$false;
 for ($i=0; $i -lt 32 -and $cursor; $i++) {
  if ($cursor.Current.ProcessId -ne $c.pid -or $cursor.Current.ControlType -eq [Windows.Automation.ControlType]::Document) { throw 'Native control left owned dialog' }
  if ([Windows.Automation.Automation]::Compare($cursor,$dialogElement)) { $reached=$true; break }
  $cursor=[Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($cursor);
 }
 if (!$reached) { throw 'Native control ancestry is invalid' }
}
if (!$c.observeOnly) { Stage 'destination'; Assert-Destination }
[Console]::Out.WriteLine('READY'); [Console]::Out.Flush();
Stage $(if ($c.observeOnly) { 'cancel-observation' } else { 'dialog-wait' });
if ($c.observeOnly -and [Console]::In.ReadLine() -cne 'ACTION_COMPLETE') { throw 'Native observation action was interrupted' }
$deadline=[DateTime]::UtcNow.AddSeconds($(if ($c.observeOnly) { 1 } else { 15 })); $dialog=[IntPtr]::Zero;
do {
 Assert-Root; $popups=@([OwnedSave]::Visible($c.pid) | Where-Object { $_ -ne $root });
 if ($c.observeOnly -and $popups.Count) { throw 'Cancellation opened a native popup' }
 if (!$c.observeOnly -and $popups.Count) {
  if ($popups.Count -ne 1) { throw 'Ambiguous owned native popups' }; $dialog=[IntPtr]$popups[0]; Assert-Dialog $dialog; break;
 }
 Start-Sleep -Milliseconds 50;
} while ([DateTime]::UtcNow -lt $deadline);
if ($c.observeOnly) { @{native_popup_absent=$true} | ConvertTo-Json -Compress; exit 0 }
if ($dialog -eq [IntPtr]::Zero) { throw 'Owned Save dialog did not appear' }
if ($c.capture) {
 Stage 'dialog-capture';
 $captureEvidence=@{status='unavailable';reason='unavailable';file=$null;width=$null;height=$null};
 try {
  . (Join-Path (Split-Path $c.observer) 'installed-native-dialog-capture.ps1');
  $captureEvidence=Save-OwnedDialogCapture $dialog $c.directory $c.destination { Assert-Dialog $dialog };
 } catch { } # Optional evidence; no input.
 [Console]::Out.WriteLine('CAPTURE:'+($captureEvidence | ConvertTo-Json -Compress)); [Console]::Out.Flush();
}
$element=[Windows.Automation.AutomationElement]::FromHandle($dialog);
$all=[Windows.Automation.Condition]::TrueCondition; $desc=[Windows.Automation.TreeScope]::Descendants;
Stage 'filename-host'; $hostCount=$null; $hostSubphase='query';
try {
[Console]::Out.WriteLine('SUBPHASE:'+$hostSubphase);
$hosts=@($element.FindAll($desc,$all) | Where-Object {
 $_.Current.ControlType -eq [Windows.Automation.ControlType]::ComboBox -and $_.Current.AutomationId -ceq 'FileNameControlHost' -and $_.Current.ClassName -ceq 'AppControlHost'
});
$hostCount=$hosts.Count; $hostSubphase='match-count'; [Console]::Out.WriteLine('SUBPHASE:'+$hostSubphase);
if ($hosts.Count -ne 1) { throw 'Unsupported or ambiguous native filename host' }; $hostControl=$hosts[0]; $hostSubphase='host-validation'; [Console]::Out.WriteLine('SUBPHASE:'+$hostSubphase); Assert-Control $hostControl $element;
$hostSubphase='modern-ancestor'; [Console]::Out.WriteLine('SUBPHASE:'+$hostSubphase);
$ancestor=[Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($hostControl); $modern=$false;
for ($i=0; $i -lt 16 -and $ancestor -and ![Windows.Automation.Automation]::Compare($ancestor,$element); $i++) {
 if ($ancestor.Current.ClassName -ceq 'DUIViewWndClassName') { $modern=$true; break }; $ancestor=[Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor);
}
if (!$modern) { throw 'Unsupported native Save dialog layout' }
} catch {
 $original=$_;
 try {
  $details=@{subphase=$hostSubphase;host_count=$(if ($null -eq $hostCount) { $null } else { [Math]::Min(64,$hostCount) });host_count_capped=($null -ne $hostCount -and $hostCount -gt 64)};
  [Console]::Out.WriteLine('HOSTFAIL:'+($details | ConvertTo-Json -Compress)); [Console]::Out.Flush();
  . $c.observer;
  . (Join-Path (Split-Path $c.observer) 'installed-native-dialog-win32.ps1');
  $bound=@{config=@{pid=$c.pid;start=$c.start};root=$root;rootClass=$rootClass;dialog=$dialog};
  $observation=Get-OwnedDialogObservation -Element $element -OwnedPid $c.pid -Guard { Assert-Dialog $dialog } -FailureFacts { Get-OwnedDialogIdentityFacts $bound };
  [Console]::Out.WriteLine('HOSTDIAG:'+($observation | ConvertTo-Json -Depth 8 -Compress)); [Console]::Out.Flush();
  $structure=Get-OwnedDialogWin32Observation $bound;
  [Console]::Out.WriteLine('WIN32DIAG:'+($structure | ConvertTo-Json -Depth 8 -Compress)); [Console]::Out.Flush();
  if ($c.capture) {
   . (Join-Path (Split-Path $c.observer) 'installed-native-foreground-evidence.ps1');
   $foregroundEvidence=Get-OwnedForegroundEvidence $bound $c.directory $c.destination;
   [Console]::Out.WriteLine('FOREGROUND:'+($foregroundEvidence | ConvertTo-Json -Depth 8 -Compress)); [Console]::Out.Flush();
  }
 } catch { } # Evidence collection cannot replace the original rejection.
 throw $original;
}
. (Join-Path (Split-Path $c.observer) 'installed-native-save-controls.ps1');
function Assert-BoundControls {
 Assert-Control $edit $element; Assert-Control $button $element;
 if (($edit.GetRuntimeId() -join ',') -cne $editRuntime -or ($button.GetRuntimeId() -join ',') -cne $buttonRuntime -or
  [OwnedSave]::GetDlgItem($dialog,1) -ne $buttonHandle -or [OwnedSave]::GetParent($buttonHandle) -ne $dialog) { throw 'Bound native controls changed' }
}
Stage 'filename-set';
Assert-Dialog $dialog; Assert-BoundControls; Assert-Destination;
$value.SetValue($c.destination);
if ($value.Current.Value -cne $c.destination) { throw 'Native filename readback differs' }
Stage 'save-invoke';
Assert-Dialog $dialog; Assert-BoundControls; Assert-Destination;
$invoke.Invoke();
Stage 'save-completion';
$deadline=[DateTime]::UtcNow.AddSeconds(10);
do {
 Assert-Root; $popups=@([OwnedSave]::Visible($c.pid) | Where-Object { $_ -ne $root });
 if (@($popups | Where-Object { $_ -ne $dialog }).Count) { throw 'Unexpected confirmation or security popup; no further input' }
 if ($popups.Count -eq 0) { @{native_dialog=$true;saved=$true} | ConvertTo-Json -Compress; exit 0 }
 Start-Sleep -Milliseconds 50;
} while ([DateTime]::UtcNow -lt $deadline);
throw 'Native Save did not finish';`;
}

async function withNativeHelper(child, action, timeouts = {}, onPhase = () => {}) {
  const observed = phase => { try { onPhase(phase); } catch { } }; // Optional receipt evidence only.
  let controlFailure, controlInvalid = false;
  let foregroundEvidence, foregroundInvalid = false;
  let readyResolve, readyReject, doneResolve, doneReject, closedResolve, output = '', result, ready = false, failure, nativeFailure, nativePhase, nativeSubphase, hostFailure, hostObservation, nativeCapture, win32Observation, win32Invalid = false, captureInvalid = false, evidenceInvalid = false;
  const readyPromise = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
  const done = new Promise((resolve, reject) => { doneResolve = resolve; doneReject = reject; });
  const closed = new Promise(resolve => { closedResolve = resolve; });
  const fail = error => { if (nativePhase) error.native_stage = nativePhase; nativeFailure ||= error; readyReject(error); doneReject(error); };
  // Observe failures from launch onward, including while the real DOM click waits.
  readyPromise.catch(() => {}); done.catch(() => {});
  child.stdout.on('data', chunk => {
    output += chunk.toString('utf8');
    if (output.length > 65536) { fail(new Error('Owned native helper output exceeded its limit')); return; }
    let index;
    while ((index = output.indexOf('\n')) >= 0) {
      const line = output.slice(0, index).trim(); output = output.slice(index + 1);
      if (line.startsWith('PHASE:')) {
        const phase = line.slice(6); if (NATIVE_PHASES.includes(phase)) { nativePhase = phase; observed(phase); } else fail(new Error('Unknown native helper phase'));
      } else if (line.startsWith('SUBPHASE:')) {
        const subphase = line.slice(9);
        if (nativePhase === 'filename-host' && HOST_SUBPHASES.includes(subphase)) nativeSubphase = subphase;
        else fail(new Error('Unknown native host subphase'));
      } else if (line.startsWith('HOSTFAIL:')) {
        try {
          assert(ready && nativePhase === 'filename-host' && !hostFailure);
          const details = validateHostFailure(JSON.parse(line.slice(9)));
          hostFailure = new Error('Owned native Save helper failed');
          hostFailure.native_host_failure = details;
          nativeSubphase = hostFailure.native_host_failure.subphase;
        } catch { fail(new Error('Invalid native host failure metadata')); }
      } else if (line.startsWith('CONTROLFAIL:')) {
        try {
          assert(ready && ['filename-edit', 'save-button'].includes(nativePhase) && !controlFailure);
          controlFailure = new Error('Owned native Save helper failed');
          assert(line.length <= 8192);
          const details = validateControlFailure(JSON.parse(line.slice(12)));
          assert.equal(details.subphase.startsWith('edit-'), nativePhase === 'filename-edit');
          controlFailure.native_control_failure = details;
        } catch { controlInvalid = true; fail(new Error('Invalid native control failure metadata')); }
      } else if (line.startsWith('CAPTURE:')) {
        try { assert(ready && nativePhase === 'dialog-capture' && !nativeCapture); nativeCapture = validateNativeCapture(JSON.parse(line.slice(8))); }
        catch { captureInvalid = true; } // Never retain paths or unvalidated pixel metadata.
      } else if (line.startsWith('HOSTDIAG:')) {
        try { assert(hostFailure && !hostObservation && line.length <= 32768); hostObservation = validateHostObservation(JSON.parse(line.slice(9))); }
        catch { evidenceInvalid = true; } // Keep the original native rejection, never raw metadata.
      } else if (line.startsWith('WIN32DIAG:')) {
        try { assert(hostFailure && !win32Observation && line.length <= 32768); win32Observation = validateWin32Observation(JSON.parse(line.slice(10))); }
        catch { win32Invalid = true; }
      } else if (line.startsWith('FOREGROUND:')) {
        try { assert(hostFailure && !foregroundEvidence && line.length <= 8192); foregroundEvidence = validateForegroundEvidence(JSON.parse(line.slice(11))); }
        catch { foregroundInvalid = true; }
      } else if (line === 'READY' && !ready) { ready = true; observed('native-ready'); readyResolve(); }
      else if (line) { try { assert(ready && !result); result = JSON.parse(line); } catch { fail(new Error('Unexpected owned native helper output')); } }
    }
  });
  child.stdin?.on('error', () => {});
  child.stderr.on('data', () => {}); // Never persist native UI/path error contents.
  child.once('error', () => { const error = new Error('Owned native helper could not start'); fail(error); });
  child.once('close', code => {
    closedResolve();
    if (hostFailure) fail(hostFailure);
    else if (controlFailure) fail(controlFailure);
    else if (code === 0 && ready && result) doneResolve({ ...result, ...(nativeCapture ? { native_dialog_capture: nativeCapture } : {}), ...(captureInvalid ? { native_capture_unavailable: true } : {}) });
    else { const error = new Error('Owned native Save helper failed'); fail(error); }
  });
  try {
    await bounded(Promise.race([readyPromise, done]), 'native helper readiness', timeouts.ready ?? TIMEOUT);
    const [value] = await bounded(Promise.all([done, Promise.resolve().then(() => { if (nativeFailure) throw nativeFailure; observed('action-dispatch'); return action(); }).then(value => { child.stdin?.write('ACTION_COMPLETE\n', () => {}); return value; })]), 'native Save action', timeouts.action ?? 30000);
    return value;
  } catch (error) {
    failure = hostFailure || controlFailure || error;
    if (controlInvalid) failure.native_control_observation_unavailable = true;
    if (nativePhase) failure.native_stage = nativePhase;
    if (nativePhase === 'filename-host' && nativeSubphase) failure.native_host_subphase = nativeSubphase;
    if (hostObservation) failure.native_host_observation = hostObservation;
    if (win32Observation) failure.native_win32_observation = win32Observation;
    if (win32Invalid) failure.native_win32_unavailable = true;
    if (foregroundEvidence) failure.native_foreground_evidence = foregroundEvidence;
    if (foregroundInvalid) failure.native_foreground_unavailable = true;
    if (nativeCapture) failure.native_dialog_capture = nativeCapture;
    if (captureInvalid) failure.native_capture_unavailable = true;
    if (hostFailure && (!hostObservation || evidenceInvalid)) failure.native_observation_unavailable = true;
    throw failure;
  }
  finally {
    try {
      if (child.exitCode === null) child.kill();
      await bounded(closed, 'owned helper exit', timeouts.exit ?? 5000);
    } catch (error) { if (!failure) throw error; failure.native_helper_cleanup_failed = true; }
  }
}

function nativeDialogCommand(script) {
  const args = ['-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')];
  // Every argument here is space-free; include the executable, spaces and final NUL.
  assert(['powershell.exe', ...args].join(' ').length + 1 < 32767, 'Native helper exceeds Windows command-line limit');
  return args;
}
function nativeDialog(config, binding, directory, destination, action, observeOnly = false) {
  const script = nativeDialogScript(config, binding, directory, destination, observeOnly);
  const child = spawn('powershell.exe', nativeDialogCommand(script),
    { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], timeout: 35000 });
  return withNativeHelper(child, action, {}, config.observeNativePhase);
}

async function assertSavedBytes(file, expected, timeout = 10000, observation) {
  assert(Buffer.isBuffer(expected) && expected.length > 0 && expected.length <= MAX_BYTES);
  observation ||= fileObservation(expected.length);
  const deadline = Date.now() + timeout; let previous;
  try {
    do {
      try {
        const stat = fs.lstatSync(file); observation.stat(stat);
        assert(stat.isFile() && !stat.isSymbolicLink(), 'Native saved output must be a regular file');
        assert(stat.size <= expected.length, 'Native saved file exceeded reviewed byte length');
        const stamp = `${stat.size}:${stat.mtimeMs}`;
        if (stat.size === expected.length && previous === stamp) {
          assert(fs.readFileSync(file).equals(expected), 'Native saved bytes differ from the reviewed API response');
          observation.finish('verified');
          return { bytes: expected.length, sha256: createHash('sha256').update(expected).digest('hex'), byte_equality: true, native_saved_file: true };
        }
        previous = stamp;
      } catch (error) {
        if (error.code !== 'ERR_ASSERTION') observation.error(error);
        if (!['ENOENT', 'EBUSY', 'EACCES'].includes(error.code)) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    } while (Date.now() < deadline);
    throw new Error('Native saved file did not stabilize at the reviewed byte length');
  } catch (error) {
    observation.finish('byte_check_failed');
    try { error.native_file_observation = observation.report; } catch { /* Preserve the byte-check error. */ }
    throw error;
  }
}

async function noDownloadDuring(page, action) {
  const observed = page.waitForEvent('download', { timeout: 1000 }).then(() => true, error => {
    if (error.name === 'TimeoutError') return false; throw error;
  });
  const [downloaded] = await Promise.all([observed, action()]);
  assert.equal(downloaded, false, 'Cancellation initiated a download');
}

async function finish(report, failure, { disconnect, alive, write }) {
  for (const [label, work] of [['disconnect', disconnect], ['owned_app_alive', alive]]) {
    try { report.cleanup[label] = (await bounded(Promise.resolve().then(work), label, 35000)) !== false; }
    catch (error) { report.cleanup.errors.push(label); report.passed = false; failure ||= error; }
  }
  try { write(); } catch (error) { report.passed = false; failure ||= error; }
  if (failure) throw failure;
}

function emitLocationEvidence(config, directory, expected, write = value => process.stdout.write(value)) {
  if (!config.privateLocationEvidence || !directory || !expected.length) return;
  const name = path.basename(directory);
  assert(/^local-native-exports-[A-Za-z0-9]{6}$/.test(name) && path.dirname(directory) === config.output);
  assert(expected.length <= 2 && new Set(expected.map(item => item.format)).size === expected.length);
  for (const item of expected) assert(Object.keys(item).sort().join(',') === 'bytes,format,sha256' && ['md', 'json'].includes(item.format) && Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= MAX_BYTES && /^[a-f0-9]{64}$/.test(item.sha256));
  // Python captures this bounded pipe in memory; never inherit it into CI logs.
  const line = 'OWNED_DOWNLOAD_EVIDENCE:' + JSON.stringify({ directory: name, expected });
  assert(line.length <= 4096); write(line + '\n');
}

async function main(args) {
  const config = parseArgs(args), { expectedVersion } = config;
  assert.equal(process.platform, 'win32', 'Installed WebView2 acceptance requires Windows');
  const { chromium } = require('playwright');
  // CDP close is transport-only in this pinned implementation:
  // https://github.com/microsoft/playwright/blob/v1.64.0/packages/playwright-core/src/server/chromium/chromium.ts
  assert.equal(require('playwright/package.json').version, '1.64.0');
  fs.mkdirSync(config.output, { recursive: true });
  const report = { passed: false, synthetic_only: true, installed_ui: true, installed_api: true,
    api_mocked: false, browser_launched: false, native_app_closed: false, expected_version: expectedVersion,
    surface: 'owned installed WebView2 viewport', focus_scope: 'DOM focus within the owned app',
    screenshots: [], native_dialog_captures: [], checks: [], downloads: [], native_save_attempts: [], browser_download_events: 0, diagnostic_requests: 0, page_errors: 0, external_requests: 0,
    blocked_external_requests: 0, network_observation_scope: 'After attachment, before test navigation',
    cleanup: { disconnect: false, owned_app_alive: false, errors: [] } };
  let browser, page, binding, failure, downloadObserver, syntheticVerified = false, nativeDirectory;
  const locationExpected = [];
  const read = route => readInstalledJSON(config.origin, route);
  const capture = async filename => {
    assert(syntheticVerified, 'No screenshot before exact synthetic task verification');
    assert.equal(new URL(page.url()).origin, config.origin, 'No screenshot outside the owned installed origin');
    await page.screenshot({ path: path.join(config.output, filename), timeout: TIMEOUT }); report.screenshots.push(filename);
  };
  try {
    report.phase = 'owned-attachment'; binding = verifyOwned(config); report.ownership = binding;
    const health = await read('/health'); assert.equal(health.app_version, expectedVersion);
    const task = (await read(`/api/tasks/${config.taskId}`)).task; assertSyntheticTask(task, config.taskId);
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${config.debugPort}`, { timeout: 30000, noDefaults: true });
    report.webview_version = browser.version();
    const deadline = Date.now() + TIMEOUT;
    while (!(page = selectOwnedPage(browser, config.origin))) {
      assert(Date.now() < deadline, 'Installed page did not become available');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    page.setDefaultTimeout(TIMEOUT); page.setDefaultNavigationTimeout(TIMEOUT);
    // Only reject outside-origin traffic. Actual installed API/assets are never
    // routed, replaced or mocked; blob/data downloads retain their native path.
    await page.route(url => !ownedRequest(url, config.origin), async route => {
      report.blocked_external_requests++; await route.abort('blockedbyclient');
    });
    let downloads = 0;
    page.on('download', () => { downloads++; report.browser_download_events = Math.min(1000, downloads); });
    page.on('pageerror', () => report.page_errors++);
    page.on('request', request => {
      const url = new URL(request.url());
      if (!ownedRequest(url, config.origin)) report.external_requests++;
      if (url.origin === config.origin && url.pathname === `/api/tasks/${config.taskId}/exports/diagnostics`) report.diagnostic_requests++;
    });
    report.phase = 'installed-document';
    await page.goto(`${config.origin}/web/index.html?task=${encodeURIComponent(config.taskId)}`);
    const reader = page.locator('#document'); await reader.getByRole('heading', { name: task.title, exact: true }).waitFor();
    assert.equal(await page.locator('#breadcrumb').innerText(), task.title);
    assert.match(await reader.innerText(), /SYNTHETIC_ONE/); syntheticVerified = true;
    await capture(config.startupOnly ? 'previous-startup.png' : 'installed-current-startup.png');
    report.checks.push('Installed bundled task reader displays the retained synthetic title and captions');
    if (!config.startupOnly) {
      config.captureNativeDialog = syntheticVerified;
      downloadObserver = await attachDownloadObservation(page, config.origin, bounded);
      report.page_download_observation = downloadObserver.report;
      config.observeNativePhase = phase => downloadObserver.phase(phase);
      report.phase = 'visible-diagnostic-disclosure';
      await page.locator('#taskStatus [data-task-action="diagnostics"]').click();
      const processing = page.locator('#toolsDialog[open]');
      await processing.getByText('诊断详情与安全报告', { exact: true }).click();
      const opener = processing.getByRole('button', { name: '预览安全诊断报告', exact: true });
      await opener.waitFor({ state: 'visible' }); assert(await opener.isEnabled());
      const dialog = page.locator('.task-diagnostic-export'), consent = dialog.locator('input[type=checkbox]');
      const save = dialog.getByRole('button', { name: '保存已预览报告', exact: true });
      async function preview(format, action) {
        const url = `${config.origin}/api/tasks/${config.taskId}/exports/diagnostics${format === 'json' ? '?format=json' : ''}`;
        const [response] = await Promise.all([page.waitForResponse(item => item.url() === url && item.request().method() === 'GET'), action()]);
        assert(response.ok()); const bytes = await bounded(response.body(), 'actual preview response');
        assert(bytes.length > 0 && bytes.length <= MAX_BYTES);
        const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
        await page.waitForFunction(expected => document.querySelector('.task-diagnostic-export pre')?.textContent === expected, text);
        assert.equal(await dialog.locator('select').inputValue(), format);
        assert.equal(await consent.isChecked(), false); assert.equal(await consent.isEnabled(), true); assert.equal(await save.isDisabled(), true);
        assert(!text.includes(config.taskId) && !text.includes(task.title) && !text.includes(task.page_url) && !text.includes('SYNTHETIC_ONE'));
        assert.equal(await dialog.locator('img').count(), 0);
        if (format === 'json') {
          const parsed = JSON.parse(text); assert.equal(parsed.versions.current_app, expectedVersion);
          assert.equal(parsed.versions.task_run_app, null); assert.equal(parsed.model.total_tokens, null); assert.equal(parsed.model.cost, null);
          report.versions = parsed.versions;
        } else { assert(text.includes(`当前运行版本：${expectedVersion}`)); assert.match(text, /任务运行版本：未知/); }
        return bytes;
      }
      nativeDirectory = fs.mkdtempSync(path.join(config.output, 'local-native-exports-'));
      report.native_exports_retained_locally = true;
      let expected = await preview('md', () => opener.click());
      assert.equal(downloads, 0); assert(await dialog.evaluate(node => node.contains(document.activeElement)));
      for (const format of ['md', 'json']) {
        report.phase = `preview-${format}`;
        if (format === 'json') expected = await preview(format, () => dialog.locator('select').selectOption('json'));
        assert.equal(report.diagnostic_requests, format === 'md' ? 1 : 2);
        await capture(`installed-current-${format}-preview.png`);
        await consent.check(); await save.scrollIntoViewIfNeeded(); await save.focus();
        await capture(`installed-current-${format}-save-focused.png`);
        const gets = report.diagnostic_requests;
        const destination = path.join(nativeDirectory, `learnnote-diagnostics.${format}`);
        assert.equal(fs.existsSync(destination), false);
        try { locationExpected.push({ format, bytes: expected.length, sha256: createHash('sha256').update(expected).digest('hex') }); }
        catch { report.location_evidence_unavailable = true; }
        const observation = fileObservation(expected.length);
        const attempt = { format, native_dialog_completed: false, file: observation.report };
        report.native_save_attempts.push(attempt); downloadObserver.active(format);
        try {
          const native = await nativeDialog(config, binding, nativeDirectory, destination, () => save.click());
          if (native.native_dialog_capture) {
            report.native_dialog_captures.push(native.native_dialog_capture);
            if (native.native_dialog_capture.status === 'saved') report.screenshots.push(native.native_dialog_capture.file);
          }
          if (native.native_capture_unavailable) report.native_capture_unavailable = true;
          assert.equal(native.native_dialog, true); assert.equal(native.saved, true);
          attempt.native_dialog_completed = true;
          report.downloads.push({ format, ...await assertSavedBytes(destination, expected, 10000, observation) });
        } finally {
          if (!attempt.native_dialog_completed) { observation.sample(destination); observation.finish('native_step_failed'); }
        }
        assert.equal(report.diagnostic_requests, gets, 'Save must reuse the exact cached preview bytes');
        assert.equal(await save.isDisabled(), true);
      }
      assert.equal(report.downloads.length, 2);
      report.browser_download_events = Math.min(1000, downloads);
      report.phase = 'cancel-and-focus'; downloadObserver.active('cancel');
      await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' });
      assert(await opener.evaluate(node => document.activeElement === node), 'Escape restores the visible opener');
      await preview('md', () => opener.click());
      const beforeCancel = downloads, filesBefore = fs.readdirSync(nativeDirectory).sort();
      const canceled = await nativeDialog(config, binding, nativeDirectory, '',
        () => noDownloadDuring(page, () => dialog.getByRole('button', { name: '取消导出', exact: true }).click()), true);
      assert.equal(canceled.native_popup_absent, true);
      await dialog.waitFor({ state: 'detached' }); assert.equal(downloads, beforeCancel);
      assert.deepEqual(fs.readdirSync(nativeDirectory).sort(), filesBefore);
      assert(await opener.evaluate(node => document.activeElement === node), 'Cancel restores the visible opener');
      assert.equal(report.diagnostic_requests, 3); report.cancel_no_download_observation_ms = 1000;
      await capture('installed-current-cancel-focus.png');
      report.checks.push('Visible disclosure; MD/JSON consent reset; exact cached API/native-saved-file byte equality; Cancel has no download; focus returns to opener');
    }
    assert.equal(report.page_errors, 0); assert.equal(report.external_requests, 0); assert.equal(report.blocked_external_requests, 0);
    report.passed = true; report.phase = 'complete';
  } catch (error) {
    failure = error; report.failure = error.message;
    if (error.native_stage) report.native_failure_stage = error.native_stage;
    for (const key of ['native_host_subphase', 'native_host_failure', 'native_host_observation', 'native_observation_unavailable', 'native_win32_observation', 'native_win32_unavailable', 'native_foreground_evidence', 'native_foreground_unavailable', 'native_control_failure', 'native_control_observation_unavailable']) {
      if (error[key] !== undefined) report[key] = error[key];
    }
    if (error.native_dialog_capture) {
      report.native_dialog_captures.push(error.native_dialog_capture);
      if (error.native_dialog_capture.status === 'saved') report.screenshots.push(error.native_dialog_capture.file);
    }
    if (error.native_capture_unavailable) report.native_capture_unavailable = true;
    if (error.native_foreground_evidence?.capture.status === 'saved') report.screenshots.push(error.native_foreground_evidence.capture.file);
    if (error.native_helper_cleanup_failed) report.native_helper_cleanup_failed = true;
    if (page && syntheticVerified) {
      try { await capture(config.startupOnly ? 'previous-startup-failure.png' : 'installed-current-diagnostic-failure.png'); }
      catch { report.failure_capture_unavailable = true; }
    }
  } finally {
    try { emitLocationEvidence(config, nativeDirectory, locationExpected); }
    catch { report.location_evidence_unavailable = true; }
    try { if (downloadObserver) await downloadObserver.close(); }
    catch { report.download_observation_cleanup_failed = true; }
    await finish(report, failure, {
      // connectOverCDP close disconnects only; never close the default context,
      // its pages, or issue Browser.close through CDP. Python owns normal WM_CLOSE.
      disconnect: async () => { if (!browser) return false; await browser.close(); },
      alive: async () => { if (!binding) return false; assert.deepEqual(verifyOwned(config), binding, 'Owned app/debug process changed during CDP attachment'); },
      write: () => fs.writeFileSync(path.join(config.output, config.startupOnly ? 'previous-startup-report.json' : 'installed-current-diagnostic-report.json'), JSON.stringify(report, null, 2) + '\n'),
    });
  }
}

module.exports = { parseArgs, bounded, readInstalledJSON, verifyOwned, assertSyntheticTask, selectOwnedPage, ownedRequest, validateHostFailure, validateControlFailure, validateHostObservation, validateWin32Observation, validateNativeCapture, validateForegroundEvidence, nativeDialogScript, nativeDialogCommand, withNativeHelper, assertSavedBytes, noDownloadDuring, finish, emitLocationEvidence };
if (require.main === module) main(process.argv.slice(2)).catch(error => { console.error(error); process.exitCode = 1; });
