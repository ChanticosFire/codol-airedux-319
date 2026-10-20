# CODOL 1604220 大厅 pump 状态机技术说明

面向后续研究者。本文只写**有实证支撑**的结论，每条都标注证据来源（反汇编地址 /
运行时读数 / 日志）。未证实的一律标注为"未证实"。

适用 Build：**1604220**（产品标签 3.19.26.17，社区称 3.19.26.13）
EXE SHA-256：`3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f`
EXE 大小：7,842,456 字节
image_base：`0x400000`

最后更新：第 188 轮（2026-10-26）。**本文已按最新发现重写，取代旧版。**

---

## 1. 一句话结论

**pump 每帧做一次"收包 → 组装 136 字节记录 → 交给 `Add` → 读状态 → 检查三道守卫 →
必要时推进前端"的循环。当前断点是收包只拿到 3–4 字节（两个探测包），
远不足以构成一条 136 字节记录，因此 `Add` 永远走"未就绪"分支，
状态码停在 1，`[lobby+0x1F4]` 永远是 1，前端梯永不推进。**

**服务端必须返回至少 136 字节的记录，这条链才可能往下走。**

---

## 2. 完整每帧循环（实证）

地址来自 `0xBAD800` 起的主函数反汇编 + 运行时轮询。

```
pump (0xBAD800)
│
├─ 0xBAD83D  cmp byte [lobby+8], 0       入口门 1
│             je 0xBAE7C6                实测 [lobby+8] = 1，门开着
│
├─ 0xBAD846  cmp dword [lobby+0x1F4], 1  入口门 2
│             jne 0xBAE7C6               要求 1F4 恰为 1
│
├─ 0xBAD862  三个守卫标志清零
│   0xBAD862  mov byte [ebp-0x989], 0
│   0xBAD869  mov byte [ebp-0x986], 0
│   0xBAD876  sete byte [ebp-0x988]      ← 来自 [ebx+0x4D70] == [ebx+0x18]
│
├─ 0xBAE215  lea ecx, [ebp-0x768]        收包目标缓冲
│   0xBAE21B  call 0xB753A0              初始化
│   0xBAE220  mov ecx, [lobby+0xC]       网络端点对象
│   0xBAE225  mov eax, [eax+0x1C]        ★ vt+0x1C = 收包（0xC73FB0）
│   0xBAE228  push 0x508                 1288 字节缓冲
│   0xBAE242  call eax                   ★ 收包
│   0xBAE244  mov esi, eax               ★ esi = 收到的字节数
│
├─ 0xBAE24E  push esi / push [ebp-0x548] 字节数 + 数据
│   0xBAE256  sub esp, 0x88              136 字节
│   0xBAE26B  call 0xB753C0              复制成一条记录
│
├─ 0xBAE276  call 0xBBA3F0               ★ Add(obj1)
│   （Add 内部见 §4）
│
├─ 0xBAE281  call 0xBBA1E0               读 obj1 状态
│   0xBAE286  cmp eax, 1
│   0xBAE289  je 0xBAE292                 状态 == 1 则跳过
│   0xBAE28B  mov byte [ebp-0x989], 1     ★ 状态 != 1 时置第二道守卫
│
├─ 0xBAE292  cmp [lobby+0x1FC], edi      服务器列表对象 vs ebx+8
│   0xBAE298  je 0xBAE2DD                 相等则直接去守卫
│   0xBAE2CD  call 0xBBA710              调用后
│   0xBAE2D2  test al, al
│   0xBAE2D4  jne 0xBAE2DD               返回值 != 0 则不去置位
│   0xBAE2D6  mov byte [ebp-0x986], 1    ★ 返回 0 时置第三道守卫
│
├─ 0xBAE2DD  三道守卫检查
│   0xBAE2E4  je 0xBAE7B4                [ebp-0x988] == 0 -> 复位
│   0xBAE2EA  je 0xBAE7B4                [ebp-0x989] == 0 -> 复位
│   0xBAE2F7  je 0xBAE7B4                [ebp-0x986] == 0 -> 复位
│
├─ 0xBAE304  mov ecx, [lobby+0x1F8]      obj1
│   0xBAE30A  call 0xBBA1E0              读状态
│   0xBAE30F  cmp eax, 2                 ★ 要求状态 == 2
│   0xBAE312  jne 0xBAE5DB               否则跳过 1F4 推进
│
├─ 0xBAE31E … 0xBAE5C3                   一系列检查
│   0xBAE5E6  mov eax, [ebx+0x130]       索引
│   0xBAE5F3  lea edx, [eax+1]
│   0xBAE5F6  mov [ebx+0x130], edx       索引 + 1
│   0xBAE5FC  cmp eax, ecx               旧索引 vs 容量
│   0xBAE5FE  jae 0xBAE613
│   0xBAE60C  call 0xBBA1F0              未满 -> 发包
│
├─ 0xBAE587  mov dword [lobby+0x1F4], 2  ★ 推进前端（实测从未执行）
│
└─ 0xBAE7AC  mov dword [lobby+0x1F4], 1  复位
```

---

## 3. 状态码 `[serverlist+0x1A0]` 的语义

**实测位置：`serverlist = [lobby+0x1FC]`，状态码在其 `+0x1A0`。**

| 码 | 含义 | 证据 |
|---|---|---|
| 0 | 未初始化 | 反汇编 |
| **1** | **等待（pending）** | `0xBBA710` 对 1/2/3 返回 1 |
| **2** | **`Add` 成功写入 2 后的状态** | §12.164 实测可达 |
| 3 | 另一中间态 | `0xBBA62B` 写 3 |
| **4** | **就绪（有数据）** | `0xBBA730` 只对 4 返回 `[0x19C]` |
| **5** | **发送失败** | `0xBBAAAC` 写 5（`0xBBA8C0` 返回 0） |

**写入点（全部 7 处，另有 1 处死代码）：**

| 地址 | 值 | 条件 |
|---|---|---|
| `0xBB76BB` | 0 | 构造/清理 |
| `0xBBA0A4` | `esi` | 未详 |
| `0xBBA1C7` | 0 | 清理 |
| `0xBBA33E` | 0 | 未详 |
| `0xBBA3D2` | **1** | `Init`，`dw=2` 时运行一次 |
| `0xBBA569` | **2** | `Add` 成功分支 |
| `0xBBA62B` | **3** | `Add` 容量满 |
| `0xBBA900` | **4** | 类型 `0x15` 消息路径 |
| `0xBBAAAC` | **5** | 发送失败 |
| ~~`0xBBA2B6`~~ | ~~4~~ | **死代码，无跳转可达** |

---

## 4. `Add`（`0xBBA3F0`）的完整逻辑

`ret 0x90`——144 字节参数。

```
0xBBA426  cmp dword [ebx+0x120], 1     要求状态 == 1
0xBBA42A  jne 0xBBA635                  否则返回
0xBBA43A  mov edi, [ebp+0x94]           ★ count
0xBBA442  jle 0xBBA5C3                  count <= 0 -> 走推进分支

成功分支（count > 0）：
0xBBA448  … 构造容器、比较、追加 …
0xBBA465  je 0xBBA5A5                   ★ 过滤 A（比较结果 == 0 则跳过）
0xBBA483  je 0xBBA5A5                   ★ 过滤 B（追加失败则跳过）
0xBBA55E  push 0x63
0xBBA569  mov dword [ebx+0x120], 2      ★ 写 2
0xBBA5CA  jne 0xBBA635                  返回

推进分支（count <= 0）：
0xBBA5C3  cmp dword [ebx+0x120], 1
0xBBA5CA  jne 0xBBA635
0xBBA5E6  mov eax, [ebx+0x130]          索引
0xBBA5F6  mov [ebx+0x130], edx          索引 + 1
0xBBA5FC  cmp eax, ecx                  旧索引 vs 容量
0xBBA5FE  jae 0xBBA613                  已满
0xBBA60C  call 0xBBA1F0                 未满 -> 发包
0xBBA611  jmp 0xBBA635                  返回
0xBBA613  … 0xBBA620  jb 0xBBA635
0xBBA62B  mov dword [ebx+0x120], 3      写 3
```

**两个过滤分支的编码：**

```
0xBBA465  0F 84 3A 01 00 00   je 0xBBA5A5
0xBBA483  0F 84 1C 01 00 00   je 0xBBA5A5
```

**§12.163 已用哨兵法证明：把这两条各改成 6 个 `nop`（`90 90 90 90 90 90`）后，
`0xBBA569` 的哨兵立刻出现且稳定——它们就是唯一的过滤。**

**§12.164 证明：只打这两个补丁，状态会从 1 变成 2 并稳定保持（1883 次采样）。**

---

## 5. 类型 `0x15` 消息路径

**这是把状态推进到 4 的唯一路径，且完全在 pump 内部（§12.202/§12.203）。**

```
pump 0xBAE2C2  call 0xBBADE0(serverlist, &136字节)
  └─ 0xBBAE3A  call 0xBBAAF0           （全镜像唯一调用者）
       ├─ 0xBBAB33  test edi, edi       ① 长度 > 0
       ├─ 0xBBAB57  call 0xBC1D20       ② 解析，须返回 1
       ├─ 0xBBAB66  call 0xBC1CB0       ③ 取类型
       ├─ 0xBBAB6B  cmp al, 0x15        ④ 类型须 == 0x15
       └─ 0xBBAB7C  call 0xBBA900       ⑤ 状态 = 4
```

**消息格式（由 `0xBC1D20` 反汇编得出）：**

```
[1 字节类型 0x14..0x1D] [2 字节 word（须为 1 或 2）] [4 字节] [2 字节]
                                                        ↑ 共 9 字节最小
```

**`0xBBAB4C push esi` / `0xBBAB4B push edi`——`esi` 是数据指针，`edi` 是长度。**

---

## 6. 发送链（`0xBBA760` → `0xC73F30` → `0xBB1420`）

```
0xBBA760(this, ptr, buf, len)
  ├─ 0xBC1C20  序列化到 1288 字节缓冲，长度写入 [ebp-0x510]
  └─ 0xBBA7C0  ecx = [this] -> vtable
     0xBBA7C4  eax = [vt+0x18] = 0xC73F30（发送）
     0xBBA7CF  push edi（= this+4，指针，不是类型值）
     0xBBA7D0  call eax

0xC73F30(this, ptr, buf, len)
  ├─ 0xC73F57  call 0x853A10        恒等函数（mov eax,ecx; ret）
  ├─ 0xC73F6C  call 0xB754C0        返回 [ptr+0x84] 的 word
  └─ 0xC73F88  call 0xBB1420        ★ 真正的发送

0xBB1420
  ├─ 0xBB143B  cmp [ebp+8], -1      检查 INVALID_SOCKET，等于则返回 -10
  ├─ 0xBB146A  sockaddr.sin_family = AF_INET
  ├─ 0xBB1477  call [0xCA8550]      端口字节序转换
  ├─ 0xBB1485  sockaddr.sin_port = ax
  ├─ 0xBB1492  call [0xCA8518]      ★ sendto
  └─ 0xBB149C  jns 成功 / 否则查错误跳表 0xBB157C
```

**成功条件（`0xBBA7D6`）：`sendto` 返回值必须 `> 0` 且 `== 序列化长度`。**

**调用点的栈平衡（§12.200 已核准）：**

```
push ecx (0xC73F66)  4      ← 这两个 push 是给 0xB754C0 的，
push esi (0xC73F67)  4        但它是裸 ret，不清理，留在栈上
push edx (0xC73F77)  4
sub esp,0x84 (0xC73F78) 132
push eax (0xC73F85)  4
                     ---
合计                148 = 0x94   ← 与 add esp,0x94 完全吻合
```

---

## 7. 关键对象与字段（全部实测）

```
lobby = [0xE85C68]
  +0x00  vtable = 0x00D5A9D0
  +0x04  0（§12.177 曾误读为 socket，实为无关字段）
  +0x08  1（pump 入口门 1）
  +0x0C  网络端点对象（vt+0x18=发送 0xC73F30，vt+0x1C=收包 0xC73FB0）
  +0x14  4
  +0x18  3
  +0x1C  0x0C02（3074）
  +0x1F4 前端梯标志（1 = 等待，2 = 推进；实测恒为 1）
  +0x1F8 obj1（列表容器，`[obj1+0x120]` = 状态码）
  +0x1FC serverlist

serverlist = [lobby+0x1FC]
  +0x84  2              （类型/标识，不是端口）
  +0x88  0x0C02 = 3074  （端口）
  +0x8C  0xFF00FF00     （地址字段）
  +0x19C 结果码（状态 == 4 时有效）
  +0x1A0 状态码
  +0x1A4 byte 标志

p = [serverlist] = 0x37xxxxxx
  +0x00  vtable = 0x00D95558
  +0x04  socket 句柄（实测 11624，有效）
```

**注意**：`[serverlist]` 指向的对象带 `0x00D95558` vtable，其 `+4` 是 socket。
**`0xC73F74 mov eax,[ebx+4]` 里的 `ebx` 就是这个对象，不是 lobby。**

---

## 8. 工具与已知陷阱

| 工具 | 用途 | 陷阱 |
|---|---|---|
| `tools/branch_map.py` | 列出区间内所有跳转及目标 | **必须**用全镜像范围 `--lo 0x400000 --hi 0xDD0000`，默认范围会假阴性（§12.202） |
| `tools/branches_to.py` | 查某地址的调用者 | 同上 |
| `tools/find_offset.py` | 搜结构偏移的 disp32 | 偏移需按 `0xFFFFFxxx` 形式传（如 `[ebp-0x768]` → `0xFFFFF898`） |
| `tools/dump_code.py` | 反汇编 | **起点必须是已知指令边界**，否则整段错位（§12.182 因此误判过） |
| `tools/probe_reg.py` | hook + 寄存器采样 | 条件分支类挂点会崩 |
| `tools/sentinel_*.py` | 只改立即数 + 轮询 | **最可靠**的观测手段 |
| `tools/watch_statecode.py` | 等客户端可读后轮询状态码 | 必须用，不能 `-SkipWait` 后立刻轮询 |

**方法论教训（都踩过）：**

1. **读结构字段前必须核对完整寻址链**——§12.196 因漏了 `[serverlist]` 一级，
   得出"socket 从未创建"的错误结论。
2. **反汇编起点错了整段都错**——先找 `push ebp / mov ebp,esp` 或已知指令边界。
3. **任何"命中次数 < 预期"的观测，先排除客户端已崩溃。**
4. **栈平衡算术是验证理解的好手段**——§12.200 用它发现了两个未清理的 push。

---

## 9. 当前阻塞点与下一步

**阻塞点**：`0xBAE242` 的收包只返回 3–4 字节（探测包），
不足以构成 136 字节记录，`Add` 永远走 `count <= 0` 分支。

**要打开这条链，服务端需要：**

1. 在 UDP 3074 上返回**至少 136 字节**的记录，使 `Add` 的 `count > 0`；
2. 并让记录通过 `0xBBA465`/`0xBBA483` 两个过滤（条目不重复 + 追加成功）；
3. 之后 `Add` 会写状态 2，`0xBAE30F` 的门槛满足；
4. 再提供一条**类型 `0x15`** 的消息（格式见 §5）把状态推到 4。

**已验证的辅助手段**：若要单独验证后续环节，可对
`0xBBA465` 与 `0xBBA483` 各打 6 字节 `nop`，此时状态会稳定变成 2
（§12.163/§12.164），但 `1F4` 仍不变，因为状态 2 只满足
`0xBAE30F` 的第一道要求，后面还有索引/容量与三道守卫。

**下一轮该做什么**：先弄清 `0xBC1D20` 期望的 136 字节记录**具体字段布局**
（反汇编 `0xB770F0`、`0xB75720` 的组合），然后在 `lobby_udp.py` 里
构造一条能通过 `Add` 两个过滤的记录，观察状态是否自然变成 2。
