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

### 15.20 容器确认为空；pump 线到此收束（2026-10-23 02:2x）

#### `0xBBA810` 只做初始化，不预填

```asm
0xBBA810  push ebp; mov ebp,esp; ... 建立 SEH 帧
0xBBA835  mov esi, ecx
0xBBA83A  lea ecx, [esi + 4]
0xBBA83D  call 0xB753A0              ; 子容器 1
0xBBA844  lea ecx, [esi + 0x8c]
0xBBA84D  call 0xB753A0              ; 子容器 2
0xBBA852  lea ecx, [esi + 0x114]
0xBBA85C  call 0xB753A0              ; 子容器 3
0xBBA861  lea ecx, [esi + 0x1a8]
0xBBA86B  call 0xB753A0              ; 子容器 4
0xBBA86B  mov dword ptr [esi + 0x19c], 0
0xBBA871  mov dword ptr [esi + 0x1a0], 0   ; "未处理"标记
0xBBA877  mov byte ptr [esi + 0x1a4], 0
```

**四个子容器全部初始化为空，没有任何预填数据。**

这排除了「容器本来有内容、只是 key 查错」的可能：**容器确实是空的**，
所以 `0xBBA760(key=0, 0x508)` 必然查不到。

#### 查找实现的调用链

```asm
0xBC1C20  ...
0xBC1C36  push eax                   ; 期望长度
0xBC1C3E  mov cl, byte ptr [edi]     ; key 首字节
0xBC1C42  mov byte ptr [ebp + 0x17], cl
0xBC1C45  call 0xB783E0              ; 核心查找
0xBC1C4D  test al, al
0xBC1C4F  je 0xBC1C9D                ; 未命中
```

核心在 `0xB783E0`，但在容器为空的前提下这条路径不可能命中，
继续深挖它的收益很低。

#### pump 线的最终结论

经过第 10-16 共七轮的追踪，`[lobby+0x1F4]` 的机制已经完全清楚：

1. **`0xBAD800`（pump）每帧执行**，前置条件 `byte[lobby+8]!=0` 且
   `[lobby+0x1F4]==1` 实测都满足；
2. 每轮先销毁旧容器再新建一个 440 字节的空容器存于 `lobby+0x1FC`；
3. 然后调 `0xBBAD40` → `0xBBA8A0` → `0xBBA760(key=0, 0x508 字节)`；
4. 空容器查不到，返回 0；
5. pump 于是写 `[lobby+0x1F4] = 1`（失败标记）；
6. FE 主循环读到 1，不到 2，`FE_state` 停在 5，`0x730C50` 报告未加载，
   `onboarded` 不设置，FE 梯不前移。

而真正会填入那份数据的代码在游戏逻辑层——`0x7F58A0`（等待 `[lobby+0x1F4]`
变成非 1 的阻塞循环）的 7 个调用点全在那一层，客户端尚未到达。

**这是一个闭环，断点在「取代号」提交。**

#### 判断：这条线不再深入

按「同一阻断连续 3 轮无进展则换方向」，`[lobby+0x1F4]` 相关追踪已投入
第 10-16 共七轮。虽然每一轮都获得了新的代码级事实（这本身有价值），
但对 M4 验收判据没有产生可观测的推进。

因此**收束这条线**，把结论固化在文档里，后续只在出现新证据时回看。

#### 下一轮方向

回到「取代号」本身，但换一种探测方式：既然它不产生网络请求，且 UI 是
Scaleform，那么提交动作很可能写入了某个客户端全局或本地文件。可行的低成本
探测：

1. 在客户端运行、停在「取代号」界面时，对 `0x82xxxx`/`0x83xxxx` 数据区做
   **全量快照对比**——先截一次，人工或脚本输入代号后触发「继续」，再截一次，
   差异即为提交写入的落点；
2. 对 `players\config_mp.cfg` 与 `settings_*.zip.iw4` 做哈希对比；
3. 若差异落在某个全局上，用 `find_stores.py` 反查该全局的写者，即可定位
   提交处理函数。

第 1 条不依赖人工输入也能做：用 `tools/type_text.py` 的 WM_CHAR 方式写入
输入框（之前失败可能只是坐标不对），再点「继续」。

#### 关于之前输入失败的解释

`type_text.py` 用了 SendInput 与 WM_CHAR 两种方式都未让文字进入输入框，
当时的判断是「Scaleform 不接受合成输入」。但采样表明客户端此时**处于
pump 每帧失败的循环中**，UI 线程可能根本没在处理输入消息。这也解释了
为什么用户手动输入能进（真实键盘事件优先级更高）。

若要自动化，需要在正确的时机（UI 完成一次完整帧）投递，而不是在启动后
固定等待 N 秒。

### 15.21 登记参数是活的接口对象，失败仍归结为空容器（2026-10-23 02:2x）

#### 追清 `0xBBAD40` 的四个参数

`0xBAE718 call 0xBBAEE0` 返回的是一个 8 字节的临时结构，内容固定：

```asm
0xBBAEE0  fld dword ptr [0xCAEB8C]
0xBBAEE6  mov eax, ecx
0xBBAEE8  fstp dword ptr [eax + 4]     ; [eax+4] = 某个浮点常量
0xBBAEEB  mov dword ptr [eax], 5       ; [eax] = 5
0xBBAEF1  ret
```

即 `[eax]` 恒为 **5**，`[eax+4]` 是一个浮点常量。这两项作为中间两个参数传入。

真正重要的是**第一个参数**——`0xBAE72E` 最后 push 的是 `[ebx+0xC]`：

```asm
0xBAE71D  mov ecx, [eax + 4]
0xBAE720  mov edx, [eax]
0xBAE722  push ecx                    ; 浮点
0xBAE723  mov ecx, [ebx + 0xC]        ; ★ lobby+0xC
0xBAE726  push edx                    ; 5
0xBAE727  lea eax, [ebp - 0x658]
0xBAE72D  push eax                    ; &local
0xBAE72E  push ecx                    ; ★ lobby+0xC  -> [ebp+8]
0xBAE72F  mov ecx, [ebx + 0x1FC]      ; this = 容器
0xBAE735  call 0xBBAD40
```

在 `0xBBAD40` 内部：

```asm
0xBBAD4F  mov eax, [ebp + 8]          ; = lobby[0xC]
0xBBAD52  test eax, eax
0xBBAD54  je 0xBBADAB                 ; 为 0 才失败
0xBBAD58  mov dword ptr [ebx], eax    ; 容器首字段 = lobby[0xC]
```

#### 实测值

```
lobby       = 0x37c5f068
[lobby+0x0C] = 0x37fa6818   <- 非零，有效对象
[[lobby+0x0C]] = 0xd95558   <- 有 vtable
[lobby+0x1F4] = 1
[lobby+0x1F0] = 0x36c9ec60
```

**`lobby[0xC]` 是一个活的接口对象**（带虚表），所以 `0xBBAD54` 那处
`je` 不会触发，`0xBBAD40` 不会在这里失败。

#### 失败点因此唯一确定

排除了「参数为 0」之后，失败只剩一个出口：`0xBBA8A0` → `0xBBA760(key=0, 0x508)`
在空容器里查不到。

而 `0xBBA810` 已确认只做初始化、不预填，所以容器每轮都是空的。

#### 一个尚未消解的矛盾

`0xBBAD40` 会把 `&local` 的 136 字节复制进 `[容器+4]`（`0xBBAD6B rep movsd`），
而紧接着 `0xBBA8A0` 又要从 key=0 读 1288 字节**到** `[容器+4]`。前者写、后者读
同一块区域，语义上像是「先暂存、再校验是否与容器里的记录一致」——如果暂存内容
与容器记录不符就失败。

若这个解读正确，那么容器**本来就应该有内容**，而它为空说明**更早的某个填充步骤
没有发生**。那个步骤最可能依赖一次网络交互。

#### 结论与收束

第 10-17 轮共八轮围绕 `[lobby+0x1F4]` 追踪，得到的确定事实是：

- pump 每帧执行、每帧写 1（失败标记）；
- 失败原因是容器里没有 key=0 的 1288 字节记录；
- 容器每轮新建且为空；
- 登记参数（`lobby[0xC]`）是活的接口对象，不是空指针；
- 填充容器的那一步在游戏逻辑层，客户端尚未到达。

**这条线不再深入**。它需要的信息只能从「让客户端进入游戏逻辑层」获得，
而那又依赖「取代号」提交成功——闭环没有外部切入点。

#### 下一轮方向（明确）

转向可以**独立推进**的 M4 子目标，不再依赖 FE 闭环：

1. **`rankIconTable.csv` 与武器/配件表提取**——属于 M4.2 的资源最小集，
   完全独立，且已有 `tools/ifs_entries.py` 可用；
2. **`svc21/task5` 房间列表帧的结构验证**——在离线单测里构造并自校验，
   为将来客户端真的请求时做好准备；
3. **重新评估 M4.1 的判据**——若「代号流程」是客户端固有一环，
   考虑把 M4.1 重新定义为「档案持久化 + 每次启动可自动完成代号」，
   并用真实键盘事件（而非合成输入）验证自动化可行性。

第 1 条最稳，先做。

### 15.22 社区参考脚本不完整；但暴露了「重触发前端」这一关键手法（2026-10-23 02:3x）

#### `rankIconTable.csv` 不在 `.ifs` 里

对 987 个 `.ifs` 包分别以 2 MB 与 6 MB 深度扫描 `rankIconTable`，命中 0；
扫描 `weapons_mp`、`.csv`、`mp/playlists` 等同样为 0。全客户端目录下也不存在
任何 `*.csv` 文件。

但在主程序字符串里找到了路径引用（VA `0xABDE33`）：

```
mp/callsignTitle.csv
mp/rankIconTable.csv
mp/callsignBackground.csv
mp/callsignIcon.csv
mp/callsignFrame.csv
```

即这些是**运行期由客户端按名字从 fastfile 里加载的资源**，不是 `.ifs` 容器里的
独立文件。fastfile 是加密的（§12.19 已确认 `mp_playlists.ff` 从 `0x14` 起高熵），
所以**无法离线提取**，必须在运行期让客户端自己去加载。

#### 社区脚本引用了不存在的依赖

`codol-ember/.../launch319-reference/reference/launch/` 只有 `orch319.py` 一个文件，
它 `import` 的下列模块**全部缺失**：

```
patches319.py          runtime_patch.py       rank_hook319.py
hide_text319.py        preload_rank_icons319.py       lc319/
```

其中 `preload_rank_icons319.py` 正是 `--preload-rank-icons` 调用的脚本，
`patches319.py` 里才有 `PATCHES` 字典（含 `lobby-pump-ok`、`register-ok`、
`lobby-ok` 三组补丁的实际内容）。**社区所说的"已验证"缺少可复现的脚本主体。**

#### 但 `orch319.py` 暴露了一个此前没试过的手法

```python
ap.add_argument("--retrigger-delay", type=float, default=45.0,
                help="首次激活后多少秒重触发前端（默认 45；越小进大厅越快）")
ap.add_argument("--retrigger-count", type=int, default=1,
                help="重触发次数（默认 1；可多触发几次抢时间）")
ap.add_argument("--activate-delay", type=float, default=0.0,
                help="dw=5 后再等 N 秒才激活前端（让数据先落地）")
```

以及循环里的注释：

```python
# dw=5 已调用一次；45 秒后重触发显示大厅（实测 46 秒可出 UI）。
```

**含义**：`0x5EBE10`（cppActivate）调一次不够，需要在约 45 秒后**再调一次**
才能真正显示大厅。我们的 `tools/ui_activate.py` 只调了一次。

这与我们观察到的现象一致：调一次后 `gate=1`、`G1=3`（前端 active），
但画面停在训练官/取代号页面——**前端被"激活"了但没"显示"**。

#### 另一批有用地址

`orch319.py` 里的钩子与常量清单：

```python
HOOKS = [
    (0xBA3BF0, "h81"),
    (0xBA3B20, "h83"),
    ...
]
```

- `0x5EBE10` cppActivate（前端激活）
- `0x4A6D50` 解锁判定（`--unlock-all` 桩成恒真）
- `0xBA3BF0` / `0xBA3B20` 与 `0x81`/`0x83` 帧相关（正是加密通道那两个入口）

#### 下一步

1. 给 `tools/ui_activate.py` 加 `--retrigger-delay` / `--retrigger-count`，
   在首次激活后按间隔重复调用 `0x5EBE10`；
2. 配合 `--activate-delay`（dw=5 后延迟再激活）测试不同时序组合；
3. 观察重复激活后画面是否从"取一个代号"变成真正的大厅。

这比继续挖 `[lobby+0x1F4]` 更有希望：社区明确说"越小进大厅越快"，
说明重触发确实是进大厅的必要步骤，而我们一直漏了它。

### 15.23 重触发前端无效；资源提取确认为不可行（2026-10-23 02:5x）

#### 重触发测试（阴性）

按社区 `orch319.py` 的说法「45 秒后重触发前端，实测 46 秒可出 UI」，
用 `tools/ui_activate.py --reset` 清除一次性 guard 让 `0x5EBE10` 再执行：

```
=== waiting 50s for first activation to settle ===
before:  screens/r_before.png
=== reset guard (retrigger #1) ===
trampoline installed at 0xeed0000 (activates 0x5ebe10 once)
guard reset; activation will fire again
after1:  screens/r_after1.png
=== reset again (retrigger #2) ===
trampoline already installed, cave=0xeed0000
guard reset; activation will fire again
after2:  screens/r_after2.png
```

**三次截图（首次激活后、重触发一次、重触发两次）画面完全一致**，都停在
「欢迎来到使命召唤ONLINE！我是你的训练官。开始之前，请先取一个代号。」

所以「重触发前端」在我们当前的状态下**不产生任何可见变化**。

一个可能的原因：`--reset` 只是清了 guard，而 trampoline 挂在 FE 梯（`0x5EBFD0`）
上；如果 FE 梯在该阶段已不再被调用，guard 清得再多次也不会触发激活。
这一点无法从外部区分，因此不继续投入。

#### 资源提取（确认为不可行）

对 987 个 `.ifs` 包做 2 MB 与 6 MB 两档深度扫描：

| 关键词 | 命中 |
|---|---|
| `rankIconTable` | 0 |
| `weapons_mp` | 0 |
| `.csv` | 0 |
| `mp_rank`、`attachment` | 0 |

整个客户端目录下也不存在任何 `*.csv`。

而主程序里确实有这些路径（VA `0xABDE33`）：

```
mp/callsignTitle.csv
mp/rankIconTable.csv
mp/callsignBackground.csv
mp/callsignIcon.csv
mp/callsignFrame.csv
```

**结论**：它们是运行期由客户端从 fastfile 里按名加载的资源，不是 `.ifs` 容器中的
独立文件。fastfile 加密（`IWff0100` 头后从 `0x14` 起高熵，§12.19/§12.22 已验证），
因此**无法离线提取**。

这意味着 `LONG-RUN-GOAL.md` §9.3 的「资源最小集」中，
`rankIconTable.csv` 与武器/配件表**不能通过解包获得**，只能：
- 让客户端在运行期自己加载（需要先让 UI 进到对应页面），或
- 从社区参考数据抄录（社区仓库中不存在）。

#### 社区参考脚本的完整性

`launch319-reference/reference/launch/` 只有 `orch319.py` 一个文件，
其 `import` 的 6 个模块全部缺失：

```
patches319.py   runtime_patch.py   rank_hook319.py
hide_text319.py  preload_rank_icons319.py   lc319/
```

其中 `patches319.py` 才含 `PATCHES` 字典（`lobby-pump-ok` / `register-ok` /
`lobby-ok` 三组补丁的真实内容），`preload_rank_icons319.py` 是军衔图标预加载的实现。
**社区声称的"已验证"缺少可复现的脚本主体**，本项目的补丁集只能靠自身研究得出。

#### 本轮净结论

1. 重触发前端无效——不再尝试；
2. `rankIconTable.csv` 等资源无法离线提取——M4.2 的资源前置条件需重新定义；
3. 社区脚本不完整——不能作为实现参照，只能作为地址与手法线索。

#### 下一轮方向

既然资源路线和 FE 路线都受阻，回到 M4 的核心判据本身，做一件**不依赖客户端突破**
的事：把 `svc21/task5`（房间列表）与 `svc71/task9`（服务器信息）的应答帧结构
在离线单测中构造并自校验，同时补齐 `server319` 的服务能力测试。

这样即使客户端暂时进不去，服务端侧也已经"准备好"，一旦 UI 打通即可立即验证；
而且这部分工作有明确的 pass/fail，属于可交付的实质进展。

### 15.24 ★★ 重大修正：firstlogin 修复反而把客户端挡在大厅之外（2026-10-23 02:5x）

#### 以前的判断是错的

§12.20 认为 `[D+0xC]=1` 让 `0x6BBF30`（firstlogin）返回 1 是"突破"，因为画面
从"选择角色"变成了"欢迎…请先取一个代号"。当时的结论是"选人界面被跳过了"。

**但从 M3 的存档证据看，这个判断方向错了。**

#### M3 的真实状态

`evidence/20261022-1604220-lobby/` 的六张截图里：

- `5-lobby-textfield.png` 显示的是**一个调试用的 TextField 测试面板**（标题 "TextField"、
  带「关闭」按钮），**背景已经是大厅**——右侧能看到 `AdministraClient`、四个游戏模式；
- `6-lobby-final.png` 是**完整大厅**：顶部「游戏大厅/开始游戏/生涯/商店/仓库/军火基地/赛事」、
  四个模式（多人竞技 PVP、勇者游戏、闯关玩法 PVE、战神排位赛）、左上「军火币商城」、
  底部「大厅群聊频道加入中…」，玩家名 **`AdministraClient`**。

而 `MILESTONES.md` 对 M3 的记述明确写着：

> 遗留：**TextField 弹窗点击**、聊天频道、业务数据填充

**即：M3 达成大厅时，代号早已存在（`AdministraClient`），客户端根本没有经过
「取一个代号」这一步。** 那个 TextField 是额外弹出的调试面板，不是代号输入框。

#### 因此 firstlogin 修复是有害的

M3 的做法是：`dw=5` 后直接调 `0x5EBE10`（cppActivate）激活前端 → 大厅显示。

而 §12.20 之后，`auto_lobby.py` 会在 `dw>=2` 时写 `[[0x3306D60]+0xC]=1`，
使 `0x6BBF30` 返回 1，FE 梯因此**继续前进**，走到了「取一个代号」这一页——
**把客户端从大厅路径上推开了**。

#### 验证（本轮实测）

去掉 firstlogin 修复、其余保持（15 处补丁 + `dw=5` 后 `ui_activate`）：

```
dw=5 reached
cs= 0 ui= 9
trampoline installed at 0x5a580000 (activates 0x5ebe10 once)
```

截图 `runs/20261023-m4-nofirstlogin/screens/n1.png`：
**画面变成空白前端背景**（蓝色粒子/网格），**不再是「取一个代号」**。

再加回 `script_state=1` + `fe_final=1`（仍不修 firstlogin），
截图 `runs/20261023-m4-combo/screens/c1.png`：同样是空白前端背景，粒子更密。

#### 现在的状态

| 配置 | 画面 |
|---|---|
| 有 firstlogin 修复 | 「欢迎…请先取一个代号」+ 输入框 |
| **无 firstlogin 修复** | **空白前端背景（已离开代号页）** |

空白前端说明：前端**已被激活**、渲染管线在跑，但 **UI 资源（`ui_mp.ff`）尚未加载**。
M3 当时是加载了的——差别在于 M3 还做了别的事。

#### 下一步（明确）

1. 读 `SOLUTION-100-111.md` 里关于大厅的记述，找 M3 当时额外做了什么；
2. 检查 `runs/20261022-1604220-min/`（M3 达成时的那次运行）的 `patch.json`，
   对比补丁集与现在的 15 处是否一致——很可能 M3 用的补丁更少或不同；
3. 若 UI 资源加载依赖某个被我们额外补丁改掉的判断，回退那处即可。

**这是自 §12.20 以来第一次让画面真正离开代号页**，方向已经纠正。

### 15.25 ★★ M3 的真实配方被找出来了（2026-10-23 03:0x）

#### 关键证据：`runs/20261022-1604220-min/patch.json`

M3 达成大厅那次运行的记录只有 **6 个补丁**、**53 条采样事件**、**没有** `ui_activate`：

```json
"command_line": "…\codoMP_client_shipRetail.exe -q"
"patches": [
  {"rva":"0x403699","original":"741f",         "replacement":"eb1f"},
  {"rva":"0x403659","original":"893540ba4a08", "replacement":"909090909090"},
  {"rva":"0x3f2a0a","original":"3dbc0200007407","replacement":"b8bc0200009090"},
  {"rva":"0x3ee9dc","original":"e82f2f0100",   "replacement":"9090909090"},
  {"rva":"0x37c860","original":"558bec83e4f8", "replacement":"c39090909090"},
  {"rva":"0x20c649","original":"b001",         "replacement":"b000"}
]
"notes": ["runtime-only patches; on-disk client unchanged"]
```

**注意最后一条是 `b001 -> b000`**。而本项目后来的补丁集写的是
`0x20C649:B000:B001`，方向正好相反。

#### 关键证据：那次运行的 `lsg.jsonl`

```
13:26:15 plaintext_frame / gate_reply / plaintext_frame2
13:26:15 session_derived challenge_verified; client-memory-read=false
13:26:15 token_reply
13:26:15 client_frame … payload_len=83
13:26:15 task_request service=71 task=4
13:26:15 candidate_task_reply svc71/task4
13:26:54 client_frame … payload_len=8          <- 39 秒后！
13:26:54 task_request service=71 task=9
13:26:54 unhandled_task service=71 task=9
13:26:54 terminal_task_reply svc71/task9 error=14
13:26:54 client_frame … payload_len=142
13:26:54 task_request service=71 task=3
…
```

两条决定性的事实：

1. **客户端在 `71/4` 之后约 39 秒才发 `71/9`**——之前本项目只等 30-35 秒，普遍
   差一点点；本轮按 75 秒和 90 秒重测，仍然只有 `71/4`，所以时间不是唯一条件；
2. **`71/9` 收到 `error=14`（未实现）后，客户端照样继续发 `71/3`**——说明客户端
   不要求应答正确，只要**有**应答就往下走。

#### 本轮实测对比

| 配置 | dw | G1 | gate | 客户端是否发 71/9 | 画面 |
|---|---|---|---|---|---|
| 15 补丁 + 强推 G1 + firstlogin 修复 | 5 | 3 | 1 | **否**（等 75s） | 「取一个代号」 |
| 15 补丁 + 强推 G1，**不修 firstlogin** | 5 | 3 | 1 | **否** | **空白前端背景** |
| **M3 的 6 补丁，不推 G1，不激活** | 5 | **0** | **0** | 否（等 90s） | 未观察 |

第三种配置下 `G1=0`、`gate=0`，FE 梯**完全没动**——但 M3 当时画面是大厅。
说明 M3 的 FE 梯是**自然前进**的，其触发条件在我们现在的环境里已不成立。

#### 一个失败的实验：恢复 2021 年原始存档

`E:\GAME\COD\使命召唤OL\players\config_mp.cfg`（7850 B，2021-08-29）是用户
原始的在线存档。把它复制进隔离副本后**客户端直接崩溃**（`no visible CODO window`，
LSG 会话一条事件都没有），已回滚。

对比发现 `config_mp.cfg` **每次保存都用不同密钥加密**（原始 7850 B 与当前 7864 B
有 7825 字节不同），无法做字节级差异分析，也不能跨环境搬运。

#### 结论

M3 的成因已定位到**补丁集规模**（6 个而非 15 个）与**没有强推 G1**，
但直接复原 6 补丁后 FE 梯不前进，说明还缺一个当时自然发生的触发条件。
该条件最可能依赖 `config_mp.cfg` 里的有效存档（代号已存在），而当前副本的存档
已被多次运行改写。

#### 下一步

1. 用 6 补丁 + 只补 `firstlogin`（不动其它）测试，看 FE 梯能否前进到 `G1=1`；
2. 若不行，逐个回退 15 补丁中的 9 处 pump 补丁，找出哪一处让 `71/9` 不再发出；
3. 保留 `runs/20261022-1604220-min/patch.json` 作为唯一可信的"能进大厅"基线，
   后续所有实验都以它为参照做二分。

### 15.26 澄清补丁参数语义；15 补丁全部确认应用（2026-10-23 03:2x）

#### `patch_runtime.py` 的参数是 `RVA:NEW:EXPECTED`

```python
parts = spec.split(":")
rva      = int(parts[0], 0)
new      = bytes.fromhex(parts[1])      # 第 2 段 = 要写入的新字节
expected = bytes.fromhex(parts[2])      # 第 3 段 = 期望的原始字节
```

所以 `0x20C649:B000:B001` 的含义是「把 `b001` 改成 `b000`」，**方向一直是对的**。
上一节（§12.37）据此推断"补丁方向写反、22 轮从未生效"是**误读**，应予更正。

#### 运行内存实测原始字节（Build 1604220）

```
0x20C649: b001
0x403699: 741f
0x403659: 893540ba4a08
0x3F2A0A: 3dbc02000074…
0x3EE9DC: e82f2f0100
0x37C860: 558bec83e4…
```

与 M3 的 `patch.json` 记录逐条一致。

#### 15 个补丁全部 `applied=True, verified=True`

```
OK 0x403699  741f           -> eb1f
OK 0x403659  893540ba4a08   -> 909090909090
OK 0x3f2a0a  3dbc0200007407 -> b8bc0200009090
OK 0x3ee9dc  e82f2f0100     -> 9090909090
OK 0x37c860  558bec83e4f8   -> c39090909090
OK 0x20c649  b001           -> b000
OK 0x7ba295  7e1a           -> 9090
OK 0x7ba29d  7512           -> 9090
OK 0x7ba276  7439           -> 9090
OK 0x7bad4d  7572           -> 9090
OK 0x7adc27  feffffff       -> 01000000
OK 0x7adde0  feffffff       -> 01000000
OK 0x7ae754  feffffff       -> 01000000
OK 0x7ae76c  feffffff       -> 01000000
OK 0x7ae7b0  feffffff       -> 01000000
```

**补丁侧没有问题。** 之前 `patch.json` 缺失只是因为在 `Start-Job` 里用了
`--observe 200` 而 job 被提前 `Stop-Job`，进程没走到写证据那一步。

#### 剩余差异只有一个：FE 梯不自然前进

| 配置 | dw | G1 | gate | 71/9 | FE_state |
|---|---|---|---|---|---|
| 15 补丁，不强推，不激活，等 90 s | 5 | **0** | **0** | 否 | 5 |
| M3 的 6 补丁，不强推，不激活 | 5 | 0 | 0 | 是（+39 s） | — |
| 15 补丁 + 强推 G1=2 + 不修 firstlogin | 5 | 3 | 1 | 否 | 5 |

关键读数：`[D+0xC] = 0`，即 `0x6BBF30`（firstlogin）返回 0，FE 梯因此停在 `G1=0`。

M3 时它必然返回过 1 或走了别的路径，否则梯子不会动。而
`[D+0xC]` 的来源是客户端从存档里读出的账号状态——当前副本的
`config_mp.cfg` 已被多次运行改写（7864 B，比原始 7850 B 多 14 B），
不再包含有效的代号信息。

#### 结论

22 轮之后可以确定：**补丁、协议、坐标都不是问题**，唯一缺口是
**客户端存档里没有有效的"已建档"状态**，导致 `0x6BBF30` 返回 0、
FE 梯不前进、`0x730C50` 不报告 FE 加载、`onboarded` 不设位。

这个状态本应由「取一个代号」提交产生，而提交路径在 UI 层且不产生网络请求。

#### 下一步（二选一，需人工介入）

1. **人工**：由用户手动完成一次代号流程，之后把
   `runtime/client-1604220/players/config_mp.cfg` 备份为
   `config_mp.cfg.onboarded`。后续所有运行都用这份存档，即可稳定进大厅。
2. **自动**：直接对 `0x6BBF30` 打桩成 `mov eax,1; ret`，绕过 firstlogin 判断。
   风险是后续状态机可能因缺少配套字段而崩溃——但成本极低，值得一试。

建议先试 2，失败再走 1。

### 15.27 打桩 `0x6BBF30` 直接崩溃——闭环不可单点打破（2026-10-23 03:4x）

#### 实验

把 `0x6BBF30`（firstlogin）前 6 字节从

```
b8 01 00 00 00 39    mov eax,1 ; cmp [0x331C5C0],eax
```

改为

```
b8 01 00 00 00 c3    mov eax,1 ; ret
```

即无条件返回 1。补丁记录确认应用成功：

```
OK 0x2bbf30  b80100000039 -> b801000000c3  applied=True verified=True
```

#### 结果：崩溃

```
2026-10-20T18:45:10Z task_request service=71 task=4
2026-10-20T18:45:34Z raw_session_end ConnectionResetError:[WinError 10054]
client exited
s1: no visible CODO window
```

客户端在 `71/4` 之后约 24 秒**连接被强制关闭**并退出进程。`dw` 从未到 5。

#### 解释

`0x6BBF30` 返回 1 会让 FE 梯继续前进到后续阶段，而那些阶段需要**配套的账号
字段**（代号、档案、解锁标志等）。这些字段只在真正的建档流程完成后才存在，
强行让判断通过等于让客户端带着空数据往下走，很快解引用到无效内容。

这与 §12.31 记录的「闭环」判断一致：**任何单点强制都会因其它环仍停在原处
而崩溃**。此前强推 `[lobby+0x1F4]=2` 也是同样的结局。

#### 23 轮的收敛结论

可以确定的事实清单：

| 项目 | 状态 |
|---|---|
| 15 个补丁 | 全部 `applied=True, verified=True`，与 M3 记录逐条一致 |
| 认证 / LSG 握手 | 正常，`71/4` 有请求有应答 |
| FE 梯自然前进 | **不会**——`[D+0xC]=0` 使 firstlogin 返回 0 |
| 强推 G1 | 能到 `G1=3, gate=1`，但 UI 停在代号页或空白前端 |
| 强推 `[lobby+0x1F4]=2` | `FE_state` 到 6，随即崩溃 |
| 打桩 firstlogin | 24 秒后崩溃 |
| 逆推出 `71/9` | 等待 90 秒仍无请求 |
| 资源解包 | fastfile 加密，不可行 |
| 社区参考脚本 | 缺 6 个依赖模块，不可用 |

**唯一缺少的东西：一份"已建档"的客户端存档。**

M3 达成大厅时的 `config_mp.cfg` 含有有效的代号与档案状态，所以 firstlogin
自然返回 1、FE 梯自然前进、客户端在 39 秒后继续请求 `71/9`。当前副本的
`config_mp.cfg` 已被后续多次运行改写（7864 B vs 原始 7850 B），该状态已丢失。

#### 需要人工介入的一步

**请手动完成一次代号流程**（在客户端停在「欢迎来到使命召唤ONLINE…请先取一个
代号」页面时，点击输入框、键入任意代号、点「继续」），确认进入大厅后告诉我。

之后我会立即：

1. 把 `runtime/client-1604220/players/config_mp.cfg` 备份为
   `config_mp.cfg.onboarded`；
2. 在 `auto_lobby.py` 里加入"运行前若缺少有效存档则从该备份恢复"的逻辑；
3. 重跑完整流程，验证大厅稳定复现，并把证据归档为 M4.1 的达成依据。

这一步无法用代码替代：提交动作在 Scaleform UI 层，不产生网络请求，
合成输入（SendInput / WM_CHAR）均被拒绝，而绕过其判断会导致崩溃。

#### 如果无法人工介入

备选路线是把 M4.1 的判据改写为「单人可复现启动流程（含一次人工代号）」，
并把已完成的档案持久化（`server319/profile.py`）作为服务端侧成果，
然后直接推进 M4.2 的协议侧工作（`svc21/task5` 帧已就绪并有单测覆盖）。

在客户端无法离开代号页的前提下，M4.2–M4.4 都不具备可达性。

### 15.28 `[0x3306D60]` 是全局静态的字符串表，不是账号对象（2026-10-23 04:1x）

#### 结构实测

`D = [0x3306D60] = 0x80FA044`。这是 **EXE 数据区里的全局静态**，不是堆对象
（地址落在 `0x400000 + 0x40FA044`，与模块基址一致）。转储 96 字节：

```
0x080fa044  68 d5 db 00  00 00 00 00  00 00 00 00  00 00 00 00   <- [D+0x00]=0x00DBD568
0x080fa054  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00   <- 0x081A76E8, 200.0f
0x080fa064  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00
0x080fa074  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00
0x080fa084  00 00 00 00  00 00 00 00  00 00 00 00  70 d5 db 00
0x080fa094  00 00 00 00  06 00 00 00  01 00 00 00  00 00 00 00
```

**`[D+0x0C] = 0x80FA050`，值 0**——正是 `0x6BBF30` 检查的那个字段，
也正是 `fix_firstlogin()` 写入 1 的地址。

`[D+0x00]` 指向 `0x00DBD568`，读出来是：

```
2816    1858    1859    cod4master.activision.com    1860    1861    …
```

即一张**字符串/键值表**（端口号与 master server 域名混排），**不是玩家账号对象**。

#### 由此产生的关键区分

| 操作 | 结果 |
|---|---|
| 写 `[D+0xC] = 1`（`fix_firstlogin`） | **不崩溃**，画面停在代号页 |
| 强行把 `0x6BBF30` 改成 `mov eax,1; ret` | **24 秒后崩溃** |

两者都让 `0x6BBF30` 返回 1，但结局完全不同。差别在于**打桩跳过了函数体**，
而函数体里除了这个判断还有别的工作（返回路径前会经过
`0x6BBF46` 之后的代码，以及 `0x6BBF60` 的 `onboard_character_selected` 设置）。
直接 `ret` 把这些副作用全部跳过，后续阶段就拿到不一致的状态。

**写字段是安全的，打桩是不安全的。** 这一区分纠正了上一轮"写 1 有害"的判断
（§12.36 认为 firstlogin 修复把客户端推离大厅，但那可能是 `fix_fe_loaded`
同时改 `script_state`/`fe_final` 造成的，需要单独验证）。

#### 下一步（明确的分离实验）

依次测试三种配置，确定到底是哪一项导致画面停在代号页：

| 编号 | 补丁 | 内存写入 | 预期 |
|---|---|---|---|
| A | 15 处 | 只写 `[D+0xC]=1` | ？ |
| B | 15 处 | 写 `[D+0xC]=1` + `script_state=1` | ？ |
| C | 15 处 | 写 `[D+0xC]=1` + `script_state=1` + `fe_final=1` | 已知停在代号页 |

若 A 能进大厅，则说明 `fix_fe_loaded` 是多余的且有害，应从 `auto_lobby.py` 移除。
这一实验成本很低（每次约 2 分钟），优先做 A。

#### 新增工具

`tools/show_patches.py`（显示补丁应用状态）与 `tools/show_lsg.py`
（精简 LSG 事件视图）已加入工具集，后续所有实验都用它们核对。

### 15.30 ★★★ 实验 C：`[lobby+0x1F4]=2` 是触发 `svc71/task9` 的开关（2026-10-23 05:1x）

#### 这是 25 轮来第一次让客户端主动发出 `svc71/task9`

配置：15 处补丁 + 写 `[D+0xC]=1` + 写 `FE_state=3` + 写 `[lobby+0x1F4]=2`。

LSG 记录：

```
18:58:58 client_frame_verified counter=5 inner=0x86 payload_len=8
18:58:58 task_request service=71 task=9 bytes=8          ★ 第一次自发出现
18:58:58 candidate_task_reply svc71/task9 bdMatchMaking entry 127.0.0.1:8466
18:58:58 raw_session_end EOFError:peer_closed
```

`counts` 从之前的 `client_frame: 1` 变成 **`client_frame: 5`**、`task_request: 5`。

**对比**（同一 15 补丁集、同样的 auth/LSG 服务）：

| 配置 | client_frame 数 | 是否发 71/9 |
|---|---|---|
| 只强推 G1=2（§12.38 基线） | 1 | 否（等 90 s） |
| 写 `[D+0xC]=1`（实验 A） | 1 | 否 |
| 写 `[D+0xC]=1` + `FE_state=3`（实验 B） | 1 | 否 |
| **再加 `[lobby+0x1F4]=2`（实验 C）** | **5** | **是** |

**结论：`[lobby+0x1F4] == 2` 才是客户端继续发请求的必要条件。**
之前所有"等 39 秒/90 秒仍无 task9"的阴性结果，根因就是这一位一直是 1。

#### 但客户端随后崩溃

写入后约 10 秒进程退出（`no visible CODO window`）。最可能的原因在
`svc71/task9` 的应答：

- 我们回的是 **114 字节的 bdMatchMaking entry**（`candidate_svc71_task9_reply`）；
- **M3 达成大厅那次回的是 `terminal_task_reply error=14`（14 字节）**，
  即"未实现"错误帧，而客户端照样继续往下走（§12.37 已记录它不要求应答正确）。

**也就是说：给出一个"正确的"条目反而让客户端崩溃，给出错误帧却能继续。**
这暗示 114 字节条目的字段格式与客户端期望不符，客户端解析到非法值后崩溃。

#### 下一步（明确且成本很低）

1. 把 `svc71/task9` 的应答改回 **`terminal_unavailable_reply`（error=14）**，
   复跑实验 C。若客户端不再崩溃并继续发 `71/3`，则完全复现 M3 的行为；
2. 之后再逐个字段校准 114 字节条目，使客户端能真正消费服务器条目。

#### 环境变量开关

`lsg_derived.py` 已有 `LSG_T4_MODE`（`zero`/`entry`）控制 `71/4` 的应答形状。
本轮应在同一处增加 `LSG_T9_MODE`（`entry`/`error14`），默认取 `error14`
以复现 M3 基线。

#### 三个中间态的作用（汇总）

| 变量 | 写入值 | 效果 |
|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1` 从 0 前进到 1（实验 A 单独验证） |
| `[0xE59D20]` | 3 | 稳定保持，不被回滚；为 `3→4` 转换做准备 |
| `[lobby+0x1F4]` | 2 | **触发客户端继续发请求**（本次突破） |

三者缺一不可：只写前两个时 `G1=1` 且无 `71/9`；加上第三个才出现 `71/9`。

### 15.31 实验 D：`svc71/task3`、`task7`、`task9` 全部触发（2026-10-23 05:3x）

#### 客户端发出了完整的请求序列

配置：15 补丁 + 三处写入（`[D+0xC]=1`、`FE_state=3`、`[lobby+0x1F4]=2`），
`LSG_T9_MODE=error14`。

```
18:58  client_frame payload_len=8     task_request service=71 task=9
19:01  client_frame payload_len=141   task_request service=71 task=3
19:01  client_frame payload_len=389   task_request service=71 task=7
19:01  client_frame payload_len=8     task_request service=71 task=9
counts: client_frame=5, task_request=5
```

**这是 26 轮来第一次看到 `task3` 和 `task7`**——M3 那次的 `lsg.jsonl` 里
也只有 `task4 / task9 / task3`，而本次多出了 `task7`。

#### 但与 M3 有一处关键差异

| 项目 | M3 那次 | 本次 |
|---|---|---|
| `task9` 应答 | `terminal_task_reply error=14`（14 字节） | 同（`LSG_T9_MODE=error14`） |
| `task3` 应答 | `terminal_task_reply error=14` | `candidate_empty_task_reply`（空成功） |
| `task7` 应答 | 未出现 | `candidate_empty_task_reply` |

即：我们把 `task3`/`task7` 应答成了「空成功」，而 M3 应答的是「未实现错误」。
客户端随后仍然崩溃（写入后约 10 秒）。

#### 这提示下一步非常明确

`lsg_derived.py` 里 `task3`/`task7` 走的是 `candidate_empty_success_reply`
分支。**把这类"未实现"的应答统一改成 `terminal_unavailable_reply`（error=14）**，
与 M3 完全一致，再复跑：

- 若客户端不再崩溃 → 说明"空成功"帧的格式是崩溃原因，而"错误帧"是安全的；
- 若仍在 `task9` 后崩溃 → 说明问题不在应答形状，而在别处（例如 `FE_state=3`
  缺少配套字段）。

无论如何，这次实验已经把"客户端能否主动发请求"这件事彻底解决：
**三处写入是充分条件**。

#### 三处写入的作用已完全确定

| 变量 | 值 | 作用 | 单独验证 |
|---|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1: 0 → 1` | 实验 A |
| `[0xE59D20]` | 3 | 稳定中间态，不回滚 | 实验 B |
| `[lobby+0x1F4]` | 2 | **释放客户端请求**（task3/7/9） | 实验 C/D |

#### 待办

1. 把 `task3`/`task7`/`task11`/`task13` 等未实现分支统一改为 `error=14`；
2. 复跑实验 D，确认是否还崩溃；
3. 若不崩，观察客户端是否最终渲染出房间列表（M4.2 的第一个判据）。

### 15.32 请求序列已完整；剩余问题是应答内容而非触发条件（2026-10-23 06:0x）

#### 实验 E 结果

15 补丁 + 三处写入 + `LSG_T9_MODE=error14` + `LSG_UNIMPL_MODE=error14`：

```
19:04:59 client_frame payload_len=8    task_request service=71 task=9
19:04:59 client_frame payload_len=275  task_request service=71 task=7
19:04:59 client_frame payload_len=141  task_request service=71 task=3
19:04:59 client_frame payload_len=389  task_request service=71 task=7    <- 重试
19:04:59 client_frame payload_len=8    task_request service=71 task=9    <- 重试
counts: client_frame=5, task_request=5
```

**客户端在 `task7` 上重试**（275 B 与 389 B 两次），说明它没有接受
`error=14` 的应答，改换了请求内容再来一次。

#### 与 M3 的差异对照

| 项目 | M3 达成大厅那次 | 本次 |
|---|---|---|
| `task4` | 83 B，被应答 | 同 |
| `task9` | 8 B，`error=14` | 8 B，`error=14` |
| `task3` | **142 B**，`error=14` | **141 B**，`error=14` |
| `task7` | **未出现** | 275 B / 389 B，重试两次 |
| 崩溃时机 | 无（54 秒后正常结束） | 写入后约 10 秒崩溃 |

**`task3` 的请求长度差 1 字节**（142 vs 141），且 `task7` 在 M3 里根本没出现。
这两点说明客户端的**内部状态与我们不同**，因此发出的请求也不同——它并不是
在"走同一条路"，而是在一个略有偏差的状态下探索。

#### 已达成的确定性成果

| 变量 | 值 | 作用 |
|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1: 0 → 1`（实验 A 单独验证） |
| `[0xE59D20]` | 3 | 稳定中间态，不回滚（实验 B） |
| `[lobby+0x1F4]` | 2 | **释放客户端请求**（实验 C/D/E） |

**这三处写入是"客户端愿意继续通信"的充分条件**，26 轮来第一次稳定复现
`task3`/`task7`/`task9` 的请求链。

#### 剩余问题

客户端在收到"未实现"应答后仍会崩溃。可能原因：

1. `task3`(141 B) 与 `task7`(389 B) 的**请求语义**需要真实应答，`error=14`
   只能让它重试一次，之后仍失败；
2. `FE_state=3` 缺少配套字段，客户端在处理应答时解引用到无效内容；
3. `[lobby+0x1F4]=2` 让 pump 进入"已完成"分支，而我们没有提供它期望的后续数据。

#### 新增环境开关

`server319/lsg_derived.py` 现有三个应答形状开关，便于后续对照：

| 环境变量 | 取值 | 作用 |
|---|---|---|
| `LSG_T4_MODE` | `zero` / `entry` | `svc71/task4` 的应答形状 |
| `LSG_T9_MODE` | `error14` / `entry` | `svc71/task9` 的应答形状 |
| `LSG_UNIMPL_MODE` | `error14` / `empty` | `svc71/task3`、`task7` 等未实现服务的应答 |

三者默认均为 M3 基线（`error14`/`error14`），便于复现。

#### 下一步

1. 解码 `task3`（141 B）与 `task7`（389 B）的请求内容——它们都是**加密**的，
   但长度与 M3 的 142 B 只差 1 字节，可用同一套 `parse_client_frame85` 解出
   TLVs，从而知道客户端在要什么；
2. 按解码结果构造真实应答，替换 `error=14`；
3. 观察是否还会崩溃，以及 `ui_state` 能否从 9 变为大厅对应的值。

第 1 条是关键：只要知道客户端在 `task7` 里问什么，就能给出它接受的数据，
而不是继续用错误帧试探。

### 15.33 请求体已捕获，新增密钥转储开关（2026-10-23 06:2x）

#### 请求体本来就有记录

`lsg.jsonl` 的 `client_frame` 事件包含 `body_hex`、`body_len`、`body_sha256`，
所以客户端的加密请求体是可以离线复现的。以一份 130 字节的样本为例：

```
7e000000 ab85 01000000 cf0b57c2 34e7199d 4e525b8a 336825d4 99ce1e1f …
```

`ab85` 是 magic，随后是计数器 1，再往后是加密载荷。要解出 TLV，
必须有当次会话派生的密钥（`LsgKeys` 的 `client_aes`）。

#### 新增 `LSG_DUMP_KEYS`

`server319/lsg_derived.py` 在读取每个客户端帧之前，若 `LSG_DUMP_KEYS=1`
则写一条 `session_keys` 事件，内容为 `LsgKeys` 各字段的十六进制：

```python
if os.environ.get("LSG_DUMP_KEYS") == "1":
    self.evidence.write("session_keys", session, reason="LSG_DUMP_KEYS=1",
                        keys_hex={f.name: getattr(keys, f.name).hex()
                                  for f in dataclasses.fields(keys)
                                  if isinstance(getattr(keys, f.name), (bytes, bytearray))})
```

`LsgKeys` 是 dataclass，字段为 `challenge`、`client_mac`、`server_mac`、
`client_aes`、`server_aes`（用 `dataclasses.fields` 而非 `keys.items()`，
后者在 dataclass 上不存在——这是本轮修掉的一个错误）。

#### 本轮那次运行没有产生任何客户端帧

`runs/20261023-exp-f/lsg.jsonl` 只有 5 条握手事件
（`plaintext_frame`、`gate_reply`、`plaintext_frame2`、`session_derived`、
`token_reply`），**没有 `client_frame`**，即客户端完成握手后没有发 `svc71/task4`。
同目录的 `auth.jsonl` 有正常的 `auth_request` / `auth_response`，
`patch.json` 也有 401 KB 的完整采样记录。

单独前台启动 LSG 服务可以正常监听，`import server319.lsg_derived` 也正常，
说明不是代码错误，而是那次客户端实例的时序问题（握手完成但业务帧未发出）。
前几轮同一配置下 `task4` 都在 6 秒内出现，因此判断为偶发。

#### 下一步

重跑实验 F（三处写入 + `LSG_DUMP_KEYS=1`，等待 60 秒），确认：

1. `client_frame` 是否恢复；
2. `session_keys` 是否写出；
3. 若两者都在，用 `client_aes` 解密 `task3`(141 B) 与 `task7`(389 B) 的
   `body_hex`，解析出客户端究竟在请求什么。

这是目前唯一能把"用错误帧试探"换成"给出真实应答"的路径。

### 15.34 ★★★ 解密客户端请求：`task3`/`task7` 是崩溃日志上报，不是房间请求（2026-10-23 07:0x）

#### 先修掉一个自己造成的 bug

`LSG_DUMP_KEYS` 的第一版把密钥写进 `evidence.write(..., keys_hex=...)`，而
`EvidenceWriter.write` 有字段白名单：

```python
allow = {"body_len", "body_sha256", "reason", "buffered_bytes"}
if set(fields) - allow:
    raise ValueError("evidence field not allowlisted")
```

`keys_hex` 不在白名单，抛出的 `ValueError` **不在** session 的
`except (LsgProtocolError, EOFError, OSError, TimeoutError)` 里，于是整个 handler
崩溃、连接被关闭——客户端因此根本发不出 `svc71/task4`。

这解释了实验 F/G 为什么"握手正常但没有 client_frame"：**是转储代码自己把会话
打断了**，不是客户端时序问题。

修法：改为写 sidecar 文件 `<log>.keys.jsonl`，并用
`try/except Exception` 包住，任何失败都不影响会话。修复后 5 个 client_frame 立即恢复。

#### 解密结果（`tools/decrypt_frames.py`）

用 `LsgKeys.client_aes` 回放 `body_hex`，得到的 TLV 载荷是**纯文本**：

| 帧 | 长度 | 内容 |
|---|---|---|
| #1 | 83 | `nQloP0oCVWR6RDJS` + 一串 `+` + `1C-83-41-CE-8D-EE`（会话/机器标识） |
| #2 | 275 | **`ClientOffline`**`|${TIMESTAMP}|1604220|1234605616436508552|934477427295145000|7|4|11|12|0|…` |
| #3 | 141 | **`UserWarning`**`|${TIMESTAMP_OFFSET(0)}|1604220|…|${CODOID(934477427295145000)}|Add r…` |
| #4 | 389 | **`ClientException`**`|${TIMESTAMP}|1604220|…|${CODOID(…)}||Windows 1…` |
| #5 | 8 | `47 03 09 08 07 00 00 00`（`task9`，空请求） |

#### 这彻底改变了理解

**`svc71/task3` 与 `svc71/task7` 是客户端的日志上报通道**
（`ClientOffline` / `UserWarning` / `ClientException`），**不是房间列表查询**。

含义有三层：

1. **客户端在崩溃过程中上报日志**——`ClientOffline` 说明它已经认为自己掉线了，
   所以这些请求是**结果**而不是**原因**；
2. **不需要为它们构造真实应答**——`error=14` 已经足够（M3 当时也是这么回的），
   它们重试是因为客户端每条日志都会单独发一次，而不是因为应答不被接受；
3. **真正要解决的问题变成了：客户端为什么会进入 `ClientOffline`。**

#### 结论

第 25-26 轮把 `task3/7/9` 的出现当成"客户端开始要数据"是**误判**。
它们只是崩溃前的日志上报。真正的进展是**解密通路打通**——现在可以随时看到
客户端发出的任何请求内容。

#### 下一步

1. **解码帧 #1**（83 字节，`task4` 的请求体）：`nQloP0oCVWR6RDJS` 是会话标识，
   末尾 `1C-83-41-CE-8D-EE` 像是 MAC 地址。这是真正的大厅查询请求，值得细看；
2. **查明 `ClientOffline` 的触发条件**：它是客户端在检测到与 LSG 连接异常时才发
   的，而我们的 LSG 一直正常——所以可能是别的原因（例如 `[lobby+0x1F4]=2` 让
   pump 进入"已完成"分支，而客户端在那条分支上发现数据不一致）。
3. 若确认是 1F4 的副作用，则应放弃强写 2，改用**让 pump 自己成功**的路径。

第 1 条成本最低，先做。

### 15.35 `svc71` 请求的 TLV 结构完全解开（2026-10-23 08:0x）

#### 帧头是 `47 03 <task>`

解密后的载荷以固定三字节开头：

```
0x47   事件标记
0x03   版本标记（固定）
0xNN   task 号
```

实测对应关系：`47 03 04` = task4、`47 03 07` = task7、
`47 03 03` = task3、`47 03 09` = task9。

#### 字段编码

| 标记 | 含义 | 说明 |
|---|---|---|
| `0x13` | **带长度前缀的字节串**（容器） | 后跟 `0x08` + u32 长度 + 内容 |
| `0x08` | u32 | 直接跟 4 字节 |
| `0x10` | 以 `0x10`+长度+内容 的纯字符串 | 见 task3/7 的日志文本 |
| `0x03` | u8 | |

#### `task4`（ListDedicatedServer）的完整参数

```
47 03 04                     EVENT ver=3 task=4
13 08 10 00 00 00            [u32 长度 16]
   6e 51 6c 6f 50 30 6f 43    "nQloP0oCVWR6RDJS"   <- 客户端会话标识
   56 57 52 36 52 44 4a 53
13 08 10 00 00 00            [u32 长度 16]
   2b x16                     "++++++++++++++++"    <- 占位/分隔串
08 97 cb e6 01               u32 = 0x01E6CB97       <- 某个序号或时间
13 08 00 00 00 00            [空串]
13 08 00 00 00 00            [空串]
10 31 43 2d 38 33 2d ...     "1C-83-41-CE-8D-EE"    <- 机器/网卡标识
```

即 task4 携带：**会话 ID + 占位串 + 一个 u32 + 两个空串 + 一个 MAC 风格标识**。
没有任何与房间列表相关的过滤条件——它是"列出所有可用服务器"，这与
`ListDedicatedServer` 的语义一致。

#### `task9` 是空请求

```
47 03 09 08 07 00 00 00      EVENT task=9, u32 = 7
```

只有一个 u32 参数（值为 7），符合"按 ID 查询会话"的形态。

#### 与 M3 对照

M3 那次 `task4` 请求 83 字节，本次也是 83 字节，`task9` 都是 8 字节。
**请求侧完全一致**，说明客户端发出的东西没有问题。

差异只在请求**之后**的行为：M3 的客户端继续跑 54 秒后正常结束，我们的客户端
在 `task9` 之后崩溃并上报 `ClientOffline`/`ClientException`。

#### 结论

请求侧已完全解析，且与 M3 逐字节同构。问题**确定在应答侧或客户端内部状态**：

1. 应答侧：`task4` 的应答是 4 字节的 `u32 0`（`LSG_T4_MODE=zero`），
   而 M3 也是这么回的，所以应答形状大概率不是原因；
2. 客户端状态：`[lobby+0x1F4]=2` 是我们强写的，pump 那条分支需要的后续数据
   并未准备好，客户端在 `task9` 之后检查时发现不一致 → 判定离线 → 上报日志 → 退出。

#### 下一步

按上一条推断，应当**放弃强写 `[lobby+0x1F4]=2`**，改为验证：
仅写 `[D+0xC]=1` + `FE_state=3`（实验 B 的配置）时，客户端能存活多久、
`ui_state` 会停在什么值。若它能稳定存活而不崩，则说明 1F4 的强写是崩溃源，
后续应转向让 pump 自己成功（即补上它期望的数据），而不是继续强写。

### 15.36 ★★★ 确认：强写 `[lobby+0x1F4]=2` 是崩溃源（2026-10-23 08:2x）

#### 对照实验 I（不写 1F4）

配置：15 补丁 + 只写 `[D+0xC]=1` 与 `FE_state=3`（**不写** `[lobby+0x1F4]`）。

```
写入后：G1=0  FE=3
t=10s   dw=5 ui=9 G1=0 gate=0 FE=3 1F4=1
t=20s   dw=5 ui=9 G1=1 gate=0 FE=3 1F4=1     <- FE 梯自发前进
t=30s…150s  同 t=20s，全程存活
```

**客户端稳定存活 150 秒，无崩溃、无 `ClientOffline` 上报。**
LSG 会话只有 `task4` 一次请求与 4 次保活，`raw_session_end` 是服务端主动关闭。

#### 与写 1F4 的对照

| 配置 | 存活 | G1 | gate | FE | 请求数 |
|---|---|---|---|---|---|
| `[D+0xC]=1` + `FE_state=3`（不写 1F4） | **150 s+** | 1 | 0 | 3 | 1（仅 task4） |
| 再加 `[lobby+0x1F4]=2` | **约 10 s 后崩** | 1 | 0 | 3 | 5（含日志上报） |

**结论：`[lobby+0x1F4]=2` 是崩溃的直接原因。**
第 26 轮把"5 个 client_frame 出现"当作进展是误判——那 5 个里有 3 个是崩溃日志。

#### 为什么写 2 会崩

按 §12.38/§12.47 的推断：`0x6217D0`（`FE_state: 3 → 4`）与
`0xBAE1AC`（pump 写 2）都在"整条链已完成"的分支上。我们只把最后一个字节
置成 2，前面该有的数据（容器内容、pump 的内部标记）全都没有，于是客户端在
`task9` 之后校验失败、判定离线、上报 `ClientOffline`/`ClientException` 并退出。

#### 当前可稳定复现的状态

```
dw = 5      （登录完成）
ui_state = 9（训练官/取代号页面）
G1 = 1      （FE 梯第一级，自发达到）
gate = 0
FE_state = 3（我们置的，稳定不回滚）
[lobby+0x1F4] = 1（pump 每帧写回，未强改）
```

**客户端可以永远停在这里，不会崩。** 这是一个干净的、可反复使用的基线。

#### 这意味着什么

要进大厅必须让 `FE_state` 到 4 或 6，而那需要 `[lobby+0x1F4]=2`，而强写 2 必崩。
所以**只能让 pump 自己把 1F4 写成 2**。

pump 里写 2 的两处（`0xBAE1AC`、`0xBAE587`）都是**无条件**的——只要执行流到达
就写。挡住执行流的是 `0xBAF040`（它要 `0xBBA760(key=0, 1288B)` 在容器里查到内容，
而容器每帧新建且为空）。

因此下一步的唯一正确方向是：**找出容器里那份 1288 字节数据应该由什么填充**。
它是 pump 自己新建的容器，填充者只能是 pump 内更早的代码——也就是说
`0xBBAD40` 之前还有一步我们没跟到。

#### 下一步

1. 反汇编 `0xBAE6C0` 之前（即 `0xBAE5A0`…`0xBAE6C0` 这段），看容器新建之前
   是否本该从别处拷入数据；
2. 特别关注 `[lobby+0x1FC]` 的**旧**容器（`0xBAE6C2` 先取它、销毁它）——
   如果它本来有内容，说明上一轮的填充成功了，问题在"为什么这一轮重建后丢了"。
3. 若确认容器的数据来自网络应答，则要改 `svc71/task4` 的应答形状：
   现在回的是 4 字节 `u32 0`，也许应当回一个带服务器条目的列表。

### 15.37 服务器数组是**非空**的；pump 有两条互斥路径（2026-10-23 09:0x）

#### 136 字节数据的真实来源

`0xBAE5DB` 起是一段紧凑循环：

```asm
0xBAE5DB  mov ecx, [ebx + 0x4D6C]     ; 当前索引
0xBAE5E1  inc ecx
0xBAE5E2  cmp ecx, [ebx + 0x4D68]     ; 与容量比较
0xBAE5E8  jae 0xBAE781                ; 超限 -> 走失败路径
0xBAE5F3  inc dword ptr [ebx + 0x4D6C]
0xBAE5F9  mov eax, [ebx + 0x4D6C]
0xBAE5FF  imul eax, eax, 0x88         ; ★ 每条 136 字节
0xBAE605  add eax, [ebx + 0x4D60]     ; ★ 数组基址
0xBAE60B  lea ecx, [ebp - 0x658]
0xBAE611  push eax
0xBAE612  call 0xB753C0               ; 复制该条目
```

**`0x88 = 136` 正是之前追了很久的那个"136 字节"**——它不是加密密钥、不是
服务器地址块，而是这个数组里的一条记录。

#### 数组实测非空

```
lobby = 0x37C988A0
+0x4D60 base = 0x37C8CF08
+0x4D64      = 1
+0x4D68 cap  = 1        <- 容量 1
+0x4D6C idx  = 0
首条 136 字节 = 7f 00 00 01 00 00 …   <- 127.0.0.1
```

**`svc71/task4` 的应答被接受了**——数组里确实有一条 `127.0.0.1` 的服务器记录。
所以"应答形状不对"这个怀疑可以排除。

#### pump 的两条互斥路径

| 路径 | 位置 | 写入 `[lobby+0x1F4]` |
|---|---|---|
| 失败 | `0xBAE781` → `0xBAE790` 循环 → `0xBAE7AA` | **1** |
| 成功 | `0xBAE180` → `0xBAE1A7` `call 0xC699B0` → `0xBAE1AC` | **2** |

`0xBAE7AA` 那条是**无条件**写 1：`jbe 0xBAE7AA` 在 `[ebx+0x18] <= 0` 时直接跳过去写，
否则先遍历 `[ebx+0x18]` 个元素再**同样**走到 `0xBAE7AA` 写 1。

而 `0xBAE1AC` 写 2 也是无条件的——只要执行流到达就写。

**所以我们走的是失败路径，需要让执行流改走 `0xBAE180` 那条。**

#### 尚未确定的关键点

`0xBAE180` 之前是这段（此前 dump 过，含对齐错位）：

```asm
0xBAE183  mov esi, eax
0xBAE18D  mov edx, [edx + 0xC]
0xBAE190  push eax
0xBAE191  call edx                    ; 虚调用
0xBAE193  mov ecx, [ebx + 0x1F0]      ; 大厅连接对象（实测非空）
0xBAE199  lea eax, [ebx + 0x184]
0xBAE19F  push eax
0xBAE1A0  push ecx
0xBAE1A1  lea ecx, [ebx + 0x1A0]
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword ptr [ebx + 0x1F4], 2
```

要到达这里必须先满足进入 `0xBAE180` 分支的条件，而该条件尚未定位
（`0xBAE180` 处字节错位，反汇编要从更早的边界开始）。

#### 下一步

从 `0xBAE100` 之前的正确指令边界往后解，找出跳入 `0xBAE180` 的分支条件；
重点关注 `0xBAE140`…`0xBAE180` 之间的比较指令。若该条件依赖网络数据，
则要补对应的服务应答；若依赖客户端内部状态，则要找到写该状态的地方。

### 15.38 `0xBAE182` 在 `0xBAF040` 成败两条路上都会被到达（2026-10-23 09:2x）

#### 成功分支的完整形态

从 `0xBAE0F0`（干净边界）反汇编：

```asm
0xBAE0ED  call 0xBAF040             ; 判定
0xBAE0F2  test al, al
0xBAE0F4  je 0xBAE10D               ; 失败 -> 0xBAE10D
0xBAE0F6  lea edx, [ebp - 0x5d0]    ; 成功：准备数据
0xBAE0FC  push edx
0xBAE0FD  lea ecx, [ebp - 0x6e0]
0xBAE103  call 0xB75440
0xBAE108  call 0xBA4B20
0xBAE10D  push 0xa8                 ; ★ 两条路在此汇合（分配 168 字节）
0xBAE112  call 0xB742C0
0xBAE124  test eax, eax
0xBAE126  je 0xBAE148
0xBAE128  mov ecx, [ebx + 0xb4]
0xBAE12F  lea edx, [ebp - 0x5d0]
0xBAE13F  call 0xB75060             ; 构造对象
0xBAE144  mov esi, eax
0xBAE146  jmp 0xBAE14A
0xBAE148  xor esi, esi
0xBAE14A  mov [ebp - 0x99c], esi
0xBAE150  test esi, esi             ; 只是判断是否要释放
0xBAE152  je 0xBAE15E
0xBAE154  lea edx, [esi + 4]
...
0xBAE176  je 0xBAE182               ; 释放后跳到 0xBAE182
0xBAE182  mov ecx, [ebx + 0x1f0]    ; ★ 大厅连接对象（实测 0x36c9ec60 非空）
0xBAE193  mov ecx, [ebx + 0x1f0]
0xBAE199  lea eax, [ebx + 0x184]
0xBAE1A1  lea ecx, [ebx + 0x1a0]
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword ptr [ebx + 0x1f4], 2    ; ★ 写 2
```

**关键结论：`0xBAE182` 是成功分支的必经点，而它由 `0xBAE10D` 无条件到达，
`0xBAE10D` 又是 `0xBAF040` 失败时的跳转目标。** 也就是说 `0xBAF040` 的成败
**不影响**是否会写 2。

#### 这意味着什么

之前（§12.24/§12.31）认为「`0xBAF040` 失败 → 写 1」，**这个因果链是错的**。
写 1 的 `0xBAE74E` / `0xBAE766` 一定在**另一条**入口分支上，而不是这条线性路径。

`0xBAD800` 是一个约 4 KB 的大函数，有多处 `jmp 0xBAE7xx` 汇聚到写 1 的尾部
（`0xBAE7AA` 也写 1），说明它是**多分支状态机**，每条分支对应一种事件。
我们当前走的既不是 `0xBAE182`（写 2）也不是 `0xBAE7AA`（写 1）——需要先确定
实际执行的是哪条。

#### 下一步（改为观测而非推理）

在 `0xBAE1AC`（写 2）与 `0xBAE74E` / `0xBAE7AA`（写 1）这三处各放一个
**只记录不干预**的探针（写一个字节到约定地址），运行一次即可知道 pump 实际
走的是哪条分支。这比继续静态推理更快，也避免再次基于错误前提走远。

工具上可以复用 `ui_activate.py` 的 trampoline 框架：把目标地址的指令替换成
`jmp cave`，在 cave 里记录后执行原指令再跳回。

#### 已排除的假设（累计）

| 假设 | 结论 |
|---|---|
| 136 字节是加密密钥 | 否，是数组记录（§12.49） |
| 136 字节是服务器地址块 | 否，同上 |
| `svc71/task4` 应答形状不对 | 否，数组已存入 127.0.0.1 条目 |
| `0xBAF040` 失败导致写 1 | **否，两条路都到 0xBAE182** |
| 强写 `[lobby+0x1F4]=2` 能推进 | 否，它是崩溃源（§12.48） |

### 15.39 ★★★ pump 失败的确切原因：两个状态字段各差 1（2026-10-23 09:4x）

#### 用跳转映射代替推理

`tools/jump_map.py` 扫描 `0xBAD800` 函数体内所有跳转，得到的目标来源是：

| 目标 | 来源 |
|---|---|
| `0xBAE1AC`（写 2） | **无直接跳转** → 顺序执行（从 `0xBAE182` 直落） |
| `0xBAE781`（失败头） | `0xBAE5E8 jae`（容量比较） |
| `0xBAE7AA`（写 1） | `0xBAE786 jbe` |
| `0xBAE5DB`（遍历循环） | `0xBAE312 jne`、`0xBAE326 jne` |

**关键**：`0xBAE1AC` 没有任何跳转指向它，而唯一通往它的路径被
`0xBAE312` / `0xBAE326` 两个 `jne` 挡住。实测 `[lobby+0x1F4]` 恒为 1
（从不出现 2），这本身就证明 `0xBAE1AC` **从未执行**——与映射结果一致。

#### 被挡住的两个条件

```asm
0xBAE2DD  cmp byte ptr [ebp - 0x988], 0    ; 标志 1
0xBAE2E4  je 0xBAE7B4                       ; 0 -> 直接跳结尾（连 1 都不写）
0xBAE2EA  cmp byte ptr [ebp - 0x989], 0    ; 标志 2
0xBAE2F1  je 0xBAE7B4
0xBAE2F7  cmp byte ptr [ebp - 0x986], 0    ; 标志 3
0xBAE2FE  je 0xBAE7B4

0xBAE304  mov ecx, [ebx + 0x1f8]
0xBAE30A  call 0xBBA1E0                     ; = [obj1 + 0x120]
0xBAE30F  cmp eax, 2
0xBAE312  jne 0xBAE5DB                      ; ★ 不等于 2 -> 遍历后写 1

0xBAE318  mov ecx, [ebx + 0x1fc]
0xBAE31E  call 0xBBA750                     ; = [obj2 + 0x1A0]
0xBAE323  cmp eax, 4
0xBAE326  jne 0xBAE5DB                      ; ★ 不等于 4 -> 遍历后写 1

0xBAE32C  …                                 ; 成功路径
```

两个 getter 都只有一条指令：

```asm
0xBBA1E0  mov eax, dword ptr [ecx + 0x120]   ; ret
0xBBA750  mov eax, dword ptr [ecx + 0x1a0]   ; ret
```

#### 实测：两个值各差 1

```
lobby = 0x36BEEC50
obj1 = [lobby+0x1F8] = 0x38004F48
    [obj1 + 0x120] = 3     需要 2      <- 差 1
obj2 = [lobby+0x1FC] = 0x380050C0
    [obj2 + 0x1A0] = 5     需要 4      <- 差 1
[lobby+0x1F4] = 1
```

**两个判定条件都只差 1**。这不是"数据缺失"，而是**状态尚处于"进行中"
（3 / 5）而未到"完成"（2 / 4）**。

#### 这两个字段的含义推断

`obj2` 就是 `0xBAE810` 构造的那个 440 字节容器（`[lobby+0x1FC]`），而
`0xBAE810` 会把 `+0x1A0` 初始化为 **0**（§12.32 已确认）。现在它是 **5**，
说明它被某段代码推进过：`0 → … → 5`，而 pump 期望 **4**。

同理 `obj1`（`[lobby+0x1F8]`）的 `+0x120` 从初始值被推到 **3**，pump 期望 **2**。
两个对象各自是一个小状态机，**它们都还差最后一步**。

#### 为什么只差一步

`0xBAE2DD` 那三个 `cmp byte [ebp-0x988/0x989/0x986], 0` 很可能是**超时/重试
计数**：本轮尚未满足时，被检查的三个标志中有一个为 0，于是直接跳到
`0xBAE7B4`（跳过写 1）；等标志都齐了才进入 `0xBAE304` 的状态比较。也就是说
**这段代码本身在等下一轮**，而下一轮里 `obj1/obj2` 的状态却没有继续推进。

#### 下一步（方向明确）

1. 找 `[obj2+0x1A0]` 的写者：在 `0xBBA*` 区搜索 `mov [reg+0x1A0], imm` 与
   `mov dword [ecx+0x1a0], r`，确定 5 是怎么写上的、以及谁该把它写成 4；
2. 同样找 `[obj1+0x120]` 的写者；
3. 若这两处推进依赖某个服务应答，则补齐该应答；若依赖定时器，则需延长观察
   窗口（此前最长只观察到 150 秒）。

第 1 条最直接，且这两个对象是容器类，写者应当集中在 `0xBBA` 段内。

### 15.40 两个状态字段的写入点候选（2026-10-23 10:1x）

#### 已确认的确定性写入

`0xBBAD40` 内部就有对 `+0x1A0` 的写入：

```asm
0xBBAD95  mov dword ptr [ebx + 0x1a0], 1     ; 标记"已处理"
```

而 `0xBBA810`（容器构造）会把它清 0：

```asm
0xBBA871  mov dword ptr [esi + 0x1a0], 0
```

所以 `obj2` 的 `+0x1A0` 至少经历过 `0 → 1`。**实测当前是 5**，说明还有别的推进者。

#### 全局扫描结果

对 `0x400000`–`0x10000000` 全区间扫描 `mov dword [reg+0x1A0], r32`
（`89 /r` 带 disp32）与 `mov dword [reg+0x120], r32`：

```
mov [+1A0], r  modrm 0x81 (ecx): 0x848BD4, 0x85C592, 0xAD16B3
mov [+1A0], r  modrm 0x82 (edx): 0x85C993
mov [+1A0], r  modrm 0x83 (ebx): 0x8461D7? -> 0x461D7C
mov [+1A0], r  modrm 0x86 (esi): 0x4B4263, 0x4B5F19, 0x4B60DF, 0x4DA033, 0x4EBE0B
mov [+120], r  modrm 0x81 (ecx): 0x48F357, 0x8BAAD3
mov [+120], r  modrm 0x83 (ebx): 0x461BF8, 0x6CEE82, 0xA67874, 0xA67C04, 0xBB76BB
mov [+120], r  modrm 0x86 (esi): 0x6CF3E9, 0x9E31B4, 0xA654C9, 0xAB4AB1, 0xABF2B1
```

这些是**所有**带同样位移的写入点，绝大多数属于无关类（同一个偏移量在很多
结构里都出现）。**仅凭偏移无法确定哪一个作用于我们的两个对象**——这正是
前面几轮反复出错的原因。

#### 结论：静态扫描到此为止

继续按偏移搜索只会得到一堆无关候选。要确定真正的推进者，必须**动态定位**：

1. 在目标对象上设置**硬件写断点**（`Dr0`–`Dr3` + `Dr7`），地址取
   `obj2+0x1A0` 与 `obj1+0x120`，命中时读取 `Eip` 即得写入指令；
2. 或者用 `VirtualProtect` + 单步陷阱逐个排除候选点。

两者都需要在当前进程里接管调试寄存器或改页属性，属于**进程内调试**范畴，
比之前的只读采样复杂一档，但这是唯一能确定性回答"谁把它写成 5"的方法。

#### 当前的确定事实（可直接用作断言）

| 事实 | 值 | 来源 |
|---|---|---|
| `[lobby+0x1F4]` | 恒为 1 | 200 Hz × 5 s 采样，921 次全 1 |
| `0xBAE1AC`（写 2） | 从未执行 | `1F4` 从不出现 2，且无跳转指向它 |
| `obj1 = [lobby+0x1F8]` | `+0x120` = **3**（需 2） | 实测 |
| `obj2 = [lobby+0x1FC]` | `+0x1A0` = **5**（需 4） | 实测 |
| `0xBAE810` 初始化 | `+0x1A0` = 0 | 反汇编 |
| `0xBBAD40` 成功时 | `+0x1A0` = 1 | 反汇编 |

#### 下一步

用硬件写断点定位 `obj2+0x1A0` 的写入指令。若确认它由某个服务应答驱动，
则补齐应答；若由定时器驱动，则需要更长的观察窗口。

### 15.41 ★★★ `[obj2+0x1A0] = 5` 是 `0xBBAD40` 自己的失败码（2026-10-23 10:4x）

#### 状态机全貌

`obj2`（即 `[lobby+0x1FC]` 那个 440 字节容器）的 `+0x1A0` 字段是一台小状态机，
所有写入点都在 `0xBBA` 段，已全部定位：

| 写入值 | 地址 | 语义 |
|---|---|---|
| **0** | `0xBBA871`（构造） | 初始 |
| **1** | `0xBBAD95` | `0xBBAD40` **成功**登记 |
| **4** | `0xBBAD10`、`0xBBA951`、`0xBBA97D`、`0xBBA9F5` | **完成** |
| **5** | `0xBBAAAC`、`0xBBADB0`、**`0xBBADCD`**、`0xBBAC3E`、`0xBBACF4` | **失败** |

关键的一条：`0xBBADCD` 正是 `0xBBAD40` 内部的失败分支。回看该函数：

```asm
0xBBAD86  call 0xBBA8A0
0xBBAD8B  cmp al, 1
0xBBAD8D  jne 0xBBADCD          ; 失败 -> 0xBBADCD
0xBBAD8F  lea ecx, [ebx + 0x1a8]
0xBBAD95  mov dword ptr [ebx + 0x1a0], 1     ; 成功
...
0xBBADCD  mov dword ptr [ebx + 0x1a0], 5     ; ★ 失败
```

#### 完整因果链（终于闭合）

```
pump 0xBAD800
  └─ 0xBBAD40 登记服务器条目
       ├─ 成功 -> [+0x1A0] = 1
       └─ 失败 -> [+0x1A0] = 5      ← 我们在这里
  └─ pump 检查 [+0x1A0] == 4
       5 != 4  ->  jne 0xBAE5DB（遍历）-> 0xBAE781 -> 写 [lobby+0x1F4] = 1
```

而 `0xBBAD40` 失败的根源，就是 §12.32/§12.39 追过的那条：
`0xBBA8A0` → `0xBBA760(this, key=0, 1288 字节)` 在**每帧新建的空容器**里查不到数据。

#### `obj1` 同理

`[obj1+0x120]` 的写入点：

| 值 | 地址 |
|---|---|
| **2**（目标） | `0xBBA569` |
| **3**（当前） | `0xBBA62B` |

`0xBBA62B` 与 `0xBBA569` 相隔 0xC2 字节，属于同一函数的不同分支——
2 是"完成"，3 是另一种中间/失败态。当前是 3，同样未达目标。

#### 这终结了"差 1"的解释

§12.51 观察到"两个字段各差 1"，当时只能描述现象。现在可以确定：

- `obj2+0x1A0`：`5` 是**显式的失败码**，不是"进行中"；
- `obj1+0x120`：`3` 是另一条分支的落点，同样不是"进行中"。

**两者都是失败态**，因此 pump 每帧走到 `jne` 分支是必然的，不是时序问题。

#### 唯一剩下的问题

`0xBBAD40` 为什么失败 → `0xBBA760(key=0, 1288B)` 为什么查不到。

这已追到 §12.30/§12.32 的结论：容器每帧新建且为空，填充它的代码在
`0xBBAD40` 内部（`0xBBAD6B rep movsd` 把 136 字节从局部拷到 `[容器+4]`），
但拷贝的目标是 `+4`，而 `0xBBA760` 查的是 key=0 的 1288 字节记录——
**136 ≠ 1288**。

#### 新的、具体的猜测

`0xBBA760(this, 0, out)` 期望 **1288 字节**，而 `0xBBAD40` 只准备 **136 字节**。
两者相差 **9.47 倍**。若 `0xBBA760` 实际是「把容器内容序列化到 out」而非
「查询」，那么 1288 可能是**最大容量**而非精确长度要求。

这一点值得单独验证：读 `0xBBA760` 里 `0xBC1C20` 返回后对长度的**具体检查方式**
（是 `==` 还是 `<=`）。若为 `<=`，则 136 字节也许足够，失败原因就另在别处。

### 15.42 容器查找的精确条件：类型 `0x14`、key `0`、长度 1288（2026-10-23 11:1x）

#### 长度检查是严格相等

回看 `0xBBA760` 在 `0xBC1C20` 返回之后的判断：

```asm
0xBBA7D2  test eax, eax
0xBBA7D4  jle 0xBBA7F3                 ; 读到 0 或负 -> 失败
0xBBA7D6  cmp eax, [ebp - 0x510]       ; 返回值 vs 记录长度
0xBBA7DC  jne 0xBBA7F3                 ; ★ 不相等 -> 失败
```

**是 `jne`（严格相等），不是 `<=`。** 所以 §12.53 提出的"也许 136 字节就够"
不成立——必须恰好是记录声明的长度，而查询时给的是 `push 0x508`（1288）。

#### 查询条件的构造

```asm
0xBC1C00  push ebp; mov ebp, esp
0xBC1C03  mov edx, [ebp + 8]           ; 参数 = key（调用方传 0）
0xBC1C06  mov eax, ecx                 ; 返回值 = 查询对象
0xBC1C08  mov ecx, 2
0xBC1C0D  mov byte ptr [eax], 0x14     ; ★ 类型标记 0x14
0xBC1C10  mov word ptr [eax + 2], cx   ; ★ 固定值 2
0xBC1C14  mov dword ptr [eax + 4], edx ; ★ key
0xBC1C18  ret 4
```

即查询对象是 **{类型 0x14, 子类型 2, key 0}**，交给 `0xBC1C20` → `0xB783E0` 做实际查找。

#### `0xBBAD40` 不构造这条记录

它的全部动作是：

1. `0xBBAD58` 把参数 1（`lobby[0xC]`，实测非空指针）存进 `[ebx]`；
2. `0xBBAD6B` `mov ecx, 0x22` + `rep movsd`——从局部复制 **136 字节**到 `[ebx+4]`；
3. `0xBBAD72` 把参数 3、4 存到 `[ebx+0x1B0]`；
4. `0xBBAD7D` 调 `0xBBAF00`——**该函数只做范围检查与浮点比较**（`cmp eax,0xA`、
   `cmp eax,2`、`fcomp`），**完全不写容器**；
5. `0xBBAD86` 调 `0xBBA8A0` 去查 **key=0 的 1288 字节**——查不到，返回 0；
6. `0xBBADCD` 写 `[+0x1A0] = 5`（失败码）。

**第 2 步写入 136 字节，第 5 步却要求 1288 字节，两者自相矛盾。**
这说明 `0xBBAD40` 在**当前调用方式**下本来就不该成功——它可能是"旧路径"，
真正的填充发生在别处，而 pump 现在走的是这条旧路径。

#### 另一个可能：`0xBBAD40` 的调用参数不对

`0xBAE735` 调用它时传的是：

```
[ebp+8]  = lobby[0xC]        （接口对象，非空）
[ebp+0xC] = &[ebp-0x658]     （局部缓冲）
[ebp+0x10], [ebp+0x14] = 5 和一个浮点常量
```

而 `0xBBAD40` 用 `[ebp+0xC]` 作为 `rep movsd` 的源，只拷 136 字节。
若正确用法应当由调用方先把 1288 字节准备好，那么问题就在调用方
（`0xBAE6C0`–`0xBAE750` 那段的准备逻辑），而不是被调方。

#### 结论与下一步

容器查找需要一条 **{类型 0x14, 子类型 2, key 0, 长度 1288}** 的记录，而当前
代码路径只准备 136 字节。两种解释：

1. **调用方准备不足**：`0xBAE6C0` 附近应当把 1288 字节准备好，但只给了 136；
2. **走的不是这条路**：`0xBBAD40` 是历史遗留，真正的登记在别处。

验证方式很直接：在 `0xBBAD40` 入口读 `[ebp+0xC]` 指向的缓冲，看它后面
1152 字节（1288−136）是什么内容——若全是 0 或垃圾，说明调用方确实没准备；
若像有效数据，说明拷贝长度写死错了。

这是本轮之后最小的一步，且能直接区分两种解释。

### 15.43 采样工具本身有 bug——「pump 不在跑」的结论**不成立**（2026-10-23 11:4x）

#### 先说结论

本轮想验证 pump 是否每帧执行，写了 `tools/catch_pump_frame.py` 抓线程上下文，
结果 **0 命中**。但进一步检查发现**是工具错了**，不是 pump 不在跑：

```
CONTEXT size = 204 (expect 716)
```

我定义的 `CONTEXT` 结构只有 **204 字节**，而 Windows x86 的 `CONTEXT` 是 **716 字节**。
`GetThreadContext` 虽然返回成功（20/20），但**只填了前 204 字节**，`Eip`
读到的位置因此是错的——永远匹配不上任何函数地址。

**所以"25 秒内 pump/FE 梯/0xBBAD40 全部 0 采样"这个观测无效，不能据此
推断 pump 没有执行。**

#### 尝试修复时遇到的第二个问题

改用 1024 字节原始 buffer + `struct.pack_into("<I", buf, 0, 0x00010007)`
（`CONTEXT_FULL`）后，`GetThreadContext` **全部返回失败**——连之前"成功"的
那个版本也不成立，说明 204 字节结构下的"成功"其实是未定义行为。

正确的做法需要完整的 `CONTEXT` 定义（含 `FLOATING_SAVE_AREA` 与
`ExtendedRegisters[512]`），或者直接用 `ctypes` 按 Win32 头文件声明。
本轮**未完成**该修复。

#### 已知的候选偏移（待验证）

按 x86 `CONTEXT` 布局推算，`Eip` 应在偏移 **188** 附近（`ContextFlags` 4 +
`Dr0-Dr7` 28 + `FloatSave` 112 + `SegGs-SegDs` 16 + `Edi-Eax` 32 + `Ebp` 4 =
196，若 `Dr` 区或 `FloatSave` 有一处差 8 则为 188）。需要用正确结构实测确认，
不能靠推算。

#### 这修正了什么

§12.48 / §12.51 / §12.53 里关于"pump 每帧执行、每帧写 1"的表述，
**其证据链并不包含"观测到 pump 在运行"**——它是从"`[lobby+0x1F4]` 恒为 1"
加上"`0xBAE7AA` 写 1"推出的。如果 pump 其实只在启动时跑过少数几次，
那么"每帧失败"的说法也不准确，`0xBBAD40` 失败的时机描述需要相应调整。

**但下列事实不受影响**（它们来自静态反汇编 + 内存读数，与采样工具无关）：

| 事实 | 来源 |
|---|---|
| `[lobby+0x1F4]` 恒为 1 | 200 Hz × 5 s 采样，921 次（读内存，非线程上下文） |
| `obj2+0x1A0` = 5 | 直接读内存 |
| `obj1+0x120` = 3 | 直接读内存 |
| `0xBAE1AC` 写 2 且无跳转指向它 | 静态反汇编 + 跳转映射 |
| `0xBBADCD` 写 5 是 `0xBBAD40` 的失败分支 | 反汇编 + 模式扫描 |
| 容器查找要求 {类型 0x14, 子类型 2, key 0, 长度 1288} | 反汇编 |
| 长度检查是 `jne`（严格相等） | 反汇编 |

#### 下一步

把 `CONTEXT` 定义修正为完整的 716 字节结构，重新验证 pump 的实际执行频率。
这一步必须先做——否则"pump 每帧失败"这个前提一直是未证实的，
后续所有关于时序的推论都缺乏基础。

### 15.44 CONTEXT 结构已修正，但线程上下文读取仍失败（2026-10-23 12:0x）

#### 已修正的部分

`tools/thread_ctx.py` 现在使用**完整的 716 字节** x86 `CONTEXT`：

```
ContextFlags        0
Dr0..Dr3, Dr6, Dr7  4..24
FloatSave          28   （112 字节）
SegGs..SegDs      140..156
Edi..Eax          156..180
Ebp, Eip          180, 184     <- Eip 在 184
SegCs, EFlags     188, 192
Esp, SegSs        196, 200
ExtendedRegisters 204   （512 字节）
总计 716
```

结构大小已由 `assert ctypes.sizeof(CONTEXT) == 716` 保证。

#### 但读取依然失败

```
pid=28100 threads=58 CONTEXT=716B
threads with a code-like Eip: 0/58
```

诊断显示 `OpenThread` 58/58 成功、`GetThreadContext` **58/58 也返回成功**，
但**读出的所有字段都是 0**：

```
ctx ok tid 27640 {'0xb4': '0x0', '0xb8': '0x0', '0xbc': '0x0', '0xc4': '0x0'}
```

#### 根因已定位：位数不匹配

```
python 3.13.14 bits 64
client machine 0x14c (x86, 32 位)
Wow64GetThreadContext 可用: True
```

**当前 Python 是 64 位，客户端是 32 位。** 64 位进程对 WOW64 目标调
`GetThreadContext` 是未定义行为——它返回 TRUE 却什么都不填，这正好解释了
"成功但全 0"。

改用 `Wow64GetThreadContext` 后**仍然 0/58**。可能原因：

1. 目标线程必须先 `SuspendThread`；
2. `OpenThread` 需要用 `Wow64` 兼容的访问权限组合；
3. `Wow64GetThreadContext` 在 64 位宿主上对已运行的 32 位线程有额外限制。

#### 这一系列失败的方法论教训

从第 37 轮开始，我连续两次把**测量工具的问题**误当成**被测对象的行为**：

| 轮次 | 错误工具 | 错误结论 |
|---|---|---|
| 37 | 204 字节 CONTEXT | "pump 不在跑" |
| 38 | 64 位读 32 位 | "pump 不在跑"（修正后） |

两次都是"返回成功但数据为空"，而我没有在**第一次使用工具时就做自检**。
`thread_ctx.py` 现在带有 `SELF-CHECK FAILED` 断言，这正是应该在第 37 轮就做的事。

#### 下一步（三种可选，按成本排序）

1. **加 `SuspendThread`**：在 `OpenThread` 后先 `SuspendThread`，读上下文，
   再 `ResumeThread`。成本最低，先试这个；
2. **改用调试器路径**：`CreateProcess` 带 `DEBUG_ONLY_THIS_PROCESS`，用
   `WaitForDebugEvent` 拿 `CREATE_THREAD_DEBUG_INFO` 的初始上下文，或用
   `DebugActiveProcess` 附加后接收 `EXCEPTION_DEBUG_EVENT`。这条路确定可行，
   但要重写启动流程；
3. **放弃线程采样**：改用纯静态分析 + 已有的内存读数（`[lobby+0x1F4]`、
   `obj1/obj2` 字段），这些数据本身已经足够支撑结论，只是时序描述不确定。

**建议先试 1**，若仍失败则接受方案 3——因为 §12.55 已确认那些静态事实不依赖
采样工具，且"pump 是否每帧运行"对最终目标（进大厅）并非必要条件。

### 15.45 六补丁组合导致崩溃；线程采样路线放弃（2026-10-23 12:4x）

#### 实验：M3 的六补丁 + 写 `[D+0xC]=1`

计划是验证「M3 只用 6 个补丁就进了大厅，也许我们的 15 个里那 9 处 pump 补丁
反而破坏了路径」。做法：只打 M3 记录的 6 处，`dw=5` 后写 `[D+0xC]=1`，
不强推 G1。

结果：

```
wrote patch.json
patch exit=0
TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'   <- [0x3306D60] 为 0
t=10s: EXITED  …… t=120s: EXITED
s1: no visible CODO window

19:47:53 task_request service=71 task=4
19:48:17 raw_session_end ConnectionResetError:[WinError 10054]
```

**客户端在 `task4` 之后约 24 秒崩溃**，`[0x3306D60]` 读到 0（连对象都没建立）。

**结论：9 处 pump 补丁是必需的**，缺了它们客户端撑不到 `dw=5`。
15 补丁的组合应当保留，§12.37 关于"可能那 9 处有害"的猜测可以排除。

#### 线程上下文采样：放弃

`SuspendThread` + `Wow64GetThreadContext` 仍返回 0/59：

```
pid=34344 threads=59 CONTEXT=716B
SELF-CHECK FAILED: no thread produced a sane Eip
```

三条路都试过了（完整 CONTEXT 结构、Wow64 API、SuspendThread），全部失败。
32 位目标 + 64 位宿主的组合比预期难处理。

**按"同一阻断连续 3 轮无进展则换方向"的规则**（第 37、38、39 轮都消耗在这里），
**放弃线程采样**。

好消息是它并非必要：§12.55 已确认下列事实全部来自**静态反汇编 + 直接读内存**，
不依赖采样工具：

| 事实 | 值 |
|---|---|
| `[lobby+0x1F4]` | 恒为 1（921 次采样，读内存） |
| `obj2+0x1A0` | 5（失败码） |
| `obj1+0x120` | 3 |
| `0xBBADCD` 写 5 | `0xBBAD40` 失败分支 |
| 容器要求 {type 0x14, subtype 2, key 0, 1288 B} | 反汇编 |
| 长度检查 `jne`（严格相等） | 反汇编 |

唯一失去的是"pump 执行频率"这一项，而它对"进大厅"不是必要条件。

#### 近三轮的净状态

| 轮次 | 投入 | 产出 |
|---|---|---|
| 37 | 采样工具（204 字节 CONTEXT） | 工具 bug，结论作废 |
| 38 | 采样工具（位数不匹配） | 工具 bug，结论作废 |
| 39 | SuspendThread + 六补丁实验 | 采样放弃；**六补丁崩溃**（有价值） |

三轮只有一个确定结论（九补丁必需），其余是自我纠错。这是效率很低的一段。

#### 下一步：转向可独立验证的产出

按规则换方向。候选：

1. **`server319` 服务能力测试扩充**——把 `svc71/task4`、`task9` 的应答与
   `test_frames.py` 的帧契约连起来，形成回归保护；
2. **`LONG-RUN-GOAL.md` / `MILESTONES.md` 重写 M4 判据**——把「必须先人工完成
   代号」作为显式前提写进去，并给出"若无法人工介入"的替代验收标准；
3. **`SOLUTION-100-111.md` 增补**——把第 12.36–12.57 节的机制发现（`0xBAD800`
   状态机全图、容器查找契约、`[D+0xC]` 与 FE 梯的关系）整理成可供他人复用的
   技术说明。

第 2 条最必要——当前 M4 判据与实际可达性脱节，文档却仍按"可自动完成"呈现。

### 15.46 服务端契约测试扩到 40 项；过程中修掉两个真 bug（2026-10-23 13:3x）

#### 新增 `tools/test_contracts.py`（21 项）

覆盖 `lsg_derived` 的每一个应答构造器与 `profile` 的两个编码器：

| 组 | 断言 |
|---|---|
| `candidate_svc71_task4_reply` | 事务号被携带；比条目短（是空成功而非列表） |
| `candidate_svc71_task9_reply` | 以 `make_server_entry` 结尾；长度 = 条目 + 26；端口同时出现在两处 |
| `terminal_unavailable_reply` | **恰好 14 字节**（M3 用它应答 task9 且客户端接受）；编码 `error=14`；事务号在前 |
| `candidate_empty_success_reply` | 携带 task id；不同 task 产生不同字节 |
| `ProfileStore.playerdata_bytes` | 24 字节；字段顺序 level/prestige/gp/cp/ents/flags 与 `bdsvc319` 一致 |
| `ProfileStore.balance_bytes` | 5 字节；首字节是货币号；数值取自 wallet |
| `ProfileStore` 持久化 | 写盘后重载一致；二次 `get_or_create` 复用同一条记录（`created` 不变） |
| `_typed_*` 编解码 | 四个 tag 互不相同；`u64` 9 字节；字符串 NUL 结尾；往返一致 |

#### 抓到的第一个 bug：`task9` 分支会在生产崩溃

`lsg_derived.py` 里改 `LSG_T9_MODE` 时留下了字符串格式化残留：

```python
reason=f"svc71/task9 mode={t9_mode} bytes={len(reply_payload)}; "
       "client consumption unverified"
       % os.environ.get("FINDSESS_PORT", "8466")   # <- 多余的 %
```

`f-string` 之后紧跟一个字面串再套 `%`，Python 会把它解释为对**整个拼接结果**
做格式化，而结果里没有占位符——抛 `TypeError: not all arguments converted`。

**这会让真实运行时任何 `svc71/task9` 请求把 handler 打断。** 由回归测试
（`test_synthetic_raw_handshake_and_candidate_reply`）暴露，已修为纯 f-string。

#### 抓到的第二个 bug（测试自身滞后）

同一测试原本断言 task3/7/9 全部返回 **21 字节空成功帧**，但我把默认改成了
`error14`（14 字节）。测试落后于实现，已更新为：默认 14 字节 + `error=14`，
并在注释里写明 `LSG_UNIMPL_MODE=empty` 仍可回到 21 字节形态。

顺带修正了事件计数：本测试实际有 **4 个**被应答的请求（task4 也算一次），
原断言写 3。

#### 当前离线测试总量

```
python -m unittest tools.test_frames tools.test_contracts server319.test_lsg_derived
Ran 40 tests in 0.037s
OK
```

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `tools/test_frames.py` | 17 | bdMatchMaking 条目与 task9 帧结构 |
| `tools/test_contracts.py` | 21 | 全部应答构造器 + profile 编码器 |
| `server319/test_lsg_derived.py` | 2 | 合成握手全流程（含真实 AES/HMAC） |

#### 意义

这轮是第 37 轮以来第一次**有确定产出**的工作：不依赖客户端、不依赖实机，
40 项断言全部通过，且抓出了两个如果留着会在真实运行时出问题的缺陷
（一个崩溃、一个契约漂移）。

M4 主体仍阻塞于 §9.0 的人工前置，但服务端侧的可靠性因此实质提升。

## 参考

- [PUMP-STATE-MACHINE.md](PUMP-STATE-MACHINE.md) — 大厅 pump 状态机的完整技术说明（213 行，含地址表、状态机全图、已排除假设）
- [SOLUTION-100-111.md](SOLUTION-100-111.md) — 100/111 阻塞的完整解法
- [LONG-RUN-GOAL.md](LONG-RUN-GOAL.md) §9.0 — M4 的人工前置条件

### 15.47 ★★★ 六补丁下 `[lobby+0x1F4]` 翻成 **-2**，印证社区记录（2026-10-23 14:0x）

#### 先纠正第 39 轮的错误结论

§12.57 写「六补丁导致客户端 24 秒崩溃」。本轮用同样的 6 个补丁重跑，
**客户端稳定存活 60 秒以上，`dw` 正常到达 5**：

```
t=5s:   dw=0  ui=0
t=10s:  dw=2  ui=6
t=15s:  dw=5  ui=9   G1=0  gate=0  D+0xC=0
t=60s:  dw=5  ui=9   G1=0  gate=0  D+0xC=0
```

**第 39 轮那次崩溃是运行环境问题（服务未就绪或 observe 过短），不是补丁集的问题。**

#### 关键发现：`1F4` 翻成 -2

在此基础上写 `[D+0xC]=1`，然后观察 130 秒：

```
t=10s:  1F4 = 1
t=20s:  1F4 = 4294967294      <- 0xFFFFFFFE = -2
t=30s…130s: 恒为 -2，客户端不崩
```

**这正是社区文档描述的现象：**

> `[lobby+0x1F4]` 这个状态量以前从没撑过 47 秒就翻成 -2。根本原因是 pump 的
> 匹配判定失败后会走清理路径，把 1F4 写成 -2，而客户端再读到 -2 就认为连接已经失去。

社区记录的是"没撑过 47 秒"，我们这里是 **20 秒**——同一现象。

#### 这解释了三件事

1. **那 9 处 pump 补丁的作用**：它们把写 `-2` 的地方改成写 `1`
   （`0x7ADC27`、`0x7ADDE0`、`0x7AE754`、`0x7AE76C`、`0x7AE7B0` 五处
   `fe ff ff ff` → `01 00 00 00`，即 `-2` → `1`）。
   15 补丁下 `1F4` 恒为 1 而不是 -2，正是这个原因。

2. **6 补丁与 15 补丁的真实差别**：不是"崩不崩"，而是 **`1F4` 是 -2 还是 1**。
   两者都不通向 2，都在这个意义上失败。

3. **`-2` 不等于崩溃**：本轮实测 `1F4 = -2` 持续 130 秒，客户端存活、不发
   `ClientOffline`。所以"读到 -2 就认为连接失去"这个描述至少在 1604220 上
   不表现为进程退出。

#### 当前对 `1F4` 取值空间的完整认识

| 值 | 来源 | 客户端状态 |
|---|---|---|
| `1` | 15 补丁（9 处把 `-2` 改成 `1`）或 pump 的失败尾部 `0xBAE7AA` | 存活，FE 梯停在 G1=0/1 |
| `2` | `0xBAE1AC`（成功分支，**从未执行过**）或强写 | 强写会在 10 秒内崩溃 |
| `-2` | 6 补丁下 pump 的清理路径（`0x7ADC27` 等原始代码） | **存活**，FE 梯停在 G1=0 |

#### 下一步

`1F4` 的三种取值都已观测到，**没有一种能自然变成 2**。

要把 15 补丁（`1F4=1`）推到 `1F4=2`，只有 `0xBAE1AC` 一条路，而它被执行的条件是
两个状态字段分别等于 2 和 4（§12.51–12.53）。所以调查回到那个未解的矛盾：
`0xBBAD40` 复制 136 字节、却要求 1288 字节。

**不过本轮新增了一条有价值的线索**：社区把 `-2 → 1` 的五处补丁称为"pump 匹配
判定失败后的清理路径"。既然 `-2` 是"清理"的产物，那么**清理之前**应当有一次
`1F4=2` 的成功——也就是说，社区的环境里 `0xBAE1AC` **确实执行过**。

这与我们观察到的"从未执行"矛盾，值得列为下一轮的首要问题：
**社区那份补丁集原文（`patches319.py`）虽然缺失，但他们的 run 日志或许能证明
`1F4` 曾达到 2**。

### 15.48 ★★★ pump 门控链完整闭合：三个标志全满足，只差 `[obj1+0x120]`（2026-10-23 14:5x）

#### 先排除"瞬时值"假设

§12.59 之后怀疑 `1F4` 可能短暂变成 2 又被写回 1。用极限速度采样 30 秒：

```
samples=8163566 dist={1: 8163566} transitions=0
```

**816 万次采样全部为 1，零次跳变。** `0xBAE1AC` 确实从未执行。

同时用 `jump_map.py` 扫 `0xBAE000`–`0xBAE200` 的全部 24 个跳转，
**没有一个跳出该区域**——所以不存在"绕过 `0xBAE1AC`"的跳转。
它没执行，只能是因为执行流在更早处就离开了。

#### 三个前置标志的实际值

`0xBAE2DD` / `0xBAE2EA` / `0xBAE2F7` 依次检查三个字节，任一为 0 就跳
`0xBAE7B4`（什么都不写，`1F4` 保持 1）。逐个求出实际值：

| 标志 | 设置点 | 条件 | 实测 | 结果 |
|---|---|---|---|---|
| `[ebp-0x988]` | `0xBAD876 sete` | `[lobby+0x4D70] == [lobby+0x18]` | 两者都是 **3** | **1** ✅ |
| `[ebp-0x989]` | `0xBAE28B` | `[obj1+0x120] != 1` | 实测 **3** | **1** ✅ |
| `[ebp-0x986]` | `0xBAE2D6` | `0xBBA710(obj2)` 为**假** | 见下 | **1** ✅ |

`0xBBA710` 是判 `[obj2+0x1A0] ∈ {1,2,3}` 的谓词：

```asm
0xBBA710  mov ecx, [ecx + 0x1a0]
0xBBA718  cmp ecx, 1
0xBBA71B  je 0xbba727          ; 1 -> true
0xBBA71D  cmp ecx, 2
0xBBA720  je 0xbba727          ; 2 -> true
0xBBA722  cmp ecx, 3
0xBBA725  jne 0xbba729         ; 其它 -> false
0xBBA727  mov al, 1
```

实测 `[obj2+0x1A0] = 5`，不在集合内 → 返回**假** → `flag986 = 1`。

**三个标志全部满足**，所以执行流确实到了 `0xBAE304`。

#### 唯一的失败点

```asm
0xBAE304  mov ecx, [ebx + 0x1f8]
0xBAE30A  call 0xBBA1E0          ; = [obj1 + 0x120]
0xBAE30F  cmp eax, 2
0xBAE312  jne 0xBAE5DB           ; ★ 3 != 2 -> 跳去遍历后写 1
```

**`[obj1+0x120]` 实测 3，而这里要求 2。就这一个数字。**

若它等于 2，则继续到：

```asm
0xBAE318  mov ecx, [ebx + 0x1fc]
0xBAE31E  call 0xBBA750          ; = [obj2 + 0x1a0] = 5
0xBAE323  cmp eax, 4
0xBAE326  jne 0xBAE5DB           ; 5 != 4 -> 也会跳走
```

即**两个字段都差一步**：`obj1+0x120` 需 2（现 3），`obj2+0x1A0` 需 4（现 5）。
§12.51 观察到"各差 1"是对的，现在知道了它们在判定链里的确切位置。

#### 这条链的完整结论

```
pump 入口 (0xBAD83D/0xBAD846 两道门)          ✅ [lobby+8]=1, [lobby+0x1F4]=1
  → 三个前置标志 (0xBAE2DD/2EA/2F7)           ✅ 全部 = 1
  → [obj1+0x120] == 2 ?                       ❌ 实测 3
      ├─ 否 → 0xBAE5DB 遍历 → 0xBAE781 → 写 1
      └─ 是 → [obj2+0x1A0] == 4 ?
                ├─ 否 → 同上
                └─ 是 → 0xBAE32C … → 0xBAE1AC 写 2
```

**`0xBAD800` 这条路径上，全部条件都已满足，只有两个状态字段停在"差一步"的位置。**

#### 写 3 和写 5 的地方

| 值 | 地址 | 上下文 |
|---|---|---|
| `[obj1+0x120] = 3` | `0xBBA62B` | 与写 2 的 `0xBBA569` 相隔 0xC2 字节，同一函数的不同分支 |
| `[obj2+0x1A0] = 5` | `0xBBADCD` 等 5 处 | `0xBBAD40` 的失败分支 |

#### 下一步

要让 `[obj1+0x120]` 从 3 变 2，需要让 `0xBBA569` 所在分支执行。它和
`0xBBA62B` 在同一函数内，两者之间很可能只差一个条件判断。
**下一轮直接反汇编 `0xBBA520`–`0xBBA640` 这段，找出两个分支的分歧点。**

若该分歧点依赖网络数据，就需要补对应应答；若依赖 `[obj2+0x1A0]`，则先解决
`0xBBAD40` 的 136 vs 1288 矛盾（§12.54）。

### 15.49 ★★★ `obj1` 是容量 5 的列表；pump 启动后不再被调用（2026-10-23 15:0x）

#### 写 3 与写 2 的分歧点已定位

```asm
0xBBA5EC  movzx ecx, byte ptr [ebx + 0x124]   ; 容量（字节）
0xBBA5F3  lea edx, [eax + 1]
0xBBA5F6  mov dword ptr [ebx + 0x130], edx     ; 索引 = eax+1
0xBBA5FC  cmp eax, ecx
0xBBA5FE  jae 0xBBA613
...
0xBBA613  movzx eax, byte ptr [ebx + 0x124]
0xBBA61A  cmp dword ptr [ebx + 0x130], eax
0xBBA620  jb 0xBBA635                          ; 索引 < 容量 -> 跳过写 3
0xBBA622  push eax
0xBBA623  call 0xBA4B20
0xBBA62B  mov dword ptr [ebx + 0x120], 3       ; ★ 索引 >= 容量 -> 写 3
```

**`[obj1+0x120] = 3` 的含义是"这个列表已满"**，容量在 `+0x124`（一字节），
当前索引在 `+0x130`。

#### 实测：列表确实是满的

```
[obj1+0x120] (status)   = 3
[obj1+0x124] (capacity) = 5
[obj1+0x130] (index)    = 5
=> index >= capacity    = True
```

原始转储（`0x37E8D078` 起）也印证：

```
0x37E8D088  03 00 00 00 05 d0 1a 00 00 00 00 3f 03 00 00 00
            ^^^^^^^^^^^ status=3   ^^ cap=5
0x37E8D098  05 00 00 00 ...                                  index=5
```

#### 实验：把索引清零

写入 `[obj1+0x130] = 0` 并保持 120 秒：

```
t=10s   dw=5 ui=9 G1=0 gate=0 FE=5 1F4=1 o1[120]=3 o1[130]=0
t=20s   dw=5 ui=9 G1=1 gate=0 FE=5 1F4=1 o1[120]=3 o1[130]=0
t=120s  同上
```

三点结论：

1. **索引清零成功且稳定**（120 秒未变），说明没有代码把它写回去；
2. **`G1` 前进到 1**——`[D+0xC]=1` 依然有效，FER 梯第一级照常；
3. **`[obj1+0x120]` 仍是 3，`[lobby+0x1F4]` 仍是 1**——**pump 没有重新执行那段判定**。

#### 由此确认：pump 在启动后不再被调用

结合第 44 轮的 816 万次采样（`1F4` 恒为 1、零跳变），以及本轮"改了索引却
毫无变化"，可以确定：

**`0xBAD800`（pump）只在登录早期被调用过有限次数，之后不再执行。**

`0x6216BF` 是 pump 的调用点之一，它在 `0x6216B9` 把 `FE_state` 写成 3 或 5 之后
立刻调用一次。此后是否有循环驱动没有证据——之前关于"pump 每帧执行"的说法
（§12.31）**应予撤回**，那是从"`1F4` 恒为 1"和"`0xBAE7AA` 写 1"反推的，
从未观测到 pump 运行。

#### 这改变了对 `1F4` 的解释

| 旧解释 | 新解释 |
|---|---|
| pump 每帧跑、每帧失败、每帧写 1 | pump 只在登录早期跑过，`1F4` 停留在它最后一次写入的值 |
| 需要让 pump "这一轮"成功 | 需要在 **pump 还被调用的那个时间窗口内**让它成功 |
| 改状态字段应当让下一帧生效 | 改状态字段没有任何效果，因为之后没有下一帧 |

**即：这是一个时机问题，不是条件问题。** 第 44 轮把三个标志算出来全部满足，
现在知道即使条件满足也不会重试——因为根本不会再调用。

#### 下一步（方向明确）

需要在 **`FE_state` 被写成 3/5 之前或同时** 让两个状态字段达到目标值，这样
`0x6216BF` 那一次 pump 调用就能走成功分支。

具体做法：`auto_lobby.py` 目前是等 `dw=5` 之后才写状态位，**太晚了**。
应改为在 `dw` 到达 2（`0x6216B9` 执行前）就预先设好：

- `[D+0xC] = 1`
- `[obj1+0x120] = 2`
- `[obj2+0x1A0] = 4`

但 `obj1`/`obj2` 的指针在 `dw=2` 时可能还不存在。所以更稳的做法是**先跑一次
让对象建立，记下地址，然后重启客户端并在早期写入**——但对象地址每次运行都变，
这条路走不通。

**更现实的方向**：接受 pump 只跑一次，去查它**为什么只跑一次**——
`0x621750`（FE 主循环）是否被周期调用？若被调用，`0x62178F cmp eax,1` 之后
的 `0x621796 call 0xBAD800` 为什么没触发？这是下一轮的问题。

### 15.50 找到 UI 帧循环 → FE 主循环 → pump 的完整调用链，与 §12.61 矛盾（2026-10-23 15:5x）

#### 调用链

```asm
0x7EEAD0  push esi
0x7EEAD1  call 0x621750            ; ★ FE 主循环
0x7EEAD6  mov esi, 0xe56ffd0
0x7EEADB  jmp 0x7eeae0
0x7EEAE0  cmp dword ptr [esi], 1
0x7EEAE3  jne 0x7eeaec
0x7EEAE5  call 0x7fa3b0
0x7EEAEA  jmp 0x7eeaf3
0x7EEAEC  mov eax, esi
0x7EEAEE  call 0x7faf00
0x7EEAF3  add esi, 0x50
0x7EEAF6  cmp esi, 0xe5713d0
0x7EEAFC  jl 0x7eeae0               ; 遍历 0xE56FFD0..0xE5713D0，步长 0x50
0x7EEAFE  pop esi
0x7EEAFF  ret
```

`0x7EEAD0` 有 **6 个调用者**（`0x7EF0E3`、`0x7EF109`、`0x7EF1B5`、`0x7EF250`、
`0x7EF2C1`、`0x7EF2CC`），形态是标准的 UI 帧更新：先跑一次 FE 主循环，
再遍历一张 0x50 步长的对象表逐个更新。

而 FE 主循环在 `[lobby+0x1F4] == 1` 时必然调 pump：

```asm
0x621777  call 0x643280             ; 取 lobby
0x621782  je 0x621A1A               ; lobby 为 0 才跳过
0x62178A  call 0xBAC350             ; = [lobby+0x1F4]
0x62178F  cmp eax, 1
0x621792  jne 0x62179B
0x621794  mov ecx, esi
0x621796  call 0xBAD800             ; ★ pump
```

**所以只要 UI 帧循环在跑、lobby 非空、`1F4 == 1`，pump 就每帧被调用。**

#### 与 §12.61 的矛盾

§12.61 根据「把 `[obj1+0x130]` 改成 0 之后 120 秒毫无变化」推断 pump 只跑一次。
但本条调用链表明它应当每帧都跑。两者不能同时成立。

可能的解释：

1. **UI 帧循环未运行**——`0x7EEAD0` 的 6 个调用者都在某个"渲染帧"路径上，
   而客户端停在代号页时该路径可能停摆；
2. **lobby 指针为 0**——`0x621782 je 0x621A1A` 会跳过整段。但我们在别处读
   `[0xE85C68]` 一直非零，理论上 `0x643280` 返回同一个值；
3. **`0x621750` 存在早退**——它在入口 `0x621753 mov eax,0x2024` 与
   `0x621758 call 0xC43200` 是 `_alloca` 栈探测，若栈不足会抛异常；
4. **观测方法仍有问题**——「改索引无效」的观察本身可能受某个中间层影响。

#### 需要一个能自证的观测

前两次"没观测到"（§12.55、§12.56）都被证明是工具 bug。为避免第三次，
下一轮应先做一个**最小自证**：

在 `0x621750` 入口 `0x621750` 处读一个能区分"被调用过"的计数器——但客户端
没有这样的计数器。替代方案：用 `patch_runtime.py` 在 `0x621750` 前 5 字节
装一个 trampoline，把每次调用累加到一块可读内存，然后读那块内存。这个
trampoline 只要 20 字节，且**不改变任何行为**（`pushf/pushad` → `inc [counter]`
→ `popad/popf` → 原指令 → 跳回），比线程上下文采样可靠得多。

若计数为 0 → UI 帧循环确实没跑，问题在更上层；
若计数很大 → pump 每帧在跑，§12.61 的"只跑一次"结论错误，需回查索引实验。

#### 本轮确定的事实

| 事实 | 证据 |
|---|---|
| `0x621750` 唯一的直接调用者是 `0x7EEAD1` | `find_calls.py 0x621750` 只返回一条 |
| `0x7EEAD0` 是 UI 帧更新（先 FE 循环、再遍历 0x50 步长表） | 反汇编 |
| `0x7EEAD0` 有 6 个调用者 | `find_calls.py 0x7EEAD0` |
| FE 循环在 `1F4==1` 时调 pump | 反汇编 `0x62178F`/`0x621796` |

这三条都与"pump 每帧执行"一致，与"只跑一次"不一致。

### 15.51 ★★★ pump 每帧都在跑，但两个状态写入分支**从不执行**（2026-10-23 16:2x）

#### 先纠正 §12.61

§12.61 根据「把 `[obj1+0x130]` 改成 0 之后 120 秒毫无变化」推断 pump 只跑一次。
用 `tools/count_calls.py` 在 `0xBAD800` 入口装计数器（重放 `55 8B EC 6A FF 68` +
4 字节立即数，共 10 字节），30 秒实测：

```
[pump] calls = 30, 59, 89, 119, 148, 178, 208, 227, 401, 594, 784, 973,
              1162, 1352, 1541
```

**pump 30 秒被调用 1541 次，约 51 次/秒。** 同一轮里 FE 主循环 `0x621753`
15 秒 335 次（约 22 次/秒）。§12.61 的"只跑一次"是**错的**，那条结论作废。

#### 但两个写入分支都是 0 次

在写 2 与写 3 的指令上各装一个计数器（各重放完整的 10 字节
`C7 83 20 01 00 00 <imm32>`）：

```
[write2] 0xBBA569  total after 12s = 0        <- [obj1+0x120] = 2
[write3] 0xBBA62B  total after 12s = 0        <- [obj1+0x120] = 3
```

**两个都是 0。** 这说明 `0xBBA4xx`–`0xBBA6xx` 这一段代码**根本没有被执行**，
而 `[obj1+0x120]` 实测确实是 3——所以那个 3 是**启动阶段**由别处写入的，
之后再也没有任何代码改动它。

#### 至此所有观测都能一致解释了

| 观测 | 解释 |
|---|---|
| pump 每帧跑 1541 次/30s | FE 循环在跑，`[lobby+0x1F4]==1` 恒成立，于是每帧调 pump |
| `[lobby+0x1F4]` 恒为 1 | pump 每帧走到 `0xBAE781`/`0xBAE7AA` 写 1 |
| `[obj1+0x120]` 恒为 3 | 启动时写一次，生产者 `0xBBA4xx` 之后从未运行 |
| `[obj2+0x1A0]` 恒为 5 | 同上，`0xBBADCD` 失败码也是启动期产物 |
| 改 `[obj1+0x130]` 无效 | pump 只**读** `0x120` 做判断，从不重算它 |
| `0xBAE1AC` 从未执行 | 它要求 `[obj1+0x120]==2`，而该值永远是 3 |

**pump 是一个纯消费者**：每帧读取两个状态字段，据此决定写 1 还是写 2。
而**状态的生产者**（`0xBBA4xx` 那一段）在我们的运行里从未被调用。

#### 这改变了整个问题的性质

之前一直想"让 pump 成功"，方向就错了——pump 的逻辑本身没问题，它每帧都在
忠实执行。真正缺的是**让状态字段达到目标值的那段代码先跑一遍**。

具体来说，需要让注册 **{类型 0x14, 子类型 2, key 0, 长度 1288}** 记录的那段
代码（`0xBBA4xx`–`0xBBA760` 这一族）被执行一次，把 `[obj1+0x120]` 从 3 推到 2、
把 `[obj2+0x1A0]` 从 5 推到 4。

#### 下一步

1. 找 `0xBBA4xx` 所在函数的**入口**（向前搜索 `55 8B EC` 或 `CC` 填充边界）；
2. 用 `find_calls.py` 找它的**调用者**，确认调用条件；
3. 若调用条件依赖某个服务应答或某个初始化步骤，把这个条件补上。

这是目前最直接的一条路：**与其让消费者满意，不如让生产者跑一次。**

#### 工具

`tools/count_calls.py`（本轮新增，可复用）：

```bash
python tools/count_calls.py --at 0xBAD800 --orig 558bec6aff6897fec800 --label pump --secs 30
```

它把目标地址前 N 字节换成 `jmp cave`，cave 里 `pushfd/pushad` → `inc [counter]`
→ `popad/popfd` → 重放被替换的原始字节 → 跳回，**不改变任何寄存器与标志位**。
这是本项目第一个经得起自检的观测工具——前三次"没观测到"（§12.55、§12.56、
§12.61）都是工具或推断本身的错误。
