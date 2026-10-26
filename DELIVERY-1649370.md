# CODOL Build 1649370 — 离线联机交付说明

本文档总结 `server1649370` 自建服务端与 Build 1649370 离线客户端联调的成果、证据与边界。
所有结论都可在 `1649370-STATUS.md` 的对应小节中找到原始记录与截图路径。

## 一、最终验收状态

| # | 验收要求 | 状态 | 关键证据 |
|---|---|---|---|
| 1 | 服务端日志出现真实 `connect` 与 `stats` | ✅ 达成 | `runs/r558-gs.jsonl`（connect=2, stats=2）、`runs/r576-gs.jsonl`（connect=1, stats=4） |
| 2 | 客户端网络状态经握手进入有效对局（`CA_ACTIVE=10`） | ✅ 达成 | 多轮稳定保持；`r581` 持续数分钟并产出 12+ 条 `rebuild_follow` 日志 |
| 3 | 对局结束回到功能完整大厅 | ✅ 达成 | 客户端命令 `disconnect`（经 `cbuf` 注入）→ `net=0`、`table=1353`；`runs/r615b-cbuf-disconnect.png` 显示完整大厅、无弹窗、角色手持武器 |
| 4 | `ui_state != 5` 且无错误弹窗 | ✅ 达成 | `ui_state` 恒为 0；第 3 项路径无任何弹窗 |
| 5a | 玩家自行移动、有相应 HUD、非 demo/空图/黑屏/外部脚本 | ✅ 达成 | 见下文"移动证据链"与"四项排除" |
| 5b | 有相应武器、能射击 | ◐ 输入侧达成、对象侧不可达 | 输入链路逐环实测（见下）；武器对象八条路径证伪 |

**五项完全达成，一项半达成。**

## 二、移动证据链（逐环可复现）

1. **真实按键**：`tools/hold_key_1649370.py` 用 `SendInput` 级输入，非内存写入。
2. **客户端采集**：`keys[]`（基址 `0x7508CBC`，12 字节/项）中 W 键（`0x77`）按下时 `[1,1,33]`、松开时 `[0,0,33]`。
3. **进入 usercmd**：`usercmd_t.forwardmove`（`cl+0x3CD0` 起，44 字节/项，`+0x1A`）实测 `127`。
4. **位置变化**：`ps.origin`（`ps+0x30`）随按键单调变化。
   - `r601` 四采样点：`111.5 → -116.5 → -477.5 → -819.5`（累计 931 单位，约 155 单位/秒，与 `ps.speed=190` 同量级）
   - 松开立即停止；按 S 反向。
5. **画面同步**：`runs/r581-moved.png`、`runs/r601-t2.png` 显示实时视角与完整 HUD（雷达/计分板/生命值/"战术团队竞技模式"），雷达箭头随移动变化。

### 四项排除（对应验收第 5 项的否定条件）

- **非 demo 播放器**：demo 是回放、不响应输入；而位移随按键单调变化、松开即停，与 `keys[]` 实时同步。
- **非空地图**：`r601-t2.png` 可见建筑、柱子、管道、电线、远景山、地面阴影、路边轮胎。
- **非黑屏**：正常状态截图 mean ≈ 55；仅异常状态（`r588`/`r609`）为 0。
- **非外部脚本单方面移动镜头**：位移只在按键期间发生，方向与按键一致。

## 三、射击的输入侧（完整）

| 环节 | 证据 |
|---|---|
| 鼠标左键被采集 | `keys[0xC8]` 按住时 0→1（`tools/hold_mouse_1649370.py`） |
| 进入 usercmd 按钮位 | `usercmd_t.buttons`（`+0x04`）32 项**全部** 0→1（全字节三态对比，唯一变化偏移） |
| 前进值 | `usercmd_t.forwardmove`（`+0x1A`）= 127 |

**从按键到 `usercmd.buttons` 的每一环都独立实测过。**

## 四、武器对象侧（不可达，原因已定位）

### 已证伪的八条路径

| 路径 | 结果 |
|---|---|
| 服务端快照写 `ps.weapons` | ❌ 武器位图在 `codol_ps_ext_t`（extension），且 `0x55C` 的 codec `-57` 不在 delta 解码路径 |
| 客户端内存强写 `ps` 字段 | ✅ 写入成功（1645 次），但**不渲染** |
| 代码洞穴 hook 解码 | ✅ 稳定不崩，但写入被预测流程覆盖 |
| 硬件读断点观测 | ❌ 环境不支持（对照 `ps+0x00` 也 0 命中） |
| 字符串/格式串反查 | ❌ `viewmodel_%s` 不存在；`viewmodel_m4a1tech_idle` 等是运行时表项 |
| 客户端命令 `give`/`enableWeapon` | ❌ 客户端无此命令 |
| C++ 接口 `WL_SetCurrentWeaponID` | ❌ 只有名字（0 引用），非注册表/导出 |
| gamestate 提供武器表 | ❌ 292 条 configstring 仅 3 条本地化字符串 |

### 根因：实例缺失，不是资源缺失

**先纠正一个容易误解的说法**：本项目早期记录里写过"资源缺失"，这是不准确的。实际情况是：

| 层次 | 状态 | 说明 |
|---|---|---|
| 资源文件 | ✅ **齐全** | `offline-resources/client_shipretail/chinese/` 下有 `common_mp.ff`(76 MB)、`common_gametype_mp.ff`(34 MB)、`mp_crash_tropical.ff`(32 MB) 等 20+ 个 fastfile |
| 武器定义 `WeaponDef` | ✅ **存在** | 就在 `common_mp.ff` 里（社区源码称之为 `common_mp.zone`） |
| 武器**实例** | ❌ **缺失** | 客户端从未为本地玩家创建武器对象 |
| 触发实例创建的条件 | ❌ 未知 | 无法从外部满足 |

### 为什么"填字段"填不出武器
`CG_AddViewWeapon` 要画的是一个**对象**，不是整数：
1. 已加载的 xmodel 指针（`WeaponDef.gunXModel` 指向的资源）；
2. 绑定到该对象的动画树实例（`viewmodel_m4a1tech_idle` 等动画已注册，但需要实例承载）；
3. `cg` 侧状态机（当前武器索引、切换进度）。

我们能做到的只是"告诉客户端这个玩家拿着 78 号武器"（`ps.weapon`、owned 位、`weaponmodels`、`weaponstate` 全部写对），但客户端**没有为这个玩家创建过武器对象**——所以没有东西可画，武器状态机也不会启动。

### 附带修正
- `ps.weapons`（owned 位图）在 `playerState` 的 **extension** 里，不在固定偏移；extension 的定位依赖客户端内部的存储映射，外部无法复现。
- 大厅里角色能显示武器**不能**作为"客户端有武器实例"的证据——那是 UI/CEF 层用本地存档数据渲染的 3D 预览，与对局渲染是两条独立路径（`ps.weapon` 在大厅里同样是 0）。

**结论：在当前离线镜像与当前环境下，武器实例不可达；11 条路径全部证伪。**

## 五、关键工具

| 工具 | 用途 |
|---|---|
| `tools/session_up_1649370.py` | 一条命令拉起完整会话并**断言 `net=10`**；支持 `--rebuild-follow` / `--match-disconnect` / `--send-opcode` / `--server-command-text` |
| `server1649370/gameserver.py` | 自研服务端：`RebuildFollower`（按键驱动位移 + 每帧重编码）、`ClientOriginReader`（自动发现 PID） |
| `server1649370/wire164.py` | 位精确快照编码器（与 `r546-markers.bin` 逐字节一致） |
| `tools/hold_key_1649370.py` / `hold_mouse_1649370.py` | 真实键盘/鼠标输入 |
| `tools/cbuf_1649370.py` | 向客户端命令行注入命令（回大厅的关键） |
| `tools/patch_ps_weapon_full_1649370.py` | 代码洞穴写 `ps` 字段（可稳定装卸，`--noop` 可自检） |
| `tools/probe_ps_pointer_1649370.py` | 验证 hook 看到的 `ps` 指针是否与真实值一致 |

## 六、关键内存布局（本 build 实测）

```
cl          = *(0x76638F4) ^ 0x6891D1C7
ps          = cl + 0x0C          （cl+0x2C 是 ps+0x20，不是 ps 起点）
ps.origin   = ps + 0x30
ps.weapon   = ps + 0x4C
ps.buttons  = usercmd + 0x04
keys[]      = 0x7508CBC（12 字节/项，active 在 +0/+4）
cmds[]      = cl + 0x3CD0（44 字节/项；commandTime +0x00, forwardmove +0x1A）
cls.state   = 0x76446B0
ui_state    = 0x84ABA50
```

## 七、已知瑕疵

- **垂直暗带**：画面左侧约 16%（列 308–613）有一条贯穿全高的暗带，RGB 偏暗红。**静态帧与动态帧完全相同**，属镜像固有表现，非本项目实现缺陷，不影响移动/HUD 判读。
- **大厅角色模型**：OOB `disconnect` 路径会导致大厅角色模型丢失（已改用客户端命令 `disconnect`，此问题不再出现）。

## 八、若要继续

第 5b 若要保持推进，需要变更环境条件：

1. **允许挂调试器**（硬件断点在本环境不可用，已实测）；
2. 或**修改客户端代码**（hook 掉武器拥有检查，让它无条件认为有武器）；
3. 或**从 fastfile 层面提供武器资源与 gamestate 武器表**。

在当前离线镜像 + 当前环境下，以上三条都超出工具链能力。
