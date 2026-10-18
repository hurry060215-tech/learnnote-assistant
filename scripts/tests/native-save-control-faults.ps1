$ErrorActionPreference='Stop'
# Synthetic CLR contracts only. No native windows, input, UIA providers or external data.
Add-Type @'
using System; using System.Threading;
namespace System.Windows.Automation {
 public class ControlType { public static readonly ControlType Edit=new ControlType(), Button=new ControlType(), Pane=new ControlType(); }
 public class TreeScope { public static readonly object Descendants=new object(); }
 public class Condition { public static readonly object TrueCondition=new object(); }
 public class ValuePattern { public static readonly object Pattern=new object(); }
 public class InvokePattern { public static readonly object Pattern=new object(); }
 public class AutomationElement { public static SyntheticNode FromHandle(IntPtr h) { return SyntheticState.Save; } }
}
public static class SyntheticState {
 public static string Mode; public static bool Diagnostic; public static int ValueReads, SavePatterns;
 public static readonly Exception Failure=new InvalidOperationException("PRIVATE_original");
 public static SyntheticNode Host, Edit, Save;
 public static void Reset(string mode, string value) {
  Mode=mode; Diagnostic=false; ValueReads=0; SavePatterns=0;
  Host=new SyntheticNode(0); Edit=new SyntheticNode(3); Save=new SyntheticNode(2);
  Edit.Pattern.Info.Value=value; Edit.Pattern.Info.IsReadOnly=mode=="readonly";
 }
}
public class SyntheticProperties {
 public int ProcessId { get { return 111; } }
 public int NativeWindowHandle { get; set; }
 public System.Windows.Automation.ControlType ControlType { get; set; }
 public string ClassName { get; set; } public string AutomationId { get; set; }
}
public class SyntheticValueProperties {
 public bool IsReadOnly { get; set; } string value;
 public string Value { get { SyntheticState.ValueReads++; return value; } set { this.value=value; } }
}
public class SyntheticPattern {
 public readonly SyntheticValueProperties Info=new SyntheticValueProperties();
 public SyntheticValueProperties Current { get { return Info; } }
}
public class SyntheticNode {
 public readonly int Handle; int reads; public readonly SyntheticPattern Pattern=new SyntheticPattern();
 public SyntheticNode(int h) { Handle=h; }
 public SyntheticProperties Current { get {
  return new SyntheticProperties { NativeWindowHandle=Handle,
   ControlType=Handle==3 ? System.Windows.Automation.ControlType.Edit : System.Windows.Automation.ControlType.Button,
   ClassName=Handle==3 ? "Edit" : SyntheticState.Mode=="save-profile" ? "WrongButton" : "Button",
   AutomationId=Handle==3 ? "1001" : "1" };
 } }
 public SyntheticNode[] FindAll(object scope, object condition) {
  if (SyntheticState.Diagnostic && SyntheticState.Mode=="budget") Thread.Sleep(1100);
  if (SyntheticState.Mode=="edit-zero") return new SyntheticNode[0];
  if (SyntheticState.Mode=="edit-two") return new [] { SyntheticState.Edit, SyntheticState.Edit };
  return new [] { SyntheticState.Edit };
 }
 public object GetCurrentPattern(object id) {
  if (Handle==2) SyntheticState.SavePatterns++;
  if ((Handle==3 && SyntheticState.Mode=="value-pattern") || (Handle==2 && SyntheticState.Mode=="invoke-pattern")) throw SyntheticState.Failure;
  return Pattern;
 }
 public bool TryGetCurrentPattern(object id, out object value) {
  if (Handle==2) SyntheticState.SavePatterns++;
  if ((Handle==3 && SyntheticState.Mode=="value-pattern") || (Handle==2 && SyntheticState.Mode=="invoke-pattern")) { value=null; return false; }
  value=Pattern; return true;
 }
 public int[] GetRuntimeId() {
  reads++; if (SyntheticState.Mode=="runtime-fault" && Handle==3) throw SyntheticState.Failure;
  return new [] { Handle, SyntheticState.Mode=="runtime-race" && Handle==3 && reads>1 ? 2 : 1 };
 }
}
public static class OwnedSave {
 public static IntPtr GetDlgItem(IntPtr h,int id) { return SyntheticState.Mode=="save-missing" ? IntPtr.Zero : new IntPtr(2); }
 public static IntPtr GetParent(IntPtr h) { return new IntPtr(SyntheticState.Mode=="save-parent" ? 9 : 1); }
 public static bool IsWindow(IntPtr h) { return true; } public static int Pid(IntPtr h) { return 111; }
 public static string Class(IntPtr h) { return h.ToInt32()==3 ? "Edit" : "Button"; }
 public static int GetDlgCtrlID(IntPtr h) { return h.ToInt32()==3 ? 1001 : 1; }
}
'@
function Stage([string]$name) { $script:stage=$name }
function Assert-Control($node,$parent) {
  if (([SyntheticState]::Mode -ceq 'edit-control' -and $node.Handle -eq 3) -or
      ([SyntheticState]::Mode -ceq 'save-control' -and $node.Handle -eq 2)) { throw [SyntheticState]::Failure }
}
function Assert-Dialog($handle) {
  $script:guardCalls++; [SyntheticState]::Diagnostic=$true
  if (([SyntheticState]::Mode -ceq 'guard-before' -and $script:guardCalls -eq 1) -or
      ([SyntheticState]::Mode -ceq 'guard-after' -and $script:guardCalls -eq 2)) { throw [SyntheticState]::Failure }
}
$root=Split-Path $PSScriptRoot
$results=[Collections.Generic.List[object]]::new()
$cases=@('md-name','md-stem','json-name','json-stem','wrong-stem','wrong-extension','wrong-case','path','empty','readonly',
  'edit-zero','edit-two','edit-control','value-pattern','save-missing','save-parent','save-control','save-profile',
  'invoke-pattern','runtime-fault','guard-before','guard-after','runtime-race','budget','format-fault')
foreach ($mode in $cases) {
  $json=$mode.StartsWith('json-'); $filename=if ($json) { 'learnnote-diagnostics.json' } else { 'learnnote-diagnostics.md' }
  $name=switch ($mode) {
    { $_ -in @('md-stem','json-stem') } { 'learnnote-diagnostics'; break }
    'wrong-stem' { 'learnnote-diagnostics-extra.md'; break }
    'wrong-extension' { 'learnnote-diagnostics.json'; break }
    'wrong-case' { 'LearnNote-diagnostics.md'; break }
    'path' { 'C:\PRIVATE\learnnote-diagnostics.md'; break }
    'empty' { ''; break }
    { $_ -in @('guard-before','guard-after','runtime-race','budget','format-fault') } { 'PRIVATE_rejected'; break }
    default { $filename }
  }
  [SyntheticState]::Reset($mode,$name)
  $c=@{observer=(Join-Path $root 'installed-native-dialog-observation.ps1');pid=111;destination=('D:\owned\local-native-exports-fresh\'+$filename)}
  $hostControl=[SyntheticState]::Host; $element=[object]::new(); $dialog=[IntPtr]1
  $all=[Windows.Automation.Condition]::TrueCondition; $desc=[Windows.Automation.TreeScope]::Descendants
  $script:stage=$null; $script:guardCalls=0; $passed=$false; $same=$false; $primaryPreserved=$false
  $output=[IO.StringWriter]::new(); $console=[Console]::Out; [Console]::SetOut($output)
  if ($mode -ceq 'format-fault') { function ConvertTo-Json { throw [SyntheticState]::Failure } }
  try { . (Join-Path $root 'installed-native-save-controls.ps1'); $passed=$true }
  catch {
    $exception=$_.Exception
    for ($i=0; $i -lt 5 -and $exception; $i++) {
      if ([Object]::ReferenceEquals($exception,[SyntheticState]::Failure)) { $same=$true; break }
      $exception=$exception.InnerException
    }
    $expected=switch ($mode) {
      { $_ -in @('edit-zero','edit-two') } { 'Ambiguous native filename edit'; break }
      { $_ -in @('save-missing','save-parent') } { 'Expected direct native Save button'; break }
      'save-profile' { 'Unexpected native Save control'; break }
      default { 'Expected writable synthetic export filename' }
    }
    $primaryPreserved=$same -or $_.Exception.Message -ceq $expected
  } finally {
    [Console]::SetOut($console)
    if ($mode -ceq 'format-fault') { Remove-Item Function:ConvertTo-Json }
  }
  $text=$output.ToString().Trim(); $output.Dispose(); $metadata=$null
  if ($text) {
    if (!$text.StartsWith('CONTROLFAIL:') -or $text.Contains('PRIVATE_')) { throw 'Unsafe control evidence' }
    $metadata=$text.Substring(12) | ConvertFrom-Json
  }
  $results.Add(@{mode=$mode;passed=$passed;stage=$script:stage;original=$same;primary_preserved=$primaryPreserved;metadata=$metadata;
    save_patterns=[SyntheticState]::SavePatterns;value_reads=[SyntheticState]::ValueReads;guard_calls=$script:guardCalls})
}
@($results.ToArray()) | ConvertTo-Json -Depth 8 -Compress
