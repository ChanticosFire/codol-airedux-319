# 给 DeepSeek 的长程目标：Build 1649370 可玩对局

> **历史目标稿，当前执行入口已改为 [1649370-HANDOFF-CURRENT.md](../1649370-HANDOFF-CURRENT.md)。** 本稿停在 r675；r731–r733 已证实 AK-47/30 HUD 与 `ui_state=5` 并存、第一人称枪模仍缺。请勿按下文旧“弹药为 0”的状态继续推断。

更新：2026-10-27。根目录 `E:\GAME\COD\codol-airedux\319`。本页是最新执行入口；旧交接中的“无地图”“无武器 HUD”“活库 revision 1227”已过时。每轮先核对当前文件、进程、Git diff、哈希和日志。

## 目标与五项验收

让 Build 1649370 经自建服务端真实连接 `mp_crash_tropical`，本地玩家用原生输入移动与射击，结束后返回大厅。五项必须在最终同一工作路径逐项复核：

1. 游戏服日志有真实 `connect` 与 `stats`，不是 demo。
2. 客户端完成握手，原生 `net_state` 达有效对局，服务端连续发快照，实际画面显示地图。
3. 对局结束后回到功能完整的大厅，仓库、背包、角色档案仍可用。
4. `ui_state != 5`，无 100、174、181 或其他错误弹窗。
5. 真实按键/鼠标与截图证明本地角色自行移动，第一人称枪模、手臂、弹药/HUD 可见，能够射击并有弹药消耗或命中反馈。外部脚本移动相机、仅见地图、仅有 `net=10` 均不算。

**当前第 5 项未达成。** 真实连接与地图已反复实测；部署 Loadout 已恢复。r673–r675 有 AK-47 HUD 图标和名称，仍然没有第一人称枪模/手臂，弹药为 0、显示“弹药用尽”，射击未证实。旧的回大厅与无弹窗证据需在最终武器路径上复核，不要拼接不同实验的局部结果。

## 最新实证与卡点

- r670 把 35 个复合武器 configstring 从槽 1224–1258 移至 1136–1170；CS12246 后改为 1171。真实客户端注册 2305 条且无 181。r671 有非零 `ps.weapon=78` 但出现 174。r673 恢复原武器 handler、lookup 分支、`0x58F3B9` 按 ID 取表，并用进程内精确名称查找后，稳定 `net=10`、`weapon/primary/altWeapon=78`，出现 AK-47 HUD，但弹药 0、无第一人称枪。表项 `[0x1C166E8+78*16+4]` 仍读 0，不能声称模型缓存已填好。见 `1649370-STATUS.md` §1264–1266、`evidence/experiments/20261027-r672-r674-weapon-hud.json`、私有 `runs/r673-init-index-screen.png`。
- r674 单独设 `viewmodelIndex=78`，原生字段确为 78，画面无变化。r675 尝试在 playerState 尾段加 30 发 clip 候选，仍稳定 `net=10` 且有 AK-47 HUD，但弹药仍 0、无枪模。该候选**未证明线格式正确或被解析器接受**，只证明没有产生可见弹药。见 `evidence/experiments/20261027-r675-clip-probe.json`、私有 `runs/r675-clip30-game.png`。
- 活库 `data/v1649370/local.sqlite3` 已由完整 `resources/1649370/local/profile/pre-r640-certenv.sqlite3` 恢复，SHA-256 `06f7a93bc8f818461fc0267f464bb3fa0e3801ac999462fc54eb8cc512af2f70`，SQLite integrity `ok`；r675 实验库隔离为 `local/profile/quarantine-post-r675.sqlite3`，不可覆盖或丢弃。r675 客户端/GS/bridge 按确切 PID 结束；每轮仍重新查进程与端口。

## 运行与资源

只复用 `E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime`，**不要再复制/新建约 15 GiB 运行时**。启动入口 `tools/session_up_1649370.py`，流程 `docs/1649370-KNOWN-GOOD-STARTUP.md`；`tools/launch_1649370.py` 必须保持无 `+cl_demo_play testdemo`。r673 的诊断选项为 `--restore-weapon-handler --restore-weapon-lookup-branch --restore-weapon-init-indexing --weapon-lookup-fallback`；gamestate `runs/r672-composite-count.bin`，SHA-256 `2f6c517931e43216740e598e642e682e55674e0d15dd3f14a9ab196a9a7acedb`；r671 武器 78 快照作 HUD 对照。这些进程内补丁不是最终服务端协议完成的证明。

资源总表在 `resources/1649370/README.md`，副本索引在 `manifest.json`。manifest 哈希是**建表时**的副本哈希，不代表活库；README 顶部 revision 1241 更新优先于页内 revision 1227 旧段。 `resources/1649370/local/` 包含私钥、账号库和二进制，已忽略，**永不提交或公开**。大型镜像是共享内容的硬链接，运行仍从原 `r107flow/runtime`；改文件前区分硬链接与独立备份。

## 接手顺序与约束

1. 保持 r673 对照，追踪 cgame 从 `ps.weapon=78` 到第一人称模型、手臂创建的真实门控：武器表项、模型注册、装备状态和必要实体/PS 字段。找出具体空返回或条件，不把 HUD 图标当枪模。
2. 独立定位 Build 1649370 的弹夹/备用弹药线格式和客户端内存字段。r675 的 clip 编码是**未验证假设**；先用实际描述符或真实样本核对索引、位宽、顺序，再做单变量实验。逐层区分编码自洽、送达、parser 接受、原生字段、HUD 与射击。
3. 枪与弹药可见后，记录原生 usercmd、服务端处理、连续快照及输入前后截图，验证玩家自行移动和射击，再联合复核结束回大厅、仓库/背包、`ui_state` 和无弹窗。
4. 每次试前备份**整库**；异常保存只隔离到忽略的 `local/profile/`，试后从核验过的完整基线整库恢复并检查哈希/integrity。不要用过时 manifest 推算活库，不丢隔离备份。
5. 不用 `run_match.py` 的 `kill_stale`，只结束本轮确切 PID；不要堆积 `cbuf_1649370.py` 命令造成指令溢出；不要让用户代为按键或截图。清理或回滚工作树前先看 diff 语义，未提交改动可能是修复。
6. 每轮更新 `1649370-STATUS.md` 和 `PROJECT_STATUS.md`，记录输入、哈希、原生日志、截图与结论边界；只提交/推送安全代码、脱敏证据和文档。**不得宣称未经实测的成功。**
