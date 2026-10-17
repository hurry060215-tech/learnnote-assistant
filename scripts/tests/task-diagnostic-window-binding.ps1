$ErrorActionPreference = "Stop"
# Execute the actual pure production predicate without loading native APIs or sending input.
$source = Get-Content (Join-Path $PSScriptRoot "../timeline-native-zoom.ps1") -Raw
$start = $source.IndexOf('function Assert-PreparedWindowFacts')
$end = $source.IndexOf('# End pure prepared-window validation.')
Invoke-Expression $source.Substring($start, $end - $start)
$root = @{ Hwnd = 100; Pid = 42; Class = "Chrome_WidgetWin_1"; Exists = $true; Visible = $true; Owner = 0 }
$popup = @{ Hwnd = 101; Pid = 42; Class = "Chrome_WidgetWin_1"; Exists = $true; Visible = $true; Owner = 100 }
Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $root @($root, $popup) 100
Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $root @($root) 100
function Must-Reject($action) {
  $rejected = $false
  try { & $action } catch { $rejected = $true }
  if (-not $rejected) { throw "Invalid prepared window was accepted." }
}
foreach ($change in @(@{ Exists = $false }, @{ Hwnd = 102 }, @{ Pid = 43 }, @{ Class = "Other" }, @{ Visible = $false }, @{ Owner = 101 })) {
  $invalid = $root.Clone()
  foreach ($key in $change.Keys) { $invalid[$key] = $change[$key] }
  Must-Reject { Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $invalid @($invalid) 100 }
}
Must-Reject { Assert-PreparedWindowFacts 0 "638000000000000000" "638000000000000000" 42 $root @($root) 100 }
Must-Reject { Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000001" 42 $root @($root) 100 }
Must-Reject { Assert-PreparedWindowFacts 100 "invalid" "invalid" 42 $root @($root) 100 }
Must-Reject { Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $root @($root, $popup) 101 }
$unrelated = $popup.Clone(); $unrelated.Owner = 0
Must-Reject { Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $root @($root, $unrelated) 100 }
$wrongPid = $popup.Clone(); $wrongPid.Pid = 43
Must-Reject { Assert-PreparedWindowFacts 100 "638000000000000000" "638000000000000000" 42 $root @($root, $wrongPid) 100 }
Write-Output "Prepared window binding: two valid and twelve negative cases passed; no native input."
