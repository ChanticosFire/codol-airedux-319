# 交接文档：CODOL 3.19.26.22 (Build 1649370) 离线复活 — 2026-10-21

> 给 Codex 的详细交接。所有结论都有 run 目录证据；地址均为实测（运行时反汇编 + ReadProcessMemory 采样）。
> 工作目录：`E:\GAME\COD\codol-airedux\319`

---

## 0. 一句话现状

**Auth、IIPS、TCLS、LSG 握手、0x85 解密全部打通；客户端能进到 `DW_LOBBY_CONNECTED`，但那是失败分支（`ui_state=4`）。真正的成功是 `ui_state=5`，卡在两点之一：客户端解不开我们发的 0x85 加密回复（`aes_recv` 未知），或 0x87 帧触发不了 crypt 初始化。**

---

## 1. 运行环境（必须）

| 项 | 值 |
|---|---|
| 权限 | **管理员**（High 令牌）。IIPS 需要 `SeDebugPrivilege` + `SeCreateGlobalPrivilege`；Medium 下游戏 14 秒内从不创建 `IIPSHostApp`，IIPS 必失败 `8189fec` |
| 客户端 | `runtime\client-1649370\codoMP_client_shipRetail.exe`（隔离副本，原件只读） |
| 启动参数 | `-q`（跳过 TCLS 门槛） |
| 服务端 | `python -m server319`（Auth，4175 TLS）+ `python -m server319.lsg`（LSG，4174 TLS） |
| 证书 | `runs\20261020-session03\tls\auth.crt` / `auth.key`（新 RunId 会自动回退到这个） |

---

## 2. 已打通（有证据）

### 2.1 Auth
- 响应 `auth_task` **必须等于请求值 +1**（请求 10 → 响应 11），`code=700`。
- 必须带 `member_position` / `estimated_wait_time` / `next_poll_after` 三个排队字段。
- 票据必须结构化（Tiger 校验），实现在 `server319/ticket.py`（`SESSION_KEY = bytes(range(24))`，写在 ticket 偏移 97–120）。
- 证据：`runs/20261020-codex-*`、`runs/20261020-session09+`。

### 2.2 LSG 握手（全部实测）

| 方向 | 帧 | 说明 |
|---|---|---|
| C→S | **28B hello**：`c8000000 c8000000 d2000000 dc000000 00000800 <8B 随机>` | 首字节 0xC8 |
| S→C | **26B 门控**：`[u32 22][0x01][0x81][u32 0xDC(220)][8B MARK][8B nonce]` | **版本必须 220**，210 会让 `stage` 永远到不了 3 |
| C→S | **153B 0x82**：`[u32 149][0xAB][0x82][0791FA00][4B session][06000000]...` | 末 8 字节是 `CHAL[:8]` |
| S→C | **0x83**：`[u32 10][0xAB][0x83][8B token]`，token = `conn+0x5FC` | 客户端接受并回 0x85 |
| C→S | **130B 0x85**：`[u32 126][0xAB][0x85][u32 seq][16B IV][96B cipher][8B tail]` | 需要 0x83 成功后才出现 |

### 2.3 0x85 解密（C2S，**已验证**）
- 密钥：`conn+0x604` 是**指针**，16B 密钥在 `[ptr+0x9C]`。
- 算法：AES-128-CBC，IV = 帧内 offset 10。
- 明文（84B，与 1604220 资料逐字节一致）：

```
54 00 00 00 86 47 03 04 13 08 10 00 00 00 "nQloP0oCVWR6RDJS"
13 08 10 00 00 00 2b×16 08 9e cb e6 01
13 08 00 00 00 00 13 08 00 00 00 00
10 "1C-83-41-CE-8D-EE" 00 00
```

---

## 3. 当前卡点（精确）

### 3.1 `ui_state` 语义（**重要修正**）

`0x7F25B0` 的跳表（`[0x84ABA50]` → 结果）：

```
0     -> 4   (fail)
1..4  -> 1   (中间态，随后 0x7EF1DE 判定失败 -> 0x7EF210 push 0xDE0640 -> UI 弹 [100] 无法连接大厅服务)
5     -> 3   (success)
```

**`DW_LOBBY_CONNECTED`（ui=4）是失败分支**，不是「已连接」。UI 上表现为 `[100]无法连接大厅服务!`（截图见 `20261020` 会话记录）。

### 3.2 `ui=5` 的条件（`0xBA0780` 反汇编）

```asm
cmp dword [ecx+0x644], 0      ; crypt
mov eax, [ecx+0xC8]           ; lstate (CS)
je  crypt_zero
  cmp eax,2 -> return 2
  cmp eax,1 -> return 2
  return eax                  ; 其他值（含 4）返回 4
crypt_zero:
  cmp eax,2 ; jne -> return eax
  cmp dword [ecx+0x5E8],3     ; stage
  -> stage==3 返回 2，否则 1
```

即：
- **A**：`crypt != 0` 且 `lstate ∈ {1,2}`
- **B**：`crypt == 0` 且 `lstate == 2` 且 `stage == 3`

`0xB7A670` 再把它映射给大厅泵：`ready([netobj+0x4F8])!=0` 时直接返回 `0xBA0780` 的值，否则 `eax==2` 时返回 1。

### 3.3 实测状态

```
ui=3: lstate=2, crypt=0, stage=2   (DW_ACCOUNT_LOGIN_COMPLETE)
ui=4: lstate=2, crypt=0, stage=3   (DW_LOBBY_CONNECTED — 条件 B 短暂成立约 5s)
ui=4: lstate=4, crypt=0, stage=0   (随后报废)
```

**`crypt` 恒为 0**，所以 A 路永远不通；B 路只在 stage=3 的 5 秒窗口内成立，但大厅泵没赶上（或 `0xB7A670` 拿到的 ready 不是 1），随后被打成 4。

### 3.4 为什么 crypt 建立不了

`0xBA3590`（加密通道建立）：

```asm
0xBA35B0 call 0xB783C0        ; 从 0x87 帧读 1 字节
0xBA35BC cmp byte [ebp+0x13], 1   ; 必须 == 1
0xBA35CA call 0xBA3420        ; 否则报废
0xBA35D7 cmp [esi+0x644], 0
0xBA35E2 call 0xBA3010        ; 初始化（内部：分配 44B → 0xB9BEB0 → 0xB76620(写 tag3=1) → 0xB75DE0(读 tag1/136B) → 0xBA2A60）
0xBA35EB mov [esi+0x644], 1
```

上游 `0xBA3AE6`：只有 `type == 0x87` 且 `[conn+0x640] >= 0xDC(220)` 才进 `0xBA3590`。

**已实测**：
- gate 改 220 后 `conn_ver=220` ✅、`stage=3` 出现 ✅。
- 发 0x87（`[u32 16][0x87][0x01][0x00×15]`）→ `DW_LOBBY_ERROR`。
- 发 0x87（`[u32 136][0x87][0x01][0x00×136]`）→ 客户端立刻 `DW_LOBBY_ERROR`（crypt 仍 0）。
- **未验证**：0x87 的 payload 到底要不要符合 TagWriter 编码（`0xBA308E` 是 `push 0x88; push 1` → 读 **tag 1、136 字节**，长度字段与 `0xBA3AC2` 的 `len+offset(5) <= 总长` 约束需要同时满足）。

### 3.5 S2C 0x85 解不开（铁证）

新增探针 `frame85_seen`：发帧后立刻在客户端内存搜我们的明文头和密文头。

```
frame85_seen pt []                 ← 明文从未出现（客户端没解密）
frame85_seen ct ["0x38b7a1ab"]     ← 密文在接收缓冲里
```

**客户端收到帧但解不开**。已排除的密钥候选（全部 `pt []`）：
- `[conn+0x604]+0x9C`（对称复用，虽能解 C2S）
- `[conn+0x604]+0x14` / `+0xAC` / `+0xBC` / `+0xCC`
- `[conn+0x608]+0x9C`（**该对象是证书缓冲，内容是 "…prise Services GmbH"/"DigiCert Inc"/X.509**，不是密钥）
- 明文 0x85 回帧（不加密）

### 3.6 强制写内存会被回滚

`runs/set_crypt.py` 在 `ui==4` 时写 `crypt=1`、`ready=1`：写入成功，但**下一瞬间客户端把 `crypt` 改回 0、`lstate` 置 4**——`0xBA3420` 内同时写 `crypt=0` 和 `lstate=4`，说明客户端有**一致性检测并回滚**。单点写内存伪造不出成功。

---

## 4. 关键地址表（运行时 VA，ImageBase 0x400000）

### 全局
| 地址 | 含义 |
|---|---|
| `0x8269774` | netobj |
| `0x84ABA50` | ui_state（0/1–4/5） |
| `0x84ABA54` | 上一个 ui_state |
| `0x84ABA7C` | business queue（采样常见 2） |
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
| `conn+0x5EC` | **不是** rx 序号（实测为 0 或 "loba" 文本片段） |
| `conn+0x5FC` | challenge（0x83 的 token 来源，8B） |
| `conn+0x604` | AES key 对象指针 → `[ptr+0x9C]` = 能解 C2S 的密钥 |
| `conn+0x608` | 证书缓冲（**不是密钥**） |
| `conn+0x640` | version（必须 ≥ 220） |
| `conn+0x644` | crypt（0/1/3） |

### 函数
| 地址 | 作用 |
|---|---|
| `0x7F25B0` | ui_state 状态映射（跳表 `0x7F25DC`） |
| `0x7EF1C8` | 大厅轮询；`0x7EF1DE cmp esi,3` 成功、`0x7EF210` 失败（`push 0xDE0640` = `[100]` 文案） |
| `0x803780` | 大厅泵（`0x803699 je→jmp` 可让它无条件成功） |
| `0xBA0780` | 连接状态查询（ui=5 判定） |
| `0xBA2A60` | 收帧处理；`crypt==0` 时要求 `lstate==2 && stage==3` |
| `0xBA3420` | 报废：`lstate=4` + `crypt=0` |
| `0xBA3AE0` | 帧 type 分派（0x87 才建 crypt） |
| `0xBA3590` | 加密通道建立 |
| `0xBA3010` | 密钥/通道初始化（内部 `0xB76620` 写 tag3、`0xB75DE0` 读 tag1/136B） |
| `0xBA4430` | 控制帧处理；**`lstate==4` 直接 `ret`，不解析任何帧** |
| `0xB783C0` | 缓冲区边界读取（`buf,len,offset,out,n`，`offset+n<=len`） |
| `0xB73FE0` | memcmp |
| `0xB76620` | 写 tag 3 + 1 字节 |

---

## 5. 阴性结果清单（避免重复踩坑）

| 尝试 | 结果 |
|---|---|
| 0x83 token 换成 0x82 尾 8B / 反序 / `conn+0x5F4` | 客户端不发 0x85 或直接报错 |
| 0x83 长度 10/12/16 | 16B 才让客户端发 0x85（不补丁也行） |
| 0x85 回帧：空 payload / 回显 96B / task_reply | 全部 `peer_closed` 或 `pt []` |
| marker `0x01` vs `0xAB` | 都失败 |
| IV 随机 vs 固定 `16..31` | 固定 IV 导致立即关闭（1649370 用帧内 IV） |
| 心跳 2s/5s/20s/30s（加密帧/4 零字节） | 2 帧后 `ConnectionAbortedError`；4 零字节也无效 |
| 0x83 后完全静默 | 6 秒后客户端自行断开，且不发业务请求 |
| 0x87 帧（16B / 137B payload） | `DW_LOBBY_ERROR`，crypt 仍 0 |
| 强制写 `crypt`/`ready` | 被客户端回滚 |
| `CHAL` 派生：`A20=SHA1(transcript)` + `HMAC-SHA1` + `HKDF`，144000 组合 | 未命中 `reply[-8:]`（`runs/derive_keys.py`） |
| `probe_anchor` 扫描解密代码页 | 对已知引用 0 命中（工具待修） |

---

## 6. 外部参考（都在仓库内）

| 路径 | 内容 | 价值 |
|---|---|---|
| `他人文件参考/bdsvc319.py` | 业务应答服务（**依赖 `bdproto319`，缺**） | 服务表 + `make_service_reply` 形状 + **tag 0x0A 在 `svc21/task5` 应答里** |
| `他人文件参考/PROGRESS.md` | 另一套跑通的 1649370 服务端 | **`DW=4→5` 可达**、svc28 必须静默、ZEROFRAME 30s、业务帧明文 |
| `他人文件参考/零补丁分析-20261019.7z` | 1604220 的 P2/P3 判定链 | CS=4 需要 D 条件；`task_reply` 格式 |
| `codol-ember/工具-tools/lobby-reproduction1604220/` | 1604220 完整服务端 | 握手 `step1/step2`、密钥派生公式、`evt4`、keepalive（**`wire.py` 被省略**） |
| `codol-ember/工具-tools/launch319-reference/reference/launch/` | **319 官方参考** | `patches319.py`（实测补丁集）、`orch319.py`（编排/dw=5 触发）、`lobby_service.py`（抓包用） |

### `patches319.py` 里可直接用的补丁（RVA = VA - 0x400000）
| 名称 | VA | 原→新 | 作用 |
|---|---|---|---|
| `LOBBY_PUMP_OK` | `0x803699` | `741f`→`eb1f` | 大厅泵无条件走成功分支（保持 dw=5） |
| `NO_DW_DELETE` | `0x803659` | `893540ba4a08`→`909090909090` | 不让 dw 被清 0 |
| `ACCOUNT_FORCE_2BC` | `0x7F2A0A` | `3dbc0200007407`→`b8bc0200009090` | 账号结果码强制 0x2BC |
| `NO_LSG_DISCONNECT` | `0x7EE9DC` | `e82f2f0100`→`9090909090` | 跳过断连处理 |
| `NO_FATAL_POPUP` | `0x77C860` | `558bec83e4f8`→`c390909090`（**6 字节，注意长度**） | 跳过致命错误弹窗 |
| `HIDE_CONNECTING` | `0x60C649` | `b001`→`b000` | 隐藏「连接中」提示 |

> 我试过 `0x403699`(LOBBY_PUMP_OK) + `0x403659`(NO_DW_DELETE) 的组合，**直接变成 `[100]`**（`runs/20261020-pump2/pump3`）。可能是补丁顺序、组合，或缺少配套补丁（如 `ACCOUNT_FORCE_2BC`、`NO_LSG_DISCONNECT`）导致，**值得 Codex 用参考的完整补丁集重试**。

---

## 7. 给 Codex 的建议路线（按性价比排序）

1. **拿 `bdproto319.py`**（和 `bdsvc319.py` 同目录）。它含 `ByteWriter`/`TypeReader` 与 0x85 封装，能直接确定 `aes_recv` 与 0x85 帧格式。这是最短路径。
2. **照 `patches319.py` 的完整补丁集**（`LOBBY_PUMP_OK` + `NO_DW_DELETE` + `ACCOUNT_FORCE_2BC` + `NO_LSG_DISCONNECT` + `NO_FATAL_POPUP`）一次性打上，观察是否能直接进大厅并截图——参考实现声称这条路可达 `dw=5` 且可视化。
3. **推 crypt**：确认 0x87 payload 的 TagWriter 编码（`0xBA308E` 读 tag 1、136 字节；`0xBA3AC2` 要求 `len+5<=总长`），试着让 `0xBA3010` 成功、`[conn+0x644]=1`。
4. **A 路**：若能拿到 `aes_recv`（transcript→HKDF 第四段），就按 `svc21/task5` 回 tag 0x0A。

---

## 8. 复验命令

```powershell
cd E:\GAME\COD\codol-airedux\319

# 一键会话（Auth + LSG + 打补丁 + 采样）
pwsh -NoProfile -File runs\run_hb88.ps1 -RunId 20261021-test

# 看状态
python -c "import json;d=json.load(open(r'runs\20261021-test\patch.json',encoding='utf-8'));[print(e['utc'],(e.get('lobby') or {}).get('ui_state'),(e.get('lobby') or {}).get('conn_lstate'),(e.get('lobby') or {}).get('conn_crypt')) for e in d['events'] if e.get('event')=='sample']"

# 看 LSG 帧
Get-Content runs\20261021-test\lsg.jsonl

# 手动补丁（示例）
python tools\patch_runtime.py --client-dir runtime\client-1649370 --evidence runs\x\patch.json `
  --patch 0x403699:EB1F:741F --patch 0x403659:909090909090:893540BA4A08 --wait 13 --observe 90
```

---

## 9. 文件地图（服务端）

| 文件 | 作用 |
|---|---|
| `server319/lsg.py` | LSG 服务（握手、0x83、0x85 解密/回帧、探针）。环境开关：`LSG_INNER`/`LSG_BIZ`/`LSG_KEYOFF`/`LSG_PLAIN85`/`LSG_SILENT_AFTER83`/`LSG_F87_DELAY` |
| `server319/lsg_client.py` | 跨进程读取（`find_service_conns`、`read_region`、`search_bytes`、`find_client_pids`） |
| `server319/auth.py` | Auth 端点 + 证据写入（字段 allowlist） |
| `server319/ticket.py` | 票据（Tiger） |
| `tools/patch_runtime.py` | 通用 RVA 补丁 + 采样（会写 `lobby` 字段） |
| `tools/patch_auth_bypass.py` | 旧采样工具（含 `conn_ver`/`conn_crypt`/`conn_stage`） |
| `runs/set_crypt.py` | 强制写 `crypt`/`ready`（**已被证明会被回滚**，留作诊断） |
| `runs/derive_keys.py` | CHAL/密钥派生穷举 |
| `runs/dump_ba3000.py` | dump 代码区（`runs/20261020-dump5/` 最新） |

---

## 10. 证据索引（最近的）

| Run | 结果 |
|---|---|
| `20261020-p3b` | 发 80/230 playerdata（inner 1），`pt []` |
| `20261020-gate220` | **gate 220 → stage=3 首次出现** |
| `20261020-f87/` `f87b/f87c/f87d` | 0x87 各变体 → `DW_LOBBY_ERROR` |
| `20261020-silent4` | 0x83 后静默 → 6s 自行断开 |
| `20261020-plain85` | 明文 0x85 → `peer_closed` |
| `20261020-base` | 基线复现 `ui=4` + `[100]` |
| `20261020-uiforce` | 强制写 crypt/ready 被回滚 |
| `20261020-pump2/pump3` | 大厅泵补丁 → 直接 `[100]` |

---

**最后更新**：2026-10-21，由 DeepSeek 交接给 Codex。
