# Synthetic installed-acceptance evidence only: exact already-bound dialog HWND.
# PrintWindow renders that window alone; never capture the desktop or send input.
function Save-OwnedDialogCapture([IntPtr]$Dialog, [string]$Directory, [string]$Destination, [scriptblock]$Guard,
  [ValidateSet('dialog','foreground')][string]$Surface='dialog', $GuardContext=$null) {
  $phase='guard-before'; $bitmap=$null; $graphics=$null; $memory=$null; $stream=$null
  try {
    [void](& $Guard $GuardContext)
    $phase='destination'
    $directoryPath=[IO.Path]::GetFullPath($Directory); $destinationPath=[IO.Path]::GetFullPath($Destination)
    $outputPath=[IO.Path]::GetDirectoryName($directoryPath)
    $format=[IO.Path]::GetExtension($destinationPath).TrimStart('.')
    $filename='installed-current-'+$format+'-native-'+$Surface+'.png'; $targetPath=Join-Path $outputPath $filename
    if ($directoryPath -cne $Directory -or $destinationPath -cne $Destination -or $directoryPath -notmatch '^[A-Za-z]:\\' -or
        [IO.Path]::GetFileName($directoryPath) -notlike 'local-native-exports-*' -or
        [IO.Path]::GetDirectoryName($destinationPath) -cne $directoryPath -or
        [IO.Path]::GetFileName($destinationPath) -cnotin @('learnnote-diagnostics.md','learnnote-diagnostics.json') -or
        $filename -cnotin @('installed-current-md-native-dialog.png','installed-current-json-native-dialog.png',
          'installed-current-md-native-foreground.png','installed-current-json-native-foreground.png') -or
        !(Test-Path -LiteralPath $directoryPath -PathType Container) -or !(Test-Path -LiteralPath $outputPath -PathType Container) -or
        ((Get-Item -LiteralPath $directoryPath).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        ((Get-Item -LiteralPath $outputPath).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        (Test-Path -LiteralPath $targetPath)) { throw 'Capture destination rejected' }
    $phase='render'
    Add-Type -AssemblyName System.Drawing
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OwnedDialogPixels {
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
}
'@
    $phase='guard-before'; [void](& $Guard $GuardContext)
    $phase='bounds'; $before=[OwnedDialogPixels+RECT]::new()
    if (![OwnedDialogPixels]::GetWindowRect($Dialog,[ref]$before)) { throw 'Capture bounds unavailable' }
    $width=$before.Right-$before.Left; $height=$before.Bottom-$before.Top
    if ($width -lt 64 -or $width -gt 4096 -or $height -lt 64 -or $height -gt 4096) { throw 'Capture bounds rejected' }
    $phase='render'
    $bitmap=[Drawing.Bitmap]::new($width,$height,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics=[Drawing.Graphics]::FromImage($bitmap); $dc=$graphics.GetHdc()
    try { if (![OwnedDialogPixels]::PrintWindow($Dialog,$dc,2)) { throw 'Owned window rendering failed' } }
    finally { $graphics.ReleaseHdc($dc) }
    $graphics.Dispose(); $graphics=$null
    $phase='guard-after'; [void](& $Guard $GuardContext)
    $after=[OwnedDialogPixels+RECT]::new()
    if (![OwnedDialogPixels]::GetWindowRect($Dialog,[ref]$after) -or
        $before.Left -ne $after.Left -or $before.Top -ne $after.Top -or
        $before.Right -ne $after.Right -or $before.Bottom -ne $after.Bottom) { throw 'Capture bounds changed' }
    $phase='persist'
    $memory=[IO.MemoryStream]::new(); $bitmap.Save($memory,[Drawing.Imaging.ImageFormat]::Png)
    $stream=[IO.File]::Open($targetPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $memory.Position=0; $memory.CopyTo($stream); $stream.Dispose(); $stream=$null
    return @{status='saved';reason='captured';file=$filename;width=[int]$width;height=[int]$height}
  } catch {
    return @{status='unavailable';reason=$phase;file=$null;width=$null;height=$null}
  } finally {
    if ($stream) { $stream.Dispose() }; if ($memory) { $memory.Dispose() }
    if ($graphics) { $graphics.Dispose() }; if ($bitmap) { $bitmap.Dispose() }
  }
}
