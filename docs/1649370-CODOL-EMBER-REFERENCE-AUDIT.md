# codol-ember 全库参考索引（2026-10-29）

> 2026-10-30 再次 `git fetch origin`：本地与远端 `main` 仍同为 `f784a77`。围绕灰色对局、实时模拟、ACK 历史、武器与赛后流程的具体适用点及边界见[Ember 对局实现资料](1649370-EMBER-MATCH-IMPLEMENTATION-REFERENCE.md)。

本地仓库：`E:\GAME\COD\codol-airedux\319\codol-ember`。远端 `https://gitea.codolai.win:2096/ember-forge/codol-ember.git`；已从 `28368dd7a3e57ec2c77db2dadad9216ba7e86531` 快进到远端 `main` 的 `f784a77f34f10698d481b1b23cf187b81d49bd02`（提交日期 2026-10-23 00:04:33 +08:00）。此前存在的两个未跟踪 `工具-tools/lobby-reproduction1604220/extracted*` 目录仍原样保留。这里是**参考库**，不是本项目的运行时或服务端源码；没有复制它的整套文件，也没有启动其服务。

2026-10-29 再次 `git fetch origin main`，本地 HEAD 与 `origin/main` 均为 `f784a77f34f10698d481b1b23cf187b81d49bd02`。本索引按**整个仓库的资料**建立，不只考察最新提交；`git ls-files` 列出 618 个已跟踪文件，其中工具、规格、研究报告三个目录分别有 409、15、111 个文件。两个既存未跟踪提取目录不计为已发布内容。该计数包含工具代码、合成样例与文档，不代表逐个文件已完成动态验证。

## 全库导航：遇到问题从哪里开始

| 问题 | 首选入口（均相对 `codol-ember/`） | 可迁移的内容与边界 |
|---|---|---|
| 版本、客户端身份、证据来源 | `版本信息-builds/1649370/manifest.json`、`项目文档-docs/sources.md`、`项目文档-docs/guides/build-identification.md` | 先对照 SHA 与 Build，再解释其他报告的地址和偏移；`qa-3.3.3.3` 与 1604220 只能作比较。 |
| 1649370 登录、大厅、客户端启动 | `研究报告-research/1649370/auth-lsg/`、`startup/`、`技术规格-specs/1649370/crossproxy/`、`工具-tools/crossproxy-{frame,pipe}-inspector/` | 查服务入口、TLS 与本地接口的已知结构；CrossProxy 检查器不是游戏 UDP 解码器。 |
| 1649370 武器资源和枪模 | `研究报告-research/1649370/iips-resources/README.md` 及其 13 份报告、`工具-tools/ifs-semantics/`、`ifs2-read-host/`、`复现样例-fixtures/1649370/` | 用名称→ID→owner→整文件读取的分层，查资源是否能被找到；这些静态与合成结果没有证明当前第一人称 viewmodel 已绑定。 |
| 1649370 大厅、背包、赛后路由 | `研究报告-research/1649370/ui/`、`技术规格-specs/1649370/ui/`、`工具-tools/ui-semantics/` | 追路由、ready、数据绑定与结果页条件；界面模型不替代 `ui_state` 和实机业务验收。 |
| PVP/PVE 玩法资料 | `PVP资料-pvp/1649370/README.md`、`PVE资料-pve/1649370/README.md`、`通用资料-common/1649370/README.md` | 目前主要是索引与缺口声明。不能据此填造武器、子弹、碰撞或胜负规则。 |
| 比较 1604220 的服务端/大厅机制 | `工具-tools/lobby-reproduction1604220/README.md`、`launch319-reference/`、`dw-stun1604220/`、`native-ingress1604220/` | 借鉴拆层、回滚收据、连接归属和负控；不能跨 Build 复制协议常量。 |
| 比较 1604220 的业务和档案 | `工具-tools/ordinary-results1604220/`、`profile-wire1604220/`、`client-state1604220/`、`auth-envelope1604220/`、`lsg-mac1604220/` | 参考有界解析、档案校验与状态机验证手法；它们没有实现本 Build 对局输入或玩家状态。 |
| 研究和观测方法 | `工具-tools/pe-analysis/`、`ghidra-scripts/`、`etl-parser/`、`tvm-analysis/`、`项目文档-docs/standards/research.md` | 可复用证据记录与静态/轨迹分析方法，地址、偏移仍须本 Build 重验。 |
| 许可、贡献及材料边界 | `LICENSE.md`、`THIRD_PARTY_NOTICES.md`、`CONTRIBUTING.md`、`项目文档-docs/standards/offline-boundaries.md` | 原创资料的非商业条件与第三方独立许可必须保留；禁止把受保护资源或私钥当作参考代码迁入。 |

仓库的 `项目文档-docs/overview.md` 明确将“客户端能运行”“Auth/LSG 完成”“可操作大厅”“实际对局”分成不同阶段；`项目文档-docs/components.md` 明确说明大型服务端实现仍在独立工作区，未作为可核验的完整 1649370 游戏服务端发布。因此不能因 `codol-ember` 有较完整的 1604220 复现包，就称它已有可直接替换本项目的 1649370 对局服务端。

## 与当前 1649370 目标相关的资料

| 参考路径（均相对 `codol-ember/`） | 已确认的内容 | 对本项目的用法与边界 |
|---|---|---|
| `版本信息-builds/1649370/manifest.json`、`研究报告-research/comparisons/project-milestone-20261022/derived1649370.md` | 原版 EXE/Base 和派生离线镜像是不同身份，报告分别列哈希与实际路线。 | 用于核对 Build/运行镜像，不用原版文件名或目录名替代 SHA。报告属于 2026-10-22 截点，不能覆盖本项目 2026-10-28 的实机结果。 |
| `研究报告-research/1649370/iips-resources/`、`工具-tools/ifs-semantics/` | IFS/IFS2 名称、ID、归档 owner、整文件读取和缓存模式的静态/合成研究。 | 当追 AK-47 fastfile 注册及 `tag_origin` 绑定时，可据此区分“文件可读”“资源登记”“最终模型绑定”三层；该库没有证明我们的武器装载已完成。 |
| `技术规格-specs/1649370/ui/first-page-routes.json`、`match-select-data.json`、`研究报告-research/1649370/ui/` | 房间/赛后路由状态、`ui_played_mapname` 初始化门、`ui_eog_show` 和结果 provider 的有界语义。 | 为“正常结束对局返回大厅”提供后续可检验的 UI 状态线索。仅是静态和模型证据，不能把设置某个 dvar 当成已经正常结束对局。 |
| `技术规格-specs/1649370/crossproxy/`、`工具-tools/crossproxy-*-inspector/` | CrossProxy 管道外层及回调 body 的只读检查器。 | 属登录/本地接口路线，不是当前 UDP 游戏 `clc_move`；不能拿其帧格式解码玩家输入。 |
| `工具-tools/launch319-reference/`、`成果应用指南-project-integration/launch319-adoption.md` | 1604220 大厅参考的准备、回滚、输入清单和源码纠错方法。 | 可借鉴显式输入/恢复收据与 A/B 记录；其协议、补丁和资源不直接套入 1649370。 |
| `工具-tools/ordinary-results1604220/`、`profile-wire1604220/`、`client-state1604220/`、`native-ingress1604220/` | 2026-10-22 新并入的离线协议、档案、状态与传输工具，配有合成测试。 | 可借鉴有界解析与正负控设计；均为 1604220 资料，未提供可直接移植的 1649370 `usercmd`、playerState 或对局服务端实现。 |
| `PVP资料-pvp/1649370/README.md`、`通用资料-common/1649370/README.md` | 玩法和共享资源的索引，明确武器/战斗具体条目尚待独立来源。 | 用于找资料及避免把 UI 路由误当作完整 PVP 对局规则。 |

2026-10-23 新增的四个提交主要是 1604220 离线工具整理与双 Build 阶段报告；全库原有的 1649370 UI、资源、启动和 CrossProxy 材料也已纳入上述索引。当前真正的玩家输入解码线索仍来自同工作区的 `他人文件参考/CODOL-Member-Preview-20261026/native-engine/source/src/codol/player/codol_usercmd.c`，须对照本项目 r762–r765 的真实包验证，不能因来源相近而误记为 Ember 仓库成果。

附带的 `D:\Tencent\QQ_Files\（仅想参考群主项目}CODOL参考项目图文教程-AI协作版.docx` 提供另两个私有参考仓的地址和克隆操作指引。它是用户提供的参考材料，内含给 AI 的委托文字；没有据此申请凭据、克隆仓库、改 AGENTS 或运行服务。本轮仅读取其资料入口并继续使用已存在的本地参考。

采纳这些资料时，按具体文件、Build、来源提交和证据类型标注。`codol-ember/LICENSE.md` 对原创成果设非商业使用条件；第三方文件仍按其独立许可。不要把参考仓、私有资源或凭据整份复制进本项目提交。
