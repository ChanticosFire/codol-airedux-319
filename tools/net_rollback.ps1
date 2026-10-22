#Requires -Version 5.1
<#
.SYNOPSIS
    1649370 离线研究的网络一键回退脚本。

.DESCRIPTION
    社区的 offline_guard.exe 使用 WFP **动态会话**（FWPM_SESSION_FLAG_DYNAMIC）为单个目标进程
    添加 4 个 IPv4/IPv6 收发拒绝过滤器。Windows 保证：动态会话的引擎句柄一旦关闭，
    该会话创建的全部过滤器与 sublayer 由内核自动删除。

    因此回退的核心动作只有一个：**结束 guard 进程**。其余步骤都是验证。

    本脚本幂等，可重复运行。它不会修改防火墙配置文件、网卡、路由或 DNS；
    只做三件事：结束残留的 guard / 游戏进程、验证 WFP 无残留、验证网络可用。

.PARAMETER KeepGame
    只结束 guard，不结束游戏进程。

.PARAMETER SnapshotDir
    快照目录，用于和运行前的基线对比。默认取最新的 net-snapshot-1649370。

.EXAMPLE
    pwsh -NoProfile -File tools\net_rollback.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepGame,
    [string]$SnapshotDir
)

$ErrorActionPreference = 'Continue'
$script:problems = New-Object System.Collections.Generic.List[string]

function Write-Section([string]$text) {
    Write-Host ""
    Write-Host ("=== {0} ===" -f $text) -ForegroundColor Cyan
}

function Write-Ok([string]$text)   { Write-Host ("  [OK]   {0}" -f $text) -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host ("  [WARN] {0}" -f $text) -ForegroundColor Yellow }
function Write-Bad([string]$text)  {
    Write-Host ("  [BAD]  {0}" -f $text) -ForegroundColor Red
    $script:problems.Add($text)
}

# ---------------------------------------------------------------- 0. 权限与快照
$isAdmin = $false
try {
    $ident = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = $ident.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }

if (-not $SnapshotDir) {
    $root = Split-Path -Parent $PSScriptRoot
    $candidates = Get-ChildItem (Join-Path $root 'evidence') -Directory -Filter 'net-snapshot-*' -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending
    if ($candidates) { $SnapshotDir = $candidates[0].FullName }
}

Write-Host "CODOL 1649370 网络回退" -ForegroundColor White
Write-Host ("  管理员权限: {0}" -f $(if ($isAdmin) { '有（可检查 WFP）' } else { '无（仅能结束进程并验证连通性）' }))
Write-Host ("  快照目录  : {0}" -f $(if ($SnapshotDir) { $SnapshotDir } else { '(未找到)' }))

# ---------------------------------------------------------------- 1. 结束 guard
Write-Section '1. 结束 offline_guard 进程（这一步即撤销动态 WFP 会话）'
$guards = Get-Process -Name 'offline_guard','offline_guard64','offline_guard_x64' -ErrorAction SilentlyContinue
$customGuardPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'runs\guard-build\client_loopback_tcp_guard-fixed.exe'
$customGuards = Get-Process -Name 'client_loopback_tcp_guard-fixed' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ([IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($customGuardPath)) }
$guards = @($guards | Where-Object { $_ }) + @($customGuards | Where-Object { $_ })
if (-not $guards) {
    Write-Ok '没有残留的 guard 进程'
} else {
    foreach ($g in $guards) {
        try {
            Stop-Process -Id $g.Id -Force -ErrorAction Stop
            Write-Ok ("已结束 guard pid={0}" -f $g.Id)
        } catch {
            Write-Bad ("无法结束 guard pid={0}: {1}" -f $g.Id, $_.Exception.Message)
        }
    }
}

# ---------------------------------------------------------------- 2. 结束游戏进程
Write-Section '2. 结束离线运行的客户端进程'
$gameNames = 'codol1649370-offline','codoMP_client_shipRetail','codol_rebuild'
$games = Get-Process -Name $gameNames -ErrorAction SilentlyContinue
if (-not $games) {
    Write-Ok '没有残留的客户端进程'
} elseif ($KeepGame) {
    Write-Warn ("保留客户端进程: {0}" -f (($games | ForEach-Object { "$($_.Name):$($_.Id)" }) -join ', '))
} else {
    foreach ($g in $games) {
        try {
            Stop-Process -Id $g.Id -Force -ErrorAction Stop
            Write-Ok ("已结束 {0} pid={1}" -f $g.Name, $g.Id)
        } catch {
            Write-Bad ("无法结束 {0} pid={1}: {2}" -f $g.Name, $g.Id, $_.Exception.Message)
        }
    }
}

# ---------------------------------------------------------------- 3. 等待句柄释放
Write-Section '3. 等待内核回收动态会话'
Start-Sleep -Seconds 2
$stillGuard = Get-Process -Name 'offline_guard','offline_guard64','offline_guard_x64' -ErrorAction SilentlyContinue
$stillCustom = Get-Process -Name 'client_loopback_tcp_guard-fixed' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ([IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($customGuardPath)) }
$stillGuard = @($stillGuard | Where-Object { $_ }) + @($stillCustom | Where-Object { $_ })
if ($stillGuard) {
    Write-Bad ("仍有 guard 存活: {0}" -f (($stillGuard | ForEach-Object { $_.Id }) -join ', '))
} else {
    Write-Ok 'guard 已全部退出，动态 WFP 会话应已被内核删除'
}

# ---------------------------------------------------------------- 4. WFP 残留检查
Write-Section '4. 检查是否有 CODOL 相关的 WFP 过滤器残留'
if (-not $isAdmin) {
    Write-Warn '需要管理员权限才能查询 WFP；跳过（动态会话语义已保证清理）'
} else {
    $wfpOut = Join-Path $env:TEMP ("wfp-state-{0}.xml" -f (Get-Date -Format 'HHmmss'))
    try {
        netsh wfp show state file="$wfpOut" 2>&1 | Out-Null
        if (Test-Path $wfpOut) {
            $hit = Select-String -Path $wfpOut -Pattern 'CODOL temporary offline research|CODOL deny all|CODOL per-image offline boundary' -SimpleMatch -ErrorAction SilentlyContinue
            if ($hit) {
                Write-Bad ("发现 {0} 处 CODOL WFP 残留，请重启或手动清理" -f $hit.Count)
            } else {
                Write-Ok 'WFP 状态中未发现 CODOL 相关过滤器/sublayer'
            }
            Remove-Item $wfpOut -Force -ErrorAction SilentlyContinue
        } else {
            Write-Warn 'netsh wfp show state 未生成文件，无法确认（不影响回退结论）'
        }
    } catch {
        Write-Warn ("WFP 查询失败: {0}" -f $_.Exception.Message)
    }
}

# ---------------------------------------------------------------- 5. 防火墙基线对比
Write-Section '5. 对比运行前的防火墙基线'
if ($SnapshotDir) {
    $fwSnap = Get-ChildItem $SnapshotDir -Filter 'fw-state-*.txt' -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending | Select-Object -First 1
    if ($fwSnap) {
        $before = (Get-Content $fwSnap.FullName -Encoding UTF8) -join "`n"
        $now = (netsh advfirewall show allprofiles state 2>&1) -join "`n"
        # 只比较 State 行，忽略时间戳等噪声
        $norm = { param($t) (($t -split "`n") | Where-Object { $_ -match 'State|状态' } | ForEach-Object { $_.Trim() }) -join '|' }
        if ((& $norm $before) -eq (& $norm $now)) {
            Write-Ok '防火墙配置文件状态与运行前一致'
        } else {
            Write-Warn '防火墙状态文本与快照不同，请人工核对：'
            Write-Host ("    快照: {0}" -f (& $norm $before))
            Write-Host ("    当前: {0}" -f (& $norm $now))
        }
    } else {
        Write-Warn '快照中没有 fw-state，跳过'
    }
} else {
    Write-Warn '未找到快照目录，跳过'
}

# ---------------------------------------------------------------- 6. 网络可用性
Write-Section '6. 验证网络可用性'
$adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' }
if ($adapters) {
    Write-Ok ("有 {0} 个适配器处于 Up: {1}" -f $adapters.Count, (($adapters | Select-Object -ExpandProperty Name) -join ', '))
} else {
    Write-Bad '没有处于 Up 状态的网络适配器'
}

$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
         Where-Object { $_.NextHop -ne '0.0.0.0' } | Select-Object -First 1
if ($route) {
    Write-Ok ("默认路由存在，下一跳 {0}" -f $route.NextHop)
} else {
    Write-Warn '没有默认 IPv4 路由'
}

$dnsOk = $false
try {
    $resolve = Resolve-DnsName -Name 'example.com' -Type A -DnsOnly -QuickTimeout -ErrorAction Stop
    if ($resolve) { $dnsOk = $true }
} catch { }
if ($dnsOk) { Write-Ok 'DNS 解析正常' } else { Write-Warn 'DNS 解析失败（可能是无外网或 DNS 变更，请人工核对）' }

$pingOk = Test-Connection -ComputerName 127.0.0.1 -Count 1 -Quiet -ErrorAction SilentlyContinue
if ($pingOk) { Write-Ok '回环连通' } else { Write-Bad '回环不通' }

# ---------------------------------------------------------------- 7. 本机服务端口
Write-Section '7. 检查本项目服务端口是否可监听（回退后应可再次绑定）'
foreach ($port in 3074, 4174, 4175) {
    $listening = $false
    try {
        $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        $probe.Start(); $probe.Stop()
        $listening = $true
    } catch { }
    if ($listening) { Write-Ok ("端口 {0} 可绑定" -f $port) }
    else { Write-Warn ("端口 {0} 当前被占用（可能是本项目服务仍在运行）" -f $port) }
}

# ---------------------------------------------------------------- 结论
Write-Section '结论'
if ($script:problems.Count -eq 0) {
    Write-Host '  回退完成，未发现问题。' -ForegroundColor Green
    Write-Host '  若仍怀疑有网络限制，最可靠的做法是重启一次系统。' -ForegroundColor Gray
    exit 0
} else {
    Write-Host ("  回退完成，但有 {0} 项需要人工关注：" -f $script:problems.Count) -ForegroundColor Yellow
    foreach ($p in $script:problems) { Write-Host ("    - {0}" -f $p) -ForegroundColor Yellow }
    Write-Host '  建议：重启系统可清除所有动态 WFP 会话。' -ForegroundColor Gray
    exit 1
}
