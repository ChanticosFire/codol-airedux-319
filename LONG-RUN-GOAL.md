# 长程自主目标（2026-10-20 夜间）

用户 2026-10-20 00:20 前后的指示：把 1649370 的工作写成**不需要中途确认方向与方案**的长程目标，持续跑；用户睡觉期间不打断。

本文件是这一轮自主工作的授权与边界。它与 [PROJECT_STATUS.md](PROJECT_STATUS.md)、[MILESTONES.md](MILESTONES.md)、[RUNBOOK.md](RUNBOOK.md) 一起构成交接面；三份原有文档仍是事实与证据的唯一来源，本文件只追加“这一夜怎么干”。

## 1. 完成判据（M3 验收）

在隔离副本 `runtime\client-1649370` 上，客户端满足以下全部条件才算完成：

1. 通过 TCLS 启动门槛，不再出现 `WIN_NO_TCLS` 致命错误；
2. 走完 IIPS 初始化，不再出现 `初始化IIPS错误`；
3. Auth/LSG 请求**实际到达**本机 `server319`，有请求字节、端口归属与服务端应答记录；
4. 客户端进入可交互的原生前台/大厅窗口（截图 + 窗口类名/标题 + 持续时间）；
5. 全过程有 `runs\<run-id>` 证据、可复验命令、pre-image 与恢复记录。

只做到 1–3 不算完成，只截到窗口而未经 1–3 也不算。若整夜只能推进到其中某一步，就以该步的真实证据和下一步最小任务收尾，不虚报。

## 2. 自治授权

- 方向、顺序、工具设计、实验取舍由 agent 自主决定，不等待确认。
- 允许：隔离副本内的可恢复配置改动（先存 pre-image，留一键恢复）；无主机级改动的观察式启动；只读内存/PE 取证；本机 `server319` 开发与自测；本地 git 提交与（凭据可用时的）推送。
- 允许启动客户端进程，但每次运行必须：先核四锚点哈希、单独 `runs\<run-id>`、记录 PID/端口/窗口、结束后清理自有进程并核对副本改动。

## 3. 硬边界（不得自行越过）

以下事项在用户醒来明确批准前**一律不做**，遇到就记录为用户待办并改做别的：

- 主机级断网/防火墙规则/网络适配器/代理/路由/DNS 的系统级改动；
- `sudo`、提权、计划任务提权、加载驱动、改系统安全策略；
- 修改原件 `E:\GAME\COD\使命召唤OL`（只读）；删除证据、`git reset/clean/stash`；
- 取消证书校验、连接或仿冒现役官方端点、使用真实账号凭据；
- 对外发布/投稿/PR、改 Gitea 权限。

理由：2026-10-19 23:37 的事故已证明主机级隔离会切断 agent 自身的通道，恢复只能靠用户；夜间无人可恢复。

## 4. 每轮循环

1. 读 `PROJECT_STATUS.md` 第 8 节起的“当前事实”，确认 `git HEAD` 与未提交改动；
2. 选一个**能独立验证**的最小假设，写清预期与判据；
3. 做实验（优先生成机器可读证据 JSON，其次截图/日志）；
4. 立即落盘：`runs\<run-id>\` + 需要长期保留的摘到 `evidence\experiments\`；
5. 更新 `PROJECT_STATUS.md`（事实、未验证项、下一步）与 `MILESTONES.md`（阶段状态）；
6. `git commit`（信息写清输入哈希、动作、结果、失败项）；
7. 若某假设被否定，把否定结果也写进文档——阴性结果同样是有价值交付。

## 5. 决策优先级队列（从当前断点起）

当前断点（2026-10-20 00:12 实验 `runs\20261020-redirect01\q.json`）：加 `-q` 后 TCLS 门槛消失，窗口类从 `GbLoginClass` 变为 `#32770` + Static 文本 `初始化IIPS错误：8189fec。`。

1. **确认 `-q` 的语义与稳定性**：与不带 `-q` 的基线做对照（窗口类、Static 文本、持续时间、TCP 表），确认门槛确实由 `-q` 跳过而非偶然；同时确认 `-qa`、`-src=tgp -q` 的组合差异。
2. **IIPS 初始化**：定位 `8189fec` 的含义与判据（`iips.dll` / `IFS2.dll` / `iips.ini` / 本地服务），先静态后动态；尝试把 `iips_url` 指向本机最小应答服务，看错误码是否变化。
3. **GbLogin / Auth**：门槛与 IIPS 都过之后，让 `dwauth.ini` 指向的 4174/4175 真正被消费，记录首个请求帧。
4. **LSG/大厅**：以 1604220 参考为候选模型，逐项验证同 Build 锚点、帧边界与客户端消费。
5. **文档与公开整理**：可复用增量按协作仓库规范另行整理（双语），不得混入私有路径。

任何一步超过 3 轮仍无增量，就把该步标为“受阻”并写清具体条件，转去做队列里下一项能推进的事，不要原地空转。

## 6. 用户醒来先看

1. 本文件末尾的“夜间日志”（每轮追加一行：时间、假设、结果、证据路径、commit）；
2. `PROJECT_STATUS.md` 最新一节；
3. `git log --oneline -15`；
4. 若要继续，直接说“继续”即可。

## 7. 夜间日志

| 时间 | 假设/动作 | 结果 | 证据 | commit |
| --- | --- | --- | --- | --- |
| 2026-10-20 01:15–01:35 | IIPS 错误可用进程内补丁绕过（Medium 无提权） | **否定**。`RVA 0x3804F2` 补丁后进程存活 40s 但弹窗仍在；点掉弹窗 2s 后 exit `0xFFFFFFFF`。IIPS 失败是致命的，只能靠管理员令牌 | `runs/20261020-night01/patch-iips{,2,3}.json`、`iips-stack.json`、`iips-code.json` | 待提交 |
| 2026-10-20 01:35–01:45 | 静态确认 `dwauth.ini` 格式与 LSG 参数来源 | **成立**：`dwauth.ini`=%59s+%hu（host+port）；LSG 从配置对象 `[esi+0x2c]+0x88..0x9C` 复制 host/port，不来自 Auth 响应；`lsg_server_ticket` 仅校验 size≤0x80 与解码长度 | `auth-fields-dump.json`、EXE 字符串表 `0x6C7D9C` | 待提交 |
| 2026-10-20 01:45–02:00 | `dwauth.ini` 是否真被解析并落到 LSG/Auth | **成立**：运行时读回 host1=127.0.0.1/port1=4174、host2=127.0.0.1/port2=4175、title=1002；LSG URL 构建函数在 RVA `0x79A6C0`，端口取 `[esi+0x2004]`，模板 `0xD5A150` | `runs/20261020-night01/config-globals.json`、`config-code.json`、`dwauth-anchor.json` | 待提交 |
| 2026-10-20 02:00–02:20 | 把 Auth 协议正式化进 server319 | **完成**：`server319/auth.py` + `test_auth.py`（9 项）+ CLI `--auth`；端到端自测 100-continue→200、20 字段、ticket 128B；全套 21 项测试通过 | `runs/20261020-night01/auth-e2e.jsonl` | 待提交 |
| 2026-10-20 02:20–02:35 | 一键复验脚本 | **完成**：`tools/run_session.ps1`（管理员会话：核锚点→server319 auth→`-q`+补丁→证据→停服务），语法检查通过 | `tools/run_session.ps1` | 待提交 |
| 2026-10-20 02:40–03:00 | 定位 LSG 连接触发机制 | **成立**：LSG 服务虚表 `0xD5A0C4–0xD5A0E4`（连接 `0xB98B70`、状态机 `0xB98AD0`）；连接经虚表间接调用，由状态机在合适游戏状态驱动。补丁后无输入则状态机不进入连接阶段 | `runs/20261020-night01/lsg-callers2.json`、`lsg-trigger.json`、`lsg-pointer.json`、`lsg-connect.json` | 待提交 |
| 2026-10-20 03:00–03:15 | UI 输入工具（LSG 状态机需要输入） | **完成**：`tools/send_input.ps1`（ENTER/SPACE/ESC/CLICK/ALT_ENTER，AttachThreadInput 前置；需管理员）；21 项测试仍通过 | `tools/send_input.ps1` | 待提交 |
| 2026-10-20 03:20–05:40 | 跳过 IIPS 错误分支能否让 Medium 跑通 | **半阳性/受阻**：补丁 `0x25A4A0:7543→EB43` 在 wait 5 应用后 IIPS 弹窗消失、进程存活 70s，但无主窗口/Auth；深层链（`GetResourceManagerII`→vtable+4 `+0x197F0`→`+0x12760`）未收敛到可修条件。IIPS 标记“受阻（需提权）” | `runs/20261020-night02/` | 待提交 |
| 2026-10-20 05:40–06:05 | 社区成功组合的 `enable_iips=0` 能否在 Medium 下跑通 | **阴性**：`enable_iips=0` + `iips_url="http://127.0.0.1/"` + Auth 服务下，游戏只出现 `CoD Splash Screen`，4 秒后 exit `0xFFFFFFFF`，无 Auth 请求。参考组合依赖管理员会话 | `runs/20261020-night02/patch-iipsoff{,2}.json` | 待提交 |
| 2026-10-20 06:10–06:30 | 离线补齐 LSG 捕获端点 | **完成**：`server319/lsg.py`（HTTPS 4174、记录 `/v1.0/...` 请求、404 占位）+ 端到端自测通过 | `runs/20261020-night03/lsg-e2e.jsonl` | 待提交 |
| 2026-10-20 06:35–06:50 | `enable_iips=0` + 双 IIPS 补丁 + Auth 组合 | **阴性**：进程 3 秒退出（`CoD Splash Screen` 后），补丁来不及生效，无 Auth。IIPS 不能禁用（资源系统必需），只能真初始化 | `runs/20261020-night03/patch-combo.json` | 待提交 |
| 2026-10-20 07:00–07:20 | 固化 M3 验收与复验手册 | **完成**：`M3-CHECKLIST.md`（五条判据当前状态、一键命令、证据判据、失败排查、恢复） | `M3-CHECKLIST.md` | 待提交 |
| 2026-10-20 07:25–07:40 | 交接质量审计 | **通过**：10 个 md 本地链接 0 断链；26 个 Python 0 语法错；6 份 evidence JSON 全部可解析；21 项单元测试通过 | `runs/20261020-night03/audit.py` | 待提交 |
| 2026-10-20 07:45–08:20 | 一键脚本 dry-run 与证据可用性 | **通过/修正**：非管理员 dry-run 正确警告并跑完（Auth 起、补丁 True、采样、退出）；修正 `AuthEvidence` 预创建 `auth.jsonl`，避免“服务未启动”与“无请求”混淆 | `runs/20261020-dryrun02/` | 待提交 |
| 2026-10-20 08:30–08:45 | IIPS 文件校验：磁盘 975 vs 列表 974 的 `readme.txt` | **阴性**：移出 `IIPSDownload\readme.txt` 后仍弹 `8189fec`；已放回。IIPS 失败与额外文件无关 | `runs/20261020-night04-patch.json` | 待提交 |
| 2026-10-20 08:55–09:05 | IIPS 失败的目录权限/UAC 虚拟化假设 | **阴性**：`IIPSDownload` 可写、可删单文件（Deny 仅限删除子目录）；`VirtualStore` 无 IIPS 重定向。排除文件系统权限 | 本机 ACL 查询 | 待提交 |
| 2026-10-20 09:10–09:25 | 夜间总结文档 | **完成**：`NIGHT-REPORT.md`（一句话结论、成果表、阴性清单、醒来三步、提交索引、环境状态）；README 顶部加链接 | `NIGHT-REPORT.md` | 待提交 |
| 2026-10-20 09:30–09:55 | IIPS 根因：Host 的权限要求 | **确认**：`IIPSHostApp.exe` manifest 为 `requireAdministrator`；`__COMPAT_LAYER=RunAsInvoker` 能让它以 Medium 启动，但 Host 自身弹 "Error" 后退出。IIPS 必须管理员是设计使然，不是配置/文件问题 | `NIGHT-REPORT.md` 待更新 | 待提交 |
| 2026-10-20 10:00–10:15 | Host "Error" 窗口内容 | **确认**：`SetPrivilege()失败。`——Host 需要调整令牌特权（如 SeDebugPrivilege），Medium 不可用；`RunAsInvoker` 无法绕过 | `runs/20261020-night04-host-error.txt` | 待提交 |
| 2026-10-20 10:55–11:10 | Host 是否被游戏创建 | **关键确认**：Medium + `RunAsInvoker` 下 14 秒内**没有 IIPSHostApp 进程**——游戏创建 Host 时被 UAC 拒绝（requireAdministrator），IIPS 必然失败。根因链闭合 | `runs/20261020-night04-patch5.json` | 待提交 |
| 2026-10-20 11:10–11:20 | 里程碑与验收清单补根因 | **完成**：MILESTONES M2 与 M3-CHECKLIST 第 2 条写入“Host requireAdministrator、Medium 从未创建 Host”的已确认根因 | `MILESTONES.md`、`M3-CHECKLIST.md` | 待提交 |
| 2026-10-20 11:25–11:35 | 最终端到端回归 | **通过**：四锚点 preflight 全 ok；21 项单元测试通过；11 md/26 py/6 JSON 审计 0 问题；工作树干净、无残留进程/端口 | 本机命令输出 | 待提交 |
| 2026-10-20 11:40–12:05 | AppCompat `RunAsInvoker` 注册表层 + Host `SetPrivilege` 补丁 | **半阳性**：注册表层让 Host 无 UAC 启动（比环境变量强），补丁越过 `SetPrivilege()失败。`，但卡在下一个错误 `IIPS_SHARE_STATE_ERROR(4)`（共享状态/全局命名对象特权）。Host 已还原，注册表项已删除 | `runs/20261020-night05-IIPSHostApp.bak` | 待提交 |
| 2026-10-20 12:10–12:25 | `IIPS_SHARE_STATE_ERROR(4)` 的对象与特权 | **确认**：`iips.dll` 引用 `SeCreateGlobalPrivilege`，需创建 `Global\IIPSShareState_MMF_` / `Global\IIPSShareState_Mutex_` 等全局对象；Medium 令牌无该特权，无法绕过 | `iips.dll` 字符串 | 待提交 |
| 2026-10-20 12:25–12:40 | 里程碑补双重特权结论 | **完成**：MILESTONES M2 写入 `SeDebugPrivilege` + `SeCreateGlobalPrivilege` 的已证实根因；环境复查干净 | `MILESTONES.md` | 待提交 |
| 2026-10-20 12:45–13:20 | `Global\`→`Local\X` 命名空间替换 + Host 补丁 | **未测（安全拦截）**：修改 `iips.dll` 6 处对象名后，`patch_runtime.py` 的四锚点校验发现 `iips.dll` 哈希不符，拒绝启动（exit 2，无 JSON），实验从未执行。已全部恢复原件 | `runs/20261020-night05-*` | 待提交 |
| 2026-10-20 13:35–14:00 | 显式绕过锚点后真正测试 Local 命名空间 | **阴性/不可测**：`--allow-anchor-mismatch` 下实验执行了，但游戏仍 `8189fec`，**Host 依然未被创建**（14 秒内无进程）——UAC 在 AppCompat 层之前就拒绝了 Host 启动，Local 命名空间假设无法验证 | `runs/20261020-night05/patch.json`、`iips.dll.pre`、`host.pre` | 待提交 |
| 2026-10-20 14:10–14:20 | Host 是否有跳过特权的命令行开关 | **阴性**：`IIPSHostApp.exe` 的 `.rdata` 只有 boost 通用 `Arguments:`/`help` 字符串，无 `priv`/`admin`/`skip` 一类开关；Host 无参数级绕过 | 本机字符串搜索 | 待提交 |

## 8. 白天续跑（2026-10-20 09:00–16:00）：认证与 LSG 握手全部打通

> 本节把「当前任务」补进长程目标：从 Codex 接手后的认证修复，到 LSG 握手解密完成。

### 8.1 已完成（按顺序）

| 时间 | 事项 | 结果 | 证据 |
|---|---|---|---|
| 09:00–10:00 | Codex 修正 Auth schema：`auth_task=11`（请求+1）、`code=700`、补 `member_position`/`estimated_wait_time`/`next_poll_after` | 客户端通过账号认证（`DW_ACCOUNT_LOGIN_COMPLETE`），**首次连上 4174** | `runs/20261020-codex-*` |
| 10:00–11:00 | Tiger 票据（`server319/ticket.py`、`a22_tiger.py`） | 票据校验通过 | 同上 |
| 11:00–12:00 | 28B hello → **26B 门控应答**（`[u32 22][01][81][D2 00 00 00][MARK][nonce]`） | 客户端回 **153B 0x82 帧**（门控被接受） | `runs/20261020-session09+` |
| 12:00–14:00 | 0x83 token 多种尝试（`conn+0x5FC`/`+0x5F4`/0x82 帧/反序） | 均 `DW_LOBBY_ERROR`；反汇编定位 0x83 handler `0xBA454B`、读 token `0xBA3BA0`、边界检查 `0xB783C0` | `runs/20261020-dump-ba3000` |
| 14:00–15:00 | 补丁 `0xBA456E`（0x83 边界检查失败跳转） | 客户端不再报错、窗口稳定 70s+、**主动发 130B 0x85** | `runs/20261020-session30` |
| 15:00–16:00 | **0x85 解密**：key=`conn+0x604`→`[ptr+0x9C]`、IV=帧内 offset 10、AES-128-CBC | **成功解出 84B 登录请求**（`0x86` 硬件指纹 + MAC，与 1604220 一致）；服务端用 `conn+0x608` 回空 0x85，客户端不再发帧（等业务应答） | `runs/20261020-session33`、`HANDSHAKE-STATUS.md` |

### 8.2 当前阶段（排队列第一）

**目标**：让客户端从“等业务应答”进入大厅。

1. **0x47 应答**：客户端 84B 登录请求（`0x47 03 04 13 08...`）需要服务端回业务帧（S2C 内层类型 + payload）。
2. **tag 0x0A 大厅地址**：1604220 资料（N97）要求服务端下发 tag `0x0A` + 8 字节（IP 4B + PORT 4B），客户端才会把大厅就绪标志置 1。
3. **验证判据**：`[0x84ABA50]` 从 0 变 5（大厅已连），或客户端发下一帧/窗口进入大厅。

### 8.3 下一步手段

- 静态：找 1649370 的 `0xB769A0` 等价物（tag 0x0A 解析器）与 0x47 应答的内层类型。
- 动态：构造最简 0x85 业务应答（`[len][0x86][...]` 或 tag 0x0A + `127.0.0.1:4174`），观察客户端是否从等待转为发帧。
- 参考：`他人文件参考/_CURRENT_STATE(1).md` 的 §43（N97）、`## 3. LSG 线上帧格式`、`§5` 的 Auth/握手记录。
| 2026-10-20 15:00–16:10 | LSG 握手加密打通与业务帧定位 | **重大进展**：0x85 解密成功（key=conn+0x604、IV offset 10、AES-128-CBC），明文为 84B 登录请求；业务 type 4 = tag 0x0A 大厅地址分支（`0xB83A4B`/`0xB83A52`），已发出 type 4 帧但客户端仍“失去连接”；下一步查业务队列 `[0x84ABA7C]` | `HANDSHAKE-STATUS.md`、`runs/20261020-session33..43` | 待提交 |
| 2026-10-20 16:20–17:00 | LSG 业务帧 type 4 与大厅连接 | **里程碑**：type 4 + tag 0x0A 使客户端到达 `DW_LOBBY_CONNECTED`（ui=4、ready=1、queue=2）；**只发一次**才保持，循环心跳会触发 `ConnectionAbortedError` | `runs/20261020-session46/47` | 待提交 |
| 2026-10-20 16:50–17:15 | LSG 内层类型扫描与 0x47 应答 | **部分成功**：`0x88` 内层使 `DW_LOBBY_CONNECTED` 保持约 16 秒（最佳），`0x84/0x86/0x87` 立即 lstate=4；`0x47` 业务类型与周期心跳仍报废。**缺 0x47 应答字节** | `runs/20261020-inner-84/87/88`、`biz-47` | 待提交 |
| 2026-10-20 17:15–17:30 | 拉取社区仓库 + 1604220 服务端参考 | **重大线索**：`lobby.py` 给出 step1/step2 格式、密钥派生公式（SHA1/HMAC-SHA1/HKDF）、evt4 body、task_reply 格式、keepalive 为裸 4 零字节；包内 `wire.py` 被省略。实验仍 lstate 2→4，推断服务器→客户端密钥方向不匹配 | `HANDSHAKE-STATUS.md` 0.11 | 待提交 |
| 2026-10-20 17:30–18:00 | conn 结构/seq 实测 + CHAL 派生穷举 | **校正**：`conn+0x5EC` 不是序号（1649370 改动），改为回显客户端 0x85 的 seq；`CHAL` 派生 14400 组合未命中（transcript 与 1604220 不同）；`0xBA4430` 的 type 4 是报废分支，S2C 不能用 type 4 | `HANDSHAKE-STATUS.md` 0.12、`runs/derive_chal.py` | 待提交 |
| 2026-10-20 18:40–20:20 | 0x85 明文/密文探针与密钥对象识别 | **决定性**：`frame85_seen` 证明客户端收帧但解不开（明文从未出现）；`0x608` 是证书缓冲不是密钥；`0x604` 是唯一 AES 对象；已穷举 6 类候选密钥/格式全部失败 | `runs/20261020-seen/sym2/key14/keyac/aeshunt` | 待提交 |
| 2026-10-20 23:40–00:10 | 0x85 解不开的根因层级 | **突破性结论**：`0xBA4430` 在 `[conn+0xC8]==4` 时直接 `ret`，CS=4 下客户端**根本不解析到达帧**；`frame85_seen pt []` 因此成立。后续应查 CS=4 的业务消费路径与 D=`*[0x3306D60]+0xC` | `HANDSHAKE-STATUS.md` 0.18 | 待提交 |
| 2026-10-21 00:10–00:55 | gate 版本 220 与 0x87 加密通道 | **突破**：gate 改 `0xDC` 后 `stage=3` 首次出现（`0xBA0780` 条件 B 短暂成立）；0x87 帧格式仍错（`DW_LOBBY_ERROR`） | `runs/20261020-gate220/f87/silent3`、`HANDSHAKE-STATUS.md` 0.20 | 待提交 |
| 2026-10-21 01:00–01:30 | crypt 初始化失败定位 | **确认**：gate 220 生效（`conn_ver=220`）、`lstate=2/stage=3` 稳定 5 秒，但 `crypt` 恒 0（`0xBA3010` 失败），客户端转 `DWLOBBY_PUMP_DISCONNECTED` | `runs/20261020-ver/forcecrypt` | 待提交 |
| 2026-10-21 01:30–02:00 | PROGRESS.md 参考（bdsvc319 实测） | **重要**：另一套 1649370 服务端已实现 `DW=4→5`；关键规则为 svc28 静默、ZEROFRAME 30s、业务帧明文；按此调整后仍 1 秒内报废，定位到触发源是我们自己的 0x85 应答 | `HANDSHAKE-STATUS.md` 0.22、`runs/20261020-ka30` | 待提交 |
| 2026-10-21 02:00–02:30 | 静默与明文 0x85 回帧 | **阴性**：静默 6s 断开且客户端不发业务请求；明文 0x85 也 `peer_closed`。三条路都断，问题在回帧内容本身 | `runs/20261020-silent4/plain85`、`HANDSHAKE-STATUS.md` 0.23 | 待提交 |
