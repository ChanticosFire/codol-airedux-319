# 长程目标（从会话 goal 导出，供新会话引用）

> 用法：在新会话里说「把本文件作为长程目标，按其中「下一步执行顺序」开始工作」。
> 本文件是 goal objective 的原文，与 `docs/NEXT-SESSION.md` 配合使用。

> **2026-10-26 前置说明（务必先读）**：下文是本目标在**较早阶段**的完整表述，其「当前卡点」是 `ui_state=5` / CA_LOADING。**后续调查（[状态记录 §1000–§1084](../1649370-STATUS.md)）已把障碍定位到更根本的层面：这个离线镜像缺少「驱动层」。**
>
> - 地图加载器 `0x456510`、表填充器 `0x44B310`、加载流程 `0x5C83D0`/`0x5C8150`、20 个具名派对事件表、名字分发器 `0x480840` 全部存在且正确；
> - 唯一能驱动它们的函数 `0x4F8CF0` 未导出、零引用，8 个段里都没有指向它的指针（§1070/§1071/§1083）；
> - 进入房间循环的两条路都经过它（§1072）；会话管理器 `[0x84ABB08]` 无写入者（§906）；房间索引只减不增（§1019）。
>
> 同时，`RELEASE.md` §3 记录的是**另一条独立路径**（服务端快照路径）的障碍：逐字段 playerState 编码仍有一个未建模分量（约 4.3 bits/字段），所以交付的 playerState 是空的。
>
> **两条路都走不通，且原因不同、互不缓解。验收第 5 项（`mp_crash_tropical` 中可控玩家的截图）在本镜像中无法达成。没有打过任何客户端补丁（§1073 说明了理由）。**
>
> **阅读顺序**：[§1074 确定性状态](../1649370-STATUS.md) → [§1084 阅读指南](../1649370-STATUS.md)（标注哪些早期结论已被取代）→ [§1022 镜像状态](../1649370-STATUS.md)。

---

在 E:\GAME\COD\codol-airedux\319 继续推进 CODOL Build 1649370（3.19.26.22，关服最后版本）的自建服务端 server1649370，目标是客户端可见可玩真实地图、对局可结束并回大厅。接手时先读 docs/DEMO-ANALYSIS.md、docs/SNAPSHOT-FORMAT-VERIFIED.md、docs/PROGRESS-AND-HELP.md，不要重复已验证项。

## 已确立，勿重复验证

协议层全通（getchallenge→connect→stats→gamestate→snapshot）。快照头逐字节已知，含 **8 位 last_changed**。快照**只有 5 个内容块**（entities 0x471D80 / playerState 0x471980 / actors 0x471010 / 未识别 0x471560 / glass 0x4475F0，各只有一个调用点，全在 0x4723C4..0x4724CD 调度器内；0x671D80 只是头解析器）。

实体列表布局已解：门控位=正文 bit 1307/1308，计数=buffer[164] 一个整字节，ID 是三段式 `((byte163>>5)&7)|(byte165<<3)|((byte166&1)<<11)` 且跳过 byte 164（因 0x66EC30 跨字节时从字节游标续读），可任意指定并已由构造验证 4048→8。

实体增量是模式操作序列而非字段循环：changed 位 → 模式选择器 → 13 项跳转表 0x671B2C；模式 3 读 11 位入 [stream+0x24]、模式 4 读 -97 入 [+0x28]、模式 1 提交并写三浮点到 [edi+0x24]/[+0x2C]/[+0x28]，已实测写入 3.5806/1.0/0.1。位置分量=gate(1 位)+scale(1 位，常量 0xDB1118=5.0)+value(5 位)。

先发无实体快照再发有实体快照，可实现 net_state=10 与实体计数=1 共存。

## 当前卡点（判据已纠正）

`net_state(0x76446B0)=10` **不代表**进对局。唯一验收判据是 **`ui_state(0x84ABA50) != 5` 且截图里出现地图**。

现状：ui_state=5、黑屏+右下角转圈，两张间隔 1 秒的截图不同（确认转圈在动=确实在等待，不是画不出来）。

调用链：0x803780 读单例 [0x8269774]（0x1618 字节，惰性 getter 0x803830）→ 0xB7A670 → 0xBA0780 映射 → 结果为 2 时 0x8037D6 选 ui_state=5。决定字段是 `[sub+0x5E8]`（sub=[单例+0x4F4]）：实测 `[+0xC8]=2`、`[+0x644]=0`、`[+0x5E8]=3`；0xBA07A4 处 `sete al; inc eax` 使 `[+0x5E8]==3` 恰好产出 status 2。

+0x5E8 的写入点：0xBA3C47(=3，同时清零 +0x5EC/+0x5F0)、0xBA3DA3(=2)、0xBA3252(=1)、0xBA3460/0xBA3661/0xBA40AA(=0)、0xB83920(=1 字节)、0xB824AC(析构体内重置)。状态 3 的前提是 `[obj+0x5FC]` 的 8 字节令牌比较成功（0xBA3C05..0xBA3C1A，call 0xB73FE0）。

未定位：如何离开状态 3。旁证：客户端连接状态名为 CA_DISCONNECTED/CA_CINEMATIC/CA_LOGO/CA_CONNECTING/CA_CHALLENGING/CA_LOADING/CA_CONNECTED，我们卡在 **CA_LOADING**。

已失败的杠杆：flags 字节 0x0C→0x08、覆盖全部 5 个内容块、推进 serverTime，均不能解除等待。

## 资源层：已 settled（2026-10-24）

`.ifs` 不是待拼接的碎片，而是「172 B 头 + CRLF 名单 + 16 B MD5 + 若干**完整签名 fastfile**」的容器。合法 fastfile 长度恒为 `0x115 + N*0x2000`（277 + N*8192）；k 个成员拼接后 `mod 0x2000 = (277k) mod 8192`，只有 k=1 等于 277（277 与 8192 互素），**所以拼接方案被结构排除**。`lf_*`/`lf_hi_*` 里 `IWff` 出现 0 次。

原先 overlay 里的 `mp_cross_fire.ff`（41,648,405）是 **2.6.9.7 的 365 二进制**，只改了 `0x8` 一个字节（`0x6D→0xCD`）冒充 461。现已换成真 461（`37,331,221`，来自 `ff_init_mp_cross_fire_V70.ifs`，签名/哈希链/zlib 全通过，240 asset）。`common_gametype_mp.ff` 的非法版（34,783,232，`mod=0`）也已换成合法 34,693,397。

**结果**：overlay 现在是**全真 461**，客户端正常启动、跑到 net 10、持有一个实体；但 `ui_state` 仍为 5、`[+0x5E8]` 仍为 3。**因此资源层不是卡点，可视为 settled**。（此前"换成 461 会崩"是启动器 30 秒超时误判。）

## 本阶段主线：用 2021-08 demo 复原对局

`E:\GAME\COD\使命召唤OL\main\demo\` 有 **22 个停服当月真实对局 demo**（21 war / 1 cha），样本 `0C-2021-8-26[19-26-24]war.demo` 用地图 **mp_crash_tropical**、模式 war，含明文 configstring（如 `d 3635 UK_spawn_music_mp_crash_tropical`）、dvar、UI 事件与尾部 asset 清单，是缺失的"正确数据样本"。

地图资源在 `E:\GAME\COD\使命召唤OL\IIPS\IIPSDownload\`（**975 个 .ifs**）。

`.ifs` 解包规则已验证：magic `nifs`，头 172 字节，fastfile 从第一个 `IWff`（cross_fire 为 0x166、crash_tropical 为 0x176）到下一个 `IWff`，fastfile 头为 `IWff0100`+u32 0x1CD(461)+u32 1；用 cross_fire 验证提取头与客户端可加载的 mp_cross_fire.ff 逐字节一致。

但单个 ff_* 不够：提取 37,367,685 vs 可用 41,648,405，差值≈lf_* 包，故一个可用 .ff 应为 **ff_* + lf_* + lf_hi_* 拼接**。

## 下一步执行顺序

1. **让客户端播 demo（最高优先，决定性）**：`mp_crash_tropical` 已是 overlay 里完整合法的真 461 三件套，22 个 demo 在 `E:\GAME\COD\使命召唤OL\main\demo\`。启动客户端（跳过 server/ring_bridge），执行 `cl_demo_play <demo>`。**出图 = 渲染与地图管线完好，缺的完全在服务端该发什么**；仍黑 = 该构建无法渲染此图，是硬限制。
2. 若播通，抓 demo 播放期间的接收路径，或静态解析 demo 帧，取得帧格式（PlayDemo VA 0x00DC5B98→代码 0x0020967C、cl_demo_play VA 0x00DC5BA4→0x002096B1；字符串位置是文件偏移，代码引用用 VA，须经 section 表换算）。
3. 从 demo 提取 `gamestate → baseline → 首帧快照` 的真实字节作为模板，套到 `mp_cross_fire`（或直接用 `mp_crash_tropical`），由 server1649370 下发。
4. 用 `ui_state != 5` 加截图验收。
5. 若 demo 路线不通，回到卡点 §5 的调用链：查 `[+0x5E8]` 如何离开 3（读 `0xBA3xxx` 那组处理，或找 `[obj+0x5FC]` 令牌比较之后的会话级消息）。

## 约束

坚持 1649370 不动摇；服务端保持 snap_trace/configstring/command 日志；每轮更新 `1649370-STATUS.md` 与 `PROJECT_STATUS.md` 并做本地 git commit；不因困难暂停工作流；不限制对话轮次直至目标达成。
