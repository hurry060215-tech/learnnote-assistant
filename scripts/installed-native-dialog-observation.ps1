# Failure-only, read-only evidence for one already-bound native Save dialog.
# No labels, values, paths, screenshots, global roots or native input are read/sent.
function ConvertTo-SafeNativeToken([string]$Text) {
  if ($Text.Length -le 64 -and $Text -cmatch '^[A-Za-z0-9_#.-]*$') { return $Text }
  return '<redacted>'
}

# Only fixed categories cross the boundary; exception text and custom type names do not.
function ConvertTo-SafeNativeException($Exception) {
  switch -CaseSensitive ($Exception.GetType().FullName) {
    'System.Windows.Automation.ElementNotAvailableException' { return 'element-unavailable' }
    'System.Windows.Automation.ElementNotEnabledException' { return 'element-disabled' }
    'System.Runtime.InteropServices.COMException' { return 'com' }
    'System.InvalidOperationException' { return 'invalid-operation' }
    'System.Management.Automation.MethodInvocationException' { return 'method-invocation' }
    'System.Management.Automation.RuntimeException' { return 'runtime' }
    default { return 'other' }
  }
}

function Get-OwnedDialogObservation($Element, [int]$OwnedPid, [scriptblock]$Guard) {
  $snapshots=[Collections.Generic.List[object]]::new()
  $clock=[Diagnostics.Stopwatch]::StartNew()
  $phase='initialization'; $reason='unavailable'; $exceptionType=$null
  try {
    $walker=[Windows.Automation.TreeWalker]::RawViewWalker
    $prune=@([Windows.Automation.ControlType]::List, [Windows.Automation.ControlType]::ListItem,
      [Windows.Automation.ControlType]::Tree, [Windows.Automation.ControlType]::TreeItem,
      [Windows.Automation.ControlType]::DataGrid, [Windows.Automation.ControlType]::DataItem,
      [Windows.Automation.ControlType]::Document)
    for ($sample=0; $sample -lt 2 -and $clock.ElapsedMilliseconds -lt 1000; $sample++) {
      if ($sample -gt 0) {
        $delay=[Math]::Min(250, [Math]::Max(0, 1000-$clock.ElapsedMilliseconds))
        Start-Sleep -Milliseconds $delay
        if ($clock.ElapsedMilliseconds -ge 1000) { break }
      }
      $phase='guard-before'
      [void](& $Guard)
      $nodes=[Collections.Generic.List[object]]::new()
      $queue=[Collections.Generic.Queue[object]]::new()
      $queue.Enqueue(@{node=$Element;parent=-1;depth=0})
      $walked=0; $foreign=0; $truncated=$false
      while ($queue.Count -gt 0 -and $walked -lt 64 -and $clock.ElapsedMilliseconds -lt 1000) {
        $entry=$queue.Dequeue(); $node=$entry.node; $walked++
        $phase='node-properties'
        if ($node.Current.ProcessId -ne $OwnedPid) { $foreign++; continue }
        $type=$node.Current.ControlType; $pruned=$type -in $prune
        $index=$nodes.Count
        $nodes.Add(@{parent=[int]$entry.parent;depth=[int]$entry.depth;type=[int]$type.Id;pruned=[bool]$pruned;
          cls=$(if ($pruned) { '' } else { ConvertTo-SafeNativeToken $node.Current.ClassName });
          id=$(if ($pruned) { '' } else { ConvertTo-SafeNativeToken $node.Current.AutomationId })})
        if ($pruned) { continue }
        if ($entry.depth -ge 8) { $truncated=$true; continue }
        $phase='first-child'
        $child=$walker.GetFirstChild($node)
        while ($child -and ($queue.Count+$walked) -lt 64 -and $clock.ElapsedMilliseconds -lt 1000) {
          $queue.Enqueue(@{node=$child;parent=$index;depth=($entry.depth+1)})
          $phase='next-sibling'
          $child=$walker.GetNextSibling($child)
        }
        if ($child) { $truncated=$true }
      }
      if ($queue.Count -gt 0) { $truncated=$true }
      # Discard this snapshot if identity/foreground changed during observation.
      $phase='guard-after'
      [void](& $Guard)
      $snapshots.Add(@{elapsed_ms=[int]$clock.ElapsedMilliseconds;truncated=[bool]$truncated;
        foreign_nodes=[int]$foreign;nodes=@($nodes.ToArray())})
    }
    if ($snapshots.Count -eq 2) { $phase='complete'; $reason='complete' }
    elseif ($clock.ElapsedMilliseconds -ge 1000) { $reason='budget' }
  } catch {
    $reason='exception'; $exceptionType=ConvertTo-SafeNativeException $_.Exception
  } # Caller retains the original host rejection; evidence is optional.
  return @{phase=$phase;reason=$reason;elapsed_ms=[int][Math]::Min(35000,$clock.ElapsedMilliseconds);exception_type=$exceptionType;
    status=$(if ($snapshots.Count -eq 2) { 'complete' } elseif ($snapshots.Count) { 'partial' } else { 'unavailable' });
    snapshots=@($snapshots.ToArray())}
}
