param(
    [Parameter(Mandatory)][ValidateSet('Install','Remove')][string]$Action,
    [Parameter(Mandatory)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
if (-not $evidence.StartsWith((Join-Path $workspace 'runs') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { throw 'EVIDENCE_MISSING' }
$program = Join-Path $env:SystemRoot 'System32\curl.exe'
$address = '127.0.0.0-127.255.255.255'
$receiptPath = Join-Path $evidence 'loopback-probe-rule.json'
if ($Action -eq 'Install') {
    if (Test-Path -LiteralPath $receiptPath) { throw 'RECEIPT_EXISTS' }
    $name = 'CODOL-Loopback-Probe-' + [guid]::NewGuid().ToString('N')
    @{name=$name;program=$program;address=$address;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
    try {
        New-NetFirewallRule -Name $name -DisplayName $name -Group $name -Direction Outbound -Action Block -Program $program -RemoteAddress $address -Protocol Any -Profile Any -Enabled True | Out-Null
        $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction Stop
        if ($rule.Action -ne 'Block' -or ($rule | Get-NetFirewallApplicationFilter).Program -ne $program) { throw 'RULE_MISMATCH' }
    } catch {
        Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        throw
    }
} else {
    if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'RECEIPT_MISSING' }
    $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if ($saved.program -ne $program -or $saved.address -ne $address -or $saved.name -notlike 'CODOL-Loopback-Probe-*') { throw 'OWNERSHIP_MISMATCH' }
    $rule = Get-NetFirewallRule -Name $saved.name -ErrorAction SilentlyContinue
    if ($rule) {
        if ($rule.Group -ne $saved.name -or ($rule | Get-NetFirewallApplicationFilter).Program -ne $program) { throw 'RULE_OWNERSHIP_MISMATCH' }
        $rule | Remove-NetFirewallRule
    }
    if (Get-NetFirewallRule -Name $saved.name -ErrorAction SilentlyContinue) { throw 'REMOVAL_INCOMPLETE' }
    @{removed=$true;name=$saved.name;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'loopback-probe-remove.json') -Encoding utf8
}
