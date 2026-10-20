# Launch the full server stack + client and verify the login actually completes.
#
# Round 65 lost its result because Start-Process was given -ArgumentList twice, so the
# auth service never started. This script passes argument arrays, then checks the
# evidence log for the events that prove the login ran to completion before anything
# else is measured.
#
#   pwsh -NoProfile -File tools\run_verified.ps1 -RunId 20261024-verify -Seconds 120

param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [int]$Seconds = 120,
    [string]$ClientDir = "runtime\client-1604220",
    [switch]$SkipWait
)

$ErrorActionPreference = "Stop"
$root = "E:\GAME\COD\codol-airedux\319"
Set-Location $root

$runDir = Join-Path "runs" $RunId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $runDir "screens") | Out-Null

$env:LSG_ZEROFRAME = '0'
$budget = $Seconds + 15

Write-Host "[1/5] cleaning stale processes"
Get-Process -Name codoMP_client_shipRetail, IIPSHostApp -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like "*Python*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "[2/5] starting lobby_udp / auth / lsg"
$udpArgs = @("-m", "server319.lobby_udp", "3074", "$budget", "$runDir\lobby_udp.jsonl")
$authArgs = @(
    "-m", "server319",
    "--client-dir", $ClientDir,
    "--auth",
    "--cert", "runs\20261022-tls-selfsigned\auth.crt",
    "--key", "runs\20261022-tls-selfsigned\auth.key",
    "--port", "4175",
    "--seconds", "$budget",
    "--evidence", "$runDir\auth.jsonl"
)
$lsgArgs = @(
    "-m", "server319.lsg",
    "--cert", "runs\20261022-tls-selfsigned\auth.crt",
    "--key", "runs\20261022-tls-selfsigned\auth.key",
    "--port", "4174",
    "--log", "$runDir\lsg.jsonl",
    "--seconds", "$budget"
)

$udpProc = Start-Process -FilePath "python" -ArgumentList $udpArgs -PassThru -WindowStyle Hidden
$authProc = Start-Process -FilePath "python" -ArgumentList $authArgs -PassThru -WindowStyle Hidden
$lsgProc = Start-Process -FilePath "python" -ArgumentList $lsgArgs -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host "[3/5] checking listeners on 3074 / 4175 / 4174"
$listen = (netstat -an | Select-String -Pattern ":3074\s|:4175\s|:4174\s" | Select-Object -First 6)
if ($listen) { $listen | ForEach-Object { Write-Host "    $_" } } else { Write-Host "    WARNING: no listeners found" }

Write-Host "[4/5] applying runtime patches"
$patchArgs = @(
    "tools\patch_runtime.py",
    "--client-dir", $ClientDir,
    "--evidence", "$runDir\patch.json",
    "--patch", "0x403699:EB1F:741F",
    "--patch", "0x403659:909090909090:893540BA4A08",
    "--patch", "0x3F2A0A:B8BC0200009090:3DBC0200007407",
    "--patch", "0x3EE9DC:9090909090:E82F2F0100",
    "--patch", "0x37C860:C39090909090:558BEC83E4F8",
    "--patch", "0x20C649:B000:B001",
    "--patch", "0x7BA295:9090:7E1A",
    "--patch", "0x7BA29D:9090:7512",
    "--patch", "0x7BA276:9090:7439",
    "--patch", "0x7BAD4D:9090:7572",
    "--patch", "0x7ADC27:01000000:FEFFFFFF",
    "--patch", "0x7ADDE0:01000000:FEFFFFFF",
    "--patch", "0x7AE754:01000000:FEFFFFFF",
    "--patch", "0x7AE76C:01000000:FEFFFFFF",
    "--patch", "0x7AE7B0:01000000:FEFFFFFF",
    "--wait", "12",
    "--observe", "$Seconds"
)
$patchProc = Start-Process -FilePath "python" -ArgumentList $patchArgs -PassThru -WindowStyle Hidden

if ($SkipWait) {
    Write-Host "started; patch pid=$($patchProc.Id) auth pid=$($authProc.Id) lsg pid=$($lsgProc.Id)"
    return
}

Write-Host "[5/5] waiting for login to complete (up to 45 s)"
$verified = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path "$runDir\lsg.jsonl") {
        if (Select-String -Path "$runDir\lsg.jsonl" -Pattern "client_frame_verified" -Quiet) {
            $verified = $true
            Write-Host "    login verified after $($i + 1) s"
            break
        }
    }
}
if (-not $verified) {
    Write-Host "    WARNING: no client_frame_verified within 45 s - environment may be broken"
}

Write-Host "summary:"
Write-Host "  run dir        $runDir"
Write-Host "  login verified $verified"
Write-Host "  patch pid      $($patchProc.Id)"
Write-Host "  auth pid       $($authProc.Id)"
Write-Host "  lsg pid        $($lsgProc.Id)"
Write-Host "  udp pid        $($udpProc.Id)"
