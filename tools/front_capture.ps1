param(
    [Parameter(Mandatory)][string]$OutFile,
    [string]$WindowClass = 'CODO',
    [int]$DelayMs = 1200
)
# Force the game window to the foreground (AttachThreadInput bypasses the
# foreground lock), then grab the desktop. PrintWindow is black for this D3D
# client, so a real screen capture is the only faithful evidence.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class FrontCap {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint attach, uint attachTo, bool attachFlag);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr SetActiveWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
$script:target = [IntPtr]::Zero
$callback = [FrontCap+EnumWindowsProc]{
    param($hWnd, $lParam)
    $cls = New-Object System.Text.StringBuilder 256
    [void][FrontCap]::GetClassName($hWnd, $cls, 256)
    if ($cls.ToString() -eq $WindowClass -and [FrontCap]::IsWindowVisible($hWnd)) {
        $script:target = $hWnd
        return $false
    }
    return $true
}
[void][FrontCap]::EnumWindows($callback, [IntPtr]::Zero)
if ($script:target -eq [IntPtr]::Zero) { throw "no visible $WindowClass window" }
$targetThread = [FrontCap]::GetWindowThreadProcessId($script:target, [IntPtr]::Zero)
$currentThread = [FrontCap]::GetCurrentThreadId()
[void][FrontCap]::AttachThreadInput($currentThread, $targetThread, $true)
try {
    [void][FrontCap]::ShowWindow($script:target, 9)
    [void][FrontCap]::SetWindowPos($script:target, [IntPtr]::new(-1), 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0040)
    [void][FrontCap]::BringWindowToTop($script:target)
    [void][FrontCap]::SetActiveWindow($script:target)
    [void][FrontCap]::SetForegroundWindow($script:target)
} finally {
    [void][FrontCap]::AttachThreadInput($currentThread, $targetThread, $false)
}
Start-Sleep -Milliseconds $DelayMs
$rect = New-Object FrontCap+RECT
[void][FrontCap]::GetWindowRect($script:target, [ref]$rect)
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$graphics.Dispose()
$full = [IO.Path]::GetFullPath($OutFile)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($full)) | Out-Null
$bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
[pscustomobject]@{ path = $full; hwnd = $script:target.ToInt64(); rect = "$($rect.Left),$($rect.Top),$($rect.Right),$($rect.Bottom)" } | ConvertTo-Json -Compress
