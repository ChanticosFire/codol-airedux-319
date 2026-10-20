# 交接文档：CODOL 3.19.26.22 (Build 1649370) 离线复活 — 2026-10-21

> 给 Codex 的完整交接。所有地址均为**运行时实测**（反汇编 + ReadProcessMemory 采样），所有结论都有 `runs/` 证据。
> 工作目录：`E:\GAME\COD\codol-airedux\319`

---

## 0. 一句话现状

**Auth / IIPS / TCLS / LSG 握手 / 0x85 解密（C2S）全部打通；服务端已拿到正确的协议算法与帧格式（`bdproto319.py`）。唯一缺口是 `packet_buffer` 的精确拼法与 `SESSION_KEY`——没有它就算不出 `enc_key`/`resp_hmac_key`，因此发不出客户端能接受的加密回复，UI 卡在 `ui_state=4`（失败分支）并弹 `[100]`。**

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

---

**最后更新**：2026-10-21，DeepSeek → Codex。
**目标状态**：已暂停（`update_goal` paused），等待 Codex 接续。
