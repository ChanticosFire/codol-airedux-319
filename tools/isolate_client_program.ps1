param(
    [Parameter(Mandatory)][ValidateSet('Install','Verify','Remove')][string]$Action,
    [Parameter(Mandatory)][string]$ClientRoot,
    [Parameter(Mandatory)][string]$EvidenceDir
)
# Program-scoped outbound block for the owned 1649370 copy.
#
# This replaces the host-wide "block all outbound" rule. It creates one
# Outbound/Block rule per executable under the staged client root, so DSH, the
# editor, browsers and every other program keep their normal network access.
#
# Known limitation, already measured on this host: Windows Firewall does not
# evaluate loopback traffic, so a program rule cannot stop the client from
# reaching a local HTTP proxy such as 127.0.0.1:7890. Combine this rule set with
# system-proxy off and no listening local proxy when the goal is "no external
# route from the client"; do not claim loopback isolation from these rules.
#
# Contract:
#   - Install/Remove require an elevated token.
#   - Only executables under the staged copy are affected.
#   - Only the receipt's unique rule group is ever removed.
#   - Receipts live under runs/ and are never committed.

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$allowed = (Join-Path $workspace 'runtime\client-1649370')
$root = [IO.Path]::GetFullPath($ClientRoot).TrimEnd('\')
if ($root -ne $allowed) { throw 'CLIENT_ROOT_NOT_OWNED_STAGE' }
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'CLIENT_ROOT_MISSING' }
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
if (-not $evidence.StartsWith((Join-Path $workspace 'runs') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$receiptPath = Join-Path $evidence 'program-isolation.json'
$resultPath = Join-Path $evidence ("program-isolation-$($Action.ToLower()).json")

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Write-Result([hashtable]$payload) {
    $payload['action'] = $Action
    $payload['utc'] = [DateTime]::UtcNow.ToString('o')
    $payload['elevated'] = $isAdmin
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding utf8
}

function Get-ClientExecutables {
    @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.exe' -ErrorAction Stop |
        Sort-Object FullName | ForEach-Object { $_.FullName })
}

switch ($Action) {
    'Install' {
        if (-not $isAdmin) { Write-Result @{ success = $false; error = 'ELEVATION_REQUIRED' }; exit 2 }
        if (Test-Path -LiteralPath $receiptPath) { throw 'RECEIPT_EXISTS' }
        $exes = Get-ClientExecutables
        if ($exes.Count -eq 0) { throw 'NO_EXECUTABLES' }
        $group = 'CODOL-319-PROG-' + [guid]::NewGuid().ToString('N')
        $rules = @()
        $index = 0
        foreach ($exe in $exes) {
            $index++
            $rules += @{ name = "$group-$index"; program = $exe }
        }
        @{ group = $group; root = $root; rules = $rules; created_utc = [DateTime]::UtcNow.ToString('o')
           identity = $identity.Name; executables = $exes.Count } |
            ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
        try {
            foreach ($rule in $rules) {
                New-NetFirewallRule -Name $rule.name -DisplayName ('CODOL Client Isolation ' + $rule.name) `
                    -Group $group -Direction Outbound -Action Block -Program $rule.program `
                    -Profile Any -Protocol Any -Enabled True -ErrorAction Stop | Out-Null
            }
            $active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Group $group -ErrorAction Stop)
            if ($active.Count -ne $rules.Count) { throw 'ACTIVE_RULE_COUNT_MISMATCH' }
            foreach ($rule in $active) {
                if ($rule.Enabled -ne 'True' -or $rule.Action -ne 'Block' -or $rule.Direction -ne 'Outbound') { throw 'RULE_STATE_MISMATCH' }
            }
            Write-Result @{ success = $true; group = $group; executables = $exes.Count; rules = $rules.Count
                            limitation = 'Windows Firewall does not evaluate loopback; this does not isolate 127.0.0.1 proxies.' }
        } catch {
            Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            Write-Result @{ success = $false; error = $_.Exception.Message; rolledBack = $true }
            exit 3
        }
        break
    }
    'Verify' {
        if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        if ($saved.root -ne $root) { throw 'ROOT_OWNERSHIP_MISMATCH' }
        $exes = Get-ClientExecutables
        $active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Group $saved.group -ErrorAction SilentlyContinue)
        $problems = @()
        if ($active.Count -ne $saved.rules.Count) { $problems += 'ACTIVE_RULE_COUNT_MISMATCH' }
        if (@(Compare-Object @($exes | Sort-Object -Unique) @($saved.rules.program | Sort-Object -Unique)).Count) { $problems += 'EXECUTABLE_SET_CHANGED' }
        foreach ($spec in $saved.rules) {
            $rule = $active | Where-Object { $_.Name -eq $spec.name }
            if (-not $rule) { $problems += "MISSING:$($spec.name)"; continue }
            if ($rule.Action -ne 'Block' -or $rule.Direction -ne 'Outbound' -or $rule.Enabled -ne 'True') { $problems += "STATE:$($spec.name)" }
            $program = ($rule | Get-NetFirewallApplicationFilter).Program
            if ($program -ne $spec.program) { $problems += "PROGRAM:$($spec.name)" }
        }
        $ok = $problems.Count -eq 0
        Write-Result @{ success = $ok; group = $saved.group; activeRules = $active.Count
                        expected = $saved.rules.Count; problems = $problems
                        limitation = 'loopback is not covered by Windows Firewall program rules' }
        if (-not $ok) { exit 3 }
        break
    }
    'Remove' {
        if (-not $isAdmin) { Write-Result @{ success = $false; error = 'ELEVATION_REQUIRED' }; exit 2 }
        if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        if ($saved.root -ne $root) { throw 'ROOT_OWNERSHIP_MISMATCH' }
        Get-NetFirewallRule -Group $saved.group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        $remaining = @(Get-NetFirewallRule -Group $saved.group -ErrorAction SilentlyContinue).Count
        Write-Result @{ success = ($remaining -eq 0); group = $saved.group; remainingRules = $remaining }
        if ($remaining -ne 0) { exit 3 }
        break
    }
}
