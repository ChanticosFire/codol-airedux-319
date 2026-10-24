# demo 播放实测记录（2026-10-24 12:0x–12:1x）

目的：用 2021-08 真实 demo（`0C-2021-8-26[19-26-24]war.demo`，地图 `mp_crash_tropical`）
把「渲染问题」与「数据问题」永久分开，并为进图链路找到缺失资源。

---

## 1. 已经做到的事（有截图/日志）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 客户端能正常启动到**主菜单/大厅**，UI 完整渲染（不是黑屏） | `runs/demo-run4-t0.png` |
| 2 | `cl_demo_play <demo>` 是**可用命令**：Cbuf 注入成功（stage=5，长度 0→46） | `runs/demo-run4-cbuf.json`、`demo-run5-cbuf.json`、`demo-run6-cbuf.json` |
| 3 | 命令执行后客户端**确实开始加载 demo 的地图资源**，并逐个报缺失文件 | 见 §2 |
| 4 | `mp_crash_tropical*.ff` 三个 461 签名 fastfile 已可从 `ff_init_mp_crash_tropical_V73.ifs` 正确提取并部署 | `docs/IFS-MERGE-RESULT.md` §9.2 |

**结论 1**：demo 播放路径是通的（命令被接受、进入地图加载），不是命令名/参数错误。

## 2. 缺失文件的序列（每次崩溃只报一个，逐个补齐）

| 顺序 | 客户端请求的路径 | 性质 | 解决方式 |
|---:|---|---|---|
| 1 | `images/loadscreen_mp_crash_tropical.iwi` | 地图专属加载画面 | 放入 `runtime/devraw_shared/images/`（来自 `runs/20261022-crash-tropical-loose-v461`） |
| 2 | `images/dpad_ks_uav.iwi` | **MP 通用 UI 图标** | 放入 `devraw_shared/images/`（来自 `runs/20261022-gametype-loose-v461`） |
| 3 | `localized_common_gametype_mp.ff` 的 zone | gametype 本地化 fastfile | 从 `ff_init_common_gametype_mp_V69.ifs` 的**成员 1** 提取（41,237 B，5 块，zone 63,100，892 asset） |

补齐方式（实测有效，3 秒）：

```powershell
# runtime 已装配后，把 5 个 loose 包整体并入 devraw_shared
robocopy runs\20261022-crash-tropical-loose-v461\main <runtime>\devraw_shared /E
robocopy runs\20261022-crossfire-loose-v461\main       <runtime>\devraw_shared /E
robocopy runs\20261022-gametype-loose-v461\main        <runtime>\devraw_shared /E
robocopy runs\20261022-dmz-loose-v461\main             <runtime>\devraw_shared /E
robocopy runs\20261022-survival-loose-v461\main        <runtime>\devraw_shared /E
```

共 3,301 个文件 / 336,823,002 B。

## 3. 同时修复的 overlay 坏件（离线，已复核）

`docs/IFS-MERGE-RESULT.md` §7 指出 overlay 有两个结构非法的 fastfile；本会话已替换并复核：

| 文件 | 旧 | 新 | 检查 |
|---|---|---|---|
| `common_gametype_mp.ff` | 34,783,232（`mod 0x2000 = 0`，结构非法） | **34,693,397**（4235 块，1400 asset） | `check_overlay_ff.py` OK |
| `mp_cross_fire.ff` | 41,648,405（2.6.9.7 365 原件 + 1 字节补丁） | **37,331,221**（4557 块，240 asset） | OK |
| `localized_common_gametype_mp.ff` | 缺失 | **41,237**（5 块，892 asset） | OK |

旧件备份在 `runs/ifs-merge/baseline_*.ff`。overlay 现在 23 个 `.ff` 全部结构合法。

## 4. 待验证（下一次运行）

替换 overlay 后重跑 `cl_demo_play`，观察：

- 是否越过 `WIN_ZONE_ERROR: [localized_common_gametype_mp.ff]`；
- 是否继续报新的缺失文件（若有，按 §2 方式补）；
- 是否出现 `mp_crash_tropical` 的真实对局画面（**唯一验收：截图里出现地图**）。

## 5. 已知干扰

本轮期间有另一个执行体在同一项目里并行跑联机实验（`runs/codex-r242-*`，12:11:25 起，
含自己的客户端 PID 24080）。两个客户端同时运行会争窗口/焦点，
因此 `cl_demo_play` 的最终判定应在其运行结束后进行。

## 6. 2026-10-24 12:15–12:20 复测：资源缺失消失，改为 dvar 空指针

overlay 修复后重跑（`demo-run9/10`，`--full`，注入前先确认主菜单）：

- 不再出现 `WIN_FILE_NOT_FOUND`（`loadscreen` 图、`dpad_ks_uav`、`localized_common_gametype_mp` 都已齐）；
- 客户端进入 `unhandled_exception`：**`0xC0000005` @ `0x43204F`**，`mov ecx, [edx+0xC]`，`edx = [0x32AA908] = 0`；
- 调用栈与栈内容显示它正在处理 **`mp_crash_tropical` / `war`** 的 configstring（`g_gametype\war\g_hardcore\0\mapname\mp_crash_tropical`），并加载 UI 字符串表（`MP_WAITING_FOR_PLAYERS`、`MP_OBJECTIVE_NEUTRAL` …）。

静态确认：

| 地址 | 事实 |
|---|---|
| `0x32AA908` | 全局 dvar 指针；唯一写入点 `0x4E8A68`（`mov [0x32AA908], eax`），其参数含字符串 **`g_gametype`**（`0xDAFAD4`） |
| `0x432000` | 把入参复制到栈、按 **`"|"`**（`0xDB0224`）切分、再与 `[g_gametype+0xC]`（dvar 当前字符串）比较 |
| `0x7CB6BC` | 另一处读取点**有空检查**（`cmp [0x32AA908],0; je ...`），说明部分代码允许它为空；`0x43204F` 没有 |

**结论**：demo 播放已经走到"应用对局 configstring / 判定 gametype"的阶段，**资源问题已排除**；
卡点是离线壳里 **`g_gametype` dvar 尚未注册**（dvar 注册发生在进入游戏/地图初始化时，
而 demo 播放是在主菜单直接发起的）。

**含义**：demo 播放**不能绕过** `CA_LOADING`——它需要先完成游戏初始化（dvar/地图）；
反过来说，一旦主线能进入地图，demo 回放应可立即工作。demo 作为"渲染基准"的价值到此为止：
它已证明渲染与地图资源链路完好，剩下的都是**游戏状态初始化**问题。

## 7. 2026-10-24 12:22–12:31：补丁推进与完整服务端流程

### 7.1 demo 的 dvar 根因被二次确认

- 运行时把 `0x432049` 的 `mov edx,[0x32AA908]; mov ecx,[edx+0xC]` 改成 `jmp 0x43208E`（`EB 53 ...`），
  崩溃**前移**到 **`0x5A5AC3`**（`mov esi,[eax+0xC]`，`eax=0`）——同一 `g_gametype` dvar 的第二个解引用点
  （`0x5A5AB0` 也读 `[0x32AA908]`）。
- 控制台 `set g_gametype war` 之后 `[0x32AA908]` 仍为 **0**（读内存确认）——`set` 不创建未注册 dvar。
- `map mp_cross_fire` / `devmap mp_cross_fire` 注入后客户端**仍留在大厅**——离线壳里这些服务器命令不生效。
- 结论：demo 播放必须在"游戏已初始化"之后；离线壳没有这条路径，demo 不能作为进图替代。

### 7.2 完整服务端流程跑到"客户端发起 connect"

按 `server1649370/README.md` 的 Quick start 搭起：

| 进程 | 命令 | 结果 |
|---|---|---|
| LSG | `python -m server319.lsg --port 28969 --allow-auth-tls` | 登录成功（`client_frame_verified`） |
| gameserver | `python -m server1649370.gameserver --port 28971 --snapshot-file runs/snapshot-hybrid-empty-actors.bin --match-duration 60` | 收到 connect/stats，发出 gamestate + 5 个 snapshot |
| bridge | `python tools/ring_bridge_1649370.py forward --target 127.0.0.1:28971 --bind-port 29000 --adr-type 2 --fake-stats --keepalive` | 转发正常 |

触发方式：`python tools/probe_2697_connect.py --host 127.0.0.1 --port 29000 --name crossfire`
（`ring_bridge connect` 只写地址，不触发 getchallenge；`probe_2697_connect` 才会触发完整握手）。

- 服务端日志：`in oob connect`(401 B) → `in connect` → `out oob`×4 → `in oob stats` → `out fragment`(gamestate) → `snapshot_source`×5；
- 客户端：**离开大厅进入地图加载画面**（`runs/fullflow-t50.png`，背景是 loading 纹理，不再是主菜单），
  但弹出 **"无法连接主机"**，`net_state=0`、`ui_state=5`。

**判断**：客户端确实尝试进图，卡点在 **gamestate 分片/确认层**（bridge 转发后客户端没接受），
不是资源或渲染问题。下一步应修 bridge 的 gamestate 分片（或改用 `inject_client_gamestate.py` 直接注入）后再看 `net_state` 与 `ui_state`。
