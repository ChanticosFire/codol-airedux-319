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
