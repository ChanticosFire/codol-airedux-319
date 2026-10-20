# LSG 握手现状（2026-10-20 下午，给 Codex / 用户）

> 承接 [HANDOFF-TO-CODEX.md](HANDOFF-TO-CODEX.md)。Codex 修好了 Auth schema 与票据，客户端已经**真正连上 4174 并走完门控**；现在卡在 **0x83 token 应答**。本文只写实测与反汇编能钉死的部分。

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
