# LSG 握手现状（2026-10-20 下午，给 Codex / 用户）

> 承接 [HANDOFF-TO-CODEX.md](HANDOFF-TO-CODEX.md)。Codex 修好了 Auth schema 与票据，客户端已经**真正连上 4174 并走完门控**；0x83 补丁后客户端**已发 0x85 加密通道帧**，现在卡在 **0x85 的会话密钥/解密**。本文只写实测与反汇编能钉死的部分。

## 0. 最新突破（2026-10-20 15:0x）

- **0x85 解密成功**：密钥 = `conn+0x604` → `[ptr+0x9C]`（16B），AES-128-CBC，IV = 帧内 offset 10（`[u32 len][ab 85][u32 seq][16B IV][cipher][8B tail]`）。
- 明文 = **84B 登录请求**，与 1604220 资料完全一致：
  ```
  54000000 86 47030413 0810000000 "nQloP0oCVWR6RDJS" 130810000000 2b×16 089ecbe601 130800000000 130800000000 10 "1C-83-41-CE-8D-EE" 0000...
  ```
  证据：`runs/20261020-session33/lsg.jsonl` 的 `frame85_plain`。
- 服务端用 `conn+0x608` 的 key 加密回了一个空 0x85（`frame85_reply`），客户端**没有再发帧**（`runs/20261020-session34`），说明它在**等业务应答**（`0x47` 的回复 / 大厅地址），不是链路问题。

## 0.1 下一步（当前唯一缺口）

- 客户端发的 84B 是**登录/进大厅请求**（`0x47` 命令码）。1604220 资料（N97）说必须回 **tag `0x0A` 的 8 字节大厅地址**，否则 UI 永远停在“连接大厅”。
- 需要确定 **1649370 的 0x47 应答格式**（内层类型 + TLV），以及 tag `0x0A` 的解析器（1604220 是 `0xB769A0`，1649370 需按同法找）。
- 临时验证手段：回一个 `0x85` 帧，载荷 `[len][0x86][...]` 或 `[len][0x47][...]`，观察客户端是否从“等应答”转为发下一帧。

## 0.2 旧记录（0x83 边界检查）

- 0x83 的边界检查分支（`0xBA456E`）**补丁成 NOP** 后，客户端不再报 `DW_LOBBY_ERROR`，并主动发 0x85。
- 说明 0x83 的 token 布局还差一点（token 位置/长度），但补丁可绕过；正式修复优先把 0x83 布局弄对。

## 0.2 业务应答参考（`svc80_responder.py`，来自 `launch1604220-repro`）

- 0x85 明文格式：`[u32 报文长度][u8 消息类型=0x86][u8 子类型][...]`。
- 客户端已知子类型：`0x47`（84B 登录：token `nQloP0oCVWR6RDJS` + codoid + MAC）、`0x1c`（30B，4×u32：4,0,1,2）。
- 服务端 `0x87`/`0x89` 是**专用处理**（客户端 `0xba3510`/`0xba3580`）；`0x87` 会让客户端**重连**，不能当业务应答。
- `svc80_responder.on_plain(pt)` 只处理 **svc80 task**（body 里 (80,230) 之类），`0x47` 不在其中，返回 `None`。
- 结论：`0x47` 的应答不是 svc80；进大厅仍要 **tag 0x0A 大厅地址**（1649370 的解析器在 `0xB769A0`，成功路径 `0xB83A52`→`netobj+0x50/0x54`→`[+0x4F8]=1`）。

## 0.3 实验记录（0x85 之后）

- 回空 0x85、回 `0x86`+tag0x0A、回 `0x87`+tag0x0A、回显 84B、每 2s 心跳（seq 固定/递增）：客户端都在 ~20-30s 出现 `与大厅服务器失去连接`。
- 注意：0x83 **加长到 16B**后，**不补丁**也能让客户端发 0x85（`runs/20261020-session38`）；说明 0x83 的边界检查需要 ≥16B payload。
- 下一步：找到 `0xB838A0`（业务帧分派）的**调用者**，确认客户端从哪个帧类型进入 `0xB83A52`（tag 0x0A）分支。

## 1. 已打通（按时间顺序）

| 步骤 | 证据 |
|---|---|
| Auth schema 修正（`auth_task=11`、`code=700`、三个排队字段） | Codex 的 `runs/20261020-codex-queue01..ticket04` |
| Tiger 票据通过，`DW_ACCOUNT_LOGIN_COMPLETE` | `runs/20261020-session09+` |
| 客户端连 4174，发 **28B hello** `c8000000 c8000000 d2000000 dc000000 00000800 <8B random>` | `runs/20261020-session08/lsg.jsonl` |
| **26B 门控应答被接受**：`[u32 22][01][81][D2 00 00 00][MARK 0x1122334455667788 8B][nonce 8B]` | `runs/20261020-session09+`，客户端下一帧是 153B `0x82` |
| 客户端 **153B 0x82 帧**：`95000000 ab 82 0791fa00 0000 <4B session> <4B 06000000> 0...` | `lsg.jsonl` 的 `plaintext_frame2.body_hex` |

**当前实现**：`server319/lsg.py` 的 plaintext 分支回门控 → 收 0x82 → 尝试回 0x83。`server319/lsg_client.py` 跨进程读客户端内存。

## 2. 0x83 尝试记录（全部失败，客户端 1 秒后 `DW_LOBBY_ERROR`）

| # | token 来源 | 帧 | 结果 |
|---|---|---|---|
| 21 | `conn+0x5FC`（1604220 参考偏移） | `0a000000 ab 83 <8B>` | `DW_LOBBY_ERROR` |
| 22 | `conn+0x5F4` | 同上 | 同上 |
| 23 | 0x82 帧 `[12:20]` | 同上 | 同上 |
| 24 | 0x82 帧 `[-8:]` | 同上 | 同上 |
| 25 | `conn+0x5FC` 反序 | 同上 | 同上 |
| 26 | `conn+0x5FC`（正向）+ marker `0x01` | `0a000000 01 83 <8B>` | 同上 |
| 27 | 同上（去反序 bug） | `0a000000 01 83 <8B>` | 同上 |
| 28 | `0xAB` + 加长 2 字节 | `0c000000 ab 83 <8B> 0000` | 同上 |

**注意**：0x83 的发送时间比 0x82 晚 8-10 秒（跨进程扫描内存），但客户端是**收到后 1 秒才报错**，所以不是超时，是**内容/格式被拒**。

## 3. 0x83 handler 反汇编（1649370，运行时 dump 0xBA3000）

```
0xBA454B  cmp eax, 2                ; [esi+0x5E8] == 2（sub）
0xBA454E  jne 0xBA46A2
0xBA4554  mov al, [ebp-0xE]         ; op 字节
0xBA4557  cmp al, 0x83
0xBA4559  jne 0xBA45F0
0xBA455F  mov eax, [ebp-0x14]
0xBA4562  push edi
0xBA4563  push eax
0xBA4564  push ebx
0xBA4565  mov ecx, esi
0xBA4567  call 0xBA3BA0             ; ★ 读 8B token
0xBA456C  test al, al
0xBA456E  je 0xBA4463               ; ★ 失败 → 报错
0xBA4574  mov eax, [esi+0x644]      ; crypt 状态
0xBA457A  test eax, eax
0xBA457C  jne 0xBA45DB              ; crypto 已就绪 → 另一条路
0xBA457E  push 0x1C
0xBA4580  call 0xB74220             ; new 0x1C
...
0xBA45B2  call 0x7F9350             ; ★ token 之后的回调
```

`0xBA3BA0`（读 token 的函数）：

```
0xBA3BA0  push ebp; mov ebp, esp; sub esp, 0x10
0xBA3BB5  push 8                    ; 读 8 字节
0xBA3BB7  lea edx,[ebp-0xC]
0xBA3BBA  push edx
0xBA3BB5  ...
0xBA3BC0  lea edx,[ebp-0x10]
0xBA3BC3  push edx
0xBA3BC4  push ecx                  ; 源
0xBA3BC5  mov [ebp-0x10], ecx
0xBA3BC8  mov ecx, [ebp+0x10]       ; 参数
0xBA3BCD  call 0xB783C0             ; 边界检查 + 读 n 字节
```

`0xB783C0` 是**缓冲区边界检查**（`offset + n <= length`），不是 token 校验：

```
0xB783C3  cmp [ebp+0x18], 0         ; out_len == 0 ?
0xB783D2  lea ecx,[edx+edi]         ; offset + n
0xB783D7  mov [esi], ecx            ; 写回新偏移
0xB783DB  cmp [ebp+8], 0            ; 源指针
0xB783E4  cmp edx, esi ; setbe bl   ; offset <= len
0xB783EA  cmp ecx, esi ; setbe al   ; offset+n <= len
0xB783EF  test al, al ; jne 0xB78403
0xB783F3  ... 失败
0xB78403  test bl, bl ; je 0xB783FC ; 失败
0xB78407  ... memcpy(dst, src+offset, n)
```

**结论**：0x83 的 token 只是被**读 8 字节**（不是 memcmp），成功后写 `conn+0x5FC`、`sub=3`、`rxseq/txseq=1`（`0xBA3BEB`-`0xBA3C47` 是成功路径）；失败只可能来自**边界检查**（payload 长度不够 / 偏移不对）。

## 4. 未解点（下一步）

1. **0x83 帧的精确布局**：`[u32 len][marker][op][8B token]` 我们试了 marker `AB`/`01`、长度 10/12；但 `[ebp-0x14]`/`ebx`/`edi` 三个参数的实际值没确认，边界检查可能因为**偏移**（op 之后的位置）不对而失败。
2. **`[esi+0x644]`（crypt 状态）**：若为 0 走 `0x7F9350`，若非 0 走 `0xBA45DB`——两条路后续都需要 0x85 加密通道。
3. **`0x7F9350` 的语义**：token 读成功后的回调，可能是“开始加密/发 0x85”。

**建议**：用 x64dbg 在 `0xBA4567`（call 0xBA3BA0）下断点，看 `ebx`/`edi`/`[ebp-0x14]` 的实际值，以及 `0xBA3BA0` 的返回值——这能一次确定 0x83 的布局。或者拿一份 1649370 正常会话的 0x83 原始帧（14 字节）直接对照。

## 5. 文件

- `server319/lsg.py`：门控 + 0x83 尝试（当前 token 逻辑可改）。
- `server319/lsg_client.py`：跨进程读 `conn`（vtable `0xD5A0C4` → `+0x398`，challenge `+0x5FC`/`+0x5F4`）。
- `runs/20261020-dump-ba3000/`：`code-ba3000.bin`、`code-ba3000.asm.txt`（0x83 handler）。
- 会话记录：`runs/20261020-session09..28/lsg.jsonl`。

## 0.4 业务帧类型已定位（2026-10-20 16:0x）

- `0xB765A0`（帧头解析）从**明文缓冲 offset 0** 读 1 字节作为业务 type。
- `0xB838A0` 的跳表：type 1→`0xB839D5`、2→`0xB83A09`、3→`0xB83A2F`、**4→`0xB83A4B`（tag 0x0A 大厅地址分支）**、5→`0xB83997`；其他值走默认错误路径。
- 调用链：`0x803780`（大厅轮询）→ `0x8037B8 call 0xB838A0` → type 4 → `0xB83A52 call 0xB769A0`（tag 0x0A）→ 写 `netobj+0x50/0x54` → `[+0x4F8]=1`。
- 已把 0x85 明文改为 `[u32 11][0x04][0x0A 0x08][127.0.0.1][4174]` 发出（`runs/20261020-session43` 的 `frame85_reply`）。
- **仍未成功**：客户端 23s 后 `与大厅服务器失去连接`。可能原因：帧没有被放入业务队列 `[0x84ABA7C]`（外层 0x85 布局/seq 问题），或 type 4 的 payload 需要更完整的 TLV。

## 0.5 ★ 里程碑：`DW_LOBBY_CONNECTED` 达成（2026-10-20 16:4x）

- LSG 服务端回 type 4 业务帧（`[u32 11][0x04][0x0A 0x08][127.0.0.1][4174]`）后，客户端状态机到达 **`DW_LOBBY_CONNECTED`**：
  ```
  ui_state([0x84ABA50]) = 4
  ready_4f8([netobj+0x4F8]) = 1
  business_queue([0x84ABA7C]) = 2
  conn_4f4([netobj+0x4F4]) = 非零
  ```
  证据：`runs/20261020-session46/patch.json`、`session47/patch.json`（采样 100 次，状态保持）。
- **关键修正**：**只发一次** type 4 帧（`frame85_reply beat=0`），**不要持续发心跳**——之前 `for _beat in range(8)` 会让客户端在第二次心跳后 `ConnectionAbortedError`（`与大厅服务器失去连接`）。
- 会话 `session47`：`DW_LOBBY_CONNECTED` 保持到采样结束（100 个 sample），`lsg.jsonl` 无 `key_error`。
- 截图：`runs/20261020-session47/screens/shot-*.png`（游戏窗口被前台文件管理器遮挡，需置前后重拍）。

## 0.6 通道保持问题（2026-10-20 16:4x 补充）

- `DW_LOBBY_CONNECTED`（ui=4/ready=1）在只发一次 type 4 后能保持 90-110 个采样，但**游戏仍会弹「与大厅服务器失去连接」**——说明 0x85 通道没有被正确维持，UI 层判定断线。
- 试过的心跳：空 16B、回显 84B、seq 固定、seq 递增，都会在 1-2 次心跳后 `ConnectionAbortedError`。
- 参考 `lsg_echo319.py` 的心跳用 `pt`（客户端请求的明文）作为载荷、`exp=conn+0x5EC` 作为序号、`b"\0"*8` 作为 tail；与本实现一致但仍有断开，说明还有一处差异（可能是 0x85 帧头 marker `0x01` vs `0xAB`、或 tail 需要非零）。
- **结论**：大厅状态机已跨过「连接大厅」，剩余问题降级为 **0x85 通道保活**；下一步聚焦 0x85 帧头与 tail 的精确字节。

## 0.7 保活卡点（2026-10-20 17:0x）

- 只发一次 type 4、之后**不主动发心跳**：`DW_LOBBY_CONNECTED` 保持，但客户端约 **10 秒**后弹「与大厅服务器失去连接」；`recv` 也**收不到**客户端的心跳帧（`plaintext_frame4` 从未出现）。
- 主动发 0x85 心跳（2s/5s、空 payload/回显、`0x01`/`0xAB` marker、seq 固定/递增）都会在 **第 2 次**发送后触发 `ConnectionAbortedError`。
- 参考 `lsg_echo319.py` 的心跳是在收到客户端 `GOT85` 后启动、每 2 秒回显 `pt`；本 build 的客户端似乎不接受主动 S2C 心跳，也不主动发心跳——更像是在等某个**特定的业务应答**（`0x47` 的回复）才会进入持续会话。
- **下一步**：从 `0x47` 的 body（`47030413 0810000000 ...`）反推应答结构；或对照 `svc80_responder` 的 `maybe_task` 规则，确认 1649370 是否用 `(svc, task)` 形式。

## 0.8 lstate=4（报废）的根因（2026-10-20 17:0x）

- 运行时采样：`DW_LOBBY_CONNECTED` 后 `[conn+0xC8]` 从 **2 变成 4**（报废），`fsm([conn+0x9C])` 变 0；`ui_state` 因此卡在 4（`0xB7A670` 要求 `[conn+0xC8]∈{1,2}` 才返回 2 → `[0x84ABA50]=5`）。
- `0xBA4430`（帧处理）只识别两类 `type`（`payload[0]`）：`0x81`（hello）和 `4`；其余全部走 `0xBA4530` → `call 0xBA3420` → `[conn+0xC8]=4`（报废）。
- 我们的 S2C 0x85 明文 `payload[0]=0x04`（type 4）→ 正好落进 `0xBA4510`（也是 `call 0xBA3420` 报废）；`0x86`/`0x85` 等则落默认报废。
- 说明 **1649370 的 S2C 业务帧不走 `0xBA4430`**（那是握手/控制帧处理器）；业务帧应经 `[netobj+0xB0]` 缓冲 → `0x803780` → `0xB838A0`（type 4 → tag 0x0A）。
- 下一步：找真正把 S2C 业务帧放进 `[0x84ABA7C]` 的处理函数（不是 `0xBA4430`），并确认 type-4 帧的外层封装。

## 0.9 内层类型尝试与 lstate 报废（2026-10-20 17:0x）

- 参考 §3 的帧布局：`加密帧=[u32 size][0xAB][0x85][u32 seq][16B IV][AES][8B]`；`明文=[u32 payload_len][u8 内层类型][payload]`；`业务载荷=[u8 业务类型(1..7)][6B 头][字段]`。
- 已试：内层 `0x86` + 业务类型 4 + tag 0x0A TLV（`session53`）→ 仍然 `DW_LOBBY_CONNECTED` 但 `[conn+0xC8]` 从 2 变 **4（报废）**，`fsm=0`。
- 说明：客户端的帧处理函数 `0xBA4430` 只认 `payload[0]` 为 `0x81` 或 `4`，其他（含 `0x86`/`0x85`）都走 `0xBA4530` → `0xBA3420` → `[conn+0xC8]=4`。我们的 S2C 帧很可能仍落在这条“控制帧默认错误”路径上。
- **未解**：1649370 的 S2C 业务帧到底走哪个函数、外层用哪个内层类型（`0x84/0x86/0x87/0x88/0x89` 中哪个是业务容器），以及 `[0x84ABA7C]` 的写入点（`probe_anchor` 对解密后的代码页扫描仍 0 命中，需修工具）。

## 0.10 内层类型扫描结果（2026-10-20 17:1x）

| 内层 | 结果 |
|---|---|
| `0x84` | `lstate` 2→4 立即报废 |
| `0x87` | 同上 |
| `0x86` | 同上 |
| **`0x88`** | **`lstate=2` 保持约 16 秒**（最好），之后仍变 4 |
| `0x88`+周期心跳 | 第 2 次心跳后 `ConnectionAbortedError` |
| `0x88`+业务类型 0x47 | `lstate` 2→4 报废 |

**结论**：`0x88` 是唯一能让连接状态保持的内层类型（ack 容器）；业务内容（`0x47` 应答）仍未知，缺它客户端会在 ~16 秒后自废 conn。下一步必须拿到 **1649370 的 0x47 应答字节**（真实抓包或参考实现的对应逻辑），否则只能继续盲试。

## 0.11 社区仓库最新与 1604220 服务端参考（2026-10-20 17:2x）

已 `git pull` 社区仓库到 `28368dd`（含 `d7ccb55` 的「Build 1604220 lobby reproduction kit」），解压 `releases/CODOL-1604220-server-repro-20261019.zip`（5.4MB）得到 `lib/codol_server/lobby.py`（29KB 大厅状态机）。

**参考给出的协议事实**（`lobby.py` docstring + 源码）：

```
step1       [u32 22][0x00][0x81][u32 220][u64 connId][8 zero]
step2       [u32 10][0x00][0x83][CHAL[8:16]]
A20   = SHA1(transcript)
K     = HMAC-SHA1(A20, session_key24)
keys  = HKDF(K,'BDDATA',72) -> T1 | T2 | aes_send | aes_recv
CHAL  = HKDF(K,'CLIENTCHAL',16)
evt4        inner 4, body = BB_UINT64_TYPE + u64(connId)
task_reply  inner 1, body = u64(txn) + u32(err) + u8(task) + u32(nres) + results
keepalive   发送裸 4 字节零 (b'\x00\x00\x00\x00')，每 20s；收到 4 零也跳过
```

注意：包内 **`wire.py`/`iips.py` 被刻意省略**（README 说「三个外部兼容模块自备」），所以 `a85_build` 的字节级实现拿不到。

**本轮实验（全部 `runs/20261020-*`）**：

| 内层/格式 | 结果 |
|---|---|
| `[len][04][0A 08 IP PORT]`（session48 形） | `lstate=2` 保持约 16s，无 peer_closed |
| `[len][88][04][0A 08 IP PORT]` | `lstate=2` 约 16s（inner-88 单发） |
| `[len][88][04]` + 零帧保活 | 1s 内 2→4 |
| `[len][04][0A+u64(1)]`（参考 evt4 body） | 客户端立即 `peer_closed` |
| `[len][04][0A 08 IP PORT]` + 零帧保活 | `peer_closed`，1s 内 2→4 |
| 收发同密钥（0x604） | 仍 `peer_closed` |

**关键推断（下一步核心）**：参考的会话密钥来自**握手 transcript 派生**（`A20/K/HKDF`），而我们从 `conn+0x604/0x608` 内存读取。用内存 key 能解开客户端→服务器方向，但服务器→客户端的 key 很可能与之不同，客户端解不开我们的帧就 `peer_closed`。**下一步应实现 SHA1+HMAC-SHA1+HKDF 派生，与 conn 内存值比对，确认 transcript 组成（28B hello + 26B gate + 153B 0x82）。**

## 0.12 conn 结构与 seq 的实测校正（2026-10-20 17:3x–17:5x）

`conn` 对象 `+0x5E0` 起的实测布局（两次运行）：

```
+0x5E0  01000000      = 1
+0x5E4  00000000      = 0
+0x5E8  02000000      = 2   (stage)
+0x5EC  0a131047 / 00000000  ← 不是 rxseq！含 "loba" 文本时说明这里是缓冲区
+0x5F0  6c6f6261 "loba" / 00000000
+0x5F4  ...            ← challenge 前的字段
+0x5FC  8B challenge
+0x604  指针 → [ptr+0x9C] 为 16B 密钥
```

- **`conn+0x5EC` 在 1649370 上不是接收序号**（1604220 的 `lsg_echo319.py` 用它当 `exp`，在 1649370 上会读出 `0x4710130a` 这类巨大值）。`server319.lsg` 已改为**回显客户端 0x85 帧里的 seq**。
- `0x82` 帧尾 8B 与 `conn+0x5FC` 的 challenge **不同**；`chal_search` 在客户端内存搜索帧尾只命中 EXE 常量和堆字符串（"certificate revocation list"），**说明客户端不缓存 `chal16[:8]`**，参考的 `CHAL[:8]==reply[-8:]` 自检在 1649370 上无法用内存比对验证。
- 用 `A20=SHA1(transcript)`/`K=HMAC-SHA1(A20, bytes(range(24)))`/`HKDF(CLIENTCHAL)` 对 14400 种 transcript 组合穷举，**没有**命中帧尾（`runs/derive_chal.py`），说明 1649370 的 transcript 组成或票据字段与 1604220 不同。
- `0xBA4430`（控制帧处理）的 `type` 取自明文 `payload[0]`：只认 `0x81` 和 `4`，且 **`4` 走 `0xBA4510` → `call 0xBA3420` → `[conn+0xC8]=4`（报废）**。因此 **S2C 业务帧不能直接用 type 4**，否则客户端主动废弃连接——这正是 `peer_closed` 的直接来源。
- 业务分派 `0xB838A0`（type 4 → tag 0x0A）是**另一条路径**（由 `0x8037B8` 调用、消费 `[0x84ABA7C]`），与 `0xBA4430` 无关。

## 0.13 seq 修正后的复测（2026-10-20 18:0x–18:3x）

- 用**客户端 0x85 帧里的 seq**（不再用 `conn+0x5EC`）重试了 `inner 0x04`、`inner 0x86 + 业务 4 + tag0x0A TLV`，结果仍是 `DW_LOBBY_CONNECTED`（ui=4、ready=1）后 **~8 秒弹「与大厅服务器失去连接」**，且 `lsg.jsonl` 记录 `peer_closed`。
- `chal_search` 的堆命中（如 `0x375ee7a9`）周围是「8 字节 tail + 一串对象字段」，**不是 16 字节 CHAL**，进一步确认客户端只保存 `CHAL[:8]`（即 0x82 帧尾），不保存 `CHAL[8:16]`；因此 0x83 用 `conn+0x5FC` 回显是可行做法，问题不在 0x83。
- 结合 `0xBA4430` 的分支语义（`payload[0]==4` → 报废），**S2C 加密帧的明文首字节不能是 0x04**；正确值只可能在 `0x81/0x84/0x86/0x87/0x88/0x89/0x90` 中，且必须让业务帧进入 `[0x84ABA7C]` 而不是走控制帧默认错误。

## 0.14 决定性证据：客户端根本没解开我们的 0x85 回复（2026-10-20 18:4x–19:5x）

新增探针 `frame85_seen`：发帧后立刻在客户端内存里搜**我们的明文头**和**密文头**。

```
frame85_seen pt []                    ← 明文从未出现
frame85_seen ct ["0x38b7a1ab"]        ← 密文在客户端内存里
```

**结论：客户端收到帧但解密失败**，随后 `peer_closed`。这排除了「帧结构/序号/marker」层面的所有猜测——问题在密钥或算法。

**密钥对象实测**：

| 偏移 | 实际内容 |
|---|---|
| `conn+0x604` → `[obj+0x9C]` | **真 AES 对象**（vtable `0x2055D900`），该 16B **能解开客户端 0x85**，即 C2S 密钥 |
| `conn+0x608` → `[obj+0x9C]` | **不是密钥对象**：内容是 `"...prise Services GmbH"`、`"DigiCert Inc"`、X.509 证书字节 |

所以 1604220 文档里「`0x608` 是接收密钥」在 1649370 **不成立**。

**已穷举的 S2C 密钥候选**（全部失败，`pt []`）：

- `[0x604]+0x9C`（对称复用）
- `[0x604]+0x14`（对象里的主密钥块）
- `[0x608]+0x9C`（证书数据）
- `[0x608]+0xAC`
- 回显客户端 96B 明文（`lsg_echo319` 的做法）
- 随机 IV / 固定 IV `16..31`、marker `0x01`/`0xAB`、seq 回显/固定

**下一步**：反汇编客户端 0x85 解密路径（`0xBA3A00` 附近，`0xBA4430` 的解密前置），定位它到底从哪个对象/偏移取 S2C 密钥，而不是继续盲试。

## 0.15 解密路径反汇编进展（2026-10-20 20:2x–21:2x）

新增 dump `runs/20261020-dump3/`（`0xBA0000`、`0xBA3000`、`0xB83000`、`0xB9A000`、`0x7F9000`）。

已排除：

- `0xBA41D0`：连接状态机（按 `[conn+0x9C]` 分支），不是解密。
- `0xBA0CC0`：3 条指令的谓词（`[conn+0x9C]==4`），不是解密。
- `0xBA24C0`：连接状态迁移 + 接收缓冲处理，不是解密。

`0xBA4430` 的调用顺序是 `0xBA24C0` → `0xBA41D0` → `[conn+0xC8]==2` 检查 → `0xBA0CC0` → 读帧头 `0xB765A0`，**真正的 AES 解密发生在别处**（很可能在 `0xBA0D10` 或 `0xBA0CF0` 一族的小函数里，或由 `0xB9BBB0`/`0xB9A000` 区域的传输层完成）。

**当前最硬的证据仍是** `frame85_seen`：密文进入客户端内存、明文从未出现 → 客户端解密失败。在找到它实际使用的 S2C 密钥来源前，继续换 marker/内层类型/IV 都是盲试。

## 0.16 继续排除（2026-10-20 21:3x–22:3x）

- `0xBA3C12 call 0xB73FE0` 属于 0x83 成功后的校验路径；`0xB73FE0` 反汇编后是**memcmp**（逐 4 字节/逐字节比较），不是加解密。
- `0xBA3C29 mov ecx,[esi+0x640]` 确认 `conn+0x640` 是 0x83 之后被使用的对象字段，但该路径只做状态检查，不产生密文。
- 新 dump：`runs/20261020-dump4/`（新增 `0xB73000` 区域）。
- 仍未定位客户端对 S2C 0x85 的 AES 解密调用点；`0x604` 对象的 `+0x9C`（C2S 可用）与 `+0x14`（试作 S2C，失败）都不是 S2C 密钥。

**方法论调整**：继续在 `0xB7xxxx`/`0xBAxxxx` 大范围盲扫代价过高。下一步改为**从数据反推**：在客户端进程里对 `0x604` 对象做**全字段 16 字节窗口**枚举（每个偏移取 16B），逐一用于加密同一明文，然后**发一次**看客户端是否不再 `peer_closed`；只要能解开一次，就能定位 S2C 密钥偏移。

## 0.17 零补丁分析（1604220 P2/P3）与 80/230 应答（2026-10-20 22:5x–23:5x）

解压 `他人文件参考/零补丁分析-20261019.7z` 到 `runs/20261020-zeropatch/`，其 README 给出 1604220 的零补丁判定链：

```
P2  = 0x6BBF30: ([0x331C5C0]==1 && CS==4) || D   (D = *[0x3306D60]+0xC 非零)
      CS=4 时若 D=false，强行让 P2 通过会进 G=1 分支阻止跳到 G=2
P3  = publisher 的 80/230 ready 字节；缺它后续阶段必失败
CS  = 连接状态：7F2CE0 在 Auth code700 成功后写 CS=9，只有 CS=9 才发 DW_ACCOUNT_LOGIN_COMPLETE
task_reply = inner 1, body = u64 txn | u32 err | u8 task | u32 nres | u32 nres | results
```

对照 1649370 实测：

- `DW_ACCOUNT_LOGIN_COMPLETE` 已出现 → **CS=9、P2 已过**。
- `[conn+0xC8]=4` 就是文档里的 **CS=4**，是「已连接」而非「报废」——之前对 lstate 的解读需要修正。
- `ui_state=4`（`DW_LOBBY_CONNECTED`）后卡在 4 而非 5，对应 **P3 未 ready**。

本轮已按 `task_reply` 构造 **inner 1 + 80/230 playerdata**（`u64 txn=1 | u32 err=0 | u8 230 | u32 nres=1 | u32 nres=1 | level=70 | prestige=0 | gp/cp=999999999 | n_ent=0 | n_flags=0`）发出（`runs/20261020-p3b` 的 `frame85_reply`）。

**但** `frame85_seen pt []` 仍是空：**客户端依旧解不开我们的密文**。也就是说 P3 应答的内容已经对了，卡点回到「S2C 加密密钥」——`0x604+0x9C` 只能解 C2S 方向，客户端解密所用的 `aes_recv` 仍未找到（`+0x14/+0xAC/+0xBC/+0xCC` 以及对称复用都已排除）。

## 0.18 根因层级推进：CS=4 下控制帧处理函数直接返回（2026-10-20 23:5x–00:0x）

`0xBA4430` 的入口反汇编：

```asm
0xBA445A  cmp dword ptr [esi+0xC8], 4
0xBA4461  jne 0xBA4479
0xBA4463  xor al, al
0xBA4476  ret 8            ; CS==4 → 不处理任何帧，直接返回 false
0xBA4479  call 0xBA24C0    ; 只有 CS!=4 才进入收包/状态机
```

结合零补丁文档（CS=4 需要 D=`*[0x3306D60]+0xC` 非零才算通过）：

- 客户端发出 0x85 后进入 **CS=4**；
- 之后所有到达的帧都**不会**进入解密/分派逻辑（`0xBA4430` 直接返回）；
- 于是 `frame85_seen pt []` 成立——密文只在接收缓冲里，从未被解密；
- 约 8–10 秒后客户端判定大厅无响应 → `peer_closed` + UI 报「失去连接」。

**这解释了为什么所有密钥/格式尝试都无效**：不是解不开，是**根本没解**。

**修正后的下一步**：不要再调帧格式，改为找 **CS=4 状态下真正消费业务数据的地方**，即 `0xB7A670`（大厅连接状态）与 `[0x84ABA7C]`（业务队列）的填充者；并验证 D 条件 `*[0x3306D60]+0xC`。

## 0.19 完整因果链：type 4 帧把 lstate 推到 4，之后客户端拒绝一切帧（2026-10-21 00:1x）

`0xBA0780`（连接状态查询）反汇编：

```asm
cmp dword [ecx+0x644], 0     ; crypt 建立了吗
mov eax, [ecx+0xC8]          ; lstate
je 0xBA079F                  ; crypt==0 分支
cmp eax,2 ; je -> return 2
cmp eax,1 ; jne -> return eax
mov eax,2 ; ret              ; crypt!=0 且 lstate∈{1,2} → 2
0xBA079F:
cmp eax,2 ; jne -> return eax
cmp dword [ecx+0x5E8],3
sete al ; inc eax           ; crypt==0 且 lstate==2 且 stage==3 → 2，否则 1
```

`ui_state` 要到 5，`0xBA0780` 必须返回 2，条件只有两条：
- **A**：`[conn+0x644]!=0`（crypt 建立）且 `lstate∈{1,2}`；
- **B**：`[conn+0x644]==0` 且 `lstate==2` 且 `[conn+0x5E8]==3`（stage 3）。

而实际发生的是：

```
客户端发 0x85（lstate=2）
→ 我们回 payload[0]=4 的帧
→ 0xBA4430 在 lstate==2 时进入，0xBA450C cmp al,4 命中
→ 0xBA4510 → call 0xBA3420 → mov [conn+0xC8],4
→ 此后 0xBA4430 一进门就 cmp 4 / ret，所有帧都不再解密
→ 约 8 秒后 peer_closed +「与大厅服务器失去连接」
```

**结论**：`payload[0]=4` 恰好是「报废」分支；`0x86/0x88/0x01` 等也都会落到 `0xBA4530` 的默认报废路径。`0xBA4430` 只服务握手帧（`0x81`/`0x83`/`0x90`），**真正的 0x85 明文分派在另一个函数**（0x83 成功后的加密通道处理），必须在它那里把 `crypt`/`stage` 推进，而不是靠控制帧类型蒙。

**下一步**：定位 0x83 成功后接收加密帧并解密的函数（`0xBA3A00`–`0xBA3D00` 区间之外的 `0xBA17D0` 一带），确认它写入 `[conn+0x644]`（crypt）与 `[conn+0x5E8]=3`（stage 3）的时机。
