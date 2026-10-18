# Exact native input guards, extracted unchanged except fixed failure tagging.
# These functions intentionally use the same caller bindings as the original helper.
function Stop-OwnedGuard([string]$Reason, [string]$Message) {
 $failure=[InvalidOperationException]::new($Message)
 $failure.Data['learnnote_guard_reason']=$Reason
 throw $failure
}
function Assert-Process {
 $p=Get-CimInstance Win32_Process -Filter "ProcessId = $($c.pid)";
 if (!$p -or $p.Name -ne 'LearnNote.exe' -or $p.CreationDate.ToUniversalTime().Ticks.ToString() -cne $c.start) { Stop-OwnedGuard 'process-identity' 'Owned app identity changed' }
}

function Assert-Root {
 Assert-Process;
 if (![OwnedSave]::IsWindow($root) -or ![OwnedSave]::IsWindowVisible($root) -or [OwnedSave]::Pid($root) -ne $c.pid -or
  [OwnedSave]::GetWindow($root,4) -ne [IntPtr]::Zero -or [OwnedSave]::Class($root) -cne $rootClass -or [OwnedSave]::Title($root) -cne 'LearnNote - Video Learning Notes') { Stop-OwnedGuard 'root-identity' 'Owned app root changed' }
}
function Assert-Dialog([IntPtr]$dialog) {
 Assert-Root;
 if ([OwnedSave]::GetForegroundWindow() -ne $dialog) { Stop-OwnedGuard 'foreground' 'Owned Save dialog is not foreground; no native input' }
 if (![OwnedSave]::IsWindow($dialog) -or ![OwnedSave]::IsWindowVisible($dialog) -or [OwnedSave]::Pid($dialog) -ne $c.pid -or [OwnedSave]::Class($dialog) -cne '#32770') { Stop-OwnedGuard 'dialog-identity' 'Owned Save dialog changed' }
 $cursor=[OwnedSave]::GetWindow($dialog,4); $reached=$false;
 for ($i=0; $i -lt 16 -and $cursor -ne [IntPtr]::Zero; $i++) {
  if ([OwnedSave]::Pid($cursor) -ne $c.pid) { Stop-OwnedGuard 'owner-process' 'Save owner chain left the owned process' }
  if ($cursor -eq $root) { $reached=$true; break }; $cursor=[OwnedSave]::GetWindow($cursor,4);
 }
 if (!$reached) { Stop-OwnedGuard 'owner-root' 'Save dialog is not owned by the exact app root' }
 $visible=@([OwnedSave]::Visible($c.pid));
 if ($visible.Count -ne 2 -or @($visible | Where-Object { $_ -ne $root -and $_ -ne $dialog }).Count) { Stop-OwnedGuard 'popup-set' 'Unexpected owned popup; no native input' }
}

# Independent evidence proof binds copies of the original exact process/window
# identities. It never alters the dynamic callback or any input guard.
function Assert-BoundDialog($Binding) {
 $c=$Binding.config; $root=$Binding.root; $rootClass=$Binding.rootClass; $dialog=$Binding.dialog
 Assert-Dialog $dialog
}

# Bounded comparisons only, including the callback's dynamic bindings versus the
# captured originals. Never return HWNDs, process dates, titles, paths or text.
function Get-OwnedDialogIdentityFacts($Expected) {
 $facts=@{binding_matches=$null;process_exists=$null;process_name_matches=$null;process_start_matches=$null;
  root_exists=$null;root_visible=$null;root_pid_matches=$null;root_ownerless=$null;root_class_matches=$null;root_title_matches=$null;
  dialog_exists=$null;dialog_visible=$null;dialog_pid_matches=$null;dialog_class_matches=$null;
  foreground='unavailable';owner_chain='unavailable';visible_count=$null;visible_set_matches=$null}
 try { $facts.binding_matches=($c.pid -eq $Expected.config.pid -and $c.start -ceq $Expected.config.start -and
   $root -eq $Expected.root -and $rootClass -ceq $Expected.rootClass -and $dialog -eq $Expected.dialog) } catch { }
 try {
  $observedProcess=Get-CimInstance Win32_Process -Filter "ProcessId = $($Expected.config.pid)"
  $facts.process_exists=($null -ne $observedProcess)
  if ($observedProcess) {
   $facts.process_name_matches=($observedProcess.Name -ceq 'LearnNote.exe')
   $facts.process_start_matches=($observedProcess.CreationDate.ToUniversalTime().Ticks.ToString() -ceq $Expected.config.start)
  }
 } catch { }
 try {
  $facts.root_exists=[OwnedSave]::IsWindow($Expected.root)
  $facts.root_visible=[OwnedSave]::IsWindowVisible($Expected.root)
  $facts.root_pid_matches=([OwnedSave]::Pid($Expected.root) -eq $Expected.config.pid)
  $facts.root_ownerless=([OwnedSave]::GetWindow($Expected.root,4) -eq [IntPtr]::Zero)
  if ($facts.root_exists -and $facts.root_pid_matches) {
   $facts.root_class_matches=([OwnedSave]::Class($Expected.root) -ceq $Expected.rootClass)
   $facts.root_title_matches=([OwnedSave]::Title($Expected.root) -ceq 'LearnNote - Video Learning Notes')
  }
  $facts.dialog_exists=[OwnedSave]::IsWindow($Expected.dialog)
  $facts.dialog_visible=[OwnedSave]::IsWindowVisible($Expected.dialog)
  $facts.dialog_pid_matches=([OwnedSave]::Pid($Expected.dialog) -eq $Expected.config.pid)
  if ($facts.dialog_exists -and $facts.dialog_pid_matches) { $facts.dialog_class_matches=([OwnedSave]::Class($Expected.dialog) -ceq '#32770') }
  $observedForeground=[OwnedSave]::GetForegroundWindow()
  $facts.foreground=if ($observedForeground -eq $Expected.dialog) { 'dialog' } elseif ($observedForeground -eq $Expected.root) { 'root' } elseif ($observedForeground -eq [IntPtr]::Zero) { 'none' } else { 'other' }
 } catch { }
 try {
  $observedOwner=[OwnedSave]::GetWindow($Expected.dialog,4); $facts.owner_chain='limit'
  for ($ownerStep=0; $ownerStep -lt 16; $ownerStep++) {
   if ($observedOwner -eq [IntPtr]::Zero) { $facts.owner_chain='missing'; break }
   if ([OwnedSave]::Pid($observedOwner) -ne $Expected.config.pid) { $facts.owner_chain='foreign'; break }
   if ($observedOwner -eq $Expected.root) { $facts.owner_chain='root'; break }
   $observedOwner=[OwnedSave]::GetWindow($observedOwner,4)
  }
  $observedVisible=@([OwnedSave]::Visible($Expected.config.pid))
  $facts.visible_count=[int][Math]::Min(64,$observedVisible.Count)
  $facts.visible_set_matches=($observedVisible.Count -eq 2 -and @($observedVisible | Where-Object { $_ -ne $Expected.root -and $_ -ne $Expected.dialog }).Count -eq 0)
 } catch { }
 return $facts
}
