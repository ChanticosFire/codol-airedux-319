# Build 1649370 离线对局：当前交接（2026-10-29）

> **2026-10-30 物品编号资料边界**：用户转来的社区实测称“部分枪械旧表 ID +9000 对应另一份目录物品 ID”，并报告 `10710` 为客户端发出的 SKU；这份外部目录与抓包未在当前机器取得。当前工作树附带的社区商城目录反而把 `1000` 直接列为 `type95_mp`，`10000` 列为徽章，SKU 最大 `2762`。因此该换算不能直接写进当前服务。仓库已有 r527 原生库存 7208 项的正例，r525 空白更像赛后前端状态问题，原因仍未定；对局快照武器 78 属于 11 位武器索引，不能与商城 ID/SKU 混算。详见 [§1331](1649370-STATUS.md) 和 [编号边界](docs/1649370-ITEM-ID-SKU-BOUNDARY.md)。

> **§1330 最新纠错，先读**：撤销下面 r811/r812 段落中把 `ps+0x564=0` 称为“武器 78 拥有位为空”的解释，以及 r813 以 `0x564=0x4000` 测拥有位的建议。那是把社区保留引擎布局套进原生客户端；`0x564` 原生字段语义未证实，装备由快照尾部 inventory 编码。r811 的 108 个原始包 `usercmd.weapon=0`（17 个真实攻击包同样为 0）、r812 的 `ps+0x333c=0` 与 `ps+0x564=0` **原始读数仍成立**，其因果未知。r813 候选未送客户端，`-57` 临时分支已撤回。下一步先查原生客户端武器选择字段的生产点和尾部 inventory 消费路径，不再做错误地址的 A/B。[证据更正](evidence/experiments/20261029-r812-native-spawn-owned-read.json)、[状态 §1330](1649370-STATUS.md)。人工扣弹不得恢复；五项验收未完成。

> **2026-10-29 r811 原生武器状态新线索（n=1）**：真实左键期间，服务端收到 17 个攻击包；独立重解同一会话的 108 个完整客户端包，全部 `usercmd.weapon=0`，尽管客户端 `ps.weapon/primary=78`、弹夹 30。3.5 秒内 632 次约 5 ms 采样的五个原生武器状态字段均为 0，弹夹不变。r738 快照缺 `0x333c` 出生时间；社区同 Build 的 `codol_game.c` 把命令武器 0 当作无武器请求，仅出生后 200 ms 暂时忽略。**这仍是待验证的原生选择/出生链路假设，不是已确定的因果**；先追命令生产点和已解析的尾部装备数据，再单变量验证。人工扣弹已删，事件 ID 54 送达不算射击。[脱敏数据](evidence/experiments/20261029-r811-native-usercmd-weapon-zero.json)、状态 §1330。继续只复用 `r107flow/runtime`，保护私有档案。五项验收未完成。

> **r812 只读复核 / r813 静态构造，语义已于 §1330 更正**：新独立连接中，客户端 `ps+0x333c=0`、`ps+0x564=0`，`ps.weapon=78`、弹夹 30；`0x564` 的原生语义未知，不能称为拥有位。临时 `-57` codec 分支曾使 r738 帧字节精确回环，并构造 109 B 候选，但 r813 候选**未发客户端**，分支已撤回。此前建议的 `0x564=0x4000` A/B 作废；下一步追命令武器生产点和快照尾部装备消费，不恢复人工扣弹。[读数与静态边界](evidence/experiments/20261029-r812-native-spawn-owned-read.json)。

> **2026-10-29 r807–r810 用户约束与最新结果**：人工把弹夹 30→29 的旧服务端诊断已删除，**不得以此验收射击或恢复这条捷径**。真实左键包现在可在默认关闭的事件探针中产生 Build 1649370 ID 54；r807/r809 客户端原生事件字段随之从 0 变为序列 1 / ID 54，弹夹保持 30。r809 按前/中/后五个原生武器状态字段均采到 0，截图无枪身/枪口反馈；r810 关闭事件开关的对照确认旧人工扣弹不会发生。[直接证据](evidence/experiments/20261029-r807-r810-native-fire-boundary.json)、状态 §1327。**当前仅输入→事件送达成立，客户端原生射击、弹药/命中/伤害仍不成立。**下一步查本 Build 原生武器状态机的条件及已加载签名 FF 后枪身定义为何仍为 `tag_origin`。r808 有额外攻击沿，单次点击因果不可夸大。完整五项验收仍未完成。

> **2026-10-29 r804–r806 事件字段最新边界**：撤销下条 r803 把 `-94` 首位称为 tag 的解释。原生 Build 1649370 读取器将其视作事件 ID 变化位；ID 54 是 `EV_SV_FIRE_WEAPON`。r804 首次启用 `0x108` 时触发了本地错误的 `-75` 编码，虽发送 64 次却使客户端玩家状态错位。修正为同 Build 源码的 1+3 位/字节 XOR 后，r805/r806 两次独立真实连接均让客户端原生读到事件序列 1、事件 ID 54，同时坐标/武器 78/弹夹 30 正常。[源与客户端证据](evidence/experiments/20261029-r804-r806-player-event-native.json)、[r806 截图](evidence/experiments/20261029-r806-event54-client-state.png)、状态 §1326。**目前只证明事件送达，尚未证明真实左键驱动、客户端开火消费、枪身、弹道/命中、伤害。**下一步把真实左键输入与单次递增事件序列绑定，并直接测消费结果；继续追查枪身定义 `tag_origin`。仍复用唯一运行时，完整五项验收未完成。

> **2026-10-29 r803 静态进展**：本 Build 的双字事件字段 `-94` 原被 `wire164.py` 误写成单字节；已按同 Build 社区编码器改为显式、经校验的 `tag 0 + 11-bit payload`，并修正只读解码器。r738 102 B 候选帧仍逐字节一致，事件边界负载 0/2047 可回读。详见 `1649370-STATUS.md` §1325 与[证据](evidence/experiments/20261029-r803-player-event-codec-static.json)。本轮没有客户端实测，尚未确定实际开火事件编号、事件序列、客户端反应，也没有解决枪身自动绑定。旧审查中“clients 段从未实现”已被现有编码器及 r735/r736 原生直读更新。

> **2026-10-29 低额度交接**：当前唯一给 DeepSeek 的长程目标已重写为 [docs/1649370-DEEPSEEK-LONGTERM-GOAL.md](docs/1649370-DEEPSEEK-LONGTERM-GOAL.md)，以 §1323 的 r800–r802 同路径三次实测为起点，列明完整五项验收、正确签名资源目录、真实连接与已恢复的背包 UI、诊断枪身/输入闭环和仍未证明的真实射击、物理、正常赛后及 `ui_state != 5`。资源原件/私有备份/哈希以 `resources/1649370/README.md` 和 `manifest.json` 为准。接手不得重跑根目录 FF 的旧无枪实验或把诊断扣弹称为开火成功。

> **2026-10-29 r800–r802 最新同路径组合复验**：签名 AK-47 资源在原生 `client_shipretail/chinese/` 路径暂存、可逆客户端模型指针绑定后，三次独立真实连接都完成鼠标转向→W/S/A/D→左键序列；服务端分别解码 347/385/324 个输入包、零错，客户端各阶段 `net=10`、朝向约 −29.8°、四方向位置读数改变，左键后诊断弹夹 30→29。手臂与 AK-47 枪身在移动及左键后[画面 r800](evidence/experiments/20261029-r800-armed-sequence-after-input.png)、[r801](evidence/experiments/20261029-r801-armed-sequence-after-input.png)、[r802](evidence/experiments/20261029-r802-armed-sequence-after-input.png)持续可见；[分列证据](evidence/experiments/20261029-r800-r802-armed-input-sequence.json)、`1649370-STATUS.md` §1323。**仍是每包有界诊断位移、人工扣弹和临时客户端枪身绑定**，不等于真实物理/射击或服务端持续发枪；正常结束、仓库与字面 `ui_state != 5` 未在同一路径验收。

> **2026-10-29 r796–r799 纠正近期无枪回归**：上一条 r793–r796 的队列 `(78,0)`、模型缓存 0 是真实读数，但“为何不完成仍未知”**已由单变量复验解开**：近期脚本把签名 `ak47_mp.ff` 放在 `r107flow/runtime/` 根目录；原生检查需要 `r107flow/runtime/client_shipretail/chinese/ak47_mp.ff`。r797/r798/r799 只改此暂存路径，三次独立真实连接均见武器查询字 1、待处理队列 0、手臂模型数 2；在现有可逆的 `weaponDef78+0x10` 客户端内存诊断绑定后，三张有效[截图 1](evidence/experiments/20261029-r797-correct-ff-path-visible-ak47.png)、[截图 2](evidence/experiments/20261029-r798-correct-ff-path-visible-ak47.png)、[截图 3](evidence/experiments/20261029-r799-correct-ff-path-visible-ak47.png)都出现 AK-47 枪身。[路径 A/B 证据](evidence/experiments/20261029-r796-r799-weapon-fastfile-stage-path-ab.json)、`1649370-STATUS.md` §1322。**这是诊断路径，不是服务端持久下发枪模或真实射击成功**；完整物理、命中、正常赛后回大厅与字面 `ui_state != 5` 仍未验收。后续所有实验先核对签名资源的原生成员路径，避免重犯此回归。

> **2026-10-29 r793–r796 最新枪模定位**：四轮独立真实连接中，客户端第一人称模型缓存 `client+0xC7F88` 在武器定义仍为 `tag_origin` 和诊断绑定到 `viewmodel_ak47` 后均为 **0**；r795/r796 各 8 次连续采样也始终为 0。r796 的原生武器选择是 **78**，武器资源查询项首字为 **0**，队列头持续 `{weapon:78,status:0}`，与 `0x5904b6–0x5904bd` 的已有待处理项提前返回条件吻合。因此单改模型指针无法建立当前路径的第一人称模型；**资源队列为何不完成仍未查明**，不要把该分支吻合写成已修复。r796 [有效画面](evidence/experiments/20261029-r796-weapon-queue-stalled-no-viewmodel.png)仍为 AK-47/29 HUD、无手臂和枪身。[四轮证据](evidence/experiments/20261029-r793-r796-firstperson-model-queue.json)、`1649370-STATUS.md` §1321；旧 r753 建模函数曾运行、r755/r756/r758 曾有枪身，这些历史结果有效。下一步沿队列生产者和消费者查状态 0 为什么常驻，再做服务端可持续的资源注册；真实射击、物理、正常回大厅及字面 `ui_state != 5` 均未验收。

> **2026-10-29 r786–r792 枪模复验警报**：七轮当前真实连接都经现有工具核对 AK-47 定义 `+0x10` 从 `tag_origin` 改向已加载 `viewmodel_ak47`、读回正确并恢复原值，然而有效截图都没有第一人称手臂/枪身。r786 同时收到 15 个攻击包，服务端诊断扣弹一次，客户端 HUD/字段 30→29，[画面](evidence/experiments/20261029-r786-binding-attack-no-gun.png)仍不显示枪身。关闭运动探针、只读解码、恢复旧桥接截断，或把绑定/取图推迟到第约 1100–1300 个快照，都未单独复现 r755/r756/r758 的历史持枪画面。旧画面有效；**当前指针修补不充分，差异原因未定位**。七轮[脱敏证据](evidence/experiments/20261029-r786-r792-viewmodel-repeat-audit.json)、`1649370-STATUS.md` §1320。停止反复切同一指针；直接读 cgame 活跃 DObj/模型列表，先查为何本轮连改指针前的手臂都未生成。所有私有资源、活库及唯一运行时恢复基线。

> **2026-10-29 r780–r785 最新实机进展**：真实输入包的角度基线来自客户端已确认的快照。r781 使用零基线时，鼠标后客户端一度读到 −29.8389°，W 后归零；现按 `messageAck` 找对应快照基线，r782/r783 两轮独立连接分别解码 246/212 包、零错，客户端鼠标后和 W 后持续约 −29.8°，位置同时沿两个世界轴变化。r784/r785 两轮完整鼠标→W/S/A/D→左键会话也均零解码错、朝向保留、每键后 X/Y 改变，左键后原生弹夹三次读到 29；**完整序列仅两次，不宣称稳定**。[脱敏证据](evidence/experiments/20261029-r780-r785-ack-baseline-yaw-movement.json)、r782 [前](evidence/experiments/20261029-r782-before-mouse.png)/[后](evidence/experiments/20261029-r782-after-yaw-w.png)与 r784 [后](evidence/experiments/20261029-r784-after-yaw-four-axis-ammo.png)、`1649370-STATUS.md` §1319。仍是每包 ±2 的诊断运动和扣一发诊断，无碰撞/时长物理、真实射击或第一人称枪身；正常结束回大厅和字面 `ui_state != 5` 未复测。下一步以这个真实输入/朝向闭环为基础做物理与开火，并单独解决枪模绑定。唯一运行时和私有档案保持基线。

> **2026-10-29 r775–r779 最新实机进展**：现有完整客户端包解码器在真实聚焦 W/S/A/D/左键下读出方向 `1/2/8/4` 与攻击位 1。旧 W-only r775 对照后，r776/r777 两轮独立连接中，游戏服默认关闭的实验探针按方向重建 X/Y 快照，客户端每键后直接读到对应坐标；r778/r779 两轮额外让左键按下沿把弹夹 30→29，客户端字段三次回读 29，r779[前](evidence/experiments/20261029-r779-before-input.png)/[后](evidence/experiments/20261029-r779-after-input.png)画面 HUD 同为 30→29。完整[源端/客户端分列证据](evidence/experiments/20261029-r775-r779-four-axis-ammo-feedback.json)、`1649370-STATUS.md` §1318。**该路径仍是每包 ±2 的轴向位置及一按一发的人工诊断，不含朝向/碰撞/真实射击；第一人称枪身依旧缺失，正常结束回大厅与字面 `ui_state != 5` 未验收。**私有档案与唯一运行时恢复基线。

> **2026-10-29 参考资料范围补充**：用户明确要求把 `codol-ember` 的**整个仓库**当作参考，不限最新进度。当天 `git fetch` 后 HEAD 与远端 `main` 均为 `f784a77`；按版本身份、1649370 资源/启动/UI、1604220 比较实现、方法工具及许可编成[全库问题索引](docs/1649370-CODOL-EMBER-REFERENCE-AUDIT.md)。其 `first-page-routes.json` 可指导赛后回大厅的观察，IIPS/IFS 报告可指导枪模资源链排查；二者均未替代 1649370 实机验收。本次只是资料索引，未改运行时/活库，已验证成果仍以 r773/r774 为准。

> **2026-10-29 r773/r774 内置服务端 W 反馈，交接入口**：游戏服新增默认关闭的 `--input-motion-probe`，仅接受 SHA 匹配、byte-exact 可重建的 r738 快照；每个新的真实 `direction=1` 包令服务端快照 X +2，最多 +64。r773/r774 两轮独立真实连接均 `net=10`、真实 CODO 窗口 W 按住 1600 ms、输入解码零错：服务端分别处理 15/10 个前进包并将 X 从 336 改为 366/356，客户端事前 336、事后三次分别稳定读到 366/356。它证明服务端内已形成单方向输入→快照→客户端位置闭环，**不等于完整自由移动**。r773[前](evidence/experiments/20261029-r773-before-w-integrated.png)/[后](evidence/experiments/20261029-r773-after-w-integrated.png)截图依然没有第一人称枪身；r774 后截图黑帧不作视觉证据。射击、持久枪模、正常收尾、字面 `ui_state != 5` 均未完成。细节 [r773/r774 证据](evidence/experiments/20261029-r773-r774-integrated-w-motion.json) 与 `1649370-STATUS.md` §1316。给 DeepSeek 的**当前完整长程目标**是 [docs/1649370-DEEPSEEK-LONGTERM-GOAL.md](docs/1649370-DEEPSEEK-LONGTERM-GOAL.md)；其旧 r675 状态已替换。唯一运行时与私有活库回到基线，无残留进程。

> **2026-10-29 最新，r765–r772**：`server1649370/client_input.py` 依据社区 AGPL 参考与真实包实现只读 `clc_move` 解码，r762/r763/r764 的 709/441/453 个完整包均与独立探针关键字段一致；r765/r767 服务端在线解出 533/99 个非碎片包、0 错。桥接器新增显式 `slot|nul` 回退：r766 的旧 `nul` 路径只有 116 个短包、0 解码，而 `slot` 正常。r738 102 B 快照已字节精确重建；r768 服务端单独改 X 336→346，客户端连续四次接受。更关键的两轮真实 W 输入：r771 解出 10 个 `direction=1` 包、实验性服务端快照 X 336→356，客户端三次读得 356；r772 解出 7 包、X→350，客户端三次读得 350，均 `net=10`。**这是外部诊断脚本按每包 +2 X 的单方向反馈，不是完整游戏物理或可自由移动验收**；同源仓库化脚本为 [`tools/input_to_snapshot_probe_1649370.py`](tools/input_to_snapshot_probe_1649370.py)，两轮截图 [按键前](evidence/experiments/20261029-r772-before-w.png) / [按键后](evidence/experiments/20261029-r772-after-w.png)，以及[源端与客户端分列数据](evidence/experiments/20261029-r768-r772-input-to-snapshot-motion.json)。按真实 `keybd_event` 的当前方式聚焦 `CODO` 才产生命令；r770 聚焦隐藏 `CoD Splash Screen` 未产生命令，不推翻早期单独的窗口消息实验。当前下一步：将解码输入与有界快照反馈整合进游戏服、扩展左右/后退及转向，追 attack→弹药/射击，另修 `weaponDef78+0x10` 持久绑定；直接测 `ui_state` 和正常结束。完整 `codol-ember` 仓库资料与适用边界见[参考索引](docs/1649370-CODOL-EMBER-REFERENCE-AUDIT.md)。只复用唯一运行时，私有存档、签名 FF 与清理均已回到基线。

> **2026-10-28 r761–r764 出站桥修复，最新**：旧桥把环 A 所有包按首个 NUL 截断；真实二进制包首个 NUL 通常在偏移 2。r761 只读槽显示 `slot+0x4E8=824` 且有效载荷最后非零偏移 823。修复后 OOB 仍按 NUL，二进制包用经界限校验的槽长；r762/r763/r764 三轮独立真实连接分别让服务端收到 709/441/453 个完整且序号各异的包，短包均为 0，客户端均 `net=10`。r764 聚焦按 W 时服务端收到 36 个完整包且客户端 cmd number 394→413，但坐标仍 `(336,60,260.5)`；左键也无已解码攻击证据。**完整收包 ≠ usercmd 已解码或移动/射击已生效**。下轮优先解密、解析用户包并以服务端 playerState 反馈；别从旧 NUL 截断日志推断客户端不发输入。[证据](evidence/experiments/20261028-r761-r764-ring-a-binary-length.json)。

> **2026-10-28 r760 补充**：独立第二轮运行可选保护工具，`probe→apply→restore` 均核对模型名与内存回读；`apply` 后[实机截图](evidence/experiments/20261028-r760-helper-viewmodel.png)可见完整 AK-47，恢复后原指针回到 `tag_origin`。服务器 `connect=1`、快照 1092 次、桥排队 1145 次，客户端 `net=10`；私有档案基线与唯一运行时恢复。工具的可逆诊断已两轮验证，**仍未构成服务端持久绑定或射击验收**。

> **2026-10-28 r754–r759 枪身绑定定位，覆盖下文“枪身仍不可见”的旧状态**：真实连接中，武器 78 定义的 `+0x10` 指向名为 `tag_origin` 的占位 XModel；同时 `viewmodel_ak47` 真正的 XModel 已加载在 `0x2311A8C`。r755、r756、r758 三次独立会话均在同一客户端内只改这一处 32 位指针，修改后截图出现完整 AK-47 枪身，修改前是手臂加 AK-47/30 HUD 而无枪身。**这是客户端内存诊断，不是服务端已能持久下发枪模**。r758 的真实鼠标左键 500 ms、窗口焦点确认、前后 `net=10`，但弹药仍 30，未见射击反馈；移动和 `ui_state != 5` 也未验收。§1272 由“资产已加载”推断“非绑定故障”的结论现已撤销：资产存在，活跃武器定义却未指向它。r757 截图黑帧与落地视角不计作视觉复现。新建可选诊断工具 `tools/probe_weapon_viewmodel_binding_1649370.py`，r759 实测 `probe→apply→restore` 与错误目标拒写，主启动路径未改。下一步先查正常武器注册为何保留 `tag_origin`，再建立可复现的装载/绑定机制；射击和移动应从服务端实际处理真实输入的路径验证。证据、三张已入库截图与清理记录见 `evidence/experiments/20261028-r754-r758-ak47-viewmodel-binding.json`。

> **2026-10-28 r753 枪身组装入口补证**：在客户端初始化后、入场前安装入口钩子，真实连接中 `0x58F850` 武器视角构建器命中 768 次（恢复时 1081 次），现场 `ECX=78`、模型参数数目 2、返回地址 `0x590744`。所以旧的“入场后才挂钩子读数 0”仅是错过调用窗口，不能说枪身构建器未运行。场内仍有手臂、AK-47/30 HUD 而无可辨认枪身；缺口已移到构建器内部或其后续提交。静态 `weaponDef+0x30` 在 1171 个定义中仅六个弹道刀非零，AK-47 为零不是独立故障证据。来源与清理见 `evidence/experiments/20261028-r753-weapon-view-builder.json`。射击、移动与 `ui_state != 5` 仍未证明。

> **2026-10-28 r748–r752 最新进展，覆盖下文 r747 的待测项**：五次独立运行均由服务端接入并达到客户端 `net=10`，每次复用同一 `r107flow/runtime`，临时放入经过签名和哈希校验的 `ak47_mp.ff`，同时恢复 `0x58EF76` 原始按武器 ID 索引。r748 在武器 ID 78 的注册调用现场读到槽指针 `0x1C16BC8`，进入时 `slot+4=0`、写入后为 `0x12CB1720`；r749 **无钩子**也读到 78 号 `slot+4` 非零。本组未出现先前的 `174 ak47_mp`。r750–r752 又证实第一人称构建器 `0x5903F0` 和模型解析器 `0x80E1D0` 在真实连接中运行，解析返回值是 2；实时读到的两项模型名是 `fja_ghillie_sc_m_vmchar_basic` 与 `han_fingerless_ss_s_vmchar_20`，均为角色手臂/手部，**不是 AK-47 枪身**。入场截图显示地图、AK-47/30 HUD 与手臂，但仍无可辨认枪身；射击、真实移动、`ui_state != 5` 仍未证明。下一步追独立的枪身注册与 view DObj 提交路径，并做服务端/客户端/截图同轮验证。完整五次发送、桥接、客户端读数和清理记录见 `evidence/experiments/20261028-r748-r752-signed-ff-indexing-viewmodels.json`。临时 FF 与钩子已撤回，写后档案保存在私有备份，活库恢复基线哈希。

> **2026-10-28 r747 测量边界**：同一签名 FF 的第三次运行仍显示 `174 ak47_mp`；服务端发送 2084 次候选快照，但客户端本轮未保持 `net=10`。`0x58F723→0x58EF60` 计数 277 混有大厅阶段其他武器，不能据此说武器 78 已写槽。下轮必须在同一写槽调用中记录 `ecx` 武器 ID、槽指针和返回后 `slot+4`，只对 ID78 下结论。证据 `evidence/experiments/20261028-r747-slot-writer-probe.json`。实验结束已撤回临时 FF、钩子和进程，正常写库副本私下留存、活库恢复基线。

> **2026-10-28 r746 补证：`174 ak47_mp` 的直接条件已定位**。签名文件临时部署第二次仍报同错（服务端 `connect=1`、候选快照 1017 次，`session.json net=10`；截图 `runs/r746-active.png`）。启动器原有 `Com Error` 断点日志 `r107flow/reuse-631eafaf/events.jsonl:233` 给出返回地址 `0x58FCF0`、格式 `174 %s` 和参数 `ak47_mp`。对应原生指令 `0x58FCD4` 测试武器登记表 `0x1C166E8 + id*16 + 4` 是否为零；为零则在 `0x58FCEB` 抛错。**已知的是空槽触发错误，未知的是槽未建立/被清零的原因**。候选写入路径 `0x58F370→0x58EF60→0x58ED10`，下一步直接计数 `0x58F723` 并对照槽值。不要重复在 `0x4F82E0` 放钩：启动器已用 INT3 断点，事件日志能直接给出调用现场。证据 `evidence/experiments/20261028-r746-error174-registration-slot.json`。临时资源、钩子和本轮进程已清理，活库基线与唯一运行时不变；第一人称武器/射击仍未成功。

> **2026-10-28 r743–r745 最新卡点，覆盖下文“只测武器缓存门槛”**：r743 活跃对局同步采样确认客户端武器 78、视角构建持续运行，但缓存队列项 `(78,0)`、查找字 0，注册前/模型解析调用 0；r744 原生队列处理持续进入，检查 `ak47_mp.ff` 可用性的 `0x4A0410` 路径持续运行，之后的武器注册 0。原始 `ff_init_weapons_V37.ifs` 的 v461 成员 `ak47_mp.ff` 已按签名、哈希链、zone 验证并备份至私有资源目录。r745 只把该文件临时放入**现有** `r107flow/runtime`：服务端发 1517 次候选、客户端曾 `net=10`，武器注册、视角后段及模型解析各进入 1 次，随即弹 `174 ak47_mp` 回大厅；文件已撤走。**没有第一人称枪模/射击成功，也没有证明 174 的具体抛错原因**。下一步定位 174 的原生抛错与该 fastfile 加载结果、依赖，再做同档单变量对照；严禁从弹窗名称猜成“档案坏了”或“服务器没发”。显式撤销旧“资源层已全部解决”：它只覆盖地图和公共 FF，未覆盖按需武器 FF。完整日志计数、内存采样、签名哈希、截图和回滚记录见 `evidence/experiments/20261028-r743-r745-weapon-fastfile-gate.json`；资源来源/独立副本见 `resources/1649370/README.md` 与 `manifest.json`。当前活库基线 `06f7a93b…2f70`、integrity `ok`，无本轮钩子或新增运行时。

> **2026-10-28 r741/r742 新卡点，覆盖下文“下一步测解析返回值”**：r742 真实连接且游戏服仍在运行时，原生 `0x5903F0` 视角构建入口命中 **16426** 次，但 `0x5905B9→0x80E1D0` 的类型化模型解析调用 **0** 次；r741 活跃对局同样解析调用 0。当前缺口在 `0x590435..0x590503` 的武器定义/缓存早退门槛，**不能推断 `0x80E1D0` 返回 0**。r742 入口 ECX 得 `cg=0x133c2ec4`，一次读取 `cg+0x15c=482,+0x3f8=0`，断服后另一次 `+0x3f8=78`；须在同一函数入口瞬间采样武器 ID、缓存状态及命中的早退地址。证据 `evidence/experiments/20261028-r741-r742-viewmodel-gate.json`。钩子已逐一恢复并核对字节；r741 正常写库副本私下隔离，基线从事前备份恢复，r742 后仍为基线哈希。请勿再仅换模型字符串或把解析器未调用写成解析失败。

> **2026-10-28 r738–r740 最新边界**：从唯一运行时的 `code_post_gfx_mp.ff` 原生 marketplace 资源解出，活库所选角色 570=`cha_sniveterana`，默认却穿 `sniprestigea` 套装。SC 第一人称手臂/手部的真实名称为 `fja_ghillie_sc_m_vmchar_basic` / `han_fingerless_ss_s_vmchar_20`；§1309 的 chameleon 模型与角色不匹配。模型加到原 gamestate 的空槽 3050/3051，快照以 `viewmodelIndex=482` 下发，r738/r739/r740 三轮均真实连接；r739 **仍在对局中**的截图有 AK-47/30 HUD 但无枪/手臂。r740 直接读到本地 cgame clientInfo `+0x400=1,+0x404=1,+0x40c=570`，故角色已从网络缓存进入 cgame；武器定义 `+0x10` 指针也非零。下一步直接测 `0x5905B9` 调用 `0x80E1D0` 的**次数和返回模型数**，再按结果查 view DObj 提交；不要再以换模型名、HUD 或断服后的截图推断渲染成功。完整来源、构造、计数和保护记录见 `evidence/experiments/20261028-r738-r740-marketplace-clientinfo.json`。枪模、射击和五项整体验收仍未完成；活库基线与唯一运行时未变。

> **2026-10-28 r737 单字段追踪**：社区 `codol_player_projection164.c:190` 说明目标 `ps+0x15c` 是第一人称手臂的模型槽；当前 gamestate 的 `NCS2568+447` 是 `fja_chameleonlava_sc_m_02_vmchar`。在 r735 的 team1/角色570记录上仅把 `viewmodelIndex 1023→447`，服务端记录候选 1289 次，客户端 `net=10` 并直接回读 447，但截图仍无枪/手臂。这**不排除模型与角色 570 不匹配**，也不证明 cgame 的模型提交路径已运行。下一步先解析角色 570 的 marketplace 默认部件及其正确模型槽，再直接测 cgame clientInfo、本地实体与 view DObj 条件；证据 `1649370-STATUS.md` §1309、`evidence/experiments/20261028-r737-arm-model-slot447.json`。旧来源结构的 `0x144/0x148` 不应盲写为本 build 的 ps 偏移。

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

**已尝试的局部变量**：`cg_drawGun 1`、`viewHeightCurrent`、`viewmodelIndex`（0/78/1023；r737 又试了 gamestate 手臂槽 447，但未确认与角色 570 配套）、`pm_type`（0/5）、demo 差异字段、模型缓存表、`stats[0]`、configstring 武器名。审查 A2 已撤销“78→0→78 切换无效”：旧服务端只反复发送末帧，这项未形成有效循环实验。

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
