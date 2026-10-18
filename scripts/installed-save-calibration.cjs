// Standalone synthetic WinForms calibration. This is not installed acceptance.
// Reuses the exact installed input helper; never changes WebView download behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync, spawn } = require('node:child_process');
const { bounded, nativeDialogScript, nativeDialogCommand, withNativeHelper } = require('./installed-diagnostic-acceptance.cjs');
const FORMATS = ['md', 'json'];
const payload = format => Buffer.from(format === 'md' ? '# Synthetic save calibration\n\nOwned fixture bytes.\n' : '{"synthetic":"save calibration","owned":true}\n');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const quote = value => "'" + value.replaceAll("'", "''") + "'";

// Public methods allow actual Windows negative tests without opening a dialog.
// No returned path is followed: classification only selects one of two fixed paths.
const HOST_SOURCE = String.raw`
using System; using System.IO; using System.Text; using System.Threading; using System.Windows.Forms;
public static class CalibrationHost {
 static Form form; static string root, exports; static bool busy;
 public static void DirectoryProof(string directory) {
  for (var current=new DirectoryInfo(directory); current!=null; current=current.Parent) {
   if (!current.Exists || (current.Attributes & FileAttributes.ReparsePoint)!=0) throw new InvalidOperationException();
  }
 }
 public static string Target(string directory,string format) {
  if (format!="md" && format!="json") throw new InvalidOperationException();
  return Path.Combine(directory,"learnnote-diagnostics."+format);
 }
 public static string Classify(string returned,string initial,string requested) {
  if (String.IsNullOrEmpty(returned) || !Path.IsPathRooted(returned)) return "unexpected";
  if (String.Equals(returned,requested,StringComparison.Ordinal)) return "requested";
  if (String.Equals(returned,initial,StringComparison.Ordinal)) return "initial";
  return "unexpected";
 }
 public static void WriteKnown(string category,string initial,string requested,byte[] bytes) {
  string target;
  if (category=="requested") target=requested;
  else if (category=="initial") target=initial;
  else throw new InvalidOperationException();
  DirectoryProof(Path.GetDirectoryName(target));
  // CreateNew rejects an existing file, link or directory. No overwrite fallback.
  using (var stream=new FileStream(target,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
   stream.Write(bytes,0,bytes.Length); stream.Flush(true);
  }
 }
 static void Emit(string line) { Console.Out.WriteLine(line); Console.Out.Flush(); }
 static void Save(string format) {
  if (busy) { Emit("ERROR"); return; } busy=true;
  try {
   string initial=Target(Path.Combine(root,"initial"),format), requested=Target(exports,format);
   DirectoryProof(root); DirectoryProof(Path.GetDirectoryName(initial)); DirectoryProof(exports);
   if (File.Exists(initial) || Directory.Exists(initial) || File.Exists(requested) || Directory.Exists(requested)) throw new InvalidOperationException();
   using (var dialog=new SaveFileDialog()) {
    dialog.InitialDirectory=Path.GetDirectoryName(initial);
    dialog.Filter="All files (*.*)|*.*"; dialog.RestoreDirectory=true;
    dialog.FileName=Path.GetFileName(initial);
    bool ok=dialog.ShowDialog(form)==DialogResult.OK;
    string category=ok ? Classify(dialog.FileName,initial,requested) : "cancelled";
    bool created=false;
    if (category=="requested" || category=="initial") {
     byte[] bytes=Convert.FromBase64String(format=="md" ? "${payload('md').toString('base64')}" : "${payload('json').toString('base64')}");
     WriteKnown(category,initial,requested,bytes); created=true;
    }
    Emit("{\"format\":\""+format+"\",\"dialog_ok\":"+(ok?"true":"false")+",\"returned_path\":\""+category+"\",\"created\":"+(created?"true":"false")+"}");
   }
  } catch { Emit("ERROR"); } finally { busy=false; }
 }
 [STAThread] public static void Main(string[] args) {
  try {
   if (args.Length!=2) throw new InvalidOperationException();
   root=Path.GetFullPath(args[0]); exports=Path.GetFullPath(args[1]);
   if (root!=args[0] || exports!=args[1] || Path.GetDirectoryName(exports)!=root || !Path.GetFileName(exports).StartsWith("local-native-exports-")) throw new InvalidOperationException();
   DirectoryProof(root); DirectoryProof(exports); DirectoryProof(Path.Combine(root,"initial"));
   Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
   using (form=new Form()) {
    form.Text="LearnNote - Video Learning Notes"; form.Width=640; form.Height=360;
    form.Shown+=(sender,eventArgs)=>{
     var worker=new Thread(()=>{
      try {
       string command;
       while ((command=Console.In.ReadLine())!=null) {
        if (command=="close") break;
        if (command!="md" && command!="json") { Emit("ERROR"); break; }
        string format=command; form.BeginInvoke(new Action(()=>Save(format)));
       }
       form.BeginInvoke(new Action(()=>form.Close()));
      } catch { Emit("ERROR"); }
     });
     worker.IsBackground=true; worker.Start(); Emit("READY");
    };
    Application.Run(form);
   }
   Emit("CLOSED");
  } catch { Emit("ERROR"); Environment.ExitCode=1; }
 }
}`;

function validateCase(value, format) {
  assert.deepEqual(Object.keys(value).sort(), ['created', 'dialog_ok', 'format', 'returned_path']);
  assert.equal(value.format, format); assert(FORMATS.includes(format));
  assert.equal(typeof value.dialog_ok, 'boolean'); assert.equal(typeof value.created, 'boolean');
  assert(['requested', 'initial', 'unexpected', 'cancelled'].includes(value.returned_path));
  assert.equal(value.dialog_ok, value.returned_path !== 'cancelled');
  assert.equal(value.created, ['requested', 'initial'].includes(value.returned_path));
  return value;
}

function hostProtocol(child) {
  let buffer = '', bytes = 0, ready = false, ended = false, failure, pending;
  const queue = []; let resolveClosed;
  const closed = new Promise(resolve => { resolveClosed = resolve; });
  const fail = () => { failure ||= new Error('Synthetic calibration host failed'); pending?.reject(failure); pending = null; };
  child.stdin.on('error', fail); child.stderr.on('data', () => {});
  child.on('error', fail);
  child.on('close', code => { ended = true; resolveClosed(code); if (code !== 0 || pending) fail(); });
  child.stdout.on('data', chunk => {
    bytes += chunk.length; if (bytes > 4096) { fail(); return; }
    buffer += chunk.toString('utf8'); let index;
    while ((index = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
      if (!line || line === 'ERROR') { fail(); continue; }
      if (queue.length >= 4) { fail(); continue; }
      if (pending) { const current = pending; pending = null; current.resolve(line); }
      else queue.push(line);
    }
  });
  async function next() {
    if (failure) throw failure;
    if (queue.length) return queue.shift();
    assert(!ended && !pending, 'Synthetic calibration host unavailable');
    return bounded(new Promise((resolve, reject) => { pending = { resolve, reject }; }), 'calibration host response', 15000);
  }
  return {
    async ready() { assert.equal(await next(), 'READY'); ready = true; },
    async result(format) { assert(ready); return validateCase(JSON.parse(await next()), format); },
    command(format) { assert(ready && FORMATS.includes(format) && !failure && !ended); child.stdin.write(format + '\n'); },
    async close() {
      let primary;
      try {
        if (child.exitCode === null && !ended) child.stdin.end('close\n');
        assert.equal(await bounded(closed, 'calibration normal close', 5000), 0);
        assert.equal(await next(), 'CLOSED'); assert.equal(queue.length, 0); assert.equal(buffer, '');
      } catch (error) { primary = error; }
      finally {
        if (!ended) { child.kill(); try { await bounded(closed, 'calibration owned process exit', 5000); } catch (error) { primary ||= error; } }
      }
      if (primary) throw primary;
    },
  };
}

function compileHost(root, execute = execFileSync) {
  const source = path.join(root, 'Calibration.cs'), executable = path.join(root, 'LearnNote.exe');
  fs.writeFileSync(source, HOST_SOURCE, { flag: 'wx' });
  try {
    execute('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      `$ErrorActionPreference='Stop'; Add-Type -Path ${quote(source)} -ReferencedAssemblies System.Windows.Forms,System.Drawing -OutputAssembly ${quote(executable)} -OutputType WindowsApplication`],
    { windowsHide: true, timeout: 30000, maxBuffer: 4096, stdio: ['ignore', 'pipe', 'pipe'] });
  } catch { throw new Error('Synthetic calibration compilation failed'); }
  return executable;
}
function bindHost(pid, executable, execute = execFileSync) {
  assert(Number.isInteger(pid) && pid > 0 && pid <= 0xffffffff);
  const script = `$ErrorActionPreference='Stop'; $p=Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}'; if (!$p -or $p.Name -cne 'LearnNote.exe' -or $p.ExecutablePath -cne ${quote(executable)}) { throw 'Synthetic process identity rejected' }; $p.CreationDate.ToUniversalTime().Ticks.ToString()`;
  let start;
  try { start = execute('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { encoding: 'utf8', windowsHide: true, timeout: 15000, maxBuffer: 4096 }).trim(); }
  catch { throw new Error('Synthetic calibration process binding failed'); }
  assert(/^\d{18}$/.test(start), 'Synthetic calibration start identity rejected');
  return { owned_start: start };
}
function regularBytes(file, expected) {
  const stat = fs.lstatSync(file); assert(stat.isFile() && !stat.isSymbolicLink() && stat.nlink === 1 && stat.size === expected.length);
  const actual = fs.readFileSync(file); assert.deepEqual(actual, expected);
  return { bytes: actual.length, sha256: digest(actual) };
}
async function finishCalibration(report, primary, actions) {
  for (const [name, action] of [['close', actions.close], ['retain', actions.retain], ['cleanup', actions.cleanup]]) {
    try { await action(); report[name + '_ok'] = true; }
    catch (error) { report[name + '_ok'] = false; primary ||= error; }
  }
  report.passed = !primary;
  try { await actions.write(); } catch (error) { primary ||= error; }
  if (primary) throw primary;
  return report;
}
function realDirectory(directory) {
  for (let cursor = path.resolve(directory); ; cursor = path.dirname(cursor)) {
    const stat = fs.lstatSync(cursor); assert(stat.isDirectory() && !stat.isSymbolicLink());
    assert.equal(fs.realpathSync.native(cursor).toLowerCase(), cursor.toLowerCase());
    if (path.dirname(cursor) === cursor) break;
  }
}
function prepareOutput(output) {
  fs.mkdirSync(path.dirname(output), { recursive: true }); realDirectory(path.dirname(output));
  fs.mkdirSync(output); realDirectory(output); // Fresh directory only; never overwrite prior evidence.
}
async function runCalibration(output) {
  assert.equal(process.platform, 'win32');
  prepareOutput(output);
  const report = { schema: 1, kind: 'standalone_winforms_save_calibration_not_installed_acceptance', passed: false, phase: 'compile', cases: [], captures: [] };
  let root, host, protocol, primary;
  try {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'learnnote-save-calibration-')); realDirectory(root);
    fs.mkdirSync(path.join(root, 'initial'));
    const directory = fs.mkdtempSync(path.join(root, 'local-native-exports-'));
    const executable = compileHost(root);
    report.phase = 'startup';
    host = spawn(executable, [root, directory], { windowsHide: false, stdio: ['pipe', 'pipe', 'pipe'] });
    protocol = hostProtocol(host); await protocol.ready();
    report.phase = 'binding'; const binding = bindHost(host.pid, executable);
    for (const format of FORMATS) {
      report.phase = format;
      const destination = path.join(directory, `learnnote-diagnostics.${format}`);
      const initial = path.join(root, 'initial', `learnnote-diagnostics.${format}`);
      assert(!fs.existsSync(destination) && !fs.existsSync(initial));
      const script = nativeDialogScript({ ownedPid: host.pid, captureNativeDialog: true }, binding, directory, destination);
      const helper = spawn('powershell.exe', nativeDialogCommand(script), { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], timeout: 35000 });
      let native;
      try { native = await withNativeHelper(helper, () => protocol.command(format)); }
      catch (error) { native = error; throw error; }
      finally {
        if (native?.native_dialog_capture) report.captures.push({ format, ...native.native_dialog_capture });
        if (native?.native_stage) report.native_failure_stage = native.native_stage;
      }
      assert(native.native_dialog && native.saved);
      const result = await protocol.result(format); report.cases.push(result);
      assert(result.created, 'Synthetic Save returned an unsupported destination');
      const actualPath = result.returned_path === 'requested' ? destination : initial;
      Object.assign(result, regularBytes(actualPath, payload(format)));
      result.other_destination_absent = !fs.existsSync(actualPath === destination ? initial : destination);
      assert(result.other_destination_absent);
    }
    assert(report.cases.every(item => item.returned_path === 'requested'), 'Synthetic FileName differs from the exact UIA destination');
    report.phase = 'complete';
  } catch (error) { primary = error; }
  return finishCalibration(report, primary, {
    close: async () => { if (protocol) await protocol.close(); },
    retain: () => {
      for (const item of report.captures) {
        if (item.status !== 'saved') continue;
        const oldName = `installed-current-${item.format}-native-dialog.png`;
        assert.equal(item.file, oldName);
        const file = `native-save-calibration-${item.format}-dialog.png`;
        const source = path.join(root, oldName), stat = fs.lstatSync(source);
        assert(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 16 * 1024 * 1024);
        fs.copyFileSync(source, path.join(output, file), fs.constants.COPYFILE_EXCL); item.file = file;
      }
    },
    cleanup: () => { assert(!host || host.exitCode !== null || host.signalCode !== null, 'Synthetic fixture process remains alive'); if (root) fs.rmSync(root, { recursive: true }); },
    write: () => fs.writeFileSync(path.join(output, 'native-save-calibration-report.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' }),
  });
}
module.exports = { HOST_SOURCE, payload, validateCase, hostProtocol, compileHost, bindHost, finishCalibration, prepareOutput, runCalibration };
