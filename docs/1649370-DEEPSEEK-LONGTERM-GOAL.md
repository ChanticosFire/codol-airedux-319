# 给 DeepSeek 的长程目标：完成 Build 1649370 自建服务端可玩对局

更新：2026-10-29，依据当前主分支 `8749424`、`1649370-STATUS.md` §1323、实机日志与截图。项目根目录 `E:\GAME\COD\codol-airedux\319`。开工先读本目录 `AGENTS.md`、`1649370-HANDOFF-CURRENT.md`、`1649370-AUDIT-20261027.md`、`1649370-STATUS.md` 最新章节、`PROJECT_STATUS.md` 顶部、`resources/1649370/README.md` 与 `manifest.json`；旧结论只作历史线索，具体事实核对当前文件和实机。

## 唯一目标与五项验收

让 Build 1649370 客户端通过自建 `server1649370` 真实连接，在 `mp_crash_tropical` 以本地玩家身份自由移动、持枪射击，正常结束并回到功能完整的大厅。五项必须在**同一可复现最终路径**逐项实测，不得把不同时期的局部成功拼成整体成功：

1. 游戏服日志直接记录真实客户端 `getchallenge`、`connect`、`stats` 和后续输入；不是 demo 回放。
2. 客户端完成握手到有效对局 `net_state=10`，服务端连续发送有效 gamestate/snapshot，客户端实际渲染 `mp_crash_tropical`。
3. 对局按正常游戏规则结束并回大厅；角色、仓库、背包、档案仍正常。强杀进程或仅断开 socket 不算正常结束。
4. 在最终路径**直接读取** `ui_state != 5`，且无 100、174、181 等错误弹窗。可见地图与 `net=10` 不能替代这个字面条件。
5. 原生键鼠、服务端输入/状态/事件日志、客户端 playerState 和前后截图共同证明自由移动与射击：可前后左右、转向，第一人称手臂和枪身持续可见，攻击产生实际武器反馈（射速、枪口或弹道、命中或伤害、弹药）。人工步进、只改 HUD 弹夹或客户端内存指针诊断不算完成。

## 当前已证实的最深进度

- 第 1、2 项在当前真实连接路线反复成立。r800/r801/r802 三次独立会话各有 `connect=1`，服务端发送 517/511/514 个快照，完整解码 347/385/324 个输入包、零错误；客户端各阶段 `net_state=10`。不是 `+cl_demo_play`。证据：`evidence/experiments/20261029-r800-r802-armed-input-sequence.json` 和对应原始忽略日志 `runs/r800..r802-gs.jsonl`。
- **背包/仓库 UI 的已验证范围单列**：r527 新实例在大厅打开仓库，Loadout 1 主副武器、储物箱物品网格与 190 道具分类曾恢复显示，原生库存计数 7,208；`evidence/experiments/20261026-r527-warehouse-control.json` 记录其与 r525 入图后仓库空白的对照。这证明档案内有库存且“保存保护必然导致空仓库”不成立，**不证明 r800–r802 对局正常结束后仓库仍可用**。最终第 3 项须同路径重新打开仓库、背包和档案实测。
- 签名武器资源 `ak47_mp.ff` 的**正确临时放置目录**为唯一运行时下的 `client_shipretail/chinese/ak47_mp.ff`；放到运行时根目录会使武器 78 查询字为 0、队列 `(78,0)` 常驻、手臂模型缓存 0。r797–r799 只改目录，三次均变为查询字 1、队列清空、手臂/手部模型缓存 2。此前 r786–r796 无枪回归的主要原因是资源暂存位置错误，不应再重复追这个已解的队列现象。证据：`evidence/experiments/20261029-r796-r799-weapon-fastfile-stage-path-ab.json`。
- r797–r799 在正确资源目录下，用可逆**客户端内存诊断**把 `weaponDef78+0x10` 从 `tag_origin` 指向已加载 `viewmodel_ak47`，三张有效截图都有 AK-47。r800–r802 又在**同一会话**完成鼠标转向、W/S/A/D、左键，原生角度约 −29.8°、逐键 XY 改变、诊断弹夹 30→29，枪身在移动和左键后持续可见。截图 `evidence/experiments/20261029-r800-armed-sequence-after-movement.png`、`20261029-r800-armed-sequence-after-input.png`、`20261029-r801-armed-sequence-after-input.png`、`20261029-r802-armed-sequence-after-input.png`；完整数值在上列 JSON。三次独立复现只支持“可见枪身的诊断输入闭环”。

## 当前未完成的卡点

- `weaponDef78+0x10` 的枪身绑定仍靠临时客户端指针写入；正常注册后为什么保持 `tag_origin`、如何由可持续运行路径建立绑定，尚未解决。签名 fastfile 是必要条件之一，不等于完成自动绑定。旧 r745 的单次 174 不能概括正确目录下的 r797–r802。
- `--input-motion-probe` 仍是按解码包 ±2 的有界人工位移；没有用 usercmd 时长、地形碰撞、角色速度等实现实际游戏物理。真实输入的服务端消费已证实，但不能称自由移动验收完成。
- 左键 attack 位已被解码，服务端人工把快照弹夹 30→29，客户端读回并显示；没有直接证明射速、开火事件、枪口火焰、弹道、命中、伤害或换弹，不能称射击成功。r803 已在主用 `wire164.py` 建立本 Build 的双字事件 `tag 0 + 11-bit payload` 显式编码/诊断解码，r738 原帧逐字节保持；**这是静态协议验证，未发送给客户端**。旧 `ps_codec.py` 的 `-94` 仍为未实现，不能把两套编码器混用。下一步须查事件编号、序列环和客户端消费点，参见 `1649370-STATUS.md` §1325。
- 正常赛后结束、回大厅后仓库/背包/档案，以及字面 `ui_state != 5`，尚未在当前最终路径实测。历史直接读数曾为 `ui_state=5`；不能用不弹错误框代替直接指标。

## 开工顺序与证据要求

1. 固定当前可进图配置：唯一 `r107flow/runtime`、r738 gamestate/snapshot、`--ring-a-length-mode slot --server-command-text off --decode-client-input`，武器 handler/lookup/init/cache 原始索引与 name fallback；签名 FF 只临时放在 `client_shipretail/chinese/`。先核对档案 SHA、EXE SHA、端口 PID 与当前 Git diff；不得重新复制约 15 GiB 运行时。
2. 优先查注册后的枪身模型为何停在 `tag_origin`，对照已加载 `viewmodel_ak47`、武器定义写入点和服务端下发的武器/玩家数据。诊断指针仅作正控；给出不靠事后手改客户端内存的可重复注册路径，并以三次真实截图复验。不要把临时 `probe_weapon_viewmodel_binding_1649370.py --apply` 包装成最终功能。
3. 参照 `他人文件参考/` 的 `codol_player_tail164.c`、`codol_clients164.c`、`codol_entities164.c` 和 `codol-ember` 全库的 Build 1649370 资源、UI、协议资料，先查现有实现与 `--help`，再改事件/物理代码。先做可逆小实验，分别核对服务端发什么、客户端读到什么、画面显示什么；三次独立复现才写稳定。对真实射击必须有武器状态及实际开火/命中反馈的直接证据，不只弹夹数字。
4. 把诊断步进升级为服务端权威的时间、方向、朝向与碰撞运动；逐方向及组合键复测。不得直接改客户端 playerState 冒充服务端反馈。核心桥/编码/启动路径变更保留开关与 A/B 回归。
5. 建立正常结束条件与赛后数据，真实走完结果页/回大厅/仓库/背包/档案；同时直接采样 `ui_state` 和 net_state，并保留时间序列、服务端日志、实机截图。最终用同一路径覆盖全部五项。

## 资源与强制约束

资源总表 `resources/1649370/README.md`、`manifest.json` 列出原路径、用途、私有副本及哈希。签名 FF 私有原件在 `resources/1649370/local/weapon-fastfiles/ak47_mp.ff`（SHA-256 `c4e975fef271f492774cc09701b1a9f7a014300b6ef94bce961def3dc819093f`）；EXE SHA-256 `141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380`。活库 `data/v1649370/local.sqlite3` 基线 SHA-256 `06f7a93bc8f818461fc0267f464bb3fa0e3801ac999462fc54eb8cc512af2f70`，SQLite `integrity_check=ok`；每轮前后完整备份，改写先定性并保留隔离库，不能丢现有 profile baseline 与 quarantine。`local/` 含私钥、账号库与客户端资源，永不提交或公开；公开只放脱敏摘要、代码与截图。

严格执行 `AGENTS.md`：先读状态、证据、社区源码、现有工具；先证明发送端，再归因接收端；单次观测不称稳定；失败实验也记录。`codol-ember/` **整个库**可参考，1604220 的资料只借鉴方法，不把其数据位直接套到 1649370。实现应服务于长期稳定开发与部署；临时客户端内存改指针、人工位移及扣弹只作带边界的诊断正控，不能接成最终玩法。禁止 `run_match.py kill_stale`，只按确切 PID 清理；禁止堆积 `cbuf` 命令导致溢出。回滚前必须检查 `git diff` 语义，未提交改动不等于垃圾。不要让用户手动按键、截图、测试或选方案。每轮更新 `1649370-STATUS.md` 与 `PROJECT_STATUS.md`，必要时同步当前 handoff；提交并推送安全文件。结论必须注明当前 Build、直接证据和限制；目标不因困难、额度或交接自行缩小或标记完成。
