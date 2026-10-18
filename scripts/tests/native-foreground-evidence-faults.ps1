# Actual evidence proof and explicit capture callback, synthetic native boundary.
# No native windows, input, screenshots or customer data are accessed by this test.
$ErrorActionPreference='Stop'
Add-Type @'
using System;
public static class OwnedSave {
 public static string Mode;
 public static bool Changed;
 public static int ForbiddenReads;
 public static bool IsWindow(IntPtr h) { return h!=IntPtr.Zero && !(Mode=="save-gone" && h.ToInt64()==2) && !((Mode=="foreground-gone" || (Mode=="race-gone" && Changed)) && h.ToInt64()==3); }
 public static bool IsWindowVisible(IntPtr h) { return !((Mode=="foreground-hidden" || (Mode=="race-hidden" && Changed)) && h.ToInt64()==3); }
 public static uint Pid(IntPtr h) { return h.ToInt64()==99 || (Mode=="race-pid" && Changed && h.ToInt64()==3) ? 999u : 123u; }
 public static IntPtr GetForegroundWindow() {
  if (Mode=="foreground-none") return IntPtr.Zero;
  if (Mode=="foreground-root") return new IntPtr(1);
  if (Mode=="foreground-foreign") return new IntPtr(99);
  if (Mode=="foreground-save") return new IntPtr(2);
  return new IntPtr(Mode=="race-foreground" && Changed ? 4 : 3);
 }
 public static IntPtr GetWindow(IntPtr h, uint kind) {
  if (kind!=4) { ForbiddenReads++; throw new Exception("PRIVATE_TRAVERSAL"); }
  long n=h.ToInt64();
  if (n==1) return new IntPtr(Mode=="root-owner" ? 9 : 0);
  if (n==2) return new IntPtr(1);
  if (n==3) return new IntPtr(Mode=="owner-foreign" ? 99 : Mode=="owner-missing" ? 0 :
    Mode=="owner-cycle" || Mode=="owner-limit" ? 4 : Mode=="sibling" || (Mode=="race-owner" && Changed) ? 1 : 2);
  if (Mode=="owner-cycle") return new IntPtr(3);
  if (Mode=="owner-limit") return new IntPtr(n+1);
  return new IntPtr(1);
 }
 public static string Class(IntPtr h) {
  long n=h.ToInt64();
  if (n==99) { ForbiddenReads++; throw new Exception("PRIVATE_FOREIGN_CLASS"); }
  if (n==1) return Mode=="root-class" || (Mode=="race-root" && Changed) ? "OTHER" : "WindowsForms10.Window.synthetic";
  if (n==2) return Mode=="save-class" || (Mode=="race-save-class" && Changed) ? "OTHER" : "#32770";
  if (Mode=="private-class") return @"C:\PRIVATE_CLASS";
  return Mode=="race-class" && Changed ? "OTHER" : "#32770";
 }
 public static string Title(IntPtr h) {
  if (h.ToInt64()!=1) { ForbiddenReads++; throw new Exception("PRIVATE_TITLE"); }
  return "LearnNote - Video Learning Notes";
 }
}
'@
function Get-CimInstance($ClassName,$Filter) {
 if ($ClassName -cne 'Win32_Process' -or $Filter -cne 'ProcessId = 123') { throw 'PRIVATE_QUERY' }
 if ([OwnedSave]::Mode -eq 'process-missing') { return $null }
 $date=[DateTime]::new(2026,1,1,0,0,0,[DateTimeKind]::Utc)
 if ([OwnedSave]::Mode -eq 'process-start' -or ([OwnedSave]::Mode -eq 'race-start' -and [OwnedSave]::Changed)) { $date=$date.AddSeconds(1) }
 return [pscustomobject]@{Name=$(if ([OwnedSave]::Mode -eq 'process-name') {'OTHER'} else {'LearnNote.exe'});CreationDate=$date}
}
. (Join-Path $PSScriptRoot '../installed-native-dialog-guards.ps1')
. (Join-Path $PSScriptRoot '../installed-native-dialog-observation.ps1')
. (Join-Path $PSScriptRoot '../installed-native-foreground-evidence.ps1')
# Renderer substitute exercises the actual production proof callback before and
# after a synthetic render. It cannot create a file or read real pixels.
function Save-OwnedDialogCapture($Dialog,$Directory,$Destination,$Guard,$Surface,$GuardContext) {
 $script:CaptureCalls++; $phase='guard-before'
 try {
  if ($Surface -cne 'foreground' -or $Dialog -ne $GuardContext.foreground) { throw 'PRIVATE_BINDING' }
  [void](& $Guard $GuardContext); $script:GuardCalls++
  if ([OwnedSave]::Mode -eq 'capture-throw') { throw 'PRIVATE_RENDER' }
  if ([OwnedSave]::Mode -eq 'capture-fail') { return @{status='unavailable';reason='render';file=$null;width=$null;height=$null} }
  [OwnedSave]::Changed=$true; $phase='guard-after'
  [void](& $Guard $GuardContext); $script:GuardCalls++
  $script:PersistCalls++
  return @{status='saved';reason='captured';file='installed-current-md-native-foreground.png';width=625;height=480}
 } catch { return @{status='unavailable';reason=$phase;file=$null;width=$null;height=$null} }
}
$results=[Collections.Generic.List[object]]::new()
foreach ($mode in @('success','sibling','foreground-save','private-class','process-missing','process-name','process-start',
 'root-owner','root-class','foreground-none','foreground-root','foreground-foreign','foreground-gone','foreground-hidden',
 'save-gone','save-class','owner-foreign','owner-missing','owner-cycle','owner-limit',
 'race-foreground','race-pid','race-start','race-root','race-class','race-owner','race-gone','race-hidden','race-save-class','capture-fail','capture-throw')) {
 [OwnedSave]::Mode=$mode; [OwnedSave]::Changed=$false; [OwnedSave]::ForbiddenReads=0
 $script:CaptureCalls=0; $script:GuardCalls=0; $script:PersistCalls=0
 $binding=@{config=@{pid=123;start=[DateTime]::new(2026,1,1,0,0,0,[DateTimeKind]::Utc).Ticks.ToString()};
   root=[IntPtr]1;rootClass='WindowsForms10.Window.synthetic';dialog=[IntPtr]2}
 $result=Get-OwnedForegroundEvidence $binding 'D:\owned\local-native-exports-fresh' 'D:\owned\local-native-exports-fresh\learnnote-diagnostics.md'
 $results.Add(@{mode=$mode;evidence=$result;captures=$script:CaptureCalls;guards=$script:GuardCalls;
   persisted=$script:PersistCalls;forbidden=[OwnedSave]::ForbiddenReads})
}
@{results=@($results.ToArray())} | ConvertTo-Json -Depth 12 -Compress
