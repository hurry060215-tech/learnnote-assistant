param(
  [Parameter(Mandatory=$true)][int]$BrowserProcessId,
  [Parameter(Mandatory=$true)][ValidateSet('open-extension', 'allow', 'deny')][string]$Action,
  [Parameter(Mandatory=$true)][string]$EvidencePrefix,
  [string]$ExpectedHost = 'learnnote-permission.test'
)

# Windows UI Automation operates only this disposable browser's native controls.
# Web documents (including the extension document) are deliberately excluded.
# Never fall back to blind coordinates, keyboard shortcuts, or another process.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$scope = [System.Windows.Automation.TreeScope]
$control = [System.Windows.Automation.ControlType]
$condition = [System.Windows.Automation.PropertyCondition]::new(
  [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $BrowserProcessId)
$deadline = [DateTime]::UtcNow.AddSeconds(20)
$openedMenu = $false
$lastNames = @()

function Read-NativeTree($element, [int]$depth, $nodes) {
  if ($depth -gt 24 -or $nodes.Count -ge 2000) { return }
  $current = $element.Current
  if ($current.ProcessId -ne $BrowserProcessId -or $current.ControlType -eq $control::Document) { return }
  $nodes.Add($element)
  $child = $walker.GetFirstChild($element)
  while ($null -ne $child) {
    Read-NativeTree $child ($depth + 1) $nodes
    $child = $walker.GetNextSibling($child)
  }
}

function Invoke-Native($element) {
  if (-not $element.Current.IsEnabled -or $element.Current.IsOffscreen) { return $false }
  $pattern = $null
  if (-not $element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
    throw "Matched native control does not support InvokePattern. No input fallback was used."
  }
  $pattern.Invoke()
  return $true
}

function Save-Evidence($window, $nodes, [string]$selected) {
  $items = @($nodes | ForEach-Object {
    @{ name = $_.Current.Name; type = $_.Current.ControlType.ProgrammaticName;
       automation_id = $_.Current.AutomationId; enabled = $_.Current.IsEnabled }
  })
  @{ process_id = $BrowserProcessId; action = $Action; expected_host = $ExpectedHost;
     selected = $selected; native_controls = $items } |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 "$EvidencePrefix.json"
  $rect = $window.Current.BoundingRectangle
  if ($rect.Width -le 0 -or $rect.Height -le 0) { throw 'Native browser window has no visible bounds.' }
  $bitmap = [System.Drawing.Bitmap]::new([int]$rect.Width, [int]$rect.Height)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  try {
    $graphics.CopyFromScreen([int]$rect.X, [int]$rect.Y, 0, 0, $bitmap.Size)
    $bitmap.Save("$EvidencePrefix.png", [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $graphics.Dispose(); $bitmap.Dispose() }
}

while ([DateTime]::UtcNow -lt $deadline) {
  $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll($scope::Children, $condition)
  foreach ($window in $windows) {
    $nodes = New-Object 'System.Collections.Generic.List[System.Windows.Automation.AutomationElement]'
    Read-NativeTree $window 0 $nodes
    $lastNames = @($nodes | ForEach-Object { $_.Current.Name } | Where-Object { $_ })
    $buttons = @($nodes | Where-Object {
      ($_.Current.ControlType -eq $control::Button -or $_.Current.ControlType -eq $control::MenuItem) -and
      $_.Current.IsEnabled -and -not $_.Current.IsOffscreen
    })
    if ($Action -eq 'open-extension') {
      $matches = @($buttons | Where-Object {
        $_.Current.Name -match '^(LearnNote Current Video Assistant|Open the LearnNote current video assistant)(\b|$)'
      })
      if ($matches.Count -eq 1) {
        Save-Evidence $window $nodes $matches[0].Current.Name
        if (Invoke-Native $matches[0]) { Write-Output 'Native LearnNote action invoked'; exit 0 }
      }
      if (-not $openedMenu) {
        $menus = @($buttons | Where-Object { $_.Current.Name -eq 'Extensions' })
        if ($menus.Count -eq 1 -and (Invoke-Native $menus[0])) { $openedMenu = $true }
      }
    } else {
      # Require the extension, the exact synthetic host, and a permission warning
      # in native UI, with both decisions visible. A page cannot satisfy this.
      $text = $lastNames -join "`n"
      $allow = @($buttons | Where-Object { $_.Current.Name -eq 'Allow' })
      $deny = @($buttons | Where-Object { $_.Current.Name -match '^(Deny|Cancel)$' })
      if ($text -match 'LearnNote' -and $text.Contains($ExpectedHost) -and
          $text -match '(additional permissions|Confirm Permissions|Read and change|Access your data)' -and
          $allow.Count -eq 1 -and $deny.Count -eq 1) {
        $selected = if ($Action -eq 'allow') { $allow[0] } else { $deny[0] }
        Save-Evidence $window $nodes $selected.Current.Name
        if (Invoke-Native $selected) { Write-Output "Native permission decision: $Action"; exit 0 }
      }
    }
  }
  Start-Sleep -Milliseconds 250
}
if ($null -ne $window -and $null -ne $nodes -and $nodes.Count -gt 0) {
  Save-Evidence $window $nodes 'No control invoked: native match unavailable'
}
@{ process_id = $BrowserProcessId; action = $Action; expected_host = $ExpectedHost;
   blocker = 'No uniquely matched native control in the selected browser process';
   native_names = $lastNames } | ConvertTo-Json -Depth 4 |
   Set-Content -Encoding UTF8 "$EvidencePrefix-blocked.json"
throw "Native UI gate could not identify $Action in the isolated browser. See $EvidencePrefix-blocked.json."
