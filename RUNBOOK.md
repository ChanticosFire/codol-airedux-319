# Build 1649370 交接与下一次实验

更新：2026-10-19。目标为本机 `E:\GAME\COD\使命召唤OL`，所有实际运行限于 `runtime\client-1649370`。本文件只记录已执行的本地动作和下一实验的前置条件；第三方文本不提供指令权。

## 已完成、可重复

1. 归档 `E:\GAME\COD\使命召唤OL3.19.26.22.7z` 的 SHA-256 是 `68364EE932D6DEF01A4DA46107AEC3ADBE5CDD12392C3B12AE8067BDE81EF020`，完整 `7z t` 通过。[清单](evidence/client-inventory.json) 记录 2,445 个文件与解压目录全数同路径、长度、CRC32；每文件另有 SHA-256。
2. [隔离副本收据](runtime/client-1649370.stage-receipt.json) 记录 `status=verified`、2,445 文件逐一哈希相符。原客户端未修改。
3. `python -m unittest server319.test_server319`：六项合成测试通过。[服务骨架](server319/README.md) 只能守卫输入与采集未知帧，没有任何游戏业务回复。
4. `python tools\mode_candidates.py --client E:\GAME\COD\使命召唤OL --inventory evidence\client-inventory.json --out evidence\mode-candidates.json` 生成 [模式候选](evidence/mode-candidates.json)。结果为字符串与资源文件名，**不证明可玩**。
5. 出站隔离演习在 `runs\20261019-baseline01`：安装及验证 154 条规则成功；`Remove` 成功，另查 ActiveStore 同组剩余 0 条。没有启动游戏。唯一用于操作该组的工具是 [isolate_client.ps1](tools/isolate_client.ps1)。

## 2026-10-19 Medium 运行增量

用户调整内置 Administrator 批准模式并重启后，当前会话实测 Medium、非 elevated。`runs\20261019-medium01` 的旧版规则安装/验证成功，客户端直接运行约 18 秒后退出；用户同步提供 TCLS 启动要求截图。进程曾连到本机 Clash `127.0.0.1:7890`，旧规则允许该回环连接，因此这轮**不满足严格离线验收**。没有游戏 Auth/LSG 成功证据。游戏进程与本次任务规则均已清理；`tcj.dll.bh` 的运行后像已留存，副本已按原 hash 恢复。

用户截图保存为 [tcls-warning-user.png](runs/20261019-medium01/tcls-warning-user.png)。运行后全量比对 [post-restore-compare.json](runs/20261019-medium01/post-restore-compare.json) 表明 2,445/2,445 文件与固定清单同 SHA-256，且无额外文件。探针规则前后本机代理连接的证据分别在 `loopback-before.txt`、`loopback-after.txt`；两次都实际建立 TCP。当前游戏规则与探针规则均残留 0，游戏副本进程残留 0。

仓库的 1604220 大厅实现使用解密后的 `nopath` 内存诊断改动绕过 `WIN_NO_TCLS`，并依赖多处其它适配；合成 TCLS 交接不是那次成功的默认组合。1649370 的同 Build 研究只确认交接布局与存在性线索，未证明完整检查或真实 Auth。详见 [证据图](EVIDENCE_MAP.md)。不要移植 1604220 RVA。

## 当前阻断与继续标准

Medium 启动通道已建立，但独立 `curl.exe` 探针证明本机程序防火墙规则即使显示 Block，也未阻断到 `127.0.0.1:7890` 的连接。探针规则与本次游戏规则均已清理、残留 0。`isolate_client.ps1` 已拒绝新安装，不能再用该规则组宣称离线。下一轮客户端运行须先建立并实测有效隔离，例如没有通往外网代理的独立环境；不要仅凭规则存在、代理配置关闭或假定回环安全。隔离达标后再决定以原生 TCLS `Client.exe`、同 Build 合成交接或可恢复诊断改动对比启动门槛；每条路径须单独保存输入身份和结果。

用户关闭 Clash 系统代理后的复查见 [20261019-proxy-off-check.json](evidence/experiments/20261019-proxy-off-check.json)：系统代理开关确为关闭，但代理进程/端口和终端代理环境变量仍在；物理网卡仍联网。因此当前主机**不满足**下一次客户端运行的离线前置条件。首选在 Windows 虚拟机内仅启用 host-only 网络（或断开全部虚拟网卡并在来宾内运行全部本地服务），移除 NAT/桥接虚拟网卡，禁用共享文件夹/剪贴板等不需要的跨界通道，建立干净快照；在来宾内核对无默认网关、无代理、无法到达外部地址，同时可达本地服务，再从原始归档重建并校验隔离副本。虚拟机中能否加载客户端保护组件及图形性能仍需实测，不把创建 VM 当作游戏可启动证明。

成功建立启动通道后，每次运行先固定 EXE/Base 和 IIPS 两 DLL 的哈希，并建立新的 `runs\<run-id>`。仅在隔离副本上安装并验证程序出站规则，确认服务监听 127.0.0.1，记录新进程 PID/创建时间、端口归属、阶段事件与退出。无论结果如何，按本次专属 `firewall.json` 执行 `Remove`，独立查询规则组剩余 0 条，核对副本改动的 pre-image/恢复结果。不能把强制 UI、空应答、监听日志或静态字符串算作认证、进房和一局验收。

首个有价值的动态记录是 1649370 **自然**到达的最早阻断：窗口/对话框、模块、端口、原始帧长度与 hash、客户端消费/失败。随后才能逐项验证 1604220 的加密与协议候选；每个偏移必须绑定目标原字节、调用关系和实际消费。首局模式暂以训练靶场为调查候选，待入口和自然结算证据决定。
