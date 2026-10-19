# 夜间自主工作报告（2026-10-20 凌晨）

> 你睡觉期间，agent 按 [LONG-RUN-GOAL.md](LONG-RUN-GOAL.md) 自主跑了 9 轮（约 01:15–09:15），目标是 M3 大厅验收。**M3 未完成**，但把能离线推进的部分全部做完了，并留下了可复验的证据与工具。这份报告是你醒来先看的一页纸。

## 一句话结论

**TCLS 门槛已过、Auth 协议已通、ticket 校验已用运行时补丁绕过；但 IIPS 初始化必须管理员令牌，夜间硬边界禁止提权，因此 M3 的 LSG/大厅步骤没有跑。** 夜间所有 Medium 侧的 IIPS 绕过假设都已试过并记录为阴性。

## 夜间做成的（可直接复用）

| 项 | 证据/入口 |
|---|---|
| `-q` 参数跳过 `WIN_NO_TCLS`（定位到参数解析代码 RVA `0x37F5C0`） | [PROJECT_STATUS.md](PROJECT_STATUS.md) 第 8 节 |
| HTTP Auth 协议捕获：`POST /auth/`、TLSv1+AES256-SHA、20 字段响应、`DW-*` 头 | `runs/20261020-redirect01/auth*.jsonl` |
| `server319` 正式实现 Auth + LSG 捕获端点（21 项测试通过） | [server319/auth.py](server319/auth.py)、[server319/lsg.py](server319/lsg.py) |
| Auth 解析器定位（RVA `0x79A6xx`）+ ticket 闸门补丁 `0x79A78E: 74 B2→90 90`（与 1604220 的 `0x79A70E` 字节一致） | `runs/20261020-redirect01/auth-patch*.json` |
| `dwauth.ini` 解析实测：第一行 LSG `4174`、第二行 Auth `4175`、title `1002` | `runs/20261020-night01/config-globals.json` |
| LSG 连接机制：服务虚表 `0xD5A0C4–0xD5A0E4`、连接 `0xB98B70`、状态机 `0xB98AD0`，由 UI 状态驱动 | [PROJECT_STATUS.md](PROJECT_STATUS.md) 第 9.6.1 节 |
| 一键会话脚本 + 输入工具 + 通用 RVA 补丁工具 | [run_session.ps1](tools/run_session.ps1)、[send_input.ps1](tools/send_input.ps1)、[patch_runtime.py](tools/patch_runtime.py) |

## 夜间试过但否定的（阴性结果）

- `enable_iips=0` 禁用：4 秒退出。
- 跳过 IIPS Init 失败分支（`0x25A4A0`）：弹窗消失，但无主窗口、无 Auth。
- 跳过 IIPS 错误弹窗调用（`0x3804F2`）：进程存活，但弹窗仍在。
- 组合补丁：3 秒退出。
- IIPS 文件列表多出 `readme.txt`：移出后仍报 `8189fec`。
- 目录权限 / UAC 虚拟化：可写可删，VirtualStore 无重定向。

**结论**：IIPS 的 `8189fec` 不是文件、配置或目录权限问题，根因已确认：`IIPS\IIPSHostApp.exe` 的 manifest 是 `requireAdministrator`，且 Host 运行时也检查管理员（`RunAsInvoker` 能让它以 Medium 启动，但 Host 自己弹 "Error" 退出）。管理员令牌下 Host 正常，IIPS 通过。

## 你醒后做什么（三步）

```powershell
# 管理员 PowerShell，E:\GAME\COD\codol-airedux\319
pwsh -NoProfile -File tools\run_session.ps1 -RunId 20261020-session01 -Seconds 120
```

1. 等 `CODO` 主窗口出现（约 15–20 秒）。
2. **另开管理员窗口**：`pwsh -NoProfile -File tools\send_input.ps1 -Action ENTER -Count 3`；不行再试 `-Action CLICK`。
3. 看 `runs\20261020-session01\`：`auth.jsonl` 应有 `auth_request`；若启动 `python -m server319.lsg --port 4174 ...`，出现 `/v1.0/title/1002/...` 就是 **M3 入口打通**。

完整判据、排查表与恢复步骤见 [M3-CHECKLIST.md](M3-CHECKLIST.md)。

## 夜间提交（16 个，全部已推送）

`d28355b` `613b02c` `3ca696c` `c690e3c` `53456c3` `32b93e2` `b05d636` `87acf09` `8f170ea` `b64e516` `14c2103` `2027f4a` `945382d` `85b6322` `bf50e83`，以及更早的协议突破 `0c37189` 等。

## 环境状态

- 隔离副本配置已恢复到原始 pre-image（`dwauth.ini` 为本轮新建的重定向文件，`iips.ini`/`stun.ini`/`cacert.pem` 的改动与恢复见 [PROJECT_STATUS.md](PROJECT_STATUS.md) 8.3）。
- 无残留游戏进程、无监听端口、未改防火墙/代理/DNS/路由、未加载驱动、未修改原件。
- 工作树干净；`runs/` 下保留全部原始证据（未提交）。

