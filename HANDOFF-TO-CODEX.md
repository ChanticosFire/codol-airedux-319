# CODOL 3.19.26.22（Build 1649370）大厅连接问题 — 交接文档（给 Codex）

> 生成：2026-10-20 上午（Asia/Shanghai）。工作目录 `E:\GAME\COD\codol-airedux\319`，隔离副本 `runtime\client-1649370`。
> 本文只写**实测/静态可复现**的结论，未验证的会标注。所有 run 目录都在 `319\runs\` 下。

## 0. 一句话现状

**TCLS 门槛已过、IIPS 已通过（管理员令牌）、Auth 已成功（200）、ticket 校验已用运行时补丁绕过；卡点是大厅（LSG）连接对象从未被创建（`[netobj+0x4F4] == 0`），UI 因此停在 `[100]无法连接大厅服务`。用状态跳表补丁强推后，错误变成 `与大厅服务器失去连接`，但 conn 仍为 0。**

## 1. 环境与启动链（已验证）

| 项 | 事实 | 证据 |
|---|---|---|
| 启动门槛 | `-q` 参数跳过 `WIN_NO_TCLS`；参数解析在 RVA `0x37F5C0` | 早期 run |
| IIPS | 必须**管理员令牌**：`IIPSHostApp.exe` manifest `requireAdministrator`，运行时 `SetPrivilege` 需 `SeDebugPrivilege` + `SeCreateGlobalPrivilege`；Medium 下游戏从不创建 Host | `PROJECT_STATUS.md` 第 10 节 |
| Auth | `POST /auth/` HTTP JSON，TLS1.0–1.2 + `AES256-SHA`（`ALL:@SECLEVEL=0`）；请求 187–188B，响应 200 / 941–942B | `runs/20261020-session0*/auth.jsonl` |
| Auth 闸门补丁 | `RVA 0x79A78E: 74 B2 → 90 90`（`je` → NOP），与 1604220 的 `0x79A70E` 字节一致；补丁后 `CODO` 主窗口出现并稳定 | `patch.json` 各 run |
| 配置 | `dwauth.ini` 两行：行1 `127.0.0.1 4174`（LSG）、行2 `127.0.0.1 4175`（Auth）；`title_id=1002` | 运行时读回 host1/port1/host2/port2 |
| 服务器 | `server319.auth`（4175）+ `server319.lsg`（4174）；`lsg.jsonl` 始终为空 = **客户端从未连 4174** | 所有 session run |

管理员会话已确认：`S-1-16-12288`，`SeDebugPrivilege` / `SeCreateGlobalPrivilege` 均 Enabled。

## 2. 已证实的地址与机制（1649370，运行时 VA）

> 与 1604220 的地址**高度一致**（同一代码库不同 build），下列均按 1649370 实测。

### 2.1 大厅失败提示链

```
0xDE0640  "SF_UI_DW_LIVE_CONNECTING_FAILED" = "[100]无法连接大厅服务!"
0x7EF254  push 0xDE0640          ← 唯一引用（实测命中）

0x7EF1C8  大厅连接 UI 轮询
  0x7EF1CD  call 0x7F25B0 → esi        ← 取状态码
  0x7EF1DE  cmp esi, 3 ; jne 0x7EF210   ← 3 = 成功
  0x7EF210  cmp esi, 4 ; jne 0x7EF41B   ← 4 = 失败 → push 0xDE0640
```

### 2.2 状态映射函数 `0x7F25B0`

```
0x7F25B0  cmp byte [0x849BA3D], 0
0x7F25B7  mov eax, 4            ; 默认失败
0x7F25BC  jne 0x7F25DB          ; 错误标志非 0 → 返回 4
0x7F25BE  mov ecx, [0x84ABA50]  ; UI 状态
0x7F25C4  cmp ecx, 5
0x7F25C7  ja 0x7F25DB           ; >5 → 返回 4
0x7F25C9  jmp [ecx*4 + 0x7F25DC] ; 跳表
```

跳表 `0x7F25DC`（6 项，实测）：

| `[0x84ABA50]` | 跳表目标 | 返回 |
|---|---|---|
| 0 | `0x7F25DB` | 4（失败） |
| 1–4 | `0x7F25D0` | 1（连接中） |
| 5 | `0x7F25D6` | 3（成功） |

### 2.3 大厅网络对象（实测）

| 地址 | 含义 | 实测值 |
|---|---|---|
| `[0x8269774]` | netobj 指针 | `0x38A2C188`（每次运行变化，正常） |
| `[netobj+0x4F4]` | **LSG conn 指针** | **`0x0`（从未创建）** |
| `[netobj+0x4F8]` | 大厅就绪标志 | `0` |
| `[netobj+0x50]/+0x54` | 大厅地址（IP/PORT） | `0` |
| `[0x84ABA50]` | UI 状态 | `0` |
| `[0x849BA3D]` | 错误标志 | `0` |
| `[0x849BA34]` | 状态计数器 | `0xA` |

22–32 秒连续采样，`conn` 与 `lobby_4F8` **恒为 0**。

### 2.4 1604220 参考资料中的对应机制（供对照，未在 1649370 逐条验证）

- `[netobj+0x4F8]=1` 需要 `0xB769A0`（大厅地址解析器）从 LSG 连接上读到 **tag `0x0A` + 8 字节**（IP 4B + PORT 4B）。
- `0xB7A670`（大厅连接状态）要求 `[netobj+0x4F4]`（conn）非 0 且 `[conn+0xC8]∈{1,2}`。
- `0x803780`（轮询主体）在状态==2 时写 `[0x84ABA50]=5`。
- LSG 对象由 `0x7F3600 → 0x7F34E0` 构建，写入 `[0x84ABA70/74]`；起连 `0xBAFDD0`。
- **1649370 实测 `0x7F3600` 无直接 `call` 调用者**（`probe_callers` 返回 0），可能经虚表/间接。

## 3. 实验记录（按 run，全部在 `319\runs\`）

| run | 补丁/条件 | 结果 |
|---|---|---|
| `session01` | Auth+LSG(未起)→ 实际只有 Auth；`-q`；无输入 | Auth 200；`CODO`+`D3DProxyWindow` 约 64s；无 4174；67s exit 0 |
| `session02` | 加 `AutoInput ENTER`（每 8s） | 同上，66s exit 0（**ENTER 点了“退出”按钮**，弹窗只有退出） |
| `session03` | Auth+**LSG(4174)** 同时起 | Auth 200；`lsg.jsonl` 空；`CODO` 约 62s；150s 时仍 alive（脚本终止） |
| `session04` | 同 session03 + 每 5s 截图 | **截图证实 20s 时 `[100]` 已出现**；游戏窗口 35s 后消失 |
| `session05` | 补丁 `0x798707: B8521000009090`（LSG 端口强制 4174） | 补丁应用成功；仍无 4174；28s exit |
| `session06` | 补丁 `0x798BB7: EB40`（LSG 失败分支强制跳过） | 仍无 4174；24s exit |
| `session07` | 补丁跳表 `0x3F25DC: D6257F00`（state 0 → 3 成功） | 22s `CODO` 消失，23s 弹 `与大厅服务器失去连接`（GBK），32s exit **-1** |

**关键差异**：session07 的跳表补丁让错误从 `[100]无法连接` 变成 `与大厅服务器失去连接`——说明 UI 状态机确实被推进，但 **conn 仍为 0**，lobby 流程检测到“无连接”后崩溃/退出。

## 4. 已试并排除的方向（Medium/无提权侧）

- `enable_iips=0`：4 秒退出（IIPS 是资源必需组件）。
- 跳过 IIPS Init 失败分支（`0x25A4A0`）：弹窗消失但无主窗口。
- 跳过 IIPS 错误弹窗调用（`0x3804F2`）：存活但弹窗仍在。
- IIPS 文件列表多出 `readme.txt`：移出后仍 `8189fec`。
- 目录权限/UAC 虚拟化：可写可删，VirtualStore 无重定向。
- `RunAsInvoker` 环境变量 / AppCompat 注册表层：Host 仍不启动（UAC 先拒绝）。
- `Global\` → `Local\X` 命名空间替换：Host 从未启动，无法验证。
- Host `SetPrivilege` 单点补丁：越过它后卡在 `IIPS_SHARE_STATE_ERROR(4)`（需 `SeCreateGlobalPrivilege`）。
- Host 命令行开关：不存在。

**结论**：IIPS 侧 Medium 路径已穷尽，必须管理员令牌（现已具备）。

## 5. 未解问题（给 Codex 的核心）

1. **为什么客户端 Auth 成功后不创建 LSG 连接对象（conn=0）？**
   - 可能 1：LSG 连接由某个任务/状态机在 Auth 后触发，该任务没有被启动（缺 `0x47` 应答？缺 `lsg_server_ticket` 有效内容？）。
   - 可能 2：`lsg_server_ticket` 零值被解析为“无效地址”，客户端放弃连接（但静态看 `0xB984B2` 只校验长度 128）。
   - 可能 3：LSG 地址来自 Auth 响应字段（URL 模板 `%s://%s:%d/%s/title/%d/queue/%d/member/%llu`），零值导致 URL 无效。
2. **`0x7F3600`（LSG 对象构建）在 1649370 的等价物与调用点**——`probe_callers` 0 命中，需要运行时断点/内存写监视。
3. **`[0x84ABA70/74]`（1604220 的 LSG 对象指针）在 1649370 是否同址**——最近一次 dump `0x84ABA60` 失败（读内存返回空），需要重试。
4. **`0x803780`（轮询主体）的调用链**——它写 `[0x84ABA50]=5`，前提是 `0xB7A670==2`。
5. **真实 `lsg_server_ticket` 样本**：任何能正常进大厅的 1649370 会话抓包（哪怕一条），能直接回答“ticket 里是否含地址/端口”。

## 6. 给 Codex 的具体建议（按优先级）

1. **先读 `[0x84ABA70]`/`[0x84ABA74]`**（运行时，25 秒后）：确认 LSG 对象是否创建。若为 0，问题在“对象构建”之前；若非 0，问题在“起连”。
2. **对 `0x7F34E0`/`0x7F3600` 下断点**（若可用调试器）或**监视 `[0x84ABA70/74]` 的写入**，拿到 1649370 的真实等价地址。
3. **查 `0xBAFDD0` 的 1649370 等价物**（1604220 的起连函数），看它是否被调用；若未被调用，追其唯一调用者（1604220 资料：`0xBB0F43`，再上就是登录/大厅业务层）。
4. **核对 Auth 响应**：1604220 的 mock 回包含 `lsg_server_ticket`/`lsg_server_ticket_size` 以及 `DW-*` 头；我们当前实现（`server319/auth.py`）已按此返回，但 ticket 是 **128 字节全零**。若 Codex 有真实 ticket 样本，替换后重试。
5. **不要**再用“强改 `[0x84ABA50]`/跳表”的方式——已证明会导致 `与大厅服务器失去连接` 并崩溃；正确路径是让 conn 自然建立。

## 7. 复现命令（管理员 PowerShell，`319` 目录）

```powershell
# 一键会话（Auth 4175 + LSG 4174 + 游戏 + Auth 补丁）
pwsh -NoProfile -File tools\run_session.ps1 -RunId 20261020-sessionXX -Seconds 150

# 单点实验（Auth+LSG 手动起，游戏 + 任意补丁）
python tools\patch_runtime.py --client-dir runtime\client-1649370 `
  --evidence runs\<id>\patch.json --patch 0x79A78E:9090:74B2 `
  --patch <RVA>:<NEWHEX>:<OLDHEX> --wait 13 --observe 120

# 运行时读地址
python tools\probe_anchor.py --client-dir runtime\client-1649370 `
  --evidence runs\<id>\anchor.json --wait 25 --anchor hex:4006de00 `
  --dump-start 0x84ABA60 --dump-size 0x30

# 找直接 call 调用者
python tools\probe_callers.py --client-dir runtime\client-1649370 `
  --evidence runs\<id>\callers.json --target 0x3F3600 --base 0x400000 --wait 25
```

## 8. 关键文件

- 服务器：`server319/auth.py`（Auth）、`server319/lsg.py`（LSG 捕获骨架，当前只回 404）
- 工具：`tools/patch_runtime.py`、`tools/probe_anchor.py`、`tools/probe_callers.py`、`tools/run_session.ps1`、`tools/send_input.ps1`
- 证据：`runs/20261020-session01..07/`、`runs/20261020-session06/`（anchor/dump 系列）
- 参考（1604220 的完整研究，**地址需按 1649370 校核**）：`他人文件参考/_CURRENT_STATE(1).md` 第 43 节（N97）、§44

## 9. 环境状态

- 隔离副本配置已恢复到原始 pre-image；`iips.dll`、`IIPSHostApp.exe`、`codoMP_client_shipRetail.exe` 均为原件哈希。
- 无残留进程/监听；未改防火墙/代理/DNS/驱动/原件。
- 当前 DSH 以管理员（High）运行，可直接跑上述命令。
