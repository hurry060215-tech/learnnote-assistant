$ErrorActionPreference='Stop'
# Synthetic CLR contracts only. No native windows, input, UIA providers or external data.
Add-Type @'
using System; using System.Threading;
namespace System.Windows.Automation {
 public class ControlType { public static readonly ControlType Edit=new ControlType(), Button=new ControlType(), Pane=new ControlType(), ComboBox=new ControlType(); }
 public class TreeScope { public static readonly object Descendants=new object(); }
 public class Condition { public static readonly object TrueCondition=new object(); }
 public class TextPattern { public static readonly object Pattern=new object(); }
 public enum SupportedTextSelection { None, Single }
 public class Automation { public static bool Compare(object a,object b) { return Object.ReferenceEquals(a,b); } }
 public class ValuePattern { public static readonly object Pattern=new object(); }
 public class InvokePattern { public static readonly object Pattern=new object(); }
 public class AutomationElement { public static SyntheticNode FocusedElement { get { return SyntheticState.Mode=="action-focus-element" ? SyntheticState.Save : SyntheticState.Focus==3 ? SyntheticState.Edit : SyntheticState.Save; } } public static SyntheticNode FromHandle(IntPtr h) { return h.ToInt32()==4 ? SyntheticState.Combo : SyntheticState.Save; } }
}
public static class SyntheticState {
 public static string Mode; public static bool Diagnostic; public static int ValueReads, SavePatterns, HostSets, EditSets, SaveInvokes, UnicodeSends, Focus, Selections, FocusChecks, SelectionChecks;
 public static readonly Exception Failure=new InvalidOperationException("PRIVATE_original");
 public static SyntheticNode Host, Combo, Edit, Save;
 public static void Reset(string mode, string value) {
  Mode=mode; Diagnostic=false; ValueReads=0; SavePatterns=0; HostSets=0; EditSets=0; SaveInvokes=0; UnicodeSends=0; Focus=0; Selections=0; FocusChecks=0; SelectionChecks=0;
  Host=new SyntheticNode(5); Combo=new SyntheticNode(4); Edit=new SyntheticNode(3); Save=new SyntheticNode(2);
  Edit.Pattern.Info.Value=value; Edit.Pattern.Info.IsReadOnly=mode=="readonly";
  Combo.Pattern.Info.Value=mode=="host-name" ? "wrong.md" : value; Combo.Pattern.Info.IsReadOnly=mode=="host-readonly";
 }
}
public class SyntheticProperties {
 public int ProcessId { get { return 111; } }
 public int NativeWindowHandle { get; set; }
 public bool HasKeyboardFocus { get { return SyntheticState.Mode!="action-uia-focus" && NativeWindowHandle==SyntheticState.Focus; } }
 public System.Windows.Automation.ControlType ControlType { get; set; }
 public string ClassName { get; set; } public string AutomationId { get; set; }
}
public class SyntheticValueProperties {
 public int Handle; bool readOnly; string value;
 public bool IsReadOnly { get { return readOnly || SyntheticState.SelectionChecks>0 && ((Handle==3 && SyntheticState.Mode=="action-edit-readonly") || (Handle==4 && SyntheticState.Mode=="action-host-readonly")); } set { readOnly=value; } }
 public string Value { get { SyntheticState.ValueReads++; return value; } set { this.value=value; } }
}
public class SyntheticPattern {
 public int Handle;
 public void Invoke() { if (Handle!=2) throw new InvalidOperationException(); SyntheticState.SaveInvokes++; }
 public void SetValue(string value) {
  if (Handle==4) { SyntheticState.HostSets++; Info.Value=SyntheticState.Mode=="action-host-readback" ? "wrong" : value; SyntheticState.Edit.Pattern.Info.Value=SyntheticState.Mode=="action-edit-readback" ? "wrong" : value; }
  else { SyntheticState.EditSets++; Info.Value=value; }
 }
 public readonly SyntheticValueProperties Info=new SyntheticValueProperties();
 public SyntheticValueProperties Current { get { return Info; } }
}
public class SyntheticNode {
 public readonly int Handle; int reads; public readonly SyntheticPattern Pattern=new SyntheticPattern();
 public void SetFocus() { SyntheticState.Focus=SyntheticState.Mode=="action-focus-wrong" || (Handle==2 && SyntheticState.Mode=="action-save-focus") ? 9 : Handle; }
 public SyntheticNode(int h) { Handle=h; Pattern.Handle=h; Pattern.Info.Handle=h; }
 public SyntheticProperties Current { get {
  return new SyntheticProperties { NativeWindowHandle=Handle==4 && SyntheticState.Mode=="action-host-handle" ? 5 : Handle,
   ControlType=(Handle==4 || Handle==5) ? (Handle==4 && SyntheticState.Mode=="host-type" ? System.Windows.Automation.ControlType.Pane : System.Windows.Automation.ControlType.ComboBox) : Handle==3 ? System.Windows.Automation.ControlType.Edit : System.Windows.Automation.ControlType.Button,
   ClassName=Handle==5 ? "AppControlHost" : Handle==4 ? "ComboBox" : Handle==3 ? "Edit" : SyntheticState.Mode=="save-profile" ? "WrongButton" : "Button",
   AutomationId=Handle==5 ? "FileNameControlHost" : Handle==4 ? "0" : Handle==3 ? "1001" : "1" };
 } }
 public SyntheticNode[] FindAll(object scope, object condition) {
  if (SyntheticState.Diagnostic && SyntheticState.Mode=="budget") Thread.Sleep(1100);
  if (SyntheticState.Mode=="edit-zero") return new SyntheticNode[0];
  if (SyntheticState.Mode=="edit-two") return new [] { SyntheticState.Edit, SyntheticState.Edit };
  return new [] { SyntheticState.Edit };
 }
 public object GetCurrentPattern(object id) {
  if (Object.ReferenceEquals(id,System.Windows.Automation.TextPattern.Pattern)) { if (SyntheticState.Mode=="action-text-pattern") throw SyntheticState.Failure; return new SyntheticTextPattern(); }
  if (Handle==2) SyntheticState.SavePatterns++;
  if ((Handle==4 && SyntheticState.Mode=="host-pattern") || (Handle==3 && SyntheticState.Mode=="value-pattern") || (Handle==2 && SyntheticState.Mode=="invoke-pattern")) throw SyntheticState.Failure;
  return Pattern;
 }
 public bool TryGetCurrentPattern(object id, out object value) {
  if (Handle==2) SyntheticState.SavePatterns++;
  if ((Handle==4 && SyntheticState.Mode=="host-pattern") || (Handle==3 && SyntheticState.Mode=="value-pattern") || (Handle==2 && SyntheticState.Mode=="invoke-pattern")) { value=null; return false; }
  value=Pattern; return true;
 }
 public int[] GetRuntimeId() {
  reads++; if (SyntheticState.Mode=="runtime-fault" && Handle==3) throw SyntheticState.Failure;
  if (Handle==5 && SyntheticState.Mode=="action-wrapper-runtime") return new [] {Handle,2};
  if (Handle==4 && SyntheticState.Mode=="host-runtime-empty") return new int[0];
  if (Handle==4 && (SyntheticState.Mode=="action-host-runtime" || (SyntheticState.Mode=="action-after-runtime" && SyntheticState.UnicodeSends>0) || (SyntheticState.Mode=="host-runtime-race" && reads>1))) return new [] {Handle,2};
  return new [] { Handle, SyntheticState.Mode=="runtime-race" && Handle==3 && reads>1 ? 2 : 1 };
 }
}
public class SyntheticTextPattern {
 public System.Windows.Automation.SupportedTextSelection SupportedTextSelection { get { return SyntheticState.Mode=="action-selection-unsupported" ? System.Windows.Automation.SupportedTextSelection.None : System.Windows.Automation.SupportedTextSelection.Single; } }
 public SyntheticRange DocumentRange { get { return new SyntheticRange(); } }
 public SyntheticRange[] GetSelection() { SyntheticState.SelectionChecks++; if (SyntheticState.Mode=="action-selection-zero") return new SyntheticRange[0]; if (SyntheticState.Mode=="action-selection-two") return new [] {new SyntheticRange(),new SyntheticRange()}; return new [] {new SyntheticRange()}; }
}
public class SyntheticRange {
 public string GetText(int max) { return SyntheticState.Mode=="action-range-text" ? "wrong" : SyntheticState.Edit.Pattern.Info.Value; }
 public void Select() { SyntheticState.Selections++; if (SyntheticState.Mode=="action-selection-focus-race") SyntheticState.Focus=9; }
 public bool Compare(SyntheticRange range) { return SyntheticState.Mode!="action-selection-partial" && !(SyntheticState.Mode=="action-selection-race" && SyntheticState.SelectionChecks>1); }
}
public static class OwnedFilenameInput {
 public static bool Focused(IntPtr dialog,IntPtr control) { SyntheticState.FocusChecks++; return SyntheticState.Mode!="action-native-focus" && SyntheticState.Focus==control.ToInt32(); }
 public static uint SendUnicode(IntPtr dialog,IntPtr edit,string text) {
  if (SyntheticState.Mode=="action-modifier") throw new InvalidOperationException("Modifier key is pressed");
  SyntheticState.UnicodeSends++;
  if (SyntheticState.Mode=="action-partial-send") return (uint)(text.Length*2-1);
  SyntheticState.Combo.Pattern.Info.Value=SyntheticState.Mode=="action-host-readback" ? "wrong" : text;
  SyntheticState.Edit.Pattern.Info.Value=SyntheticState.Mode=="action-edit-readback" ? "wrong" : text;
  if (SyntheticState.Mode=="action-after-focus") SyntheticState.Focus=9;
  return (uint)(text.Length*2);
 }
}
public static class OwnedSave {
 public static IntPtr GetDlgItem(IntPtr h,int id) { if (h.ToInt32()==4 && id==1001) return new IntPtr(SyntheticState.Mode=="host-wrong-edit" || SyntheticState.Mode=="action-wrong-edit" ? 9 : 3); return SyntheticState.Mode=="save-missing" ? IntPtr.Zero : new IntPtr(2); }
 public static IntPtr GetParent(IntPtr h) { if (h.ToInt32()==3) return new IntPtr(SyntheticState.Mode=="host-parent" || SyntheticState.Mode=="action-parent" || (SyntheticState.Mode=="action-after-parent" && SyntheticState.UnicodeSends>0) ? 9 : 4); return new IntPtr(SyntheticState.Mode=="save-parent" ? 9 : 1); }
 public static bool IsWindow(IntPtr h) { return true; } public static int Pid(IntPtr h) { return h.ToInt32()==4 && SyntheticState.Mode=="host-owner" ? 999 : 111; }
 public static string Class(IntPtr h) { return h.ToInt32()==4 ? (SyntheticState.Mode=="host-class" ? "WrongClass" : "ComboBox") : h.ToInt32()==3 ? "Edit" : "Button"; }
 public static int GetDlgCtrlID(IntPtr h) { return h.ToInt32()==3 ? 1001 : 1; }
}
'@
function Stage([string]$name) { $script:stage=$name }
function Assert-Control($node,$parent) {
  if (([SyntheticState]::Mode -ceq 'host-ancestry' -or [SyntheticState]::Mode -ceq 'action-ancestry') -and $node.Handle -eq 4) { throw 'Bound filename ComboBox and Edit changed' }
  if ($node.Handle -eq 4 -and $parent.Handle -ne 5) { throw 'Incorrect synthetic ComboBox ancestry guard' }
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
  'invoke-pattern','runtime-fault','guard-before','guard-after','runtime-race','budget','format-fault','host-pattern','host-readonly','host-name','host-runtime-empty','host-runtime-race','host-parent','host-wrong-edit','host-class','host-type','host-owner','host-ancestry')
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
      { $_ -in @('host-readonly','host-name') } { 'Expected writable synthetic filename ComboBox'; break }
      { $_ -in @('host-runtime-empty','host-runtime-race','host-parent','host-wrong-edit','host-class','host-type','host-owner','host-ancestry') } { 'Bound filename ComboBox and Edit changed'; break }
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
$actionResults=[Collections.Generic.List[object]]::new()
$nativeSource=[IO.File]::ReadAllText((Join-Path $root 'installed-diagnostic-acceptance.cjs')).Replace("`r`n","`n")
foreach ($newline in @('lf','crlf')) {
  $text=if ($newline -ceq 'crlf') { $nativeSource.Replace("`n","`r`n") } else { $nativeSource }
  $text=$text.Replace("`r`n","`n")
  $start=$text.IndexOf('function Assert-BoundControls {'); $end=$text.IndexOf("Stage 'save-completion';",$start)
  if ($start -lt 0 -or $end -le $start) { throw 'Missing action source boundaries' }
  $action=$text.Substring($start,$end-$start)
  foreach ($mode in @('action-success','action-wrapper-runtime','action-ancestry','action-host-runtime','action-host-handle','action-parent','action-wrong-edit','action-host-readback','action-edit-readback','action-after-runtime','action-after-parent',
    'action-text-pattern','action-selection-unsupported','action-native-focus','action-uia-focus','action-focus-element','action-focus-wrong','action-range-text','action-selection-zero','action-selection-two','action-selection-partial','action-selection-focus-race','action-modifier','action-partial-send','action-after-focus','action-save-focus','action-selection-race','action-edit-readonly','action-host-readonly' )) {
    # Execute each real two-second readback timeout once; all other action cases run in both newline forms.
    if ($newline -ceq 'crlf' -and $mode -in @('action-host-readback','action-edit-readback')) { continue }
    [SyntheticState]::Reset('md-name','learnnote-diagnostics.md')
    $hostControl=[SyntheticState]::Host; $script:guardCalls=0
    . (Join-Path $root 'installed-native-save-controls.ps1')
    [SyntheticState]::Mode=$mode; $script:destinations=0
    function Assert-Destination { $script:destinations++ }
    $passed=$false; $reason='complete'; $same=$false
    try { Invoke-Expression $action; $passed=$true }
    catch {
      $exception=$_.Exception; $failureMessage=$exception.Message
      for ($i=0; $i -lt 5 -and $exception; $i++) { $failureMessage=$exception.Message; if ([Object]::ReferenceEquals($exception,[SyntheticState]::Failure)) { $same=$true; break }; $exception=$exception.InnerException }
      $reason=switch ($failureMessage) {
        'Bound filename ComboBox and Edit changed' { 'binding'; break }
        'Native filename readback differs' { 'readback'; break }
        'Bound filename input focus changed' { 'focus'; break }
        'Filename selection pattern unavailable' { 'pattern'; break }
        'Filename text range differs' { 'selection'; break }
        'Filename full selection differs' { 'selection'; break }
        'Modifier key is pressed' { 'modifier'; break }
        'Native filename input was incomplete' { 'partial'; break }
        'Bound filename became read-only' { 'readonly'; break }
        default { if ($same) { 'pattern' } else { throw } }
      }
    }
    $actionResults.Add(@{mode=$mode;newline=$newline;passed=$passed;reason=$reason;original=$same;stage=$script:stage;selections=[SyntheticState]::Selections;selection_checks=[SyntheticState]::SelectionChecks;unicode_sends=[SyntheticState]::UnicodeSends;host_sets=[SyntheticState]::HostSets;edit_sets=[SyntheticState]::EditSets;save_invokes=[SyntheticState]::SaveInvokes;destinations=$script:destinations})
  }
}
@{validation=@($results.ToArray());actions=@($actionResults.ToArray())} | ConvertTo-Json -Depth 8 -Compress
