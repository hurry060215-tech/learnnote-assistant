# Exact initial synthetic name only; all destination/ownership/input guards remain separate.
function Test-InitialNativeFilename([string]$Name, [string]$Destination) {
  $expected=[IO.Path]::GetFileName($Destination)
  return $expected -cin @('learnnote-diagnostics.md','learnnote-diagnostics.json') -and
    ($Name -ceq $expected -or $Name -ceq [IO.Path]::GetFileNameWithoutExtension($expected))
}

# Failure-only read-only facts for both controls. No values, names, paths or HWNDs are emitted.
# The 1000 ms budget is cooperative; blocking calls retain the existing helper watchdog.
function Get-OwnedSaveControlEvidence($Context, [scriptblock]$DialogGuard, [scriptblock]$ControlGuard) {
  $clock=[Diagnostics.Stopwatch]::StartNew(); $phase='guard-before'; $reason='exception'; $exceptionType=$null
  $editFacts=$null; $saveFacts=$null; $status='unavailable'; $bindings=[Collections.Generic.List[object]]::new()
  try {
    [void](& $DialogGuard $Context)
    foreach ($role in @('edit','save')) {
      if ($clock.ElapsedMilliseconds -ge 1000) { $reason='budget'; throw [TimeoutException]::new('Evidence budget') }
      $phase=$role
      $facts=@{phase='query';reason='exception';exception_type=$null;count=$null;count_capped=$false;
        control_valid=$null;native_identity=$null;pattern_available=$null;runtime_present=$null;runtime_stable=$null;
        read_only=$null;expected_basename=$null;expected_stem=$null;handle_present=$null;direct_child=$null;profile_matches=$null}
      try {
        $node=$null
        if ($role -ceq 'edit') {
          $matches=@($Context.host.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) | Where-Object {
            $_.Current.ControlType -eq [Windows.Automation.ControlType]::Edit -and $_.Current.ClassName -ceq 'Edit' -and $_.Current.AutomationId -ceq '1001'
          })
          $facts.count=[Math]::Min(64,$matches.Count); $facts.count_capped=$matches.Count -gt 64; $facts.phase='count'
          if ($matches.Count -eq 1) { $node=$matches[0] }
        } else {
          $handle=[OwnedSave]::GetDlgItem($Context.dialog,1)
          $facts.handle_present=$handle -ne [IntPtr]::Zero
          $facts.direct_child=$facts.handle_present -and [OwnedSave]::GetParent($handle) -eq $Context.dialog
          $facts.phase='handle'
          if ($facts.direct_child) { $node=[Windows.Automation.AutomationElement]::FromHandle($handle) }
        }
        if ($null -eq $node) { $facts.reason='rejected' }
        else {
          $facts.phase='control'; $facts.control_valid=$false
          [void](& $ControlGuard $node $Context.element); $facts.control_valid=$true
          $runtime=@($node.GetRuntimeId()); $facts.runtime_present=$runtime.Count -gt 0
          if (!$facts.runtime_present) { throw [InvalidOperationException]::new('Unavailable runtime identity') }
          $bindings.Add(@{node=$node;runtime=($runtime -join ',');facts=$facts})
          $current=$node.get_Current(); $native=[IntPtr]$current.get_NativeWindowHandle()
          $facts.native_identity=$native -ne [IntPtr]::Zero -and [OwnedSave]::IsWindow($native) -and [OwnedSave]::Pid($native) -eq $Context.pid -and
            [OwnedSave]::Class($native) -ceq $(if ($role -ceq 'edit') { 'Edit' } else { 'Button' }) -and
            [OwnedSave]::GetDlgCtrlID($native) -eq $(if ($role -ceq 'edit') { 1001 } else { 1 })
          if ($role -ceq 'save') {
            $facts.native_identity=$facts.native_identity -and $native -eq $handle
            $facts.profile_matches=$current.get_ControlType() -eq [Windows.Automation.ControlType]::Button -and
              $current.get_ClassName() -ceq 'Button' -and $current.get_AutomationId() -ceq '1'
          }
          $facts.phase='pattern'; $pattern=$null
          $patternId=if ($role -ceq 'edit') { [Windows.Automation.ValuePattern]::Pattern } else { [Windows.Automation.InvokePattern]::Pattern }
          $facts.pattern_available=[bool]$node.TryGetCurrentPattern($patternId,[ref]$pattern)
          if ($facts.pattern_available -and $role -ceq 'edit') {
            $facts.phase='value'; $properties=$pattern.get_Current()
            $readOnly=$properties.get_IsReadOnly(); $initial=$properties.get_Value()
            if ($readOnly -isnot [bool] -or $initial -isnot [string]) { throw [InvalidOperationException]::new('Invalid pattern properties') }
            $facts.read_only=$readOnly
            $facts.expected_basename=$initial -ceq [IO.Path]::GetFileName($Context.destination)
            $facts.expected_stem=$initial -ceq [IO.Path]::GetFileNameWithoutExtension($Context.destination)
          }
          $facts.phase='complete'; $facts.reason='complete'
        }
      } catch {
        if ($facts.control_valid -eq $false) { throw }
        $facts.exception_type=ConvertTo-SafeNativeException $_.Exception
      }
      if ($role -ceq 'edit') { $editFacts=$facts } else { $saveFacts=$facts }
      [void](& $DialogGuard $Context)
    }
    $phase='guard-after'; [void](& $DialogGuard $Context)
    foreach ($binding in $bindings) {
      [void](& $ControlGuard $binding.node $Context.element)
      if (($binding.node.GetRuntimeId() -join ',') -cne $binding.runtime) { $reason='runtime-changed'; throw [InvalidOperationException]::new('Changed runtime identity') }
      $binding.facts.runtime_stable=$true
    }
    [void](& $DialogGuard $Context)
    if ($clock.ElapsedMilliseconds -ge 1000) { $reason='budget'; throw [TimeoutException]::new('Evidence budget') }
    $status='complete'; $phase='complete'; $reason='complete'
  } catch {
    $exceptionType=ConvertTo-SafeNativeException $_.Exception
    $editFacts=$null; $saveFacts=$null
  }
  return @{status=$status;phase=$phase;reason=$reason;exception_type=$exceptionType;
    elapsed_ms=[int][Math]::Min(35000,$clock.ElapsedMilliseconds);edit=$editFacts;save=$saveFacts}
}

# The editable ComboBox provider also notifies its parent of a value change.
# Bind that provider to the already selected inner Edit; never substitute a target.
function Assert-FilenameNativeHandles {
  if ($filenameComboHandle -eq [IntPtr]::Zero -or $filenameEditHandle -eq [IntPtr]::Zero -or
      ![OwnedSave]::IsWindow($filenameComboHandle) -or ![OwnedSave]::IsWindow($filenameEditHandle) -or
      [OwnedSave]::Pid($filenameComboHandle) -ne $c.pid -or [OwnedSave]::Pid($filenameEditHandle) -ne $c.pid -or
      [OwnedSave]::Class($filenameComboHandle) -cne 'ComboBox' -or [OwnedSave]::Class($filenameEditHandle) -cne 'Edit' -or
      [OwnedSave]::GetDlgCtrlID($filenameEditHandle) -ne 1001 -or
      [OwnedSave]::GetParent($filenameEditHandle) -ne $filenameComboHandle -or
      [OwnedSave]::GetDlgItem($filenameComboHandle,1001) -ne $filenameEditHandle) { throw 'Bound filename ComboBox and Edit changed' }
}
function Assert-FilenameHostBinding {
  Assert-Control $hostControl $element; Assert-Control $edit $hostControl; Assert-Control $filenameCombo $hostControl
  Assert-FilenameNativeHandles
  $properties=$hostControl.get_Current(); $comboProperties=$filenameCombo.get_Current(); $editProperties=$edit.get_Current()
  if ($properties.get_ControlType() -ne [Windows.Automation.ControlType]::ComboBox -or
      $properties.get_ClassName() -cne 'AppControlHost' -or $properties.get_AutomationId() -cne 'FileNameControlHost' -or
      $comboProperties.get_ControlType() -ne [Windows.Automation.ControlType]::ComboBox -or
      [IntPtr]$comboProperties.get_NativeWindowHandle() -ne $filenameComboHandle -or
      [IntPtr]$editProperties.get_NativeWindowHandle() -ne $filenameEditHandle -or
      !$filenameHostRuntime -or ($hostControl.GetRuntimeId() -join ',') -cne $filenameHostRuntime -or
      !$filenameComboRuntime -or ($filenameCombo.GetRuntimeId() -join ',') -cne $filenameComboRuntime) { throw 'Bound filename ComboBox and Edit changed' }
}

# Unicode input only after exact owned edit focus and full selection are proven.
function Initialize-FilenameInput {
  Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class OwnedFilenameInput {
 [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk,scan; public uint flags,time; public UIntPtr extra; }
 [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int x,y; public uint data,flags,time; public UIntPtr extra; }
 [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public KEYBDINPUT key; [FieldOffset(0)] public MOUSEINPUT mouse; }
 [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION value; }
 [StructLayout(LayoutKind.Sequential)] struct RECT { public int left,top,right,bottom; }
 [StructLayout(LayoutKind.Sequential)] struct GUIINFO { public uint size,flags; public IntPtr active,focus,capture,menuOwner,moveSize,caret; public RECT rect; }
 [DllImport("user32.dll")] static extern bool GetGUIThreadInfo(uint thread,ref GUIINFO info);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint count,INPUT[] inputs,int size);
 public static bool Focused(IntPtr dialog,IntPtr control) {
  var info=new GUIINFO(); info.size=(uint)Marshal.SizeOf(typeof(GUIINFO));
  return dialog!=IntPtr.Zero && control!=IntPtr.Zero && GetForegroundWindow()==dialog && GetGUIThreadInfo(0,ref info) && info.active==dialog && info.focus==control;
 }
 public static INPUT[] Build(string text) {
  if (String.IsNullOrEmpty(text) || text.Length>1024) throw new InvalidOperationException("Invalid bounded input");
  var inputs=new INPUT[text.Length*2];
  for (int i=0;i<text.Length;i++) {
   if (Char.IsControl(text[i])) throw new InvalidOperationException("Invalid bounded input");
   for (int up=0;up<2;up++) { inputs[i*2+up].type=1; inputs[i*2+up].value.key.scan=text[i]; inputs[i*2+up].value.key.flags=(uint)(4+up*2); }
  }
  return inputs;
 }
 public static uint SendUnicode(IntPtr dialog,IntPtr edit,string text) {
  var inputs=Build(text);
  if (!Focused(dialog,edit)) throw new InvalidOperationException("Filename focus changed");
  foreach (int key in new [] {16,17,18,91,92}) if ((GetAsyncKeyState(key)&0x8000)!=0) throw new InvalidOperationException("Modifier key is pressed");
  return SendInput((uint)inputs.Length,inputs,Marshal.SizeOf(typeof(INPUT)));
 }
}
'@
}
function Assert-FilenameInputFocus($node,[IntPtr]$handle) {
  Assert-Dialog $dialog; Assert-BoundControls; Assert-Destination
  if (![OwnedFilenameInput]::Focused($dialog,$handle) -or !$node.get_Current().get_HasKeyboardFocus() -or
      ![Windows.Automation.Automation]::Compare([Windows.Automation.AutomationElement]::get_FocusedElement(),$node)) { throw 'Bound filename input focus changed' }
}
function Assert-FilenameFullSelection($textPattern,$range,[string]$initial) {
  if ($value.get_Current().get_IsReadOnly() -or $hostValue.get_Current().get_IsReadOnly()) { throw 'Bound filename became read-only' }
  $selection=@($textPattern.GetSelection())
  if ($selection.Count -ne 1 -or !$selection[0].Compare($range) -or $selection[0].GetText(1024) -cne $initial -or
      $value.get_Current().get_Value() -cne $initial) { throw 'Filename full selection differs' }
}
function Set-OwnedFilenameText {
  Stage 'filename-focus'
  $textPattern=$edit.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern)
  if ($textPattern.SupportedTextSelection -ne [Windows.Automation.SupportedTextSelection]::Single) { throw 'Filename selection pattern unavailable' }
  Assert-Dialog $dialog; Assert-BoundControls; Assert-Destination; $edit.SetFocus()
  Assert-FilenameInputFocus $edit $filenameEditHandle
  Stage 'filename-select'
  $range=$textPattern.DocumentRange; $initial=$value.get_Current().get_Value()
  if (!(Test-InitialNativeFilename $initial $c.destination) -or $range.GetText(1024) -cne $initial) { throw 'Filename text range differs' }
  $range.Select(); Assert-FilenameInputFocus $edit $filenameEditHandle
  Assert-FilenameFullSelection $textPattern $range $initial
  Stage 'filename-type'
  Assert-FilenameInputFocus $edit $filenameEditHandle
  Assert-FilenameFullSelection $textPattern $range $initial
  if ([OwnedFilenameInput]::SendUnicode($dialog,$filenameEditHandle,$c.destination) -ne $c.destination.Length*2) { throw 'Native filename input was incomplete' }
  Stage 'filename-readback'
  $clock=[Diagnostics.Stopwatch]::StartNew()
  do {
    Assert-FilenameInputFocus $edit $filenameEditHandle
    if ($hostValue.get_Current().get_Value() -ceq $c.destination -and $value.get_Current().get_Value() -ceq $c.destination) { break }
    if ($clock.ElapsedMilliseconds -ge 2000) { throw 'Native filename readback differs' }
    Start-Sleep -Milliseconds 25 # Conditional readback wait only; never resend input.
  } while ($true)
  Stage 'save-focus'
  Assert-Dialog $dialog; Assert-BoundControls; Assert-Destination; $button.SetFocus()
  Assert-FilenameInputFocus $button $buttonHandle
  if ($hostValue.get_Current().get_Value() -cne $c.destination -or $value.get_Current().get_Value() -cne $c.destination) { throw 'Native filename readback differs' }
}

# Dot-sourced into the existing helper scope; successful validation retains its original variables.
$controlSubphase='edit-query'
try {
Stage 'filename-edit';
$controlSubphase='edit-query';
$edits=@($hostControl.FindAll($desc,$all) | Where-Object { $_.Current.ControlType -eq [Windows.Automation.ControlType]::Edit -and $_.Current.ClassName -ceq 'Edit' -and $_.Current.AutomationId -ceq '1001' });
$controlSubphase='edit-count';
if ($edits.Count -ne 1) { throw 'Ambiguous native filename edit' }; $edit=$edits[0]; $controlSubphase='edit-control'; Assert-Control $edit $element;
$controlSubphase='edit-value-pattern';
$value=$edit.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern);
$controlSubphase='edit-initial-name';
if ($value.Current.IsReadOnly -or !(Test-InitialNativeFilename $value.Current.Value $c.destination)) { throw 'Expected writable synthetic export filename' }
$controlSubphase='edit-host-binding';
$filenameEditHandle=[IntPtr]$edit.get_Current().get_NativeWindowHandle();
$filenameComboHandle=[OwnedSave]::GetParent($filenameEditHandle);
Assert-FilenameNativeHandles;
$filenameCombo=[Windows.Automation.AutomationElement]::FromHandle($filenameComboHandle);
$filenameHostRuntime=$hostControl.GetRuntimeId() -join ','; $filenameComboRuntime=$filenameCombo.GetRuntimeId() -join ',';
Assert-FilenameHostBinding;
$controlSubphase='edit-host-value-pattern';
$hostValue=$filenameCombo.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern);
$controlSubphase='edit-host-initial-name';
if ($hostValue.Current.IsReadOnly -or !(Test-InitialNativeFilename $hostValue.Current.Value $c.destination)) { throw 'Expected writable synthetic filename ComboBox' }
Stage 'save-button';
$controlSubphase='save-handle';
$buttonHandle=[OwnedSave]::GetDlgItem($dialog,1);
if ($buttonHandle -eq [IntPtr]::Zero -or [OwnedSave]::GetParent($buttonHandle) -ne $dialog) { throw 'Expected direct native Save button' }
$controlSubphase='save-control';
$button=[Windows.Automation.AutomationElement]::FromHandle($buttonHandle); Assert-Control $button $element;
$controlSubphase='save-profile';
if ($button.Current.ControlType -ne [Windows.Automation.ControlType]::Button -or $button.Current.ClassName -cne 'Button' -or $button.Current.AutomationId -cne '1') { throw 'Unexpected native Save control' }
$controlSubphase='save-invoke-pattern';
$invoke=$button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern);
$controlSubphase='runtime-ids';
$editRuntime=$edit.GetRuntimeId() -join ','; $buttonRuntime=$button.GetRuntimeId() -join ',';
} catch {
  $original=$_
  try {
    . $c.observer
    $context=@{host=$hostControl;element=$element;dialog=$dialog;pid=$c.pid;destination=$c.destination}
    $evidence=Get-OwnedSaveControlEvidence $context { param($x) Assert-Dialog $x.dialog } { param($node,$parent) Assert-Control $node $parent }
    $details=@{subphase=$controlSubphase;observation=$evidence}
    [Console]::Out.WriteLine('CONTROLFAIL:'+($details | ConvertTo-Json -Depth 5 -Compress)); [Console]::Out.Flush()
  } catch { } # Evidence cannot replace the original strict rejection.
  throw $original
}
