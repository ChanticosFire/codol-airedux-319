# 一键 demo 播放探针：启动客户端 -> 装配散装资源 -> 注入 cl_demo_play -> 定时截图
#
#   pwsh -File tools/run_demo_probe.ps1 -Name demo-probe -Demo '0C-2021-8-26[19-26-24]war.demo'
#
# 产物：runs\<Name>-launch.out、runs\<Name>-t*.png、runs\<Name>-probe.json
param(
    [string]$Name = "demo-probe",
    [string]$Demo = "0C-2021-8-26[19-26-24]war.demo",
    [int[]]$Shots = @(3, 8, 15, 25, 40),
    [switch]$SkipLoose
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$launchOut = Join-Path $root "runs\$Name-launch.out"
$launchErr = Join-Path $root "runs\$Name-launch.err"
$probe = [ordered]@{ name = $Name; demo = $Demo; started = (Get-Date).ToString('o'); steps = [ordered]@{} }

# 1) 启动（host 会装配 runtime 并挂起等守卫）
$proc = Start-Process -FilePath "python" `
    -ArgumentList @('-B', '-X', 'utf8', 'tools\launch_1649370.py', '--name', $Name, '--until-close', '--local-profile', '--full') `
    -PassThru -RedirectStandardOutput $launchOut -RedirectStandardError $launchErr -WindowStyle Hidden
$probe.steps['launched'] = $true

$runtime = "E:\GAME\COD\1649370\workspaces\offline-runs\$Name\runtime"
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and -not (Test-Path (Join-Path $runtime 'codol1649370-offline.exe'))) {
    Start-Sleep -Milliseconds 400
}
if (-not (Test-Path (Join-Path $runtime 'codol1649370-offline.exe'))) {
    $probe.steps['runtime'] = 'missing'
    $probe | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $root "runs\$Name-probe.json") -Encoding UTF8
    throw "runtime 未装配：$runtime"
}
$probe.steps['runtime'] = 'ready'

# 2) 散装资源：5 个 v461 loose 包 -> devraw_shared（demo 播放时客户端以 loose 方式找图/音）
if (-not $SkipLoose) {
    $dst = Join-Path $runtime 'devraw_shared'
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    foreach ($pack in 'crash-tropical', 'crossfire', 'gametype', 'dmz', 'survival') {
        $src = Join-Path $root "runs\20261022-$pack-loose-v461\main"
        if (Test-Path $src) { robocopy $src $dst /E /XO /NFL /NDL /NJH /NJS /NP | Out-Null }
    }
    $probe.steps['loose_files'] = (Get-ChildItem $dst -Recurse -File | Measure-Object).Count
}

# 3) demo 文件放进 runtime（客户端按 main/demo 查找）
$demoDir = Join-Path $runtime 'main\demo'
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$demoSrc = Join-Path 'E:\GAME\COD\Original Client\main\demo' $Demo
if (-not (Test-Path -LiteralPath $demoSrc)) { throw "demo 不存在：$demoSrc" }
Copy-Item -LiteralPath $demoSrc -Destination $demoDir -Force
$probe.steps['demo'] = 'staged'

# 4) 等 stage>=4 后注入（cbuf_command 自带等待与安全校验）
$cbufOut = Join-Path $root "runs\$Name-cbuf.json"
python tools\cbuf_command.py --command "cl_demo_play $Demo" --wait-stage --output $cbufOut 2>&1 |
    ForEach-Object { $_ } | Out-Null
$probe.steps['cbuf'] = if (Test-Path $cbufOut) { (Get-Content $cbufOut -Raw | ConvertFrom-Json).status } else { 'no-output' }

# 5) 定时截图
$shots = @()
$prev = 0
foreach ($t in $Shots) {
    Start-Sleep -Seconds ([Math]::Max(0, $t - $prev))
    $prev = $t
    $png = Join-Path $root "runs\$Name-t$t.png"
    $alive = Get-Process -Name 'codol1649370-offline' -ErrorAction SilentlyContinue
    if (-not $alive) {
        $shots += [ordered]@{ t = $t; png = $null; client_alive = $false }
        break
    }
    try {
        pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\capture_window.ps1') -OutFile $png | Out-Null
        $sz = (Get-Item $png).Length
        $shots += [ordered]@{ t = $t; png = $png; bytes = $sz; client_alive = $true }
    } catch {
        $shots += [ordered]@{ t = $t; png = $null; client_alive = $true; error = "$_" }
    }
}
$probe.shots = $shots

# 6) 收尾：杀掉客户端让 host 退出
$alive = Get-Process -Name 'codol1649370-offline' -ErrorAction SilentlyContinue
if ($alive) { $alive | Stop-Process -Force }
$probe | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $root "runs\$Name-probe.json") -Encoding UTF8
$probe | ConvertTo-Json -Depth 6
