# CODOL 3.19.26.22 / Build 1649370 本地服务端研究

本项目正在为 **CODOL 3.19.26.22（Build 1649370）**研究本地服务端。当前目标是让该版本客户端通过本地服务自然登录，进入由服务端驱动的真实地图，完成可玩的对局，并在结束后返回大厅。

**当前目标版本是 1649370。** 此前针对 Build 1604220（客户端显示 3.19.26.17）和 2.6.9.7 的实验保留作参考；仓库中仍有相应的历史记录，但它们不代表当前路线。

## 当前进度（2026-11-05）

本仓库的 `server319` 和 `server1649370` 已使 Build 1649370 客户端经真实本地连接进入 `mp_crash_tropical`，显示地图和 AK-47 HUD。服务端在快照内发送同 Build 的可靠视觉命令后，客户端可显示彩色地图；客户端也会发送键鼠输入和 Tab 的 `s` 请求。服务端已能确认可靠 `b` 比分回复，但 Tab 数据板仍未显示。玩家在场内观察到瞄准、射击动作和声音；弹匣 30→22→30 回跳，说明权威弹药状态尚未贯通。ESC 背包仍为空。详见[当前交接](1649370-HANDOFF-CURRENT.md)与[证据](evidence/experiments/20261105-r825-r830-reliable-transport-audit.json)。

**完整对局尚未验收。** 五项验收须在同一可复现路径完成：真实连接和输入；有效地图与持续快照；正常结束返回且大厅资料完整；直接读取 `ui_state != 5` 且没有 100/174/181 错误；原生键鼠自由移动、持续可见的第一人称枪身与手臂，以及真实弹药、命中或伤害。传输 ACK、彩色截图或射击音效各自只证明其直接观测范围。[完整标准](docs/1649370-DEEPSEEK-LONGTERM-GOAL.md#唯一目标与五项验收)。

本项目复用本机唯一的 `r107flow/runtime` 隔离运行时；仓库不附带商业客户端、地图、账号库或本机证书。研究工具中的实验开关默认不代表稳定功能。协作者应先阅读[当前交接](1649370-HANDOFF-CURRENT.md)、[工作规则](AGENTS.md)和[仓库边界](REPOSITORY.md)，再选择可复现的实验。

## 仓库内容

| 路径 | 用途 |
| --- | --- |
| [`server319/`](server319/) | 本地 Auth、LSG 与登录侧服务。 |
| [`server1649370/`](server1649370/) | 1649370 游戏服务器、gamestate 与快照编码。 |
| [`tools/`](tools/) | 客户端启动、网络桥接、demo 解析、核验和实验工具。 |
| [`docs/`](docs/) | 目标、交接、协议格式和运行记录。 |
| [`evidence/experiments/`](evidence/experiments/) | 经整理的实验摘要与证据索引。 |

本地的 `runtime/` 保存隔离客户端副本，`runs/` 保存实验运行结果；历史上有少量 `runs/` 文件被跟踪，新的原始运行数据仍留在本机。游戏文件、资源包和本机实验数据需由使用者自行准备。仓库边界见 [REPOSITORY.md](REPOSITORY.md)，公开前检查见[仓库检查记录](docs/PUBLIC-SNAPSHOT-PROVENANCE.md)。

## 阅读与运行入口

1. 阅读 [长程目标](docs/1649370-DEEPSEEK-LONGTERM-GOAL.md)与 [当前交接](1649370-HANDOFF-CURRENT.md)的顶部更新，确认本轮要验证的问题。
2. 阅读 [1649370 状态记录](1649370-STATUS.md)、[已验证的快照格式](docs/SNAPSHOT-FORMAT-VERIFIED.md)与 [demo 分析](docs/DEMO-ANALYSIS.md)，区分实测结果和待验证假设。
3. 从仓库根目录查看服务与工具参数，再按本机准备的客户端、证书和资源选择实验配置：

   ```powershell
   python -m server319.lsg --help
   python -m server1649370.gameserver --help
   python tools/launch_1649370.py --help
   python tools/ring_bridge_1649370.py --help
   ```

游戏服务器的组件说明见 [server1649370/README.md](server1649370/README.md)。历史上的 [1604220 版本切换记录](VERSION-SWITCH.md)和相关交接文档仅用于追溯当时的实验决定。
