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

# Action evidence records only comparisons made by the original guards. It never
# retries an action or reads a raw value into the report. A failed predicate may
# throw before its result exists, so null means not observed, never false.
function Set-InputPredicate([string]$Name) {
  if ($null -ne $script:inputFacts) { $script:inputFacts.predicate=$Name }
}
function Start-InputEvidence {
  $script:inputClock=$null
  $script:inputFacts=@{predicate='dialog-guard';expected_events=$c.destination.Length*2;sent_events=$null;
    native_focus=$null;uia_focus=$null;uia_focused_element=$null;
    readback_iterations=0;readback_elapsed_ms=$null;host_matches=$null;edit_matches=$null;readback_timeout=$false}
}
# Read-only exact-process window observations: count <=64, entries <=8, owners <=16.
# The 500 ms observation budget is cooperative; the existing process watchdog remains.
# Same-process structural evidence is distinct from root-owned pixel eligibility.
# Never invoke an action guard or read a title/value while identifying extra windows.
function Get-InputPopupState($Binding, [IntPtr]$Window) {
  $state=@{handle=$Window;exists=$false;visible=$null;pid_matches=$null;cls=$null;owners=@();owner_category='unavailable';reason='exception'}
  $state.exists=[OwnedSave]::IsWindow($Window)
  if (!$state.exists) { $state.reason='window-dead'; return $state }
  $state.pid_matches=([OwnedSave]::Pid($Window) -eq $Binding.config.pid)
  if (!$state.pid_matches) { $state.reason='window-foreign'; return $state }
  $state.visible=[OwnedSave]::IsWindowVisible($Window)
  if (!$state.visible) { $state.reason='window-hidden'; return $state }
  # Class is a bounded primitive of this verified same-PID HWND, not pixel permission.
  $state.cls=[OwnedSave]::Class($Window)
  if ([string]::IsNullOrEmpty($state.cls)) { throw 'Window class unavailable' }
  $owners=[Collections.Generic.List[IntPtr]]::new(); $seen=[Collections.Generic.HashSet[IntPtr]]::new(); [void]$seen.Add($Window)
  $cursor=[OwnedSave]::GetWindow($Window,4)
  if ($Window -eq $Binding.root) {
    $state.owner_category=if ($cursor -eq [IntPtr]::Zero) { 'root' } else { 'root-changed' }
  } else {
    $state.owner_category='owner-limit'
    for ($depth=0; $depth -lt 16; $depth++) {
      if ($cursor -eq [IntPtr]::Zero) { $state.owner_category='ownerless'; break }
      if (![OwnedSave]::IsWindow($cursor)) { $state.owner_category='owner-dead'; break }
      if ([OwnedSave]::Pid($cursor) -ne $Binding.config.pid) { $state.owner_category='owner-foreign'; break }
      if (!$seen.Add($cursor)) { $state.owner_category='owner-cycle'; break }
      $owners.Add($cursor)
      if ($cursor -eq $Binding.root) { $state.owner_category='root'; break }
      $cursor=[OwnedSave]::GetWindow($cursor,4)
    }
  }
  $state.owners=$owners.ToArray(); $state.reason='verified'; return $state
}
function Test-InputPopupState($First, $Second) {
  foreach ($key in @('handle','exists','visible','pid_matches','cls','owner_category','reason')) {
    if ($First[$key] -cne $Second[$key]) { return $false }
  }
  return (($First.owners -join ',') -ceq ($Second.owners -join ','))
}
function Get-InputPopupTopology($Binding, $Proofs=$null) {
  $c=$Binding.config; $root=$Binding.root; $rootClass=$Binding.rootClass
  $clock=[Diagnostics.Stopwatch]::StartNew(); $reason='root-before'; $nodes=@(); $count=$null; $dropped=$null; $stable=$null
  $candidates=[Collections.Generic.List[object]]::new()
  if ($null -ne $Proofs) { $Proofs.Clear() }
  try {
    Assert-Root
    $reason='enumeration'; $before=@([OwnedSave]::Visible($c.pid))
    if ($before.Count -gt 64) { $reason='limit'; throw 'Owned popup count exceeded' }
    $count=$before.Count; $dropped=[Math]::Max(0,$count-8)
    foreach ($window in @($before | Select-Object -First 8)) {
      $role=if ($window -eq $root) { 'root' } elseif ($window -eq $Binding.dialog) { 'save' } else { 'same-process' }
      $node=@{role=$role;reason='exception';pid_matches=$null;visible=$null;cls=$null;owner_category='unavailable';owners=@();pixel_eligible=$false}
      try {
        if ($clock.ElapsedMilliseconds -ge 500) { $node.reason='budget' }
        else {
          $first=Get-InputPopupState $Binding $window; $second=Get-InputPopupState $Binding $window
          if (!(Test-InputPopupState $first $second)) { $node.reason='window-replaced' }
          else {
            $node.reason=$first.reason; $node.pid_matches=$first.pid_matches; $node.visible=$first.visible
            $node.cls=if ($first.cls -ceq 'Auto-Suggest Dropdown') { 'Auto-Suggest Dropdown' } elseif ($null -ne $first.cls) { ConvertTo-SafeNativeToken $first.cls } else { $null }
            $node.owner_category=$first.owner_category
            $node.owners=@($first.owners | ForEach-Object { if ($_ -eq $root) {'root'} elseif ($_ -eq $Binding.dialog) {'save'} else {'same-process'} })
            $node.pixel_eligible=($role -ceq 'same-process' -and $first.reason -ceq 'verified' -and $first.owner_category -ceq 'root')
            if ($node.pixel_eligible) { $candidates.Add(@{index=$nodes.Count;binding=$Binding;state=$first}) }
          }
        }
      } catch { $node=@{role=$role;reason='exception';pid_matches=$null;visible=$null;cls=$null;owner_category='unavailable';owners=@();pixel_eligible=$false} } # Keep verified peers.
      $nodes+=,$node
    }
    $reason='enumeration'; $after=@([OwnedSave]::Visible($c.pid))
    $reason='root-after'; Assert-Root
    $stable=($before.Count -eq $after.Count -and (($before | Sort-Object) -join ',') -ceq (($after | Sort-Object) -join ','))
    $reason=if (!$stable) {'set-changed'} elseif ($clock.ElapsedMilliseconds -ge 500) {'budget'} else {'complete'}
    if ($null -ne $Proofs) { foreach ($proof in $candidates) { $Proofs.Add($proof) } }
  } catch { $nodes=@(); $count=$null; $dropped=$null; $stable=$null }
  return @{status=$(if ($null -eq $count) {'unavailable'} elseif ($reason -ceq 'complete') {'complete'} else {'partial'});reason=$reason;
    elapsed_ms=[int][Math]::Min(35000,$clock.ElapsedMilliseconds);count=$count;dropped=$dropped;set_stable=$stable;nodes=$nodes}
}
function Assert-InputPopupCapture($Proof) {
  $c=$Proof.binding.config; $root=$Proof.binding.root; $rootClass=$Proof.binding.rootClass
  Assert-Root
  # This independent foreground proof has no exact visible-window-count predicate.
  Assert-OwnedForegroundEvidence $Proof.foreground
  $current=Get-InputPopupState $Proof.binding $Proof.state.handle
  if ($current.reason -cne 'verified' -or $current.owner_category -cne 'root' -or
      !(Test-InputPopupState $Proof.state $current)) { throw 'Owned extra-window capture identity changed' }
  Assert-Root
}
function Write-InputPopupCaptures($Binding, $Proofs, [string]$Directory, [string]$Destination) {
  $slot=0
  foreach ($proof in @($Proofs | Select-Object -First 3)) {
    $slot++; $capture=@{status='unavailable';reason='guard-before';file=$null;width=$null;height=$null}
    try {
      $foreground=[OwnedSave]::GetForegroundWindow()
      $proof.foreground=@{binding=$Binding;foreground=$foreground;state=(Get-OwnedForegroundState $Binding $foreground)}
      $capture=Save-OwnedDialogCapture -Dialog $proof.state.handle -Directory $Directory -Destination $Destination `
        -Surface ('popup'+$slot) -GuardContext $proof -Guard { param($boundProof) Assert-InputPopupCapture $boundProof }
    } catch { }
    try {
      [Console]::Out.WriteLine('POPUPCAPTURE:'+(@{node_index=$proof.index;slot=$slot;capture=$capture} | ConvertTo-Json -Depth 5 -Compress)); [Console]::Out.Flush()
    } catch { }
  }
}

function Write-InputFailure($Original) {
  # Each diagnostic is independent; neither formatting nor capture can replace
  # the exact original error. All capture input has its own before/after proof.
  try {
    . $c.observer
    if ($script:inputClock) { $script:inputFacts.readback_elapsed_ms=[int][Math]::Min(35000,$script:inputClock.ElapsedMilliseconds) }
    $bound=@{config=@{pid=$c.pid;start=$c.start};root=$root;rootClass=$rootClass;dialog=$dialog}
    $details=@{action=$script:inputFacts;exception_type=(ConvertTo-SafeNativeException $Original.Exception);
      guard_failure=(Get-SafeNativeGuardFailure $Original { Get-OwnedDialogIdentityFacts $bound })}
    [Console]::Out.WriteLine('INPUTFAIL:'+($details | ConvertTo-Json -Depth 6 -Compress)); [Console]::Out.Flush()
  } catch { }
  try {
    . $c.observer
    $bound=@{config=@{pid=$c.pid;start=$c.start};root=$root;rootClass=$rootClass;dialog=$dialog}
    $popupProofs=[Collections.Generic.List[object]]::new()
    $topology=Get-InputPopupTopology $bound $popupProofs
    [Console]::Out.WriteLine('POPUPS:'+($topology | ConvertTo-Json -Depth 5 -Compress)); [Console]::Out.Flush()
  } catch { }
  if ($c.capture) {
    try {
      . $c.observer
      . (Join-Path (Split-Path $c.observer) 'installed-native-dialog-capture.ps1')
      . (Join-Path (Split-Path $c.observer) 'installed-native-foreground-evidence.ps1')
      $bound=@{config=@{pid=$c.pid;start=$c.start};root=$root;rootClass=$rootClass;dialog=$dialog}
      if ($popupProofs) { Write-InputPopupCaptures $bound $popupProofs $c.directory $c.destination }
      $foregroundEvidence=Get-OwnedForegroundEvidence $bound $c.directory $c.destination
      [Console]::Out.WriteLine('FOREGROUND:'+($foregroundEvidence | ConvertTo-Json -Depth 8 -Compress)); [Console]::Out.Flush()
    } catch { }
  }
}

# The editable ComboBox provider also notifies its parent of a value change.
# Bind that provider to the already selected inner Edit; never substitute a target.
function Assert-FilenameNativeHandles {
  Set-InputPredicate 'native-handles'
  if ($filenameComboHandle -eq [IntPtr]::Zero -or $filenameEditHandle -eq [IntPtr]::Zero -or
      ![OwnedSave]::IsWindow($filenameComboHandle) -or ![OwnedSave]::IsWindow($filenameEditHandle) -or
      [OwnedSave]::Pid($filenameComboHandle) -ne $c.pid -or [OwnedSave]::Pid($filenameEditHandle) -ne $c.pid -or
      [OwnedSave]::Class($filenameComboHandle) -cne 'ComboBox' -or [OwnedSave]::Class($filenameEditHandle) -cne 'Edit' -or
      [OwnedSave]::GetDlgCtrlID($filenameEditHandle) -ne 1001 -or
      [OwnedSave]::GetParent($filenameEditHandle) -ne $filenameComboHandle -or
      [OwnedSave]::GetDlgItem($filenameComboHandle,1001) -ne $filenameEditHandle) { throw 'Bound filename ComboBox and Edit changed' }
}
function Assert-FilenameHostBinding {
  Set-InputPredicate 'host-control'; Assert-Control $hostControl $element
  Set-InputPredicate 'edit-host-control'; Assert-Control $edit $hostControl
  Set-InputPredicate 'combo-host-control'; Assert-Control $filenameCombo $hostControl
  Assert-FilenameNativeHandles
  Set-InputPredicate 'host-current'; $properties=$hostControl.get_Current()
  Set-InputPredicate 'combo-current'; $comboProperties=$filenameCombo.get_Current()
  Set-InputPredicate 'edit-current'; $editProperties=$edit.get_Current()
  Set-InputPredicate 'host-profile-runtime'
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
  $script:inputFacts.native_focus=$null; $script:inputFacts.uia_focus=$null; $script:inputFacts.uia_focused_element=$null
  Set-InputPredicate 'dialog-guard'; Assert-Dialog $dialog
  Set-InputPredicate 'bound-controls'; Assert-BoundControls
  Set-InputPredicate 'destination'; Assert-Destination
  # Preserve the original short-circuit order; never query a later focus fact
  # after an earlier proof fails. Reset facts so they cannot refer to a prior check.
  Set-InputPredicate 'native-focus'; $script:inputFacts.native_focus=[OwnedFilenameInput]::Focused($dialog,$handle)
  if (!$script:inputFacts.native_focus) { throw 'Bound filename input focus changed' }
  Set-InputPredicate 'uia-focus'; $script:inputFacts.uia_focus=$node.get_Current().get_HasKeyboardFocus()
  if (!$script:inputFacts.uia_focus) { throw 'Bound filename input focus changed' }
  Set-InputPredicate 'uia-focused-element'; $script:inputFacts.uia_focused_element=[Windows.Automation.Automation]::Compare([Windows.Automation.AutomationElement]::get_FocusedElement(),$node)
  if (!$script:inputFacts.uia_focused_element) { throw 'Bound filename input focus changed' }
}
function Assert-FilenameFullSelection($textPattern,$range,[string]$initial) {
  Set-InputPredicate 'edit-writable'
  if ($value.get_Current().get_IsReadOnly()) { throw 'Bound filename became read-only' }
  Set-InputPredicate 'combo-writable'
  if ($hostValue.get_Current().get_IsReadOnly()) { throw 'Bound filename became read-only' }
  Set-InputPredicate 'selection-query'; $selection=@($textPattern.GetSelection())
  Set-InputPredicate 'selection-count'
  if ($selection.Count -ne 1) { throw 'Filename full selection differs' }
  Set-InputPredicate 'selection-range'
  if (!$selection[0].Compare($range)) { throw 'Filename full selection differs' }
  Set-InputPredicate 'selection-text'
  if ($selection[0].GetText(1024) -cne $initial) { throw 'Filename full selection differs' }
  Set-InputPredicate 'selection-value'
  if ($value.get_Current().get_Value() -cne $initial) { throw 'Filename full selection differs' }
}
function Set-OwnedFilenameText {
  Stage 'filename-focus'
  Set-InputPredicate 'text-pattern'; $textPattern=$edit.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern)
  Set-InputPredicate 'selection-support'
  if ($textPattern.SupportedTextSelection -ne [Windows.Automation.SupportedTextSelection]::Single) { throw 'Filename selection pattern unavailable' }
  Set-InputPredicate 'dialog-guard'; Assert-Dialog $dialog
  Set-InputPredicate 'bound-controls'; Assert-BoundControls
  Set-InputPredicate 'destination'; Assert-Destination
  Set-InputPredicate 'edit-focus'; $edit.SetFocus()
  Assert-FilenameInputFocus $edit $filenameEditHandle
  Stage 'filename-select'
  Set-InputPredicate 'document-range'; $range=$textPattern.DocumentRange
  Set-InputPredicate 'initial-value'; $initial=$value.get_Current().get_Value()
  Set-InputPredicate 'initial-name'
  if (!(Test-InitialNativeFilename $initial $c.destination)) { throw 'Filename text range differs' }
  Set-InputPredicate 'initial-range'
  if ($range.GetText(1024) -cne $initial) { throw 'Filename text range differs' }
  Set-InputPredicate 'select-range'; $range.Select(); Assert-FilenameInputFocus $edit $filenameEditHandle
  Assert-FilenameFullSelection $textPattern $range $initial
  Stage 'filename-type'
  Assert-FilenameInputFocus $edit $filenameEditHandle
  Assert-FilenameFullSelection $textPattern $range $initial
  Set-InputPredicate 'send-unicode'; $script:inputFacts.sent_events=[OwnedFilenameInput]::SendUnicode($dialog,$filenameEditHandle,$c.destination)
  Set-InputPredicate 'send-count'
  if ($script:inputFacts.sent_events -ne $c.destination.Length*2) { throw 'Native filename input was incomplete' }
  Stage 'filename-readback'
  $clock=[Diagnostics.Stopwatch]::StartNew(); $script:inputClock=$clock
  do {
    $script:inputFacts.readback_iterations=[Math]::Min(1000,$script:inputFacts.readback_iterations+1)
    $script:inputFacts.host_matches=$null; $script:inputFacts.edit_matches=$null
    Assert-FilenameInputFocus $edit $filenameEditHandle
    Set-InputPredicate 'host-readback'; $script:inputFacts.host_matches=$hostValue.get_Current().get_Value() -ceq $c.destination
    if ($script:inputFacts.host_matches) {
      Set-InputPredicate 'edit-readback'; $script:inputFacts.edit_matches=$value.get_Current().get_Value() -ceq $c.destination
      if ($script:inputFacts.edit_matches) { break }
    }
    Set-InputPredicate 'readback-timeout'
    if ($clock.ElapsedMilliseconds -ge 2000) { $script:inputFacts.readback_timeout=$true; throw 'Native filename readback differs' }
    Start-Sleep -Milliseconds 25 # Conditional readback wait only; never resend input.
  } while ($true)
  $script:inputFacts.readback_elapsed_ms=[int][Math]::Min(35000,$clock.ElapsedMilliseconds); $script:inputClock=$null
  Stage 'save-focus'
  Set-InputPredicate 'dialog-guard'; Assert-Dialog $dialog
  Set-InputPredicate 'bound-controls'; Assert-BoundControls
  Set-InputPredicate 'destination'; Assert-Destination
  Set-InputPredicate 'save-focus'; $button.SetFocus()
  Assert-FilenameInputFocus $button $buttonHandle
  $script:inputFacts.host_matches=$null; $script:inputFacts.edit_matches=$null
  Set-InputPredicate 'save-host-readback'; $script:inputFacts.host_matches=$hostValue.get_Current().get_Value() -ceq $c.destination
  if (!$script:inputFacts.host_matches) { throw 'Native filename readback differs' }
  Set-InputPredicate 'save-edit-readback'; $script:inputFacts.edit_matches=$value.get_Current().get_Value() -ceq $c.destination
  if (!$script:inputFacts.edit_matches) { throw 'Native filename readback differs' }
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
