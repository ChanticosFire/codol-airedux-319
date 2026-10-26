# Build 1649370：已验证的大厅与对局画面启动流程

记录日期：2026-10-26。工作目录：`E:\GAME\COD\codol-airedux\319`。

## 已验证的结果及边界

- 本次使用 `E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime\codol1649370-offline.exe`。用户现场确认：没有拉起 TP，没有出现“100 大厅连接错误”，进入大厅和 `mp_crash_tropical` 对局画面；画面里尚无可控玩家。
- 服务端本轮日志最后一段有真实 `getchallenge` 1 次、`connect` 1 次、`stats` 9 次、`gamestateupdate` 2 次；客户端采样到 `net_state=10`、`ui_state=0`。这证明连接与加载路径，但**不证明玩家可移动或射击**。
- `runs/r522-lsg.jsonl` 只记录到一次 `tls_handshake_failed`。本次大厅和对局成功不应被写成“LSG TLS 身份认证已成功”。
- 这条路线是隔离的离线客户端，**不是** `codoMP_client_shipRetail.exe` 零售客户端的完整启动验证。救援交接中关于零售客户端 TP/TCLS 与 TLS 的分析属于另一条路线，不要据此否定本流程。

## 启动前检查

1. 复用现有 `r107flow/runtime`，不要复制 15 GB 运行时。`tools/launch_1649370.py --reuse-runtime r107flow` 会校验其中的 EXE SHA-256 为 `141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380`。
2. 确认 `tools/launch_1649370.py` 的 `GAME_ARGUMENTS` 只有 `+set 2439 0 +set cl_timeout 600 +set cl_connectTimeout 600`，**没有** `+cl_demo_play testdemo`。后者会进入 demo 回放，破坏真实连接验证。它曾在清理未提交工作树时被误恢复，本次已移除。
3. 确认下列文件存在：`runs/20261020-live-derived01/tls/auth.crt`、`auth.key`、`runs/gamestate-client0.bin`、`runs/r522-clean-compact.bin`、`runs/_patch_r336.py`、`runs/guard-build/client_loopback_tcp_guard-fixed.exe`。丢失时从 [资源索引](../resources/1649370/README.md) 的 `local/` 独立副本恢复。
4. 以下命令在**不同 PowerShell 会话**按顺序执行。服务进程会持续运行；每次使用新的日志名，避免旧日志追加造成误判。

## 已验证命令序列

终端 A，启动 LSG 监听：

```powershell
python -m server319.lsg --cert runs\20261020-live-derived01\tls\auth.crt --key runs\20261020-live-derived01\tls\auth.key --port 28969 --allow-auth-tls --seconds 600 --log runs\r522-lsg.jsonl
```

终端 B，启动游戏服（此处保留本次实测的资源与参数）：

```powershell
python -m server1649370.gameserver --port 28969 --delay-send 1 --gamestate-source file --gamestate-file runs\gamestate-client0.bin --gamestate-gametype war --gamestate-map mp_crash_tropical --snapshot-file runs\r522-clean-compact.bin --snapshot-delay 1 --snapshot-seq 4 --snapshot-repeat 500 --snapshot-interval 0.1 --match-duration 600 --log runs\r522-gs.jsonl
```

终端 C，启动客户端。`r523` 只是记录名；真正的运行目录仍为 `r107flow/runtime`：

```powershell
python -B -X utf8 tools\launch_1649370.py --name r523 --reuse-runtime r107flow --until-close --local-profile --full --local-auth-lsg --loopback-tcp-guard
```

客户端进程起来后，在另一个终端按顺序执行。先取得本次 PID，不能沿用历史 PID：

```powershell
$gamePid = (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'codol1649370-offline.exe' -and $_.CommandLine -like '*r107flow*' } | Select-Object -First 1).ProcessId
python tools\patch_retry_ms_1649370.py --pid $gamePid --ms 0
python tools\drive_login_state_machine.py --ticks 20 --interval 0.35 --set-ui-state 1
python runs\_patch_r336.py $gamePid
```

完成以上补丁后，在终端 D 启动 UDP 桥：

```powershell
python tools\ring_bridge_1649370.py forward --target 127.0.0.1:28969 --bind-port 29023 --start-challenge --retry-seconds 0 --seconds 180
```

`--seconds 180` 只给桥 3 分钟观察窗口，需要更长对局时可提高时长。不要在桥之前执行 `+cl_demo_play` 或切换到零售 EXE。

## 验证与留痕

```powershell
python runs\_sample_state.py $gamePid 28 500
```

本次客户端采样从 `net_state=8` 前进至 `10`，`ui_state=0`；服务端 `r522-gs.jsonl` 最后一个 `start` 段有真实握手与快照。`r522-gs.jsonl` 先前已有一段历史内容，统计时要从**最后一个** `kind=start` 算起。客户端命令行应指向 `r107flow/runtime/codol1649370-offline.exe` 且不含 `+cl_demo_play`。

证据：`runs/r523-launch.out`、`runs/r523-retry.json`、`runs/r523-drive.json`、`runs/r523-patch.log`、`runs/r523-bridge-console.log`、`runs/r522-gs.jsonl`。这些 `runs/` 产物是本机记录，已将关键输入文件和启动辅助件备份至资源目录；日志可按本流程重新生成。

## 容易混淆的旧路线

`1649370-RESCUE-HANDOFF.md` 中的 TP/TCLS、`4174` LSG、系统信任 CA、`7 文件 + hosts` stage 配方，针对零售客户端 `codoMP_client_shipRetail.exe`。零售路径仍需单独验证。本流程使用离线 EXE 和本地桥，不能把两者的日志、证书或“没有进图”的结论互相套用。

上游完整 stage 配方和证书指纹已记录在[资源索引](../resources/1649370/README.md)。本轮先保存资源与已验证启动方法，不继续开发玩家生成或快照编码。

## 运行细节与易错点（2026-10-26 复核补充）

### 同端口、不同协议，并不冲突

```powershell
python -m server319.lsg      --port 28969   # TCP
python -m server1649370.gameserver --port 28969   # UDP
```

`lsg` 是 **TCP**，`gameserver` 是 **UDP**，两者可以同号共存。看到两条命令都用 `28969` 不要当成端口冲突去改号——改号会让 `ring_bridge` 与客户端的既有参数一起失效。

### `_patch_r336.py` 到底打了什么（这是能进图的关键，不是可选项）

脚本头部自述的两个结构性补丁：

```
1) 0x42F32C: 73 23 (jae +0x23) -> EB 23 (jmp +0x23)
   原因：该路径做 edx = [esi*4 + 0x1988B50] -> .data 零页 -> 0
        再 edx = [edx] -> 读地址 0 -> 访问违例
   而武器表项在本场景恒为 0，所以必须无条件跳过这条受保护路径。

2) 0x59B560: 55 8b ec 56 ... -> C3 90 ...
   这是 "assert id == index" 校验函数，在 0x42F3E0 -> 0x42F2F0 的
   1700 次迭代里第一次就 fault。跳过它让循环跑完（实测 cond=1699）。
```

**这两个补丁属于「绕过校验」，不是「修复数据」。** 它们解释了为什么历史上那个 `181 ** 646 0 0 8738 9321 1136 1224` 弹窗不再挡住进图：

- `0x59B560` 是武器定义索引校验（引用 1224 vs 本地定义 1136，差 88）
- `0x42F32C` 是空武器表导致的空指针路径
- 真实根因（服务端 gamestate 提供的武器定义数量不足）**仍然存在**，见下方「仍未解决」。

**没有这两个补丁，客户端会在进图前中断**；有了它们，进图与大厅可用，但画面里依旧没有可控玩家。

### `patch_retry_ms_1649370.py --ms 0` 改的是比较常量，不是逻辑

```
0x5C06B3  cmp eax, 0xBB8  ->  cmp eax, 0x00000001
```

它是把 3000 ms 重试阈值降到 1 ms，**保留**了"每帧最多一次"的时间比较。此前的 `patch_nodelay` 把整个 `jl` 换成 nop，会让状态机**每帧**都构造并发送 `getchallenge`，反而使客户端不稳。**不要回退到 nop 版本。**

### 状态采样地址（`_sample_state.py` 实际读的全局量）

| 名称 | 地址 | 说明 |
|---|---|---|
| `cls.state` | `0x76446B0` | **这个才是连接状态**（net_state 判据） |
| `ui_state` | `0x84ABA50` | 0=大厅，5=CA_LOADING |
| `dw` | `0x84ABA40` | |
| `acc` | `0x84ABA60` | 账号状态 |

早期记录里出现过 `cl->state` 与 `cls.state` 混用；**判据一律用 `0x76446B0`**。

### 服务启动的必需参数陷阱

- `server319.lsg` 的 **`--log` 是必需参数**（不在方括号里）。缺它时 argparse 直接 `rc=2` 退出，而如果 stderr 被丢弃，就会表现为"服务已启动但没监听"。
- `server319 --auth` 的 `--evidence` 路径**必须位于 `319/runs` 之内**，否则 `rc=2`。
- **启动后要验证端口 bind**，不要以"进程起来了"当作"在提供服务"。

本流程用的 `lsg` 命令已带 `--log`，符合要求。

### 清理进程的规矩

- `run_match.py` 在失败返回时**不会**清理自己启动的子进程，会留下孤儿（历史上有两个 `--seconds 3600` 的进程挂了两小时）。
- 清理时**按精确 PID**，不要按进程名匹配（`Stop-Process` 匹配 `server319` 会连自己的工具一起杀）。
- PowerShell 里不要用 `$pid`（只读自动变量），用 `$gamePid` 之类的名字。

### `cacert.pem` 与本离线流程无关

本流程用 `r107flow` 离线 EXE + 本地桥，**不需要**修改客户端的 `cacert.pem`、`dwauth.ini`、`stun.ini`、`iips.ini` 或 `TCLS/`。
那些是**零售客户端** `codoMP_client_shipRetail.exe` 的 staging 手段（见 `../resources/1649370/README.md` 与 `1649370-RESCUE-HANDOFF.md` §12）。**不要把两条路线的配置改动混用。**

### 日志判读

- `r522-gs.jsonl` 里包含历史段。统计握手/快照次数时**只从最后一个 `kind=start` 开始算**。
- 客户端命令行应指向 `r107flow/runtime/codol1649370-offline.exe`，且 **不含** `+cl_demo_play`。带它会进 demo 回放，看起来"有画面"但不构成真实连接验证。

## 仍未解决（不要误记为已解决）

| 缺口 | 机制 | 现状 |
|---|---|---|
| 画面里没有可控玩家 | 本地玩家实体 / 相机缺失 | 未解决；r523 只有地图与 HUD |
| 没有武器模型、准星、弹药 | **`ps.weapon` = 0**（playerState 字段 57 / offset `0x4C`） | 未解决 |
| 武器定义索引差 88（1136 vs 1224） | 服务端 gamestate 的武器定义数量不足 | 被 `_patch_r336.py` **绕过**，根因未修 |
| 移动/射击可控性 | —— | 未达成，验收第 5 项未完成 |

**关于 `ps.weapon` 的一个机制性线索**：playerState 字段表（`0xDA63E8`）第 1 项是 `offset=76 codec=-58`，而 `0x4C = 76`。也就是说 **`ps.weapon` 用的正是 codec `-58`**，而 `server1649370/ps_codec.py` 在 2026-10-26 之前**根本不支持 `-58`**（`write_field` 会抛 `unsupported codec`）。所以"服务端从未能编码 `ps.weapon`"不是遗漏给值，而是缺少编码分支。该分支现已补上（见 `local/unverified/ps_codec.py`），但**尚未在任何客户端上验证过**。
