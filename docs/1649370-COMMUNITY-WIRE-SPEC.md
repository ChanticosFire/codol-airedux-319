# 1649370 快照线格式：社区权威规格摘录（2026-10-26）

来源：`他人文件参考/CODOL-Member-Preview-20261026/`（社区成员协作包，含 1649370 原生引擎 worker49 与完整固定源码）。本页只记录**协议事实**（帧布局、段格式、字段表、codec 语义），供 `server1649370` 重新实现使用；不复制其 C 实现，也不把该包当作可直接运行的本机服务。

该包 README 第 20 行给出关键结论：**1649370 恢复镜像路线已有 `mp_crash_tropical / war` 单人真实入图、出生、手臂/M4/准星、前进和转向证据**（显式开发单人策略、70 级测试账号）。他们走的是"真实服务端引擎 + 投影为 1649370 线格式"，不是手写快照。

规格出处（同一目录）：

| 文件 | 内容 |
|---|---|
| `overlay/src/codol/snapshot/codol_snapshot.c` | 帧头与段顺序（`CODOL_WriteSnapshotDeltaNumberHeld164`） |
| `codol/player/codol_playerstate164.c` | 值 codec（`CODOL_WriteValueByDescriptor164`） |
| `codol/snapshot/codol_player_fields164.inc` | playerState 字段表，**246** 项（VA `0xDA8520`） |
| `codol/snapshot/codol_player_snapshot164.c` | ps 段（`CODOL_WritePlayerSnapshot164`） |
| `codol/snapshot/codol_player_tail164.c` | ps 尾部（objective 9 字段 / hud 42 字段） |
| `codol/snapshot/codol_entities164.c` | 实体段（`CODOL_WriteEntitiesHeld164`） |
| `codol/snapshot/codol_entity_fields164.inc` | 实体字段表：**24 种实体类型 × 63 字段** |
| `codol/snapshot/codol_clients164.c` | client 段（`CODOL_WriteClients164`） |
| `codol/snapshot/codol_client_fields164.inc` | client 字段表，87 项（VA `DA8078`） |
| `codol/snapshot/codol_actors164.c` | actor 段 |

## 1. 帧（自 `svc_snapshot` 起，写在 4 字节 ack 之后）

```
u8   svc_snapshot = 0x00
u32  serverTime            (小端)
u8   delta_number          (相对基线序号；首帧为 0)
u8   flags
1bit has_base              (1 = 本帧相对某基线做增量)
--- playerState 段 ---
--- anim commands 段 ---
--- actors 段 ---
--- entities 段 ---
--- clients 段 ---
--- glass 段 ---
u8   0x05                  (svc_EOF)
```

位流 LSB-first：位 `i` 在字节 `i>>3` 的位 `i&7`。

## 2. playerState 段

```
1bit   ps_present = 1
8bit   last_changed + 1        <== 关键：8 位，不是 5 位
for i in 0 .. last_changed:    (只写被选中的字段)
    gap(i - previous)          (4 位分组的距离码)
    value(codec, from, to)
--- ps 尾部（tail，见 §5）---
```

`gap`（ps 用 4 位分组，与 entity 的 3 位分组不同）：

```
if distance == 1: 1bit(1)
else: 1bit(0); --d;
      while d >= 15: bits(15,4); d -= 15
      bits(d,4)
```

**我们现有代码的错**：`tools/build_1649370_snapshot_entity.py` 写的是"1 bit present + 1 bit form + 5 bit count"，这一段的第二部分应为 **8 位 `last+1`**。`server1649370/ps_codec.py` 的 `write_gap` 用的是 4 位/15 形式（正确），但 `write_field` 只覆盖了旧 24 项表里的 codec。

## 3. 值 codec（`0x6701D0`，按字段描述符的 `bits` 分派）

| bits | 线格式 |
|---|---|
| `-98` | `1bit(1)` + 30 bit 绝对值（读端只保留 30 位） |
| `-87` | 16 bit 角度（`RNE(value / 0.0054931640625)`，即 ×182.044…，小端 short） |
| `-100`/`-79` | `2bit(0)` + 16 bit 角度（同上） |
| `-92`/`-91`/`-90` | `1bit(1)` + 16 bit（以 `position_base[axis]` 为中心的 XOR 增量） |
| `-86` | 6 bit 定点缩放 |
| `-102` | `1bit changed` + changed 时 31 bit |
| `-101` | `1bit changed` + changed 时 6 bit |
| `-94` | `1bit(0)` + 11 bit（事件对 payload；tag 仍限 0） |
| `-75` | `1bit`：`1` → 3 bit（delta 1..4 → 值-1）；`0` → 8 bit（`from^to`） |
| `-57` | `1bit` 布尔（取低 8 位非零） |
| `-55` | 4 组分组位域（掩码 `0x0001ffff/0x047e0000/0x08000000/0x03800000`） |
| `0` / `-99` | `1bit(0)`+符号位（`0` 型）或 `1bit(0)`（`-99` 型）；否则 `1bit(1)+1bit(1)+i32(from^to)` |
| `-85` | 颜色：`1bit`（同 RGB 且 alpha 255↔0 互换）否则 `1bit`+同RGB位+（不同则 `1bit`+3 字节）+5 bit alpha |
| `-65` | `bits(to/100, 10)`（回读按 ×100） |
| `-88`/`-97`/`-74`/`-72`/`-70` | 走通用 `WriteDeltaValue` |
| 其它正宽度（`8`、`11` 等） | 走通用 `WriteDeltaValue`（`0` 与 `< -32` / `> 32` 不支持） |

**待补**：`CODOL_WriteDeltaValue` 的实现不在 overlay 目录（在引擎核心 msg 模块），本轮未读；正宽度 codec 的确切位形（gate 位 + 宽度位，LSB-first）沿用我们 `ps_codec.py` 已验证的 `1 gate + N bits` 形式，仍需在该处核对。

## 4. 实体段

```
每个实体:
    index_code(number, last_number)
    payload:
        1bit present = 0
        1bit changed = 1
        1bit origin_baseline = 0     (用逻辑 held origin 做基线)
        6bit last                    (最高已选字段索引)
        gap(1)                        (3 位分组的距离码，与 ps 的 4 位不同)
        value(字段 0)                 (实体类型)
        for i in 1..last:
            if selected: gap(i - previous); value(字段 i)
        然后 hint==2 的强制字段按同序补写
段结束: index_code(SENTINEL, last)     (哨兵索引)
```

`index_code`：

```
d = number - last_number
if d == 1: 1bit(1)
else: 1bit(0); 1bit(d >= 512); bits(d < 512 ? d : number, d < 512 ? 9 : 11)
```

实体字段表是 **24 种类型 × 63 字段**（`codol_entity_fields164.inc`，36 KB）。我们目前完全没有实体段编码器。

## 5. ps 尾部（`codol_player_tail164.c`）

ps 段字段循环之后紧跟一个 tail，由 `known_sections` 位掩码控制的多个 record 组成：

- objective record：9 个字段（`{4,0}`、`{8,0}`、`{12,0}`、`{32,12}`、`{16,11}`、`{20,4}`、`{36,-97}`、`{28,4}`、`{40,-57}`）
- hud record：42 个字段（`-85`/-91/-92/`4`/`10`/`11`/`-90`/`0`/`-97`/`8`/`16`/`25`/`4`/`-86`/`-99`/`32`/`-65` 等）

record 通用形：

```
[outer] 1bit(有变化)            (仅 outer record)
lc_width bit (last / last+1)
for i in 0..last: 有变化则 gaps(i-previous, gap_width) + value(...)
```

## 6. 空段的最短形式

| 段 | 空段字节 |
|---|---|
| anim commands | `1bit(0)` |
| actors | `1bit(0)` |
| entities | `index_code(SENTINEL, -1)`（哨兵；`CODOL_ENTITY_SENTINEL` 常量值本轮未取到，需从 `codol_entities164.h` 或引擎常量核对） |
| clients | `1bit(0)` |
| glass | 见 `CODOL_WriteGlass`（空列表形式本轮未读） |

## 7. playerState 字段表（246 项，索引 → offset/codec）

整表已转录为本仓库的 `server1649370/player_fields164.py`（246 项，保持线序，**不可排序**）。交叉验证：该表第 57 项 = `(offset 0x004C, codec 11, hint 0, words 1)`，与 r528 从当前客户端二进制 `0xDA8520 + 57*12` 实测的 `{offset=76, codec=11, hint=0}` **完全一致**——两条独立来源互为佐证。关键索引：

| 索引 | offset | codec | 说明 |
|---|---|---|---|
| 57 | `0x004C` | 11 | **ps.weapon**（与历史 `0xDA8520 + 57*12` 一致） |
| 83 | `0x0004` | 8 | 我们实测的 snapshot body `offset 0x43`；值 5 → 观战者 HUD，值 0 → 自由相机 |
| 20 | `0x000C` | 32 | |
| 12 | `0x002C` | 8 | |
| 13 | `0x0040` | -88 | |
| 92 | `0x0174` | 32 | |

> `offset 0x0043` 这个"文件偏移"与字段表 `offset 0x0004` 只是巧合相近；我们的实测字节能改视角模式，但它的**语义还没坐实**（对照 §7 的 8 位 codec 与 demo 体里 last=216 的字段流）。下一轮应先按本规格重建 ps 段，而不是继续改那个字节。

## 8. 与现有实现的差异清单（下一轮动手顺序）

1. `tools/build_1649370_snapshot_entity.py`：ps 段头 5 bit → **8 bit `last+1`**。
2. `server1649370/ps_codec.py`：字段表从旧 24 项换成 246 项；补 `-98/-92/-91/-90/-86/-102/-101/-75/-55/-85/-65` 分支。
3. 新增实体段编码器（`index_code` + 三段位 payload + 3 位 gap + 24 类型字段表）。
4. 新增 clients 段（空 = 1 bit）与 glass 段（空形式待读）。
5. 用"最小自洽帧"实测：`has_base=0`、ps 只写若干字段（clientNum、pm_type、weapon、origin、viewangles）、entities 空、其余空段 → 客户端应保持地图且不崩；再加实体 id = 本地 clientNum。

## 9. 不可越过的边界

- 社区包的 `native-engine/codol_dedrun.exe` 是可运行的原生引擎，但需要其启动器/账号/资源绑定；本轮**没有**运行它，也没有把它的二进制或源码复制进本仓库。
- 他们的 README 明确"仍未覆盖完整多人对战、跨版本混配、全地图/PVP/PVE、长时间对局及结算"，"射击、换弹、伤害未验收"。所以即使我们复现"出生 + 手臂/M4/准星 + 前进转向"，也不等于验收第 5 项完成（还需真实射击与命中/弹药反馈）。
- 该包为 AGPL-3.0-or-later；本仓库只按协议事实重新实现，不复制其实现代码。
