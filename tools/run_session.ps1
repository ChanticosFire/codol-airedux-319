param(
    [Parameter(Mandatory)][string]$RunId,
    [int]$Seconds = 90,
    [int]$AuthPort = 4175,
    [string]$Cert = '',
    [string]$Key = ''
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
    throw "CERT_MISSING: expected $Cert and $Key (copy from a previous run's tls/ or regenerate with tools\stage_redirect.py)"
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

try {
    $patchLog = Join-Path $runDir 'patch.json'
    & python (Join-Path $workspace 'tools\patch_auth_bypass.py') `
        --client-dir $staged --evidence $patchLog `
        --wait 13 --observe $Seconds --game-args=-q
    Write-Host "patch/json: $patchLog"
} finally {
    if (-not $authProcess.HasExited) {
        Stop-Process -Id $authProcess.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ''
Write-Host 'Evidence:'
Get-ChildItem -LiteralPath $runDir -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object FullName, Length | Format-Table -AutoSize | Out-String
Write-Host 'Next: check whether the client connected to 127.0.0.1:4174 (LSG) or sent'
Write-Host 'a /v1.0/title/1002/... request; if not, the lobby trigger (likely a'
Write-Host 'UI/input step) is the next hypothesis. See PROJECT_STATUS.md section 9.'
