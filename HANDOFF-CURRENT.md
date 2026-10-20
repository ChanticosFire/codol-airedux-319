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

### 15.6 ★★★ M3 验收达成（2026-10-22，用户录屏截图归档）

用户提供的分步截图已归档到 `evidence/20261022-1604220-lobby/`，六张覆盖完整流程：

| 文件 | 画面 |
|---|---|
| `1-character-select.png` | 选择角色（五名角色，含「选择你喜欢的角色」标题） |
| `2-character-detail.png` | 角色详情（威 / 重装兵 / 28 岁 / 82 公斤） |
| `3-welcome-tutorial.png` | 欢迎页（高手 / 新手 训练分支） |
| `4-keyboard-layout.png` | 选择键盘设置（使命召唤键位 / 其他射击游戏键位） |
| `5-lobby-textfield.png` | 大厅 + TextField 模态弹窗（未关闭） |
| `6-lobby-final.png` | **完整大厅**（关闭弹窗后） |

### M3 五项判据逐条对照

| 判据 | 证据 | 状态 |
|---|---|---|
| 1. 通过 TCLS 启动门槛 | 无 `WIN_NO_TCLS`；`DW_DNS_COMPLETE` 出现 | ✅ |
| 2. 走完 IIPS 初始化 | 无 `初始化IIPS错误`；两个 `IIPSHostApp` 进程存活 | ✅ |
| 3. Auth/LSG 请求真实到达本机 | `auth.jsonl` 有 `auth_request(188B)`→`auth_response(200)`；`lsg.jsonl` 有完整握手与 `task_request svc71/task4` | ✅ |
| 4. 可交互的原生前台/大厅 | 六张截图；`6-lobby-final.png` 显示完整大厅 UI（左侧功能栏、四大模式、军火币商城、玩家信息、聊天频道栏） | ✅ |
| 5. 留下可复验证据 | `runs/20261022-*` 全过程记录 + `evidence/20261022-1604220-lobby/` 截图 + 本文档复验命令 | ✅ |

### 完整链路（最终版）

```
TCLS 门槛（副本 + -q）
  → IIPS 初始化（高权限令牌）
  → Auth 4175（自签 TLS + 七字段响应 + 真实 Tiger 票据）
  → LSG 4174（transcript 派生密钥，不读客户端内存）
  → UDP/TCP 3074 回显（lobby_udp.py）
  → 15 处运行期补丁（6 处常规 + 9 处 pump）
  → dw=5 / ui=9 / lstate=2
  → [0x82E1340] 写 2 → FE 梯自调 cppActivate → gate=1 / G1=3
  → 大厅完整渲染
```

### 遗留（不阻塞 M3）

1. `TextField` 弹窗需点「关闭」（`tools/click_at.py --window CODO --at 1405 621`）。
2. 「大厅群聊频道加入中...」需要聊天服务端支持。
3. 大厅业务数据（公告/任务/商城列表）为空，需 `svc80`/`svc255` 应答填充。
4. `svc71/task9`、`task3` 到达不稳定，属客户端竞态。

### 15.7 社区仓库遍历结果（2026-10-23）

按要求 `git fetch --all` 后确认仓库已是最新，无新提交：

```
origin  https://gitea.codolai.win:2096/ember-forge/codol-ember.git
HEAD    28368dd Merge pull request 'docs: curate 2697 reference and 1604220 adoption guidance' (#7)
behind   0
```

#### 结论一：社区自己也没有做到房间与对局

仓库内多处明确写着未实现/未验收：

| 出处 | 原文 |
|---|---|
| `工具-tools/lobby-reproduction1604220/docs/SUCCESS-SUMMARY.md` | 「聊天、**匹配、地图加载、实际对局、多人同步**及长期持续运行**未验收**」 |
| 同包 `README.md` | 「80/230 使用合法空库存/货币/entitlement 集合，**完整游戏业务与对局尚未实现或验收**」 |
| `工具-tools/launch319-reference/runtime-support/CURATION.md` | 「未新增人工大厅交互、**对局**或另一台机器验证」 |
| `技术规格-specs/1649370/ui/README.md` 系列 | 只描述 UI 路由与有界模型，「**不能由这些页面行为直接推定**」PVP 规则/匹配/对局 |

#### 结论二：目录存在但没有内容

`PVP资料-pvp/` 与 `PVE资料-pve/` 只有 README，正文是**主题规划**（`模式规则-modes/`、
`地图资料-maps/`、`房间与匹配-matchmaking/`、`对局流程-match-flow/`、`计分与结算-scoring/`），
每个版本目录下同样只有 README。**没有任何实际对局资料**。

#### 结论三：可借用的只有 UI 层线索

`技术规格-specs/1649370/ui/first-page-routes.json` 给出了房间相关的 UI 契约：

```
input_schema.room_source        = MatchService.getInstance().isInRoom
input_schema.room_object_fields = [mapID, playListID]
constants.RankedMatchStatus     = IDLE / IN_PROGRESS_IN_ROOM / BACK_FROM_GAME
BCEvent.EVT_GOTO_MATCH_SELECT   = evt_goto_match_select
continuations.setupNoRoomNavigation / setupLeaveRoomWithParty ...
```

这说明**客户端 UI 期望的输入**是「是否在房间 + mapID + playListID」，
但**没有**给出这些值从哪个 service/task 来——网络层仍需自己逆向。

#### 结论四：8 个真实任务的现状（172 个 run 汇总）

`tools/summarize_tasks.py` 扫全部历史 run 得到客户端请求过的全部任务：

| svc | task | 字节 | 出现 | 说明 |
|---|---|---|---|---|
| 71 | 4 | 3/83 | 32 | ListDedicatedServer，已有 candidate |
| 71 | 9 | 8 | 5 | FindSessions，已有 114B 条目 |
| 71 | 3 | 142/480 | 4 | 语义未知，最大 payload |
| 28 | 4 | 29 | 3 | PROGRESS.md 要求**静默** |
| 71 | 7 | 361 | 2 | 语义未知 |
| 21 | 5 | 62 | 1 | **FindLobbiesByPlaylist**（房间列表入口） |
| 11 | 13 | 3 | 1 | 内容/文件相关 |
| 102 | 5 | 12 | 1 | 未知 |

**`svc255` 与 `svc80` 从未被请求过**——所以 playerData 不是必经路径，M4.1 的重点
应从「补 svc255」转向「让 21/5 与 71/9 的应答被消费」。

#### 下一步

社区无现成方案，房间/对局需自研。优先级：

1. `svc21/task5` 已按 `bdsvc319` 默认变体（114B bdMatchMaking 条目）接上，需实测客户端是否
   在「多人竞技」页显示条目；
2. `svc71/task9` 同形状，需弄清它的触发条件；
3. 两者被消费后再谈 `svc71/task3`（142/480 字节，很可能是房间状态同步）。

### 15.8 ★★ firstlogin 修复：选人界面被跳过（2026-10-23 00:2x）

#### 根因（反汇编 `0x6BBF30`）

FE 梯在 `G1==0` 时调用 `0x6BBF30`，只有返回 1 才前进。该函数完整逻辑：

```asm
0x6BBF30  mov eax, 1
0x6BBF35  cmp [0x331C5C0], eax      ; 全局标志 == 1 ?
0x6BBF3B  jne 0x6BBF46
0x6BBF3D  cmp [0x84ABA50], 4        ; ui_state == 4 ?
0x6BBF44  je  0x6BBF54              ; 是 -> eax=1 返回
0x6BBF46  mov ecx, [0x3306D60]
0x6BBF4C  cmp dword [ecx+0xC], 0
0x6BBF50  jne 0x6BBF54              ; 非零 -> eax=1 返回
0x6BBF52  xor eax, eax              ; 否则 0
0x6BBF54  ret
```

离线环境下两个条件都不成立（`ui_state=9`、`[[0x3306D60]+0xC]=0`），函数恒返回 0，
所以 FE 梯永远停在 `G1=0`，选人界面就一直挂着——这解释了为什么之前写
`onboard_character_selected` 完全没有效果（那个统计项根本不参与这个判定）。

#### 修复

把 `[[0x3306D60]+0xC]` 写成 1 即可满足第二条路径，不必碰 `ui_state`：

```python
ptr = read_u32(h, 0x3306D60)
write_u32(h, ptr + 0xC, 1)
```

已集成到 `tools/auto_lobby.py::fix_firstlogin()`，在 `dw>=2` 时自动执行。

#### 验证

截图确认画面从「选择角色」变成训练官欢迎页：

> 欢迎来到使命召唤ONLINE！我是你的训练官。开始之前，请先取一个代号。

输入框 + 「继续」按钮，**选人界面确实被跳过了**。

#### 「取代号」仍需协议配合

用户实测：在该页填入代号后点「继续」无法进入下一步——**提交需要服务端确认**。
但目前抓到的所有 session 里，客户端在该页**没有发出任何新的 task**
（`lsg.jsonl` 始终只有 `svc71/task4` 加保活），因此提交路径尚未定位。

#### 本轮排除的假设

| 假设 | 结果 |
|---|---|
| 零帧保活干扰后续请求 | 关掉 `LSG_ZEROFRAME` 仍只有 task4 |
| pump 9 处补丁导致行为变化 | 只用 6 处补丁仍只有 task4 |
| 强推 `G1=2` 让客户端不再要数据 | 不强推也只有 task4 |
| 6 处补丁 + firstlogin 能复现 `71/9` | 仍只有 task4 |

结论：`20261022-1604220-min` 那次出现的 `svc71/task9` 是客户端侧竞态，
目前无法稳定复现。

#### 新增工具

| 工具 | 作用 |
|---|---|
| `tools/find_refs.py` | 搜索引用某数据地址的 imm32（`0xDC3EA0` → 4 处引用） |
| `tools/dump_code.py` | dump + capstone 反汇编运行时代码 |
| `tools/dump_fe_state.py` | 采样 `0x82E1300` 区域，对比推进前后变化 |
| `tools/summarize_tasks.py` | 汇总全部 run 的业务 task |
| `tools/type_text.py` | SendInput / WM_CHAR 两种输入方式，含窗口激活点击 |

#### 下一步

「取代号」需要协议应答才能过关，但请求形态尚未抓到。可选路径：

1. 在客户端提交代号**前后**对比 `lsg.jsonl`，确认是否真的没有网络请求；
2. 若确实无请求，则该步骤可能读取本地/内存中的账号对象，需要从 UI 层
   （`first-page-routes.json` 提到的 `MatchService`）反查它等待的条件；
3. 同时继续 `svc71/task4` 的应答变体试验，看能否触发客户端进入房间流程。

### 15.9 FE-loaded 是三处卡点的共同根因（2026-10-23 00:4x）

#### 反汇编链

`0x6BBF60` 是设置 `onboard_character_selected` 的函数，它有两个调用者：

```asm
; caller 1 @ 0x6C1C09
0x6C1C00  call 0x730C50        ; FE-loaded
0x6C1C05  test al, al
0x6C1C07  je 0x6C1C21          ; 未加载 -> 跳过设置
0x6C1C09  call 0x6BBF60        ; 设置 onboarded

; caller 2 @ 0x73DE94
0x73DE94  call 0x6BBF60
0x73DE99  test al, al
0x73DE9B  jne 0x73DE60         ; 失败 -> 走另一分支
```

而 `0x730C50` 自身要求**全部**成立：

```asm
0x730C57  cmp [0xE59D20], 4      ; FE_state 必须 4 或 6
0x730C62  cmp [0xE59D20], 6
0x730C67  call 0x803700          ; 对象必须非空
0x730C79  cmp eax, 2             ; 0xB7A680 必须返回 2
0x730C90  cmp [0x84ABABC], 1     ; 必须 == 1
0x730CBE  cmp byte [0x82C4A86], 0; 必须非 0
```

#### 实测值

`tools/probe_fe_loaded.py` 采样（对话结束前）：

```
FE_state [0xE59D20] = 5      <- 不是 4/6，直接失败
script   [0x84ABABC] = 0     <- 不是 1
final    [0x82C4A86] = 0     <- 是 0
```

**`FE_state=5` 是第一个也是决定性的失败点**——它让 `0x730C50` 无条件返回 0，
于是 `0x6BBF60` 不被调用、`onboarded` 永不设置、FE 梯也永远卡在 `G1==0`
（FE 梯 `G1==1` 分支同样调用 `0x730C50`）。

#### 尝试与结果

| 尝试 | 结果 |
|---|---|
| 把 `[0xE59D20]` 改成 4 | **破坏状态机**，`dw` 卡在 2，永远到不了 5 |
| 只改 `[0x84ABABC]=1` 与 `[0x82C4A86]=1` | `dw` 仍能到 5，但 `FE_state` 保持 5，`0x730C50` 依旧返回 0 |
| 不加强推、等自然推进 | `FE_state` 从不变成 4/6 |

**结论**：`FE_state` 是客户端自己的前端阶段机，5 表示"登录中"。把它强改成 4
会让后续状态转换无法进行。而真正要它变成 4/6，需要在正确的时机完成某个
前端加载动作——这个动作目前没有发生，且不清楚触发条件。

#### 由此解释的三件事

1. **为什么 `onboard_character_selected` 写了没用**：它根本不在路径上，
   写入点被 `0x730C50` 挡住。
2. **为什么「取代号」页面没有任何网络请求**：前端尚未进入加载完成态，
   UI 只是静态渲染，提交按钮的处理未接上。
3. **为什么 FE 梯需要外部强推 `G1=2`**：梯子自己在 `G1==0`/`G1==1` 都依赖
   `0x730C50` 或 firstlogin，两者离线都不成立。

#### 当前判断

M4.1（档案持久化）被 `FE_state` 卡住。这条路径需要理解前端阶段机的完整
转换条件（`[0xE59D20]` 的所有写者），成本明显高于此前预期。

可选路线：

1. 追踪 `[0xE59D20]` 的写者，弄清什么条件下它从 5 变 4/6；
2. 绕过「取代号」——直接构造客户端认为已建档的状态（需要知道 UI 从哪个
   对象读取玩家名）；
3. 接受「每次启动走一次代号流程」，转而攻克房间列表的主动触发
   （`svc21/task5` / `svc71/task9` 的请求条件）。

第 3 条与 M4 验收的"房间列表可见"直接相关，且不依赖 FE 修复，优先尝试。

### 15.10 ★★ [lobby+0x1F4] 是前端阶段机的扳机，但推到 2 会崩（2026-10-23 01:0x）

#### 完整因果链（全部反汇编验证）

```asm
; 0x621777 取 lobby 单例
0x621777  call 0x643280          ; mov eax,[0xE85C68]; 空则懒创建
0x62177C  mov esi, eax
0x621782  je 0x621A1A            ; 空 -> 跳过整段
0x62178A  mov ecx, esi
0x62178A  call 0xBAC350          ; = mov eax,[ecx+0x1F4]; ret
0x62178F  cmp eax, 1
0x621796  call 0xBAD800          ; == 1 时调用
0x62179D  mov ecx, esi
0x62179D  call 0xBAC350          ; 再读
0x6217A2  cmp eax, 2             ; ★ 必须等于 2
0x6217A5  jne 0x62199E           ; 否则跳过
0x6217AB  mov eax, [0xE59D20]    ; FE_state
0x6217B0  sub eax, 3
0x6217B3  je 0x6217CB            ; == 3 -> 写 4
0x6217B5  sub eax, 2
0x6217B8  jne 0x6217DF
0x6217BF  mov dword [0xE59D20], 6 ; ★ 我们的分支：5 -> 6
```

而 `0x730C50`（FE-loaded）又要求 `[0xE59D20] in {4,6}`，它返回 1 才会让
`0x6BBF60` 设置 `onboard_character_selected` 并推动 FE 梯。

#### 实测

`tools/probe_lobby_1f4.py` 通过 `[0xE85C68]` 找到 lobby 对象（本轮为
`0x37947E90`），读 `+0x1F4`：

```
[lobby+0x1F4] = 1     <- 代码要求 2
FE_state      = 5
dw            = 5
```

**写入 2 之后**（`--set 2`）：

```
01:03:49  [lobby+0x1F4]=1  FE_state=5  dw=5
01:03:50  [lobby+0x1F4]=2  FE_state=6  dw=5     <- 扳机生效
01:03:52  进程消失
```

**`FE_state` 确实从 5 跳到 6**，因果链完全成立。但客户端在 1-2 秒内崩溃。

#### 崩溃原因推测

`FE_state=6` 意味着前端进入"已加载"阶段，随后应该发生真正的 UI 资源加载。
崩溃可能因为：

1. 该阶段需要的资源（`.ff` 包）未就绪；
2. 通过强写得到的状态缺少配套的其它字段，前端初始化时解引用空指针；
3. `0xBAD800`（`== 1` 时才调用的那个函数）没被执行，留下了不一致状态。

#### 与社区结论的关系

社区文档（`PROGRESS.md` 与开发者口述）说：

> `[lobby+0x1F4]` 这个状态量以前从没撑过 47 秒就翻成 -2。根本原因是 pump 的匹配判定
> 失败后会走清理路径，把 1F4 写成 -2，而客户端再读到 -2 就认为连接已经失去。
> 一共改了 9 处运行期补丁……改完之后 `[lobby+0x1F4]` 首次稳定保持为 1。

关键差异：**社区让它保持 1**，而不是 2。我们观察到代码要求 2 才推进 FE_state，
但社区保持 1 时大厅就能正常渲染——说明在他们的环境里，FE 推进走的是另一条路径
（可能是时间顺序：先 `0xBAD800` 处理 1，再由别的逻辑写成 2）。

我们的 9 处 pump 补丁已经在用，`[lobby+0x1F4]` 稳定在 1——与社区一致。差别在于
社区能让客户端从 1 自然走到 2，而我们没有。

#### 下一步

1. 反汇编 `0xBAD800`（`== 1` 时调用），确认它是否负责把 1 推进到 2；
2. 若是，找出它失败的原因（可能依赖某个尚未实现的服务应答）；
3. 若不是，追踪 `[lobby+0x1F4]` 的全部写者，看谁在社区环境里写 2。

### 15.11 `[lobby+0x1F4]` 的全部写者与写 2 的两条路径（2026-10-23 01:1x）

#### 8 处写入点（全部位于 `0xBAD800`，即社区所说的 lobby pump）

用 `find_refs.py --pattern c783f4010000`（`mov dword [ebx+0x1F4], imm32`）扫描：

| 地址 | 写入值 | 备注 |
|---|---|---|
| `0xBADB40` | `0xFFFFFFFF`（-1） | 失败路径 |
| `0xBADDDA` | —— | 社区补丁 `baddDA+6` 的目标 |
| `0xBADFA2` | —— | 前置调用 `0xC699B0`（`0xBADF9D`） |
| **`0xBAE1AC`** | **2** | ★ 正常推进路径 A |
| **`0xBAE587`** | **2** | ★ 正常推进路径 B |
| `0xBAE74E` | —— | 社区补丁目标 |
| `0xBAE766` | **1** | 社区补丁改成写 1 |
| `0xBAE7AA` | —— | 社区补丁目标 |

**关键发现：写 2 的两处（`0xBAE1AC`、`0xBAE587`）是无条件写入**——只要执行流到达
那里就会写 2，中间没有 `test al,al` 之类的分支。

#### 写 2 的前置调用

两处写 2 之前都调用 `0xC699B0`，参数相同：

```asm
; 路径 A @ 0xBAE193
0xBAE193  mov ecx, [ebx+0x1F0]     ; 参数 1 = lobby[0x1F0]（服务器地址/端口）
0xBAE199  lea eax, [ebx+0x184]     ; 参数 2 = &lobby[0x184]
0xBAE19F  push eax
0xBAE1A0  push ecx
0xBAE1A1  lea ecx, [ebx+0x1A0]     ; this = lobby+0x1A0
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword [ebx+0x1F4], 2 ; 无条件

; 路径 B @ 0xBAE56B 结构相同
```

#### `0xC699B0` 的语义（设置服务器地址）

```asm
0xC699B0  cmp dword [esi+0x1C], 0  ; 已设置过？ -> 返回 0
0xC699D1  mov ecx, [ebp+8]         ; 参数 1
0xC699D4  test ecx, ecx
0xC699D6  je 0xC699C2              ; 为 0 -> 返回失败
0xC699D8  mov [esi], ecx           ; 保存
0xC699DA  call 0xBB1A80            ; 计算标识，存 [esi+0x38]
0xC699E2  mov eax, [ebp+0xC]       ; 参数 2 指向的结构
0xC699E7  mov [esi+0x3C], [eax+0]  ; 复制 4 个字段到 +0x3C..+0x48
0xC699F9  mov [esi+0x1C], 1        ; 标记成功
0xC699FC  mov al, 1                ; 返回成功
```

即：**只有拿到非零的服务器地址，才会标记成功**。

#### 推断

`[lobby+0x1F0]` 是客户端从服务端拿到的**大厅服务器地址/端口**。它目前为 0，
所以 `0xC699B0` 走失败分支。但由于写 2 本身无条件下达，真正的问题可能不是
`0xC699B0` 的返回值，而是**执行流根本到不了 `0xBAE1AC` / `0xBAE587`**。

两条路径都在 `0xBAD800` 内部较深的位置，前置条件尚未解析清楚——反汇编在
`0xBAE100` 处因字节对齐中断（把 `0xBAE100` 当成指令边界解出了 `stc`）。
下一步应从 `0xBAE0C0` 或更早的函数头部开始解码，或直接在这两个地址上看
哪些跳转能到达。

#### 与社区补丁的关系

社区 9 处补丁覆盖了 `0xBADC26`、`0xBADDDA+6`、`0xBAE74E+6`、`0xBAE766+6`、
`0xBAE7AA+6`，即把「写 -2」改成写 1。**他们没有动写 2 的两处**——说明在社区
环境里客户端能自然到达写 2。我们的客户端停在写 2 之前。

#### 结论

`[lobby+0x1F4]` 停在 1 并非某个补丁缺失，而是 pump 内部某个前置判断让执行流
提前返回。强写 2 能让 `FE_state` 到 6（已验证），但会崩溃。正确做法是让客户端
自己走到写 2——这需要先弄清 `0xBAD800` 从入口到 `0xBAE1AC` 的完整路径。

### 15.18 失败点定位：容器里缺少 key=0 的 1288 字节数据（2026-10-23 02:1x）

#### `0xBBA760` 是一个「按 key 读取定长数据」的函数

```asm
0xBBA760  push ebp; mov ebp,esp; sub esp,0x518
0xBBA773  mov eax, [ebp + 8]        ; 参数1 = key（调用方传 0）
0xBBA779  mov edi, [ebp + 0xc]      ; 参数2 = 输出缓冲
0xBBA77C  mov esi, ecx              ; this
0xBBA77F  lea ecx, [ebp - 0x518]
0xBBA787  call 0xBC1C00             ; 用 key 构造查询条件
0xBBA795  push 0x508                ; ★ 期望长度 0x508 = 1288 字节
0xBBA7A1  call 0xBC1C20             ; ★ 在容器里查找
0xBBA7B6  cmp al, 1
0xBBA7B8  jne 0xBBA7F3              ; 找不到 -> 返回 0
0xBBA7BA  mov edx, [ebp - 0x510]    ; 实际长度
0xBBA7C2  mov eax, [ecx]
0xBBA7C4  mov eax, [eax + 0x18]     ; 虚表第 6 项
0xBBA7D0  call eax                   ; 读取
0xBBA7D2  test eax, eax
0xBBA7D4  jle 0xBBA7F3               ; 读 0 或负 -> 返回 0
0xBBA7D6  cmp eax, [ebp - 0x510]
0xBBA7DC  jne 0xBBA7F3               ; 长度不符 -> 返回 0
```

所以 `0xBBA8A0`（进而 `0xBBAD40`、进而 pump 的写 1）失败的原因只有可能是：
**容器里没有 key=0 对应的、长度为 0x508 的那份数据**。

#### 容器对象从哪来

`0xBAE6C2` 起的流程：

```asm
0xBAE6C2  mov esi, [ebx + 0x1fc]     ; 旧容器
0xBAE6C8  cmp esi, edi
0xBAE6CA  je 0xBAE6DC
0xBAE6CC  mov ecx, esi
0xBAE6CE  call 0xBBA670              ; 销毁旧容器
0xBAE6D3  push esi
0xBAE6D4  call 0xB742E0              ; 释放
0xBAE6DC  mov [ebx + 0x1fc], edi     ; 清空
0xBAE6E2  push 0x1b8                 ; ★ 440 字节
0xBAE6E7  call 0xB742C0              ; 分配
0xBAE6FF  call 0xBBA810              ; 构造容器
0xBAE712  mov [ebx + 0x1fc], eax     ; 保存到 lobby+0x1FC
0xBAE718  call 0xBBAEE0              ; 取两个 dword 作为参数
0xBAE71D  mov ecx, [eax + 4]
0xBAE720  mov edx, [eax]
0xBAE72F  mov ecx, [ebx + 0x1fc]     ; this = 新容器
0xBAE735  call 0xBBAD40              ; 登记数据
```

即 pump **每次都新建**一个 440 字节的容器，然后试图往里面登记，登记失败就写
`[lobby+0x1F4] = 1`。

#### 目前的完整因果链

```
pump 0xBAD800
  -> 新建容器（440 字节）存于 lobby+0x1FC
  -> 0xBBAD40(this=容器, addr, buf, len)
       -> 0xBBAD6B rep movsd 34     复制 136 字节
       -> 0xBBA8A0
            -> 0xBBA760(容器, key=0, out)   期望 0x508 字节
                 -> 0xBC1C20 查找失败
       -> 返回 0
  -> 写 [lobby+0x1F4] = 1           失败标志
  -> [lobby+0x1F4] != 2，于是 0x6217A2 的比较不过，FE_state 停在 5
```

#### 结论

一个**刚新建的空容器**里当然没有 key=0 的数据。这说明 `0xBBAD40` 的语义
不是「查询」，而更可能是「**注册/插入**」——`0xBBA760` 在插入失败后返回 0
是正常的首轮行为，真正的判断在别处。

也就是说：`0xBAE74E` 写 1 的那两个分支，可能对应的是「这次还没准备好」，
而不是「永远失败」。若如此，pump 后续应该还有把 1 推进到 2 的路径——
而 `0xBAE1AC`/`0xBAE587` 两处无条件写 2 正是它。

#### 下一步

1. 反汇编 `0xBBA810`（容器构造）与 `0xBBAEE0`（参数来源），确认容器类型；
2. 反汇编 `0xBBAD40` 尾部的失败分支 `0xBBADCD`，看它在什么情况下不走
   `[ebx+0x1A0]=1` 的成功路径；
3. 关键验证：在运行期**连续采样** `[lobby+0x1F4]` 与 `lobby+0x1FC`，
   确认 pump 是否周期性重建容器、值是否在 1 与其它值之间跳动。若只在 1
   上不动，说明这个阶段确实进不去；若跳动，则说明只是采样时机问题。

第 3 条成本最低，优先做。

### 15.19 采样证明 pump 每轮都在跑、每轮都失败（2026-10-23 02:1x）

#### 高频采样结果

`tools/sample_1f4.py` 以 200 Hz 采样 5 秒：

```
lobby = 0x361a7c60
--- 921 samples over 5.00s ---
  distribution of [lobby+0x1F4]: 1:921
  transitions observed: 0
  final 1FC=0x381b0180  FE_state=5
```

**921 次采样值恒为 1，零次跳变，容器指针也不变。**

一度据此推断「pump 只跑了一次」，但这是错的——见下面的前置条件验证。

#### pump 的两个入口条件都满足

```asm
0xBAD83D  cmp byte ptr [edi], 0     ; edi = ebx+8
0xBAD840  je 0xBAE7C6               ; 为 0 -> 直接返回
0xBAD846  cmp dword [ebx+0x1F4], 1
0xBAD84D  jne 0xBAE7C6              ; 不等于 1 -> 直接返回
```

实测：

```
lobby      = 0x3793efe0
byte[+0x08] = 1        <- 非零，不提前返回
[+0x1F4]    = 1        <- 等于 1，继续
[+0x1FC]    = 0x37d92820
[+0x1F0]    = 0x3617ec60
```

**两个条件都满足，所以 pump 确实在执行。**

容器指针恒定并不表示没重建——`0xBAE6C2` 起的流程是先销毁旧容器、释放，再分配新的，
分配器极可能返回同一地址。因此 **pump 是每轮重建容器、每轮登记失败、每轮写 1**。

#### 完整死锁结构

```
每帧:
  FE 主循环 0x621750
    -> 读 [lobby+0x1F4] == 1
    -> call 0xBAD800 (pump)
         -> 重建 440 字节容器 -> lobby+0x1FC
         -> 0xBBAD40 登记数据 -> 0xBBA8A0 -> 0xBBA760(key=0, 1288 字节)
         -> 查不到 -> 0
         -> 写 [lobby+0x1F4] = 1
    -> 再读 [lobby+0x1F4]，仍为 1，不等于 2
    -> FE_state 不推进，停在 5
```

同时 `0x7F58A0`（一个「等 `[lobby+0x1F4]` 变成非 1」的阻塞重试循环，内部 sleep 10ms
后重调 pump）有 **7 个调用者**（`0x629319`、`0x62AA88`、`0x62F88F`、`0x634A98`、
`0x67578D`、`0x759A7E`、`0x7CA24D`），全在游戏逻辑层——这些地方**都没被执行到**，
因为客户端还没有进入游戏逻辑。

#### 因果关系的最终形态

这不是「FE 等 state」或「state 等 FE」的单向依赖，而是一个**闭环**：

- pump 需要容器里有 key=0 的 1288 字节数据才能成功；
- 容器每轮新建、每轮为空；
- 而填入这份数据的路径在游戏逻辑层（`0x7F58A0` 的 7 个调用点所在的那一层）；
- 游戏逻辑层又等待 FE 完成（`FE_state` 到 6、`onboarded` 置位）。

**闭环的断点在「取代号」提交**：只有玩家完成建档，FE 才会放行到游戏逻辑层，
游戏逻辑层才会去驱动 `0x7F58A0` 这条等待链，pump 才可能成功。

这也解释了为什么之前所有「绕过去」的尝试都会崩溃——闭环里任何一环被强行
置位，其它环仍然停在原处，状态不一致就崩。

#### 下一步

1. 反汇编 `0xBBA810`（容器构造），确认它是否预填内容；若预填，则 `0xBC1C20`
   查找失败说明预填的 key 不是 0，需要找出正确的 key；
2. 反汇编 `0x7F58A0` 的一个调用点（如 `0x67578D`），看它属于哪个功能，从而
   判断「游戏逻辑层」具体在等什么；
3. 确认「取代号」提交的落点：既然它不是网络请求，最可能是写 `config_mp.cfg`
   或某个全局，可从 `0x83xxxx` 区的写入点反查。

第 1 条最直接，优先。
