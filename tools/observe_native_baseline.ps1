param(
    [Parameter(Mandatory)][string]$EvidenceDir,
    [ValidateRange(5,120)][int]$Seconds = 40
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$root = Join-Path $workspace 'runtime\client-1649370'
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
if (-not $evidence.StartsWith((Join-Path $workspace 'runs') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { throw 'EVIDENCE_MISSING' }
$token = whoami /groups | Select-String 'S-1-16-8192'
if (-not $token -or ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'MEDIUM_TOKEN_REQUIRED' }
$receipt = Get-Content -Raw -LiteralPath (Join-Path $evidence 'firewall.json') | ConvertFrom-Json
$verified = Get-Content -Raw -LiteralPath (Join-Path $evidence 'verify-result.json') | ConvertFrom-Json
if ($receipt.root -ne $root -or -not $verified.success -or $verified.rules -ne $receipt.rules.Count) { throw 'FIREWALL_RECEIPT_INVALID' }
if (@(Get-NetFirewallRule -PolicyStore ActiveStore -Group $receipt.group).Count -ne $receipt.rules.Count) { throw 'FIREWALL_NOT_ACTIVE' }
$exe = Join-Path $root 'codoMP_client_shipRetail.exe'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne '36997674B18F2896DE5E9D755686F6922AF10708F355175714058D0A0172B537') { throw 'EXE_IDENTITY_MISMATCH' }
if (@(Get-Process codoMP_client_shipRetail -ErrorAction SilentlyContinue).Count) { throw 'GAME_ALREADY_RUNNING' }

$events = New-Object System.Collections.Generic.List[object]
$owned = New-Object System.Collections.Generic.List[int]
$started = [DateTime]::UtcNow
try {
    $process = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    $owned.Add($process.Id)
    $events.Add(@{event='started';pid=$process.Id;created_utc=$process.StartTime.ToUniversalTime().ToString('o');utc=[DateTime]::UtcNow.ToString('o')})
    for ($elapsed = 0; $elapsed -lt $Seconds; $elapsed++) {
        Start-Sleep -Seconds 1
        $live = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($process.Id)" -ErrorAction SilentlyContinue | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) })
        foreach ($child in $children) { if (-not $owned.Contains([int]$child.ProcessId)) { $owned.Add([int]$child.ProcessId) } }
        if ($elapsed -in @(0,2,5,10,20,30,39) -or -not $live) {
            $pids = @($owned.ToArray())
            $connections = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $pids -contains $_.OwningProcess } | ForEach-Object { @{pid=$_.OwningProcess;local="$($_.LocalAddress):$($_.LocalPort)";remote="$($_.RemoteAddress):$($_.RemotePort)";state=[string]$_.State} })
            $events.Add(@{event='sample';elapsed_s=$elapsed+1;alive=[bool]$live;window_title=if($live){$live.MainWindowTitle}else{''};window_handle=if($live){[int64]$live.MainWindowHandle}else{0};owned_pids=$pids;tcp=$connections;utc=[DateTime]::UtcNow.ToString('o')})
        }
        if (-not $live) { break }
    }
} catch {
    $events.Add(@{event='error';error=$_.Exception.GetType().FullName;message=$_.Exception.Message;utc=[DateTime]::UtcNow.ToString('o')})
    throw
} finally {
    foreach ($pidOwned in @($owned.ToArray() | Sort-Object -Descending)) {
        $target = Get-Process -Id $pidOwned -ErrorAction SilentlyContinue
        if ($target -and $target.Path -and $target.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Process -Id $pidOwned -Force -ErrorAction SilentlyContinue
            $events.Add(@{event='stop_owned';pid=$pidOwned;utc=[DateTime]::UtcNow.ToString('o')})
        }
    }
    $events.Add(@{event='final';remaining_owned=@(Get-Process -Id $owned.ToArray() -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object Id);utc=[DateTime]::UtcNow.ToString('o')})
    @{build=1649370;root=$root;started_utc=$started.ToString('o');seconds=$Seconds;events=$events} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'native-observation.json') -Encoding utf8
}
