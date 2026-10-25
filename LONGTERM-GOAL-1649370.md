# 长程目标（新对话直接使用）

> 把下面分隔线内的全文作为新对话的第一条消息发出即可接续。

---

## 任务：推进 CODOL Build 1649370 自建服务端，达成「玩家可自由移动、射击的操作型对局」

**项目根**：`E:\GAME\COD\codol-airedux\319`
**游戏**：CODOL Build 1649370（3.19.26.22），版本不可变更
**自建服务端**：`server1649370/gameserver.py`（UDP 游戏服）+ `server319/lsg`（认证）
**交接总结**：先读 `HANDOFF-1649370.md`；详细实验日志在 `1649370-STATUS.md`（至 §527）

**后续实测（§526）**：正确 codec 的 `client_number=0`，以及再加 `1735=Player`，都未使角色出生；不要重复。`0x6C7` 是否是本 build 的玩家名 bank 仍未知。

**最新修正（§527）**：逐条 hook 证实原版 245 B 快照解析玩家状态成功（错误位 0，出口 bit 1382）；把 `0x35` 从 `01` 改成 `00` 后，玩家状态解析已报错（错误位 1，出口 bit 994），但运行时跳过错误仍可能进入 `CA_ACTIVE(10)` 并显示地图。因此此前“`pm_type=0` 已是有效非观战快照”的判断不成立，不能以该单字节补丁为构造基础。两次实验均复用 `r107flow/runtime`，未创建大型运行时。

### 最终目标

客户端与服务端建立真实连接，`server1649370` 下发 gamestate/snapshot，
客户端加载 `mp_crash_tropical`，进入【玩家可自由移动、射击的操作型对局】；对局可结束并返回大厅。

### 验收标准（5 项，须全部满足）

| # | 验收项 | 当前 |
|---|---|---|
| 1 | gs 日志出现真实 `connect`/`stats` 包 | ✅ 已达成 |
| 2 | 客户端 `net_state` 由握手推进 | ✅ `CA_ACTIVE(10)` |
| 3 | 对局可结束并返回大厅 | ✅ `disconnect` → 完整大厅 |
| 4 | `ui_state != 5` | ✅ 全程 `ui=0` |
| 5 | 截图是【可自由操作的对局】（能移动/射击，**不是 demo 播放器**） | ❌ **唯一未达成** |

**你的任务就是攻下第 5 项。**

### 当前卡点（已精确定位）

客户端已 `CA_ACTIVE(10)`、世界正常渲染，但当前改字节样本的玩家状态解析会报错；
画面仍停在「战术团队竞技模式 + **按 空格↓** + 计分板 0 0」，
**玩家角色从未 spawn**，因此玩法输入不被消费。

- 「按 空格」的确切来源：configstring **index 1424 = `PLATFORM_PRESS_TO_SPAWN`**
- 阻塞点在**服务端下发的玩家数据**，不在输入层

### 勿重复验证（已用实验排除，省时间）

1. **输入通道不是问题**：`SendInput` / `GetKeyboardState` IAT 钩子 / `PostMessage` /
   `WM_CHAR`+鼠标，覆盖**全部 7 个窗口**（含 CEF `Chrome_WidgetWin_0`、`CoD Splash Screen`），
   消息均入队成功（返回 1），`pm_type`/`origin` 均不动。
2. **客户端从不调用 `GetKeyboardState`**：带计数器的钩子证明调用计数恒 0。
3. **无 DirectInput/RawInput**：模块清单无 `dinput8`/`xinput*`/`hid`。
4. **`forwardmove` 不在 `cl`**：全扫 `cl+0x0..0x9000` 不存在。
5. **`cl+0x3B98` 不是可控 clientNum**：连写 0 共 60 次，每帧被重置为 -1，无任何效果。
6. **不存在 CoD 风格 configstring 数组**：全内存扫描 1007.7 MB，`\sv_hostname\` 0 命中。
7. **`WM_ACTIVATEAPP(1)` 会导致客户端断开**，不要发。
8. **demo 回放不算达成**。

### 已经掌握的能力（直接用）

**可自建 gamestate**：`tools/build_gamestate_1649370.py` 与真实文件达成
**BYTE-EXACT ROUND-TRIP**（6411 字节逐字节一致）：

```
--check FILE                                      解析 + 往返验证
--in F --out F --set-client N                     改 client_number
--in F --out F --add-player IDX --add-value STR   插入 text 条目
```

**gamestate 结构**（已实测吻合）：
```
tag3 | server_command_sequence u32 | map | zone | checksum u32
| tag4 | ConfigStrings | tag5 | client_number u32 | checksum_feed u32 | tag5
```
**ConfigStrings 编码**（`SLOT_COUNT=12761`、`MAX_TEXT_BYTES=8191`）：
```
count u16
text[]:   index = 1 bit("==prev+1") 否则 14 bit 绝对索引 ; 然后 NUL 字符串
simple:   count 10 bit ; 每项 index + 11 bit model
complex:  count 11 bit ; 每项 index + 11 + 8 + 1(+9) + 4(+14*n)
```
字符串 NUL 终止；位流 LSB-first；gs 在文件前加 4 字节 `00 00 00 00` 封装。

**已实测的关键事实**：
- gamestate 有 **291 条 configstring**（索引 0..12249），不是 3 条
- **`client_number = 1`**（demo 抓包值）→ 单客户端连接应分配 **0**
- **`simple`/`complex` 段都是 0**，模型引用用**文本 `* <modelIndex>`** 放 text 池
  → **加玩家数据只需改 text 池，不必碰位流段**
- 参考实现（1604220）的玩家名 bank 是 `0x6C7 + clientIndex`，
  但我们的 gamestate 里该区间**为空**（来自 demo，本地回放不需要玩家 configstring）
  → **本 build 的真实玩家 bank 索引仍需自己测**

### 建议的攻坚顺序

1. **定位本 build 的玩家 configstring 索引**
   - 反汇编 `CL_ParseSnapshot`（`0x471E90`）附近，找 `0x6C7 + reg` 或类似的 base+index 常量
   - 或在 demo 回放时观察哪个索引区间被玩家数据填充
2. **继续验证玩家条目索引与格式**；`client_number=0` 和 `1735=Player` 已实测无效，不能当作尚未试过的方案
3. **先生成能完整解析的玩家状态，再加入本地实体与位置**
   - `0x35=0` 会在玩家状态块内报错，旧样本的 `CA_ACTIVE(10)` 不能证明快照有效。
   - 原版 245 B 的玩家状态出口 bit 1382、无错误；以此为参照定位变化字段的编码。
   - 然后定位实体表位游标、构造本地实体与位置，并验证合法终止符及移动/射击。
4. **定位 cgame 的 `cg` 全局**，查 `cg->spectatorClient` / `cgs->clientNum`，确认「按空格」判据

### 关键地址（全部经实测）

| 项 | 值 |
|---|---|
| `cls.state` | `0x76446B0`；`CA_ACTIVE=10`、`CA_PRIMED=9`（**非教科书 5/6**） |
| `cl` 指针 | `[0x76638F4] ^ 0x6891D1C7`（是 `clientActive_t`，**不是** `clc`） |
| `cl->playerState` | `cl + 0x3BA4`（`pm_type` 在 `+0`） |
| 玩家坐标 | `cl + 0x3C80/84/88`（x/y/z） |
| snapshot 解析标志 | `cl + 0x3BE4` |
| `cl->cmdNumber` | `cl + 0x3B94` |
| gamestate `[3]` | `cl + 0x3BE8`（=155） |
| `ui_state` | `0x84ABA50` |
| 产品标识校验 | `0x4549EB..0x454A28`（`strcmp(edx,"cod")`，失败即 `Com_Error`） |
| 主窗口 | class `CODO`，1920×1080 |

### 环境与工作流

**启动序列**（约 60 秒）：

```
1. python -m server319.lsg --cert runs\20261020-live-derived01\tls\auth.crt \
     --key runs\20261020-live-derived01\tls\auth.key --port 28969 --allow-auth-tls --seconds 600
2. python -m server1649370.gameserver --port 28969 --delay-send 1 \
     --gamestate-source file \
     --gamestate-file runs\demo-outer-exact\gamestate-network-ffb56d7e-6411.bin \
     --gamestate-gametype war --gamestate-map mp_crash_tropical \
     --snapshot-file runs\snap-nospec-1.bin \
     --snapshot-delay 1 --snapshot-seq 4 --snapshot-repeat 5000 \
     --snapshot-interval 0.1 --match-duration 600 --log runs\rNNN-gs.jsonl
3. python -B -X utf8 tools\launch_1649370.py --name rNNN --reuse-runtime r107flow \
     --until-close --local-profile --full --local-auth-lsg --loopback-tcp-guard
4. python tools\patch_retry_ms_1649370.py --pid <pid> --ms 0
5. python tools\drive_login_state_machine.py --ticks 20 --interval 0.35 --set-ui-state 1
6. python runs\_patch_r336.py <pid>          # 运行时补丁 + 全局对象初始化
7. python tools\ring_bridge_1649370.py forward --target 127.0.0.1:28969 \
     --bind-port 290NN --start-challenge --retry-seconds 0 --seconds 400
```

**快照配方**（`runs/snap-nospec-1.bin`，245 B）：
```
源: runs/demo-outer-exact/baseline-outer17-245.bin
0x35 : 01 -> 00              ⇒ pm_type: PM_INTERMISSION(2) → PM_NORMAL(0)
0x0F / 0x14 / 0x18 : x / z / y (float)
```

**诊断脚本**：`runs/_hook_gks2.py`、`_hook_gks_count.py`、`_verify_gks_hook.py`、
`_find_forwardmove.py`、`_find_real_configstrings.py`、`_parse_gamestate_ref.py`

### 约束

- 坚持 Build 1649370；**不虚构达成**；demo 回放不作为达成依据
- 每轮更新 `1649370-STATUS.md` + `PROJECT_STATUS.md`，本地 commit 并 **push**
  （remote `codol-airedux-319`，分支 `main`）
- **绝不能杀 launch 起的 python 进程**（`--until-close` 会连带终止客户端）
- `runs/` 被 gitignore，新证据需 `git add -f`
- `disconnect` 是退出对局回大厅的正确命令；`switchtomainmenu` 会杀进程
- `--local-auth-lsg` 强制 `--loopback-tcp-guard`，只支持端口 28969
- 已获授权：可打补丁、可改程序（运行时改代码、patch 运行副本 exe、改服务端/工具源码）

### 一句话

连接、进图、渲染、服务端驱动移动、退出回大厅**全部已跑通**；
现在只差一件事 —— **让客户端真正 spawn 一个属于自己的、可被操作的角色**。
输入层已彻底排除，问题在服务端下发的玩家数据（configstring 玩家条目 + 快照实体）。
