# CODOL Build 1649370 本地 bot 对战：多 agent 技术路线

> **2026-10-22 新门槛**：人工 LSG 到 token；私有 `dwauth.ini` 已使配置端口读为 28969，但认证来源和登录状态仍是 0。社区 EXE 的静态写入点已定位：`0x7F28F0 → 0x7F2B90` 创建 Auth 来源，后续 `0x801A00`；下一步实测状态机触发与游戏自主 `/auth/`，随后验证 LSG 的首个 `0x85`。详见 [1649370-REASSESSMENT-20261022.md](1649370-REASSESSMENT-20261022.md)。

> **2026-10-22 边界更新**：用户已允许驱动和更高权限跟踪。旧文中的“不加载驱动”要求已被新指令取代；但不得中断本机网络/工作流，任何网络过滤仍限可回退的进程内临时 WFP 动态会话。当前优先实验和判定门槛见 [1649370-REASSESSMENT-20261022.md](1649370-REASSESSMENT-20261022.md)。

更新：2026-10-21（Asia/Shanghai）  
主线目录：`E:\GAME\COD\codol-airedux\319`  
社区只读参考：`E:\GAME\COD\1649370`  
原始客户端只读来源：`E:\GAME\COD\Original Client`  
历史版本：1604220 仅见 `ARCHIVE-1604220.md`，保留成果，不再作为当前实现基底。

## 1. 目标、边界与完成判据

目标是**玩家与至少一名由本地 AI 驱动的 bot 在真实地图中对战，并能正常结束或退出、返回大厅**。验收需要同时证明：地图已经装载、玩家能移动和交互、bot 能自主行动与交战、对局可结束、返回大厅后能再次建立房间。大厅画面、房间画面、黑屏、`bots.cfg` 字符串、单独出现的 bot 模型都不能代替上述证明。

所有实现留在 `319` 的工具、私有资源副本、包装层和独立运行目录。社区源码、社区存档、原始客户端文件、已校验的基底 EXE 均不修改。不得加载驱动；网络约束仅使用当前已验证的**进程内临时 WFP 动态会话**，恢复游戏主线程前核对守卫 ready（四个过滤器、目标进程身份、动态会话、单进程 job），每次结束核对 `guard_cleanup.closed=true`、`engine_close_status=0` 和无残留进程；异常时使用 `tools/net_rollback.ps1` 一键回退。运行时资源只可复制到独立 stage，不能写入共享缓存的目录联接或社区资源库。继续使用 `319/data/v1649370/` 私有 SQLite 存档，不覆盖用户当前昵称及装备。

## 2. 已证事实与当前阻断

| 项 | 状态与证据 | 不可据此推断 |
|---|---|---|
| 完整 host、大厅、本地房间 | `tools/launch_1649370.py --full --local-profile` 已运行；大厅和房间截图见 `1649370-STATUS.md` 顶部 | 房间即对局 |
| 私有档案 | 昵称“南韩超人朴玄俊”在私有库和原生大厅均已核对 | 可以改社区源库 |
| 地图资源 | `tools/extract_signed_ifs_fastfiles_1649370.py` 已从原 IFS 提取 `mp_strike_sh`、`mp_backlot_sh` 各三个 FF，发行签名、哈希链、zone 通过 | FF 完整即客户端已装载地图 |
| 直接 `devmap` | 启动参数仍进大厅；命令队列两次黑屏，无可信地图载入证据；三次探针后已换向 | 黑屏即地图加载成功 |
| 房间开局静态入口 | `room.startgame` 回调 `0x6398A0` → 当前房间 vtable `+0x3C`（样本 `0x62F840`）；`0x639890` 是 `room.leave` → vtable `+0x38`；`mmstart sv_resetServer; ...; map %s` 格式串；`StartMatch` 等 GFx 名称存在 | 字符串、直接引用即运行时可达；旧记录把 `0x639890` 当 startgame 是错的 |
| “准备”按钮 | 两轮点击仅见 UI 状态变化；选定原生断点未命中。后续审计确认四个候选断点至少在导航资源加载时仍有效；ABC 静态解析找到 `LobbyController.onChangeReadyStateHandle` → `CFunctionContainer.SetReadyState(1)`，默认函数体为空桩 | 静态调用即实机已执行；默认空桩即运行时未重绑。须测按钮路径和槽位状态 |
| bot 线索 | `development_mp.ff` 内有 `bots.cfg`；镜像含 `botsAddAll` 直接引用 | bot 命令已注册、AI 能运行 |

最新依据：`evidence/experiments/20261021-1649370-map-probes.json`、`20261021-1649370-room-start-refs.json`、`20261021-1649370-room-ui-probes.json`。`1649370-STATUS.md` 较早的 §2.4、§2.5、§5 是历史现场；其中 `fileSysCheck.cfg` 的待办已被顶部纠偏和实机大厅结果取代。不要重做此项。

## 3. 多 agent 分工与依赖

协调 agent 维护本路线、`1649370-STATUS.md`、`PROJECT_STATUS.md`、实验索引和集成分支；拥有 `tools/launch_1649370.py` 的最终合并权。其他 agent 对共享启动包装层提交小补丁或明确的改动提案，由协调 agent 合并。静态研究可并行；**同一时刻只能有一个 agent 启动 1649370 客户端、占用动态 WFP 守卫或操作游戏窗口**。每个运行使用唯一 `--name`，不得重用其他 agent 的 stage。各 agent 不直接改同一份私有 SQLite；运行前备份并记录源 hash，运行后检查完整性、昵称与装备。

| 工作流 | 负责人范围与可并行产物 | 交付接口 |
|---|---|---|
| A：GFx/房间按钮 | 解开对应 UI 资源，只读定位“准备”“开始”按钮到原生入口的调用；审计断点在社区适配器安装后是否被覆盖；记录按钮前后 native 房间/成员状态 | `tools/room_ui_probe_*.py`、地址/原始字节/调用约定、单次运行证据 JSON |
| B：房间开局与状态机 | 沿 `room.startgame` 回调 `0x6398A0` 的 vtable `+0x3C` 找到运行时目标、房主/人数/ready 守卫、`mmstart` 命令生成与消费；将最小本地会话数据供应限定在包装层 | 已验证的状态转换图、失败守卫及最小补丁方案；不伪造“进入地图”结果 |
| C：地图资源与装载 | 建立所选房间地图名 ↔ FF/IWI/loose 依赖清单；从同版本原 IFS 验签提取、按 hash 复制到独立 stage；观察成功/失败文件访问及地图加载阶段 | 可重放的资源清单、指纹、装载证据和明确缺件列表 |
| D：bot 与脚本 | 在尚未开图时并行做静态 ABI 研究：`botsAddAll` 两处引用、`bots.cfg`、脚本资产、实体分配和导航依赖；在 G2 后才做实机召唤与 AI 验证 | bot 初始化、生成、行为、伤害的独立证据；失败时说明是命令、脚本、导航还是实体层 |
| E：运行安全与验收 | 维护独立运行证据、截图/事件比对、私有档案校验、WFP 回退和无残留检查；对每个门槛做冷启动复测 | 每轮验收摘要与回退记录；不得仅凭 host `main_menu_verified` 字段判大厅失败 |

如实际并行 agent 少于五个，优先 A+B、C、D、E；协调 agent 可兼任 E。A 与 B 先共享静态地址和状态定义，再由唯一的运行持有者做房间探针。C 可独立准备资源，D 可独立解析 bot，均不应自行同时启动游戏。

## 4. 关键路径与实验设计

### G0：冻结可复现基线（已完成，需守护）

运行入口为 `tools/launch_1649370.py --full --local-profile`。每轮先检查精确 EXE、原 IFS、地图 FF 指纹与私有存档；记录 `result.json` 中 guard ready/cleanup、stop reason、输入镜像 hash。保留已验证的大厅、建房、离房路径作为回归。若新补丁破坏 G0，先回退本轮补丁，不向后推进。

### G1：证明“准备/开始”实际进到哪条原生链

1. A 以已解析的 `LobbyController.onChangeReadyStateHandle` 和 `CFunctionContainer.SetReadyState` 为锚点，补齐按钮事件 → ActionScript 调用的运行证据，并验证类级 Function 槽位是否被引擎重绑。区分请求与 native→UI 命名调用；每条边注明证据类型。
2. B 选择**函数入口或已核实执行的指令**做一次性断点，启动后读取断点原始字节与 `0xCC` 回读；社区适配器装载后再复核。未命中时先排除断点被覆盖或走到别的实现，不能把零命中当作逻辑不存在。
3. 运行持有者在同一固定模式、固定地图、1/12 房间中依次观察：建房、点击“准备”、取消准备、尝试房主开始、离房。每步记录线程、返回地址、参数、房间指针、vtable 目标、成员身份/ready 状态、命令队列长度；敏感指针只进本地证据文件。
4. **通过门槛**：至少一次可重复地观测到点击动作进入某个已辨认的 native 入口，且解释它为何停在开局之前。若按钮只在 SWF 内改变状态，交付 SWF 到 native 的断点位置和缺失的消息/服务边界。

### G2：从房间启动真实地图

1. 沿 `room.startgame` 回调 `0x6398A0` 的 vtable `+0x3C` 测量房间对象动态目标，识别房主、人数、ready、模式和地图参数守卫。对 `mmstart sv_resetServer; ...; map %s` 的组装点（`0x632462` 一带）与命令消费者做前后状态快照。优先让原房间路径自然发出命令，再使用仅在本地房间有效的包装层补齐缺失状态/回调。注意：`0x639890` 是 `room.leave`，不是 startgame；且命令/函数必须在游戏主线程执行，跨线程调用会被引擎拒绝。包装层 `--room-command` 已能在房间有效后暂停主线程、向原 Cbuf 追加一条命令并恢复；已用它到达 `0x6398A0`/`0x62F840`，并确认 `0x631E90`（mmstart 构造）因本地 playlist/gametype 为 -1 返回 NULL。`devmap`/`map` 不是该客户端的注册命令，已实测无效果，不要再把它们当作入口。**2026-10-21 换向**：`0x62FAF4` 捕获到 `room.startgame` 实际排入 Cbuf 的文本是 ` sv_resetServer; ... map <map>; ...`，补 `mmstart` 前缀后仍黑屏；客户端没有独立的 `mmstart` 命令注册，该文本是发给匹配服务端的请求，客户端不含 listen server。**PVE/训练也已实测依赖匹配服务**（靶场弹“服务器繁忙中，请稍候重试”），离线 UI 没有本地地图入口。不要再在 Cbuf/mmstart 前缀或 PVE 点击上重复实验；下一分支是用 loopback 服务捕获/回答匹配请求，或复用/适配 `319/server319`，并同时评估客户端是否含可独立调用的地图启动函数。**2026-10-21 服务端审计**：1649370 镜像没有 `SV_SpawnServer`/`SV_Startup`/`codol_zoneType`/`sv_maxclients` 等服务端串，只有客户端 `loadingnewmap`；社区源码也没有 online/server 模块。工作区仅有 2.6.9.7 的 `codol_dedrun.exe`，协议为 `IW4OL2.6.9.7`，1649370 无匹配标记，不能直接配对。当前 G2 阻断是缺少 1649370 服务端/协议实现；下一步先检索 1649370 服务端资料，再做 wire capture 和最小适配。**2026-10-21 loopback 探针**：2.6.9.7 `codol_dedrun.exe` 已在私有目录加载 `mp_cross_fire`（Bot waypoint 444 节点，监听 `127.0.0.1:28969`）；私有 `client_loopback_guard.exe` 已复制到 `319/tools/ref/`，包装层 `--loopback-guard` 以临时 WFP 动态会话只放行 UDP `127.0.0.1:28969`，ready 校验通过。1649370 的 `connect` 不是注册 Cbuf 命令，注入后无 UDP/服务端日志。不要再注入 `connect`；下一步逆向 1649370 内部连接入口（`0x604260`/`0x605920` 一带）或走在线 lobby 路径，才能测跨版本 wire 兼容。**2026-10-21 CL_MapLoading 探针**：在 2697 服务端 + loopback 守卫下注入 `room.startgame`，`0x5BE730`（CL_MapLoading 候选）零命中、服务端无连接、仍黑屏；房间路径只发匹配请求。下一步在游戏主线程用代码 cave 直接调用 `0x5BE730`（保存寄存器→call→恢复→ret，返回原 EIP），不要用远程线程；调用前需确认 `localhost` 解析端口与 `net_port` 设置。**2026-10-21 主线程 cave 结果**：`--main-call` 已实现并成功 armed（修复 rel32 无符号打包和 WOW64 上下文），但 `0x5BE730` 调用后无连接/无地图，进程仍响应。下一步必须先在同一调用上设 `0x5BE730` 真实断点，区分 cave 未执行与函数无效果；不要盲调第二个函数。**2026-10-21 断点证明**：真实断点在 `0x5BE730` 命中，cave 确实执行；但该函数先扫描 `0x76446A1`–`0x76446C1` 的 0x20 字节点表，全空即返回，不会走 `"localhost"` 连接分支。下一步审计该表并填最小 localhost 条目，或定位真正的 CL_MapLoading/CL_Connect 入口；不要在没有表状态的情况下重复盲调。**2026-10-21 换向**：预写 `0x76446A1`/`0xC7AF590` 为 localhost 后再调用，断点命中、连接状态置 4、前端状态 5，但服务器地址结构仍全 0，28969/28960 都无 UDP 包。直接调用连续三轮无连接，停止该方向；改走在线 lobby：用 1649370 v0.0.7 服务端/启动器进大厅，返回一个本地服务器条目，让客户端自己的连接代码填地址并连接。**2026-10-21 在线 lobby 评估**：v0.0.7 服务端可启动（health ok，3074/3075/17500/8000/8080），但其客户端启动器要求原版 `Base.dll`/反作弊栈，与“不加载驱动”冲突，且服务端无房间/对局应答。该路径在当前边界内不可用。下一步需用户提供 1649370 专用服务器/协议资料，或继续离线客户端的地址/连接适配并验证 2.6.9.7 wire 兼容。**2026-10-21 netadr 结果**：从 `NET_AdrToString` 确认 1649370 `netadr_t` 为 `+0x14` 类型、`+0x18` IPv4、`+0x1C` 网络序端口；写入 `type=4, 127.0.0.1, 28960` 后调用 `0x5C05F0`，客户端仍报 `EXE_HOSTUNREACH`，服务端无 getchallenge、无 28960 UDP。地址格式问题已排除；下一步审计 `NET_SendPacket`/`NET_Init` 与 connection sock，确认离线构建是否初始化客户端网络，或向用户索取 1649370 服务端/协议抓包。**2026-10-21 发送路径定位**：`EXE_HOSTUNREACH` 来自 `WSAEHOSTUNREACH`（映射表 `0xBB1594` 的 10065→4），调用链 `0x5C0EF3 → 0x675260 → 0x6751F0 → 0x77FB80 → 0x622040`；type=2 只走进程内 loopback，type=4 走 UDP 并在 socket/路由层失败。下一步必须审计 `0x622040` 与 `NET_Init`/socket 创建，确认离线客户端是否根本没有建立 UDP socket；若网络栈被禁用，仅提供 1649370 服务端也不够。**2026-10-21 传输通道发现**：`0x622040` 从固定表 `0xE3F4DB0`（条目 `0x18`，有效索引 `<0x9D`）取通道对象；连接路径传入 `0x9D=157`，跳过查表并返回 `-7`，最终成为 `EXE_HOSTUNREACH`。下一步定位 `0x7F5xxx` 通道创建逻辑并让连接路径使用有效索引；若该表在离线构建中从不初始化，需要同时恢复客户端传输层。
2. C 将 UI 所选地图固定为同版本已验签的一套资源；建立逻辑路径、IFS 包、原始 hash、FF/zone hash、stage 目标路径。`OfflineResourceSupplier` 目前只处理 `main/images/*.iwi`；非 IWI 文件走明确的只读提取和私有 stage 复制。缺件用文件访问跟踪和引擎报错定位，不按名字猜测。
3. 运行时区分：命令未提交、命令被拒、资源缺失、引擎开始装载但失败、世界已生成。不要用一张黑屏区分这些状态；至少采用**两个独立信号**，例如引擎阶段/客户端状态的已校验快照加真实场景与可控角色画面。
4. **通过门槛**：从本地房间进入真实地图，玩家能够移动、开火或操作，且运行期无外部服务依赖；录制关键事件、截图和一段可重放操作序列。此时才把 G2 标为完成。

### G3：启用本地 AI bot

1. D 验证 `botsAddAll`、bot dvar 与相关脚本是否注册、何时可调用、需要哪些游戏模式/导航资产；区分“命令存在”与“spawn 成功”。优先利用发行包已有 AI，避免另造无关的敌人模型。
2. 在 G2 的最小地图/模式下先生成 1 个 bot，检查实体是否进入正确队伍、能自主寻路/选择目标、对玩家造成伤害且能被玩家击中；然后再扩到多 bot。记录 bot 数、队伍、实体状态、坐标随时间变化、伤害/击杀事件和画面。
3. 若内置 bot 入口不可达，按证据定位到脚本加载、导航、实体分配或模式限制，再做最小包装层适配。每种替代实现仍须满足“自主 AI 对手”，脚本固定靶或仅同步展示不算完成。
4. **通过门槛**：一次完整可玩的玩家对 bot 对局，并有 bot 行为和交战的双重证据。

### G4：结束、回大厅、重复性

分别验证正常赛终、玩家主动退出和异常/超时终止：房间与地图状态释放、UI 回主大厅、私有档案可保存、动态守卫和子进程清理。至少两次全新冷启动完成 G2→G3→回大厅，其中一次再建房；任何一次残留 WFP 过滤器、守卫或客户端都使本门槛失败。保留 `tools/net_rollback.ps1` 的可用性与运行记录。

## 5. 协同协议、证据与提交

每个 agent 开始前读取本路线、`1649370-STATUS.md` 顶部、相关实验 JSON、目标源文件与当前 `git status`。静态工作使用独立文件名前缀和分支/工作树；不在同一工作树同时编辑包装层、状态文档或私有档案。协调 agent 为唯一运行持有者分配会话名；运行前声明具体假设与单一判定点，运行后释放持有权并记录清理结果。脚本应默认只读、幂等、拒绝覆盖非同内容文件，资源输出置于 git 忽略的 `319/runs/`；证据摘要置于 `319/evidence/experiments/`。

每轮交付最少包含：

1. 假设、输入指纹、改动文件、执行命令、会话名和预期观测；
2. 实际运行证据（`result.json`/`events.jsonl` 路径、必要截图、关键事件和反例），明确区分静态线索、运行观测与已通过门槛；
3. 守卫 ready/cleanup、原件与社区源文件 hash 不变、私有 SQLite 完整性与昵称保留；
4. 阻断分类、同类连续轮数、下一次实验或换向方案；
5. 更新 `1649370-STATUS.md` 与 `PROJECT_STATUS.md`，由协调 agent 合并并**本地 git 提交**，提交后工作树干净。

同一阻断的“一轮”定义为一个有预先判定标准、已运行或已完成静态验证、已记录并提交的实验。连续三轮若仍无新的可定位证据或门槛推进，协调 agent 必须停做相同试法，写明失败原因并换到另一入口。既有三次直接 `devmap` 探针已触发换向，当前优先级是 G1 房间真实调用链；只有 G1/G2 证据要求时才回到直接地图命令。

## 6. 近期任务队列与集成顺序

| 顺序 | 任务 | 负责人 | 完成输出 |
|---|---|---|---|
| 1 | 审计一次性断点是否在社区适配器补丁后仍保留，并从 UI 资源定位“准备”按钮的 ActionScript/native 入口 | A+B | 有效断点、调用约定、按钮前后状态；消除“零命中”的歧义 |
| 2 | 静态确定 `room.startgame` 回调 `0x6398A0` 的 vtable `+0x3C` 目标、`mmstart` 格式参数与房主/人数守卫 | B | 可在单次房间会话中验证的状态和地址清单 |
| 3 | 固定一个房间地图并补齐同版本 FF/IWI/loose 依赖，审计 stage 是否碰到共享目录联接 | C | 完整指纹清单及只向私有 stage 复制的脚本 |
| 4 | 形成 bot 入口/导航/脚本依赖表，不启动游戏 | D | G2 一通过即可执行的最小 bot 实验 |
| 5 | 集成 G1，再按 G2→G3→G4 顺序推进；每门槛通过后回归 G0 和网络守卫 | 协调 agent+E | 逐门槛证据、文档更新和本地提交 |

路线的当前完成点是 **G0 已验证、G1 正在定位、G2–G4 未通过**。任何 agent 不得以静态线索或 UI 外观提前改变此状态。

## 2026-10-21 G2 传输建链实测（本轮）

实现 `--transport-connect`：主线程 cave 调 `0x621E50(adr,buf,len)` 建通道，再 `0x5C05F0` 发 getchallenge。实测 `0x621E50` 返回 -7，`[biz+0x18]=0`（`vt+0x20=0x8834A0` 读该字段），通道仍 0x9D，2697 服务端无包。`0xBB4E60` 清 0，`0xBB2C40` 在 `0xBB2D20` 置 1 但需先完成 `0xBB6FB0` 等子初始化；直接 poke 闸门会让客户端 `unhandled_exception`。下一步：用 `0xBAD810` 的参数调用 `0xBB2C40`，或走进程内 loopback 环桥（`0x6750A0` 写、`0x674F30`/`0x675140` 读）。证据 `evidence/experiments/20261021-1649370-transport-gate-crash.json`。

## 2026-10-21 G2 环桥探针（本轮）

`--ring-probe`：adr type=2/28969/channel 0x9D、state=4，主线程调 `0x5C05F0`；环 A 光标 0→0，`0x6750A0` 断点零命中。结论：`0x5C05F0` 在构造 getchallenge 前早退，缺连接字段/计时器状态，不是环布局问题。下一步在 `0x5C05F0` 跟踪早退分支，或用 `0xBAD810` 参数调 `0xBB2C40` 完成真实初始化。证据 `evidence/experiments/20261021-1649370-ring-probe.json`。

## 2026-10-21 G2 getchallenge 捕获（本轮）

state 4 是 connect 分支，state 3 才是 getchallenge 分支（`0x5C0F3C` 跳表）。state=3 后在 `0x6750A0` 断点命中，栈上得到 `getchallenge 0 "a731af49a6a2c7e2"`（38B），arg1=0/ring A、arg3=2、arg5=28969、arg8=0x9D。文本握手可达，无需传输通道。环 A 光标 `0x788680C` 未观察到递增；下一步用代码 cave 持久 hook `0x6750A0` 捕获并桥接 2697。证据 `evidence/experiments/20261021-1649370-getchallenge-captured.json`。

## 2026-10-21 G2 持久 hook 崩溃（本轮）

`0x6750A0` 入口 cave hook（保存 flags/regs、复制 `[esp+8]`、重放 prologue、跳回 `0x6750A5`）两次都让客户端 `unhandled_exception`（加 `cld` 前后）。一次性断点仍可靠，已抓到 `getchallenge 0 "a731af49a6a2c7e2"`。hook 由 `--hook-loopback` 控制、默认关闭。下一步用一次性断点 + Python UDP 桥完成 challenge/connect，不继续修 hook。证据 `evidence/experiments/20261021-1649370-loopback-hook-crash.json`。

## 2026-10-21 G2 2697 challengeResponse 兼容确认（本轮）

1649370 的 `getchallenge 0 "a731af49a6a2c7e2"` 加 `\xff\xff\xff\xff` 前缀直接发 2697，收到 `\xff\xff\xff\xffchallengeResponse -486178985\0`，协议兼容。把应答注入 loopback 接收环（`0x786DBC0`）后读光标 0→1，但状态保持 3、无 connect；type=4/2、带/不带前缀均如此。下一步直接调用 `0x5C1678` 解析器或找网络泵真正接收队列。证据 `evidence/experiments/20261021-1649370-challenge-response-probe.json`。

## 2026-10-21 G2 直接 OOB 解析器 fatal（本轮）

主线程调 `0x5C0FD0`（eax="challengeResponse -486178985"，栈 netadr，arg0=0）→ 客户端 `fatal_dialog`，无 JSON。环注入（`0x786DBC0`）读光标 0→1 但状态仍 3、无 connect。目前无已验证的 challengeResponse 回送方法；2697 文本应答已确认可用。下一步 hook 真实 `0x5C0FD0` 调用路径，或回到 `0xBB2C40` 完整初始化。证据 `evidence/experiments/20261021-1649370-parser-fatal.json`。

## 2026-10-21 G2 缺口裁决（本轮）

2697 对 1649370 的 getchallenge 已回 `challengeResponse -486178985`；客户端回送路径全部未打通（环注入被消费但状态仍 3、冷调 `0x5C0FD0` 直接 fatal、poke 闸门崩）。详见 `1649370-G2-GAP.md`。下一步优先“真实传输通道”：还原 `0xBAD810 → 0xBB2C40` 参数，让 `[biz+0x18]` 自然置 1；其次服务端侧补齐。不再重复冷调解析器/poke 闸门/裸环注入。

## 2026-10-21 G2 传输初始化冷调用崩溃（本轮）

`0xBB2C40(arg1=[host+0xC], arg2=connection, ecx=biz)` → 客户端 `unhandled_exception`；需要 `0xBAD810/0xB74FE0` 的真实会话对象，冷调用不可行。客户端侧最后一条捷径关闭；需要 1649370 服务端/协议资产，或改用其它可玩构建。证据 `evidence/experiments/20261021-1649370-init-transport-crash.json`。

## 2026-10-21 G2 通道表为空、客户端捷径耗尽（本轮）

扫描 `0xE3F4DB0` 157 项全空；伪造 0xA8 会话调 `0xBB2C40`、fake EBP 帧调 `0x5C1678` 均 `unhandled_exception`。2697 的 challengeResponse 已可用，但离线客户端无法接受/建真实通道。下一步需裁决：继续真实 `0xBAD810` 会话对象逆向（高风险），或改做 2.6.9.7/3.3.3.3 可玩构建。证据 `evidence/experiments/20261021-1649370-transport-table-empty.json`。

## 2026-10-21 G2 raw UDP 补丁首试（本轮）

type=4 的 `0x622040` 参数：len=0x26、data=0x1AE210、type=4、127.0.0.1:28969、channel=0x9D；Com Error `EXE_CLIENTFAILEDTOCHALLENGE`。把入口 9 字节改成 socket/sendto cave 后客户端 `unhandled_exception`；ABI/调用路径不安全。下一步只替换无效通道分支、保留原函数其它路径，并先逐指令 trace。证据 `evidence/experiments/20261021-1649370-raw-udp-patch-crash.json`。

## 2026-10-21 G2 无效分支 raw UDP 补丁仍崩（本轮）

只替换 `0x6221D8`（`mov ebx,-7`）为 socket/sendto cave，保留 `0x622040` 其它路径；客户端仍 `unhandled_exception`。参数已知（data=0x1AE210、len=0x26、127.0.0.1:28969、channel=0x9D）。下一步逐指令 trace 首个 type=4 调用，再用“先走原分支、后 sendto”的隔离 stub。证据 `evidence/experiments/20261021-1649370-raw-udp-branch-crash.json`。

## 2026-10-21 G2 无效通道分支确认（本轮）

`0x622040`/`0x6221D8` 断点各命中一次；`0x6221D8` 时 `ebx=-7`、len=0x26、data 候选 `0x13A033E8`、type=4、127.0.0.1:28969，Com Error `EXE_CLIENTFAILEDTOCHALLENGE`。分支与参数正确，branch-only 补丁崩溃在 cave/socket 或清理契约。下一步 noop→`0x6750A0`→socket 逐级隔离。证据 `evidence/experiments/20261021-1649370-invalid-branch-trace.json`。

## 2026-10-21 G2 noop 补丁成功、分支参数确认（本轮）

`0x6221D8 -> xor ebx,ebx; jmp 0x6221DD` 后客户端保持响应、无 Com Error；参数 len=38、data=0x1AE210、type=4、127.0.0.1、port 网络序 0x2971、channel=0x9D。之前 socket/sendto cave 的数据/长度正确，崩溃在 Winsock 调用或清理交互。下一步先只调 `socket(2,2,17)` 隔离 socket 与 sendto。证据 `evidence/experiments/20261021-1649370-branch-noop-args.json`。

## 2026-10-21 G2 socket-only 存活、WSAStartup 崩（本轮）

无效分支只调 `socket(2,2,17)` 时客户端存活、无 Com Error，但 handle=0；在 cave 内加 `WSAStartup(0x202,&wsadata)` 后以 `0xC0000409` 退出。socket-only stub 安全，问题在 WSAStartup 导入/ABI 或句柄无效。下一步 WSAStartup 走独立远程线程/用已有 WSA，并单独测 sendto。证据 `evidence/experiments/20261021-1649370-branch-socket.json`。

## 2026-10-21 G2 stdcall 修复、socket 成功（本轮）

Winsock 是 `__stdcall`；去掉 cave 在 WSAStartup/socket/sendto 后的 `add esp` 后，`socket(2,2,17)` 返回有效句柄 `0xD00`，客户端存活、无 Com Error。socket+sendto/sendto-only 不再崩溃，但 `ring-probe.json` 不写出、服务端无包，sendto 路径变为挂起。下一步 sendto 放独立远程线程并记录返回值，或用 WSASendTo/非阻塞 socket。证据 `evidence/experiments/20261021-1649370-stdcall-socket.json`。

## 2026-10-21 G2 客户端进程内真实 UDP 发送成功（本轮）

`--remote-udp-send` 用 `CreateRemoteThread` 在客户端进程内执行 `WSAStartup(0x202)+socket(2,2,17)+sendto`，发送 `getchallenge 0 "a731…"` 到 28969；`sendto_return=37`，2697 日志出现 `SV packet 127.0.0.1:63053: getchallenge...`。证明真实 Winsock UDP 通道可用。剩余：接收 challengeResponse 并注入客户端、保持同一 socket/源端口用于 connect。证据 `evidence/experiments/20261021-1649370-remote-udp-success.json`。

## 2026-10-21 G2 客户端进程内真实 UDP 收发成功（本轮）

远程线程 `WSAStartup+socket+sendto+recvfrom` 从客户端进程发 getchallenge（sendto=37），收 `challengeResponse 1179435301`（recv=33），来源 127.0.0.1:28969，源端口 53648；2697 日志确认。真实 Winsock 双向通道可用。环注入那次未写出 JSON，尚未证明。下一步持久 socket/同源端口 + 按真实 from-adr 注入。证据 `evidence/experiments/20261021-1649370-remote-udp-recv.json`。

## 2026-10-21 G2 2697 完整 admission 握手打通（本轮）

裸 UDP 先 `getchallenge` 得 `challengeResponse 575562493`；`connect` 的 `name` 必须是 UTF-16LE hex（`player`→`50006c006100790065007200`），2697 返回 `connectResponse \mapname\mp_cross_fire\gametype\war\sv_maxclients\12\protocol\1\shortversion\1.1.1.13`。服务端 admission 文本格式已还原。下一步在客户端持久 socket 跑完整握手并喂给客户端。证据 `evidence/experiments/20261021-1649370-connect-response.json`。

## 2026-10-21 G2 2697 完整握手工具化（本轮）

`tools/probe_2697_connect.py` 完成 `getchallenge → connect`（name=UTF-16LE hex），2697 返回 `connectResponse \mapname\mp_cross_fire\gametype\war\sv_maxclients\12\protocol\1\shortversion\1.1.1.13`，证据 `ok:true`。服务端 admission 文本格式可复跑；剩余是客户端持久 socket + 应答注入。证据 `evidence/experiments/20261021-1649370-connect-probe.json`。

## 2026-10-21 G2 客户端进程内完整 admission 成功（本轮）

固定源端口 28970，客户端进程内完成 getchallenge/connect（UTF-16LE hex 名字），收到 `challengeResponse -891575079` 与 `connectResponse map=mp_cross_fire/gametype=war`；2697 日志 `CS_FREE → CS_CONNECTED ... 127.0.0.1:28970<=>127.0.0.1:28969`。线程退出 socket 关闭后 disconnect。协议层已打通；下一步保持线程/socket 存活，接 stats/heartbeat/native 并桥接回客户端。证据 `evidence/experiments/20261021-1649370-remote-connect-success.json`。

## 2026-10-21 G2 connect 后 512 个 9 字节包（本轮）

保持 socket 不断开时，2697 在 connectResponse 后发送 512 个 `[u32 seq][u32 0][u8 checksum]` 包（seq 1 递增，checksum 如 1→0x66、0x67→0x00），像 512 槽 stats/keepalive 挑战；socket 关闭后 disconnect。下一步确认语义并实现保活/响应。证据 `evidence/experiments/20261021-1649370-remote-connect-linger.json`。

## 2026-10-21 G2 connect 后 9 字节包定量分析（本轮）

`tools/analyze_2697_postconnect.py`：connect 成功后 2 秒收到 326 个 `[u32 seq][u32 0][u8 checksum]` 包，seq 1 递增；checksum 非 `0x67-seq`（1→26、2→25、3→24、4→31、326→93），更像 CRC/命令字节。下一步确认它是 stats 挑战、reliable command 还是 snapshot/keepalive 头。证据 `evidence/experiments/20261021-1649370-postconnect-packets.json`。

## 2026-10-21 G2 9 字节包映射到 CODOL_WritePacket（本轮）

源码 `CODOL_WritePacket` 在 server 侧为 4 字节 sequence + 消息；观测包 = 4 字节 sequence + 5 字节 `00 00 00 00 <byte>`，不是 reliable-transport `0xfffffff0` 头，也不是 512 槽 stats。326 个包是普通 netchan，消息 5 字节；byte 随 seq 变化。下一步确认 5 字节消息 opcode 与 ACK 需求。证据 `evidence/experiments/20261021-1649370-postconnect-format.json`。

## 2026-10-21 G2 9 字节包是 netchan XOR 编码（本轮）

`sv_net_chan.c` 的 `SV_Netchan_Encode` 把 `data[4..]` 与 `challenge ^ netchan.outgoingSequence` 做 XOR，再按 `lastClientCommandString` 逐字节混合。观测到的 9 字节包 = 4 字节 sequence + 5 字节编码消息；最后字节随 seq 变化不是 checksum/stats 位图，而是 XOR 混淆结果。下一步解码该 5 字节消息或按 keepalive/ACK-only 处理。证据 `evidence/experiments/20261021-1649370-postconnect-xor.json`。

## 2026-10-21 G2 connect 后 9 字节包 = 空快照（本轮）

用 getchallenge cookie 与 seq 做 XOR 解码，5 字节消息最后一字节恒为 `0x06` = `svc_snapshot`；326 个/2 秒是服务端持续推送空/最小快照，不是 stats/keepalive。前 4 字节是快照头字段。下一步保持 socket 收流并桥接客户端或复现 ACK/命令。证据 `evidence/experiments/20261021-1649370-postconnect-decode.json`。

## 2026-10-21 G2 离线菜单没有网络对象（本轮）

`tools/scan_client_network_objects.py` 全用户地址扫描 vtable `0xC7AF2C`（recvfrom 包装器），两次均 0 个对象。离线重建客户端有 Winsock 导入、远程线程能建 socket，但自身网络对象从未构造；没有现成 socket 可改指。剩余路径：构造客户端网络对象，或把服务端数据喂进客户端环/解析器。证据 `evidence/experiments/20261021-1649370-network-object-scan.json`。

## 2026-10-21 G2 客户端网络对象类已还原（本轮）

vtable `0xC7AF2C`，对象布局 `+4 sockaddr_in`、`+0x14 SOCKET`、`+0x18 辅助句柄`；方法 `connect 0xC65480`、`init 0xC654A0`（自己创建 socket 并存 +0x14）、`send 0xC65560`、`recv 0xC655B0`、`sendto 0xC655E0`、`recvfrom 0xC65610`。离线菜单不实例化（扫描 0），但 init 可用来构造网络对象。下一步分配 0x40 对象、写 vtable、调 init 验证 socket。证据 `evidence/experiments/20261021-1649370-net-object-class.json`。

## 2026-10-21 G2 0xC654A0 是 TCP accept（本轮）

构造 0xC7AF2C 对象并调用 `0xC654A0(port=-1)` 后 `[obj+0x14]=0`；解析 IAT 发现 `0xCA8500 = ws2_32!accept`，该函数在 `[obj+0x18]` 的 listen socket 上 accept，并把结果存 +0x14。不能拿它建 UDP socket。下一步用 WSA 建 UDP socket 存 `obj+0x14`，再用对象 `sendto 0xC655E0`/`recvfrom 0xC65610` 方法；或找在线 UDP 对象/vtable。证据 `evidence/experiments/20261021-1649370-netobj-accept.json`。

## 2026-10-21 G2 UI 本地对战入口探索（本轮）

模拟点击 `游戏大厅 → 开始游戏` 后出现 `多人竞技(PVP)`、`闯关模式(PVE)`、`勇者游戏`、`排位赛`、`自定义`、`训练`、`影院` 子页；`自定义` 有完整建房面板（模式/地图/房间名/人数 12/创建房间），但点 `创建房间` 无响应；`多人竞技` 显示“未找到房间”，`勇者游戏` 空白，`训练` 标签点不亮。1649370 资源树只有 common/ui/post-gfx fastfile，没有 `mp_*` 地图 fastfile。结论：UI 建房后端驱动，无房间服务不会开本地局；下一步构造客户端网络对象/环消息路径，或跑兼容房间/lobby 后端。证据 `evidence/experiments/20261021-1649370-ui-custom-room.json`。

## 2026-10-21 G2 主菜单 Cbuf 注入成功、地图加载失败（本轮）

新增 `--cbuf-command`，在主菜单 stage 5 直接向原生 Cbuf 追加命令；`devmap mp_strike_sh` 注入成功（old_length 0 → new_length 22），画面黑屏数秒后回到大厅，进程仍响应。Cbuf 注入机制可用，但 1649370 客户端不接受 3.3.3.3 的 `mp_strike_sh` 地图（缺 1649370 原生 `mp_*` fastfile/版本不匹配）。下一步必须拿到 1649370 兼容地图 fastfile，或跑兼容房间后端。证据 `evidence/experiments/20261021-1649370-cbuf-devmap.json`。

## 2026-10-21 G2 阻断结论：缺 1649370 地图资产/房间后端（本轮）

`--cbuf-command` 已能在 stage 5 注入 `devmap mp_strike_sh`（0→22）和 `map mp_strike_sh`（0→19）；两者都被客户端接受执行，但画面要么黑屏数秒后回大厅，要么直接留在大厅，进程始终响应。全盘搜索确认 1649370 资源树只有 common/ui/post-gfx fastfile 和 `mp_playlists.ff`，没有 1649370 原生 `mp_*` 地图 fastfile；3.3.3.3 的 `mp_strike_sh`/`mp_arkaden_sh` 不被接受。同时离线客户端没有网络/房间对象。结论：没有兼容地图或能提供地图加载路径的房间/lobby 后端，无法进入任何本地 bot 地图。证据 `evidence/experiments/20261021-1649370-map-load-failure.json`。

## 2026-10-21 自检纠正：完整客户端在使命召唤OL（本轮）

此前只搜了 `E:\GAME\COD\1649370` 与 `Original Client`，漏掉 `E:\GAME\COD\使命召唤OL`。该目录有 `IIPS\IIPSDownload\*.ifs` 地图包；用 `extract_signed_ifs_fastfiles_1649370.py` 从 `ff_dlc18_mp_hardhat_sh_V37.ifs` 提取出原生 v461、发布者签名验证通过的 `mp_hardhat_sh.ff`（35.5MB，zone 76.5MB，382 assets）及 load/const，并加入 `--map-probe mp_hardhat_sh`。Cbuf `devmap`/`map mp_hardhat_sh` 注入成功（0→23/20），但社区 exe 黑屏数秒后回大厅/仓库，未进地图。下一步确认社区 exe 是否缺 listen-server/map-load 路径，或改用完整客户端 `codoMP_client_shipRetail.exe`。证据 `evidence/experiments/20261021-1649370-full-client-maps.json`。

## 2026-10-21 原生 hardhat 三目录均不进图（本轮）

把从完整客户端 `ff_dlc18_mp_hardhat_sh_V37.ifs` 提取的 v461 签名 `mp_hardhat_sh.ff` 分别放到 `runtime\client_shipretail\chinese`、`runtime\main`、`runtime\zone`，Cbuf `devmap`/`map` 都注入成功（0→23/20），但社区 `codol1649370-offline.exe` 仍黑屏/回大厅，无 Com Error。结合路线图既有结论：`devmap`/`map` 在此客户端不是注册命令，社区 exe 是 client-only，没有 listen server/本地开图入口；地图只能由服务端 gamestate 驱动。完整客户端地图资产已可用（可喂 2697 服务端），剩余是客户端网络对象/连接路径。证据 `evidence/experiments/20261021-1649370-hardhat-paths.json`。

## 2026-10-21 G2 stats 上传完成，服务端保持连接（本轮）

裸 UDP 依次完成 `getchallenge` → `connect`（connect 包必须 latin-1 编码，UTF-8 会把 `\xff` 变成 `c3bf` 而被 disconnect）→ 27 个 stats 包（`\xff\xff\xff\xffstats\0 + index:u8 + compressed:u16=0 + 1238 字节`，profile 32768 字节，头部为 `crc32(profile[4:])`）。服务端日志出现 `CoDOL 2697 stats complete client=0 compressed=0`，返回 `statResponse 0` 并持续发送 9 字节快照，连接不再断开。这解除了 stats 上传阻断。下一步把同一 stats 上传放进 1649370 进程远程线程，并确认服务端随后是否发 gamestate/需要 userinfo、usercmd。证据 `evidence/experiments/20261021-1649370-stats-complete.json`。

## 2026-10-21 G2 stats 后首包未触发 gamestate（本轮）

stats 完成后发送 `u32 sequence=1 + clc_clientCommand(0x02) + "userinfo \name\player\xuid\...\rate\25000\0"`，服务端保持 `CS_CONNECTED`，日志无 `CS_PRIMED`/gamestate，仍只回 `statResponse` 和 9 字节快照。说明首个 clientCommand 不是进入世界的触发包；下一步改试 `clc_move`/usercmd 首包，或把 userinfo 走 OOB，并检查 `SV_PacketEvent` 的状态门槛。证据 `evidence/experiments/20261021-1649370-stats-first-command.json`。

## 2026-10-21 G2 gamestate 已捕获并解码（本轮）

stats 完成后发送 `u32 sequence=1 + clc_move(0x00) + cmdCount=1 + 200 个零`，服务端日志出现 `SV_SendClientGameState()` 与 `Going from CS_CONNECTED to CS_PRIMED`。随后收到 3 个 netchan 分片（seq 7，index 0/1/2，1172/1172/1114 字节），重组 3428 字节；保留前 4 字节明文 serverId，其余与 `cookie ^ seq`（本次 0xB6）XOR，得到 gamestate 明文：`00 00 00 00 03 00 00 00 00 "mp_cross_fire" "mp" ... \g_gametype\war\mapname\mp_cross_fire\2485\12\`。工具 `tools/reassemble_2697_gamestate.py`，输出 `runs/2697-gamestate-packets/gamestate-final.bin`。下一步把 gamestate 及后续快照喂进客户端环/解析器，驱动地图加载。证据 `evidence/experiments/20261021-1649370-gamestate-captured.json`。

## 2026-10-21 G2 gamestate 注入后客户端开始 challenge（本轮）

`--ring-probe --ring-type 4 --inject-gamestate gamestate-final.bin` 把 3428 字节 gamestate 写入环 slot `0x786DBC0`（state 1→3，channel=0x9D，read/write cursor=1）。约 20 秒后客户端弹出 `EXE_CLIENTFAILEDTOCHALLENGE`，说明它已消费 gamestate 并推进到 challenge/连接阶段；该次没有启动 2697 服务端，所以 challenge 失败。下一步在注入 gamestate 的同时启动 2697 服务端 + loopback guard，观察是否能完成 challenge 并加载 `mp_cross_fire`。证据 `evidence/experiments/20261021-1649370-gamestate-injected.json`。

## 2026-10-21 G2 带服务端的 gamestate 注入仍卡 challenge（本轮）

2697 服务端 + loopback guard + `--ring-probe --ring-type 4 --inject-gamestate` 联合运行，客户端仍先黑屏再弹 `EXE_CLIENTFAILEDTOCHALLENGE`，而 2697 `qconsole.log` 没有任何 getchallenge/connect。说明客户端 challenge 目标不是 `127.0.0.1:28969`，单纯启动服务端不能满足；必须在改状态前把 `challengeResponse`（必要时还有 `connectResponse`）和 gamestate 一起排进环，或显式改客户端 challenge 目标地址。证据 `evidence/experiments/20261021-1649370-gamestate-challenge-failed.json`。

## 2026-10-21 G2 三消息同序列注入仍 challenge 失败（本轮）

`tools/inject_client_gamestate.py` 在改状态前依次排入 `challengeResponse 1469978033`、`connectResponse map=mp_cross_fire`、3428 字节 gamestate（slot `0x786DBC0/0x786E0C4/0x786E5C8`，cursor=3，state=3，connection adr 设为 127.0.0.1:28969）。客户端仍然黑屏后弹 `EXE_CLIENTFAILEDTOCHALLENGE`。trio 已进入环，但客户端要求自己的 challenge cookie/目标；下一步改写 challenge 目标/端点表，或截获 getchallenge 并用匹配 cookie 回答。证据 `evidence/experiments/20261021-1649370-gamestate-sequence-injected.json`。

## 2026-10-21 G2 无效通道改为成功返回后，gamestate 注入进入黑屏加载态（本轮）

把 `0x6221D8` 的 `mov ebx,-7` 改成 `mov ebx,1`（`--branch-noop`），让 `0x675260/0x622040` 的发送返回成功；再执行 `--ring-probe --ring-type 4 --inject-gamestate gamestate-final.bin`。结果不再出现 `EXE_CLIENTFAILEDTOCHALLENGE`，客户端进入纯黑屏（仅光标）并持续到 70 秒观察超时，进程响应、`stop_reason=observation_timeout`、无 Com Error。说明已越过 challenge 错误，进入“等后续数据/加载”状态。下一步在 gamestate 后继续喂快照/配置串，或确认它是否在等某个 server 包。证据 `evidence/experiments/20261021-1649370-branch-success-gamestate.json`。

## 2026-10-21 G2 合成快照流未推进（本轮）

`tools/feed_client_snapshots.py` 在通道成功补丁 + ring-probe 后，把 gamestate 与 13 条合成 `serverId=0 + svc_snapshot` 消息排入环（queued=14，cursor=14，state=3）。客户端保持黑屏（仅光标）、无错误、进程响应，但 `read cursor` 仍为 0——环泵没有消费这些消息。说明合成快照格式/状态不对，或泵在状态 3/黑屏时不再读取。下一步改用真实捕获的快照字节（含 netchan/序列），或在主线程直接调用泵/解析函数后再观察 read cursor。证据 `evidence/experiments/20261021-1649370-feed-snapshots-black.json`。

## 2026-10-21 G2 原生 cross_fire 基础图仍黑屏（本轮）

从完整客户端 `ff_init_mp_cross_fire_V70.ifs` 提取出原生 v461 签名的 `mp_cross_fire.ff`（37,331,221 字节，zone 75,189,466，240 assets）及 load/const，加入 `--map-probe mp_cross_fire_native`。用 `map-probe + --branch-noop + --ring-probe --ring-type 4 + --inject-gamestate` 重试：40 秒、90 秒都是纯黑屏（仅光标），进程响应、无错误。说明即使地图资产齐全，gamestate 注入仍不足以完成地图加载，客户端在等更多 loader/server 数据，或图载过程卡住。下一步检查黑屏期间是否打开 `mp_cross_fire.ff`/zone，或补齐 configstring/snapshot/loader 数据。证据 `evidence/experiments/20261021-1649370-native-crossfire-black.json`。

## 2026-10-21 G2 本地 challenge 读到，环注入不推进状态（本轮）

远程线程调用 `0x5BF860(buf)`，读到客户端本地 challenge 字符串 `a731af49a6a2c7e2`。在黑屏 state=3 时再次注入 `OOB challengeResponse 1469978033` + `OOB connectResponse` + gamestate，read cursor 从 4 推进到 7（泵消费了），但 state 仍是 3。说明环里的 challengeResponse 文本不是把状态机从 3 推到 4 的事件；需要主线程调用 `0x5C0FD0` 解析器（正确帧），或改状态机接受注入响应。证据 `evidence/experiments/20261021-1649370-local-challenge.json`、脚本 `runs/_tmp_callchallenge.py`。

## 2026-10-21 G2 强制 state4 仍黑屏（本轮）

在原生 `mp_cross_fire` + 通道成功补丁 + gamestate 注入的黑屏基础上，把 `0x76446B0` 从 3 强制写成 4；20 秒后 state 仍为 4、channel 0x9D、read/write cursor 1，画面仍是纯黑屏（仅光标），进程响应。说明直接改状态值不能启动地图加载，客户端需要真实的 challenge/connect/gamestate 网络事件，而不是只改 state。当前阻断：没有能让 1649370 客户端完成这组事件的兼容服务端/网络对象；地图资产已就绪但客户端在 state 3/4 停滞、I/O 为 0。证据 `evidence/experiments/20261021-1649370-force-state4.json`。

## 2026-10-21 完整客户端 exe 启动尝试（用户允许全部修改后）

把 `使命召唤OL` 根目录复制/联接成私有 `runs/full-client-private`（省略 ACE/TGuard/TerSafe/PolicyProbe/TenRpcs 等反作弊依赖），直接启动 `codoMP_client_shipRetail.exe +set fs_basepath`：进程存活但无窗口，只加载 WOW64 基础模块，无 ACE/TGuard。包装层 `--image` 完整 exe：报“仅运行项目固定版本基底或 workspaces 内候选”；放入 workspaces 候选后报“补丁原字节不匹配”；改用空补丁 `[]` 后退出码 `0xC0000135`（缺 Base.dll/同目录依赖）。说明完整 exe 不能直接替代社区离线镜像，需要自己的 TCLS/依赖链。证据 `evidence/experiments/20261021-1649370-full-client-launch.json`，私有副本 `runs/full-client-private`。

## 2026-10-21 完整 exe 直接 +devmap 仍无窗口（本轮）

用私有副本 `runs/full-client-private` 直接启动 `codoMP_client_shipRetail.exe +set fs_basepath ... +devmap mp_cross_fire`，进程存活但 20 秒后仍无窗口，只加载 WOW64 基础模块，`codoMP_client_shipRetailBase.dll` 未加载。说明完整 exe 在进入游戏前等待 TCLS/启动链/依赖，不是 `+devmap` 能绕过。包装层失败点（候选限制/补丁不匹配/空补丁缺 DLL）已记在证据里。下一步走 TCLS 启动链并监控是否加载 ACE/TGuard 驱动，或补齐 Base.dll/同目录依赖后直接启动。证据 `evidence/experiments/20261021-1649370-full-client-launch.json`。

## 2026-10-21 完整 exe 卡在 TCLS/启动握手，无任何窗口（本轮）

直接启动私有副本的 `codoMP_client_shipRetail.exe` 后，进程有 15 个线程，等待原因包含 `EventPairLow` 与 `ExecutionDelay`；枚举该 PID 的所有窗口（含隐藏）结果为 0 个窗口；`tasklist /M` 只显示 64 位/WOW64 基础模块。说明它停在创建窗口/加载 32 位游戏模块之前的 TCLS/launcher/反作弊握手，而不是 `+devmap` 或地图问题。下一步必须走 `TCLS\Client.exe` 或模拟 TCLS 管道/握手，并监控是否加载 ACE/TGuard 驱动。证据 `evidence/experiments/20261021-1649370-full-client-launch.json`。

## 2026-10-21 完整 exe 需要 TCLS 登录链，当前离线副本无 token（本轮）

`TCLS\config\dirserver.xml` 指向 `tcls.qq.com`、`123.151.176.103`、`119.84.150.46`、`183.61.224.121`、`101.91.63.192` 的 8080/5223/10009 端口；完整 `codoMP_client_shipRetail.exe` 的 15 个线程停在 `EventPairLow`/`ExecutionDelay`，0 个窗口，说明它必须先拿到 TCLS/launcher 的管道/握手才会创建游戏窗口。原始 TCLS/TGuard 链会加载腾讯反作弊服务/驱动，违反“不加载驱动”；当前离线客户端里没有 TCLS token/离线配置。下一步需要离线 TCLS/launcher 绕过，或回到社区离线 exe + 兼容服务端/网络对象。证据 `evidence/experiments/20261021-1649370-full-client-tcls.json`。

## 2026-10-21 TP 弹浏览器确认：合成 TCLS 只过启动门槛，TP 仍拦截

合成 TCLS 后窗口 `警告码(3, 1045, 19002)` 的“确定”直接打开腾讯游戏安全中心：
`https://gamesafe.qq.com/game_tips.shtml?a=3&b=1045&c=19002&game_id=52&reason_id=3`
页面为“特殊弹窗：查杀病毒和木马，重启机器后再试”（错误码 230）。这证明 `a=3/b=1045/c=19002/game_id=52/reason_id=3` 是 TP 反作弊自己的告警，不是 TCLS 登录错误。TP 会检测环境并 shell-execute 浏览器，之后不创建游戏主窗口。决定：不把 TP 运行时绕过作为主路线；复用社区离线 exe（本身排除 TP/TCLS）继续做客户端网络/地图路径。证据 `evidence/experiments/20261021-1649370-tp-browser-warning.json`、`...fullclient-synthetic-tcls*.json`。

## 2026-10-21 给社区 exe 补完整 Base.dll 仍无网络对象（本轮）

尝试三种方式把完整客户端 `codoMP_client_shipRetailBase.dll` 给社区离线 exe：私有 overlay 被拒（必须在固定资源目录/workspaces）；workspaces overlay 带 DLL 被拒（overlay 不可携带执行组件）；启动后 1 秒内复制 Base.dll 到 runtime 成功，但扫描 vtable `0xC7AF2C` 仍 0 个网络对象，客户端保持大厅。说明社区 exe 的离线构建不是“缺 Base.dll”，而是网络对象/连接路径本身未初始化；加 Base.dll 不能复活。证据 `evidence/experiments/20261021-1649370-base-overlay-no-netobj.json`。

## 2026-10-21 cdb 附加 TP 进程失败，改静态/进程内 hook（本轮）

synthetic TCLS 启动后存在进程树：root `33424` 退出、游戏子进程 `codoMP_client_shipRetail` `9264` 存活。`cdb -p 33424` 报 Win32 error 87（进程已退出）；`cdb -p 9264 -c "lm;q"` 挂起、无提示/输出，被超时终止。说明 TP/anti-debug 会阻挡或冻结调试器附加，cdb 不是可靠路线。下一步改：对 `TASLoginBase.dll`/`TGuardBase.dll`/`ClientBase.dll` 的 TP URL 格式串做静态分析，或用进程内 API hook（不依赖调试器）拦截 `ShellExecute/浏览器` 调用后再打补丁。证据 `evidence/experiments/20261021-1649370-tp-cdb-attach.json`。

## 2026-10-21 TP URL 静态定位完成，调用图受保护（本轮）

TP URL 格式串 `?a=%d&b=%d&c=%d&game_id=%d&reason_id=%d` 出现在 `ClientBase.dll`/`tpsvcBase.dll`/`TASLoginBase.dll`（VA `0x101CC8E4`）、`TGuardBase.dll`（VA `0x106C41E8`）、`Base.dll`；但前三者没有绝对 dword 引用，TGuardBase 只有一处 `0x11337EA1`（像数据指针）。这些模块也没有静态导入 `ShellExecute`/`CreateProcess`/`WinExec`，浏览器 API 是运行时解析或保护/解包路径。结合 cdb 附加挂起，结论：正常静态调用图不可用；下一步走进程内 API hook（shell32/kernel32，按 URL 过滤）或 TGuardBase URL 数据流补丁，而不是继续 cdb。证据 `evidence/experiments/20261021-1649370-tp-static.json`。

## 2026-10-21 进程内 hook 成功压掉 TP 浏览器，但 blanket CreateProcess 也压掉游戏窗口（本轮）

`tools/hook_tp_browser.py` 在完整客户端进程内 patch `shell32!ShellExecuteA/W`、`ShellExecuteExA/W` 和 `kernel32!CreateProcessA/W`（原字节已记录）。结果：TP 警告窗口和浏览器都不再出现；但 60 秒采样内游戏进程始终 `exit_code=259`、0 个窗口。说明 blocking 所有 CreateProcess 同时阻断了游戏/CEF 的窗口路径。下一步改成按命令行过滤的 CreateProcess hook：允许游戏/CEF，只拦截 `gamesafe`/浏览器启动；再观察 TP 警告是否非致命、游戏窗口是否出现。证据 `evidence/experiments/20261021-1649370-tp-hook-results.json`、工具 `tools/hook_tp_browser.py`。

## 2026-10-21 按命令行过滤的 CreateProcess hook：浏览器不再开，但游戏窗口仍不出现（本轮）

`tools/hook_tp_browser.py` 现在 patch `shell32!ShellExecute*`，并在 `kernel32!CreateProcessA/W` 入口装 cave stub：只扫描命令行里的 `gamesafe`，命中才返回 0，否则执行原 prologue 后跳回。60 秒采样结果：TP 警告窗口/新浏览器进程都没有出现，但游戏进程仍 `exit_code=259`、0 个窗口。说明 TP 的阻断不只是“打开浏览器”这个通知；warning/exit 判定或另一个检查仍在阻止游戏窗口。下一步：hook/patch `TGuardBase`/`TASLoginBase`/`ClientBase` 的 warning/exit 判定，或 hook `ExitProcess/TerminateProcess` 看 TP 是否在终止子进程，或运行真实 TGuard 服务测试环境是否被接受。证据 `evidence/experiments/20261021-1649370-tp-hook-filtered.json`。

## 2026-10-21 对话框/退出 API 全部中和后仍无游戏窗口（本轮）

在 ShellExecute/CreateProcess 过滤补丁之上，又 patch `ExitProcess`、`TerminateProcess`、`MessageBoxA/W`、`DialogBoxParamW`、`CreateDialogParamW`（全部成功）。60 秒结果：TP 警告窗口不再出现，但游戏进程仍 `exit_code=259`、0 个窗口；同时出现若干新的 msedge 背景进程，无法确认是否 TP 启动。说明仅靠 API 级中和不足以让游戏继续：TP 的阻断在受保护的判定路径（TGuardBase/TASLoginBase/ClientBase）或要求真实 TGuard 服务。下一步只剩：启动真实 TGuard 服务测试，或对 `.tp3/.tls` 的 TP 判定做运行时 patch（需要能绕过 anti-debug 的跟踪手段）。证据 `evidence/experiments/20261021-1649370-tp-dialog-hook.json`。

## 2026-10-21 安装真实 TGuard 服务也不能让 TP 放行（本轮）

从私有副本运行 `TGuardSvc.exe -install`（服务名 `TGuardSvc`，Manual），`Start-Service` 后 Status=Running；再用合成 TCLS 启动完整客户端，结果仍没有游戏窗口（采样进程无窗口后结束），TP 警告这次未出现。随后已 `-uninstall` 移除服务。结论：单靠真实 TGuard 服务不能满足 TP；TP 仍要求真实 TCLS/TesSafe 登录/token 环境，或必须在受保护的 TP 判定里做运行时 patch。证据 `evidence/experiments/20261021-1649370-tguard-service.json`。

## 2026-10-21 PAGE_GUARD+VEH 跟踪 TP URL 未命中（本轮）

`tools/trace_tp_url.py` 在完整客户端内存中只找到 Base.dll 的 URL 格式串副本 `0x61E56B98`，把页 `0x61E56000` 设为 `PAGE_READONLY|PAGE_GUARD` 成功，并注入 VEH（handler `0x11230000`）。等待 8–12 秒，`exception_address/eip` 仍为 0，游戏仍无窗口。说明 TP 不读这个 Base.dll 副本，或读的是稍后加载模块里的另一份，或 VEH 安装未生效。下一步：在进程恢复前安装 VEH 并保护所有模块的所有副本，或按用户允许的 method 2 转 ETW/内核驱动级跟踪。证据 `evidence/experiments/20261021-1649370-tp-veh-trace.json`。

## 2026-10-21 VEH 全副本重试仍无命中，长时间失败转 method 3

`trace_tp_url.py` 在 VEH 安装后（`veh_exit=0xFFFFFFFF`，handler 有效）轮询保护所有找到的 URL 副本；仍只发现 Base.dll `0x61E56B98`，保护页 `0x61E56000` 成功，但 10 秒内 `exception_address/eip=0`，游戏仍无窗口。说明 TP 不通过这个可读副本读取格式串（可能提前解密/复制），进程内 PAGE_GUARD 无法定位 TP 判定。按“长时间失败转 3”的约定：停止在这条 VEH/调试器思路上继续消耗，转向 method 3（重新设计不依赖 anti-debug 的静态/进程内 patch），或回到社区离线 exe + 自写 server（完全绕开 TP）。证据 `evidence/experiments/20261021-1649370-tp-veh-retry.json`。

## 2026-10-21 自写最小 1649370 服务端握手通过（本轮）

新增 `tools/mini_1649370_server.py`（UDP `127.0.0.1:28969`，不改社区源码），实现 `getchallenge`→`challengeResponse <cookie>`、`connect`→`connectResponse \mapname\mp_cross_fire\gametype\war\sv_maxclients\12\protocol\1\shortversion\1.1.1.13`，并记录 `stats`/payload 包。用 `tools/probe_2697_connect.py` 实测 `ok=true`。下一步补 stats/usermove/gamestate 编码，再接有网络对象的客户端；社区离线 exe 仍缺网络对象，完整 exe 仍被 TP 挡。证据 `evidence/experiments/20261021-1649370-mini-server-handshake.json`。

## 2026-10-21 最小服务端补齐 stats + gamestate 分片（本轮）

`tools/mini_1649370_server.py` 现在对每个 `stats` 包回 `\xff\xff\xff\xffstatResponse`，并在收到 usermove 类包（首字节 1）后依次发送捕获的 2697 gamestate 分片 `[1172, 1172, 1114]`。`tools/probe_mini_gamestate.py` 实测：connectResponse 正常、3 个 statResponse、3 个分片长度正确。注意：这是服务端原型，分片仍是 2697 捕获帧；1649370 客户端还没有网络对象可接。证据 `evidence/experiments/20261021-1649370-mini-server-gamestate.json`。

## 2026-10-21 找到并成功调用社区 exe 的 netobj 分配器 0x803830（本轮）

静态分析发现 `0x803830` 先检查 `[0x8269774]`，为空则 `new(0x1618)` + 构造 + 写回；在社区离线客户端大厅用远程线程调用它，`[0x8269774]` 从 0 变为 `0x23E1A030`（非空），vtable `0x00D599DC`。但 `+0x4F4`（conn）仍为 0，`+0x4F8=0xBAADF000`（未初始化），说明只创建了对象，还没建立连接/套接字。下一步调用 `0x803780`/`0xB838A0`/`0xB7A670`（ecx=netobj）或填 `netobj+0x50/0x54` 后驱动 `0xB769A0`，目标是创建 conn/socket 并发 getchallenge。证据 `evidence/experiments/20261021-1649370-netobj-created.json`。

## 2026-10-21 驱动 netobj 仍未建出 conn（本轮）

`tools/drive_client_netobj.py` 正确用 cave 调用 `0x803830`（创建 netobj）、`0x803780`、`0xB838A0(ecx=netobj)`、`0xB7A670(ecx=netobj)`；netobj 为 `0x23E39FE0`，但 `+0x4F4`（conn）始终 0，`+0x4F8` 仍 `0xBAADF000`。手工写 netadr（type=4/127.0.0.1/28969）并置 `+0x4F8=1` 后再调 `0xB838A0`，conn 仍 0（state 变 1）。说明 `0xB838A0`/`0xB7A670` 本身不创建 conn；必须走 lobby 包解析 `0xB769A0`/`0xB83A52`（tag 0x0A）或找 conn 构造函数。证据 `evidence/experiments/20261021-1649370-netobj-drive.json`。

## 2026-10-21 反汇编确认 0xB838A0 不是 conn 创建点

它先检查 `[netobj+0x4F4]`（conn）；为 0 时跳到 `0xB83AA7`，只处理 `[netobj+4]`（lobby 对象），不会分配 conn。`0xB769A0` 只是 tag 0x0A 的 8 字节读取器；`0xB83A52` 把地址写到 `[lobby+0x50/0x54]` 并置 `[netobj+0x4F8]=1`，也不是 conn 分配。conn 必须由独立构造函数/连接入口创建（下一步沿 `0x5C05F0`/`0x5C0EF3` 连接路径或 `0xB7A240` 附近找）。

## 2026-10-21 0x847155 是清空 conn 的析构/清理代码，不是构造函数（本轮）

反汇编 `0x847100` 看到它把 `[esi+0x57C]`、`[esi+0x4F4]`、`[esi+0x4EC]` 等重置为 0/空表；这是对象清理，不是连接创建。`netobj+0x4F4` 的非零写入点还没找到。下一步：对 `netobj+0x4F4` 下硬件写断点（DRx+VEH）抓真实赋值者，或审计 `0x5C05F0` 使用的全局连接对象 `[0x331C0C8]^0xD362501F` 的构造路径。

## 2026-10-21 conn 类方法确认，但构造函数仍未定位

`0xBA0780` 读 conn 的 `+0x644/+0xC8/+0x5E8` 状态；`0xBA0DE0` 写 `+0xAE4`；`0xBA34D0` 检查 `+0xC8==2`、`+0x5E8==3`。这些是 conn 实例方法，说明 conn 对象布局存在，但没有一个函数把 `[netobj+0x4F4]` 写成非零。静态搜索 `0x4F4` 只看到 `0x847155` 的清零和读取者。下一步必须用硬件写断点 DR0=netobj+0x4F4（DR7 写断点）抓真实写入者，或从 `0xBA0xxx` 类的 vtable/构造函数反查分配点。

## 2026-10-21 conn 方法没有直接 vtable 指针，构造函数高度混淆

对 `0xBA0780`/`0xBA0DE0`/`0xBA34D0` 做全文件 dword 搜索，0 个直接引用；说明 conn 的 vtable/构造路径不是普通绝对指针，可能被加密/重定位或由运行时生成。结合 `netobj+0x4F4` 只有清零/读取、没有非零写入，静态定位 conn 构造函数已到瓶颈。下一步只能 DR0 硬件写断点 + 真实触发（需要一次实际连接尝试），或从有网络对象的完整客户端抓一次正常连接做对照。当前没有可触发真实连接的环境。

## 2026-10-21 找到真正的 conn 构造函数 0xBA2800 和连接函数 0xB81EF0

`0xB81F7C` 处 `push 0xAE8; call new; ecx=object; call 0xBA2800`，构造后 `0xB81FFD` 写 `[netobj+0x4F4]`，再 `0xB82025` 调 `0xBA4080(conn, netobj+0x500)` 启动连接。`0xBA2800` 设置 vtable `0xD5A4F4`、复制 0x88 字节结构、`ret 0x9C`。直接构造尝试失败：用 `VirtualAllocEx(0xAE8)` + cave 传 0x9C 零参数调 `0xBA2800`，客户端在 ~12 秒内 unhandled exception 终止，没有产生 conn 证据。说明参数结构/堆分配方式不对；下一步应直接调整个 `0xB81EF0` 并传完整 0x88 结构，或先用游戏 `new 0xB74220` 分配对象。证据 `evidence/experiments/20261021-1649370-conn-constructor-found.json`。

## 2026-10-21 conn 构造函数两次调用都崩溃

第一次用 `VirtualAllocEx(0xAE8)` + 0x9C 零参数调 `0xBA2800`，客户端 unhandled exception；第二次改用游戏 `new 0xB74220(0xAE8)`，并按 `0xB81EF0` 的栈布局传 0x88 零结构 + `[netobj,1,0,0,0]`，仍然 `unhandled_exception`，没有 conn 状态。说明仅调构造函数不够：0x88 结构内容、`0xB81EF0` 的完整前置（`[ebp+0x94]/[ebp+0x98]/[ebp+0x9C]`、初始化）必须一起满足。下一步直接调整个 `0xB81EF0`，或先完整复刻它的参数结构/前置状态。

## 2026-10-21 成功创建真实 conn 对象 0x245EBBF0（vtable 0xD5A4F4）

改用 `0xB82070` 连接包装函数（内部 `0xB81EF0`，默认 flags `0x80000`），cave 传 `cfg`（netadr 127.0.0.1:28969）+ 0x88 零结构，`ecx=netobj`，调用成功。结果：`netobj+0x4F4 = 0x245EBBF0`，vtable `0xD5A4F4`，`conn+0xC8=4`，`conn+0x644=0`，`netobj+0x4F8` 仍 `0xBAADF000`。随后调 `0xBA4080(conn, netobj+0x500)`，conn 状态仍 4，服务端没有收到 UDP getchallenge。说明 conn 已创建，但发送/tick 路径还没接通。下一步：调 `0xB7A670`/`0xBA0780` 驱动状态机，或把 conn 接到全局连接对象 `0x5C05F0`/`0x5C0EF3`，再观察 28969。证据 `evidence/experiments/20261021-1649370-conn-object-created.json`、工具 `tools/start_conn.py`、`tools/conn_send.py`。

## 2026-10-21 0xBA4080 状态机细节：conn 创建后卡在 c8=4

`0xBA4080` 先把 `conn+0xC8` 置 1、`conn+0x5E8=0`，把 `[arg]` 的 0x88 结构复制到 `conn+0x538`，调 `0xBA9970`、`0xBA0760(conn,2,...)`，然后 `0xC73900` 分支：返回 1 → `c8=2` 并调 `0xBA32A0`；返回 -2 → 等 `conn+0x508`；其他 → 错误码 `0x12` 并调 `0xBA3420`。实测创建后 `c8=4`，说明走的是错误/其他分支，发送未发生。下一步：直接调 `0xBA32A0`（成功分支发送）或检查 `0xC73900`/socket 返回值，再观察 28969。

## 2026-10-21 0xBA32A0 不是发送函数

反汇编显示它是 conn 的事件/状态回调：按 `[ebp+8]` 分支，操作 `conn+0x100/0x110` 定时器，调用 `conn+0xCC` 对象的 vtable 方法，并在 `conn+0x90` 时调 `0xBA3100`；没有 `sendto`。真正的发送更可能在 `0xBA0980`（`0xBA32A0` 里第一个 call）或 `0xBA3100` 内。下一步直接调 `0xBA0980`/`0xBA3100`（ecx=conn），或对 `sendto` 下 IAT 断点看谁发包。

## 2026-10-21 客户端确实有 UDP socket，conn 仍卡 c8=4

用 `--loopback-guard --loopback-port 28969` 启动后，`Get-NetUDPEndpoint -OwningProcess` 显示客户端绑定了 `0.0.0.0:58843` 和 `0.0.0.0:22011`，证明网络栈存在。`0xB82070` 创建的 conn（`0x2462BB98`，vtable `0xD5A4F4`）调 `0xBA4080`/`0xBA0980`/`0xBA3100` 后 `c8` 仍为 4，服务端没收到 getchallenge。说明失败在 conn 状态机/地址校验内部，不是“没有 socket”。下一步：读 `0xBA4080`/`0xC73900` 的返回值/错误码，或直接走 `0xBA3420`/`0xBA32A0` 分支，或用客户端现有 socket 发原始 getchallenge 单独验证服务端路径。

## 2026-10-21 0xC73900 是带 0x88 结构的查询函数，0xBA4080 调它时栈不匹配

反汇编 `0xC73900` 显示它读 `[ebp+8]` 的 0x88 结构、调 `0xC76920`、`ret 0x88`；但 `0xBA4080` 在 `0xBA4114` 只 `lea ecx,[ebx+0xC4]; call 0xC73900`，没有压 0x88 参数，静态反汇编看起来栈不平衡。可能是不同重载/中间跳板，或反汇编起点落在函数中部。下一步必须在运行期用 cave 调 `0xBA4080` 并读返回值（al）与 `0xC73900` 的实际栈参数，别再只靠静态推测。

## 2026-10-21 0xC73900 对零结构和 conn+8 都返回 -1

创建 conn 后，`conn+0x538` 的 netadr 是 `type=4, 127.0.0.1, port=0x2971 (28969)`，有效；但直接调 `0xC73900`（ecx=conn+0xC4）分别传零 0x88 结构和 `conn+8` 的 0x88 副本，两次都返回 -1，`c8` 仍 4。说明 `0xC73900` 不是简单的地址解析，期望的输入/状态还没找对；`c8=4` 就是这条失败路径。下一步在 `0xBA4114` 真实调用点抓实际栈/结构内容和 `0xC73900` 返回值，或从它调用的 `0xC76920` 反查语义。证据 `evidence/experiments/20261021-1649370-c73900-probe.json`、工具 `tools/probe_c73900.py`。

## 2026-10-21 0xC73900 真正 call 点是 0xBA411A，但 hook 后 conn 创建失败

`0xBA4114` 是 `lea ecx,[ebx+0xC4]`，`0xBA411A` 才是 `call 0xC73900`（原始字节 `e8 e1 f7 0c 00`）。把 `0xBA411A` 改到 cave 后，`0xB82070` 连接调用返回 `conn=0`，cave 日志全 0，说明 hook 的栈/返回约定破坏了调用（或 cave 未执行）。下一步：修正 cave 的 `ret 0x88` 栈平衡/调用约定，或在 `0xC73900` 入口用更简单的 VEH/断点只记录不替换调用。

## 2026-10-21 VEH 只读跟踪 0xC73900：guard 设置被拒（error 5）

`tools/trace_c73900_veh.py` 成功注入 VEH（`addveh=0x74E8A442`），但 `VirtualProtectEx(0xC73000, 0x120 PAGE_EXECUTE_READ|PAGE_GUARD)` 返回 error 5 (access denied)，所以没有触发 guard，日志全 0。代码页有额外保护/不可改保护，PAGE_GUARD 路线不可用。下一步改用 DRx 执行断点（不改页保护）或在 `0xBA411A` 用不破坏栈的 naked hook（只记录后 jmp 回原 call）。

## 2026-10-21 NOP 掉 0xBA4122 的 jne 后 conn 仍 c8=4

原字节是 `75 27`（jne 0xBA414B），patch 成 `90 90` 后重新创建 conn：`conn=0x2460C338`，vtable `0xD5A4F4`，但 `conn+0xC8` 仍为 4，服务端仍无 getchallenge。说明 `0xBA4122` 不是 `0xBA4080` 实际走到的分支，或 `0xBA4080` 在更早的 `0xBA9970`/`0xBA0760` 就返回/异常。下一步：在 `0xBA4080` 入口和 `0xBA4122` 上计数/断点，确认是否执行到；或 patch `0xBA4080` 内部直接置 `c8=2` 并 call `0xBA32A0`。

## 2026-10-21 强置 c8=2 并调 0xBA32A0(1) 仍回到 c8=4

conn 创建后手工写 `conn+0xC8=2`，再调成功分支 `0xBA32A0(conn, 1)`；调用后 `c8` 又变回 4，`conn+0x644=0`，服务端仍无 getchallenge。说明 `0xBA32A0` 内部会重新判定并走失败/重置路径，或它依赖 `conn+0xCC`/定时器状态。下一步：调 `0xBA3100`/`0xBA0980` 或对 `0xBA32A0`/`0xBA3420` 内部做状态跟踪，找真正把 c8 置 4 的指令。

## 2026-10-21 强置 c8=2 后调 0xBA3100/0xBA0980 仍回到 4

conn 创建后写 `c8=2`，依次调 `0xBA3100(conn)`、`0xBA0980(conn)`，两次调用后 `c8` 都是 4，`0x644=0`，服务端没有 getchallenge。说明这两个函数也不是发送入口，或它们内部同样重新判定/重置。下一步必须找真正写 `conn+0xC8=4` 的指令（DRx 写断点或代码搜索），以及 `conn+0xCC` 对象的方法调用链。

## 2026-10-21 禁用 0xBA3420 重置后 conn 稳定在 c8=2

把 `0xBA3420`（它显式写 `[conn+0xC8]=4` 并清字段）首字节 patch 成 `C3`（直接返回），再创建 conn：`conn_c8=1`；调用 `0xBA3100`/`0xBA0980`/`0xBA32A0(1)` 后 `c8` 稳定为 2，不再回 4。但服务端仍没有 getchallenge。说明已越过错误重置，进入“已连接/等待”状态；下一步要找 `c8=2` 状态下真正的发包调用（可能在 conn+0xCC 对象或网络 pump），而不是再改状态字段。

## 2026-10-21 找到真正的 sendto 包装 0xBB1420

`sendto` IAT 是 `0xCA8518`，调用点在 `0xBB1492`；所在函数 `0xBB1420` 构造 `sockaddr_in` 并调用 `sendto`。签名（stdcall）：`[ebp+8]=socket`、`[ebp+0xC]=ip`、`[ebp+0x90]=port`、`[ebp+0x94]=buf`、`[ebp+0x98]=len`。这是客户端真正的 UDP 发送入口。下一步：用客户端现有 socket（或 `ws2_32!socket` 远程创建）调 `0xBB1420` 发 getchallenge，验证 28969；再把它接回 conn 状态机。

## 2026-10-21 客户端进程内 socket+0xBB1420 发送尝试导致客户端崩溃

`tools/client_udp_send.py` 计划在目标进程内调 `ws2_32!socket(2,2,0)` 建 socket，再用 `0xBB1420` 发 getchallenge；但第一次远程 `socket` cave 执行后客户端直接退出，第二次 `VirtualAllocEx` 返回 NULL，未产生任何 UDP 包。说明远程线程里调 `socket` 的方式/地址/调用约定不对（或 WSA 上下文/线程安全），不是服务端问题。下一步改用 conn 已持有的 socket 字段（避免新建），或先定位 `ws2_32!socket` 在目标里的正确地址/调用方式。

## 2026-10-21 找到 conn 的 socket 字段 conn+0xC4 并成功创建 0xCCC

`0xC738D0` 只把 `[conn+0xC4]` 初始化为 `-1`；`0xC738E0` 是 socket 创建包装（`socket(AF_INET)` 后写回 `conn+0xC4`）。调用 `0xC738E0(conn+0xC4, 2)` 后 `conn+0xC4=0xCCC`（有效 SOCKET），`conn+0xC8` 仍 1/2。用该 socket 调 `0xBB1420` 发 getchallenge（host/network 序端口都试过）仍未在 28969 抓到包，说明 `0xBB1420` 的参数结构/返回值还有问题。下一步：捕获 `0xBB1420` 的 eax 和 `WSAGetLastError`，或直接调 `ws2_32!sendto` 用 socket 0xCCC 验证。

## 2026-10-21 直接 ws2_32!sendto 用 socket 0xCEC 返回 -1

`0xC738E0` 创建并写回 `conn+0xC4=0xCEC`，但直接调 `ws2_32!sendto(socket=0xCEC, ...)` 返回 -1 (SOCKET_ERROR)，服务端仍无包。说明 `conn+0xC4` 很可能不是 Winsock SOCKET，而是客户端内部 socket 索引/句柄；`0xBB1420` 需要的是另一层映射后的真实 socket。下一步：调 `WSAGetLastError` 确认错误码（可能 10038 not a socket），并找内部 socket ID 到 Winsock SOCKET 的映射/`NET_GetSocket` 函数。

## 2026-10-21 成功从客户端进程发出第一个 UDP getchallenge，服务端已收到

`0xC738E0` 建的不是 Winsock UDP socket（`sendto` 报 10057 WSAENOTCONN）；改用 `ws2_32!socket(2,2,0)` 远程创建并写回 `conn+0xC4=0xCD4`，再调 `ws2_32!sendto`：返回 37、WSA error 0；私有服务端日志收到：
`ffffffff6765746368616c6c656e6765203020226137333161663439613661326337653222`
ASCII：`\xff\xff\xff\xffgetchallenge 0 "a731af49a6a2c7e2"`，peer `127.0.0.1:49314`。这证明客户端 UDP 发送链路已通，之前的失败都是因为 `conn+0xC4` 是内部 socket id 而不是 Winsock SOCKET。下一步：在客户端接收/处理 challengeResponse（recvfrom 或客户端 recv 包装），再驱动 connect/gamestate。证据 `evidence/experiments/20261021-1649370-client-getchallenge-success.json`。

## 2026-10-21 客户端收到 challengeResponse

在 `conn+0xC4` 写入真实 UDP socket `0xCCC` 后，用 `ws2_32!sendto` 发 getchallenge（peer 61019），私有服务端回 `challengeResponse 6ad8d973`；再用 `ws2_32!recvfrom` 在客户端进程内读到：
`\xff\xff\xff\xffchallengeResponse 6ad8d973`
这说明客户端 UDP 发送 + 接收两条链路都已打通。下一步：把 challengeResponse 喂给客户端 parser/连接路径，发 connect、收 connectResponse，再推进 gamestate/地图。证据 `evidence/experiments/20261021-1649370-client-challenge-response.json`。

## 2026-10-21 冷调 0x5C0FD0 解析 challengeResponse 会把 netobj/conn 清零

在 conn/socket 就绪后，把 `challengeResponse 6ad8d973` 放到目标内存，cave `eax=buf; call 0x5C0FD0`；调用后 `[0x8269774]` 和 `netobj+0x4F4` 都变成 0，服务端也没有 connect。说明 `0x5C0FD0` 不是可直接冷调的纯解析器，或它需要完整 OOB 帧/已注册的接收上下文，否则触发网络重置。下一步：不要冷调 parser；改为 hook/替换 `recvfrom` 让真实接收路径拿到 challengeResponse，或调用带完整帧/上下文的接收分发函数。

## 2026-10-21 找到 recvfrom 包装 0xBB15E0

`recvfrom` IAT 是 `0xCA851C`，调用点 `0xBB163C`；包装签名约 `[ebp+8]=socket, [ebp+0xC]=buf, [ebp+0x10]=len, [ebp+0x14]=flags, [ebp+0x18]=from`，返回读取字节数。它只做接收，不做协议解析。冷调 `0x5C0FD0` 已证明会清零 netobj/conn，所以下一步必须：用 `0xBB15E0` 收包后，找到真实接收分发/parser 调用点（谁在正常路径调用它并传上下文），而不是冷调 parser。

## 2026-10-21 找到正常“收包+分发”函数 0xC73FC0

`0xBB15E0`（recvfrom 包装）的唯一调用者是 `0xC7401E`，所在函数 `0xC73FC0` 先建 0x88 结构、用 `[this+4]` 作为 socket 收包，再 `0xB753A0(context, from, size)` 分发。用 fake transport（`[this+4]=socket`）+ `context=netobj` 调它：客户端成功收到 getchallenge 响应（服务端已回 cookie），但 `conn+0xC8` 仍 1，未发 connect。说明 `context`/`from`/`this` 的取值还不对。下一步：尝试 `context=conn`、`from=0` 或真实 transport 对象 `conn+0xCC`，并读 `0xC73FC0`/`0xB753A0` 返回值。

## 2026-10-21 0xC73FC0 只是收包/记录来源，不是协议分发

反汇编 `0xB753A0` 只把 `[ebp+8]` 指针和 16 位 from 写入 `context+0x84`，没有解析。`0xC73FC0` 用 `[this+4]` 收包、构造 0x88 结构、再调这个 setter；所以调用它不会推进 challenge/connect 状态。真正的 challengeResponse 解析仍在别处（`0x5C0FD0` 冷调会重置，需要它的正常调用者/上下文）。下一步：找 `0x5C0FD0` 的调用者/接收循环，而不是继续调 `0xC73FC0`。

## 2026-10-21 找到真正的 server-message parser 0x5C13A0

`0x5C0FD0` 其实是错误处理器——`0x5C1AEC` 传给它的是静态串 `0xdbce80="EXE_SERVER_DISCONNECTED"`，所以冷调 `challengeResponse` 会触发断线/重置。真正的 parser 在 `0x5C13A0`：它构造消息、调 `0x768DC0`/`0x768EC0`，在 `0x5C1684` 比较 `0xDBFEE8="challengeResponse"`，命中后调 `0x5C1300` 解析。下一步：用正确的 netadr/消息参数调用 `0x5C13A0`（或它的正常调用者），而不是 `0x5C0FD0`。

## 2026-10-21 冷调真正 parser 0x5C13A0 同样把 netobj/conn 清零

用 `challengeResponse 6ad8d973` + 6 dword netadr + length 调 `0x5C13A0`，调用后 `[0x8269774]` 和 `conn` 又变 0，服务端无 connect。说明这个 parser 需要更完整的调用上下文/消息对象（`0x768DC0` 前置、正确的 length/netadr/字符串指针），不能靠猜栈参数冷调。下一步：找 `0x5C13A0` 的正常调用者（接收循环）并复刻其完整上下文，而不是继续冷调。

## 2026-10-21 0x5C13A0 的两个调用者都依赖队列/流对象

调用点在 `0x5C2040`/`0x5C2112`；调用前先 `0x4F36C0` 分配队列、`0x66EFD0` 取流，再 `ecx=ebx`（队列/流对象）、`push [ebp+8]`、6 dword netadr，最后 call parser。所以 parser 不是独立函数，冷调缺少 `ebx` 流对象和队列状态，才会清零网络。下一步：复刻 `ebx` 流对象/队列上下文，或 hook 这两个调用者的正常入口，而不是继续冷调。

## 2026-10-21 parser 上下文成为新阻断

`0x5C13A0` 必须由 `0x5C2040`/`0x5C2112` 用 `ebx` 队列/流对象调用；冷调会清零 netobj/conn。已确认 `0x5C0FD0` 是错误处理器，真正 parser 是 `0x5C13A0`；收发 UDP 链路已通（getchallenge/challengeResponse 都成功）。但要把 challengeResponse 送进 parser，必须复刻 `0x4F36C0`/`0x66EFD0` 构造的队列/流对象，或抓一次真实接收循环的 `ebx`/栈上下文。当前没有可产生真实接收循环的客户端（社区 exe 无网络对象、完整 exe 被 TP 挡），冷调 parser 每次都会重置网络。下一步只能：抓真实接收上下文（需要能正常连接的客户端），或从 `0x4F36C0`/`0x66EFD0` 逆向构造完整队列对象。

## 2026-10-21 0x5C1EE0 dispatcher 非破坏性但未解析

构造 0x30 字节 buffer 对象（`+8/+0xC=buf`, `+0x14=0`, `+0x18=len`, `+0x1C=0`），以 `arg0=0`、`arg1=obj`、6 dword netadr 调 `0x5C1EE0`；调用后 `netobj/conn` 没有清零（比冷调 parser 安全），`c8` 仍 1，服务端无 connect。说明入口/字段还不完整（可能 `arg0` 要是 netobj/连接对象，或 `+0x8/+0xC/+0x14` 的 buffer 语义不同）。下一步：试 `arg0=netobj`、调整 buffer 字段，并读返回值。

## 2026-10-21 dispatcher arg0=netobj 仍不解析

`0x5C1EE0(arg0=netobj, arg1=fake buffer obj, netadr)` 调用后 `netobj/conn` 未清零，但 `c8` 仍 1、服务端无 connect。结合 `arg0=0` 也无效，说明 `0x5C1EE0` 不是正确的消息入口，或 buffer 对象字段/前置 `0x66EFD0` 流对象仍缺。UDP 收发已通，但 challengeResponse 无法进入真实 parser；冷调 `0x5C13A0` 会清零网络，`0x5C1EE0` 不解析。下一步只能：完整复刻 `0x4F36C0`/`0x66EFD0` 的队列/流对象，或抓一次真实接收循环的 `ebx`/栈上下文。

## 2026-10-21 逆向 0x66EFD0/0x4F36C0：确认是消息流/队列操作

`0x66EFD0` 是 `MSG_ReadString`（从 `edi+0x1C` 起按字节读，遇到 `%`/`\n` 终止，最多 0x400，写到 eax），所以它要求 `edi` 是 `msg_t` 流对象（`+8/+0xC` buffer、`+0x14` 起始、`+0x18` 长度、`+0x1C` 读索引）。`0x4F36C0` 是队列 push（`esi` 队列计数器、`edi` 队列对象、参数 8/0xC）。`0x5C1EE0` 先 `MSG_ReadString` 得到首 token，再与 `0xDBFFA0`（`"R"`/命令头）比较：不等走 `0x5C20C8` 分支；两条分支都会调 `0x5C13A0`。说明构造 `msg_t` 对象本身是对的，但首 token/消息头（`R` 或 OOB 头）还没对上；下一步用真实 `R`/`\xff\xff\xff\xff` 头 + challengeResponse 构造流，再调 `0x5C1EE0`，并读两条分支的返回值。

## 2026-10-21 R\nchallengeResponse 头仍未解析

把 `msg_t` buffer 改成 `R\nchallengeResponse 6ad8d973`（让 `MSG_ReadString` 先读到 `R`），再调 `0x5C1EE0`；结果 `netobj/conn` 未清零，但 `c8` 仍 1、服务端无 connect。说明首 token `R` 对上了，但后续 parser 仍未把 challengeResponse 送进 `0x5C13A0`，或 `msg_t` 的 `+0x14/+0x18` 长度/索引语义还不对。下一步直接以 `ecx=msg_t` 调 `0x5C13A0`（带 length+netadr），绕过 dispatcher 的首 token 分支。

## 2026-10-21 直接 ecx=msg_t 调 0x5C13A0 仍清零网络

用 `R\nchallengeResponse` 的 `msg_t` 作 `ecx`、`length+netadr` 作栈参数调 parser，调用后 `netobj/conn` 再次变 0，服务端无 connect。说明 `0x5C13A0` 需要的不只是 `msg_t`，还需要它调用者 `0x5C1EE0` 建立的队列/流状态（`0x4F36C0`/`0x66EFD0`）以及 `0xB753A0` 的 from 记录。冷调 parser 路线到此为止；下一步转让客户端自己走真实连接/接收循环：填充服务器浏览器表 `0x76446A1` 触发原生连接，或 hook `0x5C2040`/`0x5C2112` 的正常入口。

## 2026-10-21 服务器浏览器入口 0x5BF3E0 定位

`0x76446A1` 表被 `0x5BF3E0` 读取（`cmp byte [0x76446A1],0`），它同时用 `0x331C0C8` 连接对象、设置 `[conn+0x12A6F8]`、调用 `0x549E50`/`0x5BF1C0` 等，是原生“选择服务器并连接”的入口。`0x5BE730` 只扫描表；真正初始化连接的是 `0x5BF3E0` 这一带。下一步：构造 `0x76446A1` 表项（地址字符串/端口/序号）并调用 `0x5BF3E0`，让客户端自己建立连接，而不是冷调 parser。

## 2026-10-21 原生 server browser 0x5BF3E0 冷调无包

把 `0x76446A1` 置 1、传 `"127.0.0.1:28969"` 调 `0x5BF3E0`，客户端在调用后退出，服务端无 getchallenge/connect。说明它也不是可直接冷调的“连接函数”，需要 UI/浏览器对象状态。下一步：构造完整表项 + 用模拟点击走原生服务器浏览/连接路径，而不是冷调入口。

## 2026-10-21 大厅截图在 12 秒时仍是黑屏

启动社区离线客户端 12 秒后 `capture_screen` 得到全黑 1920x1080，说明 CEF/大厅还没渲染或窗口被遮；此时无法可靠模拟点击。下一步：等到 20–25 秒再截图，确认 UI 出现后用 Win32 `SetCursorPos`/`SendInput` 模拟点击“多人竞技/服务器浏览”，并同时抓 28969 的 UDP 包；不再冷调入口。

## 2026-10-21 UI 自动化成功进入 PVP/靶场对话框

25 秒截图确认大厅已渲染（PVP/勇者/闯关/PVE 四卡）；用 `SetCursorPos`+`mouse_event` 点击“多人竞技(PVP)”后显示“未找到房间”；再点“自定义/训练”区域弹出靶场对话框，含“取消/进入靶场”按钮。随后客户端因 60 秒观察窗口结束而退出，未确认“进入靶场”是否加载地图。下一步：把观察窗口延长到 120 秒，按同一坐标点击“进入靶场”，观察是否进入本地靶场/地图，并抓 28969 与服务端日志。

## 2026-10-21 模拟点击进入靶场被“服务器繁忙”拦截

120 秒窗口下，前台点击“多人竞技(PVP)”→“训练”→“进入靶场”，客户端弹出“服务器繁忙中，请稍候重试”，没有发 UDP 到 28969，也没有加载地图。说明靶场/训练不是本地模式，仍走匹配服务；UI 点击路线无法绕过网络。下一步转“自定义房间/服务器浏览”或原生连接入口，不再把训练当本地入口。

## 2026-10-21 模拟点击成功创建并进入自定义房间

前台点击 PVP→自定义→创建房间，客户端进入房间界面：`迷你战争/战术团队竞技`、时间 10:00、得分 75、血量 100、1/12，底部有“返回大厅/准备”。这是第一次真正进入可开局房间，但仍未向 28969 发包。随后点击“准备”，按钮仍显示“准备”，未开始游戏。下一步：尝试房间内“开始游戏”控件/键盘 Enter/房主开始路径，或在房间有效后用包装层 `--room-command` 触发原房间 startgame，再观察是否本地加载地图。

## 2026-10-21 自定义房间“高级选项”里发现 AI 开关

模拟点击进入自定义房间后，点“高级选项”打开对话框，字段包括时间/得分/重生/血量/友军伤害/旁观/阵亡回放/只能爆头/**AI开关（关闭）**/开始时限制武器/真实模式，底部“取消/恢复默认/应用”。这说明 1649370 原生支持本地 AI bot，只差正确开启并开始游戏。当前 120 秒观察窗口在尝试切换 AI 时结束；下次用更长窗口（180s），点击 AI 行/箭头并用键盘 Right/Enter 切换为“打开”，点“应用”，再回房间点“准备/开始”，观察是否本地加载地图。

## 2026-10-21 AI 开关可见但鼠标点击不切换

在 180 秒窗口内再次进入自定义房间→高级选项，对“AI开关（关闭）”分别点击值文本 (1235,894)、左图标 (1208,894)、右图标 (1259,894)，以及标签+键盘 Right，值始终仍为“关闭”。说明它可能是模式相关/禁用项（战术团队竞技不允许 AI），或需要组合框 Tab 焦点/键盘而非鼠标。下一步：创建个人竞技/机械公敌等模式房间再试 AI 开关，或用 Tab 遍历焦点 + Up/Down/Enter；不再重复同一坐标。

## 2026-10-21 AI 开关已成功切到“打开”，但房间“准备”仍不开始

用户手动点击后，高级选项显示 `AI开关 = 打开`；关闭对话框后房间地图变为化学工厂，说明设置已应用。随后点击“准备”多次（(1843,1051)），按钮仍显示“准备”，没有加载地图、28969 无包。下一步：房间内找“开始游戏”控件/键盘 Enter，或用主线程调用 `room.startgame`（`0x6398A0`）/`0x62FAF4` 触发开局。AI 开关本身已确认可用，这是本地 bot 对战的关键前置。

## 2026-10-21 双击“准备”后出现黑屏加载态（CPU 69、WS 1.2GB）

进入自定义房间（地图核弹小镇）后，`--room-command room.startgame` 注入成功（`room-command.json` status=queued、length 0→16、room 0x23D978B8），再双击“准备”，窗口立即变黑，进程存活、CPU 持续上升、工作集 1.2GB，10–30 秒仍未出现画面。结合房间地图是“核弹小镇”（`mp_nuked`），而我们目前只提取了 `mp_cross_fire`/`mp_hardhat_sh` 的原生 fastfile，黑屏很可能是缺失 `mp_nuked` 地图资产导致加载卡住，不是网络问题。用户确认：AI bot 本来就不会出现在 lobby、只在对局内出现。下一步：把房间地图改成已提取的交叉火力，或从 `ff_init_mp_nuked_V74.ifs`/`lf_init_mp_nuked_V8.ifs` 提取 `mp_nuked` 后再开局。

## 2026-10-21 补上 mp_nuked 资产后仍黑屏

从 `ff_init_mp_nuked_V74.ifs` 提取出 `mp_nuked.ff`（22,946,069）、`mp_nuked_load.ff`（24,853）、`mp_nuked_const.ff`（49,429），签名/哈希校验通过；给包装层加 `--map-probe mp_nuked_native` 并重新进入“核弹小镇”自定义房间，双击“准备”后仍然黑屏（CPU 56、WS 1.2GB）。说明黑屏不只是缺 nuked 地图资产，更像客户端在等服务器 gamestate / 本地对局初始化。下一步：改用已提取的“交叉火力”地图做对照（排除地图本身），并把我们的 gamestate/服务端接到客户端连接状态机。

## 2026-10-21 交叉火力对照被 UI 点击抖动挡住；lf_init_mp_nuked_V8.ifs 不是 v461 fastfile

为排除 nuked 地图资产问题，尝试用 `--map-probe mp_cross_fire_native` 重新进房间做对照，但这次 `SetForegroundWindow`/`mouse_event` 点击 PVP/自定义未生效，停留在主大厅；同时 `lf_init_mp_nuked_V8.ifs` 用提取工具报 `name/magic count mismatch 101 != 0`，说明它不是同一种签名 fastfile 容器（可能是 loose/流式资源）。下一步：改用固定的房间配置/表项直接指定地图，减少 UI 点击；并给 nuked 黑屏更长等待（60–90s）确认是否只是加载慢。

## 2026-10-21 UI 点击已稳定：悬停 1.2s 后再点；但点地图下拉立刻黑屏

确认 `SetCursorPos` 后必须等待约 1.2 秒让游戏更新 hover，再 `mouse_event` 才能稳定点中（本轮成功点开 PVP→自定义→创建房间）。进入房间后地图是“北境中转站”，点击左上地图下拉 (370,200) 后窗口立即黑屏，CPU 88、WS 1.2GB，等待 60 秒仍未恢复，最终客户端在观察窗口结束时退出。说明换未提取地图会走同一条黑屏加载路径；下一步只选择已提取的“交叉火力”，或先补目标地图资产再换图。

## 2026-10-21 地图缩略图可选，但该房间池里没有交叉火力

自定义创建页的三张地图缩略图可点选（点击右侧第二张后预览从“北境中转站”切到乡下农庄，文案“大型地图。乡下农庄…”），但该池只有办公室/乡下农庄/工业图，没有交叉火力；第三张点击未改变选择。说明换图必须补对应地图资产，不能指望池里出现已有地图。下一步：优先提取房间池实际出现的 mp_nuked/乡下农庄/北境中转站等 fastfile，或批量提取 ff_init_mp_* 后再进图。

## 2026-10-21 房间地图是随机池，单张 map-probe 对不上

又提取了 `mp_overgrown`（乡下农庄）和 `mp_afghan`（荒漠边陲）并加进包装层，但重新创建房间时地图变成夜色泥沼，与已 staged 的地图不一致。说明自定义房间每次从地图池随机抽图，单张 `--map-probe` 不可控。下一步：一次性提取并 stage 所有 `ff_init_mp_*` 地图（约 37 张），或找到房间对象的地图字段直接固定成已准备的地图。

## 2026-10-21 全地图池 106 个 ff 已 staged，房间仍不开始——确认不是地图问题

批量提取 37 个 `ff_init_mp_*` 包，得到 106 个 `.ff`（含 load/const），用 `CODOL_MAP_DIR` 全部铺进运行时；进自定义房间（地图公寓楼）后，单击/双击“准备”和 Enter 都没有触发开局，房间保持 1/12、无黑屏、无 28969 包。结论：地图资产不是阻断点，阻断在房间 ready/start 的状态机。反汇编 `0x6398A0` 确认它是按 `[0x3306910]` 当前 playlist 走快速匹配/party start 的入口（`vtable+0x3c`），不是本地房间 ready；下一步从底层找 ready 按钮真正调用的 party/lobby 命令与房间状态字段，而不是继续换图/重试 UI。

## 2026-10-21 按“绕过房间直接进图”尝试：map/devmap Cbuf 无效，原生 0x4F3890 直调崩溃

按用户提示不走房间接口，先用 `--cbuf-command "map mp_cross_fire"`，再用 `"devmap mp_cross_fire"`（`--map-command-mode none`）注入，客户端都停在大厅，没进图；随后按 `0x4F8B20` 命令处理里的调用形态，直调 `0x4F3890(map,0,0)`（经 `0x4F2DE0`），进程立即退出/窗口消失，说明该调用还需要命令上下文或正确的 this/ret 约定。下一步：反汇编 `0x4F8B20`/`0x4F2DE0` 确认 `devmap` 命令真正调用的入口与参数，再用正确约定调用；不再盲调。

## 2026-10-21 0x4F2DE0 调用约定已逆清，但远程线程直调仍崩溃；queue devmap 也无效

`0x4F2DE0` 是“按 `;`/换行拆分字符串，再 `func(arg0,arg1,chunk)`”的包装，`ecx=func`、`[ebp+0x10]=字符串`、`[ebp+8]/[ebp+0xC]=参数`。按此把 map 字符串放到 `[ebp+0x10]` 重试，进程仍立即退出；`--map-command-mode queue` 的 `switchtomainmenu;devmap mp_cross_fire` 也只是回大厅，没有进图。说明它必须在主线程/命令上下文中调用，远程线程不行；下一步在主线程的 Cbuf/命令执行点 hook，注入 `devmap mp_cross_fire`，而不是远程线程裸调。

## 2026-10-21 主线程 cave 调 0x4F2DE0→0x4F3890 不崩但也没进图

给包装层加 `CODOL_MAIN_MAP`：在主线程暂停窗口分配 RWX cave，执行 `pushad; push "mp_cross_fire"; push 0; push 0; mov ecx,0x4F3890; call 0x4F2DE0; add esp,0xC; popad; ret`。结果进程存活、窗口正常、仍在大厅，没有黑屏/无包。说明这次调用没有崩，但发生在主菜单之前，地图队列没有立刻切换；下一步把同一 cave 调用挪到主菜单之后/房间有效时，并补 `map_restart` 或 `0x4F7DA0` 的立即加载路径。

## 2026-10-21 主线程 cave 追加 0x4F7DA0 仍无效；room-command devmap 只入队不执行

主线程 cave 在 `0x4F2DE0→0x4F3890` 后再调 `0x4F7DA0`，进程仍正常但停大厅；改用 `--room-command "devmap mp_cross_fire"`，`room-command.json` 显示 `status=queued`、`length 0→22`、room `0x245C79B0`，但房间界面不变、无地图加载。说明房间命令缓冲区 `0x33821B0` 只是入队，消费点在主线程别处。下一步：找 `0x76595A4`/`0x33821B0` 的消费者（Cbuf 执行点），在主线程 hook 后执行队列，而不是只写入。

## 2026-10-21 找到命令缓冲消费者 0x4F2EC0/0x4F3080；远程执行队列崩溃

`0x4F2EC0` 按行拆分 `0x76595A4` 描述符并直接 `call 0x4F3890(line)`，是真正执行 Cbuf 的函数；`0x4F3080` 是它的包装（先 `0x4F2FF0` flush，再 `0x4F2EC0(descriptor,arg)`）。在 `--room-command "devmap mp_cross_fire"` 已入队（length 22）后，用远程线程调 `0x4F3080`，客户端立即退出/窗口消失，说明 Cbuf 执行也必须在主线程。下一步：把 `0x4F3080` 调用嵌进 room-command 注入器的主线程暂停窗口（写队列后、ResumeThread 前设 EIP），再让它自己执行 devmap。

## 2026-10-21 Cbuf 执行终于进入命令处理，但在 0xA3942A 崩溃

修正两个错误后——`0x4F2EC0` 的 `[ebp+8]` 是缓冲区索引（eax=0，不是 `0x76595A4`），以及 cave 里 `call` 相对偏移（`call_next=cave+10`）——主线程 cave 执行 `push 0; xor eax,eax; call 0x4F3080`，`devmap mp_cross_fire` 不再停在队列，而是进入命令解析后在 `0xA3942A`（`mov ebx,[eax+0x40]`，eax 指向损坏字符串）访问冲突。说明 Cbuf 执行已经打通，剩下是命令字符串/参数或 `devmap` 上下文。下一步改 `map mp_cross_fire`、补 `sv_cheats 1`，或修正注入文本的前导换行。

## 2026-10-21 0x4F30C0 是真正的命令执行器，主线程执行 devmap 已触发地图加载

主线程 cave 执行 `push 0; push 0; mov eax,"devmap mp_cross_fire"; call 0x4F30C0; add esp,8`，`room-command.json` 的 `exec_cmd.status=armed`，客户端不再崩溃，而是进入黑屏地图加载态（CPU 52→61、WS 1.2GB、进程 Responding），持续 50 秒仍黑屏。说明命令注入到 devmap 的路径已经打通；黑屏是地图加载/等待 gamestate，不再是命令或崩溃问题。下一步：等更久，或在 devmap 后再执行 map_restart/sv_ 初始化，确认地图能否真正进入并可加 bot。

## 2026-10-21 devmap;map_restart 仍黑屏，线程全部 Wait/UserRequest

命令执行器 `0x4F30C0` 执行 `devmap mp_cross_fire;map_restart`（`exec_cmd.status=armed`），客户端不再崩溃，黑屏、CPU 44、WS 1.2GB；`Get-Process Threads` 显示主/渲染线程均 `Wait:UserRequest`，没有异常退出。说明地图加载阶段在等某个用户态事件/服务器状态，而不是崩溃或命令失败。下一步：用转储/ETW/线程栈确认等待对象，或补本地 gamestate/`sv_` 初始化让加载完成。

## 2026-10-21 黑屏全内存转储已抓到，CDB 只显示 Wow64 等待栈

`devmap` 黑屏后写 `runs/20261021-1649370-dump132.dmp`（进程 uptime 67s），CDB 离线加载显示各线程停在 `wow64!whNtWaitForWorkViaWorkerFactory` / `WaitForMultipleObjects`，主线程也是 Wow64 等待；`!wow64exts.sw` 加载扩展时挂起超过 120 秒，已终止。说明黑屏是用户态等待，下一步需要把 dump 的 32 位 CONTEXT 解出来（自写 minidump 解析/StackWalk64，或本地扩展路径）而不是依赖在线扩展。

## 2026-10-21 minidump 解析器写好，但线程上下文是 AMD64 而不是 x86

`parse_minidump_threads.py` 能读 Memory64List/ThreadList，dump 有 1028 个内存区间；线程 `ThreadContext` 大小 3263、`ContextFlags=0x10005F`（AMD64），`Rip/Rsp` 是 wow64 栈，不是游戏 32 位 `Eip/Esp`。所以离线栈还没展开到游戏代码。下一步改用活进程对每个线程 `OpenThread + Wow64GetThreadContext` 直接取 32 位 CONTEXT（不依赖 dump 的 64 位上下文），再按 EBP/栈扫描定位黑屏等待点。

## 2026-10-21 活进程 32 位线程栈已抓到：主线程在正常帧循环 Sleep(1)，不是死锁

`dump_threads32_live.py` 用 `Wow64GetThreadContext` 取到主线程 TID 6768 `EIP=76F4858C`（ntdll 等待），EBP 链回到 `0x4FE37E`（`0x4FE220` 客户端帧循环里的 `Sleep(1)`），再上 `0x4FEA95`、`0x77FA69`（`0x77FA04` 主循环）、`0xC42788`；其余线程在 `0x67CBAE`/`0x67C6BD`/`0x49F32D` 等 worker。说明黑屏时游戏主循环仍在跑，地图/世界没有完成初始化，不是死锁。下一步：从这些 worker 和地图加载状态全局变量定位“地图请求已入队但未完成”的原因。

## 2026-10-21 worker 反汇编：0x67CBA0 是 1ms 事件等待，0x49F32D 是线程退出/错误路径

黑屏时主线程正常 `Sleep(1)` 帧循环；worker `0x67CBA0` 对 `[0x7886BBC]` 句柄调用 `WaitForSingleObject(...,1)`，`0x67C6BD` 只是线程 proc 返回后的 `add esp,4`；`0x49F32D` 走 `0x66D930`（字符串 `0xDCA224`）后发事件，像线程退出/错误清理。说明没有线程卡在加载函数里；下一步直接读地图/世界状态全局（`0x35053DC`、`0x766A20C`、`0x7886BBC`）判断地图请求是否被消费。

## 2026-10-21 黑屏时地图状态全局：0x3306910=-1、0x35053DC=0、队列空

`read_map_state.py` 读到当前地图索引 `0x3306910=0xFFFFFFFF`、地图/世界状态 `0x35053DC=0`、地图队列 `0x76661A8/AC=0`、地图数 `0x33E9990=5`；`0x33821B0` 房间缓冲里是 `roomChatChannelID 0;...`，不是我们的 `devmap`。说明 `0x4F30C0` 这次调用没有真正应用命令/地图请求没有入队，黑屏不是地图已加载。下一步先用无害命令（如 echo/map_restart）验证 `0x4F30C0` 的返回和副作用，再决定调用约定/主线程时机。

## 2026-10-21 直调 0x4F3890 已不崩，但地图状态仍不变

修正 cave 参数为 `push map; push 0; push map`（同时填 `[ebp+8]` 和 `[ebp+0x10]`）及 `call` 偏移 `+18` 后，房间内主线程直调 `0x4F3890` 安全返回、客户端存活；但 `0x3306910` 仍 `-1`、`0x35053DC=0`、地图队列仍 0。说明 `0x4F3890` 需要更多全局/playlist 上下文，或它只是“请求入队”而非立即加载。下一步读它的返回值/关键全局，或改调真正消费地图请求的 `0x4F7DA0`/`0x67...` worker 路径。

## 2026-10-21 修正 CONTEXT 标志后房间 ready 真正执行，崩溃点从空 ECX 移到堆地址

`_main_thread_call` 原来 `ContextFlags=0x10001` 只带 CONTROL，`ECX` 没被写入；改成 `0x10003`（CONTROL|INTEGER）后，`CODOL_ROOM_READY` 调 `0x62F840(ecx=room)` 不再在 `0x62F85A`（`[ebx+0x278]`，ebx=0）崩，而是在 `0x21A0A000` 堆地址访问冲突。说明 ready 方法已进入真实逻辑（读房间/发消息），下一步反汇编 `0x62F840` 的堆访问/发送路径，补有效房间字段或 stub 掉离线失败分支。

## 2026-10-21 0x62F840(1,0,0) 主线程执行成功，进入黑屏开局等待

修正 CONTEXT_INTEGER 后，用 cave `push 1; push 0; push 0; call 0x62F840`（ECX=room）调用房间开始方法，不再崩溃；客户端黑屏、CPU 52、WS 1.2GB，地图索引仍 -1，`roomstart139-server` 无 UDP。说明 ready/start 方法已真正执行到“开始对局”路径，黑屏是等服务器 gamestate/加载完成。下一步：给本地连接注入 gamestate，或 patch 掉等待服务器的加载门槛。

## 2026-10-21 0x62F840 的 arg0=0/1 都黑屏，怀疑注入点不在安全帧边界

用 cave `push 0/1; push 0; push 0; call 0x62F840`（ecx=room）分别执行，均无崩溃、黑屏、CPU 53、WS 1.2GB、无 UDP；地图索引仍 -1。`original_eip` 落在 `0x945D00`/`0x9F40FE` 一带，可能是在 UI/渲染重入区改了主线程上下文，导致黑屏而非真正开局。下一步：把调用挂到客户端帧边界（`0x4FE220` 入口）做 one-shot hook，而不是在任意 EIP 直接切上下文。

## 2026-10-21 帧边界 hook 已稳定：0x4FE220 13 字节 trampoline 不崩，但地图仍不加载

在 `0x4FE220` 入口写 `E9` 跳 cave，cave 只执行一次 `push map; push 0; push map; call 0x4F3890`，再执行原 13 字节并跳回 `0x4FE22D`。客户端存活、无崩溃、房间界面正常；`0x3306910` 仍 `-1`、地图队列仍 0。说明帧边界安全，但 `0x4F3890` 仍因 playlist 计数为 0 提前返回。下一步在 cave 里先写 `[0x3306994]=1` 再调用，或改调 `0x62F840`（ready/start）在帧边界执行。

## 2026-10-21 帧 hook 已执行（flag=1、playlist 计数=1），但 0x4F3890 仍回滚到 -1

读内存确认 `0x4FE220` patch 为 `E9 DB 1D 36 11`，cave 标志 `0x11860800=1`，`0x3306994=1`；但 `0x3306910` 仍 `-1`、地图队列 0。说明 `0x4F3890` 被调用了，但在 `0x4F38C0` 的 playlist 检查/后续失败分支里回滚。下一步读 `0x33069D4` 的 playlist 地图指针/名称，补成 `mp_cross_fire` 或直接跳过失败分支。

## 2026-10-21 跳过 playlist-zero 失败分支后仍不加载

在帧 hook 里把 `0x4F38C8` 的 `je` 改成 `90*6`，并写 `[0x3306994]=1`，cave 仍执行 `0x4F3890(map,0,map)`；结果无崩溃、客户端存活，但 `0x3306910` 仍 `-1`、队列仍 0。说明 `0x4F3890` 要么没有真正执行到队列插入，要么在更早分支返回；下一步要在 cave 里读 `0x3306910`/返回值，或用硬件断点确认调用是否命中，而不是继续盲试。

## 2026-10-21 0x4F3890 确认命中并返回 -1

帧 hook cave 在 call 后写 `eax` 到 `cave+0x904`，读到 `0xFFFFFFFF`，同时 flag=1、`[0x3306994]=1`，客户端不崩。说明函数确实执行，但在 playlist/地图名查找分支返回 -1，跳过 `0x4F38C8` 的 je 也没用，失败点更早或在后续 lookup。下一步沿 `0x4F3890` 的 `-1` 返回路径（`0x4F39B1` 起）找出具体失败条件，或直接用房间实际地图名/记录而不是 `mp_cross_fire`。

## 2026-10-21 0x4F3890 的 -1 路径定位到地图校验 0x66C1D0

反汇编 `0x4F3960`–`0x4F39E0` 显示，成功路径在 `0x4F3964` 把 map 记录挂到 `[0x33303B0]` 链表；`0x4F3980` 若 `[eax+8]==0` 跳到 `0x4F39B1`，调用 `0x66C1D0`，返回 0 就 `je 0x4F3A04` 失败。我们的 `mp_cross_fire` 在这里被判无效，所以返回 -1。下一步反汇编 `0x66C1D0` 看它检查什么（文件/zone 列表/地图白名单），再补对应条件或换成房间实际地图名。

## 2026-10-21 0x66C1D0 已反汇编：按 0x33069D4 map 记录做检查

它按 `[0x3306910]`/`[0x3306994]` 取 `[0x33069D4]` 的 map 记录，再调 `0x76F190` 做文件/名称检查；在 `0x66C212` 强制跳成功（`75->EB`）后，帧 hook 仍得到 `0x3306910=-1`、队列 0。说明失败点不只在 `0x66C1D0` 的返回值，`[0x33069D4]` 记录本身/后续挂链表路径也没通过。下一步需要构造 `0x33069D4` 的合法 map 记录，或直接用房间实际地图记录，而不是只 patch 校验跳转。

## 2026-10-21 0x33069D4 不是地图记录，而是命令字符串数组

扫描房间对象和 `0x33069D4` 后，`0x33069D4[0..2]` 指向 `profile_menuDvarsSetup`/`lerp_bone` 等 Cvar 字符串，不是 map record；房间对象 0x40000 字节内也没有 `mp_` 地图名。说明之前“构造 playlist map 记录”的方向基于错误全局。下一步改走 `--inject-gamestate`/本地服务端，或重新找真正保存房间地图的字段（从 UI 地图下拉的写入点反向），不再改 `0x33069D4`。

## 2026-10-21 试跑 2.6.9.7 dedrun 本地 bot 服务端，卡在 IPv4 bind

按 `runs/2697-server-test/cmd.json` 启动 `codol_dedrun.exe`（mp_cross_fire、12 bots、net_ip 127.0.0.1/net_port 28969），进程存活但 `sys_error.txt` 报 `Sys_Error: Could not bind to a IPv4 network socket`，`Get-NetUDPEndpoint`/netstat 均无 28969 监听；改成 `net_ip 0.0.0.0` 仍同样失败。说明 dedrun 的 socket 初始化/绑定路径有问题，暂时不能作为 1649370 的本地 bot 服务端。下一步换端口、去掉 net_ip、或用 2.6.9.7 客户端先验证 dedrun 本身可连。

## 2026-10-21 2.6.9.7 dedrun 参数试错：bind/archive 二选一失败

完整 `cmd.json` + `net_ip 127.0.0.1`/`0.0.0.0` → `Could not bind to a IPv4 network socket`；去掉 `net_ip` 或改空串 → `CoDOL startup archive loading failed`；改 `net_ip 192.168.10.108`/换端口也回到 archive 失败。说明 dedrun 对参数顺序/`net_ip` 与资源根很敏感，当前命令行不能同时满足 bind 和 archive。下一步用 2.6.9.7 客户端验证 dedrun 本身，或从 dedrun 的 `Sys_Error` xref 找 bind 失败条件。

## 2026-10-21 dedrun：去掉 net_port 可 bind（17733），但 archive 加载失败

保留 `net_ip 127.0.0.1`、删掉 `+set net_port` 后，dedrun 绑到默认 17733（`Get-NetUDPEndpoint` 可见），但 `sys_error.txt` 变成 `CoDOL startup archive loading failed`；`net_port 0` 同样绑 17733、archive 失败。说明 bind 失败与 `net_port` 参数强相关，而 archive 失败是另一条路径（资源/启动参数）。下一步从 dedrun 的 `Sys_Error` 字符串 xref 找 archive 失败条件，或改用 `server.cfg` 而不是命令行。

## 2026-10-21 2.6.9.7 增强启动器里找到现成本地 bot 房间实现

`launch_backend_enhanced.py` 用 `client_room2697.dll` + `run_room_match2697` 自动起本地 bot 对局，`gameplay-settings.json` 里 bot_count/bot_difficulty/score_limit 都可配；它通过 `client_room2697.dll` 注入房间逻辑，正是 1649370 缺的“房间 ready/start + bot”参考。下一步先跑一次 2.6.9.7 增强版对局，抓 room-bridge 的命令/字段，再把同样模式移植到 1649370（不直接加载 2697 DLL，避免 ABI 问题）。

## 2026-10-21 2697 房间 DLL 里逆出 room-bridge 协议线索

`client_room2697_enhanced.dll` 含 `room-ready.txt`、`room_ready sequence=%u map=%s`、`room_start requested in_room=%d ready=%u sequence=%u ds=%d index=%d`、`room_change requested map=%s ready=%u`、`room_ready_set value=%u`、`local-room-options.txt`（`%15s %u %63s`）和 `udp:127.0.0.1:28969`。说明 2697 的本地房间是通过 UDP 127.0.0.1:28969 的 room backend 收发 `room_ready/room_start/room_change`，这正是 1649370 房间 ready 当前缺的后端。下一步跑一次 2697 增强对局抓 UDP 包，按 `room_ready/room_start` 格式给 1649370 补本地 room backend。

## 2026-10-21 2.6.9.7 增强启动器 stage-check 通过

正确游戏目录是 `E:\GAME\COD\codol-airedux\2.6.9.7\使命召唤Online`；系统 Python 3.14 缺 `cryptography`，改用启动器自带 `runtime\python\python.exe` 后 `--stage-check` 输出 `STAGE_OK`，并显示“团队竞技上限 200，时长 30 分钟，BOT veteran”。说明参考本地 bot 房间的 staging 链路可用。下一步实际启动一次，读 `room-ready.txt`/`local-room-options.txt` 或抓 28969 的 room_ready/room_start 包，再移植到 1649370。

## 2026-10-21 2697 增强对局实际启动失败：OSError 1346 模拟级别

`stage-check` 通过，但实际 `launch_backend_enhanced.py` 报 `client_error=OSError(22, '未提供所需的模拟级别，或提供的模拟级别无效。', None, 1346)`，客户端未起来、无 `room_events`。说明启动器的身份/令牌模拟步骤在当前非高完整性进程里失败；下一步用高完整性/管理员启动该 Python，或绕过 `launcher_identity2697` 的模拟调用，再抓 room-ready/28969 包。

## 2026-10-21 参考对局仍被 1346/UAC 挡住

`Start-Process -Verb RunAs` 启动启动器后进程立即消失（UAC 未交互/被策略拒绝），没有客户端、没有 room 事件；非提升启动仍是 `OSError 1346`。说明当前会话拿不到参考对局的模拟级别。下一步不再依赖参考启动器，直接在 1649370 侧补 room backend（按已抓到的 `room_ready/room_start` 字符串格式），或改用 1649370 自己的 wrapper 令牌路径启动参考客户端。

## 2026-10-21 确认 1649370 侧没有现成 dedicated server 二进制

递归搜 `1649370` 和 `使命召唤OL` 的 `*ded*` 只命中贴图/资源名，没有 `codol_dedrun.exe` 一类服务端；2.6.9.7 的 dedrun/增强启动器又被 1346/UAC 挡住。因此 1649370 本地 bot 对局必须自己补 room backend（按 `room_ready/room_start/room_change` 文本/UDP 协议）或把 1649370 客户端接到一个可用的本地服务端。下一步先实现最小 room backend：监听 28969，记录并回应 room_ready/room_start，再用帧 hook 触发 0x62F840 观察它是否发包。

## 2026-10-21 room backend 监听 28969，触发 0x62F840 后零 UDP/TCP 包

`room_backend_1649370.py` 同时监听 UDP/TCP 28969 并回复 `room_ready`；帧/房间注入执行 `0x62F840(0,0,0)` 后日志只有 `listening`，没有客户端连接/数据报。说明 1649370 的房间开始不是通过 28969 网络，而是本地 frontend/channel 对象；之前黑屏是本地开始路径缺上下文。下一步反汇编 `0x62F840` 的 `0x631E90`/`0x632070`/`0x62F6F0` 调用，找它依赖的本地 channel/room 对象字段。

## 2026-10-21 反汇编 0x631E90/0x632070/0x62F6F0：开始路径依赖 room 的 +0x105F0 配置、+0x105FC 模式/地图字节、+0x1061C 队伍/槽位、+0xE360 索引

`0x631E90` 用 `[edi+0x105FC]` 查 `0x761740` 表并拼 `[eax*0x3E24+0x7B25A40]` 记录；`0x632070` 读 `[edi+0x105F0]` 的 `0xDB6AA0` 配置并检查 `[0x82E1363]`；`0x62F6F0` 把 `[edi+0x168/0x16C/0x170]` 复制到 `esi+0x3A048/0x3A04C/0x3A050`。黑屏说明这些 room 字段在离线房间里没被初始化到可用值（尤其 `+0x105FC`/`+0x1061C`）。下一步读这些字段的实际值，按合法 map/mode 初始化后再调 `0x62F840`。

## 2026-10-21 按 room 字段初始化后仍黑屏

在 room-command 注入器里写 `[room+0xE360]=0`、`[room+0x105FC]=0`、`[room+0x1061C]=0`、`[room+0x105D8]=1`、`[room+0x170]="mp_cross_fire"`（长度 13），再调 `0x62F840(0,0,0)`；结果仍黑屏、CPU 51、WS 1.2GB，`0x3306910=-1`、`0x3306994=0`（计数被清回 0）。说明仅这些字段不够，开始路径还会清计数/等另一对象。下一步在字段初始化后先读 `+0x105F0` 配置/`0x631E90` 的返回值，或补 `[room+0x105F0]` 的表项。

## 2026-10-21 room 字段已写入，客户端仍黑屏后在 0x945CEB 崩溃

注入器确认写了 `0xE360=0`、`0x105FC` 低字节 0、`0x1061C=0`、`0x170="mp_cross_fire"`，`read_room_fields` 也读回正确值；但客户端从黑屏转为 `0xC0000005 @ 0x945CEB`（UI/渲染区），不是地图加载成功。说明开始路径在字段就绪后进入了另一条 UI/渲染分支并崩，仍缺前置对象。下一步用线程栈/转储确认 `0x945CEB` 的调用者，或先不调 `0x62F840`，只让游戏自己消费 room 字段。

## 2026-10-21 0x945CEB 是容器查找 mov esi,[ecx]，说明调用者传了无效 this

反汇编 `0x945CE0` 是通用容器/数组查找（`ecx+0/4/8` 判断 + `[eax*32+...+8]`），崩溃在 `0x945CEB` 的 `mov esi,[ecx]`；我们的 room 字段初始化让开始路径走进这条查找，但传入的 container 指针无效。下一步从崩溃线程栈找 `0x945CE0` 的调用者，确认它查的是哪个 room/UI 容器，再补该对象或跳过该查找。

## 2026-10-21 阶段性重估：社区离线客户端的房间/地图直调路线仍未打通

已确认：AI 开关存在、`0x62F840` 是房间 ready/start、`0x4F3890` 是地图加载、`0x4F30C0` 是命令执行、帧边界 hook 可安全调用；但字段初始化后仍在 `0x945CEB` 的容器查找崩溃，地图索引始终 -1，28969 无包。继续盲补 room 字段收益很低。更高成功率的路线转为**全客户端 + TP 绕过**：全客户端原生就有 bot 菜单/房间/退大厅，卡点只在 TP（1045/19002）；允许驱动后可做内核级隐藏/用户态 patch，比在社区离线客户端里重建 room 状态机更接近目标。下一步重开 TP 路径（驱动/ETW 抓判定 + 用户态 patch），同时保留 room 字段线作为备选。

## 2026-10-21 全客户端重检：进程到 12 秒仍活，出现隐藏的 GbLoginClass 登录窗 + TCP 36.131.222.111:443，随后退出

`launch_synthetic_tcls.py --mode tgp-sign --allow-any` 的 evidence 显示 `windows=[{class:"GbLoginClass", visible:false}, {class:"IME"}]`，无 CODO 游戏窗；sample 12.2s 后 `alive:false, exit_code:0`，owned pids 被终止。说明全客户端不是完全没窗口，而是停在登录/TP 前置窗（隐藏），之后退出。下一步把 `GbLoginClass` 显示出来并定位退出原因（TP 1045/19002 或登录），再决定 patch 点。

## 2026-10-21 全客户端约 9 秒内静默退出，只有隐藏 GbLoginClass/IME，无 TCP

第二次 TCLS 重检 evidence 的 sample 在 `elapsed_ms=9153` 时 `alive:false, exit_code:0`，窗口仍是隐藏的 GbLoginClass + IME，`tcp=[]`，没有 CODO 游戏窗。说明这次客户端在登录/TP 前置阶段就退出，没进入网络。下一步用 ETW/进程审计抓退出前的最后模块/线程，或从 GbLoginClass 的 WndProc/TP 初始化处 patch 退出分支；不再重复同参数启动。

## 2026-10-21 全客户端静默退出仍缺可观测原因

隐藏 GbLoginClass、9 秒 exit_code=0、无 TCP；`--dismiss-dialogs` 可能把 TP 警告点掉后客户端直接退出，也可能是 TCLS 未被消费。下一步不再盲启，先用 ETW（Microsoft-Windows-Kernel-Process / Image Load / TCPIP）记录一次启动，抓退出前最后加载的模块/线程和是否有 TP 模块（TGuard/tpsvc/TASLogin）活动；再按模块定位 patch 点。

## 2026-10-21 WPR/ETW 抓到全客户端启动，CSV 里出现 TP 痕迹

`wpr -start GeneralProfile` 下启动全客户端后停止，ETL 359,661,568 字节（drop 22889 事件），`tracerpt` 转 CSV 1.36GB。grep 到 `%TEMP%\tenprotect_id_52.tmp`、`TGuard`/`TenProtect`/`TP` 目录、`sstpsvc.dll` 等；说明 TP 在启动阶段确实活动。下一步从 CSV 里按 `codoMP_client_shipRetail.exe` 的 PID 过滤 Image/Process 事件，取退出前最后加载的模块和 TP 模块时间线，再定位 patch 点（不再盲启）。

## 2026-10-21 ETW 证据里找到 TP3Helper：可见 #32770 对话框 + 隐藏 GDI+ Window (TP3Helper.exe)

`full-etw.json` 在 1 秒时 owned pids `[31296,26432]`，26432 有：可见 `#32770`，标题空；隐藏 `GDI+ Hook Window Class`，标题是 `GDI+ Window (TP3Helper.exe)`；`MSCTFIME UI`/`IME`。说明全客户端启动时 TP 由 TP3Helper.exe 接管并弹一个无标题对话框；`--dismiss-dialogs` 点掉后客户端 9 秒静默退出。下一步抓 TP3Helper 的命令行/对话框文本/父进程，确它是“检测到调试/注入→通知客户端退出”，再决定 patch TP3Helper 或跳过其对话框。

## 2026-10-21 TP3Helper 命令行是 TP3Helper.exe 5000，父进程为客户端

轮询记录到 `pid=36848 ppid=23924 cmd="E:\GAME\COD\使命召唤OL\TP3Helper.exe 5000"`，在整个 20 秒观察窗口内持续存活；观察结束后与父进程一起退出。参数 `5000` 很可能是超时/等待毫秒，TP3Helper 更像看门狗/辅助进程，不是主 TP 判定。下一步在它存活时枚举其 `#32770` 子控件文本（按钮/静态文本）和父进程命令行，确认它弹的是“警告/退出”还是普通登录提示。

## 2026-10-21 全客户端退出根因确认：TCLS 启动器检查未通过

TP3Helper/#32770 对话框的子控件文本是：“请使用腾讯游戏登录器(TCLS文件夹内的Client.exe)启动游戏。”所以 `--dismiss-dialogs` 点的是这个“非 TCLS 启动”警告，不是 TP 1045；合成 TCLS mapping 不被接受。真实 `TCLS\Client.exe` 存在（955,592 字节），但单独启动后立即退出、无窗口/日志，说明它还依赖登录/目录服务。下一步跑 TCLS\Client.exe 带参数/日志或反查这条提示的检查点，让客户端接受我们的启动方式，再谈 TP。

## 2026-10-21 TCLS Client.exe -src=tgp 也立即 exit 0，无子进程

`Start-Process` 后 5 秒 `HasExited=True, ExitCode=0`，系统里没有 `codo`/`TAS` 子进程；`TCLS\config\dirserverdynamic.ini` 只有 `successfulserverid=1/port=8080`，`versionserverconfigdynamic.ini` 只有 `id=1/port=8001`，没有主机名。说明 TCLS Client 依赖它自己的目录/登录服务发现，离线单启不会拉起游戏。下一步反查 `Client.exe` 的参数/服务发现字符串，或直接 patch 客户端的“必须 TCLS 启动”检查；否则全客户端路线仍被登录器门挡住。

## 2026-10-21 找到 TCLS 检查的本地化 key WIN_NO_TCLS

全客户端 `localization.txt` 里有 `WIN_NO_TCLS = "请使用腾讯游戏登录器(TCLS文件夹内的Client.exe)启动游戏。"`；`codoMP_client_shipRetail.exe` 里 `WIN_NO_TCLS` ASCII 在文件偏移 `0x6C7F80`（VA `0xDDDF80`），但 exe 中没有指向该 VA 的绝对引用，说明它走的是本地化表/key 查找而不是直接字符串。下一步在弹窗时 hook `MessageBoxW`/`CreateDialog` 抓返回地址，或反查本地化 key 查表函数，定位 `WIN_NO_TCLS` 的判定分支后 patch。

## 2026-10-21 当前两条路线都停在“启动/房间门”

全客户端被 `WIN_NO_TCLS`（必须 TCLS Client.exe）挡住，真实 TCLS Client 离线单启 exit 0 不拉游戏；社区离线客户端被 room/start 状态机挡住（0x945CEB 容器崩溃、地图索引 -1）。下一步优先做可验证的静态 patch：在社区客户端里把 `0x62F840` 的 start 分支改成直接调用已确认可用的 `0x4F3890` + 合法 map 参数（不再依赖 room 字段），或在全客户端里 hook `MessageBoxW` 抓 `WIN_NO_TCLS` 的调用者后 patch 判定。两条都先做“单点 patch + 可回退 + 证据”，不再扩大注入面。

## 2026-10-21 单点 patch 0x945CEB 成功阻止崩溃：房间开始后回到大厅而不是黑屏/崩溃

把 `mov esi,[ecx]`（`8B 31`）改成 `xor esi,esi`（`31 F6`），再执行 `0x62F840(0,0,0)`；客户端不再 `0xC0000005 @ 0x945CEB`，而是正常回到大厅，`0x3306910=-1`、`0x3306994=1`。说明 start 路径因为容器查找返回 null 而中止，但不再崩。下一步补这个容器/查找结果（让 `0x945CE0` 返回合法 map 记录），而不是继续改 room 字节。

## 2026-10-21 容器 lookup hook 安装成功但客户端在 room 流程中退出，未记录到调用

`hook_container_lookup.py` 把 `0x945CE0` 前 6 字节改成跳 cave（保存 ECX/返回地址后执行原 `55 8B EC 8B 45 08` 再跳回），cave 在 `0x3DF30000`；但进入房间/触发 start 后客户端退出，读 `[cave+0x800]/[cave+0x804]` 均为 0，窗口消失。说明 hook 点没被这次 start 命中，或客户端在更早路径退出。下一步改为在 `0x62F840` 入口记录 ecx/返回地址，确认 start 是否真正进入容器查找。

## 2026-10-21 start hook 确认 0x62F840 被调用一次

`hook_start_callsite.py` 在 `0x62F840` 入口记录 `count=1`、`ecx=0x13C87910`（room）、`ret=0x117B000C`（我们的 `_main_thread_call` cave）。说明 start 方法确实执行；返回地址是我们自己的 cave，所以还没拿到游戏内自然调用者。`room-command.json` 的 `room_start.status=armed`。下一步用自然 ready/start（不经过我们的 cave）触发，hook 才能记录游戏内调用者并定位它依赖的容器。

## 2026-10-21 自然点击“准备”不会调用 0x62F840

在房间内装 start hook 后点击“准备”，`count=0`、`ecx/ret=0`，说明 `0x62F840` 不是 ready 按钮的直接处理函数，而是 host/backend 触发的 start 事件。这也解释了之前为什么点“准备”没反应：离线房间没有主机/后端去调用 start。下一步找真正的 ready 按钮处理（UI 事件/room 命令），而不是继续调 0x62F840。

## 2026-10-21 CEF 远程调试参数被客户端接受但 9222 无 CDP

用 `-- --remote-debugging-port=9222` 启动社区客户端，进程正常运行（使命召唤online），但 `http://127.0.0.1:9222/json` 5 秒超时，netstat 无监听。说明客户端虽基于 CEF，但未开启 DevTools 远程调试（或端口被禁用）。下一步只能走 UI 事件/room 命令桥接，无法用 CDP 直接执行 JS 点“准备”。

## 2026-10-21 UI 资源里也搜不到 room_ready/“准备”

在 `1649370\resources` 和 `bin\v1649370` 下遍历文件搜 `room_ready`/`roomReady`/UTF-8/GBK“准备”，零命中；客户端 exe 也没有 `room_ready`/`room_start` 字符串。说明 ready 按钮逻辑在 CEF 二进制/加密资源里，或走 native UI 事件而不是文本命令。下一步只能从窗口消息/辅助功能（MSAA/UIA）或 native 事件表反查，无法再靠字符串定位。

## 2026-10-22 自然登录链打通：Auth → LSG → 原生大厅（本轮）

本轮门槛（已通过）：**不修改代码、不伪造连接状态，由游戏自身状态机完成登录并进入原生大厅**。

- 入口：`0x7F26C0` 按 `[0x84ABA50]` 分派 `0x7F3600`（会话准备）/`0x7F28F0`（Auth）/`0x7F3800`（LSG）/`0x7F27B0`（收尾）。
- 会话准备用 `dwauth.ini` 的 Auth 主机 `0x81A76A8` 与 LSG 主机 `0x81A7F34` 建对象；LSG netadr 由 `0xBAEBB0 → 0xB76F10` 写入 `0xE3EC988`（0x88 字节块，不是主机名）。
- 把 `[0x84ABA50]` 置 1 后 tick `0x7F26C0`，客户端自主完成 `/auth/`、LSG 握手、token、加密 `0x85`，并请求 `svc71/task4`。
- 现场：`ui_state=5, login_ready=2, auth_state=9, lsg_state=2, conn+0xC8=2, conn+0x5E8=3`；服务端日志见 `evidence/experiments/20261022-natural-auth-lsg-c.jsonl`，大厅截图 `evidence/experiments/20261022-natural-lobby-ui.png`。
- 工具：`tools/drive_login_state_machine.py`（状态机驱动）、`tools/read_lsg_config.py`（配置块读取）、`tools/set_lsg_host.py`（反证用，已证明不可写字符串）。

**下一门槛（G2 服务层）**：

1. 用真实 bdService 应答替换 `svc71/task4`（服务器列表）候选形状，参考 `server319/lsg_derived.py` 的 `make_server_entry` 与 `codol-node/lsg.js` 的 task4/task9 实现，判据是客户端接受应答并继续请求 task9/房间列表。
2. 解析并回答 `svc80/task232`、`svc9/task5`（当前 `error=14`），避免客户端把大厅业务当失败。
3. 让客户端显示服务器条目后，走原生“开始游戏 → 多人竞技/自定义房间”路径，抓取 `mmstart`/房间请求，再由本地服务返回可加入的 dedicated 结果，进入 1649370 的 UDP 游戏通道；地图装载与 bot 生成在此之后。
4. 每次只改一个服务应答，记录客户端下一帧请求作为判据；连续三轮无新请求则换服务或换入口。

## 2026-10-22 服务层解码与主线程开图（本轮）

- LSG 请求已可读：`svc71/4`、`svc28/4`、`svc102/7`、`svc102/1`、`svc3/46`、`svc3/48`、`svc80/232`、`svc9/5` 的参数全部解出并落证据。
- `AI开关` 属模式相关：个人竞技可切“打开”，战术团队竞技惰性；坐标见 STATUS 顶部。
- `0x62F840` 主线程调用不再崩，但只拆 UI 不加载地图；赛单/地图表只由网络消息解析写入（`0x5C206E/0x5C213C`），必须服务端下发。
- 下一门槛：按 `GAME_TRANSPORT_PROGRESS.md` 实现游戏通道服务端（NAT/INIT/DATA/gamestate），再谈地图装载与 bot。

## 2026-10-22 房间浏览 21/13（本轮）

- 客户端 `自定义 → 查找房间` 主动发 `svc21/task13`（query=5、initial、8B 游标、pageSize=30、4×Int32 条件）。
- 已按 3.3.3.3 文档实现房间列表记录与信封（双/单 count、v4/v46 地址、计数回显），客户端仍显示“未找到房间”。
- 下一门槛：用解码对象偏移（+0x10/+0x120/+0x124/+0x128/+0x1cc/+0x208）下写断点反查客户端列表解码器，确定记录字段顺序；之后再走 11/11 入房与 6/14 mmrsv/mmbook。

## 2026-10-22 bdService 内层 HMAC（本轮）

- 业务回执被 `0xBA3710` 的 16 字节 HMAC 校验拒绝（`HMAC mismatch` 0xD5A4FC）；内存扫描无 “AI-Room” 证明记录未解码。
- 已排除：序号/计数起始值、回执顺序（改成每个请求都回）、单/双 count、地址块布局。
- 下一门槛：在 `0xBA3710` 比较点下断点，确定 HMAC 字段位置/覆盖范围/密钥，再验证房间列表与 task4。

## 2026-10-22 内层 HMAC 密钥与旁路（本轮）

- 运行时验证内层 HMAC 密钥 = LSG `server_mac`（逐字节一致）。
- 6 种覆盖均失败；比较点 hook 命中 0；跳过整段 HMAC 处理后记录仍不解码。
- 下一门槛：hook `0xBA39E7`/`0xBA3A05` 确认消息是否到达 bdService 分发器，dump 其 buffer/len，按真实布局修正。

## 2026-10-22 修正：大厅不读 LSG socket（本轮）

- 计数 hook 证明：登录结束后 `0xBA3710` 命中 0；手动 `0xB838A0` 后命中 8。
- 持续泵后房间列表记录被正确解码（内存 +0x120/+0x124/+0x128/+0x168/+0x170 全对），基线回执无需 HMAC。
- 上一轮“内层 HMAC 根因”结论作废。下一步：查询前保持泵运行，确认 UI 渲染房间行，再抓 11/11 入房。

## 2026-10-22 房间记录解码但 UI 不消费（本轮）

- 记录稳定解码（字段全对），但内存中始终只有 1 份副本 → UI/结果缓存未消费。
- 已排除 v4/v46 地址布局、空成功回执、刷新/模式点击重查。
- 下一轮：hook 21/13 发送构建路径或任务完成回调，找到结果消费者，必要时直接构造结果对象。

## 2026-10-22 房间查询链与回调（本轮）

- 发送链：0x62DD60 → 0x7F43C0（注册回调 0x7F4330）→ 0xBA3370 → 0xBA24C0 → 0xC739E0 → 0xC76DB0 → send。
- 回调 0x7F4330 实测 hits=0（task=13/21 均如此），但记录仍解码 → 解码与完成是两条路径。
- 下一轮：hook 任务完成/出队，找“响应→pending 任务”的匹配点。

## 2026-10-22 任务完成与 task 字节无关（本轮）

- 三种 task 字节（0x0D/0x15/0x26）回调均 0 命中，记录均解码。
- 抓到任务对象 0x4de5ce08（vtable 0xD59A08）；注册链 0x7FAA20→0x7FA800，管理器 0x6376F0。
- 下一轮反汇编任务类虚表与 0x7FA800，找响应匹配键。

## 2026-10-22 任务完成线：错误回执也不触发（本轮）

- 错误回执同样 0 命中 → 响应→任务完成整体未走通。
- addTask(0x7FA800) 命中 1 次：action=38、ecx=0x4f65cde4。
- 0xE56FFE0 槽表是消息处理器注册表（首字段为消息类型）。
- 传输单例 0x23D7F5A8 仍 0xBAADF00D 填充；盲调 0x7EF0D0/0x4A6470 会崩溃。
- 下一轮：接收入径定位任务匹配函数，或转游戏传输线。

## 2026-10-22 信封/帧形态矩阵全失败（本轮）

- 空结果、帧类型（0x85/0x84 × 0x01/0x86/0x00）、信封标签、无 tid 共 12 种回执，回调全 0 命中。
- 0xB9B230 返回对象回执前后 128 字节相同 → 是请求参数不是任务。
- 下一轮：试 0x84 帧（0xBA0E20）作为完成/状态消息；反查 functor 注册保存回调的位置。

## 2026-10-22 训练靶场：更短的分配入口（本轮）

- 训练→靶场→进入靶场直接发 21/5 query1（u32(1),u32(0),u32(10),tag7）。
- 已实现回执：114B bdMatchMaking 条目（127.0.0.1:8466）。
- 客户端仍停在“正在搜寻服务器...”（任务完成问题）。
- 下一轮集中攻任务完成（0x84 帧 / functor 注册）。

## 2026-10-22 任务完成：task 字节无关、tid=0 无效、0x84 致命（本轮）

- task 字节=99 仍解码 → 记录解析是 service 级。
- tid 从 0 开始仍 0 命中。
- 0x84 帧导致连接中止（10053）。
- 下一轮：对比 svc71/task4 的完成行为，定位真正的任务表。

## 2026-10-22 找到 pending 任务表（本轮）

- 表 0xE56FFE0（0x50 步长，40 槽）：+0x00 action、+0x08 tid、+0x28 params、+0x30 回调。
- 房间查询占 index 7（action=0x26）；回执后槽不变 → 任务从未完成。
- 闭环测试真实 tid（40896）与 action+tid（37253）均 0 命中。
- 下一轮：找“比较 +0x08 清零 +0x00”的函数，或 PAGE_GUARD 捕获第一次写。

## 2026-10-22【突破】任务完成函数 0x7FB240（本轮）

- 0x7FB240(action) 遍历任务表，命中后用 slot+0x30 回调完成任务。
- 远程调用 0x7FB240(0x26) 后回调 hits=1（handler=0x6376F0、ctx=5）→ 完成机制正常。
- UI 仍空：强制路径不带结果。
- 下一轮：找“带结果完成”的调用，或先写结果再完成。

## 2026-10-22 回执已到服务层，只差成功完成（本轮）

- 任务槽 +0x40 handler=0x6376F0、+0x44 ctx=5；params +0x1C 已挂解码记录。
- 0x7FAF50 是单槽完成（EAX=slot，栈参数=成功标志）；0x7FB240 批量但标志硬编码 0。
- 远程线程直调 0x7F4330(params,1) 会崩溃 → 必须走窗口线程。
- 下一轮：给 call_main_thread 加 EAX 支持，窗口线程调 0x7FAF50(slot,1)。

## 2026-10-22 成功分支崩溃：少一步“准备参数”（本轮）

- 窗口线程 0x7FAF50(slot,1) → unhandled_exception；成功分支把 params+0x28(30) 当指针。
- 响应处理器只写了 params+0x1C（记录），未写 +0x28/+0x40/+0x44。
- handler 链 0x6376F0→0x637590：count×0x238 拷到 room+0x7470，count 写 room+0x7230（UI 列表）。
- 下一轮：补写 params 或直接写 room 列表模型验证。

## 2026-10-22 列表模型写入点与注入失败（本轮）

- 0x62CD30 单房间显示、0x637720 批量、0x637590 通知分发。
- 直接写模型不渲染；0x637720 不渲染；0x62CD30 崩溃（智能指针非法）。
- 下一轮：观察自建房间时 room+0x7238 的填充方式。

## 2026-10-22 创建房间先发 21/13，创建停滞（本轮）

- 点“创建房间”只触发 21/13，无 21/1；room+0x7238 未填充。
- 推断：创建前用 21/13 检查重名，任务不完成则停滞。
- 另：点击命中率不稳，需要带校验的点击助手。

## 2026-10-22 点击可靠性（本轮）

- 新增 click_verified.py（点击+区域比对+重试）。
- 创建房间标签需 --method post；创建按钮两种方式都无响应。
- 下一轮：网格扫描按钮区/检查 disabled，确认 21/1 出现。

## 2026-10-22 光标模板点击校准（本轮补充）

- tools/find_cursor.py + cursor_template.png，FFT SSD 定位光标。
- 实测点击误差约 6px，按钮区域 205x65 → 按钮无响应不是坐标问题。
- 后续：mouse 点击用光标校准；创建按钮问题转向控件状态/前置数据。

## 2026-10-22【突破】键盘触发创建，已进本地房间（本轮）

- 鼠标网格 15 点无效；Tab×2+Enter 成功建房并进入房间场景（1/12，战术团队竞技/迷你战争）。
- 服务端无新请求 → 纯本地流程。
- 下一轮：键盘焦点开“高级选项”查 AI，再点“准备”看能否进本地对局。
