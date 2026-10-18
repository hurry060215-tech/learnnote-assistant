# Failure-only read-only pixels/topology. This proof grants no input eligibility.
# Only the exact app PID/start/root, known Save window and its owned foreground
# window are inspected. No titles (except the existing root guard), text or values.
function Get-OwnedForegroundState($Binding, [IntPtr]$Foreground) {
 $c=$Binding.config; $root=$Binding.root; $rootClass=$Binding.rootClass
 Assert-Root
 if ($Foreground -eq [IntPtr]::Zero -or $Foreground -eq $root -or
     [OwnedSave]::GetForegroundWindow() -ne $Foreground) { Stop-OwnedGuard 'foreground' 'Owned evidence foreground changed' }
 $chains=[Collections.Generic.List[object]]::new()
 foreach ($window in @([IntPtr]$Binding.dialog,$Foreground)) {
  if (![OwnedSave]::IsWindow($window) -or ![OwnedSave]::IsWindowVisible($window) -or
      [OwnedSave]::Pid($window) -ne $c.pid) { Stop-OwnedGuard 'dialog-identity' 'Owned evidence window changed' }
  $chain=[Collections.Generic.List[IntPtr]]::new(); $seen=[Collections.Generic.HashSet[IntPtr]]::new()
  [void]$seen.Add($window); $cursor=[OwnedSave]::GetWindow($window,4); $reached=$false
  for ($step=0; $step -lt 16 -and $cursor -ne [IntPtr]::Zero; $step++) {
   if (![OwnedSave]::IsWindow($cursor) -or [OwnedSave]::Pid($cursor) -ne $c.pid -or !$seen.Add($cursor)) {
    Stop-OwnedGuard 'owner-process' 'Owned evidence owner identity changed'
   }
   $chain.Add($cursor)
   if ($cursor -eq $root) { $reached=$true; break }
   $cursor=[OwnedSave]::GetWindow($cursor,4)
  }
  if (!$reached) { Stop-OwnedGuard 'owner-root' 'Owned evidence root not reached' }
  $chains.Add($chain.ToArray())
 }
 # Class reads occur only after both windows and every owner have passed proof.
 $saveClass=[OwnedSave]::Class($Binding.dialog); $foregroundClass=[OwnedSave]::Class($Foreground)
 if ($saveClass -cne '#32770' -or [string]::IsNullOrEmpty($foregroundClass)) {
  Stop-OwnedGuard 'dialog-identity' 'Owned evidence window class changed'
 }
 Assert-Root
 if ([OwnedSave]::GetForegroundWindow() -ne $Foreground) { Stop-OwnedGuard 'foreground' 'Owned evidence foreground changed' }
 return @{save_class=$saveClass;foreground_class=$foregroundClass;save_owners=$chains[0];foreground_owners=$chains[1]}
}

function Assert-OwnedForegroundEvidence($Proof) {
 $current=Get-OwnedForegroundState $Proof.binding $Proof.foreground
 if ($current.save_class -cne $Proof.state.save_class -or $current.foreground_class -cne $Proof.state.foreground_class) {
  Stop-OwnedGuard 'dialog-identity' 'Owned evidence class changed during capture'
 }
 foreach ($key in @('save_owners','foreground_owners')) {
  if ($current[$key].Count -ne $Proof.state[$key].Count) { Stop-OwnedGuard 'owner-root' 'Owned evidence topology changed' }
  for ($index=0; $index -lt $current[$key].Count; $index++) {
   if ($current[$key][$index] -ne $Proof.state[$key][$index]) { Stop-OwnedGuard 'owner-root' 'Owned evidence topology changed' }
  }
 }
}

function Get-OwnedForegroundEvidence($Binding, [string]$Directory, [string]$Destination) {
 $clock=[Diagnostics.Stopwatch]::StartNew(); $phase='guard-before'; $guardFailure=$null; $exceptionType=$null
 $capture=@{status='unavailable';reason='unavailable';file=$null;width=$null;height=$null}
 $windows=@(); $sameWindow=$null; $status='unavailable'; $reason='exception'
 try {
  $foreground=[OwnedSave]::GetForegroundWindow()
  $state=Get-OwnedForegroundState $Binding $foreground
  $proof=@{binding=$Binding;foreground=$foreground;state=$state}
  $candidate=[Collections.Generic.List[object]]::new()
  foreach ($entry in @(@{role='save';cls=$state.save_class;owners=$state.save_owners},
                       @{role='foreground';cls=$state.foreground_class;owners=$state.foreground_owners})) {
   $owners=@($entry.owners | ForEach-Object {
    if ($_ -eq $Binding.root) { 'root' } elseif ($_ -eq $Binding.dialog) { 'save' }
    elseif ($_ -eq $foreground) { 'foreground' } else { 'other-owned' }
   })
   $candidate.Add(@{role=$entry.role;cls=(ConvertTo-SafeNativeToken $entry.cls);owners=$owners})
  }
  $phase='capture'
  $capture=Save-OwnedDialogCapture -Dialog $foreground -Directory $Directory -Destination $Destination `
    -Surface 'foreground' -GuardContext $proof -Guard { param($boundProof) Assert-OwnedForegroundEvidence $boundProof }
  if ($capture.status -eq 'saved') {
   $windows=@($candidate.ToArray()); $sameWindow=($foreground -eq $Binding.dialog)
   $status='complete'; $reason='complete'; $phase='complete'
  } else { $reason='capture-unavailable' }
 } catch {
  $exceptionType=ConvertTo-SafeNativeException $_.Exception
  $guardFailure=Get-SafeNativeGuardFailure $_ $null
 }
 return @{scope='read-only-owned-foreground';status=$status;phase=$phase;reason=$reason;
  elapsed_ms=[int][Math]::Min(35000,$clock.ElapsedMilliseconds);exception_type=$exceptionType;
  guard_failure=$guardFailure;foreground_is_save=$sameWindow;windows=$windows;capture=$capture}
}
