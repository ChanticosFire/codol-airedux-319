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
