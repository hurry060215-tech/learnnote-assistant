param(
  [Parameter(Mandatory = $true)][int]$OwnedBrowserPid,
  [ValidateSet("reset", "200")][string]$Zoom = "reset"
)
$ErrorActionPreference = "Stop"
# This helper accepts only the disposable browser process started by the test.
# It never uses the arbitrary foreground window, changes permissions, or reads a
# user profile. Extension warning/permission dialogs are outside this test.
if ($OwnedBrowserPid -le 0) { throw "An owned Edge process ID is required." }
$process = Get-Process -Id $OwnedBrowserPid -ErrorAction Stop
if ($process.ProcessName -ne "msedge") { throw "The owned process is not Edge." }
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class TimelineZoomWindow {
  public delegate bool Callback(IntPtr window, IntPtr parameter);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr parameter);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder name, int length);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public static IntPtr[] OwnedWindows(uint process) {
    var windows = new List<IntPtr>();
    EnumWindows((window, _) => {
      uint owner; GetWindowThreadProcessId(window, out owner);
      var name = new StringBuilder(256); GetClassName(window, name, name.Capacity);
      if (owner == process && IsWindowVisible(window) && name.ToString() == "Chrome_WidgetWin_1") windows.Add(window);
      return true;
    }, IntPtr.Zero);
    return windows.ToArray();
  }
}
"@
$windows = @([TimelineZoomWindow]::OwnedWindows([uint32]$OwnedBrowserPid))
if ($windows.Count -ne 1) { throw "Expected exactly one visible window owned by the disposable Edge process." }
$window = $windows[0]
[void][TimelineZoomWindow]::SetForegroundWindow($window)
Start-Sleep -Milliseconds 200
function Send-OwnedZoomKey([string]$keys) {
  [uint32]$owner = 0
  [void][TimelineZoomWindow]::GetWindowThreadProcessId($window, [ref]$owner)
  if ($owner -ne $OwnedBrowserPid -or [TimelineZoomWindow]::GetForegroundWindow() -ne $window) {
    throw "Owned Edge window lost focus; no keyboard input sent."
  }
  [System.Windows.Forms.SendKeys]::SendWait($keys)
  Start-Sleep -Milliseconds 150
}
Send-OwnedZoomKey "^0"
if ($Zoom -eq "200") {
  # Browser-native presets: 100, 110, 125, 150, 175, 200 percent.
  1..5 | ForEach-Object { Send-OwnedZoomKey "^{ADD}" }
}
@{ owned_pid = $OwnedBrowserPid; window = $window.ToInt64(); requested_percent = $(if ($Zoom -eq "200") { 200 } else { 100 }) } | ConvertTo-Json -Compress
