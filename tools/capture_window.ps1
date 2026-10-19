param(
    [Parameter(Mandatory)][string]$OutFile,
    [string]$WindowClass = 'CODO',
    [string]$TitleFilter = '',
    [switch]$BringToFront
)
# Capture a specific window (even if occluded) with PrintWindow.
#
# PW_RENDERFULLCONTENT (2) is required for Direct3D/composited windows; plain
# PrintWindow returns black for those. The image is saved as PNG.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinCap {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
$script:found = @()
$callback = [WinCap+EnumWindowsProc]{
    param($hWnd, $lParam)
    $cls = New-Object System.Text.StringBuilder 256
    [void][WinCap]::GetClassName($hWnd, $cls, 256)
    if ($cls.ToString() -ne $WindowClass) { return $true }
    $title = New-Object System.Text.StringBuilder 512
    [void][WinCap]::GetWindowText($hWnd, $title, 512)
    if ($TitleFilter -and ($title.ToString() -notlike "*$TitleFilter*")) { return $true }
    if (-not [WinCap]::IsWindowVisible($hWnd)) { return $true }
    $script:found += [pscustomobject]@{ Handle = $hWnd; Class = $cls.ToString(); Title = $title.ToString() }
    return $true
}
[void][WinCap]::EnumWindows($callback, [IntPtr]::Zero)
if (-not $script:found.Count) { throw "no visible window with class $WindowClass" }
$target = $script:found[0]
if ($BringToFront) {
    [void][WinCap]::ShowWindow($target.Handle, 9)   # SW_RESTORE
    [void][WinCap]::SetForegroundWindow($target.Handle)
    Start-Sleep -Milliseconds 800
}
$rect = New-Object WinCap+RECT
[void][WinCap]::GetWindowRect($target.Handle, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) { throw "window has empty rect" }
$bmp = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $graphics.GetHdc()
$ok = [WinCap]::PrintWindow($target.Handle, $hdc, 2)
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()
if (-not $ok) { throw "PrintWindow failed" }
$full = [IO.Path]::GetFullPath($OutFile)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($full)) | Out-Null
$bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
[pscustomobject]@{ path = $full; class = $target.Class; title = $target.Title; width = $width; height = $height } |
    ConvertTo-Json -Compress
