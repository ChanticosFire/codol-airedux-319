# CODOL Build 1649370 — 当前状态与卡点（2026-10-26 收尾版）

> 本文档替代此前所有"交付说明"性质的内容。只写**可验证的当前状态**、**确切卡点**、**已修复的自身错误**。
> 历史流水见 `1649370-STATUS.md`；逐轮摘要见 `PROJECT_STATUS.md`；codex 的完整交接见 `1649370-RESCUE-HANDOFF.md`。

---

## 一、已达成（有截图/日志/内存读数支撑）

| # | 项 | 证据 |
|---|---|---|
| 1 | 协议层全通：`getchallenge` → `connect` → `stats` → `gamestate` → `snapshot` | `runs/r558-gs.jsonl`（connect=2, stats=2）、`runs/r576-gs.jsonl` |
| 2 | 客户端进入 `net_state = 10`（`CA_ACTIVE`） | 多轮 `_sample_state.py` 实测，稳定保持 |
| 3 | **3D 场景可见** | `runs/r581-moved.png`、`runs/r601-t2.png`：完整街景、建筑、柱子、阴影、电线、远景山 |
| 4 | **玩家可由真实按键驱动移动** | `runs/r601` 四采样点：`origin.x` `111.5 → -116.5 → -477.5 → -819.5`（累计 931 单位）；松开即停；按 S 反向 |
| 5 | HUD 完整 | 雷达（箭头随移动变化）、计分板、生命值条、"战术团队竞技模式" |
| 6 | `ui_state = 0`（非 5） | 多轮实测 |
| 7 | 干净回大厅 | `cbuf "disconnect"` → `net=0`、`table=1353`、`runs/r615b-cbuf-disconnect.png`（mean≈92，无弹窗） |
| 8 | 大厅角色模型可见 | `runs/restored-session2.png`（存档恢复后，角色完整渲染） |

**第 3、4 两项是 codex `RELEASE.md` §3 判定为 "build-level limitation / not achieved" 的部分。**
它未做到的原因：playerState 逐字段 delta 编码有未建模分量（约 4.3 bits/字段），交付的 ps 是空的。
本项目用 `r546-markers.bin` 静态帧 + `wire164.py` **位精确重建**（`identical to r546: True`）绕开该分量，ps 非空，故有相机、能渲染、能移动。

**注意**：大厅里"角色手里似乎有武器"**不是**对局武器渲染的证据——那是 UI/CEF 用本地存档渲染的预览，`ps.weapon` 在大厅同样是 0（已实测）。

---

## 二、卡点（当前真实阻塞）

### 2.1 武器模型不显示（核心卡点）
- 进地图：无手臂、无武器模型；
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

### 2.3 LSG TLS 信任链未建立
- 客户端内置 **OpenSSL 0.9.8zg**，信任锚是 `SSL_CERT_FILE` / `SSL_CERT_DIR` / `C:\Program Files (x86)\Common Files\SSL\cert.pem`；
- **不读 `cacert.pem`**（codex 文档明确记录，实测也确认）；
- 我们的证书（`runs/20261020-live-derived01/tls/auth.crt`，DER sha256 `bd56e356…`）与客户端信任的 CA（`CN=127.0.0.1, O=offline-research`，sha256 `08:9F:0E:09…`）**不匹配**，该 CA 私钥不在仓库内；
- 客户端期望 TLS：**RSA2048+ / TLS1.0 / AES128-SHA:AES256-SHA**。

### 2.4 缺失的 stage 配置（codex 文档 §12）
- **hosts 黑洞**：10 个腾讯域名（`login.codol.qq.com` 等）当前一条都没写；
- **7 个配置文件**：`dwauth.ini`、`iips.ini`、`stun.ini`、`IIPS/IIPSFilelist.ini`、`IIPS/IIPSHostApp.ini`、`TCLS/config/dirserver.xml`；
- **带 `# CODOL-LOCAL-CA` 标记的 CA 块**（注入客户端真实读取的信任库）。

---

## 三、我犯过并已修复的错误（记录以免重蹈）

| 错误 | 后果 | 状态 |
|---|---|---|
| 把 `data/v1649370/local.sqlite3` 的 `profiles` 替换成社区原版（revision 50），其余表保持原样 | **存档数据自相矛盾**：仓库空、大厅无模型、连杀技能错用武器贴图 | ✅ 已从 `backup-before-revert-20261026-232301.sqlite3` 完整恢复（`revision 1241`、`owned_ids 7208`、原 sha256），大厅模型已回来 |
| 往 `runtime/client-1649370/cacert.pem` 追加 CA | 客户端根本不读该文件，**完全无效操作** | 已记录，不再做 |
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

1. **先解决 LSG 认证**（§2.2/§2.3）——它是"账号/档案体系"的入口，武器/背包/购买都是其下游表现。
   - 方向 A：按 codex §12 做完整 stage（hosts + 7 文件 + 带标记 CA + TLS1.0/RSA2048/AES-SHA）；
   - 方向 B：找回 `CN=127.0.0.1` 那张 CA 的私钥，重签服务端证书；
   - 验证判据：`lsg.jsonl` 出现 `auth_request` 后**不再 `SSLEOFError`**，而是完整的 `auth_response`。
2. **武器实例问题**（§2.1）——在 LSG 通了之后再看；"玩家没有装备武器"可能是档案体系未建立的下游后果。
3. **不要再投入**：`cacert.pem` 追加 CA、`ps` 字段试值、`cg_weapon` cvar —— 均已证伪。

---

## 六、诚实的总结

**做成了的**：真连接、进图、可见 3D 场景、真实按键移动、完整 HUD、干净回大厅、`ui_state=0`。
均有截图和内存读数，且第 3/4 项是 codex 判定为不可能的部分。

**没做成的**：武器模型、购买、档案同步。
三者共同上游是 **LSG 认证未建立**，而不是"武器代码没写"。

**教训**：在武器线上花了约 60 轮反复试 `ps` 字段值，而真正的断点在**最开始的 TLS 握手**。
如果早查 `lsg.jsonl` 的统计（`r208`–`r257` 全成功、`r261` 起全失败），可以省下大量时间。
