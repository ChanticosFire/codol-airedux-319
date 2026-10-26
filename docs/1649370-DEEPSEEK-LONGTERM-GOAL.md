# 交给 DeepSeek 的长程目标：CODOL Build 1649370 可操作对局

> 2026-10-26 交接时点。将本页全文作为接手任务；以磁盘、进程和新实验为准，不把历史总结当作当前事实。项目根：`E:\GAME\COD\codol-airedux\319`。

## 目标与验收

使 Build **1649370** 客户端经自建 `server1649370` **真实连接**进入 `mp_crash_tropical`，属于本地玩家的角色能通过游戏操作移动和射击，结束对局可返回大厅。必须逐项以真实客户端操作、原生状态、服务端日志和截图验证：

1. 游戏服日志出现真实 `connect` 与 `stats`；
2. 客户端网络状态经握手进入有效对局（历史实测 `CA_ACTIVE=10`）；
3. 对局结束后回到功能完整的大厅；
4. `ui_state != 5`，没有错误弹窗；
5. 截图及输入实验显示玩家**自行**移动和射击、有相应武器/HUD，不是 demo 播放器、空地图、黑屏、外部脚本单方面移动镜头或仅有 `net=10`。

截至交接，**第 5 项未达成**。不要把“按 W → 外部脚本改快照 → 画面平移”的历史实验（`1649370-STATUS.md` §553–559）直接认作完整玩家移动；射击从未验证成功。

## 必须沿用的运行路径与资源

- 唯一近期实证能进大厅和地图的路径是 `E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime\codol1649370-offline.exe`。用 `tools/launch_1649370.py --reuse-runtime r107flow`；**不再生成或复制约 15 GiB 的运行时**。它是可进图的离线 EXE，不能因“非零售 EXE”否定已经观察到的真实连接。零售 `codoMP_client_shipRetail.exe` 的 TP/TCLS、100 大厅问题属于另一条未完成路线。
- 启动顺序、端口和必需补丁：`docs/1649370-KNOWN-GOOD-STARTUP.md`。`+cl_demo_play testdemo` 必须保持删除。`runs/_patch_r336.py` 的两处武器注册表绕过是可进图所需，但没有补齐缺失的武器定义。
- `resources/1649370/README.md` 是资源总表；`manifest.json` 是建表时副本的 SHA-256，不代表后来变化的活数据库。私钥、账号数据库、运行时二进制在 Git 忽略的 `resources/1649370/local/`；不要提交或公开。关键测试文件已有独立副本；r528 184 B 候选另存 `local/unverified/r528-weapon1-codec11.bin`。
- 当前本地档案 `data/v1649370/local.sqlite3` 已恢复为 **revision 1227、selected character index 0 / ID 570**；r528 试验前的 revision 1226 完整隔离于 `resources/1649370/local/profile/quarantine-r528-weapon-test.sqlite3`。恢复来源为同目录 `restored-public-baseline.sqlite3` 的 public blob，只替换 public，保留现有 secure 和 7,208 条 entitlement。继续测试前先备份；不要把隔离库重新当活库。
- 交接时没有客户端进程；r528 临时游戏服、桥和 r527 LSG 已结束。较早的 UDP 28969 游戏服 PID 11920 当时仍在运行，启动新服务前**重新查询实际进程/端口**，不要信任 PID 长期有效。

## 最近实证与关键纠错

1. r523/r524：同一运行时真实连接、进入大厅与 `mp_crash_tropical`，不拉 TP、不报 100；无可控玩家。r524 用有效 profile 时部署背包能显示武器，但入图后原生档案会出现无效装备 ID，曾把错误值写盘。详见状态 §1105–1106。
2. `tools/launch_1649370.py` 现有 `profile_catalog_error` 与 `LocalProfileBridge.initialize` 保存保护，r526 **实机拒绝**一次无目录主武器 ID `1900489201` 写盘，保住有效数据库；它只拦 `service.save`，**拦不到 `LocalProfileBridge.save` 前段的 `inspect_snapshot` 异常**。不能说它彻底修好了档案。
3. r526 把 16 B `snapshot-ps58.bin` 第一次送到当前可进图客户端，日志 `connect=1`、快照 50 帧，`net=10/ui=0` 但世界黑屏、无玩家；已正常返回大厅。它不能替换完整 182 B 快照。证据 `evidence/experiments/20261026-r526-ps58-summary.json`、状态 §1107。
4. r527 全新、带同一保存保护的实例，进图前“仓库→背包”能显示完整 Loadout，“储物箱”显示物品网格，角色外观分类 190 件；原生库存与数据库均为 7,208。r525 入图后仓库空白发生在保存拦截前，故**保存保护不是仓库空白原因**。入图/回大厅后的前端状态故障具体点未定。证据 `evidence/experiments/20261026-r527-warehouse-control.json`、状态 §1108。
5. r528 读取**当前客户端实际描述符**：`0xDA8520 + 57*12` 是 `{offset=76, codec=11, hint=0}`，即 `ps.weapon` 使用正宽 11 位编码。历史 §597 曾把该字段当 34 位绝对编码插入，编码假设错误。由 `r522-clean-compact.bin`（182 B）在**文件 bit 428** 将原 `changed=0` 替换为 `changed=1, nonzero=1, value=1 (11 bit LSB)` 共 13 bit，生成 `runs/r528-weapon1-codec11.bin`（184 B，SHA-256 `5cd12dde23ad3f35d0da829374ea918a9a564dbb022a8cacd933996de77332ac`）。客户端进 `net=10` 约 0.4 秒即退出；日志 `connect=1`、`stats=0`、`gamestateupdate=5`、候选快照 50 帧。同一时点出现原生访问违例及 `Runtime selected character missing; refusing save`，启动器 `stop_reason=unhandled_exception`、`child_terminated=true`。**因此不能判定 13 位候选的 parser 成败，更不能说武器已出现。**脱敏汇总 `evidence/experiments/20261026-r528-weapon-handoff.json`；原始本机日志 `runs/r528-weapon-gs.jsonl`、`runs/r527-launch.out`、`r107flow/reuse-c06359f6/events.jsonl`。
6. r527 在试验前后档案自动保存多次，selected character 从 570 经过多个目录内 ID 到 15765，最后运行时读成缺失。那些中间 ID 虽在目录中，不能仅凭目录命中认定是有效选中角色。已隔离 revision 1226 并恢复 public。此行为与客户端 UI 预览、对局切换或快照的关系尚未分清。

## 接手后的先后顺序

1. 核对 Git HEAD、工作树、当前进程/端口、资源副本和活数据库；只在必要时正常关闭当前客户端。不要 `git checkout --` 清理“不属于任务”的未提交改动，先审语义。每次实验独立命名日志和候选快照。
2. 修好**档案采样导致启动器终止客户端**的路径：在 `LocalProfileBridge.save` 对“运行时 selected character 暂缺”作有界跳过并记录，保留最后有效磁盘档案；不能全局吞异常，也不能保存零/乱码 ID。用同一完整基线快照对照，确认没有因保护逻辑掩盖原生崩溃。
3. 对 182 B 已验证可显示地图的 `runs/r522-clean-compact.bin` 建立**逐字段解码/重编码**和完整 bit/byte 游标校验。描述符来源要读 Build 1649370 客户端本体；历史轨迹给出 `weapon` changed 在客户端 bit 460 / 文件 bit 428，但 §598–599 曾有相反换算，务必在新鲜客户端上用只读 parser hook 重新验证。增字段后必须连同后续 ps、实体、尾段正确重编码，而非只把余下原始 bit 顺移；对齐和 EOF 也须验证。
4. 一次只改一个语义，先证 `ps.weapon` 被正确解析并出现在 snapshot 与 cgame/HUD，再补足玩家实体、玩家名/configstring 与缺失武器定义。`client_number=0` 和 `1735=Player` 已单独实测无效，勿重复当作新方案。没有武器/HUD就不能验收射击。
5. 用真实按键和鼠标与服务端 usercmd/快照回路验证移动、射击、弹药或命中反馈；保留操作前后截图、原生状态、网络日志。最后验证正常退出后大厅功能与仓库仍可用，避免只看大厅背景就判定返回成功。

## 工作约束与报告格式

- Build 固定 1649370；不得改成 demo 回放、零售客户端其它 build、仅注入 UI 的替代路线。任何候选都必须区分**构造、自洽校验、送达客户端、parser 接受、画面可见、可操作**六个层次。
- 不向用户要求手工按键、截图或选路线；自主操作与判断。不要用 `run_match.py` 的 `kill_stale()` 清理当前实例；不要杀 `launch_1649370.py --until-close` 的 Python 父进程。可以正常 `quit` 或经游戏 UI 退出；`disconnect` 是历史上能回大厅的命令，`switchtomainmenu` 会杀进程。
- 避免 `cbuf_1649370.py` 堆积命令导致“客户端指令溢出”与空手；每次只注入必要的单条命令。不要把用户存档、密钥、含玩家名的截图提交 Git；可提交脱敏 JSON 证据，私有截图放 `runs/`。
- 每轮更新 `1649370-STATUS.md` 与 `PROJECT_STATUS.md`，给出具体实验输入、哈希、进程/端口、原生日志、截图及结论边界；本地 commit 并 push `origin main`。任何诊断失败都继续选择下一条可行路线，不能把短暂 `net=10` 或“客户端没崩”写作完成。
- 原长程目标五项全部以当前实证复核后才宣告完成。`resources/1649370/README.md` 和 `docs/1649370-KNOWN-GOOD-STARTUP.md` 是入口；`1649370-STATUS.md` §1105–1109 优先于旧 `HANDOFF-1649370.md` 与 `LONGTERM-GOAL-1649370.md` 的过时结论。
