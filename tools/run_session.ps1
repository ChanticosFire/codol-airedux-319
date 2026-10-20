param(
    [Parameter(Mandatory)][string]$RunId,
    [int]$Seconds = 90,
    [int]$AuthPort = 4175,
    [int]$LsgPort = 4174,
    [string]$Cert = '',
    [string]$Key = '',
    [ValidateSet('', 'ENTER', 'CLICK', 'SPACE', 'ESC')][string]$AutoInput = '',
    [int]$InputInterval = 8,
    [int]$InputCount = 6
)
# One-shot session runner for Build 1649370.
#
# Run this from an ELEVATED PowerShell (the client needs an elevated token for
# IIPS to initialize; a Medium token always stops at 初始化IIPS错误：8189fec).
#
#   pwsh -NoProfile -File tools\run_session.ps1 -RunId 20261020-session01 -Seconds 90
#
# What it does:
#   1. verifies the four Build anchors in the staged copy;
#   2. starts the server319 Auth endpoint on 127.0.0.1 (TLS<=1.2, legacy suites);
#   3. launches the client with -q and applies the runtime ticket-gate patch
#      (RVA 0x79A78E: 74 B2 -> 90 90) inside the process image only;
#   4. records auth JSONL, patch JSON, TCP/window samples under runs\<RunId>;
#   5. stops the Auth endpoint and prints the evidence paths.
#
# It does not change firewall, proxy, DNS or any system network setting, does
# not modify client files, and does not load drivers.

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$runDir = Join-Path $workspace ("runs\" + $RunId)
$staged = Join-Path $workspace 'runtime\client-1649370'
if (-not (Test-Path -LiteralPath (Join-Path $staged 'codoMP_client_shipRetail.exe'))) { throw 'STAGED_CLIENT_MISSING' }
[IO.Directory]::CreateDirectory($runDir) | Out-Null

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'WARNING: not elevated. IIPS will fail with 8189fec before Auth. Re-run from an elevated PowerShell.' -ForegroundColor Yellow
}
if (-not $Cert) { $Cert = Join-Path $runDir 'tls\auth.crt' }
if (-not $Key) { $Key = Join-Path $runDir 'tls\auth.key' }
if (-not (Test-Path -LiteralPath $Cert) -or -not (Test-Path -LiteralPath $Key)) {
    # Fall back to the newest certificate under runs\<id>\tls so a fresh RunId
    # works without manual -Cert/-Key flags.
    $found = Get-ChildItem (Join-Path $workspace 'runs') -Recurse -Filter 'auth.crt' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) {
        $srcDir = Split-Path -Parent $found.FullName
        $srcKey = Join-Path $srcDir 'auth.key'
        if (Test-Path -LiteralPath $srcKey) {
            $targetDir = Split-Path -Parent $Cert
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
            Copy-Item -LiteralPath $found.FullName -Destination $Cert -Force
            Copy-Item -LiteralPath $srcKey -Destination $Key -Force
            Write-Host "cert auto-copied from $srcDir"
        }
    }
}
if (-not (Test-Path -LiteralPath $Cert) -or -not (Test-Path -LiteralPath $Key)) {
    throw "CERT_MISSING: no auth.crt/auth.key under runs\*\tls; pass -Cert/-Key or run tools\stage_redirect.py first"
}

Write-Host "run dir: $runDir"
$authLog = Join-Path $runDir 'auth.jsonl'
$authProcess = Start-Process -FilePath 'python' `
    -ArgumentList @('-m', 'server319', '--client-dir', $staged, '--auth',
                    '--cert', $Cert, '--key', $Key, '--port', $AuthPort,
                    '--seconds', ($Seconds + 40), '--evidence', $authLog) `
    -WorkingDirectory $workspace -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
if ($authProcess.HasExited) { throw 'AUTH_SERVER_EXITED: check python/server319 output' }
Write-Host "auth listening on 127.0.0.1:$AuthPort (pid $($authProcess.Id))"

# LSG (lobby) listener on the dwauth.ini line-1 port. The client opens this
# channel right after Auth; without it the game shows the in-client
# "[100]无法连接大厅服务！" dialog and quits.
$lsgLog = Join-Path $runDir 'lsg.jsonl'
$lsgProcess = Start-Process -FilePath 'python' `
    -ArgumentList @('-m', 'server319.lsg', '--cert', $Cert, '--key', $Key,
                    '--port', $LsgPort, '--log', $lsgLog, '--seconds', ($Seconds + 40)) `
    -WorkingDirectory $workspace -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
if ($lsgProcess.HasExited) { throw 'LSG_SERVER_EXITED: check python/server319.lsg output' }
Write-Host "lsg listening on 127.0.0.1:$LsgPort (pid $($lsgProcess.Id))"

$inputJob = $null

try {
    if ($AutoInput) {
        $inputJob = Start-Job -ScriptBlock {
            param($cwd, $action, $interval, $count)
            Set-Location $cwd
            Start-Sleep -Seconds 20
            for ($i = 0; $i -lt $count; $i++) {
                & pwsh -NoProfile -File 'tools\send_input.ps1' -Action $action -Count 1 2>&1 | Out-Null
                Start-Sleep -Seconds $interval
            }
        } -ArgumentList $workspace, $AutoInput, $InputInterval, $InputCount
        Write-Host "auto-input: $AutoInput every ${InputInterval}s x $InputCount (starting after 20s)"
    }
    $patchLog = Join-Path $runDir 'patch.json'
    & python (Join-Path $workspace 'tools\patch_auth_bypass.py') `
        --client-dir $staged --evidence $patchLog `
        --wait 13 --observe $Seconds --game-args=-q
    Write-Host "patch/json: $patchLog"
} finally {
    if ($inputJob) {
        Stop-Job $inputJob -ErrorAction SilentlyContinue
        Remove-Job $inputJob -Force -ErrorAction SilentlyContinue
    }
    if (-not $authProcess.HasExited) {
        Stop-Process -Id $authProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($lsgProcess -and -not $lsgProcess.HasExited) {
        Stop-Process -Id $lsgProcess.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ''
Write-Host 'Evidence:'
Get-ChildItem -LiteralPath $runDir -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object FullName, Length | Format-Table -AutoSize | Out-String
Write-Host 'Next: check whether the client connected to 127.0.0.1:4174 (LSG) or sent'
Write-Host 'a /v1.0/title/1002/... request; if not, the lobby trigger (likely a'
Write-Host 'UI/input step) is the next hypothesis. See PROJECT_STATUS.md section 9.'
