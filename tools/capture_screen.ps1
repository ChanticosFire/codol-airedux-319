param(
    [Parameter(Mandatory)][string]$OutFile,
    [string]$WindowClass = 'CODO',
    [int]$DelayMs = 1500
)
# Bring the game window to the foreground and capture the desktop.
# PrintWindow returns black for this Direct3D client, so a real screen grab is
# the only reliable evidence of what is rendered.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class ScreenCap {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
"@
$script:target = [IntPtr]::Zero
$callback = [ScreenCap+EnumWindowsProc]{
    param($hWnd, $lParam)
    $cls = New-Object System.Text.StringBuilder 256
    [void][ScreenCap]::GetClassName($hWnd, $cls, 256)
    if ($cls.ToString() -eq $WindowClass -and [ScreenCap]::IsWindowVisible($hWnd)) {
        $script:target = $hWnd
        return $false
    }
    return $true
}
[void][ScreenCap]::EnumWindows($callback, [IntPtr]::Zero)
if ($script:target -eq [IntPtr]::Zero) { throw "no visible $WindowClass window" }
[void][ScreenCap]::ShowWindow($script:target, 9)
[void][ScreenCap]::SetWindowPos($script:target, [IntPtr]::new(-1), 0, 0, 0, 0, 0x0001 -bor 0x0002)  # HWND_TOPMOST, NOSIZE|NOMOVE
[void][ScreenCap]::SetForegroundWindow($script:target)
Start-Sleep -Milliseconds $DelayMs
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$graphics.Dispose()
$full = [IO.Path]::GetFullPath($OutFile)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($full)) | Out-Null
$bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
[pscustomobject]@{ path = $full; width = $bounds.Width; height = $bounds.Height; hwnd = $script:target.ToInt64() } | ConvertTo-Json -Compress
