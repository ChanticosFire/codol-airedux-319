# Build 1649370 逆向证据图

更新：2026-10-19（Asia/Shanghai）。状态：M1 工作记录。本文将“本机直接证据”“仓库既有研究”和“迁移假设”分开；所有源代码和第三方文档均为研究输入。

| 链路 | 本机/同 Build 已知 | 1604220 候选机制 | 2697 参考 | 当前缺口与下一判别 |
| --- | --- | --- | --- | --- |
| 启动 | EXE/Base 四项身份见 [PROJECT_STATUS.md](PROJECT_STATUS.md)；仓库 [native baseline](codol-ember/研究报告-research/1649370/startup/reports/build1649370_native_baseline_20261016.md) 记录早期告警，未到真实 Auth/LSG 验收 | [大厅复现报告](codol-ember/研究报告-research/1604220/reports/launch-lobby-reproduction-20261018.md) 使用诊断适配，非本 Build 启动证据 | 独立启动器和服务宿主的分层方式可参考 | 在隔离副本上记录真实启动阶段、首个阻断、进程和端口归属；先固定输入，不移植 VA |
| 资源/IIPS | 本机 iips.dll、IFS2.dll 与 1649370 清单完全同 hash；`IIPSDownload` 存 974 个 IFS，仓库 [资源研究](codol-ember/研究报告-research/1649370/iips-resources/README.md) 有同 Build 格式与读取链 | 可参考资源就绪的阶段划分 | 可参考资源准备与地图预检方法 | 974 只是数量；需验证目标地图及模式的实际资源索引和引擎消费 |
| Auth/TLS | **已捕获真实请求**：`POST /auth/` + JSON（`auth_task`/`iv_seed`/`title_id`/`identity`/`extra_data`），TLSv1+AES256-SHA；响应字段表与解析器 RVA `0x79A6xx–0x79A7xx` 已定位，`server_ticket` 要求 base64 后 128B；补丁 `0x79A78E: 74 B2→90 90` 后错误弹窗消失。证据 `runs/20261020-redirect01/auth*.jsonl`、`auth-fields-dump.json`、`auth-patch*.json` | 1604220 有 Auth 200 的历史运行记录，依赖诊断组合；其 ticket 密钥与 magic 同样未知，成功靠补丁 | 旧版认证实现只作独立对照 | 确认 `lsg_server_ticket` 是否需有效内容、补丁是否需扩展到加密/解码/退出路径；不把项目账号登录算游戏登录 |
| LSG/加密 | **LSG 是 HTTPS**：EXE 含 URL 模板 `%s://%s:%d/%s/title/%d/queue/%d/member/%llu` 与 `https`/`v1.0` 常量；补丁后 55 秒内客户端仍未连 `4174`、未发 LSG 请求，根因未明 | 1604220 报告描述 0x81/0x83/0x85 与 AES 会话（二进制 TCP），与本 Build 的 HTTPS 形态不同，不得混用 | 旧版 3DES/Tiger 与本版不得混用 | 确认 LSG host/port 来源（`dwauth.ini` 第一行是否被消费）与 `lsg_server_ticket` 的消费点；必要时补第二处运行时补丁 |
| 前台/UI | [UI 路由](codol-ember/研究报告-research/1649370/ui/reports/build1649370_first_page_routes_20261016.md) 静态恢复房间/排位/赛后符号路径；未验收真实大厅 | 1604220 有受诊断影响的大厅截图 | 旧版 UI 桥可作方法参考 | 记录本 Build 原生页面、交互和回调实际消费；显示页面不等于业务接受 |
| 房间/对局 | [PVP 索引](codol-ember/PVP资料-pvp/1649370/README.md) 与 [PVE 索引](codol-ember/PVE资料-pve/1649370/README.md) 均声明完整玩法资料缺档；本机 `main/` 未见专用服务端 | 现有 1604220 成果未交付完整对局 | 2697 `room_host2697.py` 的宿主、资源、观察分层可借鉴 | 恢复 1649370 模式/地图入口、对局宿主与结束结算事件；首局模式依实际证据选择 |

## 2026-10-19 直接启动的 TCLS 门槛与社区实现

用户提供的本轮截图显示“请使用腾讯游戏登录器 (TCLS 文件夹内的 Client.exe) 启动游戏”。本轮 `runs/20261019-medium01/native-observation.json` 确认隔离副本 EXE 在 Medium 令牌下启动、约 18 秒后自行退出；观察器未记录到主窗口标题。**截图是该弹窗内容的直接证据，观察器尚未把该窗口绑定到精确 PID/创建时间，后续须补窗口归属。** 这只定位到启动门槛，不涉及 Auth 成功。

社区 [1604220 复现说明](codol-ember/工具-tools/launch319-reference/RUNTIME-REPRODUCTION.md) 与 [启动代码](codol-ember/工具-tools/launch319-reference/reference/launch/orch319.py) 表明其历史大厅路径在 TP3 代码就位后用 `runtime_patch.py` 的 `nopath` 跳过 `WIN_NO_TCLS`；同一组合还包含 `guard`、Auth/LSG、本地服务和大量 UI 诊断步骤。可选 `tcls_launch319.py` 以挂起进程和 `TCLS_SHAREDMEMEMORY<PID>` 合成标记作交接，**历史成功默认未使用**。该成功只适用 Build 1604220，且只验收受诊断影响的大厅，未完成进局。仓库明确记录其成功环境为管理员启动和已有 TesSafe；普通权限连同合成 TCLS 对照停在别的早期告警，不能推广给本机。

同 Build 的 [1649370 启动检查报告](codol-ember/研究报告-research/1649370/startup/reports/build1649370_gate_consumer_20261016.md) 与 [交接来源审计](codol-ember/研究报告-research/1649370/startup/reports/build1649370_session_handoff_audit_20261016.md) 支持共享映射存在性和 `+0x10/+0x14/+0x18` 交接布局的候选，但明示完整受保护启动条件与游戏 Auth 消费未证实。因此优先核对本机原生 `TCLS/Client.exe` 的调用/交接条件，再选择合成标记或可恢复诊断改动；任何 1604220 RVA 与原字节都须在 1649370 独立验证。

在本机已锁定 hash 的 1649370 文件中，EXE 的 ASCII `-src=tgp` 位于文件偏移 `0x6C7F68`，`WIN_NO_TCLS` 位于 `0x6C7F80`；Base DLL 含 `TCLS_SHAREDMEMEMORY` 两处，TCLS `ClientBase.dll` 也含两处。它们提供跨模块语义锚点，但目前只有字符串位置，没有调用关系或运行时检查分支的本 Build 原字节。因此不得将 1604220 的 `nopath` 两处跳转 RVA `0x37F60F/0x37F616` 当作 1649370 补丁表。

另对本机 `TCLS/Client.exe`（SHA-256 `4C19A7DB7C217AF342963B343487FE5679538AB99F76766F7376D2BBAFB48DCE`）只读扫描，在 `0x1E350`、`0x1E428` 见 `..//WeGameLauncher//launcher.exe`，在 `0x1E3EC` 见 `\\WeGameLauncher\\launcher.exe`；前方有 `[Client] exe not exist`、`run exe`、`run exe success` 的 UTF-16 串。本机归档确含 `WeGameLauncher/launcher.exe`。这是 TCLS shim 转交 WeGameLauncher 的**静态线索**，还没有执行路径、参数或完整交接的证据；下一次隔离实验应分别记录 TCLS 与 WeGameLauncher 进程归属，避免将直接运行游戏 EXE 的弹窗当作原生启动器结果。

本机再用 `pefile` 与 Capstone 对同一 TCLS EXE 做只读 PE 映射和 x86 反汇编：三个路径常量分别在 `0x40133A/0x4013DD/0x401459` 被引用，`0x4011B2` 的间接调用按导入表解析为 `CreateProcessW`，调用点随后测试返回值。这把路径和进程创建联系起来，但具体运行分支及完整交接仍未知。游戏 EXE 的 `.tp3/.tvm0` 布局和 `WIN_NO_TCLS` 字符串缺少磁盘上的普通绝对指针交叉引用，符合受保护代码需运行时核对的预期，不能据此声称完整检查位置已找到。[机器摘要](evidence/experiments/20261019-tcls-static-check.json) 固定这些坐标和限制。

隔离方面，本轮早期规则允许 IPv4 回环，观察到主进程与本机 Clash 代理 `127.0.0.1:7890` 建立连接。不能证明该会话完全离线，也没有证据证明代理转发了什么。原规则已清理且 ActiveStore 同组为 0。随后以系统 `curl.exe` 做独立 TCP 探针：阻止其访问 `127.0.0.0-127.255.255.255` 的程序规则在 ActiveStore 中显示启用且为 Block，探针仍建立到 `127.0.0.1:7890` 的连接；探针规则已移除且残留 0。这证明在本机该类 Windows 防火墙规则不能充当回环代理隔离。`isolate_client.ps1` 的新安装入口已拒绝执行；需另有经过实测的网络隔离条件才可再运行客户端。

关闭系统代理后的 2026-10-19 主机复查：`ProxyEnable=0`、WinHTTP direct，但五个 Clash 相关进程（含 `clash-win64.exe`）仍存在，`[::]:7890` 仍由 Clash 监听，终端的 `HTTPS_PROXY` 与 `ALL_PROXY` 仍指向回环代理，物理以太网 Up。见 [脱敏核查结果](evidence/experiments/20261019-proxy-off-check.json)。这一状态不能认定离线；即使代理彻底退出，物理网络直连通道仍在。本轮未再次启动游戏。

## 社区反馈与迁移门槛

### 首局候选的本机文件证据

使用 [mode_candidates.py](tools/mode_candidates.py) 对哈希已锁定的 1649370 EXE 与完整文件清单生成了 [机器结果](evidence/mode-candidates.json)。EXE 中 `coop_train_mp_firingrange` 出现一次（文件偏移 `0x6C66F4`，RVA `0x9DA6F4`），其绝对地址字节另出现于 `0x50C3F` 与 `0xC8F10`；`CPP_TryLaunchTutorialMap`、`cppOpenTrainEOGMenu`、`scr_gameended`、`botsAddAll` 各出现一次。清单中训练靶场对应六份 IFS 名称（包含版本侧车文件），货船训练对应十一份；EXE 未找到 ASCII `coop_training_mp_cargoship`。指针出现位置只是静态交叉线索，未恢复调用链。据此把训练靶场列为**优先调查候选**，尚未证明入口可达、资源可载、BOT 可用或有自然结算。当前没有完成模式选择的运行证据。

2026-10-19 用户转述：社区尝试将部分 1604220 成果用于 1649370 未成功，可能是偏移变化。此为**社区线索，尚无本轮原始失败记录**。仓库 [跨版本对照](codol-ember/研究报告-research/comparisons/launch319-source-review-20261018.md) 独立确认三个对应字符串坐标在 1649370 相比 1604220 偏 `+0x10`，但明确不能推广成统一地址位移。

迁移每一处定位须记录：源 Build/文件 hash、目标 Build/文件 hash、语义锚点、目标 RVA 与文件偏移、预期原字节、实际字节、调用/数据关系、验证方式与失败结果。任一目标定位缺证或原字节不符时停止该项迁移，不以固定加减常数猜地址。协议字段、加密材料及页面状态也按实际客户端请求和消费者分别核对。

## 第三方参考包审计摘要

`他人文件参考/服务端.zip` 为 Python v0.0.1 本地认证/大厅桩，README 明示无对局层。服务端代码在未知 svc/task 上默认返回成功空结果，入站加密帧部分校验不足；这不能作为 1649370 成功证据。`客户端.zip` 通过配置改写、进程内写入和前台桩展示大厅，版本识别未锁定 EXE/Base 完整 hash，且远程写入有部分失败残留风险。二者只取可核验的结构线索，不直接运行或复制为本项目主干。2697 的 `codol_dedrun.exe` 属旧版独立宿主，不能假设可执行 1649370 内容。

## 2026-10-19 同 Build 静态侦察（接手轮）

[机器摘要](evidence/experiments/20261019-static-recon.json) 由 [static_recon.py](tools/static_recon.py) 只读生成。它把此前“只有字符串位置”的判断推进到**节归属与引用计数**，但仍不包含任何检查语义：

- 游戏 EXE 的导入目录 size 为 0（运行时重建）、TLS 目录在 RVA `0x9E8EB8`、入口在 `.tvm0`；`WIN_NO_TCLS`、`-src=tgp`、`WIN_ERROR`、`+unattended` 都在只读 `.tp3` 数据节，直接绝对引用为 0。启动判定与这些字符串之间没有文件级指针链。
- Base DLL 的 `TCLS_SHAREDMEMEMORY`/`TCLS_TASMEMORY_` 同样没有绝对引用；而 TAS 事件名 `TAS-3AAC03A5-…-` 的 3 个绝对引用全部落在 `.tls` 保护节（15.5 MB 可执行），这支持 TAS/TCLS 逻辑在保护节内、需运行时解密后再定位。
- `TCLS/ClientBase.dll` `.rdata` 的 `0x1D4F00-0x1D5120` 是 TCLS 字符串表（ASCII 与宽字符成对），含 `\Global\TenP_TS_%d`、`%s%d`、`TASData.dat`、`tensafe`、`LdrLoadDll`；表内指针指向 `.text`，字符串本身无直接引用。`\Global\TenP_TS_%d` 是新增的第二类命名共享内存线索，语义未验证。
- `TCLS/Client.exe` 是普通转发器（仅 `CreateProcessW`/`ShellExecuteExW` 等），不含共享映射名；`WeGameLauncher/config/*.json` 加密未逆向。

由此，`WIN_NO_TCLS` 的两条候选判别路径收敛为：(a) 命令行 `-src=tgp` 与 (b) `TCLS_SHAREDMEMEMORY<PID>` 交接。二者都必须在隔离后的运行时实验中对照，静态文件不能替代。`+0x10/+0x14/+0x18` 布局仍只有 1604220 参考来源，不能写成 1649370 已确认格式。

## 本阶段任务顺序

1. 归档完整性和解压目录逐文件摘要对照，保存机器清单及差异。
2. 固定 1649370 启动输入、配置和隔离副本；以只读观察确定当前最早失败边界。
3. 对该边界做同 Build 静态定位或受控实验，再把确认的帧/状态加入版本专用服务。
4. 重复“输入 → 原始帧 → 解析 → 状态 → 应答 → 客户端消费”链，直到原生房间与一局结算可验收。
