param(
    [Parameter(Mandatory)][string]$RunId,
    [int]$Seconds = 100
)
# Run one session, force the CODO window to the foreground every few seconds
# (without sending any input), and capture the desktop so the lobby screen is
# actually visible instead of being covered by other windows.
$ErrorActionPreference = 'Stop'
$workspace = 'E:\GAME\COD\codol-airedux\319'
$runDir = Join-Path $workspace ("runs\" + $RunId)
New-Item -ItemType Directory -Force -Path (Join-Path $runDir 'screens') | Out-Null

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32Fg {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    public static IntPtr Find(string cls) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((h, l) => {
            var sb = new StringBuilder(256);
            GetClassName(h, sb, 256);
            if (sb.ToString() == cls && IsWindowVisible(h)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
"@

$shot = {
    param($runDir, $index)
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $bmp.Save((Join-Path $runDir ("screens\lobby-{0}.png" -f $index)), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}

$authJob = Start-Job -ScriptBlock {
    param($cwd)
    Set-Location $cwd
    python -m server319 --client-dir runtime\client-1649370 --auth `
        --cert runs\20261020-session03\tls\auth.crt --key runs\20261020-session03\tls\auth.key `
        --port 4175 --seconds ($using:Seconds + 60) --evidence "runs\$using:RunId\auth.jsonl"
} -ArgumentList $workspace
$lsgJob = Start-Job -ScriptBlock {
    param($cwd)
    Set-Location $cwd
    python -m server319.lsg --cert runs\20261020-session03\tls\auth.crt `
        --key runs\20261020-session03\tls\auth.key --port 4174 `
        --log "runs\$using:RunId\lsg.jsonl" --seconds ($using:Seconds + 60)
} -ArgumentList $workspace
Start-Sleep -Seconds 3

$game = Start-Job -ScriptBlock {
    param($cwd, $runId, $secs)
    Set-Location $cwd
    python tools\patch_auth_bypass.py --client-dir runtime\client-1649370 `
        --evidence "runs\$runId\patch.json" --wait 13 --observe $secs --game-args=-q
} -ArgumentList $workspace, $RunId, $Seconds

for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 9
    $hwnd = [Win32Fg]::Find('CODO')
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][Win32Fg]::ShowWindow($hwnd, 9)
        [void][Win32Fg]::BringWindowToTop($hwnd)
        [void][Win32Fg]::SetForegroundWindow($hwnd)
        Start-Sleep -Milliseconds 400
    }
    & $shot $runDir $i
}

Wait-Job $game -Timeout 60 | Out-Null
Stop-Job $game -ErrorAction SilentlyContinue
Remove-Job $game -Force -ErrorAction SilentlyContinue
Stop-Job $lsgJob -ErrorAction SilentlyContinue
Remove-Job $lsgJob -Force -ErrorAction SilentlyContinue
Stop-Job $authJob -ErrorAction SilentlyContinue
Remove-Job $authJob -Force -ErrorAction SilentlyContinue
Get-Process codoMP_client_shipRetail -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "done: $runDir"
