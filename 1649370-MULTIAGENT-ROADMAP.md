# CODOL Build 1649370 本地 bot 对战：多 agent 技术路线

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
