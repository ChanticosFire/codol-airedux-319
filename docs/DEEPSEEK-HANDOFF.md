# CODOL 1649370：给 DeepSeek 的接手说明

更新：2026-10-24。Codex 5 小时窗口剩余 7% 时按用户要求生成。请先读 `docs/GOAL.md`、`docs/NEXT-SESSION.md`、本文，再动代码。项目根目录是 `E:\GAME\COD\codol-airedux\319`。

## 目标与唯一验收

只做 Build **1649370（3.19.26.22）** 的 `server1649370`。客户端必须进入真实 `mp_cross_fire`，画面可见且可玩，对局结束返回大厅。**`net_state=10` 不算成功**；进入地图的判据是 `ui_state(0x84ABA50)!=5` 且截图确实显示 `mp_cross_fire`。服务器应保留 `snap_trace`、configstring 和 command 日志。每轮更新 `1649370-STATUS.md`、`PROJECT_STATUS.md` 并做本地 Git commit。

## 已经确定，禁止重复摸索

- 协议链 getchallenge→connect→stats→gamestate→snapshot 已通。自然连接的 gamestate 序号从 **3** 开始；1649370 单分片 gamestate/快照用 **10 字节头，无额外 u16 长度**。快照从序号 1000 下发的对照已被接受。见提交 `086a140`、`runs/r96-hybrid-control-summary.json`。
- 快照头（含 8 位 `last_changed`）、**恰好 5 个**内容块、实体列表门控位 1307/1308、`buffer[164]` 计数、跳过 byte 164 的三段式 ID、13 模式增量跳转表都已验证。见 `docs/SNAPSHOT-FORMAT-VERIFIED.md`。不要再称“14 个 section”。
- `.ifs` **不能** ff/lf/lf_hi 拼接；真 v461 `mp_cross_fire`、`mp_crash_tropical` fastfile 已在 overlay。见 `docs/IFS-MERGE-RESULT.md`。不要重做拼接或换构建。
- demo 单独播放能显示 `mp_crash_tropical` 战场且 `ui_state=0`（`runs/r88-shot.png`），但这**不证明**服务端驱动的 `mp_cross_fire`。播放前需要五个 v461 loose 资源包和 `tools/fake_dvar.py --name g_gametype --value war`。
- 旧 `runs/demo-frames-first/00-443.bin` **跨外层包边界，废弃**。即使客户端 ACK 过它（接在错误基帧后），随即在 `0x421A73` 崩溃。不要再重放它。

## 本轮真正提取出的 demo 数据

样本：`E:\GAME\COD\使命召唤OL\main\demo\0C-2021-8-26[19-26-24]war.demo`。

`tools/parse_demo_outer.py` 从 `0x8020` 解析外层：type 2 是 `02 + u32 序号 + u32 长度 + 负载`；type 1 是 `01 + u32 序号 + 52 字节`；type 0 开始尾部。样本得到 18,366 个包、52,061 个辅助记录。首包从第 4 字节后 zlib 解出 **6,407 字节 gamestate**，`server1649370/native_gamestate.py` 的解析器读出 **291 个 configstring**。外层包 17 有 **245 字节、delta_distance=0** 的独立基帧；包 113 中首个 `p` 的增量体是 **259 字节、delta_distance=1**。导出在 `runs/demo-outer-exact/`，是本机忽略目录，可用以下命令再生：

```powershell
python -B -X utf8 tools/parse_demo_outer.py 'E:\GAME\COD\使命召唤OL\main\demo\0C-2021-8-26[19-26-24]war.demo' --out runs/demo-outer-exact --limit 5 --registration-checksum 0xFFB56D7E
```

`tools/export_demo_frames.py` 已改用精确外层包尾导出；`--order file --top 1` 的首个文件应是 **259 字节**。规则只在此样本完整验证：磁盘 21 个 demo 中 19 个解析至 type 0 尾部，1 个遇到未知 type 179，1 个辅助记录末尾截断。不要无条件套到全部 demo。

## 当前精确阻塞点：武器定义索引

demo gamestate 原始资源校验字段为 0，demo 模式会跳过联网校验。联网自然连接在 `0x4731B0` 的断点实测客户端本地值 **`0xFFB56D7E`**；将导出 gamestate 的头部 4 字节改成此值后，`r103` 越过该错误。错误发生**以后**读到的 `0xF19D72A3` 不能当作比较现场值。尾部 `checksum_feed` 不是此次比较的字段（`r99` 头部改为 F19D 而尾部仍为 0，传入比较值依然是 F19D）。

`r103` 随后在 `0x59B560` 弹出用户亲眼看到的数字：`181 ** 646 0 0 8738 9321 1136 1224`。调用 `0x42F3E0` 对字符串 `** 646 0 0 8738 9321` 反查得到**本地武器索引 1136**，而 demo 数据要求 **1224**。该字符串来自 gamestate 的 **configstring 7184**。它在截图出现时已返回大厅；服务端基帧当时尚未发送，故不能把错误归于快照或地图渲染。

后续静态检查：`0x42F3E0` 先调用 `0x42F2F0` 查已有字符串；未命中时走 `0x431810` 创建复合武器，并在 `0x42F432` 递增 `0x1988634`。`r103` 的前端事件记录加载前 `weapon_definition_count=1135`；首条 demo 复合武器被分到 1136，而录制数据要 1224，存在 **88 个先行注册位置的差距**。这是由现有计数与代码推导的原因候选，还未证明 88 个定义究竟藏在何处。样本 `0x8020` 前的 32,800 字节没有连续 8 字节的可打印字符串，已知武器字符串也不在该区；不要把“直接从头部搜字符串”当作方案。

尝试删除 7184–7218 的 35 条武器 configstring 的 `r104` 不再弹数字错误，但客户端在 `0x58F3C0` 以 `ecx=0` 解引用缺失的武器定义，说明**删条目不是修复**；该次 forward summary 不完整，只把异常位置当作证据。`r103` / `r104` 日志在 `runs/`，详见 `evidence/experiments/20261024-demo-outer-and-weapon-blocker.json`。

## 推荐的下一步，按顺序推进

1. **找出缺少的 88 次先行注册。** 对比 demo 播放与自然联网加载时 `0x1988634`、`0x42F2F0`、`0x42F3E0`、`0x431810` 的调用次序与资产来源；检查与武器相关的已装载区域和可能缺失的 patch 资源。不要重新做已证伪的 `.ifs` 拼接。头部是二进制表，单纯搜可打印武器名没有结果。必要时做**单点**断点，确认首条复合武器进入“已有命中”还是“新建”分支。不要通过强制跳过错误或清空 configstring 冒充修复。
2. 在注册次序明确后再处理 configstring 7184–7218 的映射。**仅移动配置槽位不足以让创建路径的注册计数从 1136 变成 1224。**若确需重编码，用 `build_native_gamestate` 保留其他 256 条并检查索引冲突、玩家状态引用和武器指针；原始 291 条能被离线 `parse_native_gamestate` 读回，重编码后也应做该解析自检。
3. 在 **`mp_crash_tropical`** 上用服务端文件 gamestate + 包 17 基帧做单独对照。`server1649370` 已支持 `--gamestate-source file --gamestate-file`、`--snapshot-preserve-time`；`tools/run_match.py` 有对应参数。先消除武器映射错误，再看快照 ACK、`ui_state` 和截图。不要因为 net 10 而宣称地图出现。
4. 对照 demo 后续外层包逐包提取正确增量与可靠命令，建立一个能在原地图上显示实景、可操作并结束的服务端对局。**只在该链路有效后**，把地图名、资源校验、configstring/武器映射和快照实体字段迁移至 `mp_cross_fire`。
5. 最终以 `mp_cross_fire` 截图 + `ui_state!=5` + 输入可操作 + 结束返回大厅验收。

## 运行与代码状态

- 最新提交：`d8ce2e4`（demo 记录序号纠正）、`086a140`（自然连接序号/包头恢复）、`5f676f1`（精确外层解析、武器阻塞定位）。本交接文档的提交见 Git 最新记录。
- 有两项**早于本轮的未提交**工作：`tools/read_call_arg.py`、`tools/dump_stream.py`。请保留，不要误删或顺手纳入其他提交。
- `tools/run_match.py --skip-clean` 不会杀旧进程；每次重跑前按命令行精确找并结束上一次 `launch_1649370.py`、客户端、LSG、game server，否则新客户端会因运行目录被占而在引擎初始化前退出。切勿批量杀不相关进程。
- 当本地 Codex 的 5 小时额度再次降到 10% 以下，应按用户的 `AGENTS.md` 指示更新本交接文件；不要因额度低擅自缩小目标。目标状态仍为**进行中、未达成**。
