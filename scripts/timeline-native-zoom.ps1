param(
  [Parameter(Mandatory = $true)][int]$OwnedBrowserPid,
  [ValidateSet("reset", "200", "prepare", "capture")][string]$Zoom = "reset",
  [string]$CapturePath
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
  [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
  public delegate bool Callback(IntPtr window, IntPtr parameter);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr parameter);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder name, int length);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowDpiAwarenessContext(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetThreadDpiAwarenessContext();
  [DllImport("user32.dll")] public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out Rect rectangle, int size);
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
function Assert-OwnedForeground {
  [uint32]$owner = 0
  [void][TimelineZoomWindow]::GetWindowThreadProcessId($window, [ref]$owner)
  if ($owner -ne $OwnedBrowserPid -or [TimelineZoomWindow]::GetForegroundWindow() -ne $window) {
    throw "Owned Edge window lost focus; no keyboard input or capture performed."
  }
}
function Send-OwnedZoomKey([string]$keys) {
  Assert-OwnedForeground
  [System.Windows.Forms.SendKeys]::SendWait($keys)
  Start-Sleep -Milliseconds 150
}
if ($Zoom -in @("prepare", "capture")) {
  if ($Zoom -eq "capture" -and (-not $CapturePath -or [IO.Path]::GetExtension($CapturePath) -ne ".png")) { throw "An owned PNG output path is required." }
  Add-Type -AssemblyName System.Drawing
  $display = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $screens = @([System.Windows.Forms.Screen]::AllScreens)
  $windowAwareness = [TimelineZoomWindow]::GetAwarenessFromDpiAwarenessContext([TimelineZoomWindow]::GetWindowDpiAwarenessContext($window))
  $threadAwareness = [TimelineZoomWindow]::GetAwarenessFromDpiAwarenessContext([TimelineZoomWindow]::GetThreadDpiAwarenessContext())
  function Describe-Geometry($rectangle) {
    @{ dwm = @{ left = $rectangle.Left; top = $rectangle.Top; right = $rectangle.Right; bottom = $rectangle.Bottom };
       display = @{ left = $display.Left; top = $display.Top; width = $display.Width; height = $display.Height };
       window_dpi = [TimelineZoomWindow]::GetDpiForWindow($window); display_count = $screens.Count;
       window_dpi_awareness = $windowAwareness; helper_thread_dpi_awareness = $threadAwareness }
  }
  Assert-OwnedForeground
  $rect = New-Object TimelineZoomWindow+Rect
  if ([TimelineZoomWindow]::DwmGetWindowAttribute($window, 9, [ref]$rect, 16) -ne 0) { throw "Owned Edge window bounds unavailable." }
  # No DPI mode is changed. At one 96-DPI display, physical DWM and PowerShell
  # screen coordinates agree even if this helper's thread is DPI-unaware.
  if ($screens.Count -ne 1 -or $windowAwareness -lt 1 -or $threadAwareness -lt 0 -or
      [TimelineZoomWindow]::GetDpiForWindow($window) -ne 96 -or $display.Left -ne 0 -or $display.Top -ne 0 -or
      -not $display.Equals($screens[0].Bounds)) { throw "Native capture requires one verified 96-DPI display with matching physical/screen coordinates. Geometry: $(Describe-Geometry $rect | ConvertTo-Json -Depth 4 -Compress)" }
  function Read-OwnedBounds {
    Assert-OwnedForeground
    $current = New-Object TimelineZoomWindow+Rect
    # DWM visible bounds exclude invisible resize borders and use physical pixels.
    if ([TimelineZoomWindow]::GetDpiForWindow($window) -ne 96 -or
        [TimelineZoomWindow]::DwmGetWindowAttribute($window, 9, [ref]$current, 16) -ne 0) { throw "Owned Edge window bounds or 96-DPI coordinate contract changed." }
    return $current
  }
  function Assert-SameBounds($expected, $actual) {
    if ($expected.Left -ne $actual.Left -or $expected.Top -ne $actual.Top -or
        $expected.Right -ne $actual.Right -or $expected.Bottom -ne $actual.Bottom) {
      throw "Owned Edge window moved or resized; no screenshot saved. Before: $(Describe-Geometry $expected | ConvertTo-Json -Depth 4 -Compress) After: $(Describe-Geometry $actual | ConvertTo-Json -Depth 4 -Compress)"
    }
  }
  $initialGeometry = Describe-Geometry $rect
  if ($Zoom -eq "prepare") {
    # Fit only the already verified disposable window, before the zoom baseline.
    # Capture mode never moves/resizes a window or accepts a cropped rectangle.
    Assert-OwnedForeground
    [void][TimelineZoomWindow]::ShowWindow($window, 3) # SW_MAXIMIZE
    Start-Sleep -Milliseconds 250
    $rect = Read-OwnedBounds
  }
  $width = $rect.Right - $rect.Left
  $height = $rect.Bottom - $rect.Top
  $bounds = [System.Drawing.Rectangle]::new($rect.Left, $rect.Top, $width, $height)
  if ($width -le 0 -or $height -le 0 -or -not $display.Contains($bounds)) {
    throw "Owned Edge window is not wholly on the display; no partial capture accepted. Geometry: $(Describe-Geometry $rect | ConvertTo-Json -Depth 4 -Compress)"
  }
  if ($Zoom -eq "prepare") {
    @{ owned_pid = $OwnedBrowserPid; window = $window.ToInt64(); action = "prepare";
       method = "maximize-owned-window-before-baseline"; before = $initialGeometry;
       after = (Describe-Geometry $rect) } | ConvertTo-Json -Depth 5 -Compress
    exit 0
  }
  $bitmap = [System.Drawing.Bitmap]::new($width, $height)
  $graphics = $null
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $beforeCopy = Read-OwnedBounds
    Assert-SameBounds $rect $beforeCopy
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    $afterCopy = Read-OwnedBounds
    Assert-SameBounds $beforeCopy $afterCopy
    $bitmap.Save([IO.Path]::GetFullPath($CapturePath), [System.Drawing.Imaging.ImageFormat]::Png)
    $colors = [System.Collections.Generic.HashSet[int]]::new()
    for ($y = 0; $y -lt $height; $y += [Math]::Max(1, [int]($height / 40))) {
      for ($x = 0; $x -lt $width; $x += [Math]::Max(1, [int]($width / 40))) {
        [void]$colors.Add($bitmap.GetPixel($x, $y).ToArgb())
      }
    }
    if ($colors.Count -lt 2) { throw "Owned Edge window capture is blank." }
    @{ owned_pid = $OwnedBrowserPid; window = $window.ToInt64(); action = "capture";
       x = $rect.Left; y = $rect.Top; width = $width; height = $height; sampled_colors = $colors.Count;
       window_dpi = 96; display_count = $screens.Count; window_dpi_awareness = $windowAwareness;
       helper_thread_dpi_awareness = $threadAwareness; coordinate_contract = "single-display-96-dpi";
       bounds_stable = $true; geometry = (Describe-Geometry $rect) } | ConvertTo-Json -Depth 5 -Compress
  } finally { if ($graphics) { $graphics.Dispose() }; $bitmap.Dispose() }
  exit 0
}
Send-OwnedZoomKey "^0"
if ($Zoom -eq "200") {
  # Browser-native presets: 100, 110, 125, 150, 175, 200 percent.
  1..5 | ForEach-Object { Send-OwnedZoomKey "^{ADD}" }
}
@{ owned_pid = $OwnedBrowserPid; window = $window.ToInt64(); requested_percent = $(if ($Zoom -eq "200") { 200 } else { 100 }) } | ConvertTo-Json -Compress
