# Failure-only structure below one independently reverified exact owned dialog.
# No text, labels, values, screenshots, input, global tree or alternate selector.
function Get-OwnedDialogWin32Observation($Binding) {
 $winClock=[Diagnostics.Stopwatch]::StartNew(); $winPhase='guard-before'; $winReason='unavailable'
 $winException=$null; $winGuardFailure=$null; $winTruncated=$false
 $winNodes=[Collections.Generic.List[object]]::new()
 try {
  Assert-BoundDialog $Binding
  $winPhase='children'
  $winQueue=[Collections.Generic.Queue[object]]::new()
  $winSeen=[Collections.Generic.HashSet[IntPtr]]::new()
  [void]$winSeen.Add($Binding.dialog)
  $winQueue.Enqueue(@{handle=$Binding.dialog;parent=-1;parentHandle=[IntPtr]::Zero;depth=0})
  while ($winQueue.Count -gt 0 -and $winNodes.Count -lt 64 -and $winClock.ElapsedMilliseconds -lt 500) {
   $winEntry=$winQueue.Dequeue(); $winHandle=[IntPtr]$winEntry.handle
   if (![OwnedSave]::IsWindow($winHandle) -or [OwnedSave]::Pid($winHandle) -ne $Binding.config.pid -or
     ($winEntry.parent -ge 0 -and [OwnedSave]::GetParent($winHandle) -ne $winEntry.parentHandle)) { throw [InvalidOperationException]::new('Native child identity changed') }
   $winClass=[OwnedSave]::Class($winHandle); $winId=[OwnedSave]::GetDlgCtrlID($winHandle)
   # Structure only; do not descend into native content lists, trees or web views.
   $winPruned=$winClass -cin @('SysListView32','SysTreeView32','Internet Explorer_Server','Chrome_RenderWidgetHostHWND')
   $winIndex=$winNodes.Count
   $winNodes.Add(@{parent=[int]$winEntry.parent;depth=[int]$winEntry.depth;cls=(ConvertTo-SafeNativeToken $winClass);id=[int]$winId;pruned=[bool]$winPruned})
   if ($winPruned) { continue }
   if ($winEntry.depth -ge 8) { $winTruncated=$true; continue }
   $winChild=[OwnedSave]::GetWindow($winHandle,5)
   while ($winChild -ne [IntPtr]::Zero -and $winSeen.Count -lt 64 -and $winClock.ElapsedMilliseconds -lt 500) {
    if (![OwnedSave]::IsWindow($winChild) -or [OwnedSave]::Pid($winChild) -ne $Binding.config.pid -or
      [OwnedSave]::GetParent($winChild) -ne $winHandle -or !$winSeen.Add($winChild)) { throw [InvalidOperationException]::new('Native child ancestry changed') }
    $winQueue.Enqueue(@{handle=$winChild;parent=$winIndex;parentHandle=$winHandle;depth=($winEntry.depth+1)})
    $winChild=[OwnedSave]::GetWindow($winChild,2)
   }
   if ($winChild -ne [IntPtr]::Zero) { $winTruncated=$true }
  }
  if ($winQueue.Count -gt 0) { $winTruncated=$true }
  $winPhase='guard-after'; Assert-BoundDialog $Binding
  $winReason=if ($winClock.ElapsedMilliseconds -ge 500) { 'budget' } else { 'complete' }
  $winPhase='complete'
 } catch {
  $winReason='exception'; $winException=ConvertTo-SafeNativeException $_.Exception
  if ($winPhase -in @('guard-before','guard-after')) {
   $winGuardFailure=Get-SafeNativeGuardFailure $_ { Get-OwnedDialogIdentityFacts $Binding }
  }
  # An ownership/race/provider failure never leaves a falsely verified tree.
  $winNodes.Clear(); $winTruncated=$false
 }
 return @{status=$(if ($winPhase -eq 'complete') { 'complete' } else { 'unavailable' });phase=$winPhase;reason=$winReason;
  elapsed_ms=[int][Math]::Min(35000,$winClock.ElapsedMilliseconds);exception_type=$winException;guard_failure=$winGuardFailure;
  truncated=[bool]$winTruncated;nodes=@($winNodes.ToArray())}
}
