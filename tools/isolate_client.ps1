param(
    [Parameter(Mandatory)][ValidateSet('Install','Verify','Remove')][string]$Action,
    [Parameter(Mandatory)][string]$ClientRoot,
    [Parameter(Mandatory)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($ClientRoot).TrimEnd('\')
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$allowed = Join-Path $workspace 'runtime\client-1649370'
if ($root -ne $allowed) { throw 'CLIENT_ROOT_NOT_OWNED_STAGE' }
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'CLIENT_ROOT_MISSING' }
if (-not $evidence.StartsWith((Join-Path $workspace 'runs') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
foreach ($candidate in @($root, $evidence)) {
    $cursor = $candidate
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'REPARSE_POINT' }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}
$expect = @{
    'codoMP_client_shipRetail.exe' = '36997674B18F2896DE5E9D755686F6922AF10708F355175714058D0A0172B537'
    'codoMP_client_shipRetailBase.dll' = 'EF75220DE1D6973F34C7069F5BF211B11BD61520C6C0DE1882F7359FA5BC6A20'
}
foreach ($name in $expect.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $root $name) -Algorithm SHA256).Hash -ne $expect[$name]) { throw "IDENTITY_MISMATCH:$name" }
}
if ($Action -ne 'Remove' -and @(Get-NetFirewallProfile -PolicyStore ActiveStore | Where-Object {-not $_.Enabled}).Count) { throw 'FIREWALL_PROFILE_DISABLED' }
$exes = @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.exe')
if (@(Get-ChildItem -LiteralPath $root -Recurse -Force | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'REPARSE_POINT' }
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$receipt = Join-Path $evidence 'firewall.json'
if ($Action -eq 'Install') { throw 'LOOPBACK_NOT_ISOLATED: program firewall rules did not block 127.0.0.1 on this host; use a separately verified network-isolated environment' }
switch ($Action) {
    'Install' {
        if (Test-Path -LiteralPath $receipt) { throw 'RECEIPT_EXISTS' }
        $group = 'CODOL-1649370-' + [guid]::NewGuid().ToString('N')
        $rules = @()
        $i = 0
        foreach ($exe in $exes) {
            foreach ($family in @('v4','v6')) {
                $i++
                $ranges = if ($family -eq 'v4') { @('0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255') } else { @('::/1','8000::/1') }
                $rules += @{ name = "$group-$i"; program = $exe.FullName; remote = $ranges }
            }
        }
        @{ group=$group; root=$root; rules=$rules; created_utc=[datetime]::UtcNow.ToString('o') } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receipt -Encoding utf8
        try {
            foreach ($rule in $rules) {
                New-NetFirewallRule -Name $rule.name -DisplayName $rule.name -Group $group -Direction Outbound -Action Block -Program $rule.program -RemoteAddress $rule.remote -Protocol Any -Profile Any -Enabled True | Out-Null
            }
            if (@(Get-NetFirewallRule -PolicyStore ActiveStore -Group $group).Count -ne $rules.Count) { throw 'ACTIVE_RULE_COUNT_MISMATCH' }
            @{ success=$true; action='Install'; rules=$rules.Count; executables=$exes.Count; utc=[datetime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'install-result.json') -Encoding utf8
        } catch {
            # Only this new unique group is removed on a failed install.
            Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            @{ success=$false; action='Install'; error=$_.Exception.Message; utc=[datetime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'install-result.json') -Encoding utf8
            throw
        }
    }
    'Verify' {
        if (-not (Test-Path -LiteralPath $receipt)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receipt | ConvertFrom-Json
        if ($saved.root -ne $root -or $saved.rules.Count -ne 2 * $exes.Count) { throw 'OWNERSHIP_OR_COUNT_MISMATCH' }
        if (@(Compare-Object @($exes.FullName | Sort-Object -Unique) @($saved.rules.program | Sort-Object -Unique)).Count) { throw 'EXECUTABLE_SET_CHANGED' }
        foreach ($spec in $saved.rules) {
            $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $spec.name -ErrorAction Stop
            if ($rule.Group -ne $saved.group -or $rule.Enabled -ne 'True' -or $rule.Action -ne 'Block' -or $rule.Direction -ne 'Outbound') { throw 'RULE_STATE_MISMATCH' }
            if (($rule | Get-NetFirewallApplicationFilter).Program -ne $spec.program) { throw 'RULE_PROGRAM_MISMATCH' }
            if (@(Compare-Object @($spec.remote | Sort-Object) @((($rule | Get-NetFirewallAddressFilter).RemoteAddress) | Sort-Object)).Count) { throw 'RULE_ADDRESS_MISMATCH' }
        }
        @{ success=$true; action='Verify'; rules=$saved.rules.Count; executables=$exes.Count; utc=[datetime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'verify-result.json') -Encoding utf8
    }
    'Remove' {
        if (-not (Test-Path -LiteralPath $receipt)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receipt | ConvertFrom-Json
        if ($saved.root -ne $root) { throw 'ROOT_OWNERSHIP_MISMATCH' }
        foreach ($spec in $saved.rules) {
            $rule = Get-NetFirewallRule -Name $spec.name -ErrorAction SilentlyContinue
            if ($rule) {
                if ($rule.Group -ne $saved.group -or ($rule | Get-NetFirewallApplicationFilter).Program -ne $spec.program) { throw 'RULE_OWNERSHIP_MISMATCH' }
                $rule | Remove-NetFirewallRule
            }
        }
        if (@(Get-NetFirewallRule -Group $saved.group -ErrorAction SilentlyContinue).Count) { throw 'REMOVAL_INCOMPLETE' }
        @{ success=$true; action='Remove'; utc=[datetime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'remove-result.json') -Encoding utf8
    }
}
