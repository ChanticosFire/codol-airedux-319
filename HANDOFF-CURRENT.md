# 交接文档：CODOL 3.19.26.17 / Build 1604220 离线复活 — 2026-10-22

> **★ 最新状态（2026-10-22 21:30，以本节为准）**
>
> 工作目标已切到 **Build 1604220**（社区称 3.19.26.13），见 [VERSION-SWITCH.md](VERSION-SWITCH.md)。
> **`[100]无法连接大厅服务` 已消除**，客户端现在报 `[111]与大厅服务失去连接`；采样首次出现
> **`dw=5, ui=9, ready=1, lstate=2, state=DWLOGON_REGISTERCODOID_COMPLETE`**。
>
> 三个决定性修复：
> 1. **TLS 证书必须自签（叶子=CA）**，不能用 CA 签发叶子；
> 2. **Auth 响应只回 7 个字段**（`auth_task=请求+1`、`code="700"` 字符串、真实 Tiger 票据…）；
> 3. **LSG 密钥由 `server319/lsg_derived.py` 从握手 transcript 派生**，不再读客户端内存。
>
> 剩余缺口：`svc71/task9`（社区给 82B bdMatchMaking 条目）与 `task3`，以及后续任务链。
> 详见本文件 §14 与 [PROJECT_STATUS.md](PROJECT_STATUS.md) §12.10。

> **给 Codex 的完整交接。** 下列 §0–§13 是 Build 1649370 时期的历史记录（方法论、地址表、阴性结果仍然有效），
> **§14 是 1604220 的最新进展与下一步**。所有地址均为运行时实测，所有结论都有 `runs/` 证据。
> 工作目录：`E:\GAME\COD\codol-airedux\319`

---

## 0. 一句话现状（1649370 时期，已过时，见上方最新状态）

**Auth / IIPS / TCLS / LSG 握手 / 0x85 解密（C2S）全部打通；服务端已拿到正确的协议算法与帧格式。当时认为缺口是 `packet_buffer` 与 `SESSION_KEY`；该判断后来被 §15 行（transcript 审计）反证，并在 1604220 上以 `lsg_derived.py` 的派生实现彻底解决。**

---

## 1. 运行环境（硬要求）

| 项 | 值 |
|---|---|
| 权限 | **管理员**。IIPS 需 `SeDebugPrivilege` + `SeCreateGlobalPrivilege`；Medium 下游戏 14 秒内不创建 `IIPSHostApp`，IIPS 必失败 `8189fec` |
| 客户端 | `runtime\client-1649370\codoMP_client_shipRetail.exe`（隔离副本；原件只读） |
| 启动参数 | `-q` |
| 服务端 | `python -m server319 --auth ... --port 4175` + `python -m server319.lsg ... --port 4174` |
| TLS | `runs\20261020-session03\tls\auth.crt` / `auth.key`（脚本会自动回退到此） |

---

## 2. 已打通（有证据）

### 2.1 Auth（`server319/auth.py` + `ticket.py`）
- `auth_task` **必须 = 请求值 + 1**（10 → 11）；`code=700`。
- 必须带 `member_position` / `estimated_wait_time` / `next_poll_after`。
- 票据需结构化（Tiger 校验）。`ticket.py`：`SESSION_KEY = bytes(range(24))`，写入 ticket `[97:121]`，`[124:128]` = `tiger(ticket[:121])[:4]`，magic `0xEFBDADDE`，共 128B。
- 证据：`runs/20261020-codex-*`、`runs/20261020-session09+`。

### 2.2 LSG 握手（`server319/lsg.py`）

| 方向 | 帧 | 备注 |
|---|---|---|
| C→S | **28B hello**：`c8000000 c8000000 d2000000 dc000000 00000800 <8B>` | 首字节 0xC8 |
| S→C | **26B 门控**：`[u32 22][0x01][0x81][u32 0xDC(220)][8B MARK][8B nonce]` | **版本必须 220**。210 时 `stage` 永远到不了 3 |
| C→S | **153B 0x82**：`[u32 149][0xAB][0x82][0791FA00][4B session][06000000]…` | 尾 8B = `CHAL[:8]` |
| S→C | **0x83**：`[u32 10][0xAB][0x83][8B token]` | token = `conn+0x5FC`；客户端接受后发 0x85 |
| C→S | **130B 0x85**：`[u32 126][0xAB][0x85][u32 seq][16B IV][96B cipher][8B tail]` | 只在 0x83 成功后出现 |

### 2.3 0x85 解密（C2S，**已验证可用**）
- 密钥：`conn+0x604` 是**指针**，16B 密钥在 `[ptr+0x9C]`。
- 算法：AES-128-CBC，IV = 帧内 offset 10。
- 明文 84B（与 1604220 资料逐字节一致）：

```
54 00 00 00 86 47 03 04 13 08 10 00 00 00 "nQloP0oCVWR6RDJS"
13 08 10 00 00 00 2b×16 08 9e cb e6 01
13 08 00 00 00 00 13 08 00 00 00 00
10 "1C-83-41-CE-8D-EE" 00 00
```

> 注意：这个能否解开只是**旁证**——它证明 `[conn+0x604]+0x9C` 等于 `dec_key`，可作为派生算法的**自检目标**（见 §4）。

---

## 3. `bdproto319.py`：正确的协议算法（用户提供，最关键资料）

文件在 `他人文件参考/bdproto319.py`（323 行，`lsg.js` 移植）。它推翻了我们此前三处根本假设。

### 3.1 密钥派生（服务端自己算，**不读内存**）

```python
SESSION_KEY = bytes.fromhex('8ecd56428021ead23643c94801f4095daafe3875f087b13f')

out1  = SHA1(packet_buffer)
data3 = HMAC-SHA1(key=out1, data=SESSION_KEY)      # ★ 参数顺序与常规相反
out2  = calc_hmacs(data3, b'CLIENTCHAL', 16)  -> response_id = out2[8:16]
out3  = calc_hmacs(data3, b'BDDATA', 72)
hmac_key      = out3[0:20]     # 校验客户端帧
resp_hmac_key = out3[20:40]    # 签我们的响应
dec_key       = out3[40:56]    # 解客户端帧
enc_key       = out3[56:72]    # 加我们的帧
```

`calc_hmacs(data, key, size)` **不是**标准 HKDF：

```python
dst = b''; count = 1
buf = key + bytes([count])
result = HMAC(key=data, data=buf)
dst += result[:min(20, size)]
while len(dst) < size:
    buf = result + key + bytes([count + 1]); count += 1
    result = HMAC(key=data, data=buf)
    dst += result
return dst[:size]
```

### 3.2 响应帧（`make_encrypted_reply`）——**帧头 `AB 85`，尾部真 HMAC**

```python
len_buf    = u32(len(service_payload))
inner      = 0x01
enc_buffer = align16(len_buf + bytes([inner]) + service_payload)
enc_data   = AES-128-CBC(enc_buffer, keys['enc_key'], seed)
body       = b"\xAB\x85" + u32(msg_count) + seed(16B) + enc_data
total_len  = u32(len(body) + 8)          # ★ 长度含尾部 8B
response   = total_len + body
response  += HMAC-SHA1(keys['resp_hmac_key'], response)[:8]   # ★ 真 HMAC，不是 8 个零
```

默认 `seed = 5eed5eed5eed5eed5eed5eed5eed5eed`（**固定**，不是随机 IV）。

### 3.3 三条与我们旧实现相反的结论

1. **帧头 `AB 85`**（我们后期改成了 `01 85`，方向错了）。
2. **尾部 8B 是真 HMAC**（我们一直发 8 个零）——**这一条足以解释为什么每一帧都被客户端丢弃**：。
3. **密钥来自 `packet_buffer` 派生**，不是从 `conn+0x604` 读。

### 3.4 其它可用工具函数

| 函数 | 用途 |
|---|---|
| `make_header_ack()` / `_v2()` / `_319()` / `_real()` | 各种 hello/ack 变体（`AB 90`、`AB FF` 等） |
| `make_file_info` / `make_file_data` | svc10 文件应答 |
| `ByteWriter` / `TypeReader` | `uint32/uint64/byte/string/blob/raw` 编码 |

---

## 4. 唯一缺口：`packet_buffer` 与 `SESSION_KEY`

### 4.1 自检方法（已就绪）

`bdproto319.derive_keys(packet_buffer)` 必须能复现客户端内存里的 `dec_key`：

```
目标 dec_key = 8e6b3363f46e0be95f2cae182adc8a1a   （runs/20261020-base）
```

（该密钥实测能解开客户端 0x85，明文头 `54 00 00 00 86 47…`）

脚本：`runs/verify_keys.py`、`runs/find_packet_buffer.py`。

### 4.2 已排除（**不要重复**）

| 尝试 | 结果 |
|---|---|
| `packet_buffer` = `hello/gate/frame2` 的各种切片拼接（1–4 段，5860 种） | `dec_key` 不匹配 |
| 再叠加 `ticket.py` 重建的 128B 票据 / 其 `[97:121]` 24B | 不匹配 |
| `SESSION_KEY` = 票据 24B / `range(24)` / `8ecd…` / 全零 / hello+gate+frame2 尾 24B / `sha1` 派生 | 全不匹配 |
| 读 `0x111F440`（codol-node 的地址） | **全零**（`runs/20261021-sk`） |
| 内存搜 `8ecd5642…` 这 24 字节 | **不存在**（`session_key_search` 空） |

### 4.3 推断

`bdproto319` 注释说 `packet_buffer = 客户端 hello尾 + 我们的 ack + client_auth`。既然纯 LSG 帧拼不出来，`client_auth` 很可能指 **Auth 阶段的产物**（`server_ticket` / `client_ticket` / `iv_seed` / `ciphertext` 的某种组合，可能带长度前缀）。

**→ 需要 `lsg.js`（`bdproto319` 的移植源）或 `bdsvc319` 的调用方，看 `packetBuffer` 的确切构造。**

---

## 5. `ui_state` 语义（**重要修正，别再误判**）

`0x7F25B0` 跳表（`[0x84ABA50]` → 结果）：

```
0     -> 4   (fail)
1..4  -> 1   (中间态；随后 0x7EF1DE 判定失败 -> 0x7EF210 push 0xDE0640 -> UI 弹 [100] 无法连接大厅服务)
5     -> 3   (success)
```

**`DW_LOBBY_CONNECTED`（ui=4）是失败分支**，不是“已连接”。UI 上表现为 `[100]无法连接大厅服务!`。

### `ui=5` 的条件（`0xBA0780`）

```asm
cmp dword [ecx+0x644], 0     ; crypt
mov eax, [ecx+0xC8]          ; lstate (CS)
je  crypt_zero
  cmp eax,2 -> return 2 ;  cmp eax,1 -> return 2 ;  否则 return eax
crypt_zero:
  cmp eax,2 ; jne -> return eax
  cmp dword [ecx+0x5E8],3    ; stage
  -> stage==3 返回 2，否则 1
```

- **A**：`crypt != 0` 且 `lstate ∈ {1,2}`
- **B**：`crypt == 0` 且 `lstate == 2` 且 `stage == 3`

`0xB7A670` 再映射：`ready([netobj+0x4F8])!=0` 时直接返回 `0xBA0780` 的值；否则 `eax==2` 返回 1。

**实测**：`crypt` 恒 0（A 路不通）；B 路在 `stage=3` 的约 5 秒窗口内成立，但大厅泵没赶上，随后被打成 4。

**强制写内存无效**：`runs/set_crypt.py` 在 `ui==4` 时写 `crypt=1`、`ready=1`，客户端**下一瞬间**就把 `crypt` 改回 0、`lstate` 置 4（`0xBA3420` 内同时干这两件事）——有一致性检测并回滚。

---

## 6. crypt 为什么建立不了

`0xBA3590`（加密通道建立）：

```asm
0xBA35B0 call 0xB783C0        ; 从 0x87 帧读 1 字节
0xBA35BC cmp byte [ebp+0x13], 1   ; 必须 == 1
0xBA35CA call 0xBA3420        ; 否则报废
0xBA35D7 cmp [esi+0x644], 0
0xBA35E2 call 0xBA3010        ; 初始化
0xBA35EB mov [esi+0x644], 1
```

上游 `0xBA3AE6`：只有 `type == 0x87` 且 `[conn+0x640] >= 0xDC(220)` 才进 `0xBA3590`。

`0xBA3010` 内部顺序：
```
0xB74220  分配 44B
0xB9BEB0  构造对象
0xB76620  写 tag 3 + 1 字节（失败则返回 false）
0xB75DE0  读 tag 1、0x88(136) 字节
0xBA2A60  收帧处理（crypt==0 分支要求 lstate==2 && stage==3）
```

**已试**：0x87 帧的 payload 用 `01+00×15`、`01+00×136`、`01+88+00×136`；延迟 2/7 秒；等 `stage==3` 再发（注意：**必须在收到 0x85 之后**才能等到 stage 3，提前等会死锁）。结果要么 `DW_LOBBY_ERROR`，要么 `crypt` 仍 0。

---

## 7. 关键地址表（运行时 VA，ImageBase `0x400000`）

### 全局
| 地址 | 含义 |
|---|---|
| `0x8269774` | netobj |
| `0x84ABA50` | ui_state |
| `0x84ABA54` | 上一个 ui_state |
| `0x84ABA7C` | business queue |
| `0x84ABA70/74` | lsg obj a/b |
| `0x849BA3D` | error flag |
| `0x3306D60` | D 条件对象（零补丁文档：`*[0x3306D60]+0xC` 非零才算 CS=4 通过） |

### netobj / conn
| 偏移 | 含义 |
|---|---|
| `netobj+0x4F4` | conn 指针 |
| `netobj+0x4F8` | ready（tag 0x0A 成功后 = 1） |
| `conn+0xC8` | lstate（CS） |
| `conn+0x5E8` | stage（0/1/2/3） |
| `conn+0x5EC` | **不是** rx 序号（实测为 0 或 "loba"/"v10000_4" 文本） |
| `conn+0x5FC` | challenge（0x83 的 token，8B） |
| `conn+0x604` | AES key 对象指针 → `[ptr+0x9C]` = `dec_key` |
| `conn+0x608` | **证书缓冲**（"…prise Services GmbH"/"DigiCert Inc"/X.509），不是密钥 |
| `conn+0x640` | version（必须 ≥ 220） |
| `conn+0x644` | crypt（0/1/3） |

### 函数
| 地址 | 作用 |
|---|---|
| `0x7F25B0` | ui_state 映射（跳表 `0x7F25DC`） |
| `0x7EF1C8` | 大厅轮询；`0x7EF1DE cmp esi,3` 成功；`0x7EF210` 失败（`push 0xDE0640` = `[100]` 文案） |
| `0x803780` | 大厅泵；`0x803699` 处 `je`（`74 1f`）可改成 `jmp`（`eb 1f`）让它无条件成功 |
| `0xBA0780` | 连接状态查询（ui=5 判定） |
| `0xBA2A60` | 收帧处理；`crypt==0` 时要求 `lstate==2 && stage==3` |
| `0xBA3010` | 密钥/通道初始化 |
| `0xBA3420` | 报废：`lstate=4` + `crypt=0` |
| `0xBA3AE0` | 帧 type 分派（0x87 才建 crypt） |
| `0xBA3590` | 加密通道建立 |
| `0xBA4430` | 控制帧处理；**`lstate==4` 直接 `ret`，不解析任何帧** |
| `0xB783C0` | 缓冲区边界读取（`buf,len,offset,out,n`，要求 `offset+n<=len`） |
| `0xB73FE0` | memcmp |
| `0xB76620` | 写 tag 3 + 1 字节 |

---

## 8. 阴性结果清单（**避免重复踩坑**）

| 尝试 | 结果 |
|---|---|
| 0x83 token 换成 0x82 尾 8B / 反序 / `conn+0x5F4` | 客户端不发 0x85 或报错 |
| 0x83 长度 10 / 12 / 16 | 16B 才稳定让客户端发 0x85 |
| 0x85 回帧：空 / 回显 96B / task_reply / 80-230 playerdata | 全部 `peer_closed` 或 `pt []` |
| marker `0x01` vs `0xAB` | 都失败（但 `bdproto319` 证明**正确是 `AB`**，且必须带真 HMAC） |
| IV 随机 vs 固定 `16..31` | 1649370 用帧内 IV；固定 IV 立即断开 |
| 心跳 2s/5s/20s/30s（加密帧 / 4 零字节） | 2 帧后 `ConnectionAbortedError`；4 零也无效 |
| 0x83 后完全静默 | 6 秒后自行断开，且不发业务请求 |
| 0x87 帧（16B / 137B / `01+88+136B` payload） | `DW_LOBBY_ERROR`，crypt 仍 0 |
| 强制写 `crypt`/`ready` | 被客户端回滚 |
| `CHAL` 派生：`A20=SHA1(transcript)` + `HMAC-SHA1` + `HKDF`，144000 组合 | 未命中 `reply[-8:]`（`runs/derive_keys.py`） |
| 大厅泵补丁 `0x803699 je→jmp`（单独 / +Auth） | 导致 `[100]` 或直接退出（`runs/20261020-pump2/pump3`、`20261021-p1/p2`） |

> **注意**：`patches319.py` 的补丁地址在 1649370 上**字节不匹配**（例如 `0x803699` 实测是 `dc fe`，参考期望 `74 1f`）——**不要直接套用**，需按本 build 重新定位。

---

## 9. 外部参考（都在仓库内）

| 路径 | 内容 | 价值 |
|---|---|---|
| `他人文件参考/bdproto319.py` | **协议实现**（密钥派生 + 帧构造） | **最高**——算法已确定，只差 `packet_buffer` |
| `他人文件参考/bdsvc319.py` | 业务应答服务（`import bdproto319`） | 服务表 + `make_service_reply` 形状；**tag 0x0A 在 `svc21/task5` 应答里** |
| `他人文件参考/PROGRESS.md` | 另一套跑通的 1649370 服务端 | `DW=4→5` 可达；svc28 必须静默；ZEROFRAME 30s；业务帧明文 |
| `他人文件参考/零补丁分析-20261019.7z` | 1604220 的 P2/P3 判定链 | CS=4 需 D 条件；`task_reply` 格式 |
| `codol-ember/工具-tools/lobby-reproduction1604220/` | 1604220 完整服务端 | 握手、密钥派生公式、`evt4`、keepalive（**`wire.py` 被省略**） |
| `codol-ember/工具-tools/launch319-reference/reference/launch/` | 319 官方参考 | `patches319.py`（补丁集，地址需重新定位）、`orch319.py`（编排：`--mark-onboarded`/`--set-rank`/`--unlock-all`/code-cave `set_stat_int`）、`lobby_service.py`（抓包用） |

### `bdsvc319.py` 里 `svc21/task5` 的 tag 0x0A（**正确位置**）

```python
# 3333 §46.3 RegisterCodoID 应答格式
w.raw(bytes([0x0A]))
w.raw(struct.pack("<IH", ipnum, port) + b"\x00\x00")   # IP + PORT
w.raw(bytes([0x08])); w.uint32(0)                      # tag08 + 结果码 0
w.raw(bytes([0x03, 0x00]))
```

**不要再把 `0A 08 IP PORT` 塞进 0x85 明文**——位置错了。

---

## 10. 给 Codex 的路线（按性价比）

1. **拿 `lsg.js`**（或 `bdsvc319` 的调用方）。确认 `packetBuffer` 与 `SESSION_KEY` 的真实来源。**这一步做完，剩下全是已知量。**
2. 若拿不到：尝试从**客户端侧**动态抓 `dec_key` 的**派生输入**——例如在 `0xBA3010` 里断点/读参数（需要调试器，属进程内操作）。
3. 拿到 `enc_key`/`resp_hmac_key` 后，按 `make_encrypted_reply` 发帧（`AB 85` + 真 HMAC），先回 0x85（登录应答），再按 `svc21/task5` 回 tag 0x0A。
4. 协议通了之后，用 `orch319.py` 的 code-cave 技巧处理 onboarding/rank/unlock，让 UI 正常显示。

---

## 11. 复验命令

```powershell
cd E:\GAME\COD\codol-airedux\319

# 一键会话（Auth + LSG + Auth补丁 + 采样 100 次）
pwsh -NoProfile -File runs\run_hb88.ps1 -RunId 20261021-test

# 看状态（ui / lstate / crypt / stage）
python -c "import json;d=json.load(open(r'runs\20261021-test\patch.json',encoding='utf-8'));[print(e['utc'],(e.get('lobby') or {}).get('ui_state'),(e.get('lobby') or {}).get('conn_lstate'),(e.get('lobby') or {}).get('conn_crypt'),(e.get('lobby') or {}).get('conn_stage')) for e in d['events'] if e.get('event')=='sample']"

# 看 LSG 帧
Get-Content runs\20261021-test\lsg.jsonl

# 验证密钥派生（自检目标 8e6b3363…）
python runs\verify_keys.py runs\20261020-base
python runs\find_packet_buffer.py runs\20261020-base
```

---

## 12. 文件地图（服务端与工具）

| 文件 | 作用 |
|---|---|
| `server319/lsg.py` | LSG 服务：握手、0x83、0x85 解密/回帧、探针。环境开关：`LSG_INNER`/`LSG_BIZ`/`LSG_KEYOFF`/`LSG_PLAIN85`/`LSG_SILENT_AFTER83`/`LSG_F87_WAIT` |
| `server319/lsg_client.py` | 跨进程读取：`find_service_conns`、`read_region`、`search_bytes`、`find_client_pids` |
| `server319/auth.py` | Auth 端点 + 证据写入（字段 allowlist） |
| `server319/ticket.py` | 票据（Tiger） |
| `tools/patch_runtime.py` | 通用 RVA 补丁 + 采样（写 `lobby` 字段） |
| `tools/patch_auth_bypass.py` | 旧采样工具（含 `conn_ver`/`conn_crypt`/`conn_stage`） |
| `runs/verify_keys.py` | 用 `bdproto319` 验证 `packet_buffer` |
| `runs/find_packet_buffer.py` | 穷举 `packet_buffer` 组合 |
| `runs/set_crypt.py` | 强制写 `crypt`/`ready`（已证明会被回滚） |
| `runs/dump_ba3000.py` | dump 代码区（`runs/20261020-dump5/` 最新） |

---

## 13. 证据索引

| Run | 结果 |
|---|---|
| `20261020-session47/48` | 单发 type-4 帧 → `ui=4`（后被证明是 fail） |
| `20261020-gate220` | **gate 220 → stage=3 首次出现** |
| `20261020-ver` | `conn_ver=220` 确认 |
| `20261020-p3b` | 发 80/230 playerdata → `pt []` |
| `20261020-silent4` | 0x83 后静默 → 6s 自行断开 |
| `20261020-plain85` | 明文 0x85 → `peer_closed` |
| `20261020-uiforce` | 强制写 crypt/ready 被回滚 |
| `20261021-sk` | `0x111F440` 全零、`8ecd…` 不在内存 |
| `20261021-f87e/f87g/f87h` | 0x87 各时序（含「先收 0x85 再等 stage 3」） |
| `20261021-p1/p2` | 大厅泵补丁 → `[100]`/退出；且 `patches319.py` 地址在本 build 不匹配 |

## 13.5 历史更正（1649370 时期的关键反证，保留备查）

> **transcript 审计纠正（2026-10-20）**：早期「唯一缺口是 `packet_buffer` 与固定 `SESSION_KEY`」的判断**已被反证**。
> 用 `runs/20261020-base`、`gate220`、`session33` 的 hello/gate/0x82 帧，按
> `hello[8:] + gate[0:4] + b"\xAB\x81" + gate[6:] + client_auth[:-8]` 构造 transcript，并用本项目 Auth 票据里
> 实际写入的 24B 合成会话密钥，三个 run 的客户端 challenge、0x83 token、0x85 帧尾 HMAC 与 AES 明文形状全部吻合；
> 第三方 `bdproto319.py` 的固定 `8ecd…` 密钥与「参数反序」在这些 run 上均不吻合。
> 重跑：`python tools/verify_lsg_capture.py runs/20261020-base`；
> 结论见 `evidence/experiments/20261020-lsg-transcript-audit.json`。
> 该审计只证明 C→S 的本地合成会话派生，不证明 S→C 应答被客户端消费——后者已在 1604220 上由 `lsg_derived.py` 推进到 `[111]` 阶段。

> **其它纠错**：派生的 C→S AES 密钥等于 `[conn+0x604]+0x9C`，S→C 等于 `[conn+0x608]+0x9C`（早期「0x608 是证书」已被反证）；
> `ui=4` 是失败分支，只有 `ui=5` 才是成功；`DW_LOBBY_CONNECTED` 只是状态名。

---

**最后更新**：2026-10-22，DeepSeek → Codex。
**目标状态**：已暂停（`update_goal` paused）。

---

## 14. Build 1604220 实况（2026-10-22，最新）

### 14.1 身份与副本

| 项 | 值 |
|---|---|
| 原始包 | `E:\GAME\COD\3.19.26.13`（只读） |
| 工作副本 | `runtime\client-1604220`（2173 文件 / 25.86 GB） |
| EXE | `3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f`（7,842,456 B） |
| Base DLL | `7bbc5fb07ebca9b4671ec0e9a953bbd4e1baaca6a9ca29888531c3213e400f64`（61,137,048 B） |
| IIPS | 与 1649370 **字节相同**（`72ddb9d1…` / `b507b47a…`） |

EXE/Base 哈希与 `codol-ember/工具-tools/lobby-reproduction1604220/docs/SUCCESS-SUMMARY.md` 记录完全一致。

### 14.2 客户端配置（社区 `workflow.prepare` 的格式，**三行纯文本**）

```
runtime\client-1604220\dwauth.ini     127.0.0.1 4174 / 127.0.0.1 4175 / 03EA
runtime\client-1604220\stun.ini       127.0.0.1 ×3
runtime\client-1604220\iips.ini       enable_iips=1 + iips_url="http://127.0.0.1/"
runtime\client-1604220\cacert.pem     原库 + 我们的自签证书
```

写错格式（用 ini 节 `[Auth] host1=…`）客户端**完全不读**，会继续连腾讯（`223.111.197.45:443`）然后报 `DW_DNS_ERROR`。改成上面三行后，观测到 `127.0.0.1:4175 SynSent` → `DW_DNS_COMPLETE`。

### 14.3 TLS：必须自签（叶子 = CA）—— **本次最关键的发现**

1604220 的 `codoMP_client_shipRetailBase.dll` 内含 OpenSSL，**强制校验证书**（1649370 不校验，所以旧版不做任何事也能过 Auth）。用「CA 签发叶子」的链式证书会得到：

```
tls_handshake_failed  SSLError: [SSL: TLSV1_ALERT_UNKNOWN_CA]
```

**正确做法**（社区 `workflow.tls_pair()` 生成的就是这种）：

```powershell
openssl req -x509 -newkey rsa:2048 \
  -keyout runs\20261022-tls-selfsigned\auth.key \
  -out    runs\20261022-tls-selfsigned\auth.crt \
  -days 3650 -nodes -subj "/CN=127.0.0.1/O=offline-research" \
  -addext "subjectAltName=IP:127.0.0.1,DNS:localhost"
```

并把这份证书写入：

- `runtime\client-1604220\cacert.pem`（追加）
- `C:\Program Files (x86)\Common Files\SSL\cert.pem`（OpenSSL 默认信任库，Base DLL 里的路径字符串）

结果：`auth_request len=188` → `auth_response 200`。

> 已安装但**单独不够**的尝试（都失败）：`certutil -addstore -user Root ca.crt`、`certutil -addstore Root ca.crt`、`SSL_CERT_FILE` 环境变量、`CURL_CA_BUNDLE` 环境变量。

### 14.4 Auth 响应：只回 7 个字段

`codol-ember/.../authchan.py::auth_answer` 的形状：

```python
{
  "auth_task": str(int(request["auth_task"]) + 1),   # 字符串，+1
  "code": "700",                                     # 字符串！
  "iv_seed": str(request.get("iv_seed", "0")),
  "client_ticket": base64(build_ticket(uid)),
  "server_ticket": base64(build_ticket(uid)),
  "identity": request.get("identity", "local"),
  "lsg_server_ticket": base64(build_ticket(uid)),
  "lsg_server_ticket_size": str(128),
}
```

`auth_task == 32` 时额外回 `extra_data`（codoid 握手）。

**必须删掉**的字段（客户端严格解析，多了就 `DW_ACCOUNT_ERROR`）：
`result`、`success`、`member_position`、`estimated_wait_time`、`next_poll_after`、`time_to_live`、`licenses`、`license_id`、`cd_key`、`ciphertext`、`extra_data`(非 32)、`user_id`、`title_id`。

`server_ticket` 必须是**真实 Tiger 票据**，全零票据同样导致 `DW_ACCOUNT_ERROR`。

### 14.5 LSG：密钥从 transcript 派生（不读客户端内存）

`server319/lsg_derived.py` 已实现：

```
session_derived   challenge_verified; client-memory-read=false
token_reply       0x83
client_frame_verified  counter=1 inner=0x86 payload_len=83
task_request      service=71 task=4
```

transcript 构造（经 `tools/verify_lsg_capture.py` 在多个 1649370 run 上验证）：

```
hello[8:] + gate[0:4] + b"\xAB\x81" + gate[6:] + client_auth[:-8]
```

密钥来源：本项目 Auth 票据里实际写入的 24B 合成会话密钥（`server319/ticket.py::SESSION_KEY` = `bytes(range(24))`）。
第三方 `bdproto319.py` 的固定 `8ecd…` 与「参数反序」在这些 run 上**不成立**。

### 14.6 当前状态（2026-10-22 21:28，`runs/20261022-1604220-71empty/`）

采样（90 次，进程存活）：

```
dw=0, ui=0
dw=2, ui=6           DW_DNS_COMPLETE
dw=5, ui=9, ready=1, lstate=2   DWLOGON_REGISTERCODOID_COMPLETE   ← dw=5 达成
```

UI 报错从 `[100]无法连接大厅服务` 变为 `[111]与大厅服务失去连接`。

`lsg.jsonl`（该轮带 `--observed71-empty`）：

```
plaintext_frame(28) → gate_reply → plaintext_frame2(153)
session_derived → token_reply
client_frame_verified counter=1 inner=0x86 payload_len=83
task_request service=71 task=4
candidate_task_reply svc71/task4
idle_control ×2
```

对比**不带**该开关的 `runs/20261022-1604220-min/`：

```
task_request svc71/task9 → unhandled_task → terminal_task_reply error=14
task_request svc71/task3 → unhandled_task → terminal_task_reply error=14
```

即：`--observed71-empty` 让 3/7/9 走空成功，客户端不再收到 `error=14`，但 `[111]` 仍在。

### 14.7 下一步（按优先级）

1. **`svc71/task9` 回 82B bdMatchMaking server entry**（不要空成功）。参考 `他人文件参考/bdsvc319.py::make_server_entry`：

   ```python
   u32 ip_le("127.0.0.1") + u16 port + u16 0
   + 5 × u32 0 + u32 0x9D + 5 × u32 0
   + u32 1 + u32 1 + string("TestServer") + u32 0
   + u32 ip + u16 port + u16 0 + u32 0
   ```

   端口用 `8466`（`FINDSESS_PORT`）。

2. **`svc71/task3`**：`bdsvc319` 未单列，先按空成功。

3. **观察 `[111]` 是否消失**；若消失，检查 `dw` 是否停在 5、UI 是否可交互。

4. **后续任务链**：按 `bdsvc319.py` 的 service 表补 `svc10`（文件）、`svc80`（playerdata）、`svc11`（清单）、`svc21`（lobby 列表，含 tag `0x0A`）、`svc28`（**必须保持静默**）。

5. **保活**：`ZEROFRAME`（裸 4 字节 0）每 30 秒；`idle_control` 已在处理。

### 14.8 复验命令

```powershell
cd E:\GAME\COD\codol-airedux\319
$py = "python"
$a = Start-Process $py -ArgumentList "-m","server319","--client-dir","runtime\client-1604220","--auth",
  "--cert","runs\20261022-tls-selfsigned\auth.crt","--key","runs\20261022-tls-selfsigned\auth.key",
  "--port","4175","--seconds","110","--evidence","runs\REPLACE\auth.jsonl" -PassThru -WindowStyle Hidden
$l = Start-Process $py -ArgumentList "-m","server319.lsg",
  "--cert","runs\20261022-tls-selfsigned\auth.crt","--key","runs\20261022-tls-selfsigned\auth.key",
  "--port","4174","--log","runs\REPLACE\lsg.jsonl","--seconds","110" -PassThru -WindowStyle Hidden
Start-Sleep 4
python tools\patch_runtime.py --client-dir runtime\client-1604220 --evidence runs\REPLACE\patch.json `
  --patch 0x403699:EB1F:741F --patch 0x403659:909090909090:893540BA4A08 `
  --patch 0x3F2A0A:B8BC0200009090:3DBC0200007407 --patch 0x3EE9DC:9090909090:E82F2F0100 `
  --patch 0x37C860:C39090909090:558BEC83E4F8 --patch 0x20C649:B000:B001 `
  --wait 12 --observe 90
```

> `runs/run_1604220.ps1` 存在但 **`Start-Job` 参数传递有 bug**（Auth 起不来），现阶段请用上面的内联命令。

### 14.9 本轮代码改动清单

| 文件 | 改动 |
|---|---|
| `server319/manifest.py` | 新增 `BUILDS`（1649370 / 1604220）+ `detect_build()`，`verify_client` 按 EXE hash 自动识别 |
| `server319/__main__.py` | staged 路径由 `detect_build` 推导；`stage-receipt.json` 改为可选 |
| `server319/auth.py` | 改为 7 字段最小响应；`code` 为字符串；`auth_task` = 请求+1；真实 Tiger 票据；TLS 错误记录完整原因 |
| `tools/patch_runtime.py` | 接受任一已记录 build；sample 里接入 `lobby` 采样 |
| `tools/patch_auth_bypass.py` | `sample_lobby` 新增 `dw`（`0x84ABA40`） |
| `runs/run_1604220.ps1` | 1604220 专用会话脚本（**有 job 传参 bug，暂用内联命令**） |
| `runs/probe_patch_sites.py` | 核对 `patches319.py` 六个锚点字节（1604220 上**全部 MATCH**） |
| `runs/find_a20.py` | `a20_of` 候选穷举（未命中，已被 §15 行的 transcript 审计取代） |

### 14.10 已知坑（不要再踩）

1. `dwauth.ini` 用 ini 节格式 → 客户端不读，连腾讯。
2. 用 CA 签发叶子的证书 → `UNKNOWN_CA`；**必须自签**。
3. Auth 响应多字段 → `DW_ACCOUNT_ERROR`；**只回 7 个**。
4. `server_ticket` 全零 → `DW_ACCOUNT_ERROR`。
5. `patches319.py` 的地址是 **1604220** 的，在 1649370 上会 `DIFF`（当年失败的原因）。
6. `patch_runtime.py` 原本硬编码 `runtime/client-1649370`，现已按 build 识别。
7. `run_1604220.ps1` 的 `Start-Job` 传参有 bug，Auth 不会监听；用内联 `Start-Process`。
8. 客户端截图需**强制置前**才有意义（`runs/run_lobby_capture.ps1` 有现成逻辑）。

---

## 15. Build 1604220：111 已消除，大厅背景已出（2026-10-22 23:5x）

### 15.1 这一步做了什么

`[100]` 与 `[111]` 均已消除，客户端渲染出大厅背景。三层修复缺一不可：

1. **UDP 3074 回显**（`server319/lobby_udp.py`）——握手走 UDP，此前无人应答。
2. **lobby pump 9 处补丁**——绕握手失败跳转 + 把「写 -2」改成写 1，
   注意 `0xBADC27` 而非 `0xBADC26`（`mov esi,-2` 的立即数偏移）。
3. **强推补丁**（`tools/ui_activate.py`）——`0x7F25F0` 跳板调用 `0x5EBE10`（cppActivate），
   dw=5 调一次、45 秒后 `--reset` 重触发。

完整 15 处补丁列表见 `PROJECT_STATUS.md` §12.11。

### 15.2 当前状态

```
dw=5, ui=9, lstate=2, DWLOGON_REGISTERCODOID_COMPLETE
```

截图：大厅背景（蓝雾 + 半透明几何层 + HUD 边框），**无 111 弹窗**。
但**UI 层（按钮/文字）为空**。

### 15.3 缺什么

`lsg.jsonl` 显示：`svc71/task4` → 应答 → 客户端不再请求，只有保活帧。
即前端框架已激活，但没有数据可渲染。

下一步：主动推送 player/lobby 数据（参考 `bdsvc319.py` 的 `svc80` 形状），
必要时补 `svc10` 文件清单。

### 15.4 复验命令

```powershell
cd E:\GAME\COD\codol-airedux\319

# 1) 起三个本机服务
python -m server319.lobby_udp 3074 200 runs\X\lobby_udp.jsonl
python -m server319 --client-dir runtime\client-1604220 --auth \
  --cert runs\20261022-tls-selfsigned\auth.crt \
  --key  runs\20261022-tls-selfsigned\auth.key \
  --port 4175 --seconds 195 --evidence runs\X\auth.jsonl
python -m server319.lsg --cert runs\20261022-tls-selfsigned\auth.crt \
  --key runs\20261022-tls-selfsigned\auth.key \
  --port 4174 --log runs\X\lsg.jsonl --seconds 195

# 2) 打 15 处补丁并启动客户端
python tools\patch_runtime.py --client-dir runtime\client-1604220 \
  --evidence runs\X\patch.json --wait 12 --observe 175 \
  --patch 0x403699:EB1F:741F --patch 0x403659:909090909090:893540BA4A08 \
  --patch 0x3F2A0A:B8BC0200009090:3DBC0200007407 \
  --patch 0x3EE9DC:9090909090:E82F2F0100 \
  --patch 0x37C860:C39090909090:558BEC83E4F8 --patch 0x20C649:B000:B001 \
  --patch 0x7BA295:9090:7E1A --patch 0x7BA29D:9090:7512 \
  --patch 0x7BA276:9090:7439 --patch 0x7BAD4D:9090:7572 \
  --patch 0x7ADC27:01000000:FEFFFFFF --patch 0x7ADDE0:01000000:FEFFFFFF \
  --patch 0x7AE754:01000000:FEFFFFFF --patch 0x7AE76C:01000000:FEFFFFFF \
  --patch 0x7AE7B0:01000000:FEFFFFFF

# 3) dw=5 后装强推跳板（另开窗口）
python tools\ui_activate.py --wait-dw5 60
# 45 秒后重触发
python tools\ui_activate.py --reset

# 4) 置前截图
pwsh -NoProfile -File tools\capture_screen.ps1 -OutFile runs\X\shot.png -DelayMs 3000
```

### 15.5 新增文件

| 文件 | 作用 |
|---|---|
| `server319/lobby_udp.py` | UDP+TCP 3074 回显端点 |
| `tools/ui_activate.py` | cppActivate 强推跳板 |
| `tools/find_calls.py` | 扫描指定 VA 的全部 call 调用点 |
| `tools/watch_patch_sites.py` | 监视补丁点是否被还原 |
| `tools/probe_pump_sites.py` | 读取 pump 补丁九处字节 |
| `tools/dump_state_mapper.py` | 转储 ui_state 映射与全局量 |

### 15.12 FE 梯（前端状态机）的卡点（2026-10-22 23:1x）

`他人文件参考/零补丁还债台账.md` 给出了 FE 梯 `0x5EBFD0` 的完整解码：

```
入口: call 0x5EE7C0(登录态查询)          ; eax!=1 -> 整梯 return
       G1=[0x82E1340], CS=[0x84ABA50]
 G1==0: call 0x6BBF30(firstlogin)         ; al==0 -> 留 0
            al==1 -> 推 cppFirstLogin 建 UI -> G1=1
 G1==1: cmp CS,9 ; !=9 -> 留 1
            call 0x730C50(FE-loaded) ; al==0 -> 留 1        ← 当前卡这里
            cmp [[0x3306D60]]+0xC,0 ; !=0 -> 跳过
            cmp byte [0x82E1346],0 ; !=0 -> 排队
            cmp [0x84ABAFC],0 ; ==0 -> 等待 ; 会话 ready 调用==1
            推 cppInLoginQueue 建 UI -> G1=2
 G1==2: call 0x5EBE10(cppActivate) -> gate=1 ; [G1]=3
```

新增 `tools/probe_fe_ladder.py` 采样全部门控量，实测稳定值：

```
G1=0  gate=0  queue=0  CS=9  dw=5  session_ready=0  D+0xC=0
FE_obj 由 0xFFFFFFFF 变为 695689256（0x2976E028）后稳定
```

**关键发现：`G1` 一直是 0。** 即 `0x6BBF30`（firstlogin）在离线会话里从不返回 1，
梯子第一步就停住，后面的 `cppActivate` 自然永远不会被它自己调用。

新增 `tools/force_fe_ladder.py` 把 `G1` 写成 1（仅进程内存）。实测：

```
before  G1=0 gate=0 session_ready=0 CS=9
now     G1=1 gate=0 session_ready=1 CS=9
after   G1=1 gate=0 session_ready=1 CS=9
```

**`G1` 停在 1，`gate` 仍为 0** —— 说明 `G1==1` 分支里 `0x730C50`（FE-loaded）
返回 0，梯子继续等待前端资源加载完成。

### 15.13 下一步

1. 反查 `0x730C50`（FE-loaded）的判定条件——它很可能检查某个 Scaleform 影片/资源
   是否就绪，若依赖客户端资源文件则需要让它以为已加载。
2. 或直接把 `G1` 写成 2（跳过 FE-loaded），观察 `cppActivate` 是否被执行、gate 是否置 1。
3. 注意 `tools/ui_activate.py` 的跳板是「绕过梯子直接调 cppActivate」，与此处的
   「让梯子自己走完」是两条不同路径，可分别验证。

### 15.14 ★★★ 大厅完整渲染（M3 核心达成，2026-10-22 23:4x）

把 FE 梯的 `G1` 从 0 直接写成 **2**（跳过 firstlogin 与 FE-loaded 两道自检），
梯子随后**自己**走完了最后一步：

```
before  G1=0 gate=0 session_ready=0 CS=9
now     G1=2 gate=0 session_ready=1 CS=9
now     G1=3 gate=1 session_ready=1 CS=9    ← cppActivate 已被梯子自己调用
after   G1=3 gate=1 session_ready=1 CS=9
```

`G1=3` / `gate=1` 说明 `0x5EBE10`（cppActivate）执行成功，前端正式激活。

截图 `runs/20261022-1604220-g2/screens/d1.png` 显示**完整大厅 UI**：

- 左侧菜单：`公告`、`福利`、`任务`
- 主区：`多人游戏 (PVP)`、`特种行动`、`闯关模式 (PvE)`、`自定义游戏`
- 右上：玩家名 `Administrator`、军衔 `新兵`
- 中间：`TextField` 模态弹窗（带「关闭」按钮）——与社区记录一致
- 底部：`大门解锁特追加门...`

用户亦确认「成功进入大厅」并录屏。

### 15.15 至此的完整链路

| 环节 | 手段 | 状态 |
|---|---|---|
| TCLS 门槛 | 副本 + `-q` | ✅ |
| IIPS 初始化 | 高权限令牌 | ✅ |
| Auth | 自签 TLS + 7 字段响应 | ✅ |
| LSG 握手 | transcript 派生密钥 | ✅ |
| UDP 3074 | `lobby_udp.py` 回显 | ✅ |
| lobby pump | 9 处补丁 | ✅ |
| dw=5 | `lobby_pump_ok` 等 6 处补丁 | ✅ |
| 前端激活 | `G1=2` → 梯子自调 cppActivate | ✅ `gate=1` |
| **大厅 UI** | — | ✅ **已渲染** |

### 15.16 已知遗留

1. `TextField` 模态弹窗仍在，需点击「关闭」（可脚本化或用 `tools/capture_screen.ps1` 前的点击器）。
2. 大厅数据（公告/任务/商城）为空，需要 `svc80`/`svc255` 等业务应答填充。
3. `svc71/task9`、`task3` 仍未稳定到达。

### 15.17 复验要点

`G1` 推进必须**在 dw=5 之后**、且顺序为 **0 → 2**（直接写 2）；
写 1 只会停在 `G1==1` 等 FE-loaded。工具：`python tools\force_fe_ladder.py --to 2 --set-ready`。
