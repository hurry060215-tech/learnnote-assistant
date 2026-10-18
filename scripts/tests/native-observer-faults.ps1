# Synthetic object graph only. Do not load UIAutomation or access native windows.
$ErrorActionPreference='Stop'
Add-Type @'
using System;
namespace System.Windows.Automation {
  public class ControlType {
    public int Id;
    ControlType(int id) { Id=id; }
    public static ControlType List=new ControlType(50008), ListItem=new ControlType(50007),
      Tree=new ControlType(50023), TreeItem=new ControlType(50024), DataGrid=new ControlType(50028),
      DataItem=new ControlType(50029), Document=new ControlType(50030), Window=new ControlType(50032),
      ComboBox=new ControlType(50003);
  }
  public class Properties {
    public int ProcessId=123;
    public ControlType ControlType=global::System.Windows.Automation.ControlType.Window;
    public string ClassName="#32770", AutomationId="";
    public string Name { get { throw new Exception("PRIVATE_NAME"); } }
    public string Value { get { throw new Exception("PRIVATE_VALUE"); } }
  }
  public class Node {
    public Properties Properties=new Properties();
    public Node First, Next;
    public bool FailCurrent;
    public Properties Current { get {
      if (FailCurrent) throw new InvalidOperationException("PRIVATE_PROPERTY C:\\private");
      return Properties;
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
$results=[Collections.Generic.List[object]]::new()
foreach ($mode in @('success','guard-before','property','first-child','next-sibling','guard-after','guard-before-late','budget')) {
  $script:Mode=$mode; $script:GuardCalls=0
  [Windows.Automation.TreeWalker]::Mode=$mode
  $root=[Windows.Automation.Node]::new()
  $hostNode=[Windows.Automation.Node]::new()
  $hostNode.Properties.ControlType=[Windows.Automation.ControlType]::ComboBox
  $hostNode.Properties.ClassName='AppControlHost'; $hostNode.Properties.AutomationId='FileNameControlHost'
  $listNode=[Windows.Automation.Node]::new()
  $listNode.Properties.ControlType=[Windows.Automation.ControlType]::List
  $listNode.Properties.ClassName='PRIVATE_LIST'; $listNode.Properties.AutomationId='PRIVATE_ID'
  $root.First=$hostNode; $hostNode.Next=$listNode
  # Any accidental traversal below a content branch must fail.
  $hiddenNode=[Windows.Automation.Node]::new(); $hiddenNode.FailCurrent=$true; $listNode.First=$hiddenNode
  if ($mode -eq 'property') { $root.FailCurrent=$true }
  $guard={
    $script:GuardCalls++
    if (($script:Mode -eq 'guard-before' -and $script:GuardCalls -eq 1) -or
        ($script:Mode -eq 'guard-after' -and $script:GuardCalls -eq 2) -or
        ($script:Mode -eq 'guard-before-late' -and $script:GuardCalls -eq 3)) { throw 'PRIVATE_GUARD C:\private' }
    if ($script:Mode -eq 'budget' -and $script:GuardCalls -eq 1) { Start-Sleep -Milliseconds 1100 }
  }
  $observation=Get-OwnedDialogObservation -Element $root -OwnedPid 123 -Guard $guard
  $results.Add(@{mode=$mode;observation=$observation})
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
@{results=@($results.ToArray());exceptions=@($exceptions)} | ConvertTo-Json -Depth 12 -Compress
