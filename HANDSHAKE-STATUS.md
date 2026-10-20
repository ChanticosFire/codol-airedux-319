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
