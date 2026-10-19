# M3 验收清单与复验手册

更新：2026-10-20（Asia/Shanghai）。目标 Build **1649370**（3.19.26.22），隔离副本 `runtime\client-1649370`。本文只列可执行的判据与命令；事实与证据索引见 [PROJECT_STATUS.md](PROJECT_STATUS.md) 与 [MILESTONES.md](MILESTONES.md)。

## 1. 验收定义（五条同时满足才算 M3）

| # | 判据 | 当前状态 |
| --- | --- | --- |
| 1 | 通过 TCLS 门槛，不再出现 `WIN_NO_TCLS` 致命错误 | **已满足**：`-q` 参数（RVA `0x37F5C0` 参数解析；无 `-q`/`-qa` 才弹窗） |
| 2 | 走完 IIPS 初始化，不再出现 `初始化IIPS错误` | **未满足（需管理员令牌）**：根因已确认——`IIPS\IIPSHostApp.exe` 的 manifest 是 `requireAdministrator`，Medium 下游戏**从未创建 Host 进程**（UAC 拒绝），故 `8189fec` 是硬性管理员依赖；禁用/跳过/文件/权限/兼容层全部阴性 |
| 3 | Auth/LSG 请求真实到达本机 server319，有请求字节/端口/应答记录 | **Auth 已满足**（`POST /auth/`，`auth.jsonl`）；**LSG 未发生**（状态机未推进） |
| 4 | 进入可交互的原生前台/大厅（截图 + 窗口类/标题 + 持续时间） | **未满足**：补丁后 `CODO` + `D3DProxyWindow` 稳定 55s，但未证明可交互，且截图取证受限 |
| 5 | 全过程有 `runs\<id>` 证据、可复验命令、pre-image 与恢复记录 | **部分满足**：Auth/补丁/窗口有证据；LSG/截图缺失 |

## 2. 一键复验（管理员 PowerShell，`319` 目录）

```powershell
# 1) Auth + 补丁 + 证据（脚本内部会核四锚点、起 server319 auth、应用 0x79A78E 补丁）
pwsh -NoProfile -File tools\run_session.ps1 -RunId 20261020-session01 -Seconds 120

# 2) 主窗口出现后，另开管理员窗口推进 UI（LSG 状态机需要输入）
pwsh -NoProfile -File tools\send_input.ps1 -Action ENTER -Count 3
# 备选：-Action CLICK / SPACE；每次之间等 2-3 秒

# 3) 观察 LSG（可选，另开窗口）
python -m server319.lsg --cert runs\20261020-session01\tls\auth.crt `
    --key runs\20261020-session01\tls\auth.key --port 4174 `
    --log runs\20261020-session01\lsg.jsonl --seconds 180
```

## 3. 证据判据

- `runs\<id>\auth.jsonl`：应含 `auth_request`（`POST /auth/`）、`auth_response`（200，20 字段）。
- `runs\<id>\patch.json`：`patches[0].original == 74b2`、`verified_after == true`、采样中 `CODO`/`D3DProxyWindow` 可见、无 `#32770` 错误弹窗。
- `runs\<id>\lsg.jsonl`：出现 `lsg_request` 且 `request_line` 形如 `GET /v1.0/title/1002/queue/<q>/member/<m> HTTP/1.1`，即为 **LSG 入口打通**（M3 第 3 条达成）。
- 截图：需管理员会话下无控制台启动（计划任务/`CreateProcessAsUser`）或用户手动截图；`PrintWindow` 对该 D3D 客户端全黑，桌面截屏会被 sudo 控制台遮挡。

## 4. 失败排查

| 现象 | 含义 | 下一步 |
| --- | --- | --- |
| 弹 `WIN_NO_TCLS` | 少了 `-q` | 确认 `run_session.ps1` 的 `--game-args=-q` |
| 弹 `初始化IIPS错误：8189fec` | 当前会话非管理员 | 用管理员 PowerShell 重跑 |
| 有 `auth_request` 但无 `lsg_request` | Auth 过了，LSG 状态机未推进 | 用 `send_input.ps1` 推进；若仍无，检查 4174 监听与 `dwauth.ini` 第一行 |
| 补丁 `original != 74b2` | 代码未解密或基址变化 | 确认 `module_base=0x400000`；把 `--wait` 调到 12-14 秒 |
| 进程 2-4 秒退出 | IIPS/资源初始化失败 | 回到第 2 条，确认管理员令牌 |

## 5. 恢复

```powershell
# 配置（dwauth.ini/stun.ini/iips.ini/cacert.pem）回到原始 pre-image
python tools\stage_redirect.py restore --client-dir runtime\client-1649370 --run-dir runs\20261020-redirect01

# 手动补回 HostPid（备份在 runs\20261020-redirect01\HostPid.pre）
Copy-Item runs\20261020-redirect01\HostPid.pre runtime\client-1649370\IIPS\HostPid

# 核对四锚点未被改动
python -m server319 --client-dir runtime\client-1649370 --preflight
```

## 6. 已知边界

- 补丁只在进程镜像内，退出即恢复；未修改任何客户端文件。
- 未加载驱动、未改防火墙/代理/DNS/路由、未连接官方端点（Auth/LSG 全走 127.0.0.1）。
- 本机 `sudo pwsh -File <脚本>` 会静默失败，使用 `sudo pwsh -Command "& '...'"` 或直接在管理员 PowerShell 中运行。
