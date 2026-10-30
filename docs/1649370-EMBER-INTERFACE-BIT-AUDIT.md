# Ember 社区库接口与数据位深查（2026-10-30）

## 范围和证据等级

本地 `codol-ember` 的 `HEAD` 与 `origin/main` 经重新 fetch 均为 `f784a77`。本记录优先核对公开库的 1649370 UI、CrossProxy、IIPS/IFS、2697 对局架构和 1604220 工具；再把它们与本机 2697 源码包、当前 1649370 服务端和同 Build 社区字段表逐项对照。来源按四类区分：**A** Ember 公开库中同 Build 的静态规格；**B** Ember 报告提到但不在公开库内的本机 2697 源码/脚本；**C** 当前仓库的 1649370 社区预览字段表；**D** 当前自建连接实测。A/B 的接口不能未经消费验证直接成为 C/D 的游戏 UDP 数据位。

Ember 的 `项目文档-docs/components.md` 明确说大型服务端仍在独立工作区。`PVP资料-pvp/1649370/README.md` 也只串联 UI/玩法主题，未公开完整 PVP 模拟或武器 bitstream。`研究报告-research/offline-implementations/version-2697.md` 的原生快照内部章节标为资料描述，缺对应原生源码和构建证明。其价值主要是**模块职责、状态迁移和验证不变量**。

## 可直接核对的接口

| 接口 | 精确形式和来源 | 能用于当前目标的部分 | 禁止误用 |
|---|---|---|---|
| 2697 房间准备邮箱（B） | 本机 `CODOL2697/fbe7c395/server2697/room_host2697.py:121–154`：`room-request.txt` 五行依次为递增序号、`mp_` 地图名、模式、席位数、bot 数；`room-cancel.txt` 写同代次；成功原子替换 `room-ready.pending` 为 `room-ready.txt`，两行为序号和地图；错误单独写 `room-error.txt` | 为 1649370 房间→对局交接设计代次、取消和原子 ready，防迟到结果误触连接 | 这些文本文件是 2697 本地协调接口，不是 1649370 客户端 wire 消息 |
| 2697 原生游戏进程（B） | 同文件 `:69–112`：核验 `codol_dedrun.exe` 摘要，单局工作目录，`+set g_gametype`、`+map`、回环 UDP `28969`，等地图初始化日志才回 ready | 以 native worker 负责模拟、Python 负责会话；可借鉴资源/进程归属和就绪判据 | 不复制 2697 EXE/脚本到唯一 1649370 运行时；“进程 ready”仍非玩家可操作 |
| 2697 出生与开局（B） | `script-overlay2697/maps/mp/gametypes/war.gsc:43–68` 绑定模式开始、出生点；`_playerlogic.gsc:516–589` 出生时选点，`updateSessionState("playing", "")`，设置血量、`hasSpawned=true` 和 `spawnTime`；`_gamelogic.gsc:414–483` 区分赛前、宽限期和 `game["state"]=="playing"` | 给当前灰屏调查列出**状态问题**：队伍、实际出生、session playing、视觉状态、装备、对局状态分别测量 | 2697 GSC 变量不是 1649370 网络字段，不能照名字往快照填值 |
| 1649370 CrossProxy callback body（A） | `技术规格-specs/1649370/crossproxy/command-frame.md`：CrossProxy→game，callback 参数 `(1, body, 0x2810)`；body `+0/+4/+8` 为 4B 数值/数值/原长度，`+0x0c` payload 容量 `0x2800`，`+0x280c` 4B 清零且语义未知 | 若后续追房间本地桥，可按固定 body 尺寸和已知方向定位真正消费者 | callback 的 `1` 不是 Auth/LSG opcode；这不是对局 UDP 格式；其发送方对负长度不安全，不能当接收端校验策略 |
| 1649370 结果/返回页面（A） | `技术规格-specs/1649370/ui/first-page-routes.json`：输入 `ui_played_mapname`、`eog_is_data_updated`、`is_in_party`、`is_party_member_all_in_room`，房间对象 `mapID/playListID`；`match-select-data.json`：结果 provider 读取 `ui_eog_show` 与地图门槛，返回匹配页事件 `evt_goto_match_select` | 设计正常赛后→结果→房间/大厅的观测点；未来用客户端真实页面与业务持久化验证 | JSON 是打包 AS3 静态重建，不是游戏服务器 `serverCommand`，设置一个 dvar 不等于正常完成对局 |
| 1649370 IIPS/IFS 资源身份（A） | `研究报告-research/1649370/iips-resources/reports/build1649370_ifs2_id_lifecycle_20261016.md`：`root.idTable[pathRow.fileId] == pathRow`；`build1649370_full_open_20261016.md`：file ID 与公开 handle 分离，同 ID 可共享缓存、每个 handle 有独立游标 | 查枪模需分清名称→file ID→归档 owner→Open/Read→FF 登记→武器定义→viewmodel 绑定，避免把“文件存在”当成最终加载 | 这些是有界 DLL/模型分析，不证明当前枪身自动绑定 |

## 真正涉及游戏快照的数据位

Ember 公开库**没有**可直接套用的 1649370 游戏 UDP 字段宽度表。`version-2697.md:141,157–169` 只要求对目标 Build 重建标签、位序、量化表、ACK 基线、失败原子性和实体生命周期；其 J/K 档案命令、`!` 命令环表示属于 2697 资料，不能推广。`工具-tools/ordinary-results1604220/`、`client-state1604220/` 是另一 Build 的纯工具。

当前工作树的**同 Build** `server1649370/player_fields164.py` 来自社区预览、共 246 项（C），`server1649370/wire164.py` 按这些项编码。与本问题直接相关的是：

| 1649370 对象 | 同 Build 字段表 / 当前实测 | 意义和限制 |
|---|---|---|
| `playerState +0x10` | 字段序号 **54**，codec `-102`；社区 `codol_player_projection164.c:199–200` 对逻辑标志只拥有 `0x1800` 掩码，映射源状态的 `0x1000` | r818 服务端置 `0x1000` 后原生选枪重置门控改变；r819/r820 原生命令环主武器变 78。这说明该位是有效线索，**不证明比赛已开局或可射击** |
| `playerState +0x4c` | 字段序号 **57**，正宽度 **11 bit**，当前值武器 78 | HUD/玩家武器存在与原生枪身/开火是不同消费者；r821 武器 78、弹夹 30，903 次开火状态仍为零 |
| `playerState +0x333c` | **不在 246 项快照描述表中**；字段序号 **98** 实际为偏移 `0x258`、1 bit、hint 2 | **撤销** `20261029-r811-native-usercmd-weapon-zero.json` 中“`0x333c, netfield 98`”的字段对应；r812 只读 `ps+0x333c=0` 本身仍有效。社区 `codol_game.c:164–183` 把该地址当服务器侧出生时间门槛线索，但当前尚无把它作为普通 playerState delta 发给客户端的依据；不能盲构造单字段快照 |
| 生命值与装备 | 当前 `wire164.py` 通过 playerState 尾段写 health、装备和弹夹；r821 客户端 `ps+0x1a4=100`、`stats3=1`、clip 30 | 灰屏时生命值非零，不能把灰屏归为死亡；尾段到达也不代表完整出生/视觉状态 |
| 时间 | `gameserver.py:send_due_snapshots()` 每次重复同一快照文件，将 `serverTime` 设为 `72192+index*500` | 计时器会前进，但地图/玩家模拟没有相应前进；需区分显示时间与 `game["state"]` 等真实流程 |

`player_fields164.py` 的表来自本工作区**其他同 Build 社区材料**，不是 Ember 公开库的原创成果。`0x333c` 的更正是核对当前代码得出的，避免沿历史文案误造字段。临时实验文件在 `runs/`，隐私档案在 `resources/1649370/local/`，二者不入库。

## 可落实到本项目的实现顺序

1. **开局判据**：先采同 Build 原生正常对局与 r821 的可比数据，依次看实际发出的可靠命令、clients 队伍、playerState 标志/尾段、视觉状态、出生后第一帧和客户端消费者。Ember 的 2697 GSC 只提供“该测哪些状态”的清单。单独推进 `serverTime`、改 `ui_state` 或写 `ps+0x333c` 均不能作为开局实现。
2. **输入与快照历史**：在现有 `server1649370/client_input.py` 和 `gameserver.py` 中保留每客户端、每 ACK 的命令/快照基线，严格区分未变化的武器 delta 与真实武器零值。发送成功、客户端 ACK、模拟提交三者分别记录；失败时不推进历史。这是 Ember 2697 报告中可迁移的核心不变量，当前 r819 用户命令若只用零基线重解会被误判为武器 0。
3. **原生对局权威**：优先评估本工作区已存在的同 Build 社区 retained engine 的玩家投影、客户端记录、移动/武器状态和脚本；若独立引擎暂不适配，则在现有服中按同一权威状态逐步实现，而不是让静态快照、计时器和人工弹夹变化代替物理/射击。每项用原客户端输入、画面和服务端状态闭环验证。
4. **枪模与赛后**：按 IIPS ID/owner/handle、FF 注册、武器定义及 viewmodel 链定位自动绑定；赛后按 `ui_played_mapname`、结果 provider、房间/大厅路由与档案写回逐层核实。可见枪身和倒计时都只是局部证据。

本次只读分析没有启动 Ember/2697 原生程序、没有复制大型运行时或改写当前游戏服。请以[主参考索引](1649370-CODOL-EMBER-REFERENCE-AUDIT.md)和[本次实机证据](../evidence/experiments/20261030-r818-r821-grey-native-selection.json)区分来源。
