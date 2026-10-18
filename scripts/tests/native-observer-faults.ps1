# Synthetic object graph only. Do not load UIAutomation or access native windows.
$ErrorActionPreference='Stop'
Add-Type @'
using System;
namespace System.Windows.Automation {
  public class ControlType {
    private int id;
    public bool FailId;
    public int GetterThrows;
    public int Id { get {
      if (FailId) { GetterThrows++; throw new InvalidOperationException("PRIVATE_TYPE_ID"); }
      return id;
    } }
    public ControlType(int value) { id=value; }
    public static ControlType List=new ControlType(50008), ListItem=new ControlType(50007),
      Tree=new ControlType(50023), TreeItem=new ControlType(50024), DataGrid=new ControlType(50028),
      DataItem=new ControlType(50029), Document=new ControlType(50030), Window=new ControlType(50032),
      ComboBox=new ControlType(50003);
  }
  public class Properties {
    public int ProcessIdValue=123;
    public ControlType ControlTypeValue=global::System.Windows.Automation.ControlType.Window;
    public string ClassNameValue="#32770", AutomationIdValue="", FailProperty="";
    public int GetterThrows, ClassReads, IdReads, ForbiddenReads;
    public bool NullClass, NullId;
    private void Read(string property) {
      if (FailProperty==property) { GetterThrows++; throw new InvalidOperationException("PRIVATE_PROPERTY"); }
    }
    public int ProcessId { get { Read("process-id"); return ProcessIdValue; } }
    public ControlType ControlType { get { Read("control-type"); return ControlTypeValue; } }
    public string ClassName { get { ClassReads++; Read("class-name"); return NullClass ? null : ClassNameValue; } }
    public string AutomationId { get { IdReads++; Read("automation-id"); return NullId ? null : AutomationIdValue; } }
    public string Name { get { ForbiddenReads++; throw new Exception("PRIVATE_NAME"); } }
    public string Value { get { ForbiddenReads++; throw new Exception("PRIVATE_VALUE"); } }
  }
  public class Node {
    public Properties Properties=new Properties();
    public Node First, Next;
    public bool FailCurrent, NullCurrent;
    public int CurrentReads, CurrentThrows;
    public Properties Current { get {
      CurrentReads++;
      if (FailCurrent) { CurrentThrows++; throw new InvalidOperationException("PRIVATE_PROPERTY C:\\private"); }
      return NullCurrent ? null : Properties;
    } }
  }
  public class TreeWalker {
    public static TreeWalker RawViewWalker=new TreeWalker();
    public static string Mode="success";
    public Node GetFirstChild(Node node) {
      if (Mode=="first-child") throw new InvalidOperationException("PRIVATE_FIRST C:\\private");
      return node.First;
    }
    public Node GetNextSibling(Node node) {
      if (Mode=="next-sibling") throw new InvalidOperationException("PRIVATE_NEXT C:\\private");
      return node.Next;
    }
  }
  public class ElementNotAvailableException : Exception { }
  public class ElementNotEnabledException : Exception { }
}
public class PRIVATE_Exception : Exception { }
'@
. (Join-Path $PSScriptRoot '../installed-native-dialog-observation.ps1')
# Reproduce the engine behavior separately and prove the actual CLR getter was read/threw.
$probe=[Windows.Automation.Node]::new(); $probe.FailCurrent=$true
$memberCaught=$false; $memberValue=$null; $explicitCaught=$false
try { $memberValue=$probe.Current } catch { $memberCaught=$true }
try { [void]$probe.get_Current() } catch { $explicitCaught=$true }
$getterProbe=@{member_null=($null -eq $memberValue);member_caught=$memberCaught;explicit_caught=$explicitCaught;
  reads=$probe.CurrentReads;throws=$probe.CurrentThrows}
$results=[Collections.Generic.List[object]]::new()
foreach ($mode in @('success','guard-before','property','process-id','control-type','type-id','class-name','automation-id',
  'null-current','invalid-process','missing-type','invalid-type-id','null-class','null-id',
  'first-child','next-sibling','guard-after','guard-before-late','budget')) {
  $script:Mode=$mode; $script:GuardCalls=0
  [Windows.Automation.TreeWalker]::Mode=$mode
  $root=[Windows.Automation.Node]::new()
  $hostNode=[Windows.Automation.Node]::new()
  $hostNode.Properties.ControlTypeValue=[Windows.Automation.ControlType]::ComboBox
  $hostNode.Properties.ClassNameValue='AppControlHost'; $hostNode.Properties.AutomationIdValue='FileNameControlHost'
  $listNode=[Windows.Automation.Node]::new()
  $listNode.Properties.ControlTypeValue=[Windows.Automation.ControlType]::List
  $listNode.Properties.ClassNameValue='PRIVATE_LIST'; $listNode.Properties.AutomationIdValue='PRIVATE_ID'
  $root.First=$hostNode; $hostNode.Next=$listNode
  # Any accidental traversal below a content branch must fail.
  $hiddenNode=[Windows.Automation.Node]::new(); $hiddenNode.FailCurrent=$true; $listNode.First=$hiddenNode
  if ($mode -eq 'property') { $root.FailCurrent=$true }
  if ($mode -in @('process-id','control-type','class-name','automation-id')) { $root.Properties.FailProperty=$mode }
  if ($mode -eq 'type-id') { $root.Properties.ControlTypeValue=[Windows.Automation.ControlType]::new(50032); $root.Properties.ControlTypeValue.FailId=$true }
  if ($mode -eq 'null-current') { $root.NullCurrent=$true }
  if ($mode -eq 'invalid-process') { $root.Properties.ProcessIdValue=0 }
  if ($mode -eq 'missing-type') { $root.Properties.ControlTypeValue=$null }
  if ($mode -eq 'invalid-type-id') { $root.Properties.ControlTypeValue=[Windows.Automation.ControlType]::new(49999) }
  if ($mode -eq 'null-class') { $root.Properties.NullClass=$true }
  if ($mode -eq 'null-id') { $root.Properties.NullId=$true }
  $guard={
    $script:GuardCalls++
    if (($script:Mode -eq 'guard-before' -and $script:GuardCalls -eq 1) -or
        ($script:Mode -eq 'guard-after' -and $script:GuardCalls -eq 2) -or
        ($script:Mode -eq 'guard-before-late' -and $script:GuardCalls -eq 3)) { throw 'PRIVATE_GUARD C:\private' }
    if ($script:Mode -eq 'budget' -and $script:GuardCalls -eq 1) { Start-Sleep -Milliseconds 1100 }
  }
  $observation=Get-OwnedDialogObservation -Element $root -OwnedPid 123 -Guard $guard
  $typeThrows=0
  if ($null -ne $root.Properties.ControlTypeValue) { $typeThrows=$root.Properties.ControlTypeValue.GetterThrows }
  $reads=@{root=$root.CurrentReads;host=$hostNode.CurrentReads;pruned=$listNode.CurrentReads;hidden=$hiddenNode.CurrentReads;
    throws=($root.CurrentThrows+$root.Properties.GetterThrows+$typeThrows);
    pruned_class=$listNode.Properties.ClassReads;pruned_id=$listNode.Properties.IdReads;
    forbidden=($root.Properties.ForbiddenReads+$hostNode.Properties.ForbiddenReads+$listNode.Properties.ForbiddenReads)}
  $results.Add(@{mode=$mode;observation=$observation;reads=$reads})
}
$exceptions=@(
  [Windows.Automation.ElementNotAvailableException]::new(),
  [Windows.Automation.ElementNotEnabledException]::new(),
  [Runtime.InteropServices.COMException]::new('PRIVATE_COM'),
  [InvalidOperationException]::new('PRIVATE_INVALID'),
  [Management.Automation.MethodInvocationException]::new('PRIVATE_INVOCATION'),
  [Management.Automation.RuntimeException]::new('PRIVATE_RUNTIME'),
  [PRIVATE_Exception]::new()
) | ForEach-Object { ConvertTo-SafeNativeException $_ }
@{results=@($results.ToArray());exceptions=@($exceptions);getter_probe=$getterProbe} | ConvertTo-Json -Depth 12 -Compress
