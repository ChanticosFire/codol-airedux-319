param([Parameter(Mandatory)][string]$EvidenceDir)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
if (-not $evidence.StartsWith((Join-Path $workspace 'runs') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$taskName = 'CODOL-Medium-Probe-' + [guid]::NewGuid().ToString('N')
$output = Join-Path $evidence 'scheduled-medium-output.txt'
$probe = Join-Path $evidence 'scheduled-medium-child.ps1'
@'
$groups = whoami /groups
$groups | Set-Content -LiteralPath '__OUTPUT__' -Encoding utf8
'@.Replace('__OUTPUT__', $output.Replace("'", "''")) | Set-Content -LiteralPath $probe -Encoding utf8
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$probe`""
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (-not (Test-Path -LiteralPath $output) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
    $task = Get-ScheduledTaskInfo -TaskName $taskName
    $label = if (Test-Path -LiteralPath $output) { @(Get-Content -LiteralPath $output | Where-Object { $_ -match 'Mandatory Level' } | ForEach-Object { [string]$_ }) } else { @() }
    @{ task=$taskName; output_exists=(Test-Path -LiteralPath $output); mandatory_label=$label; last_task_result=$task.LastTaskResult; utc=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'scheduled-medium-result.json') -Encoding utf8
} finally {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}
