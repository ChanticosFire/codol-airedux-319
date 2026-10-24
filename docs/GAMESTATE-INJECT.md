# 客户端侧 gamestate 注入实验（2026-10-24 12:39–12:41）

目的：绕开 `ring_bridge` 的收发链路，直接把 `challengeResponse` + `connectResponse` + gamestate
写进客户端的 loopback 接收环，看能否把 `net_state` 推到 9/10 并让 `ui_state` 离开 0/5。

工具：`tools/inject_client_gamestate.py <gamestate.bin>`（项目自带）。
gamestate 样本：`runs/gamestate-3426.bin`（2697 抓包重组，3426 字节）。

---

## 1. 结果

| 步骤 | 观测 |
|---|---|
| 注入前 | `net_state=1`、`ui_state=0`（主菜单） |
| 注入 3 条消息（33 B / 106 B / 3426 B）入环 | `connection=0x1338aa80`，3 个 slot 写入，`cursor_after=3` |
| 注入后 8 s | **`net_state=5`**、`ui_state=0` |
| 之后 30 s（每 5 s 采样） | `net_state=5` 稳定、`ui_state=0` 稳定 |
| `ring_bridge pump --settle 0.5` ×5 | `net_state=5`，`ring_b` `read=write=3`（已消费），`ring_a` `read=write=0`（客户端未发包） |

结论：**`challengeResponse` 被客户端接受**（state 1→5，比此前只能到 3/4 前进一步），
但 `connectResponse`/gamestate 没有把状态推进到 9；客户端也没有主动发包（`ring_a` 为空）。

## 2. 解释

`inject_client_gamestate.py` 只做三件事：写 connection 的 netadr、把三条消息塞进接收环、把
`net_state` 写成 3。它**不调用** `CONNECT_FN`（`0x5BE730`），所以客户端没有进入"主动 connect"
的分支，`connection_state` 始终为 0；收到 `challengeResponse` 后停在 5（challenging 完成），
后面的 `connectResponse` 不在它当前等待的消息类型上。

`ring_bridge connect` 会调用 `CONNECT_FN`（写地址 + 触发 connect），
`ring_bridge pump` 只调用 `PUMP_FN`（`0x4F8D70`）——两者需要**按顺序组合**，而不是只注入响应。

## 3. 下一步（下一轮）

1. **顺序修正**：`ring_bridge connect --address 127.0.0.1:29000`（调 `CONNECT_FN`）→
   再 `inject_client_gamestate.py` 注入 3 条消息 → 再 `pump`；
   观察 `ring_a` 是否出现客户端发出的 getchallenge/connect。
2. 若 `ring_a` 有包，接 `forward` 转发给 `server1649370`，让服务端按正常状态机回包。
3. 若客户端始终不发包，检查 `CONNECT_FN` 的返回值与 `connection_state`（0 是否表示未初始化），
   必要时在调用 `CONNECT_FN` 前补 `drain`/`pump`。
4. 只有 `net_state` 到 9 且 `ui_state` 变化，才算这一层打通；`ui_state` 仍 5 时才回到 `0xBA3xxx` 状态机。

## 4. 2026-10-24 12:42–12:45：load/const 配套性修复后，state 到 6

### 4.1 找到并修掉一个真实的不配套

overlay 里的 `mp_cross_fire_load.ff`（24,853，sha `0b04da67…`）与 `mp_cross_fire_const.ff` 是 **2026-10-22 的旧版**，
而主 `mp_cross_fire.ff` 已在 12:02 换成 V70 提取的新版（37,331,221）。**主件换新、load/const 仍旧版**，
客户端加载时报 **"磁盘读取错误"**（IIPS 上下文 `0:0:mp_cross_fire_load-1044`）。

已把 `mp_cross_fire_load.ff`（sha `dd9caec4…`）与 `const.ff` 换成 `runs/ifs-merge/extracted/` 里的同源版本，
旧件备份为 `runs/ifs-merge/baseline_mp_cross_fire_load_*.ff`。

### 4.2 重跑完整流程的结果

流程：`inject_client_gamestate.py`（注入 3 条消息）→ `ring_bridge connect`（调 CONNECT_FN）→
`server1649370.gameserver` + `ring_bridge forward` → 连续 `ring_bridge pump`。

| 观测 | 结果 |
|---|---|
| 服务端 | `in oob connect` → `out oob`×4 → `in oob stats` → `out fragment`(gamestate) → snapshot×32 → `in oob heartbeat`×3 |
| 客户端 | `net_state` **1→6**（历史最深，此前 5），`ui_state=0` |
| 20 s 后 | `net_state` 复位 0 |
| 错误 | `EXE_ERR_SERVER_TIMEOUT`（不再是"磁盘读取错误"） |

**结论**：load/const 不配套确实是"磁盘读取错误"的原因，已修复；现在卡点前移到
**客户端在 state 6 等待服务器响应超时**——gamestate 已发出但未被接受（或后续 netchan 确认缺失）。
下一步应查 gs 的 gamestate 分片 seq/ack 与客户端 netchan 期望，并给 `heartbeat` 补响应。

## 5. 2026-10-24 12:46–12:48：单条注入与状态机顺序

新增 `tools/inject_one.py`：一次只往 loopback 接收环写**一条**消息（challenge / connect / gamestate / raw），
并可设定 `net_state`，用于把客户端逐步从 3 → 5 → 6 → 9 走过每一档。

实测（客户端已在主菜单）：

| 步骤 | 观测 |
|---|---|
| `ring_bridge connect --address 127.0.0.1:29000` | `state=4`，`ring_b=0` |
| `inject_one --kind challenge --set-state 3` | `state_before=4`，`state_after=3` |
| `pump` ×3 | **`state` 回到 4** |

解释：`connect` 已经让客户端进入"已发起 connect、等待 connectResponse"的 4 档；
此时再补 `challengeResponse` 不属于它当前等待的消息，状态机重新评估后回到 4。
→ **挑战阶段必须在 connect 之前完成**：正确顺序是先 `inject_one challenge`（3→5），
再注入 `connectResponse`（5→6），最后 `gamestate`（6→9），每步之后 `pump` 并采样。

`inject_client_gamestate.py` 一次性塞 3 条消息、随后又被 `ring_bridge connect` 把状态改成 4，
正好破坏了这条顺序；这解释了两轮里"注入后 state 只到 4/6"的现象。

## 6. 2026-10-24 12:49–12:51：分步注入走到 5，gamestate 未被接受

按"先 challenge、再 connectResponse、最后 gamestate"的顺序，用 `inject_one.py` 分三步注入，
每步后 `ring_bridge pump` 并采样：

| 步骤 | `state_before` | `state_after` | pump 后 |
|---|---|---|---|
| `--kind challenge --set-state 3` | 1 | 3 | **4** |
| `--kind connect` | 4 | 4 | **5** |
| `--kind gamestate --file runs/gamestate-native.bin` | 5 | 5 | **5** |

- 前两步顺序正确：challenge 把客户端推进到 4，connectResponse 再推到 5；
- 第三步 `gamestate`（`build_native_gamestate` 的 90 字节）**没有**把 5 推到 9，`ui_state` 仍 0。

解释：`challengeResponse`/`connectResponse` 是 OOB，客户端从环里取出后直接处理；
gamestate 是 inband（带 `svc 0x03`），客户端要用 **netchan 序号** 与它当前期望的 seq 对齐后才会解析。
`inject_one` 写入的是裸 svc 数据（前 4 字节 ack 为 0），没有携带客户端期望的递增 seq，
因此被当作"过期/重复"消息丢掉。

下一步：在注入 gamestate 前，先读出客户端当前的期望 seq（`connection` 对象或 `ring_a` 的写序号），
把 payload 的 netchan 头改成该 seq；或改走 gs 的真实分片（它带 `seq|0x80000000` 与 XOR key）。

## 7. 2026-10-24 12:49–12:52：state 6 是稳定卡点

两个变量都排除了：

| 变量 | 设置 | 结果 |
|---|---|---|
| gamestate 延迟 | `--delay-send 0`（connect 后立即发） | `state=6`、`ui=0` |
| snapshot 序号起点 | `--snapshot-seq 1`（从 1 递增） | `state=6`、`ui=0` |

两轮服务端日志都完整：`connect → out oob×4 → stats → gamestate 分片 → snapshot`，
客户端也在发 `heartbeat`；但 `net_state` 稳定停在 **6**，不再前进。

静态补充：`0x76446B0` 的**立即数**写入只有 5 处 ——
`0x470467=3`、`0x5BE90A=7`、`0x5BEA8B=4`、`0x77C343=0`、`0x813D34=7`；
**没有直接写 5/6/9/10 的立即数**，5/6 一定是由寄存器写入（`mov [0x76446B0], eax/ecx`）。
`0x5BE730` 是 `CONNECT_FN`，`0x5BEA8B` 写 4 就在它附近 —— 下一轮应反汇编 `0x5BE900–0x5BEB40`，
找出 5→6 的写入点及 6 的等待条件（很可能是"等 svc 消息/等 netchan ack"）。

### 下一步

1. 反汇编 `0x5BE900–0x5BEB40`，定位 `mov [0x76446B0], reg` 的 5/6 写入；
2. 从写入点向回找条件跳转，确认 6→9 需要什么消息/字段；
3. 按条件补服务端消息（而不是继续换 seq/delay）。

## 8. 2026-10-24 12:52–12:55：connect 状态机反汇编

`0x5BEA40–0x5BEB19`（`CONNECT_FN` 尾部）的实际结构：

```asm
0x005BEA45  cmp  dword ptr [0x76446B0], 5     ; 只有 state==5 才进
0x005BEA53  jne  0x5BEA80
0x005BEA55  call 0x7F9090                     ; 取连接对象
0x005BEA5A  mov  ecx, [eax+0x30]
0x005BEA6A  xor  edx, [eax+0x11128]           ; 解码 key
0x005BEA71  mov  byte ptr [eax+0x1112C], 1
0x005BEA78  mov  [eax+0x20], edx
0x005BEA7B  call 0x7F85C0
0x005BEA80  push 0x1398 / 0 / 0x7888788
0x005BEA8B  mov  dword ptr [0x76446B0], 4     ; 无条件写 4
0x005BEA95  call 0xC42DE0                     ; memset(0x7888788,0,0x1398)
0x005BEA9A  eax = [0x331C0C8] ^ 0xD362501F    ; 解码 connection
0x005BEAAA  mov  [eax], ecx
0x005BEAAF  lea  esi, [eax+0x14]
0x005BEAB7  mov  dword ptr [eax+0x30], 0xFFFFF448
0x005BEAEA  call 0x5C05F0                     ; 发 getchallenge
```

结论：
- **`state==5` 是"连接对象就绪"的分支**：它做一次连接对象解码/初始化，然后**无条件把 state 写回 4**，
  紧接着调用 `0x5C05F0` 发 getchallenge。这正是"注入 challengeResponse 后状态回到 4"的机制。
- state 5/6/9/10 都**不是立即数写入**：`0x76446B0` 的立即数写入只有 3/7/4/0/7 五处，
  也没有 `A3`（moffs）写入；5/6 一定由寄存器/间接写入，需要动态 hook 或继续找 `mov [reg], eax`（reg 来自 `lea`）。

### 下一步

1. 动态：在 `0x5C05F0`（发 getchallenge）与 `0x7F85C0` 下断点，记录 state 6 时客户端正在等什么；
2. 静态：从 `0x5C1678`（challengeResponse 分支）向前找 `mov [0x76446B0], reg` 的 5/6 写入；
3. 服务端侧同时把 gamestate 的 netchan seq 从 3 改成 1（`_send_fragments` 的 `seq = 3 + count` 写死），
   因为客户端第一个可靠包通常期望 seq=1。

## 9. 2026-10-24 12:55–12:58：gamestate seq 改 1 仍被拒

改动：`server1649370/gameserver.py` 的 gamestate netchan seq 由 `3 + count` 改为 `1 + count`
（注释：客户端第一个可靠包期望 seq=1，从 3 开始会被当重复包丢弃）。

重跑结果：

| 观测 | 结果 |
|---|---|
| gs 日志 | `fragment seq=1 message=gamestate chunk=90`，snapshot seq 1..11 |
| bridge dump | gamestate 包**确实注入**了：`01000080 00 00 8a04 5a00 0000…`（seq_word `0x80000001`、index 0、count-1 0、frag_size 1162、len 90） |
| 客户端 | `state=6` 稳定 **24 秒**，随后复位 0（服务器超时） |

→ **不是 seq 问题**。客户端收到了带正确 seq 的 gamestate 分片，但没有接受。
剩下的差异只可能在 **fragment 头字段语义**（`count` 是"总数"还是"末片索引"、`frag_size`/`len` 的顺序）
或 gamestate 负载本身的格式。

### 下一步（最有把握）

用 2697 真实服务器的抓包做对照：`runs/snapshot-2697-*.bin`、`runs/servercmd-2697-*.bin` 是抓到的真实包，
直接比较它们的分片头字节与 gs 生成的 `01000080 0000 8a04 5a00…`，找出字段顺序/语义差异，
再让 gs 按真实头输出。

## 10. 2026-10-24 12:58–13:05：真实抓包对照 → 补上 2 字节长度前缀

`runs/codex-2697-stats-packets2.bin`（5233 B）是**含分片头的真实服务器包**，逐包解析：

| 包 | 字节 | 解读 |
|---|---|---|
| 0 | `94 04 · 01 00 00 80 · 00 · 02 · 8a 04 · 8a 04 · data` | u16 长度 1172 = **10 + 1162**，seq `0x80000001`，index 0，末片索引 2，frag_size 1162，len 1162 |
| 1（@1174） | `94 04 · … · 01 · 02 · …` | 同前，index 1 |
| 2（@2348） | `58 04 · … · 02 · 02 · 8a 04 · 4e 04` | 长度 1112 = 10 + 1102，末片 |

→ 真实包头 = **u16 长度（10 + chunk）+ 10 字节 netchan 头 + chunk**；`count` 字段确实是"末片索引"（0/1/2 对应 3 片），
与 gs 的 `count-1` 语义一致。**gs 唯一缺的是这个 u16 长度前缀**。

已修改 `gameserver.py::_send_fragments`：`header = u16(10+len(chunk)) + u32(seq_word) + index + count-1 + u16(frag_size) + u16(len) + chunk`。

### 10.1 新问题：bridge 的 fragment 检测失效

加前缀后，包的前 4 字节变成 `64 00 01 00`（长度 + seq 低字节），
`ring_bridge` 的 `fragment = (u32(data[0:4]) & 0x80000000) != 0` 判为 **false**，
于是按"快照"丢弃（`state 6 < reliable_until_state 9`）。

绕过：forward 加 `--reliable-until-state 0`，dump 从 4 条增加到 11 条（gamestate + 6 snapshots 都注入）。

### 10.2 仍未接受

`state=6`、`ui=0` 不变。注入的 gamestate 包：`64 00 · 01 00 00 80 · 00 · 00 · 8a 04 · 5a 00 · 00 00 00 00 00 02 01 01 01 …`
（长度 102 = 10 + 90，seq 1，index 0，末片 0，frag 1162，len 90）。

下一步对比 **payload 内容**：2697 的 `codex-2697-gamestate.bin`（3426 B）是
`00 00 00 00 03 00 00 00 00 "mp_cross_fire\\0" "mp\\0" 7b f1 e8 36 04 …`；
gs 的 native 是 `… "mp_cross_fire\\0" "war\\0" <checksum> 04 …`。差异点：gametype（`mp` vs `war`）、
registration checksum、以及 configstring 数量/内容。下一轮应逐字段对齐后再发。

## 11. 2026-10-24 13:05–13:10：断点证明 gamestate 从未到达解析器

两组实锤：

| 实验 | 结果 |
|---|---|
| `--gamestate-source capture`（3426 B 的 2697 真实 gamestate） | `state=6`、`ui=0`（与 native 90 B 完全相同） |
| 断点 `0x472D80:GamestateParse` + `0x5C1678:ChallengeBranch` | **ChallengeBranch 命中**；**GamestateParse 一次都没命中** |

结论：
1. **不是 gamestate 内容问题**——换成 2697 真实 3426 B gamestate 结果一样；
2. 客户端**从没进入 gamestate 解析器**，也就是说 gamestate 包在**网络层**就被丢弃了，
   根本没到 `0x472D80`；
3. challengeResponse 分支正常（`0x5C1678` 命中），所以问题在 challenge 之后的
   **connectResponse / netchan 可靠包**这一段。

### 下一步

1. 找 `0x472D80` 的调用方（`call 0x472D80`），看它在什么条件下被调用（svc 类型？netchan seq？）；
2. 对比真实 2697 的 **connectResponse 字节**与 gs 的 `connectResponse \\mapname…`（真实包里有
   `snapshot-2697-seq5.bin` 等含 `MP_CONNECTED` 的 svc 0x01 数据，很可能 connectResponse 之后还有
   一条 `svc 0x01` 的 `MP_CONNECTED` 服务端命令，客户端正是等它）；
3. 若是，gs 应通过 `--command-file` 在 connect 后补发这条 svc 命令，而不是只靠 gamestate。
