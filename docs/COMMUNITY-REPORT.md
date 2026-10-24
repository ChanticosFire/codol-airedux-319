# CODOL Build 1649370 自建服务端 —— 进度报告（社区版）

> 版本：1649370（3.19.26.22，关服前最后一个构建）
> 状态：**协议层全通，真实对局画面可复现；尚未做到 mp_cross_fire 可玩**
> 日期：2026-10-25

---

## 一、目标与现状（先看结论）

**目标**：自建服务端 `server1649370`，让 1649370 客户端进入真实地图 `mp_cross_fire`、可见可玩、对局能结束并回到大厅。

**现状（诚实结论）**：

| 项目 | 状态 |
|---|---|
| UDP 协议（getchallenge → connect → stats → gamestate → snapshot） | ✅ 全通 |
| 快照头格式（逐字节） | ✅ 已知 |
| 实体列表布局（门控位、计数、三段式 ID） | ✅ 已解 |
| demo 数据离线解析（真实服务器下发内容） | ✅ 已打通 |
| 真实对局画面（demo 回放 crash_tropical） | ✅ 已出现 |
| **服务端数据被客户端完整解析**（gamestate + 快照 3 个内容块） | ✅ 已出现 |
| **mp_cross_fire 可玩** | ❌ 未达成 |
| **对局结束回大厅** | ❌ 未达成 |

---

## 二、已达成（可复现）

### 2.1 协议层

`server1649370` 已实现并跑通：

- `getchallenge` / `connect` / `stats`（OOB，明文）
- `gamestate`、`snapshot`、`command`（inband，netchan）
- 分片规则：**小包（≤1162 B）直接发**（首 4 字节 ack）；大包加分片头
  （u16 长度 + `seq|0x80000000` + index/count + frag_size/len）

### 2.2 真实对局画面

用 22 个 2021-08 真实对局 demo 中的 `0C-2021-8-26[19-26-24]war.demo`
（`mp_crash_tropical`/`war`），配合一个关键补丁：

> 离线壳里 `g_gametype` dvar 没有注册，demo 播放在 `0x43204F` 空指针崩溃。
> 解决方式：**不改代码**，在客户端进程内伪造一个 dvar 结构
> （`name="g_gametype"`、`+0xC → "war"`），把 `[0x32AA908]` 指过去。

结果：`net_state` 1 → 8 → **10**，画面出现完整真实对局（地图、士兵、小地图、
比分、计时、玩家列表），且第二帧截图 hash 不同（画面在动）。

### 2.3 服务端数据被完整解析

在 demo 起状态（`net_state >= 7`）后接入 `server1649370`：

```
Dispatch=1（0x473420 包分发）
GamestateParse=1（0x472D80 gamestate 解析）
Entities=2（0x471D80 实体块）
PlayerState=1（0x471980）
Actors=1（0x471010）
```

→ **服务端下发的 gamestate 与快照内容块确实被客户端执行了**。

### 2.4 demo 数据离线解析（本次最大成果）

demo 是**明文数据**，格式：

```
[u8 type=0x01][u32 little-endian len][文本命令 ... \0][二进制数据]
```

已提取（样本 demo）：

| 命令 | 数量 | 含义 |
|---|---|---|
| `d <idx> <value>` | 540 | dvar / configstring |
| `p <frame>` | **1725** | packetentities（实体帧） |
| `w <a> <b> <c>` | 526 | 数据块 |
| `r` / `v` / `s` | 62 / 20 / 14 | 其他 |

其中 **1050 个 `p` 帧 ≥100 字节**，最大的一个 **62,474 字节**，开头：

```
00 d0 97 1a 00 01 04 05 d4 09 00 00 ...
```

按已知快照头格式解析完全吻合：

| offset | 值 | 含义 |
|---|---|---|
| 0 | `00` | svc_snapshot |
| 1–4 | `d0 97 1a 00` | serverTime |
| 5 | `01` | delta_distance |
| 6 | `04` | flags |
| 7… | `05 d4 09 00 00` | 位字段（含 8 位 last_changed） |

→ **demo 的 `p` 帧 = 真实服务器下发的快照体**，可直接作为服务端模板。

---

## 三、关键卡点（需要社区一起看）

### 3.1 `net_state >= 7` 才会处理 inband 包

`0x5C2260`（网络帧处理）里：

```asm
0x5C22FC  cmp dword ptr [0x76446B0], 7
0x5C2303  jl 0x5C2413          ; net_state < 7 → 直接丢包
```

这是之前所有"快照被丢弃"的真正原因，与包格式/加密/seq 无关。
目前只有 **demo 播放**能稳定把 `net_state` 推到 7+（`0x813D34` 无条件写 7）。

### 3.2 demo 播放约 20 秒后会崩溃

| 实验 | 是否有 gs | 存活 |
|---|---|---|
| 无服务端 | 无 | ≥24 秒（画面正常） |
| 有服务端（native gamestate） | 有 | 5–20 秒退出 |
| 有服务端（capture 真实 gamestate） | 有 | 7 秒退出 |

→ **崩溃由服务端 gamestate 触发**，不是 demo 本身。越早发越早崩。

### 3.3 换图三条路全部被实验排除

要把地图从 `crash_tropical` 换成 `mp_cross_fire`：

1. 改 demo 内 `d 2557 "mp_crash_tropical"` → 无效（§39）
2. 改 exe 常量 `0x9C6670` → 无效（§52）
3. 全量替换 demo 资产名 → state 8 崩溃（§35）

已知：demo 播放的地图加载发生在播放后 17–20 秒（`patch_mp_crash_tropical.ff` 请求），
但 `0x49ED40`/`0x49E160`/`0x776F00` 三个断点在播放期间都 0 命中 → 走的是另一条
尚未定位的路径。

---

## 四、可复现的数据产物（本次打包内容）

### 4.1 游戏服（零第三方依赖）

`server1649370/`：纯 Python 标准库（`argparse/json/socket/struct/time/dataclasses/pathlib`）。

```bash
python -m server1649370.gameserver --port 28971 \
  --gamestate-source capture \
  --snapshot-file templates/00-62474.bin \
  --snapshot-seq 100001 --snapshot-delay 1
```

### 4.2 demo 解析工具（零第三方依赖）

| 工具 | 作用 |
|---|---|
| `parse_demo.py` | 解析 demo 消息流 |
| `extract_demo_cmds.py` | 提取全部文本命令（d/p/s/w/r/v） |
| `split_demo_records.py` | 按文本头切分记录，得到每帧二进制 |
| `export_demo_frames.py` | 导出快照体（`00-*.bin`） |

```bash
python tools/demo/extract_demo_cmds.py <demo> --output cmds.json
python tools/demo/export_demo_frames.py <demo> --out frames --top 5
```

### 4.3 快照模板

`templates/`：从 demo 导出的真实快照体（最大 62,474 字节）。

---

## 五、社区可以帮什么

1. **`net_state=7` 的稳定入口**：不依赖 demo，让客户端直接进入"处理 inband 包"状态；
2. **gamestate 崩溃定位**：真实 1649370 的 gamestate 完整字节（我们只有 3426 字节抓包，
   是否缺 configstring？）；
3. **demo 地图名来源**：demo 播放时 `patch_mp_crash_tropical.ff` 的请求路径
   （三个已知加载函数都不命中）；
4. **`mp_cross_fire` 的 demo**：如果你有 1649370 的 cross_fire 对局 demo，
   可以直接用同一套解析器提取快照模板。

---

## 六、免责声明

- 本报告只描述**协议与数据格式**的研究结果；
- 不包含游戏客户端、不包含 fastfile 资源、不提供绕过验证的工具；
- 所有实验均在本地离线环境、使用公开的旧版 demo 文件完成。
