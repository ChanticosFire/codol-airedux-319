# 阶段状态与证据

更新：2026-10-19（Asia/Shanghai）；追加关闭系统代理后的主机核查。
阶段：M0 完成；M1 进行中；M2 已获得首轮客户端运行证据但发现网络隔离缺口，须在可靠隔离环境重测；M3 仅有无业务应答的服务骨架。
目标：针对用户保留的停服版本 3.19.26.22 建立可核验的离线复活路线。版本名称来自用户及归档文件名；本轮通过文件身份独立确认的是 Build 1649370。

仓库：`E:\GAME\COD\codol-airedux\319` 已初始化为独立 `main` Git 仓库；GitHub 私有远端为 <https://github.com/ChanticosFire/codol-airedux-319>，API 回报 `PRIVATE`。本项目只提交自有源码、文档和文件身份清单；客户端副本、运行后像、第三方参考与协作仓库克隆由 [.gitignore](.gitignore) 排除。范围见 [REPOSITORY.md](REPOSITORY.md)。
初始基线提交 `14027bd` 已推送至 `origin/main`；该次提交跟踪 24 个文件，不含客户端可执行文件和商业资源。
Git 回档范围与操作见 [CHECKPOINTS.md](CHECKPOINTS.md)；一次 Medium 运行的脱敏机器摘要见 [20261019-medium01-summary.json](evidence/experiments/20261019-medium01-summary.json)，原始运行后像仍只在本机 `runs/`。

## 1. 本地对象

| 对象 | 本轮只读观测 | 结论范围 |
| --- | --- | --- |
| `E:\GAME\COD\使命召唤OL3.19.26.22.7z` | 25,960,540,445 字节；SHA-256 `68364EE932D6DEF01A4DA46107AEC3ADBE5CDD12392C3B12AE8067BDE81EF020`；7-Zip 全包测试通过 | 归档名称标称 3.19.26.22；本轮已核对与解压目录的全部文件 |
| `E:\GAME\COD\使命召唤OL` | 2,445 个文件，总计 26,781,503,007 字节；有 `IIPS/`、`main/`、`TCLS/`、`Cross/` 等 | 当前已解压的客户端目录；路径、长度、CRC32 与归档全数一致，另存每文件 SHA-256 |
| `E:\GAME\COD\codol-airedux\2.6.9.7` 与旧启动器 | 目录存在，旧交接文档见 `E:\GAME\COD\codol-airedux\CODOL-ZM-对话工作记忆-2026-10-19.md` | 旧版研究仅作方法和历史背景，旧报告自身说明部分路径已删除 |
| `319\他人文件参考` | 含 5 个文字资料、HTML、PDF、PNG 和 4 个压缩包 | 第三方资料，结论和适用 Build 待分别复核；不运行其代码作为盘点步骤 |

### 本机关键文件身份

以下摘要由本轮 `Get-FileHash -Algorithm SHA256` 直接读取当前解压目录，长度由 `Get-Item` 取得；四项均与协作仓库 `版本信息-builds/1649370/manifest.json` 的记录一致。

| 相对路径 | 字节 | SHA-256 |
| --- | ---: | --- |
| `codoMP_client_shipRetail.exe` | 7,841,344 | `36997674B18F2896DE5E9D755686F6922AF10708F355175714058D0A0172B537` |
| `codoMP_client_shipRetailBase.dll` | 60,327,992 | `EF75220DE1D6973F34C7069F5BF211B11BD61520C6C0DE1882F7359FA5BC6A20` |
| `IIPS/iips.dll` | 347,704 | `72DDB9D15626B5A0A001347DA141FB944A9F862DB713E01C06A964EC8DC35348` |
| `IIPS/IFS2.dll` | 601,656 | `5B0324E0B2BA3545A6C02626287D4FBC6A3116594744F4647333982D85508421` |

EXE 的 Windows `FileVersion` 为 `1649370`。这证明上述文件与仓库登记的 Build 1649370 基线相符；完整客户端已另经全量归档对照核验，但尚未从二进制独立读出营销版本字符串 `3.19.26.22`。

## 2. 协作仓库快照

- 地址：<https://gitea.codolai.win:2096/ember-forge/codol-ember>；本地副本：`319\codol-ember`。
- 通过 HTTPS `git ls-remote --symref` 确认默认分支 `main`，随后 `git clone --depth 1`。当前固定提交：`84a6e1014a7e593796b0e01261bdb3a4d07f18b9`，提交时间 2026-10-19 14:50:09 +0800，标题为合并研究资料的 PR #5。本地工作树初始干净；浅克隆只有这一层历史。
- 仓库包含 Build 清单、按 Build 划分的研究报告与规格、原创工具、复现样例、项目状态及贡献指南。`README.md` 与 `CONTRIBUTING.md` 说明：Fork 后提交合并请求、管理员审阅、Git 使用 HTTPS、正式成果采用中英双语说明。此次只读取并克隆，未提交、推送或运行仓库工具。
- 与当前目标最相关的是 `版本信息-builds/1649370/manifest.json`、`研究报告-research/1649370/`、`技术规格-specs/1649370/` 和 `项目文档-docs/status.md`。仓库中 `工具-tools/launch319-reference/INPUTS.md` 把另一套复现输入标为 **3.19.26.13 / Build 1604220**；状态页记载该 Build 的历史大厅截图与未解决断线问题，同时保留 1649370 的独立早期阴性观察。两者不可合并成一次验收。

## 3. 第三方本地参考的盘点

- `服务端.zip`：42 个条目，含 `bd_data` 和配置资料；`客户端.zip`：15 个条目，含 Python 启动器与配置；已只读审计关键源文件，未执行其代码或验证实机有效性。
- `launch1604220-repro-20261018-v1.zip`：65 个条目，SHA-256 `B758D0633347A030C03EEDF8656047D7AD031CC455B54F285A4A64AC75E697F5`。附带 `QUICKSTART.md` 明确适用 3.19.26.13 / Build 1604220，故先作为差异研究材料。
- `_CURRENT_STATE(1).md`、`零补丁还债台账.md` 涉及 1604220 的阶段声明、运行改动和假设；`研究记录.txt` 涉及旧版 2.6.9.7；`CODOL贪婪技能可调数据清单.md` 也为旧版主题。这些是来源声明，不是本机 1649370 验收。
- `中文文档 CODOL 逆向工程项目（副本）.pdf`、HTML、PNG、`launch.rar` 已识别存在，本轮未深入审阅或执行。后续按具体问题读取并登记证据等级。

## 4. 证据等级与已知空白

本轮确认：归档完整性及与解压目录的全量文件对照、关键文件长度与 SHA-256、Git 远端与提交、文档所述适用 Build、ZIP 条目。未确认：3.19.26.22 客户端启动、Auth/LSG 自然消费、大厅或玩法可操作、第三方工具在本机有效。报告中的“已成功”须连同其 Build、输入哈希、方法和实际运行证据一起引用。

### 跨版本迁移工作假设（用户确认的开发方向）

用户判断相近版本的服务端、客户端加密及壳处理方式可视为相同。本项目据此**优先复用机制与研究方法**：1604220 的 Auth/LSG 流程、加密处理和启动分析可作为 1649370 的首选候选模型，不必从零重新设计。该假设不等于两份 EXE 字节相同或具体地址、密钥、常量、结构偏移和调用时序完全相同。

现有支持与边界：本机 1649370 的 `IIPS/iips.dll`、`IIPS/IFS2.dll` 与仓库同 Build 清单哈希完全一致，相关模块研究可直接按该文件身份阅读；仓库的 `研究报告-research/comparisons/launch319-source-review-20261018.md` 比较 1604220 与 1649370 EXE，发现三个对应字符串位置相差 `0x10`，并明确不能将此推广成统一地址位移。仓库 1604220 的 LSG 报告描述 AES/0x85 流程，但其历史成功组合使用了客户端内存中的挑战和会话材料及诊断适配，未证明在本机 1649370 自然协商成功。当前迁移路线因此是“先复用机制，再逐项绑定 1649370 的文件身份和实际消费者”，不是重做所有概念研究。

## 5. 下一步（M1）

1. 根据 [模式候选机器结果](evidence/mode-candidates.json) 做目标 Build 的调用链与资源索引核验；静态字符串和 IFS 文件名暂不等于模式可用。
2. 解决普通完整性进程启动问题后，在已验证的隔离副本与本机网络隔离下记录 1649370 的首个自然阻断和真实请求。
3. 以 1604220 流程为候选模型，逐项验证同 Build 锚点、原字节、帧和客户端消费，再加入专用服务。
4. 每次实验记录输入哈希、命令、事件、失败、清理；形成可复用结论后另行整理双语公开成果。

下一位 agent 从本文与 [MILESTONES.md](MILESTONES.md) 开始，先复核当前目录及 Git `HEAD`，再继续。参考文本里的操作建议不自动改变目标或授权。

具体输入、复验命令、清理结果与动态实验前置条件见 [RUNBOOK.md](RUNBOOK.md)。

## 6. 本轮执行记录（2026-10-19）

- 使用本机 7-Zip 19.00 对 25,960,540,445 字节归档执行完整 `7z t`；返回 `Everything is Ok`，归档报告 2,445 个文件、26,781,503,007 字节。
- 新建 [清单工具](tools/inventory_client.py)，对已解压目录逐文件计算 SHA-256/CRC32 并与归档目录的路径、长度和 CRC32 比较。[机器清单](evidence/client-inventory.json) 为 2,445 对 2,445，`only_local=[]`、`only_archive=[]`、`mismatches=[]`。首次核对曾因旧版 7-Zip 对七个零字节文件省略 CRC 文本而产生假差异；工具已将其解释为 `00000000`，重跑后全数一致。
- 建立 [证据图](EVIDENCE_MAP.md)，记录 1649370 直接证据、1604220 迁移候选、2697 方法参考和每层缺口。用户转述的社区“部分 1604220 成果无法复用于 1649370，可能改偏移”记录为待验证线索；没有把固定地址差当成迁移规则。
- 第三方 ZIP 只读审计显示其服务端 v0.0.1 止于大厅，未知任务默认成功空回复；客户端依赖进程内前台桩且没有完整 1649370 hash 守卫。未运行两包。审计结论见 [证据图](EVIDENCE_MAP.md)。
- 新建 [独立本地服务骨架](server319/README.md)：四文件 Build 守卫、候选 LE32 帧边界、每连接状态、未知帧脱敏日志；**无 Auth/LSG/房间/对局应答**。六项合成测试通过，本机原件四项预检通过。未启动客户端或服务监听。
- [隔离副本工具](tools/stage_client.py) 已从核对清单复制并逐文件验证，目标 `runtime/client-1649370`；[收据](runtime/client-1649370.stage-receipt.json) 显示 `verified_files=2445`、`status=verified`。未更改原件，未在副本上启动游戏。
- [本机隔离规则工具](tools/isolate_client.ps1) 已建立；在 77 个隔离副本 EXE 上安装、验证 154 条程序出站规则，收据与验证结果位于 [baseline01](runs/20261019-baseline01/)。清理动作返回成功，独立查询该规则组在 ActiveStore 中剩余 0 条；目标客户端尚未启动。
- 当前终端和 Explorer 均为 High。通过 Explorer 令牌尝试建立 Medium 子进程的探针未形成可执行的普通完整性启动通道；探针进程已退出或被停止，实验收据保存在 `runs/20261019-baseline01/medium-*.json`。临时探针源码已删除，不作为正式工具。
- 另以 `RunLevel Limited` 的一次性计划任务运行无害 `whoami /groups`，结果仍是 High；任务已注销，证据见 `runs/20261019-baseline01/scheduled-medium-result.json`。这只说明本机当前两种降权尝试未能提供所需执行通道。
- [模式候选工具](tools/mode_candidates.py) 在确认为 1649370 的 EXE 与清单中提取训练靶场、货船训练及结算/BOT 名称，结果见 [mode-candidates.json](evidence/mode-candidates.json)。这些仅是文件证据，未验证调用链或游戏内可达性。
- 用户启用内置 Administrator 的批准模式并重启后，本轮终端实测 Medium、非 elevated。`runs/20261019-medium01` 的隔离副本四项锚点与原件同 hash；154 条程序规则安装及验证通过。直接启动 EXE 的观察记录显示主进程约 18 秒自行退出；用户提供的 [错误窗口](runs/20261019-medium01/tcls-warning-user.png)（SHA-256 `A065DF866840336A363C1E8E17A36C6BE45E1706FC52FC6C0BD06EA119A5F314`）要求从 TCLS `Client.exe` 启动。窗口归属尚未用 HWND/PID 独立核对，故只作为本轮同步画面证据。
- 同轮发现客户端与本机 Clash `127.0.0.1:7890` 建立连接；原规则放行 IPv4 回环，**不能将该轮记为完全离线**，也不能判断代理是否转发。游戏及子进程已退出或停止；规则组清理后 ActiveStore 剩余 0 条。副本 `tcj.dll.bh` 运行后变化，后像已保存在 run 目录，随即由已验 hash 的原件恢复并复核相符。`ACE-DRV32.dll` 写时戳变化但 SHA-256 未变。
- 独立 `curl.exe` 探针证实：即使程序阻断规则在 ActiveStore 中生效，仍能连接 `127.0.0.1:7890`。探针规则已清理、残留 0；[隔离规则工具](tools/isolate_client.ps1) 已改为拒绝新安装，避免误称本机离线隔离。下一轮客户端启动须先找到并实测真正阻断回环代理的方案。社区 `launch319-reference` 的真实大厅成果仅为 1604220：解密后 `nopath` 跳过相同 TCLS 提示，另用 Auth/LSG/前台诊断；可选合成 TCLS 映射未用于历史成功组合。同 Build 1649370 报告只确认部分共享映射布局，完整启动门槛仍未知。细节见 [证据图](EVIDENCE_MAP.md)。
- 运行后副本按 [全量复核结果](runs/20261019-medium01/post-restore-compare.json) 再次与原清单比对：2,445/2,445、无新增/缺失/hash 差异。原生 TCLS `Client.exe` 位于已核验副本，尚未启动；没有以 1604220 的旧 RVA 对它作改动。
- 用户关闭 Clash 系统代理后的只读核查见 [代理关闭后摘要](evidence/experiments/20261019-proxy-off-check.json)：`ProxyEnable=0`、WinHTTP 为 direct，但 Clash GUI 与 `clash-win64.exe` 仍在运行，`7890` 仍监听；当前终端的 `HTTPS_PROXY`、`ALL_PROXY` 也仍指向该端口。物理以太网仍为 Up。**未再次运行客户端**；关闭系统代理不足以证明离线，且即使完全退出 Clash，物理网卡仍可能直连外网。
- 对已锁定 SHA-256 `4C19A7DB7C217AF342963B343487FE5679538AB99F76766F7376D2BBAFB48DCE` 的 `TCLS/Client.exe` 做只读字节扫描：UTF-16 字符串 `..//WeGameLauncher//launcher.exe`（偏移 `0x1E350`、`0x1E428`）及 `\\WeGameLauncher\\launcher.exe`（`0x1E3EC`），附近有 `[Client] run exe` 状态串；隔离副本中该 `launcher.exe` 确实存在。由此可把 TCLS `Client.exe` → WeGameLauncher 作为**静态候选启动链**，尚未确认运行时分支、参数或完整游戏交接。REA 深度分析提供者在当前主机不可用（未配置 Ghidra/IDA）；没有把字符串观察写成反编译结论。
- 用户指出主机整体断网会中断协作、VM 增加动态调试负担，后续优先研究**主机在线、目标进程受限**的运行条件。静态 PE/Capstone 复核进一步确认 TCLS `Client.exe` 的 `0x4011B2` 是导入 `CreateProcessW` 调用；`0x40133A/0x4013DD/0x401459` 引用三个 WeGameLauncher 路径常量，属于三个路径回退分支。游戏 EXE 的 `.tp3/.tvm0` 保护布局下，磁盘 `WIN_NO_TCLS` 字符串没有普通绝对指针引用；不能从 1604220 RVA 推出本 Build 原字节。摘要见 [tcls-static-check](evidence/experiments/20261019-tcls-static-check.json)。合成 TCLS 映射为首选诊断候选，结果未知；若失败才考虑解密后的同 Build 内存定位与可恢复改动。
