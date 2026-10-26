# CODOL Build 1649370 — 救援交接（2026-10-26）

> **2026-10-26 续修正**：本交接早先把零售客户端 `codoMP_client_shipRetail.exe` 的 TP/TCLS 故障与隔离离线客户端混为一谈。已验证的 `r107flow/runtime/codol1649370-offline.exe` 路线可进入大厅与 `mp_crash_tropical` 对局画面；用户现场确认未拉起 TP、未出现 100 大厅错误。当前仍**无可控玩家**。本文件中“3D 场景从不渲染”“可用私有客户端副本已丢失”等绝对表述仅可作为当时零售路径的历史判断，不能否定现存的 `r107flow`。另一次工作树清理错误地恢复了 `tools/launch_1649370.py` 的 `+cl_demo_play testdemo`，使后续启动误走 demo；现已移除。复现步骤见 [已验证启动流程](docs/1649370-KNOWN-GOOD-STARTUP.md)，资源副本见 [资源索引](resources/1649370/README.md)。

> 用途：把当前状态交给下一个接手者（Codex）。本文件只写**可执行的结论**，不写流水账。
> 长程目标已于第 521 轮**暂停**（goal revision 9, paused）。恢复前请先读完本文件。
> 完整日志见 `1649370-STATUS.md`（1085+ 节，含 131 处更正标记）与 `PROJECT_STATUS.md`。

---

## 0. 一句话现状

**服务端已能完整驱动协议层，客户端被"接受"到 `net_state=10` 并可由服务端送回大厅（state 0）；但它拿到的 playerState 是空的，所以 3D 场景从不渲染。**
**验收第 5 项（`mp_crash_tropical` 中可控玩家的截图）从未达成，也不存在这样一张截图。**

---

## 1. 已达成且可复现（证据充分，不要重复验证）

```
协议层全通: getchallenge -> connect -> stats -> gamestate -> snapshot
             -> 对局计时结束 -> OOB disconnect -> 回大厅 state 0
客户端网络状态到达 net_state = 10
服务端可按时长自动结束对局
playerState 块在遵守 frame-loop 布局后确实被接受（state 10 的来源）
```

证据：

```
evidence/experiments/20261023-codex-match-flow.json
evidence/experiments/20261023-codex-state-vs-uistate.json
evidence/experiments/20261023-codex-oob-disconnect-success.json
evidence/experiments/20261023-codex-ps-nonempty-accepted.json
```

---

## 2. 最深的诊断：为什么画面不出现（`RELEASE.md` §3，四条都是实测）

```
1. 实体块（A=1）设置 global stream-error flag —— 实体循环没有基于计数的退出
   -> 实体快照被拒绝           20261023-codex-error-persists.json

2. playerState 块确实被接受（这就是 state 10 的来源）
                              20261023-codex-ps-nonempty-accepted.json

3. 逐字段 delta 编码仍有一个未建模分量，实测约 4.3 bits/字段
   -> 交付出去的 playerState 是空的 -> cgame 没有相机、没有本地玩家
                              20261023-codex-ps-full-overrun.json

4. 绕开线格式直接写 playerState history ring 无效
   -> cgame 消费的是"每快照副本"
                              20261023-codex-ring-write-no-effect.json
```

**八条独立路径已试过并失败**：实体增量编码、clc 注入、cg 注入、UI 强制、远程回调、ps ring 写入、ps slot 写入、vieworg 写入。

**结论**：这是**构建级限制**（offline rebuild 的 3D 场景路径惰性），不是服务端缺陷。

---

## 3. 当前环境缺了两样东西（这就是"进度倒退"的真正原因）

### 3.1 能工作的私有客户端副本已丢失

`1649370-MULTIAGENT-ROADMAP.md:290` 记录的可用做法：

> 把 `使命召唤OL` 根目录复制/联接成私有 `runs/full-client-private`，**省略 ACE/TGuard/TerSafe/PolicyProbe/TenRpcs 等反作弊依赖**

- **该副本已不存在**
- **仓库里没有重建它的工具**（只有 `patch_auth_bypass.py` / `record_bypass.py`）
- 现在所有测试跑在**全客户端**上：`1604220\runtime\client-1649370` → junction → `319\runtime\client-1649370`
- 全客户端含真文件：`TP3Helper.exe` 4,063,728 / `TenRpcs.dll` 17,408,064 / `TerSafe.dll` 8,280,328 / `PolicyProbe.dll` 6,855,224 / `ACE-DRV32.dll` 6,835,192 / `ace-ats32.dll` 1,758,784
- 全客户端会走 TP/TCLS 门控（`1649370-STATUS.md:2576`：「全客户端退出根因：TCLS 启动器检查未通过」）
- **直接后果**：客户端连 LSG(4174) 都不尝试 —— `319/runs/live-lsg.jsonl` 是 **0 行**

### 3.2 客户端信任的 CA 私钥不在仓库里

客户端 TLS 栈是**内置 OpenSSL 0.9.8zg**（DLL 内有版本串 `OpenSSL 0.9.8zg 11 Jun 2015`）。它读的信任锚是：

```
SSL_CERT_FILE 环境变量
SSL_CERT_DIR  环境变量
C:\Program Files (x86)\Common Files\SSL\cert.pem
C:\Program Files (x86)\Common Files\SSL\certs\
```

**不是 `cacert.pem`**（`cacert.pem` 这个文件名在 DLL 中出现 **0 次**；`cacert` 的 18 次命中全是二进制噪音如 `ocacert]`）。

当前系统上那个 `cert.pem` 只有一张证书：

```
subject/issuer = CN=127.0.0.1, O=offline-research
sha256 = 08:9F:0E:09:D7:15:0B:83:3D:96:2F:E8:8C:9B:F3:A5:9C:49:B5:A4:78:24:3C:F6:F8:A8:61:00:46:AE:1D:09
写入时间 2026-10-20 21:16:35
```

我们手上持有的证书（**全部与它不匹配**）：

```
1604220/runs/stage1/tls/ca.crt      FF:4A:28:44...  CN=CODOL AirRedux Lab CA, O=offline-research
1604220/runs/stage1/tls/auth.crt    C0:EA:26:2B...  CN=codol-lobby.local (SAN: localhost, codol-lobby.local, 127.0.0.1)
1604220/runs/live-stage/tls/auth.crt DB:BE:34:90...
319/runs/20261020-live-derived01/tls/auth.crt  BD:56:E3:56...   <== 519-521 用的就是这张
```

**没有 `CN=127.0.0.1` 那张 CA 的私钥**，所以 Auth(4175) 的 TLS 在当前环境必然失败：

```
319/runs/live-auth.jsonl  三次连续
"tls_handshake_failed", "reason": "SSLError: [SSL: TLSV1_ALERT_UNKNOWN_CA] tlsv1 alert unknown ca", "requests": 0
```

---

## 4. "大厅 100 已解决"的实现：代码在，证据没了

`HANDSHAKE-STATUS.md` 记录得很明确：

```
第 150 行：LSG 服务端回 type-4 业务帧
          [u32 11][0x04][0x0A 0x08][127.0.0.1][4174]
          后，客户端状态机到达 DW_LOBBY_CONNECTED
第 157 行：证据 runs/20261020-session46/patch.json、session47/patch.json（采样 100 次，状态保持）
第 158 行：关键修正 —— 只发一次 type-4 帧（frame85_reply beat=0），
          不要持续发心跳（for _beat in range(8) 会让客户端第二次心跳后 ConnectionAbortedError）
```

- **实现还在**：`server319/lsg_derived.py`（`python -m server319.lsg` 默认走它）
- **但 `runs/20261020-session46/`、`runs/20261020-session47/` 已不存在**
- `server319/lsg.py` 里那个 `LsgServer` 是**保留的 legacy probe**，docstring 明说"did not establish a usable lobby"，只有 `--legacy-probe` 才会用到

**注意**：这条大厅路径（LSG 明文 TCP + type-4 帧）与 Auth(4175) 的 TLS **是两条独立的线**。Auth TLS 失败不一定挡住大厅，但 TP 门控会。

---

## 5. 各服务的正确启动方式（已用端口 bind 验证过，不是推断）

```powershell
# Auth 4175 —— --client-dir 必需；--evidence 必须在 319/runs 内，否则 rc=2
python -m server319 --auth --port 4175 `
    --cert runs\20261020-live-derived01\tls\auth.crt `
    --key  runs\20261020-live-derived01\tls\auth.key `
    --client-dir "E:\GAME\COD\codol-airedux\1604220\runtime\client-1649370" `
    --evidence runs\live-auth.jsonl --seconds 7200
# 成功标志: "Auth listening on 127.0.0.1:4175 for 7200s"

# LSG 4174 —— --cert --key --log 三者都是必需参数（--log 少给会 rc=2 静默退出）
python -m server319.lsg --port 4174 `
    --cert runs\20261020-live-derived01\tls\auth.crt `
    --key  runs\20261020-live-derived01\tls\auth.key `
    --log  runs\live-lsg.jsonl `
    --client-dir "E:\GAME\COD\codol-airedux\1604220\runtime\client-1649370" `
    --allow-auth-tls --seconds 7200
# 成功标志: "LSG derived listening 127.0.0.1:4174 for 7200s"

# lobby_udp 3074 —— 位置参数 port seconds logfile；cwd 必须是 1604220
# 环境变量: LOBBY_UDP_REPLY (hex), LOBBY_UDP_REPLY_MATCH=1402, LOBBY_UDP_ECHO=0
# 136 字节应答: rec[0:4]=127.0.0.1, rec[0x80:0x84]=u32 2, rec[0x84:0x86]=u16 3074
python -m server319.lobby_udp 3074 200 runs\live-lobby.jsonl
# 成功标志: {"event": "endpoint_up", "port": 3074}
```

**客户端配置**（`dwauth.ini`，当前内容即正确）：

```
127.0.0.1 4174
127.0.0.1 4175
03EA
```

**客户端启动**：`codoMP_client_shipRetail.exe -q`，挂起启动后在 **t≈14s** 打补丁：

```
VA 0x79A78E:  74 B2  ->  90 90
```

---

## 6. 已被回滚的改动（不要再动）

第 520 轮跑过 `stage_redirect.py stage`，它改了 4 个文件：

```
1604220/runtime/client-1649370/dwauth.ini   重写内容与 pre-image 逐字节相同（SAME）
1604220/runtime/client-1649370/stun.ini     同上（SAME）
1604220/runtime/client-1649370/iips.ini     同上（SAME）
1604220/runtime/client-1649370/cacert.pem   176 -> 177 张证书（唯一真实改动）
```

第 521 轮已跑 `stage_redirect.py restore`，**4/4 文件 sha256 全部 matches_pre: true**，`cacert.pem` 回到 176 张。

**命令行**（如需再次核对）：

```powershell
cd E:\GAME\COD\codol-airedux\1604220
python tools\stage_redirect.py restore --client-dir runtime\client-1649370 --run-dir runs\live-stage
```

**结论：当前客户端没有任何被修改的文件。不要再往 `cacert.pem` 追加 CA —— 客户端 TLS 不读它。**

---

## 7. 本会话新增的代码资产（含明确局限）

### 7.1 `server1649370/ps_codec.py`

```python
# codec -97 现在支持两种形式（原来只有 1+32，而且 read 侧对 gate=0 直接 raise）
gate=0 -> 1 bit + 8 bits，语义是「增量」：value = current - decoded8
gate=1 -> 1 bit + 32 bits，语义是「绝对值」
# 由环境变量 PS97_GATE0=1 选择写哪种

# 新增 codec -58（原不支持）：
#   0x66FE90 布局 = 1 位门控；gate=0 -> 读 2 位整数(0..3) 再乘 10.0（比例常量 0xD599EC = 10.0）
#   gate=1 -> 走浮点路径 0x66EE60
if value == 0 or value % 10 != 0 or value // 10 > 3:  gate=1 + le32
else:                                                  gate=0 + 2 bits(value // 10)

# 新增 codec -57（原不支持）：1 位布尔（0x6708F0 读 1 位）

# _self_test() 已补入 -58/-57，当前 rc=0
```

### 7.2 `tools/build_1649370_snapshot_entity.py`

```python
FIELD_CODECS          # 0xDA63E8 的 24 项 offset -> codec 映射
_write_ps_deltas()    # write_gap 到目标 offset + write_field，末尾 writer.bit(0) 终止
build(..., ps_fields={offset: value})   # None 保持原来的 skip 行为（13 字节，无回归）
```

生成产物（**从未被送给客户端**）：

```
runs/snapshot-ps58.bin   16 字节  （ps_fields={76:10}，-58 字段）
runs/snapshot-ps57.bin   16 字节  （ps_fields={65:1}，-57 字段）
runs/snapshot-both.bin   17 字节  （两者）
runs/snapshot-... skip 模式仍为 13 字节
```

**局限（必须记住）**：这些只证明**我们自己的写入器和读取器彼此同意**，**从未证明与客户端同意**。它们是等待验证的假设。

### 7.3 反汇编结论（静态，其中两条被后续翻案，用最新版）

```
0x4F8CF0          未导出、零调用者、8 个段中零指针引用  -> 入口是死代码（§1071/§1083 已证）
0x4F8D70          不是独立函数，它是 0x4F8CF0 内部代码（回溯 prologue = 0x4F8CF0）
                  但 0x4F9428（在 0x4F9240 内）确实 call 它
                  => "死函数"只意味着入口不可达，不代表函数体内每个字节都不可达
0x4F9240          有活调用者 0x4FE312 / 0x4FE658（在 0x4FE220 内）
                  0x4FE220 <- 0x4FEA20 <- 0x77FA64（引擎循环内，0x77FA6E: jmp 0x77FA04）
0x5C2260          同一条链上的 CL packet 事件，再往下 0x5C1EE0 做 "R" 前缀分派
环 B 游标          0x7872C00 / 0x7872C04 —— 实测在客户端运行期间始终 (0,0)，从未初始化
```

**待验证**：这条"活路径触及死函数内部代码"的静态结论，需要运行时断点/计数器证实，静态分析在本项目已被翻案两次。

---

## 8. 不要做的事（都踩过）

```
x 不要用 tools/run_match.py 驱动零售客户端
  它启动的是 codol1649370-offline.exe（11MB 社区镜像，不是零售客户端），
  而且要求 --reuse-runtime 指向已存在的 offline-runs session（当前不存在）。
  它的 "engine never initialised" 就是这个原因。它退出时不清理自己启动的子进程，
  会留下孤儿（曾有两个 --seconds 3600 的进程挂了两小时）。

x 不要丢弃子进程的 stderr
  LSG 缺 --log 会 rc=2 直接退出，Auth 缺 --evidence（或路径不在 319/runs 内）也会 rc=2。
  曾因此报告"服务已启动"而实际一个都没起。启动后必须验证端口 bind。

x 不要把 cacert.pem 当作客户端的 TLS 信任源
  客户端是 OpenSSL 0.9.8zg，读 SSL_CERT_FILE / SSL_CERT_DIR / Common Files\SSL。

x 不要持续发心跳 / 重复发 type-4 帧
  会让客户端在第二次心跳后 ConnectionAbortedError（HANDSHAKE-STATUS.md:158）。

x 不要用 Stop-Process 匹配 server319 这类名字去清理
  会连自己一起杀。按精确 PID 杀。
  PowerShell 里不要用 $pid（只读自动变量），用 $procId 之类。

x 不要因为静态分析串出一条 call 链就宣布"重大突破"
  本项目已两次翻案（§1082 撤回、§1099 修正）。运行时测量优先。

x 不要动客户端文件（尤其 cacert.pem）
  即使可回滚，也不该动已验证环境。
```

---

## 9. 恢复路径（按优先级，未执行）

```
第 1 步（前提，不做则后面全部无效）
  重建省略反作弊依赖的私有客户端副本，跳过 TP/TCLS 门控。
  做法参考 1649370-MULTIAGENT-ROADMAP.md:290：把游戏根目录复制/联接成私有副本，
  省略 ACE / TGuard / TerSafe / PolicyProbe / TenRpcs / TP3Helper / ace-ats32 等。
  判据：客户端启动后不弹 "请使用腾讯游戏登录器启动游戏"，且能尝试连接 4174。

第 2 步（TLS 信任）
  二选一：
  a) 找回 CN=127.0.0.1（O=offline-research）那张 CA 的私钥，用它重签服务端证书；
  b) 把我们 lab CA 装进客户端真实读取的信任库（Common Files\SSL\cert.pem 或 SSL_CERT_FILE），
     并用 openssl s_client 验证客户端视角能验通。

第 3 步（大厅）
  用 lsg_derived 的 type-4 帧路径复现 DW_LOBBY_CONNECTED：
  只发一次 [u32 11][0x04][0x0A 0x08][127.0.0.1][4174]，不要心跳。

第 4 步（快照与 playerState）
  把 runs/snapshot-ps58.bin / ps57.bin 通过完整链路（gameserver + ring_bridge）送给客户端，
  观察 stream-error flag 与 ui_state。这是 7.1/7.2 那些 codec 工作的第一次真实检验。

第 5 步（仍可能失败的点）
  即使 1-4 全通，RELEASE.md §3 第 1、3 条仍然存在：
  实体块会设 stream-error、playerState 可能仍为空。那两条不在本次 codec 工作的覆盖范围内。
```

---

## 10. 关键文件与证据索引

```
319/1649370-STATUS.md              主日志（1085+ 节；§1074 状态、§1084 阅读指南、§1102 审查）
319/1649370-RESCUE-HANDOFF.md      本文件
319/PROJECT_STATUS.md              逐轮摘要
319/RELEASE.md                     交付说明；§3 根因链；§7 协议附录（快照布局/codec 语义）
319/HANDSHAKE-STATUS.md            LSG 握手全过程；:150 type-4 帧；:157/158 证据与修正
319/1649370-MULTIAGENT-ROADMAP.md  :290 私有副本做法；TP3Helper 相关记录
319/docs/GOAL.md                   目标原文
319/docs/NEXT-SESSION.md           新会话启动指引
319/server1649370/                 服务端：gameserver.py / native_gamestate.py / ps_codec.py
319/server319/                     Auth 4175 / LSG 4174 / lobby_udp 3074
319/tools/                         约 500 个脚本（disasm_image_1649370.py 是可靠的反汇编器）
1604220/tools/                     patch_auth_bypass.py / stage_redirect.py
1604220/runtime/client-1649370/    客户端（junction -> 319/runtime/client-1649370）
```

---

## 11. 一句话给接手者

**协议层是通的，缺的是"让客户端愿意把画面画出来"以及"让它不触发 TP 门控地跑到那一步"。**
**本仓库里价值最高的东西不是服务端代码，而是这份"哪些结论经过验证、哪些被翻过案"的记录 —— 请继续维持这个区分。**

---

## 12. 完整客户端 stage 配方（2026-10-26 补充，这是最关键的一节）

### 12.0 结论先行

**之前所谓的"进度倒退"其实不是倒退 —— 是从未做过完整的 stage。**

上游参考实现 `_upstream/codol_launcher/tools/native-client/reference/launcher/core/prep.py`
里的 `apply()` 才是完整配方：改 **7 个文件 + hosts + CA**。我们只处理了 4 个（其中 3 个写回原值），
**完全没碰 `TCLS`、`IIPS` 的两个 ini、以及 hosts 黑洞** —— 所以客户端启动时仍去解析真实腾讯域名、
尝试连外网、卡在 TCLS/TP 检查，根本不进网络流程。

### 12.1 hosts 黑洞（10 个域名，当前一条都没有）

上游 `HOSTS_DOMAINS`：

```
login.codol.qq.com
tub.codol.qq.com
stat.iips.qq.com
ctrl.iips.qq.com
iips.speed.qq.com
rtstat.iips.qq.com
down-update.qq.com
stun.qq.com
stun1-stn.codol.qq.com
stun2-stn.codol.qq.com
```

需要以 `127.0.0.1 <domain>`（或 `::1`）形式写进 `C:\Windows\System32\drivers\etc\hosts`。
**当前 hosts 里这 10 个域名一个都没有**（只有 steam 的条目）。

> 注：改 hosts 会影响整机解析。上游的设计是把这些域名黑洞到回环，让客户端的请求落到本地服务。

### 12.2 七个配置文件的正确内容

```python
# dwauth.ini —— 上游格式是「每个字段单独一行」
'%s\r\n%s\r\n%s\r\n%s\r\n3ea\r\n' % (addr, port, addr, port)

# iips.ini
'iips_url="http://%s:8000/"' % addr          # 注意上游用 8000，不是 8099

# stun.ini —— 三行 addr
''.join('%s\n' % addr for _ in range(max(3, len(lines))))

# IIPS/IIPSFilelist.ini —— 改写每个 FileUrl
re.sub(r'(FileUrl\s*=\s*)(\S+)', fix, txt)
#   fix: 'http://%s:8000/%s' % (addr, basename(url))

# IIPS/IIPSHostApp.ini —— 改写 Address
re.sub(r'Address=udp://[^\r\n]+', 'Address=udp://%s:8000' % addr, txt)

# TCLS/config/dirserver.xml —— 改写 host 属性（TP 门控关键）
re.sub(r'host="[^"]*"', 'host="%s"' % addr, txt)
```

### 12.3 cacert.pem 必须带标记

```python
CA_MARKER = '# CODOL-LOCAL-CA'

# 注入方式：先找标记块并替换；找不到才 append
pem = (CA_MARKER + '\n' + ca_pem.strip() + '\n').encode()
# 追加时还要保证原文以 \n 结尾
```

**单纯的裸 PEM append 缺少标记行**（我们 round 520 的做法）。虽然上游的 fallback 也是 append，
但补上标记才能被识别/替换，也便于 `restore`。

### 12.4 TLS 参数必须匹配（`_upstream/codol_server/apps/codol-platform/src/native_config.rs:429`）

```rust
"tls10_loopback_explicit_certificate" => {
    if key.id() != RSA || key.bits() < 2048 { bail!("requires project RSA2048 or stronger") }
    tls.set_security_level(0);                        // TLS1.0 的 legacy 签名需要
    tls.set_min_proto_version(TLS1);
    tls.set_max_proto_version(TLS1);
    tls.set_cipher_list("AES128-SHA:AES256-SHA");      // 只有这两套
    tls.set_options(NO_RENEGOTIATION);
}
```

注释说明：这个子集**正好交集**于实测的 1604220 ClientHello 的 RSA AES 套件。
所以服务端必须是 **RSA2048+ / TLS1.0 / AES128-SHA 或 AES256-SHA**。
Python 的 `ssl` 默认配置可能不支持 TLS1.0 或这三套 cipher —— 需要显式设置：
`ssl.SSLContext(PROTOCOL_TLS_SERVER)` + `set_ciphers('AES128-SHA:AES256-SHA')` +
`minimum_version=maximum_version=TLSv1` + `security_level` 下调。

### 12.5 关于 `data/tls/auth.key`

**不存在。** 全盘 `E:\GAME\COD` 搜 `auth.key` 只有 3 个，全部是本项目自己生成的：

```
1604220\runs\live-stage\tls\auth.key        2026-10-26 09:48
1604220\runs\stage1\tls\auth.key            2026-10-26 07:15
319\runs\20261020-live-derived01\tls\auth.key  2026-10-24 23:03
```

没有 `data\tls` 目录；`319\runtime` 与 `1604220\runtime` 下都没有 `auth.key`。
客户端信任的那张 `CN=127.0.0.1, O=offline-research` CA 的私钥**仍不在仓库内**，
但按 12.1-12.4 的完整配方，可以用我们自己新生成的 CA 重新走一遍（注入带标记的 CA 块即可）。

### 12.6 修订后的第 1 步（替换 §9 的第 1 步）

```
按 12.1 ~ 12.4 做完整 stage（7 文件 + hosts + 带标记 CA + TLS1.0/RSA2048/AES-SHA），
而不是只改 4 个文件。
然后再看客户端是否：
  a) 不再弹 "请使用腾讯游戏登录器启动游戏"
  b) 开始尝试连接 4174（live-lsg.jsonl 出现非零行）
只有 b) 成立，后面的快照/codec 工作才有意义。
```
