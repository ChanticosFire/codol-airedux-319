param(
    [string]$WindowClass = 'CODO',
    [ValidateSet('ENTER', 'SPACE', 'ESC', 'CLICK', 'ALT_ENTER')][string]$Action = 'ENTER',
    [int]$Count = 3,
    [int]$IntervalMs = 1500
)
# Send input to the game window (used to advance the lobby state machine).
#
# LSG connect is dispatched by a state machine (vtable 0xD5A0D8 -> 0xB98B70)
# only when the game reaches the right state; a patched client sitting on the
# CODO window with no input does not connect. This helper focuses the window and
# sends one of a few safe inputs.
#
# Must run elevated (the client runs elevated); Win32 input injection across
# integrity levels is blocked otherwise.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class GameInput {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint attach, uint attachTo, bool flag);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetActiveWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
$script:target = [IntPtr]::Zero
$callback = [GameInput+EnumWindowsProc]{
    param($hWnd, $lParam)
    $cls = New-Object System.Text.StringBuilder 256
    [void][GameInput]::GetClassName($hWnd, $cls, 256)
    if ($cls.ToString() -eq $WindowClass -and [GameInput]::IsWindowVisible($hWnd)) {
        $script:target = $hWnd
        return $false
    }
    return $true
}
[void][GameInput]::EnumWindows($callback, [IntPtr]::Zero)
if ($script:target -eq [IntPtr]::Zero) { throw "no visible $WindowClass window" }

$targetThread = [GameInput]::GetWindowThreadProcessId($script:target, [IntPtr]::Zero)
$currentThread = [GameInput]::GetCurrentThreadId()
[void][GameInput]::AttachThreadInput($currentThread, $targetThread, $true)
try {
    [void][GameInput]::ShowWindow($script:target, 9)
    [void][GameInput]::BringWindowToTop($script:target)
    [void][GameInput]::SetActiveWindow($script:target)
    [void][GameInput]::SetForegroundWindow($script:target)
} finally {
    [void][GameInput]::AttachThreadInput($currentThread, $targetThread, $false)
}
Start-Sleep -Milliseconds 600

for ($i = 0; $i -lt $Count; $i++) {
    switch ($Action) {
        'ENTER' { [System.Windows.Forms.SendKeys]::SendWait('{ENTER}') }
        'SPACE' { [System.Windows.Forms.SendKeys]::SendWait(' ') }
        'ESC' { [System.Windows.Forms.SendKeys]::SendWait('{ESC}') }
        'ALT_ENTER' { [System.Windows.Forms.SendKeys]::SendWait('%{ENTER}') }
        'CLICK' {
            $rect = New-Object GameInput+RECT
            [void][GameInput]::GetClientRect($script:target, [ref]$rect)
            $point = New-Object GameInput+POINT
            $point.X = [int](($rect.Right - $rect.Left) / 2)
            $point.Y = [int](($rect.Bottom - $rect.Top) / 2)
            [void][GameInput]::ClientToScreen($script:target, [ref]$point)
            [void][GameInput]::SetCursorPos($point.X, $point.Y)
            Start-Sleep -Milliseconds 150
            [GameInput]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)  # LEFTDOWN
            [GameInput]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)  # LEFTUP
        }
    }
    Write-Host "sent $Action $($i + 1)/$Count"
    Start-Sleep -Milliseconds $IntervalMs
}
