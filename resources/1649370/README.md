# Build 1649370 资源索引与本机备份

更新：2026-10-26。项目根目录：`E:\GAME\COD\codol-airedux\319`。

本页是接手入口：[已验证启动流程](../../docs/1649370-KNOWN-GOOD-STARTUP.md) → 本页 → [逐文件清单及 SHA-256](manifest.json)。`local/` 是资源备份目录，已被 `.gitignore` 整体排除；其中有**私钥、账号数据库及客户端二进制**，不要加入 Git 或公开分发。代码和表格可提交，秘密字节不能提交。

## 当前使用的路线

已验证启动：`r107flow/runtime/codol1649370-offline.exe` + 本地服务 + UDP 桥。用户确认进入大厅和 `mp_crash_tropical` 对局画面，未拉起 TP、未出现 100 大厅错误；**尚无玩家**。不能把零售客户端 `codoMP_client_shipRetail.exe` 的 TP/TCLS 故障套在这条路线上。零售版参考资料与候选证书另列为“参考/待验证”。

## 大型资源：同卷硬链接镜像，不再复制大型运行时

| 资源 | 原目录 | 资源目录副本 | 作用 | 文件数 / 逻辑大小 | 方式 |
|---|---|---|---|---|---|
| 当前隔离运行时 | `E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime` | `local/mirrors/runtime-r107flow` | 真实启动的 EXE、`mp_crash_tropical` fastfile、图像声音和已铺设的配置 | 88,586 / 14.95 GiB | 88,569 个静态文件硬链接；17 个可变文件独立复制 |
| 社区 1649370 素材库 | `E:\GAME\COD\1649370\resources\v1649370` | `local/mirrors/community-resources-v1649370` | `offline-menu-patches.json`、overlay、image/loose library；重建时使用 | 41,739 / 7.48 GiB | 41,731 个硬链接；8 个可变文件独立复制 |
| 原始客户端 | `E:\GAME\COD\Original Client` | `local/mirrors/original-client` | 社区启动器的原始素材来源；仅作源文件，不作为本流程启动目标 | 2,446 / 24.96 GiB | 2,351 个硬链接；95 个可变文件独立复制 |

这些镜像合计 132,771 个目录项，**新增普通文件内容仅 14,398,078 字节**；硬链接不再占用几十 GiB 的第二份数据。删除原路径后，硬链接目录项仍可找回文件；但两条路径共享文件内容和同一块磁盘，原文件被改写或磁盘损坏时，硬链接也会受到影响。可变配置、密钥、数据库和关键测试输入均另有独立字节副本。**运行时仍只从原来的 `r107flow/runtime` 启动，资源镜像只用于恢复。**

## 当前流程的独立副本

以下均在 `local/` 下，逐文件大小与 SHA-256 见 `manifest.json`。原件若丢失，先按哈希核对副本，再复制回原位置。

| 资源目录副本 | 原路径（相对 `319/`，另有说明除外） | 作用 / 状态 |
|---|---|---|
| `tls-active/auth.crt`、`tls-active/auth.key` | `runs/20261020-live-derived01/tls/` | r523 启动 LSG 使用的服务端证书与私钥；**当前流程** |
| `tls-active/system-trust-cert.pem` | `C:\Program Files (x86)\Common Files\SSL\cert.pem` | 本机 OpenSSL 默认信任锚的原样副本；零售 TLS 排查参考，**不是** r523 已验证认证成功的证据 |
| `profile/local.sqlite3`、`profile/game-settings.sqlite3` | `data/v1649370/` | `--local-profile` 的本地账户、角色与游戏设置；勿把账号库当公共测试数据 |
| `fixtures/gamestate-client0.bin` | `runs/gamestate-client0.bin` | r523 游戏服实际发送的 6,411 B gamestate，`client_number=0` |
| `fixtures/r522-clean-compact.bin` | `runs/r522-clean-compact.bin` | r523 实际发送的 182 B 快照文件；服务端日志的 wire payload 长 186 B |
| `fixtures/gamestate-network-ffb56d7e-6411.bin` | `runs/demo-outer-exact/` 同名文件 | §523.2 历史可复现配方的 gamestate |
| `fixtures/baseline-outer17-245.bin` | `runs/demo-outer-exact/` 同名文件 | 原始 demo 提取的 245 B 快照基线 |
| `fixtures/snap-nospec-1.bin` | `runs/snap-nospec-1.bin` | 历史上能渲染地图的最小 `pm_type` 修改样本；仍无可控玩家 |
| `helpers/_patch_r336.py`、`helpers/_sample_state.py` | `runs/` 同名文件 | r523 的运行时补丁与只读状态采样；原目录被 Git 忽略，故单独保留 |
| `helpers/client_loopback_tcp_guard-fixed.exe` | `runs/guard-build/` 同名文件 | `--loopback-tcp-guard` 需要的本地 TCP 辅助程序 |
| `community-code/` | `E:\GAME\COD\1649370\` 中的 `src/`、`tools/`、`manifests/`、`bin/`、`data/`、`native/` 及入口文件 | 社区 Python 包和离线基础 EXE 的**独立**副本，157 文件 / 37,322,019 B；不含 15 GB 运行时 |

## 证书与私钥：不能混用

下表是证书本体 DER 的 SHA-256 指纹，不是 PEM 文件哈希。完整文件哈希见 `manifest.json`。候选证书与私钥均已独立复制到 `local/alternate-tls/`；**只有 `319` 的 `auth.crt/key` 用于上面的 r523 命令**。

| 证书原路径 | 指纹 SHA-256 | 资源副本 | 解释 |
|---|---|---|---|
| `C:\Program Files (x86)\Common Files\SSL\cert.pem` | `089F0E09D7150B833D962FE88C9BF3A59C49B5A478243CF6F8A8610046AE1D09` | `local/tls-active/system-trust-cert.pem` | 现有系统信任锚；目前未找到对应 CA 私钥 |
| `319/runs/20261020-live-derived01/tls/auth.crt` | `BD56E356E3D0861F6E4F0C16C46BC5589490243116668ADF01F73ADD45525FDB` | `local/tls-active/auth.crt` | 当前 r523 LSG 进程使用 |
| `1604220/runs/stage1/tls/ca.crt` | `FF4A2844D51421538287F4D9B87B54842FB35DB3D435284FF26162972EC28419` | `local/alternate-tls/stage1/ca.crt` | 另一个 CA，不等于当前系统信任锚 |
| `1604220/runs/stage1/tls/auth.crt` | `C0EA262B76B30C98ACFA1B30CD1E8106A7F03DF2893A4C023445C1134DD071E4` | `local/alternate-tls/stage1/auth.crt` | 另一个服务端证书，未用于 r523 |
| `1604220/runs/live-stage/tls/auth.crt` | `DBBE34909825241F942E65BC61C4D5BE82EE0DB4A50869826DAF01ABB3A64911` | `local/alternate-tls/live-stage/auth.crt` | 零售路线实验材料，未用于 r523 |

`local/alternate-tls/stage1/` 与 `live-stage/` 还保留各自的 `ca.key`、`auth.key`、CSR、序列号和 SAN 配置。`1604220/runs/stage1/pre-image/`、`live-stage/pre-image/` 原始配置也分别保存在 `local/pre-image/`。它们用于回溯零售 staging，**不应替换当前离线运行时的证书或配置**。原先交接里提到的 `data/tls/auth.key` 在所查目录不存在。

## 上游参考实现与其他资料

| 原路径（相对 `E:\GAME\COD\codol-airedux/`） | 资源副本 | 作用 / 证据状态 |
|---|---|---|
| `_upstream/codol_launcher/tools/native-client/reference/launcher/core/prep.py` | `local/reference/upstream/prep.py` | 零售客户端完整 stage：`apply()` 的 7 个文件、hosts、`# CODOL-LOCAL-CA` 标记；`restore()` 使用备份原件。**参考实现，非 r523 命令** |
| `_upstream/codol_server/apps/codol-platform/src/native_config.rs` | `local/reference/upstream/native_config.rs` | `tls10_loopback_explicit_certificate` 约束：RSA ≥2048、TLS 1.0、AES128/256-SHA、security level 0 |
| `_upstream/codol_server/crates/protocol-codol/src/dir.rs` | `local/reference/upstream/dir.rs` | `dirserver.xml` 结构参考 |
| `_upstream/codol_launcher/docs/CLIENT_PREPARATION.md` | `local/reference/upstream/CLIENT_PREPARATION.md` | 零售客户端准备说明 |
| `_upstream/codol_server/tools/smoke_native_launch.py`、`smoke_original1604220.py` | `local/reference/upstream/` 同名文件 | 上游启动检查例程 |
| `_upstream/codol_launcher/tools/verify_original_client.py`、`verify_native_service.py` | `local/reference/upstream/` 同名文件 | 上游文件/服务核对例程 |
| `CODOL-2.6.9.7-Launcher/data/` | `local/reference/launcher-data/` | 参考启动器数据，40 文件；**不是**已验证运行依赖 |
| `319/他人文件参考/codol-server-launcher-members-20261023/launcher/tls/` | `local/reference/qt-tls/` | `qcertonlybackend.dll`、`qschannelbackend.dll`，供研究 Qt TLS 后端使用 |
| `319/tools/run_match.py` | `local/reference/run_match.py` | 历史编排脚本；本次 r523 用的是上面逐步命令 |
| `319/runs/_find_bisect_points.py` | `local/reference/_find_bisect_points.py` | 扫描辅助脚本当前字节副本；其 `LO/HI` 范围曾被误回滚，**语义需另核对** |

零售 `codoMP_client_shipRetailBase.dll` 的 OpenSSL 路径、`cacert.pem` 是否被读取、TP/TCLS 门控等判断来自救援交接与上游代码，属于**零售路径分析**。不要把该分析当成本次离线客户端的运行条件。零售问题若重新开展，应先阅读上述 `prep.py` 和本目录保留的原始配置，不要重复手工猜七个配置项。

## 待验证资产（保留，不用于已验证命令）

| 原路径（相对 `319/`） | 资源副本 | 状态 |
|---|---|---|
| `runs/snapshot-ps58.bin`、`snapshot-ps57.bin`、`snapshot-both.bin` | `local/unverified/` | 16 / 16 / 17 B；尚未送给客户端 |
| `server1649370/ps_codec.py` | `local/unverified/ps_codec.py` | 新增 playerState codec，仅自洽验证 |
| `tools/build_1649370_snapshot_entity.py` | `local/unverified/build_1649370_snapshot_entity.py` | `ps_fields` / `FIELD_CODECS` / `_write_ps_deltas`，未用于 r523 |
| `runs/start_lobby_services.py`、`client_live_services.py` | `local/unverified/` | 手写启动脚本，未作为 r523 可靠配方 |

## 接手与防误操作

1. 要复现大厅/对局画面，先读[启动流程](../../docs/1649370-KNOWN-GOOD-STARTUP.md)，**复用** `r107flow`，不要新建大运行时，也不要使用 `+cl_demo_play`。
2. 某个原件丢失时，先查看 `manifest.json` 的 `source`、`backup`、`sha256`，用 `Get-FileHash -Algorithm SHA256` 对照后再复制。镜像目录仅作恢复源，不当作第二个活运行时。
3. 清理未提交文件前先看 `git diff` 的语义。曾把移除 `+cl_demo_play` 的修复误认为实验残留并 `git checkout --` 回滚，导致后续启动走 demo；`runs/_find_bisect_points.py` 的扫描范围也曾同样被误回滚。
4. 此资源目录和原目录都在本机磁盘，能防误删路径，不能防整个磁盘损坏。私钥如需异机备份，应使用受控的加密存储，保持其不进入 Git。
