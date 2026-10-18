param([string]$HostFailureBody)
# Synthetic bindings only. The actual production guard functions and callbacks
# execute against this fake native boundary; no user32, CIM or real UI is used.
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Collections.Generic;
public static class OwnedSave {
 public static string Mode="success";
 public static int ProcessCalls, ChildReads, ForbiddenReads, ClassReads;
 public static void Reset(string mode) { Mode=mode; ProcessCalls=ChildReads=ForbiddenReads=ClassReads=0; }
 public static bool IsWindow(IntPtr h) { return h.ToInt64()!=0 && h.ToInt64()!=90 && !(Mode=="root-gone" && h.ToInt64()==1) && !(Mode=="dialog-gone" && h.ToInt64()==2); }
 public static bool IsWindowVisible(IntPtr h) { return !(Mode=="root-hidden" && h.ToInt64()==1) && !(Mode=="dialog-hidden" && h.ToInt64()==2); }
 public static uint Pid(IntPtr h) {
  long n=h.ToInt64();
  return n==99 || (Mode=="root-pid" && n==1) || (Mode=="dialog-pid" && n==2) || (Mode=="child-foreign" && n==3) ? 999u : 123u;
 }
 public static IntPtr GetWindow(IntPtr h, uint kind) {
  long n=h.ToInt64();
  if (kind==4) {
   if (n==1) return new IntPtr(Mode=="root-owner" ? 90 : 0);
   if (n==2) return new IntPtr(Mode=="owner-process" ? 99 : Mode=="owner-missing" ? 0 : Mode=="owner-cycle" ? 9 : 1);
   return new IntPtr(Mode=="owner-cycle" && n==9 ? 9 : 0);
  }
  ChildReads++;
  if (kind==5) {
   if (n==4 && Mode!="tree-depth" && Mode!="tree-limit") { ForbiddenReads++; throw new Exception("PRIVATE_CONTENT"); }
   if (Mode=="tree-budget") System.Threading.Thread.Sleep(550);
   if (Mode=="tree-depth") return new IntPtr(n>=2 && n<20 ? n+1 : 0);
   return new IntPtr(n==2 ? 3 : 0);
  }
  if (kind==2) {
   if (Mode=="child-cycle") return new IntPtr(3);
   if (Mode=="tree-limit") return new IntPtr(n<100 ? n+1 : 0);
   if (Mode=="tree-depth") return IntPtr.Zero;
   return new IntPtr(n==3 ? 4 : n==4 ? 5 : 0);
  }
  throw new Exception("PRIVATE_INVALID_KIND");
 }
 public static IntPtr GetParent(IntPtr h) {
  long n=h.ToInt64();
  if (Mode=="child-reparent" && n==3) return new IntPtr(90);
  return new IntPtr(Mode=="tree-depth" && n>=3 ? n-1 : n>=3 ? 2 : n==2 ? 1 : 0);
 }
 public static string Class(IntPtr h) {
  long n=h.ToInt64(); ClassReads++;
  if (Mode=="child-foreign" && n==3) { ForbiddenReads++; throw new Exception("PRIVATE_FOREIGN"); }
  if (n==1) return Mode=="root-class" ? "OTHER" : "WindowsForms10.Window.synthetic";
  if (n==2) return Mode=="dialog-class" ? "OTHER" : "#32770";
  if (Mode=="class-private" && n==3) return @"C:\PRIVATE_CLASS";
  if (n==4 && Mode!="tree-depth" && Mode!="tree-limit") return "SysListView32";
  return n==3 ? "ComboBox" : "Edit";
 }
 public static string Title(IntPtr h) { if (h.ToInt64()!=1) { ForbiddenReads++; throw new Exception("PRIVATE_TITLE"); } return Mode=="root-title" ? "PRIVATE_TITLE" : "LearnNote - Video Learning Notes"; }
 public static IntPtr GetForegroundWindow() {
  if (Mode=="foreground-none") return IntPtr.Zero;
  if (Mode=="foreground-other") return new IntPtr(99);
  if (Mode=="foreground-root" || (Mode=="uia-guard-after" && ProcessCalls>=2) || (Mode=="win-guard-after" && ChildReads>0)) return new IntPtr(1);
  return new IntPtr(2);
 }
 public static IntPtr[] Visible(uint pid) {
  if (pid!=123) throw new Exception("PRIVATE_WRONG_PID");
  return Mode=="popup-extra" ? new[]{new IntPtr(1),new IntPtr(2),new IntPtr(9)} : Mode=="popup-missing" ? new[]{new IntPtr(1)} : new[]{new IntPtr(1),new IntPtr(2)};
 }
 public static int GetDlgCtrlID(IntPtr h) { if (Mode=="child-foreign" && h.ToInt64()==3) { ForbiddenReads++; throw new Exception("PRIVATE_FOREIGN_ID"); } return h.ToInt64()==5 ? 1001 : (int)h.ToInt64(); }
}
namespace System.Windows.Automation {
 public class ControlType {
  public int Id { get { return 50032; } }
  public static ControlType Window=new ControlType(), List=new ControlType(), ListItem=new ControlType(), Tree=new ControlType(), TreeItem=new ControlType(), DataGrid=new ControlType(), DataItem=new ControlType(), Document=new ControlType();
 }
 public class Properties {
  public int ProcessId { get { return 123; } }
  public ControlType ControlType { get { return global::System.Windows.Automation.ControlType.Window; } }
  public string ClassName { get { return "#32770"; } }
  public string AutomationId { get { return ""; } }
 }
 public class Node { public int Reads; public Properties Current { get { Reads++; return new Properties(); } } }
 public class TreeWalker {
  public static TreeWalker RawViewWalker=new TreeWalker();
  public Node GetFirstChild(Node n) { return null; }
  public Node GetNextSibling(Node n) { return null; }
 }
}
'@
function Get-CimInstance($ClassName, $Filter) {
 if ($ClassName -cne 'Win32_Process' -or $Filter -cne 'ProcessId = 123') { throw 'PRIVATE_BINDING_QUERY' }
 [OwnedSave]::ProcessCalls++
 if ([OwnedSave]::Mode -eq 'process-missing') { return $null }
 $date=[DateTime]::new(2026,1,1,0,0,0,[DateTimeKind]::Utc)
 if ([OwnedSave]::Mode -eq 'process-start') { $date=$date.AddSeconds(1) }
 return [pscustomobject]@{Name=$(if ([OwnedSave]::Mode -eq 'process-name') { 'PRIVATE_PROCESS' } else { 'LearnNote.exe' });CreationDate=$date}
}
. (Join-Path $PSScriptRoot '../installed-native-dialog-guards.ps1')
. (Join-Path $PSScriptRoot '../installed-native-dialog-observation.ps1')
. (Join-Path $PSScriptRoot '../installed-native-dialog-win32.ps1')
function Invoke-ActualGuardScope([string]$Mode) {
 [OwnedSave]::Reset($Mode)
 $c=@{pid=123;start=[DateTime]::new(2026,1,1,0,0,0,[DateTimeKind]::Utc).Ticks.ToString()}
 $root=[IntPtr]1; $rootClass='WindowsForms10.Window.synthetic'; $dialog=[IntPtr]2
 $bound=@{config=@{pid=$c.pid;start=$c.start};root=$root;rootClass=$rootClass;dialog=$dialog}
 if ($Mode -eq 'binding-config') { $c=@{pid=123;start='different'} }
 if ($Mode -eq 'binding-root') { $root=[IntPtr]90 }
 if ($Mode -eq 'binding-dialog') { $dialog=[IntPtr]90 }
 if ($Mode -eq 'binding-runtime') { $c=$null }
 $element=[Windows.Automation.Node]::new()
 # Exact same dynamic callback and fact callback as the generated helper.
 $uia=Get-OwnedDialogObservation -Element $element -OwnedPid 123 -Guard { Assert-Dialog $dialog } -FailureFacts { Get-OwnedDialogIdentityFacts $bound }
 $win32=Get-OwnedDialogWin32Observation $bound
 return @{mode=$Mode;uia=$uia;win32=$win32;uia_reads=$element.Reads;child_reads=[OwnedSave]::ChildReads;forbidden_reads=[OwnedSave]::ForbiddenReads}
}
$results=[Collections.Generic.List[object]]::new()
foreach ($mode in @('success','process-missing','process-name','process-start','root-gone','root-hidden','root-pid','root-owner','root-class','root-title',
 'foreground-root','foreground-none','foreground-other','dialog-gone','dialog-hidden','dialog-pid','dialog-class','owner-process','owner-missing','owner-cycle',
 'popup-extra','popup-missing','binding-config','binding-root','binding-dialog','binding-runtime','uia-guard-after','win-guard-after',
 'child-foreign','child-reparent','child-cycle','tree-limit','tree-depth','tree-budget','class-private')) {
 $results.Add((Invoke-ActualGuardScope $mode))
}
# Execute the actual generated host catch body, rather than a hand-written
# approximation, with guard, loading and formatting evidence failures.
$hostBranch=[scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($HostFailureBody)))
function Invoke-PrimaryPreservation([string]$Mode) {
 [OwnedSave]::Reset('foreground-root')
 $c=@{pid=123;start=[DateTime]::new(2026,1,1,0,0,0,[DateTimeKind]::Utc).Ticks.ToString();observer=(Join-Path $PSScriptRoot '../installed-native-dialog-observation.ps1')}
 if ($Mode -eq 'observer-load') { $c.observer=Join-Path $PSScriptRoot 'synthetic-absent-observer.ps1' }
 if ($Mode -eq 'format') { function ConvertTo-Json { throw 'PRIVATE_FORMAT_FAILURE' } }
 $root=[IntPtr]1; $rootClass='WindowsForms10.Window.synthetic'; $dialog=[IntPtr]2
 $element=[Windows.Automation.Node]::new(); $hostCount=0; $hostSubphase='match-count'
 $primary=[InvalidOperationException]::new('PRIVATE_PRIMARY_FAILURE')
 try {
  try { throw $primary } catch { & $hostBranch }
 } catch { return @{mode=$Mode;preserved=[object]::ReferenceEquals($_.Exception,$primary)} }
 return @{mode=$Mode;preserved=$false}
}
$primaryResults=@('guard','observer-load','format' | ForEach-Object { Invoke-PrimaryPreservation $_ })
@{results=@($results.ToArray());primary=$primaryResults} | ConvertTo-Json -Depth 12 -Compress
