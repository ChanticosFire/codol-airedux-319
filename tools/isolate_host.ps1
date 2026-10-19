param(
    [Parameter(Mandatory)][ValidateSet('Snapshot','Apply','Verify','Restore','Status')][string]$Action,
    [Parameter(Mandatory)][string]$EvidenceDir
)
# Build 1649370 lab host isolation.
#
# Why this replaces tools/isolate_client.ps1: per-program outbound rules were
# proven ineffective against 127.0.0.1:7890 on this host because Windows
# Firewall does not filter loopback traffic. This tool instead installs one
# high-priority "block all outbound" rule. Windows Firewall still does not
# evaluate loopback, so 127.0.0.1 services stay reachable while every external
# route (including a still-listening local HTTP proxy forwarding upstream) is
# blocked. Every step verifies that loopback survival explicitly and rolls back
# on failure.
#
# Contract:
#   - Apply/Restore require an elevated token; Snapshot/Status/Verify do not.
#   - Apply never edits firewall profile policy, GPO or registry. It adds one
#     rule in a uniquely named group and records that group in the receipt.
#   - Restore removes only the group recorded in this run's receipt.
#   - The receipt lives under runs/ and is never committed.
#
# Exit codes: 0 success, 2 refused preflight, 3 verification failure (rolled back).

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$evidence = [IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\')
$runsRoot = Join-Path $workspace 'runs'
if (-not $evidence.StartsWith($runsRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'EVIDENCE_OUTSIDE_RUNS' }
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$receiptPath = Join-Path $evidence 'host-isolation.json'
$resultPath = Join-Path $evidence ("host-isolation-$($Action.ToLower()).json")

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Write-Result([hashtable]$payload) {
    $payload['action'] = $Action
    $payload['utc'] = [DateTime]::UtcNow.ToString('o')
    $payload['elevated'] = $isAdmin
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding utf8
}

function Get-FirewallSummary {
    $profiles = @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {
        @{ name = $_.Name; enabled = [bool]$_.Enabled
           defaultInbound = [string]$_.DefaultInboundAction
           defaultOutbound = [string]$_.DefaultOutboundAction }
    })
    $group = $null; $ruleCount = 0
    if (Test-Path -LiteralPath $receiptPath) {
        $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        $group = $saved.group
        $ruleCount = @(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue).Count
    }
    @{ profiles = $profiles; labGroup = $group; labRuleCount = $ruleCount }
}

function Get-HostNetworkSummary {
    $proxy = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    $clash = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'clash|mihomo|verge|v2ray|xray|sing-box' } | ForEach-Object {
        @{ pid = $_.Id; name = $_.ProcessName }
    })
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in 7890,7891,1080,10808,8080,4174,4175 } |
        ForEach-Object { @{ address = $_.LocalAddress; port = $_.LocalPort; pid = $_.OwningProcess } })
    $envProxy = @{}
    foreach ($name in 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY') {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $envProxy[$name] = $value }
    }
    @{ wininetProxyEnable = $proxy.ProxyEnable; wininetProxyServer = $proxy.ProxyServer
       clashProcesses = $clash; expectedProxyListeners = $listeners; proxyEnvironment = $envProxy }
}

function Test-Tcp([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 2500) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false } finally { $client.Dispose() }
}

function Test-ExternalRoute {
    $dns = $false
    try { [void][System.Net.Dns]::GetHostAddresses('example.com'); $dns = $true } catch { $dns = $false }
    $httpsDirect = $false
    try { $null = Invoke-WebRequest -Uri 'https://example.com' -TimeoutSec 6 -UseBasicParsing; $httpsDirect = $true } catch { $httpsDirect = $false }
    $httpsProxy = $false
    try { $null = Invoke-WebRequest -Uri 'http://example.com' -Proxy 'http://127.0.0.1:7890' -TimeoutSec 6 -UseBasicParsing; $httpsProxy = $true } catch { $httpsProxy = $false }
    [pscustomobject]@{
        tcp_8_8_8_8_53        = Test-Tcp '8.8.8.8' 53
        tcp_1_1_1_1_443       = Test-Tcp '1.1.1.1' 443
        dns_public_name       = $dns
        https_direct          = $httpsDirect
        https_via_local_proxy = $httpsProxy
    }
}

function Test-LoopbackService {
    # Bind an ephemeral 127.0.0.1 listener, connect to it, then close it. This
    # proves the block-all rule left loopback untouched without depending on
    # any other local service being up.
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try {
        $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
        $connected = Test-Tcp '127.0.0.1' $port 2000
        [pscustomobject]@{ port = $port; connect_ok = $connected }
    } finally { $listener.Stop() }
}

function Install-BlockAllRule([string]$group) {
    New-NetFirewallRule -Name "$group-blockall" -DisplayName "$group block all outbound" `
        -Group $group -Direction Outbound -Action Block -Profile Any -Protocol Any `
        -RemoteAddress Any -Enabled True -ErrorAction Stop | Out-Null
}

function Remove-LabRules([string]$group) {
    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}

function Assert-Elevated {
    if (-not $isAdmin) { Write-Result @{ success = $false; error = 'ELEVATION_REQUIRED'; hint = 'Run this action from an elevated PowerShell.' }; exit 2 }
}

switch ($Action) {
    'Status' {
        $fw = Get-FirewallSummary; $net = Get-HostNetworkSummary
        Write-Result @{ success = $true; firewall = $fw; network = $net; identity = $identity.Name }
        break
    }
    'Snapshot' {
        $fw = Get-FirewallSummary; $net = Get-HostNetworkSummary
        $routeBefore = Test-ExternalRoute
        $snapshot = @{ success = $true; firewall = $fw; network = $net; externalRoute = $routeBefore
                       identity = $identity.Name; computer = $env:COMPUTERNAME }
        $snapshot | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'host-before.json') -Encoding utf8
        Write-Result $snapshot
        break
    }
    'Apply' {
        Assert-Elevated
        if (Test-Path -LiteralPath $receiptPath) { throw 'RECEIPT_EXISTS' }
        $before = Test-ExternalRoute
        $loopBefore = Test-LoopbackService
        $group = 'CODOL-319-LAB-' + [guid]::NewGuid().ToString('N')
        @{ group = $group; created_utc = [DateTime]::UtcNow.ToString('o'); identity = $identity.Name
           before = $before; loopbackBefore = $loopBefore } |
            ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
        try {
            Install-BlockAllRule $group
            $active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Group $group -ErrorAction Stop)
            if ($active.Count -ne 1) { throw 'RULE_NOT_ACTIVE' }
            $after = Test-ExternalRoute
            $loopAfter = Test-LoopbackService
            $externalBlocked = (-not $after.tcp_8_8_8_8_53) -and (-not $after.dns_public_name) -and (-not $after.https_via_local_proxy)
            $loopbackSurvived = $loopAfter.connect_ok
            if (-not ($externalBlocked -and $loopbackSurvived)) {
                Remove-LabRules $group
                Write-Result @{ success = $false; error = 'ISOLATION_VERIFICATION_FAILED'
                                before = $before; after = $after; loopback = $loopAfter
                                rolledBack = $true }
                exit 3
            }
            Write-Result @{ success = $true; group = $group; before = $before; after = $after
                            loopback = $loopAfter; externalBlocked = $externalBlocked
                            loopbackSurvived = $loopbackSurvived }
        } catch {
            Remove-LabRules $group
            Write-Result @{ success = $false; error = $_.Exception.Message; rolledBack = $true }
            exit 3
        }
        break
    }
    'Verify' {
        if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        $active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Group $saved.group -ErrorAction Stop)
        $route = Test-ExternalRoute
        $loop = Test-LoopbackService
        $ok = ($active.Count -eq 1) -and (-not $route.tcp_8_8_8_8_53) -and (-not $route.dns_public_name) -and (-not $route.https_via_local_proxy) -and $loop.connect_ok
        Write-Result @{ success = $ok; group = $saved.group; activeRules = $active.Count
                        externalRoute = $route; loopback = $loop }
        if (-not $ok) { exit 3 }
        break
    }
    'Restore' {
        Assert-Elevated
        if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'RECEIPT_MISSING' }
        $saved = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        Remove-LabRules $saved.group
        $remaining = @(Get-NetFirewallRule -Group $saved.group -ErrorAction SilentlyContinue).Count
        $route = Test-ExternalRoute
        Write-Result @{ success = ($remaining -eq 0); group = $saved.group; remainingRules = $remaining
                        externalRoute = $route }
        if ($remaining -ne 0) { exit 3 }
        break
    }
}
