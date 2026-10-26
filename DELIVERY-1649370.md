# CODOL Build 1649370 — 当前状态与卡点

> 2026-10-27 更新：r643/r644 已恢复**离线客户端**的真实 TLS 认证。实际启动的 `r107flow/runtime/cacert.pem` 原有 175 张证书，不含当前 LSG 自签证书；追加匹配证书后，两个新实例均出现 `POST /auth/`、`auth_response 200`，并继续 LSG task。`tools/launch_1649370.py` 的复用分支现会幂等补齐该证书，原件在 `resources/1649370/local/tls-active/`。下文旧 §2.3、§2.4、§5、§6 对 TLS 的“未建立/不读 cacert.pem/必须先做零售 stage”判断**不适用于已验证的离线路线**。新认证仍未证明档案快照、第一人称武器或射击可用；r644 对局截图仍无武器。详见状态 §1260。

> r647 进一步实证：对局武器表 11 条、`ps.weapon=0`；增加 `(5960,"ak47_mp")` 或把 gametype 改为 `mp` 均不增加武器表。退出时 public 档案被自动改写 240 字节，已隔离试验后整库并恢复 revision1241 的完整用户基线。当前重点是对局 fastfile 注册与服务端玩家装备下发。

> 本文档替代此前所有"交付说明"性质的内容。只写**可验证的当前状态**、**确切卡点**、**已修复的自身错误**。
> 历史流水见 `1649370-STATUS.md`；逐轮摘要见 `PROJECT_STATUS.md`；codex 的完整交接见 `1649370-RESCUE-HANDOFF.md`。

---

## 一、已达成（有截图/日志/内存读数支撑）

| # | 项 | 证据 |
|---|---|---|
| 1 | 协议层全通：`getchallenge` → `connect` → `stats` → `gamestate` → `snapshot` | `runs/r558-gs.jsonl`（connect=2, stats=2）、`runs/r576-gs.jsonl` |
| 2 | 客户端进入 `net_state = 10`（`CA_ACTIVE`） | 多轮 `_sample_state.py` 实测，稳定保持 |
| 3 | **3D 场景可见** | `runs/r581-moved.png`、`runs/r601-t2.png`：完整街景、建筑、柱子、阴影、电线、远景山 |
| 4 | 按键经外部 `RebuildFollower` 驱动服务端位置变化；**原生 usercmd 自主移动未验收** | `runs/r601` 四采样点：`origin.x` `111.5 → -116.5 → -477.5 → -819.5`；服务端组件直接读取客户端 `keys[]` 并重建快照 |
| 5 | HUD 完整 | 雷达（箭头随移动变化）、计分板、生命值条、"战术团队竞技模式" |
| 6 | `ui_state = 0`（非 5） | 多轮实测 |
| 7 | 干净回大厅 | `cbuf "disconnect"` → `net=0`、`table=1353`、`runs/r615b-cbuf-disconnect.png`（mean≈92，无弹窗） |
| 8 | 大厅角色模型可见 | `runs/restored-session2.png`（存档恢复后，角色完整渲染） |

第 3 项比旧 `RELEASE.md` 的黑屏结论有进展；第 4 项仅证明外部读键并重建快照可改变位置。
它未做到的原因：playerState 逐字段 delta 编码有未建模分量（约 4.3 bits/字段），交付的 ps 是空的。
本项目用 `r546-markers.bin` 静态帧 + `wire164.py` **位精确重建**（`identical to r546: True`）绕开该分量，ps 非空，故有相机和可见场景；自主移动仍需完整 usercmd/服务端回路证明。

**注意**：大厅里"角色手里似乎有武器"**不是**对局武器渲染的证据——那是 UI/CEF 用本地存档渲染的预览，`ps.weapon` 在大厅同样是 0（已实测）。

---

## 二、卡点（当前真实阻塞）

### 2.1 武器模型不显示（核心卡点）
- 进地图：r644 认证恢复后仍无手臂、无武器模型；
- 大厅：人物模型有，**手里没有枪模**；
- 仓库：**有贴图、无模型**；
- 装备界面的连杀技能图标错用武器贴图（数据错乱的表征）。

已排除的解释（均有实测记录）：
| 尝试 | 结果 |
|---|---|
| `ps.weapon = 78`（ak47_mp）+ `ps+0x564` owned bit + `ps+0x81C+78` model 三者同时写对 | ✅ 写入成功、❌ 仍不渲染（第 108/109 轮） |
| 追加 `weaponstate`/`weapAnim`/`weaponTime` | ✅ 全对、❌ 仍不渲染 |
| 服务端快照写 `ps.weapons`（`0x55C`） | ❌ codec `-57` 不在 delta 解码路径；客户端 0 处 `[reg+0x55C]` 引用 |
| 客户端 cvar `cg_weapon*` | ❌ 注入成功、无效果 |
| 客户端命令 `give` | ❌ 客户端无此命令 |
| C++ 接口 `WL_SetCurrentWeaponID` | ❌ 只有字符串名、0 处代码引用 |
| gamestate 的 292 条 configstring | ❌ 只有 3 条本地化字符串，无武器定义表 |
| `common_mp.ff`（76 MB，武器定义所在） | ❌ `IWff0100` 格式、非 zlib、内容不可直接读 |

**推断（未验证）**：武器渲染需要客户端内部存在**完整武器实例**（xmodel 句柄 + 动画树实例 + cg 状态机联动），`ps` 整数字段无法伪造该实例。

### 2.2 购买报错"档案快照尚未同步"
- 客户端 `connect` 包带 `statver\19 1248641861`、`secureProfileReady\1`；
- 服务端**没有任何 profile/stat 同步响应**；
- LSG 日志：`auth_request` 曾成功一次（`15:26:06`），随即 `io_error: SSLEOFError`，之后又回到 `tls_handshake_failed / unknown ca`。

### 2.3 离线客户端 TLS 已恢复，档案同步仍待验证
- r643 与 r644 实机：实际运行时 `r107flow/runtime/cacert.pem` 加入当前 LSG 自签证书后，`POST /auth/` 得到 200，业务 task 开始流动；代码已在复用启动时幂等补齐。
- r644 的服务端 `connect=1`、客户端 `net=10`，截图有地图/HUD，但无第一人称武器；`disconnect` 后 `net=0`，可见大厅角色。购买与仓库是否恢复尚未操作验证，不能推断档案同步完成。
- 下列零售客户端的 OpenSSL 路径研究不能直接套用到此离线 EXE；它本体含 `cacert.pem` 字符串，本次改实际运行时文件有 A/B 实机证据。

### 历史零售 TLS 线索（不作为当前离线路线卡点）
- 客户端内置 **OpenSSL 0.9.8zg**，信任锚是 `SSL_CERT_FILE` / `SSL_CERT_DIR` / `C:\Program Files (x86)\Common Files\SSL\cert.pem`；
- **不读 `cacert.pem`**（codex 文档明确记录，实测也确认）；
- 我们的证书（`runs/20261020-live-derived01/tls/auth.crt`，DER sha256 `bd56e356…`）与客户端信任的 CA（`CN=127.0.0.1, O=offline-research`，sha256 `08:9F:0E:09…`）**不匹配**，该 CA 私钥不在仓库内；
- 客户端期望 TLS：**RSA2048+ / TLS1.0 / AES128-SHA:AES256-SHA**。

### 2.4 零售客户端 stage 配方（独立路线）
- **hosts 黑洞**：10 个腾讯域名（`login.codol.qq.com` 等）当前一条都没写；
- **7 个配置文件**：`dwauth.ini`、`iips.ini`、`stun.ini`、`IIPS/IIPSFilelist.ini`、`IIPS/IIPSHostApp.ini`、`TCLS/config/dirserver.xml`；
- **带 `# CODOL-LOCAL-CA` 标记的 CA 块**（注入客户端真实读取的信任库）。

---

## 三、我犯过并已修复的错误（记录以免重蹈）

| 错误 | 后果 | 状态 |
|---|---|---|
| 把 `data/v1649370/local.sqlite3` 的 `profiles` 替换成社区原版（revision 50），其余表保持原样 | **存档数据自相矛盾**：仓库空、大厅无模型、连杀技能错用武器贴图 | ✅ 已从 `backup-before-revert-20261026-232301.sqlite3` 完整恢复（`revision 1241`、`owned_ids 7208`、原 sha256），大厅模型已回来 |
| 往 `319/runtime/client-1649370/cacert.pem` 追加 CA | 不是实际启动的 `r107flow/runtime/cacert.pem`，因此没有改变离线客户端 TLS | 已改为在复用运行时的实际证书包中补入匹配证书 |
| 用"重大突破"描述没有实质进展的尝试 | 误导判断、浪费轮次 | 已在文档中改为只写可验证结论 |
| `--oob-delay` / `--server-command-text ""` | 前者参数不存在，后者被 argparse 拒绝 | 已更正为 `--match-duration`；空文本用默认值 |
| 只改 `local.sqlite3` 的部分表做"回退" | 制造了比原问题更难查的数据不一致 | 已恢复；教训写入本文档 §3 |

---

## 四、复现当前状态的命令

```powershell
cd E:\GAME\COD\codol-airedux\319

# 完整会话（含按键驱动、动态帧重编码）
python tools\session_up_1649370.py --name <name> --rebuild-follow

# 纯净会话（无按键驱动、无动态帧重编码，供人工操作）
python tools\session_up_1649370.py --name <name> --server-seconds 7200 --bridge-seconds 7200
```

`session_up` 会断言 `cls.state == 10`，失败即非零退出。

关键环境：
```
服务端  server1649370  UDP 28969
LSG     server319.lsg  TCP 28969
桥      tools/ring_bridge_1649370.py forward --target 127.0.0.1:28969  UDP 29023
客户端  codol1649370-offline.exe（经 tools/launch_1649370.py 启动）
存档    data/v1649370/local.sqlite3（revision 1241，owned_ids 7208）
```

关键内存布局（本 build 实测）：
```
cl          = *(0x76638F4) ^ 0x6891D1C7
ps          = cl + 0x0C          （cl+0x2C 是 ps+0x20，不是 ps 起点）
ps.origin   = ps + 0x30
ps.weapon   = ps + 0x4C
usercmd.buttons = +0x04
usercmd.forwardmove = +0x1A
keys[]      = 0x7508CBC（12 字节/项，active 在 +0/+4；鼠标左键 0xC8）
cmds[]      = cl + 0x3CD0（44 字节/项）
cls.state   = 0x76446B0
ui_state    = 0x84ABA50
```

---

## 五、若要继续（按优先级）

1. **继续验证档案同步协议**：r644 TLS 认证已恢复，但购买、仓库及玩家装备关系尚未实机确认。先记录缺失的业务 task/响应，再定位档案快照确认。
2. **武器注册与玩家装备**：r645–r647 在真实连接 `net=10` 时，武器字符串表只剩 11 条（`defaultweapon_mp` + 10 个 `defaultknife_mp`），`ps.weapon=0`、`primary=0`、`viewmodelIndex=1023`。在现有完整 gamestate 里加 `(5960,"ak47_mp")`、或把 gametype 从 `war` 改为 `mp`，表仍为 11，枪模仍不显示。下一步需定位进入对局时为什么丢失大厅的 1353 条定义、哪个 fastfile 注册流程没有执行，并由服务端下发有效的玩家装备状态。
3. **保持实验边界**：不要再把单独的 `net=10`、认证 200、`ps` 强写或一条 configstring 视为武器可用；必须读表、读 `ps`、看画面并验证射击反馈。

---

## 六、诚实的总结

**做成了的**：真连接、进图、可见 3D 场景、按键经 `RebuildFollower` 改变位置、HUD、干净回大厅；原生自主移动与射击仍未验收。
可见场景及外部读键导致的位置变化有截图和内存读数，但后者不能替代原生玩家移动验收。

**没做成的**：武器模型、射击、购买、档案同步完整性。
此前 TLS 认证确实回归过；r643/r644 已修复这一层。**武器与购买仍未解决**，不能再把两者直接归因于 TLS 握手。

**教训**：在武器线上花了约 60 轮反复试 `ps` 字段值；TLS 握手曾是独立回归，已修复，但不是枪模缺失的充分解释。
如果早查 `lsg.jsonl` 的统计（`r208`–`r257` 全成功、`r261` 起全失败），可以省下大量时间。
