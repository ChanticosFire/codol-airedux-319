# 同步 main/ 与 hires/ 资源到本 runtime
#
# 本包刻意省略了 runtime/main (约 7.4 GB) 与 runtime/hires (约 7.2 GB)：
# 二者是原版游戏资源，可从已有 runtime 或原版客户端安装目录复制重建。
#
# 用法：
#   .\sync-missing-resources.ps1 -Source "E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime"
#   .\sync-missing-resources.ps1 -Source "E:\GAME\COD\codol-airedux\319\runtime\client-1649370"
#
# -Source 指向一个**已有的 runtime 目录**（其中应含 main\ 与 hires\）。
# 本脚本只复制这两个目录，不会删除目标侧任何文件。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    # 本包所在的 runtime 目录；默认取脚本同级的 runtime\
    [string]$Target = (Join-Path $PSScriptRoot 'runtime'),

    [switch]$WhatIfOnly
)

$ErrorActionPreference = 'Stop'

Write-Host '=== CODOL 1649370 runtime 资源同步 ==='
Write-Host "  源     : $Source"
Write-Host "  目标   : $Target"
Write-Host ''

if (-not (Test-Path -LiteralPath $Source)) {
    throw "源目录不存在: $Source"
}
if (-not (Test-Path -LiteralPath $Target)) {
    throw "目标 runtime 不存在: $Target（本脚本应放在包的根目录）"
}

$dirs = @('main', 'hires')
foreach ($d in $dirs) {
    $src = Join-Path $Source $d
    if (-not (Test-Path -LiteralPath $src)) {
        throw "源中缺少 $d\ : $src"
    }
    $s = Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue |
         Measure-Object Length -Sum
    Write-Host ("  [{0}] {1:N0} files  {2:N1} MB" -f $d, $s.Count, ($s.Sum / 1MB))
}
Write-Host ''

if ($WhatIfOnly) {
    Write-Host '  -WhatIfOnly：仅演练，不复制。'
    return
}

foreach ($d in $dirs) {
    $src = Join-Path $Source $d
    $dst = Join-Path $Target $d
    Write-Host "  -> 复制 $d ..."
    # /E 递归含空目录；/XO 只覆盖更新的；不删除目标独有文件
    $null = robocopy $src $dst /E /XO /NFL /NDL /NJH /NJS /R:1 /W:1
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { throw "robocopy 失败，exit=$rc" }
    Write-Host ("     done (robocopy exit={0})" -f $rc)
}

Write-Host ''
Write-Host '=== 同步完成，校验 runtime 总大小 ==='
$all = Get-ChildItem -LiteralPath $Target -Recurse -File -ErrorAction SilentlyContinue |
       Measure-Object Length -Sum
Write-Host ("  runtime: {0:N0} files  {1:N1} MB" -f $all.Count, ($all.Sum / 1MB))
Write-Host ''
Write-Host '提示：完整 runtime 预期约 15.3 GB / 88,581 文件。'
Write-Host '      若数量明显偏少，请检查 -Source 是否指向正确的 runtime 目录。'
