# Build 1649370 离线对局：当前交接（2026-10-27）

> **2026-10-28 r735/r736 新边界**：当前活库 revision 1241 的选中角色直接读得 570。按社区 `codol_client_projection164.c` 的 team/character/typed 字段构造本地 client 0 记录，分别发送 team1 与 team2；服务端分别记录候选快照 835/1040 次，客户端 `net=10`，内存 0x160 字节记录随队伍位从 `(0x4=1,0x154=0)` 变为 `(2,1)`，均有 `0x7c=570,0x150=1`。这直接证明 **clients 段被原生客户端解析并缓存**，但尚未证明角色 570 的默认模型部件完整注册、cgame 的 clientInfo 已采用或本地实体满足渲染条件。两张场内截图仍无枪/手臂，射击未验收。直接读 `[0x84ABA50]=5` 仍不满足原验收字面条件；然而 §1273 早已显示值 5 与活跃 handler、对局倒计时并存，**不能再把 5 单独解释成加载页**。详细命令、哈希和边界见 `1649370-STATUS.md` §1308 与 `evidence/experiments/20261028-r735-r736-typed-clientstate.json`。活库与唯一运行时基线未变。

> **2026-10-28 补证与撤销**：我按新增的项目规则复核了三件事，脱敏记录见 `evidence/experiments/20261028-r731-r733-audit-followup.json`。r731 注入 `cg_thirdPerson 0→1→0` 后，三张地图截图均无第一人称枪/手臂；但尚未读取 dvar 内部值，因此只能说画面阴性。r732/r733 加入社区格式的 **client 0 空记录**，两次独立连接均 `net=10`、AK-47/30 HUD 可见而枪模仍缺；r734 在无 cvar 注入时用默认快照作严格对照，同样无枪。**四次直接读取 `[0x84ABA50]` 均为 `ui_state=5`，即使地图画面可见，第 4 项仍不达标。**撤销本页旧“未测量 ui_state”与任何依据地图画面推定 `ui_state != 5` 的说法。旧“最小实体复核从未执行”也不准确：r696 快照生成器早已包含 `(0,type 1,{2:200.0})`，r731–r734 重复发送并进入 `net=10`；实体内部计数未读。客户端内部是否采用了空 client 记录未读，带有效外观的记录仍待测。后文若冲突，以此补证与原始日志为准。

> 本文是**当前有效**的交接文档，取代 `1649370-HANDOFF.md`（2026-10-21/22 的旧 bot 阶段记录）作为入口。
> 所有结论都对应 `runs/` 下的截图/日志或 `evidence/experiments/` 的脱敏 JSON；`1649370-STATUS.md` 有逐轮细节。

> ⚠️ **开工前必读（强制）**：`AGENTS.md`（项目工作规则，含归因、复用、工程改动、验收测量等硬约束）与 `1649370-AUDIT-20261027.md`（已犯错误清单）。
> 违反规则必须在当轮文档里写明"违反了 R x.y，原因…"。规则里的 R2.3 要求：**"下一步"里出现 ≥2 次仍未执行的条目，当轮必须执行或给出阻塞证据**。

---

## 0. 一句话结论

**自建连接能显示地图、AK-47/30 HUD，掉线后也曾回大厅；但第一人称枪/手臂与射击仍缺，r731–r734 地图可见时 `ui_state` 仍为 5，回大厅后的仓库功能也未验证。**“cgame 不提交 viewmodel”只是待验证的接收端推断；先分别核对服务端发送、客户端读取和渲染门控。

---

## 1. 环境（唯一，勿复制）

| 项 | 值 |
|---|---|
| 工作仓库 | `E:\GAME\COD\codol-airedux\319`（`main`，远端 `ChanticosFire/codol-airedux-319`） |
| 客户端镜像 | `E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe`，SHA-256 `55f067ac…3ffd` |
| **唯一运行时** | `E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime`（约 15 GB，**不复制**） |
| 运行中镜像 | 同上副本，SHA-256 `141215dd…d380`，仅 6 处 VA 改动（`0x4730A0`、`0x4FDAE2`、`0x77EEA5`、`0x7E993D`、`0xD8CCFE`、`0xE579F0`） |
| 地图 | `runtime\client_shipretail\chinese\mp_crash_tropical.ff`（32,620,821 B，10-24，未改） |
| 活库 | `data\v1649370\local.sqlite3`，**基线 SHA-256 `06f7a93b…2f70`，integrity=ok** |
| 基线备份 | `resources\1649370\local\profile\pre-r640-certenv.sqlite3` |

**流程纪律**：开工前备份库；只按**精确 PID** 结束本轮启动的客户端/游戏服/桥/LSG；收尾核对库 SHA-256 与 integrity；被改写则隔离到 `resources\1649370\local\profile\quarantine-post-<轮次>.sqlite3` 并从基线整库恢复。`resources/1649370/local/` 永不入库。

---

## 2. 已证实的成功

### 2.1 ps 段与 gamestate 段被正确解析（范围已收窄，见审查文档）

> 2026-10-27 自查修正：原措辞"帧格式与整条通路正确"**过强**。真实 demo 帧只证明 **playerState 段与 gamestate 段**被正确解析（cgame 据此渲染观战提示）；**实体段未验证**（r703 的玩家实体帧直接让客户端崩溃），clients 段与 glass 段从未成功下发。

把 2021 年真实 demo 的**完整基线帧原样**下发（`runs/r695-demo-outer/baseline-outer17-245.bin`，245 B）：

- 客户端 `net=10`；
- 画面出现**观战覆盖层**：`鼠标左键 - 下一位玩家 / 鼠标右键 - 上一位玩家 / E - 第一人称`；
- 回读 `pm_type=5`、`clientNum=1`、`weapon=0`、`viewmodelIndex=0`、origin `(336,60,261)`。

**含义**：服务端 → 桥 → 客户端 ring 的链路能承载真实服务端帧，**ps 与 gamestate 段的编码/解析无误**；`pm_type=5` 是观战/死亡态。实体段与 clients 段仍属未验证区。

### 2.2 能进入有效对局并显示地图

`runs/r716-nocmd-game.png`、`runs/r724-game.png`、`runs/r713-stable-game.png` 都是**真实对局画面**：

- `mp_crash_tropical` 柱廊场景正常渲染；
- HUD 完整：左上雷达、右上「得分/杀/亡/助」、左下对局时钟（27:26 / 28:16 / 21:17）、右下 **AK-47 + 30 发** +「全自动」；
- `ps` 同步 `weapon=78`、`clip=30`、origin 正确、`commandTime`/`command_number` 递增。

### 2.3 服务端 weapon 字段驱动 HUD

`runs/r718-switch-game.png`（weapon=0 帧）对比 `runs/r724-game.png`（weapon=78）：

- 78 → 右下有 AK-47 武器栏与 30 发；
- 0 → **右下武器栏整块消失**，时钟/雷达/得分仍在。

### 2.4 掉线后客户端能回大厅

- 掉线瞬间纯黑：`runs/r729-after.png`（6 KB，luma 0）；
- 5 秒后完整大厅：`runs/r729-later.png` —— 顶部「游戏大厅/开始游戏/生涯/商城/仓库/军火基地/赛事」、左侧每周任务/生涯任务、右侧四个玩法入口、右上角色「南韩超人朴玄俊 / 新兵」、货币 199993320 / 520；
- 中央弹「**服务器连接断开**」（不是 100/174/181）。

### 2.5 服务端侧日志真实

每个会话 `-gs.jsonl` 都有 `getchallenge`/`connect`/`stats`/`inband_sent/received`/`oob_sent/received`/`client_acked_ours`。例 r706：`connect=1`、`stats=2`、`inband_sent=9277`、`client_acked_ours=1`。

### 2.6 稳定性工程（已落地）

- **`--server-command-text off`**：r717/r718/r720 三个成功样本分别维持约 100/70/60 秒，期间未见「客户端指令溢出」；同期 r719/r721 连接失败、r729/r730 更早断线，**不能宣称稳定窗口已达到 60–100 秒**。
- **`tools/session_retry_1649370.py`**：最多 N 次重试 + 失败后精确 PID 清理；`--after-success` 在成功瞬间跑探针（`{pid}`/`{name}`）。

---

## 3. 当前卡点

### 3.1 核心：第一人称枪模/手臂不出现（验收 5 未达成）

以下字段已有直接回读，但玩家客户端列表、实体和渲染状态尚未全量验证：

| 已确认 | 证据 |
|---|---|
| `ps.weapon/primary/altWeapon = 78`，`clipWeapon=78`、`clipCount=30` | `read_client_ps` 实时回读 |
| `stats[0]`（`ps+0x1A4`）写入生效 | 实机回读 |
| origin / viewHeight / commandTime 正确 | 实机回读 |
| HUD 响应 weapon（武器栏显隐） | r718 vs r724 |
| `viewmodel_ak47` XModel 已加载（`0x2311A8C`，4 处引用） | 内存扫描 |
| 真实 demo 帧可渲染 | 观战覆盖层 |

**已尝试的局部变量**：`cg_drawGun 1`、`viewHeightCurrent`、`viewmodelIndex`（0/78/1023）、`pm_type`（0/5）、demo 差异字段、模型缓存表、`stats[0]`、configstring 武器名。审查 A2 已撤销“78→0→78 切换无效”：旧服务端只反复发送末帧，这项未形成有效循环实验。

**待验证推断**：HUD 响应了 `ps.weapon`，但客户端列表/实体是否满足本地玩家条件、cgame 是否提交 viewmodel，均缺直接读数。

### 3.2 连接不稳定（≈40% 失败）

同配置五次（r717–r721）：3 次成功（稳 60–100 s），2 次**未到 `net=10` 就进程退出**（`net=3/4`，`session.out` 停在 `bridge listening`）。

成功后仍会在 7–100 s 断开：r729 `t=32.37 s`、r730 `t=7.33 s`，**早于服务端主动 disconnect，不是我们踢的**。

### 3.3 两个弹窗

- 「**客户端指令溢出**」：与 serverCommand 相关，`--server-command-text off` 后消失；cbuf 实测峰值 **43 / 131072**，不是文本堆积。
- 「**服务器连接断开**」：掉线回大厅时的连接层提示。

### 3.4 尚未验证

- **大厅功能可用性**（仓库/背包/角色档案）：r730 尝试点「仓库」时 `--after-success` 里用了 `Start-Sleep`（cmd 不识别）导致后续未执行，**验证没做成**。
- **真实键鼠移动 + 射击（弹药消耗/命中反馈）**：完全没有。

### 3.5 已修的真实缺陷

`ring_bridge_1649370.py` 的 `_inject_raw` 原先在 16 槽 ring B 满时只重试 `60×10 ms` 就丢包（r710 实测 14 次 `ring_b_full`，客户端 `state=8` 时消费慢 → **gamestate 分片被丢**）。已改为有界背压（`RING_B_WAIT_SECONDS = 30.0`），r711 复测 `ring_b_full=0`。

---

## 4. 可复现的启动方式

### 4.1 稳定起会话（推荐）

```powershell
cd E:\GAME\COD\codol-airedux\319
python tools\session_retry_1649370.py --name rXXX --attempts 3 -- `
  --runtime r107flow `
  --gamestate runs/r694-gamestate-start.bin `
  --snapshot runs/r696-weapon78-health100.bin `
  --server-seconds 300 --bridge-seconds 300 `
  --restore-weapon-handler --restore-weapon-lookup-branch `
  --restore-weapon-init-indexing --weapon-lookup-fallback `
  --server-command-text off
```

- `r694-gamestate-start.bin`：真实 demo 开局 configstring（`435=1`、`15=1825900`，294 行）；
- `r696-weapon78-health100.bin`：92 B，weapon 78 / clip 30 / health 100 / origin `(336,60,260.5)`；
- **`--server-command-text off` 必加**。

### 4.2 成功瞬间跑探针

```powershell
--after-success "python tools/read_client_ps_1649370.py --pid {pid} --watch 1 && python tools/capture_window_bg.py --out runs/rXXX.png"
```

**注意**：`--after-success` 走 `shell=True`，在 Windows 上是 **cmd 语义**，不要用 `Start-Sleep`（改用 `powershell -Command "Start-Sleep 6"` 或把等待写进 Python）。

### 4.3 收尾与恢复

```powershell
# 只按精确 PID 结束：客户端、28969/29023 的 UDP 持有者、28969 的 TCP 监听者
(Get-FileHash data\v1649370\local.sqlite3 -Algorithm SHA256).Hash
# 若 != 06F7A93B…2F70 -> 隔离到 quarantine-post-<轮次>.sqlite3，再从 pre-r640-certenv.sqlite3 整库恢复
```

---

## 5. 工具清单（`tools/`）

### 会话与网络
| 工具 | 用途 |
|---|---|
| `session_up_1649370.py` | 一键起 LSG + 游戏服 + 客户端 + 桥并断言 `net=10`；支持 `--server-command-text off`、`--snapshot-dir`、`--match-disconnect N` |
| `session_retry_1649370.py` | 带重试 + 精确 PID 清理，`--after-success` 探针 |
| `ring_bridge_1649370.py` | 环缓冲桥（已修 ring B 丢包，30 s 背压） |
| `watch_drop_1649370.py` | 每 200 ms 读 `net_state`，掉线瞬间截图 |
| `capture_window_bg.py` | 后台抓窗口截图（输出 luma 极值） |
| `send_key_1649370.py` | 发送按键（`--vk 0x45`=E、`--vk 0x1B`=ESC） |
| `click_1649370.py` | 按客户区坐标点击（`--x 680 --y 57`） |

### 只读与内存
| 工具 | 用途 |
|---|---|
| `read_client_ps_1649370.py` | 读 `cl->ps` |
| `read_client_memory_1649370.py` | 读任意地址（`--ps` 相对 ps） |
| `scan_client_memory_1649370.py` | 值/字符串/`--range` 扫描（三者恰好一个） |
| `dump_range_1649370.py` | 原始字节 dump（供差分） |
| `twodump_diff_1649370.py` | 同进程两次 2 MB 差分（噪声 18179→56 字节） |
| `sample_diff_1649370.py` | 多采样 + 每样本标注 `ps.weapon` |
| `probe_cbuf_1649370.py` | 采样 cbuf 描述符 `0x76595A4`（峰值 43/131072） |
| `hook_ring_1649370.py` | ring 记录 hook |

### 帧构造与解析
| 工具 | 用途 |
|---|---|
| `build_weapon_probe_snapshot_1649370.py` | 构造快照（`--weapon-id --clip-count --origin --health --field offset=value`） |
| `build_entity_frame_1649370.py` | 构造带玩家实体快照（**实体段会让客户端崩溃，未通过**） |
| `decode_ps_1649370.py` / `decode_entities_1649370.py` | 解码 ps / 实体段（实体段仅零尾部帧可用） |
| `parse_demo_outer.py` / `dump_demo_cmds.py` | 拆 demo / 有序命令 dump |
| `add_configstrings_1649370.py` | 往 gamestate 合并 configstring |

---

## 6. 关键地址与结构（已核实）

| 项 | 值 |
|---|---|
| `cl` | `*(0x76638F4) ^ 0x6891D1C7` |
| `ps` | `cl + 0x0C` |
| `NET_STATE` | `0x76446B0` |
| cbuf 描述符 | `0x76595A4`（`{pointer, capacity=0x20000, length}`） |
| ring B | `0x786DBC0`，16 槽 × 0x504，读写 `0x7872C00 / 0x7872C04` |
| ring A | `0x7872C08`，64 槽，读写 `0x7886808 / 0x788680C` |
| weapon def 表 | `0x1988B50`（1171 项） |
| 服务端模型缓存 | `0x1C166E8`（1700×16 B） |
| `viewmodel_ak47` XModel | `0x2311A8C`（.bss 引用 `0x2605FDC` 等） |
| ps 字段 | `0x04` pm_type、`0x30/34/38` origin、`0x4C` weapon、`0x1A4` stats[0]、`0x170` viewHeightCurrent、`0x3F8` primary、`0x494` clipWeapon、`0x498` clipCount |

**tagged 记录（`0x2605F9C`）**：`+0x40 = 0x2311A8C`，与退出后逐字段一致 → **静态资源记录，不是 `cg_weapons` 运行时槽**。

---

## 7. 下一步建议（按优先级，已按 2026-10-27 自查重排）

> 自查后新增两条**低成本、未验证**的假设，应排在最前（详见 `1649370-AUDIT-20261027.md`）。

1. **`cg_thirdPerson` 已作 0→1→0 画面对照**：r731 三张截图均无枪/手臂；内部 dvar 值未直接读取，因此下一次应先读取该值，再决定是否继续这条方向。
2. **clients 段已有两种带角色 ID 的实测形式**：社区 `codol_clients164.c` 格式已移植；r735/r736 的 team1/team2 角色 570 记录进入原生 0x160 字节缓存，但均未出现枪/手臂。先核对角色 570 的默认身体部件是否在 gamestate 模型表注册，再直接测 cgame 的 clientInfo 是否采用，以及 `541800` 角色路径与 `5903F0/80E1D0` 第一人称模型提交条件；不能再把“未发 clients 段”当现有缺口。
3. **最小实体已在现有 r696 快照中**：r731–r734 重复发送并进入 `net=10`；仍需直接读实体计数，再与 r703 的两个实体崩溃样本逐字段比较。
4. **枪模的 cgame 提交路径**：
   - 已有：`twodump_diff`（同进程噪声 56 字节）、`sample_diff`（带 weapon 标签）。
   - **注意**：原写的"客户端拒收 `weapon=0` 帧"**是错的** —— 查 `-gs.jsonl` 的 `snapshot_source` 可见 `--snapshot-dir` 只重复**最后一帧**，0 帧各只发了 1 次。要制造切换必须让 0 帧成为末帧，或改服务端发送逻辑。
5. **稳定性**：连接阶段 ≈40% 失败 → `session_retry`（3 次期望 ≈94%）；另需**回归检查 ring 背压是否把丢包换成了阻塞**（修复后从未复查 `ring_b_full` 与掉线分布）。
6. **大厅功能**：重做 r730 未完成的验证 —— 掉线回大厅后用 `click_1649370.py` 点「仓库」并截图（`--after-success` 是 cmd 语义，别用 `Start-Sleep`）。
7. **验收 5**：真实键鼠移动 + 射击弹药消耗/命中反馈，目前完全没有。

---

## 8. 验收项对照（当前真实状态）

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 真实 `connect`/`stats` 日志，非 demo | ⚠️ `-gs.jsonl` 有真实会话计数（`connect=1/stats=2`），但**尚未确认是否符合"游戏服原生日志行"的口径** |
| 2 | 原生 `net_state` 有效对局且画面显示地图 | ✅ `net=10` + `mp_crash_tropical` 实拍 |
| 3 | 回大厅后仓库/背包/角色档案可用 | ⚠️ **只证实"能回大厅"，功能可用性未验证** |
| 4 | `ui_state != 5`、无 100/174/181 弹窗 | ❌ r731–r733 直接读 `[0x84ABA50]=5`；地图可见时仍不满足。历史还出现过「指令溢出」「连接断开」 |
| 5 | 真实键鼠移动 + 第一人称枪模/手臂/弹药 HUD + 射击反馈 | ❌ **未达成**（弹药 HUD ✅，枪模/手臂/射击 ❌） |
