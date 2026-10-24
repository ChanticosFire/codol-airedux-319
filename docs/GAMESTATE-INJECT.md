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

## 12. 2026-10-24 13:05–13:12：真实 gamestate + 真实 MP_CONNECTED 都被拒

| 实验 | 结果 |
|---|---|
| `--gamestate-source capture`（3426 B，2697 真实 gamestate） | `state=6`、`ui=0` |
| `--command-file runs/servercmd-2697-svc.bin`（真实 `svc 0x01`，明文 `f "MP_CONNECTED…`） | `state=6`、`ui=0` |
| 断点 `0x472D80` | **一次未命中**（gamestate 从未到解析器） |

三条合起来说明：**客户端在 state 6 时没有把 bridge 注入的可靠包交给上层**，
与包内容无关。最可能的原因在 **netchan 接收路径的初始化/校验**：

- 客户端在 6 档可能还没建立"可靠接收"上下文（例如 waiting for server ack 或
  `[connection+0x30]` 的 seq 窗口）；
- 真实 2697 包的 data 前 4 字节是 **ack**（`00 00 00 00`），我们一直发 0；
  若客户端要求 ack 覆盖它已发的 seq（3 左右），我们的包会被当"未确认"丢弃。

### 下一步（下一轮首选）

1. 在客户端 state 6 时读 `connection` 对象的 seq/ack 字段（`[conn+0x30]` 等），确认它期望的 ack；
2. 让 gs 的 `_send_fragments` 把 payload 前 4 字节的 ack 写成该值（可加 `--ack` 参数）；
3. 若仍不通，再查 netchan 接收上下文的建立条件（`0x5C05F0` 调用前后写了哪些字段）。

## 13. 2026-10-24 13:12–13:18：challenge 字段排查（假设被部分证伪）

上一轮猜测 `connection+0x08` 是客户端 challenge（读到 21766）。本轮在干净连接上重测：

| 步骤 | 观测 |
|---|---|
| 客户端经 `inject_client_gamestate` + `ring_bridge connect` | `conn=0x13CDD564` |
| 读 `conn+0x08` | **0**（不是 21766） |

→ `connection+0x08` **不是** challenge（上次的 21766 可能是别的字段/噪声）。
客户端 connect 的 userinfo 里 `challenge` 也是 0，所以两侧 XOR key 都按 `seq & 0xFF` 计算，**本来就是一致的**——
key 假设可以排除。

已给 `gameserver.py` 加 `--challenge-override`（默认 None，不影响现有行为），但本轮未验证到它有用；
保留作为后续如果发现真实 challenge 字段时的开关。

### 仍未解释

`state=6` 时 gamestate 包已注入（102 B、seq 1、长度前缀正确），但 `0x472D80` 从未被调用。
下一步应直接观测**网络接收循环**：在 `0x4F8D70`（pump）内或 ring 消费点下断点，
确认 state 6 时客户端是否把 ring_b 的包交给 netchan 层。

## 14. 2026-10-24 13:18–13:24：challenge 对齐把状态推到 5

用新加的 `--challenge-override 1469978033`（即 `inject_client_gamestate` 注入的 cookie）重跑：

| 观测 | 结果 |
|---|---|
| gs 日志 | `challenge_override 1469978033`、`connect`（`effective_challenge=1469978033`） |
| 客户端 | `state` **4→5**（此前同流程只到 4），`ui=0` |
| gs 发出 | gamestate（seq 1）+ 20 个 snapshot，dump 25 条均已注入 |
| 20 秒后 | `state` 复位 0（超时） |

→ **XOR key 对齐确实有意义**（4→5），但 `state 5` 仍不是"gamestate 已接受"；
5 档稳定 20 秒后超时，说明客户端在 5 档等的是另一条消息/事件，而不是我们发的 gamestate。

注意：上一轮"key 不一致"时反而到过 6，说明 **5/6 不是简单的线性进度**，
6 很可能是"包被接收但校验失败"的错误态（乱序/重复/解密错误都可能导致），不能把 6 当成功。

### 下一步

1. 读 `0x5C1678`（challengeResponse 分支）之后的状态写入，确认 5→? 的条件；
2. 在 `0x472D80` 下断点，配合 `--challenge-override` 再跑一次，确认 gamestate 是否终于进入解析器；
3. 若仍不进，改在 ring 消费点（`0x4F8D70` 内部）下断点，看包交给谁。

## 15. 2026-10-24 13:24–13:32：复现 ui_state=5，并定位到 LSG 未实现任务

带 **LSG 登录**的流程（`server319.lsg` + `drive_login_state_machine` + `inject_client_gamestate` + `ring_bridge connect`）：

| 观测 | 结果 |
|---|---|
| `state` | 4 |
| **`ui_state`** | **5（加载屏）** ← 首次在该流程中复现原始卡点 |
| 截图 | `runs/r23-ui5.png` |
| `0x472D80` 断点 | 0 次命中 |

同时 `runs/r23-lsg.jsonl` 里客户端连续请求了 **5 类 LSG 任务**，服务端全部未实现（`error=4`）：

| service/task | 参数摘要 | LSG 回复 |
|---|---|---|
| 28/4 | `tag(0x6c)` | presence not implemented |
| 102/7 | `u32(50),u8(1),u64(0),u8(1),u64(1),u8(1),u64(2),u8(1)` | unhandled |
| 102/1 | `u32(0),u32(1),u8(3),u64(0)` | unhandled |
| 3/46 | `str_hex(),u64(0),str_hex(),u32(10),u32(0)` | unhandled |
| 3/48 | `str_hex(),u64(0),str_hex(),u32(0),u32(100),u32(0)` | unhandled |
| 80/232 | `str_hex()` | unhandled |

**结论**：`ui_state=5` 不是游戏服务器/快照造成的，而是 **LSG（大厅服务）在登录后等待这些任务响应**；
LSG 回 `error=4` 后客户端停在加载屏。→ 主线的下一关是 **LSG 任务覆盖**，不是快照格式。

### 下一步

1. 用 `tools/room_backend_1649370.py`、`tools/native_room_flow.py` 里已有的房间/服务契约，
   给 `server319.lsg` 补上 28/4、102/1、102/7、3/46、3/48、80/232 的最小合法响应；
2. 每补一类就重跑（LSG + drive_login），观察 `ui_state` 是否离开 5；
3. `ui_state` 离开 5 后再接游戏服务器与快照。

## 16. 2026-10-24 13:32–13:44：补齐 7 个 LSG 任务，unhandled 归零

在 `server319/lsg_derived.py` 的分发链里，给登录后客户端连发的任务补了"空成功"回复
（与已实现任务相同的 envelope）：

```python
if (service, task) in ((28, 4), (102, 1), (102, 7), (3, 46), (3, 48), (80, 232), (9, 5)):
    reply_payload = (_typed_u64(counter) + _typed_u32(0) + b"\x03"
                     + bytes([task & 0xFF]) + _typed_u32(1) + _typed_u32(1))
```

结果：

| 观测 | 结果 |
|---|---|
| `runs/r24-lsg.jsonl` | 5 类任务从 unhandled 变为 `candidate_task_reply`；客户端继续发 `9/5` |
| `runs/r25-lsg.jsonl` | 补上 `9/5` 后 **unhandled = 0**，客户端共发 8 个任务后不再发新请求 |
| `ui_state` | 仍 **5**（加载屏） |
| 接游戏服务器（`inject` + `connect` + gs） | gs 只收到 **inband**，客户端在 ui=5 时**不发 connect** |

结论：**LSG 任务链已经走通**（unhandled 归零），但 `ui_state=5` 不因此解除；
而且 ui=5 时客户端不会主动向游戏服务器发起 connect。也就是说加载屏在等一条**异步事件**
（匹配成功/房间开始），而不是等任务响应。

### 下一步

1. 查客户端"开始/匹配"的触发点（`0x803780` 读 `[singleton+0x4F4]+0x5E8`，状态 3 = matched-waiting）；
2. 由 LSG 主动推送一条"匹配成功/房间已就绪"消息（需要 LSG 的出站主动帧，`lsg_derived.py` 里已有 `build_server_frame85`）；
3. 或从 UI 触发（点击"开始游戏"按钮/注入对应 UI 事件），让客户端自己进入 connect 流程。

## 17. 2026-10-24 13:44–13:56：LSG 任务补齐后，加载对象字段实测

在 `ui_state=5` 的活跃客户端上，按文档的指针链逐级读取：

| 地址 | 值 | 含义 |
|---|---|---|
| `[0x8269774]` | `0x43CE6CB0` | 加载单例（存在，非空） |
| `[singleton+0x4F4]` | `0x2464B8C0` | 加载子对象 |
| **`[sub+0x5E8]`** | **3** | matched-waiting（与文档一致） |
| `[sub+0x5EC]` | **2** | 新数据 |
| `[sub+0x5F0]` | **10** | 新数据（文档说写 3 时会清零它，此处非 0） |
| `[sub+0xC8]` | 2 | 与文档一致 |
| `[sub+0x644]` | 0 | 与文档一致 |

结论：
1. **LSG 任务补齐没有改变 `[+0x5E8]=3`**，所以加载屏不是"任务没回"造成的；
2. `[+0x5EC]=2`、`[+0x5F0]=10` 是此前没记录的字段，很可能是状态机计数器，
   下一轮应在 `0xBA3xxx` 区域找读这两个字段的指令，确认解除 3 的条件。

另外：`ui_state=5` 时注入 `challengeResponse` 并置 `net_state=3`，pump 后 `net_state` 回到 **0**
（状态机不接受），说明 ui=5 时网络状态机被加载屏挂起。

### 下一步

1. 反汇编 `0xBA3C00–0xBA4100`，找读 `[+0x5EC]`/`[+0x5F0]` 的指令与分支；
2. 若条件明确（如 `+0x5EC` 需到某值），构造对应输入/补消息；
3. 或在 `0xBA07A4` 前下断点，记录映射函数收到的完整输入。

## 18. 2026-10-24 13:56–14:08：加载状态迁移的完整时序（新工具 watch_loading.py）

新增 `tools/watch_loading.py`：轮询 `[0x8269774] → +0x4F4 → sub` 的
`+0x5E8/+0x5EC/+0x5F0/+0xC8/+0x644`，只在变化时打印。配合 LSG 登录实测：

```
t=0     ui=0  net=1  singleton=0
t=2.0   ui=1  net=1
t=2.5   ui=2  net=1
t=4.26  ui=3  net=1  singleton 出现，sub 出现，fields=[0, 垃圾, 垃圾, 1, 0]
t=5.01  ui=3  fields=[1, 垃圾, 垃圾, 2, 0]
t=5.26  ui=3  fields=[2, 垃圾, 垃圾, 2, 0]
t=5.76  ui=4  fields=[3, 1, 2, 2, 0]      ← 5E8=3 出现（早于 ui=5）
t=6.26  ui=5  fields=[3, 2, 2, 2, 0]      ← 5EC 1→2，ui=5
t=17.03 ui=5  net=0                        ← 超时
t=17.53 ui=5  fields=[3, 2, 8, 2, 0]      ← 5F0 跳变
t=17.78 ui=5  fields=[3, 2, 9, 2, 0]      ← 继续递增
```

**关键结论**：

1. `5E8=3` 在 **ui=4** 时就已写入，`ui=5` 只是映射结果（3 → status 2 → ui 5）；
2. `5EC` 的序列是 `0 → 1 → 2`：写 `5E8=3` 时为 1（对应 `0xBA3C38` 的 `mov [esi+0x5EC], ebx=1`），
   随后被另一处改成 2 —— **2 很可能才是"等待回执"的真实状态**；
3. `5F0` 不是超时倒计时，而是**事件计数**：`0xBA2E5C` 的 `inc [ebx+0x5F0]` 在
   收到每个消息/事件时执行（`0xBA2E4F` 还读 `[ebx+0x530]` 标志）；
4. 因此下一关是 **让 `5EC` 从 2 继续前进**（或找谁在 5E8=3 后把它改成 2）。

### 下一步

1. 扫描/反汇编写 `[sub+0x5EC]` 的第二处（`0x873CD6` 是写 byte 0/1 的，不是 2）；
2. 在 `0xBA2E5C` 下断点，记录每次递增时的调用栈，确认是哪个消息在计数；
3. 找到"回执"对应的事件后，由 LSG/游戏服务器补发。

## 19. 2026-10-24 14:08–14:20：写 `5E8=3` 的函数已定位

`0xBA3BA0` 是一个 3 参数函数（`ret 0xC`），完整结构：

```asm
0xBA3BA0  push ebp / mov ebp,esp / sub esp,0x10
0xBA3BB0  mov eax,[ebp+8]        ; arg0
0xBA3BBD  mov ecx,[ebp+0xC]      ; arg1
0xBA3BC8  mov ecx,[ebp+0x10]     ; arg2
0xBA3BCD  call 0xB783C0          ; 解码/解析（5 参数）
0xBA3BD5  test al,al
0xBA3BD7  jne 0xBA3C05           ; 成功 → 比较令牌
          ; 失败：call 0x4F7940(4); call 0xBA3420(重置); ret
0xBA3C05  push 8 / lea edx,[ebp-0xC] / lea eax,[esi+0x5FC] / call 0xB73FE0   ; memcmp(令牌,解码,8)
0xBA3C1A  test eax,eax
0xBA3C1C  jne 0xBA3C62           ; 不等 → push 3; 失败路径
0xBA3C1E  lea ebx,[eax+1]        ; ebx = 1
0xBA3C21  cmp [esi+0x644], 0
0xBA3C29  call 0x8435D0
0xBA3C3B  mov [esi+0x5EC], ebx   ; = 1
0xBA3C41  mov [esi+0x5F0], ebx   ; = 1
0xBA3C47  mov [esi+0x5E8], 3     ; = 3
```

补充：
- `[esi+0x5EC]` 是 **word 字段**（`0x8741E7` 处有 `mov word [esi+0x5EC], 0` 清零）；
- 写 `5EC=1` 用的是寄存器写（`89 9E`），静态扫不到常数；
- 实测 `5EC=2` 说明它写入后被**另一条寄存器写**改成 2（同一函数的重复调用/另一处 ebx=2 的调用），
  但 `5E8=3` 的唯一写入点仍是 `0xBA3C47`。

**结论**：`0xBA3BA0` 就是"客户端收到匹配/房间信息并校验 8 字节令牌"的入口。
它成功后才写 `5E8=3`（→ ui=5）。下一步应该 hook `0xBA3BA0`，记录 **谁调用、arg0/arg1/arg2 是什么**，
从而知道客户端在等哪条具体的匹配消息。

## 20. 2026-10-24 14:20–14:32：匹配入口的触发链（消息 0x83 → 0xC8=2 → 5E8=3）

### 20.1 断点实测

`--breakpoint 0xBA3BA0:MatchEntry` 在 LSG 登录流程里**命中 1 次**，栈解析：

| 项 | 值 |
|---|---|
| 返回地址 | `0x00BA456C` |
| arg0 | `0x2466A0F6` |
| arg1 | `1` |
| arg2 | `9` |

调用点 `0xBA4567` 的上文：

```asm
0xBA454B  cmp eax, 2
0xBA454E  jne 0xBA46A2
0xBA4554  mov al, [ebp-0xE]
0xBA4557  cmp al, 0x83        ; ← 消息类型 0x83
0xBA4559  jne 0xBA45F0
0xBA455F  mov eax, [ebp-0x14]
0xBA4562  push edi / push eax / push ebx
0xBA4567  call 0xBA3BA0
```

→ 客户端收到**消息类型 0x83** 且 `[esi+0xC8]==2` 时进入匹配校验，校验通过才写 `5E8=3`。

### 20.2 0xC8 状态机

| 地址 | 动作 |
|---|---|
| `0xBA36B5` | `call 0xC73900`（对 `[ebx+0xC4]` 做检查） |
| `0xBA36C0` | `cmp eax,1; jne` |
| **`0xBA36C8`** | **`mov [ebx+0xC8], 2`**（进入"匹配中"）→ `call 0xBA32A0` |
| `0xBA40A0` | `mov [ebx+0xC8], 1` + `mov [ebx+0x5E8], 0`（**重置**路径） |

实测 `0xC8=2` 在 ui=5 期间**一直不变**，与前面的分析一致。

### 下一步

1. 反汇编 `0xC73900`（返回 1 才进 0xC8=2），确认它测的是什么；
2. 找谁调用 `0xBA40A0`（重置：0xC8=1、5E8=0），那多半是超时/断开路径；
3. 若有别的代码把 0xC8 从 2 改成 3/4，那才是"匹配完成"的出口——目前只看到 2 和 1。

## 21. 2026-10-24 14:32–14:44：匹配入口的参数实测

新增 `tools/read_match_arg.py`：等 `MatchEntry` 断点命中后解析栈上的返回地址与三个参数，
并把指针参数指向的内存 dump 出来。实测（两次运行，参数结构一致）：

| 项 | 值 |
|---|---|
| 返回地址 | `0x00BA456C`（稳定） |
| arg0 | `0x2464A85E`（堆指针，指向 **64 字节全 0** 的缓冲区） |
| arg1 | **1**（标量） |
| arg2 | **9**（标量） |

结合 `0xBA3BA0` 的函数体：

```asm
mov eax,[ebp+8]      ; arg0 = 输出缓冲区（空）
mov ecx,[ebp+0xC]    ; arg1 = 1
mov ecx,[ebp+0x10]   ; arg2 = 9
call 0xB783C0        ; 5 参数解码器：从消息里读出 8 字节到 [ebp-0xC]
```

→ `arg0` 是**输出缓冲**（解码器填充），`arg1=1`、`arg2=9` 是解码器的两个标量参数
（很可能是"字段类型/长度"）。匹配校验用的 8 字节令牌就是解码器写进 `[ebp-0xC]` 的值。

### 下一步

1. 反汇编 `0xB783C0`，确认 arg1/arg2 的语义（类型与长度）；
2. 0x83 消息的发送方：LSG 的帧类型是 0x85，0x83 很可能是**游戏服务器**或**另一层帧**，
   应在客户端 LSG 读取路径（`0xBA3710` 附近）下断点确认；
3. 若确认 0x83 来自 LSG，则由 LSG 侧补发一条更完整的 0x83（带真实匹配数据），
   让客户端从 0xC8=2 前进。

## 22. 2026-10-24 14:44–15:00：连接端口与 T4 模式两次尝试（均未改变 ui=5）

### 22.1 连接目标端口

`inject_client_gamestate.py` 原来把 connection 的 netadr 端口写死为 **28969（LSG 端口）**，
疑似让客户端的游戏连接指错地方。已加 `--port`（默认仍 28969，保持兼容）。

实测 `--port 29000`（bridge）：`state=4`、`ui=5`，gs 只收到 **inband**，客户端仍不发 connect。
→ **端口不是原因**，ui=5 时网络状态机确实被挂起。

### 22.2 LSG 的 T4 完整匹配记录

`lsg_derived.py` 有 `LSG_T4_MODE=entry` 分支（task4 回 114 字节匹配记录而不是 4 字节空包）。
验证环境变量传递正常（`python -c` 能读到 `entry`），但 LSG 实际回复长度仍是 **194 字节**
（对应 zero 模式的短 payload），说明 entry 分支没有被走到。

→ 下一轮应直接检查 `(71,4)` 分支里 `t4_mode` 的读取位置（我新增的 7 任务分支改变了行号，
   需确认没有提前匹配/短路），并打印实际读取到的值。

### 仍然成立的结论

- `ui_state=5` 在 LSG 登录完成后出现，与游戏服务器/快照无关；
- 5E8=3 由 `0xBA3BA0`（LSG 0x83 令牌校验）写入；
- 5EC=2、5F0（事件计数）在 ui=5 期间演进；
- 客户端在 ui=5 时不向任何游戏端口发 connect。

## 23. 2026-10-24 15:00–15:15：T4 entry 生效但无效；trace-files 揭示 UI 音乐循环重试

### 23.1 T4 entry 已生效（上一轮判断有误）

给 `(71,4)` 分支的 reason 加上模式与负载长度后实测：

```
svc71/task4 reference candidate mode=entry payload=140
```

→ `LSG_T4_MODE=entry` **确实生效**（140 字节匹配记录，不是 31 字节空包）；
上一轮把 194 字节的**整体回复长度**误当成"zero 模式"。

但即便回完整匹配记录，客户端仍 `state=4`、`ui=5`，gs 只收到 inband。

### 23.2 trace-files：加载屏在反复请求 UI 音乐

带 `--trace-files` 跑到 ui=5，`events.jsonl` 里 **5178 条**文件事件，尾部全是同一种失败在循环：

```
file_missing: CreateFileA error=3
path: .\hires\sound\music\ui\ui_sp_hz_t_menumusic.mp3
caller: 0xc513d9
```

还有 `ui_sp_hz_af_caves_loud*`。文件其实存在（`offline-resources\main\sound\music\ui\` 下有 5,627,532 字节副本），
但客户端只在 **`hires\`** 下找，overlay/runtime 的 `hires` 里没有。

**判断**：这是加载屏期间的**音频循环重试**，很可能是"转圈"噪声的一部分，
但不一定是 ui=5 的根因（音乐加载失败不应阻塞 UI 状态机）。下一步可把这几首 UI 音乐放进
`offline-resources\hires\sound\music\ui\`，消掉这条重试再看状态是否变化。

## 24. 2026-10-24 15:15–15:30：补齐 UI 音乐；加载对象含未初始化标记

### 24.1 音乐补齐生效

把 `ui_sp_hz_t_menumusic.mp3`、`ui_sp_hz_af_caves_loud*` 复制到
`offline-resources\hires\sound\music\ui\` 后重跑（`--trace-files`）：

| 指标 | 补齐前 | 补齐后 |
|---|---|---|
| `file_missing` 条数 | 5178 | **2353** |
| UI 音乐缺失 | 循环出现 | **消失** |

剩余缺失（都是每轮 3–5 次，属"可选/回退"类）：
`main_shared/config_mp.cfg`、`hires/config_mp.cfg`、`main/config_mp.cfg`、
`TCLS/config/LoginQ.dat`、`client_shipRetail/chinese/patch_ui_mp.ff`，以及少量 `hires/images/*.iwi` 特效贴图。
`patch_ui_mp.ff` 在 IIPS 里没有对应包（搜索 `ui_mp|patch` 无结果），暂不作为主因。

### 24.2 加载对象含 debug 未初始化标记

ui=5 时读 `sub=0x2464B8C0`：

| 偏移 | 值 | 说明 |
|---|---|---|
| +0x90 | **0xBAAD0001** | debug heap 未初始化标记 |
| +0x530 | **0xBAADF000** | 同上 |
| +0xCC | 0x43CE6CB0 | 指向单例自身（非空） |
| +0x5FC | 0xFD3EF65A | 8 字节令牌的低半 |
| +0x644 | 0 | |

`0xBA2E4F` 读的正是 `[ebx+0x530]`（`movzx eax, byte [ebx+0x530]`），
而 `0xBA3315` 读 `[esi+0x90]`——这两个字段**从未被正式初始化**。

把两者都写成 0 后：`ui=5`、`state=0` 不变 → 它们不是 ui=5 的直接开关，
但说明这个加载对象只被**部分构造**，完整初始化路径还没走到。

### 下一步

1. 找构造函数（哪个函数写 +0x90/+0x530 的非标记值），确认它是否被调用；
2. 若确实没有，需要在进入匹配前显式调用它（或补一条会触发它的消息）。

## 25. 2026-10-24 15:30–15:45：小包不应分片（真实抓包依据）与"不 connect"死循环

### 25.1 真实服务器的小包不分片

对照 `runs/servercmd-2697-svc.bin`（1139 B < 1162）：首字节就是 `01`（svc 0x01），
**没有 u16 长度前缀、没有 FRAGMENT_BIT 头**。也就是说：

- `payload > frag_size` → 加分片头（u16 长度 + `seq|0x80000000` + index/count + frag_size/len）；
- `payload <= frag_size` → **直接发**，前 4 字节就是 ack。

而 `gameserver.py::_send_fragments` 之前对**所有**包都加分片头，90 字节的 native gamestate
也被包成 102 字节的分片包。已修复：`count <= 1` 时直接 `sendto(payload)`（仅对 svc 数据做 XOR），
日志里记为 `kind: single`。

### 25.2 但验证不了：客户端在 ui=5 时不 connect

修复后重跑：客户端 `state=4`、`ui=5`，gs 日志只有 **inband**——客户端没有发 connect，
gs 没有 peer，也就不会发 gamestate，`0x472D80` 仍然是 0 命中。

形成死循环：

```
ui=5  →  客户端不发 connect  →  gs 无 peer  →  不发 gamestate  →  客户端不离开 ui=5
```

而 `ui=5` 时直接注入 challengeResponse（+ pump）会让 `state` 回到 0（状态机被挂起），
说明 **必须先从 ui=5 里出来，网络层才会工作**。

### 下一步

1. 继续找 `ui=5` 的出口（`0xC8=2` 之后没有 3/4 的写入，需要查 `0xBA32A0` 调用的 `0xBA0980` 等子函数）；
2. 或反向：先让客户端不进入 ui=5（在 LSG 登录完成前注入/连接），再验证小包修复后的 gamestate 是否终于到达 `0x472D80`。

## 26. 2026-10-24 15:45–16:00：小包不分片 + 明文，仍不进解析器；定位分发循环

### 26.1 修复与结果

| 改动 | 结果 |
|---|---|
| 小包（<=1162 B）直接发送、不加分片头 | gs 日志出现 `out single gamestate`，客户端 `state` 从 4 升到 **5** |
| 小包不再 XOR（真实 `servercmd-2697-svc.bin` 是明文 `01 01 00 00 00 66 20 22 …`） | 仍 `state=5`、`ui=0`，**`0x472D80` 0 命中** |

### 26.2 解析器调用链

`0x472D80` 只有两个 `call` 调用点：

| 调用点 | 上下文 |
|---|---|
| `0x473457` | **网络包分发循环**：`0x473447 inc eax / mov [ebx+0x1C],eax / cmp ecx,5 / cmp ecx,4 …`，按读到的 svc 字节分发，5/4/3 分支里调用解析器 |
| `0x5AC1C4` | `0x5AC180` 函数（初始化路径） |

→ gamestate 必须经 `0x473420` 的**分发循环**（读取 svc 字节）才会进入 `0x472D80`。
现在包已到 ring、`state=5`，但分发循环显然没读到它。

### 下一步

在 `0x473420`（或 `0x473447`）下断点，确认这个循环是否运行、`ecx`（svc 字节）读到什么；
如果循环根本不跑，说明 `state=5` 时客户端还没有"开始处理 inband 包"，要往回找这个循环的触发条件。

## 27. 2026-10-24 16:00–16:15：分发循环 0 命中 → 客户端在 state=5 时根本不处理 UDP 包

### 27.1 断点结果

在 `0x473420`（分发函数入口）与 `0x473447`（循环体）下断点，跑完整流程（inject + connect + gs + forward + pump）：

```
Dispatch hits=0
DispatchLoop hits=0
```

→ **分发函数根本没被调用**。也就是说 gamestate 包即使已进 ring、`state=5`，客户端也没跑网络包处理。

### 27.2 静态调用链

| 地址 | 内容 |
|---|---|
| `0x473260` | 分发函数入口（唯一调用者 `0x473BE8`） |
| `0x473BB3` | `cmp eax,3; ja; jmp [eax*4+0x473C50]` —— **4 路消息类型 switch** |
| case 0 | `call 0x4737E0` |
| case 1 | `call 0x4738A0` |
| **case 2** | **`call 0x473260`**（gamestate/多包分发） |
| case 3 | `call 0x471E90` |
| `0x473A80` 起 | 网络包解包：按 `[edi+0x2C]` 决定走 `0x794380` 解密还是直接拷贝 |

结论：消息先经过 `0x473A80` 一带的解包，再按类型 switch 分发；
现在这条链**一次都没跑**，所以问题不在"包格式/加密"，而在**上游没有把 ring 里的包交给这个处理函数**。

### 下一步

1. 找调用 `0x473A80` 所在函数的入口（上游网络帧处理），确认它在 state=5 时是否被调度；
2. 若未被调度，查它的触发条件（可能是 `PUMP_FN 0x4F8D70` 内部的一个子步骤，需要额外参数/标志）；
3. 这也是为什么 `inject_client_gamestate` 的 3 条消息能到 challenge 分支（`0x5C1678`）却不进 gamestate 解析——两条路径的上游不同。

## 28. 2026-10-24 16:15–16:30：定位网络接收函数与 seq 窗口

### 28.1 接收链（静态）

`0x473A50`（分发入口）的调用者之一 `0x5C2434` 位于网络接收函数内：

```asm
0x5C23E0  call 0x66EE10          ; 从 stream 读 4 字节（seq_word）
0x5C23E5  ecx = eax & 0x7FFFFFFF ; seq
0x5C23ED  eax >>= 31             ; bit31 = FRAGMENT/加密标志
0x5C23F0  mov [ebx+0x144], ecx
0x5C23F6  mov [esi+0x2C], eax    ; ← 0x473A80 判断的就是这个
0x5C23F9  mov eax, [ebx+0x140]
0x5C23FF  lea edx, [eax-0x200]
0x5C2405  cmp [ebx+0x144], edx
0x5C240B  jge 0x5C241C           ; seq 必须 >= max_seq-0x200，否则丢弃
0x5C240D  mov [ebx+0x144], eax
0x5C2413  xor al,al; ret
0x5C241C  ...
0x5C242B  call 0x470A60
0x5C2434  call 0x473A50           ; 分发
```

两个结论：
1. `[esi+0x2C]` 就是**包头 bit31**（分片/加密标志），与 `runs/servercmd-2697-svc.bin` 的明文小包吻合；
2. 客户端有 **seq 窗口检查**：`seq >= [ebx+0x140] - 0x200`，否则丢弃。

### 28.2 改大 seq 无效

把 gamestate 的 seq 从 1 改成 **100000**（snapshot 也配 100001 起）重跑：

```
state=5  ui=0  Dispatch=0  GamestateParse=0
```

→ 仍 0 命中。说明包**没有进入这个接收函数**（不是窗口问题，也不是格式问题）。

### 下一步

找 `0x5C23E0` 所在函数的入口与调用者（上游帧调度），确认它在 state=5 时是否被调度；
若没有，用 `--main-call` 直接调用它（必要时先写 stream 缓冲），把 ring 里的包推进分发链。

## 29. 2026-10-24 16:30–16:45：决定性门槛 —— `net_state >= 7` 才处理 inband 包

### 29.1 接收函数的门禁

`0x5C2260`（网络帧处理，被 `0x4F8CD6/0x4F8D60/0x4F8ED8` 调用，即 **PUMP 函数内部**）在
OOB 分支之后：

```asm
0x5C22FC  cmp dword ptr [0x76446B0], 7     ; net_state
0x5C2303  jl 0x5C2413                      ; < 7 → 直接返回 false（丢包）
0x5C2309  ebx = connection
0x5C2315  cmp eax, 4                       ; 长度检查
...
0x5C23E0  call 0x66EE10                    ; 读 seq_word
0x5C242B  call 0x470A60
0x5C2434  call 0x473A50                    ; 分发
```

**这就是所有"包被丢弃"的根因**：我们一直把 `net_state` 停在 4/5/6，而客户端
**只有 state >= 7 才处理 inband 包**。所以 `0x473420`（分发）和 `0x472D80`（gamestate 解析）
永远 0 命中，与包格式、加密、seq 全部无关。

### 29.2 state=7 的写入点

| 地址 | 上下文 |
|---|---|
| `0x5BE90A` | CONNECT_FN 尾部，只在 `state >= 7` 时才走到（鸡生蛋） |
| **`0x813D34`** | **无条件** `mov [0x76446B0], 7`，前面是 `0x5C8A70`（CL_Shutdown）、`0x5C83D0`（CL_Init），是**连接初始化**路径 |

```asm
0x813D11  call 0x5C8A70
0x813D16  eax = 3 / (ebx ? 7 : 3)
0x813D25  call 0x5C83D0        ; CL_Init
0x813D34  mov [0x76446B0], 7   ; ← 无条件
```

### 下一步

1. 用 `--main-call` 调用 `0x813CF0` 所在函数（先找入口），让 `net_state=7`；
2. state 7 后再发 gamestate（小包、大 seq），验证 `0x473420` / `0x472D80` 是否终于命中；
3. 注意 `0x813D11` 会先 CL_Shutdown/CL_Init，可能重置已注入的连接对象——需要在其后重新注入/连接。

## 30. 2026-10-24 16:45–17:00：强改 state=7 会被复位；应走 CL_Init

### 30.1 poke `net_state=7`

在 `state=4` 时直接把 `0x76446B0` 写成 7（`poke_code.py` 回读确认 `04→07`）：

| 时间点 | state | 结果 |
|---|---|---|
| poke 后立即 | 7 | — |
| 1 秒后 | **0** | 状态机把它复位 |
| 之后 10 秒（gs 已发 gamestate+snapshot） | 0 | `Dispatch=0`、`GamestateParse=0` |

→ **强改状态不够**：客户端状态机在下一帧就修正/重置，包仍然被丢弃。

### 30.2 正路：调用 CL_Init 路径

`0x813C20`（函数入口，`0x813D34` 写 state=7 的那段就在其中）内部是
`0x5C8A70`（CL_Shutdown）→ `0x5C83D0`（CL_Init）→ `mov state,7`，是客户端自己认可的
"连接初始化完成"路径。

尝试用 launcher 的 `--main-call 0x813C20` 调用它，但参数拼接失败：

```
launch_1649370.py: error: unrecognized arguments: -- +set 2439 0 ...
```

原因：`--cbuf-command "echo cl_init_probe"` 的空格值被 shell 拆开，`cl_init_probe` 溢出成位置参数。
下一轮改用 `--cbuf-command=echo`（等号、无空格）或直接写一个调用脚本（复用
`ring_bridge_1649370.Client.invoke_sequence([{"target":0x813C20,"args":[]}])`）。

### 下一步

1. 用 `ring_bridge` 的 `Client.invoke_sequence` 在主线程调用 `0x813C20`（不依赖 launcher 参数）；
2. 调用后立即 inject + connect + gs + pump，验证 `net_state` 是否保持 7、`Dispatch` 是否命中；
3. 若 CL_Init 重置了连接对象，则在 CL_Init 之后重新执行 inject/connect。

## 31. 2026-10-24 17:00–17:10：CL_Connect 需要"服务器列表"，否则跳过 state=7

用新工具 `tools/call_fn_1649370.py 0x813C20`（走 `ring_bridge` 的
`Client.invoke_sequence` 在主线程调用）实测：调用成功返回（`returned_eip` 正常、进程存活），
但 `net_state` 仍是 **1**，`ui=0`。

反汇编 `0x813C20`（CL_Connect）：

```asm
0x813C2B  edi = ecx                     ; 上下文
0x813C2D  mov [0x826A9F0], eax          ; 服务器索引/句柄
0x813C54  call 0xBEAA80
0x813C59  cmp [0x826A9F0], 0
0x813C68  call 0xBEC980
0x813C80  call 0x4F4A90                 ; ← GetServerList
0x813C8D  mov eax,[ebp-4]
0x813C98  cmp eax, ebx
0x813C9A  je 0x813F51                   ; 失败 → 跳过 CL_Init/state=7
0x813D11  call 0x5C8A70                 ; CL_Shutdown
0x813D25  call 0x5C83D0                 ; CL_Init
0x813D34  mov [0x76446B0], 7
```

`0x4F4A90`（GetServerList）：

```asm
0x4F4AB8  call 0x4F49E0                 ; 读服务器列表（文件/配置）
0x4F4AC0  test al,al
0x4F4AC2  jne 0x4F4AE4
0x4F4ACE  mov eax, 0xFFFFFFFD           ; -3：没有服务器列表
```

→ **CL_Connect 在"没有服务器列表"时直接返回 -3**，不会执行 CL_Init，也不会写 state=7。
这与离线客户端 `[0x76446A1..0x76446C1]` 的 server 数组全 0 一致（CONNECT_FN 开头也有同样的空表提前返回）。

### 下一步

1. 反汇编 `0x4F49E0`，确认服务器列表来自哪个文件/配置（dwauth.ini？某个 .cfg/注册表？）；
2. 构造一份最小服务器列表（指向 127.0.0.1:28971），让 `0x4F4A90` 返回成功；
3. 再调用 `0x813C20`，验证 `net_state` 是否保持 7、`Dispatch` 是否命中。

## 32. 2026-10-24 17:10–17:25：CL_Connect 的分支一次都没走到

### 32.1 先修正一个误读

`0x4F49E0` 不是"读服务器列表"，而是**路径规范化函数**（处理 `/`、`\`、`.`、`:`，
并限制到 0x100 字符）——`0x4F4A90` 是"按路径加载资源"的包装，失败返回 `-3`。

`[0x76446A1]` 处那个 0x20 步长的字节数组在启动后**已经是 1**（非空），
所以 CONNECT_FN 开头的空表提前返回不是当前问题。

### 32.2 断点结果

在 `0x813C98`（`je 0x813F51` 失败跳转）与 `0x813D11`（CL_Shutdown 前）各下断点，
再调用 `0x813C20`：

```
CLInitPath=0
CLConnectFail=0
```

两处都没命中 → 函数在到达它们之前就返回了。

原因：`0x813C2D mov [0x826A9F0], eax` 把 **eax 当作参数**（server 索引），
而 `invoke_sequence` 只传 `args: []`、不设 eax/ecx，函数在早期分支就退出。

### 下一步

1. 给 `invoke_sequence` 增加寄存器/参数支持（eax=server 索引、ecx=上下文），
   再调用 `0x813C20`；
2. 或在 `0x813C20` 入口观察 eax/ecx 的期望值（从调用者 `0x813xxx` 反推）；
3. 只有走到 `0x813D34` 才会写 `net_state=7`，这是后续处理 inband 包的前提。

## 33. 2026-10-24 17:25–17:40：重大修正 —— `0x813C20` 是 CL_PlayDemo，不是 CL_Connect

### 33.1 命名纠正

`0x813C20` 的调用者（`0x814960`）在调用前用 `0x774900` 格式化字符串，格式串是：

```
0xDE72F0: 'demo/%s.demo'
```

→ `0x813C20` 是 **`CL_PlayDemo(name)`**：拼出 `demo/<name>.demo` 再走
`CL_Shutdown(0x5C8A70) → CL_Init(0x5C83D0) → net_state=7(0x813D34)`。

**所以 `net_state=7` 本来就是"demo 播放初始化"写的**，这也解释了：
- demo 播放路径会进入 state 7（= 允许处理 inband 包）；
- 之前 `cl_demo_play` 崩在 `g_gametype` dvar，根本没走到 `0x813D34`；
- 我们在网络路线上怎么也进不了 7——因为那是 demo 路径。

调用参数（从 0x814930 反推）：`eax=0`、`ecx=服务器/文件名字符串指针`、栈上一个 0。

### 33.2 双补丁重试 demo

同时 patch 两处 `g_gametype` 空指针：

| 地址 | 原指令 | 补丁 |
|---|---|---|
| `0x432049` | `mov edx,[0x32AA908]; mov ecx,[edx+0xC]` | `EB 53 …`（跳 0x43209E 返回 true） |
| `0x5A5AB0` | `mov eax,[0x32AA908]; mov esi,[eax+0xC]` | `EB 42`（跳 0x5A5AF4 跳过比较） |

结果：`cl_demo_play` 注入后**不再立即崩**（此前 9 秒内必崩），但 10 秒后仍崩在
`0xc0000005 @ 0x105`（`call [0]` 之类，空函数指针），`state` 仍为 1。

→ 第二个 patch 跳过了 `[edi]`/`[edi+4]` 的初始化，可能让后续空指针调用；
下一轮应改为"只把 `[0x32AA908]` 指向一个合法 dvar 替身"，而不是跳整段。

### 下一步

1. 构造最小 dvar 替身（name="g_gametype"、+0xC 指向 "war" 字符串），写进客户端内存并把
   `0x32AA908` 指过去——两处解引用都会安全通过，不需要改代码；
2. 然后再 `cl_demo_play`，验证 `net_state` 是否到 7；
3. state=7 后立刻接 gamestate/snapshot，验证 `Dispatch/0x472D80` 是否终于命中。

## 34. 2026-10-24 17:40–17:55：**里程碑 —— demo 播放成功，真实地图画面出现**

### 34.1 关键方法：伪造 g_gametype dvar

`tools/fake_dvar.py`：在客户端进程内 `VirtualAllocEx` 一小块内存，构造
`dvar_t{ name="g_gametype", flags=0, type=0, +0xC -> "war" }`，并把 `[0x32AA908]` 指过去。
**不改任何代码**，两处 `[dvar+0xC]` 解引用都安全通过。

### 34.2 结果

`cl_demo_play 0C-2021-8-26[19-26-24]war.demo` 之后：

| 时间 | net_state | ui_state |
|---|---|---|
| t=3..12 | 1 | 0 |
| **t=15** | **8** | 0 |
| **t=18+** | **10** | 0 |

**画面**：`runs/r51-demo-state10.png`（4.9 MB PNG）——
真实的 `mp_crash_tropical` 对局：地图建筑、士兵模型、小地图、比分 0-0、计时 30:45、
"消灭所有敌人！"目标提示、玩家列表（地角靓仔/亚呀亚/柠檬荔枝/天生长的酷/冰火绣气…）。
3 秒后再截一帧（`r51-demo-state10-b.png`）**hash 不同 → 画面在动**，demo 确实在实时播放。

### 34.3 意义

1. **渲染链路、地图资源、UI、demo 播放全部正常**——"黑屏+转圈"从此可以排除渲染问题；
2. demo 播放会把 `net_state` 推到 **7→8→10**，这正好是处理 inband 包的门槛；
3. 之前所有网络尝试卡在 state 5/6，现在有了"进入 state 7+"的可靠方法。

### 下一步

1. 用这条路径（假 dvar + demo）在 state 10 时抓 demo 的 gamestate/首帧快照字节（路线 B）；
2. 或先把 `mp_cross_fire` 的 demo/对局跑起来：`cl_demo_play` 只认地图名，可尝试把 demo 的地图名换成 mp_cross_fire（或直接用服务端 + 已进入 7 的状态）；
3. 目标仍是"mp_cross_fire 可见可玩 + 对局结束回大厅"：现在至少证明了客户端能渲染真实地图。

## 35. 2026-10-24 17:55–18:10：**关键链路打通 —— state>=7 时 gamestate 被分发/解析**

### 35.1 22 个 demo 都不含 mp_cross_fire

逐文件扫描 `mp_*` 字符串：地图只有 `mp_crash_tropical`、`mp_afghan`、`mp_ambush_sh`、`mp_bog_sh`、
`mp_boomtown`、`mp_abandon` 等，**没有 mp_cross_fire**。

### 35.2 篡改地图名失败

把 demo 里 27 处 `mp_crash_tropical` 替换为 `mp_cross_fire\0\0\0\0`（保持 17 字节）后播放：
`state` 到 8 后客户端在 21 秒内退出（资产名 `mp_crash_tropical_tp` 等被破坏，地图资产不匹配）。

### 35.3 决定性实验：demo 播放期间注入 gamestate

流程：假 dvar → `cl_demo_play`（demo 播放把 state 推到 7/8/10）→ 在 state 10 时接入
`ring_bridge connect` + `server1649370.gameserver`（native gamestate）+ `forward` + `pump`。

结果（断点计数）：

```
Dispatch=1
GamestateParse=1
state=10
```

**这是第一次让 `0x473420`（包分发）和 `0x472D80`（gamestate 解析）真正被调用**。
之前的 0 命中完全是因为 `net_state < 7`（见 §29）。

### 结论

- **门槛已破**：只要客户端在 state >= 7，服务端下发的 gamestate 就会被正常分发和解析；
- demo 播放是进入 state 7+ 的可靠手段；
- 下一步可以把 snapshot 也送进同一条链（`0x471D80` 实体循环），并让服务端在 state 7+ 后接管，
  逐步脱离 demo（先 demo 起状态，再让服务端 gamestate 覆盖地图信息）。

## 36. 2026-10-24 18:10–18:25：**快照的 3 个内容块全部被解析**

在 §35 的链路上再给 gs 加 `--snapshot-file runs/snapshot-hybrid-empty-actors.bin`（12 次），
并在三个内容块入口下断点：

```
Entities=2        (0x471D80，实体循环)
PlayerState=1     (0x471980)
Actors=1          (0x471010)
state=10
```

→ **快照的实体/玩家状态/actor 三个内容块都真正执行了**。此前"实体循环只读越界、
必然拒绝快照"的结论（README 的 known limitation）在 state>=7 的路径上没有复现。

### 意义

1. 服务端下发的 **gamestate + snapshot 都能被客户端完整解析**（不是"到 state 10 就停"）；
2. 现在具备了"服务端数据 → 客户端实体表"的完整通道；
3. 剩下的问题只是：**让地图是 mp_cross_fire，而不是 demo 的 crash_tropical**。

### 下一步

1. 把 gs 的 gamestate `mapname` 设为 `mp_cross_fire`，在 demo 起状态后立刻发送，
   看客户端是否转而加载 `mp_cross_fire.ff`（overlay 里已是 V70 提取的 461 版本）；
2. 若 demo 播放器锁死地图，则改为"假 dvar → 手工进入 state 7（不走 demo）→ gs gamestate"，
   再验证实体表是否仍被解析；
3. 验收仍是 `ui_state != 5` + 截图里出现 **mp_cross_fire**。

## 37. 2026-10-24 18:25–18:40：cross_fire gamestate 被解析但地图不切换

在 demo 起状态后把 gs 的 `--gamestate-map` 设为 `mp_cross_fire` 并立刻发送：

| 观测 | 结果 |
|---|---|
| `Dispatch` | 1 |
| `GamestateParse` | 1 |
| `state` | 8 |
| 截图 | `runs/r56-crossfire.png`：**灰度**的对局画面，仍是 crash_tropical 的建筑 |

→ gamestate 本身被解析了，但 **demo 播放器已经锁定了 crash_tropical 的地图**，
后到的 mapname 不会触发换图。

补充：`cl_demo_play doesnotexist` **不会**进入 state 7 —— `0x813C20` 里
`0x4F4A90`（按路径加载资源）失败后直接跳 `0x813F51`，跳过 `CL_Shutdown/CL_Init`，
`0x813D34` 不执行（断点 `State7=0`）。

### 下一步

1. 只有"先进入 state 7、再由 gamestate 选图"才可能拿到 mp_cross_fire；
   demo 路径会锁图，需要在 `CL_Init` 之后、demo 真正加载地图之前注入；
2. 更实际的替代：把 demo 头部/首条 gamestate 里的地图名改成 `mp_cross_fire`
   （只改地图名字段，不动资产名），让 demo 播放器自己去加载 cross_fire；
3. 或接受"demo 只用于证明渲染"，回到纯服务端路径：想办法让 `net_state` 稳定在 7
   （`0x813D34` 是唯一可靠写入点，需要先通过 `0x4F4A90` 的资源检查）。

## 38. 2026-10-24 18:40–18:55：demo 消息流里的地图名

demo 不是纯二进制——它是**文本命令 + 二进制帧**的混合流。地图名出现在两条 configstring/dvar 文本消息里：

| 偏移 | 内容 |
|---|---|
| 56883 | `... 01 29 00 00 00` + `d 3635 UK_spawn_music_mp_crash_tropical\0` |
| 60940 | `... 01 43 00 00 00` + `d 3636 AB_spawn_music_mp_crash_tropical\0` |
| 73655 | `... 01 9c 00 00 00` + `d 2557 "mp_crash_tropical" 1000\0` |

即每条消息 = `01` + u32 长度 + 文本。地图名一共出现 27 次（含资产名）。

### 为什么"改地图名"没成功

之前把全部 27 处替换成 `mp_cross_fire\0\0\0\0`，长度虽然不变，但把
`mp_crash_tropical_tp` 这类**资产名**也改坏了，客户端加载到 state 8 就退出。

### 下一步

1. 只改 **dvar/configstring 里的地图名**（`d 2557 "mp_crash_tropical" 1000` 这条），
   保持消息长度（用等长替换，例如 `"mp_cross_fire____"` 或调整 u32 长度字段）；
2. 但更可靠的是从 `0x813C20`（CL_PlayDemo）内部找**它自己用哪个字段决定加载哪张图**——
   demo 播放器很可能用 `d 2557`（mapname dvar）或 gamestate 首包；
3. 如果它用 `d 2557`，改这一条就能让 demo 加载 `mp_cross_fire`。

## 39. 2026-10-24 18:55–19:10：改 `d 2557` 地图名不改变 demo 选图

生成 `runs/cf_dvar.demo`：把唯一的 `d 2557 "mp_crash_tropical" 1000` 等长改成
`d 2557 "mp_cross_fire"\0\0\0\0 1000`（31→30 字节，其余 27 处资产名不动）。

播放结果：`state` 仍 1→8→**10**，画面 `runs/r58-cf.png` 仍是 **crash_tropical** 的灰度建筑
（多了"等待队伍就绪……"与一个"16"计数），**没有换成 cross_fire**。

→ **demo 播放器选图字段不是 `d 2557`**。它可能用：
1. demo 头里的某个定长字段；
2. demo 流里另一个更早的 gamestate 消息；
3. 或它根本不"选图"——demo 首帧就带地图资产引用，客户端按资产名找 ff。

### 下一步

1. 反汇编 `0x813C20` 内部（CL_PlayDemo 主体，0x813C20–0x814000），找它调用
   "加载地图 fastfile"（`Com_LoadMap`/`SV_SpawnServer` 一类）时用的参数来源；
2. 或直接看 trace-files：播放 `cf_dvar.demo` 时客户端访问了哪个 `.ff`——
   若仍是 `mp_crash_tropical.ff`，说明选图发生在更早的字段。

## 40. 2026-10-24 19:10–19:25：地图加载走 `patch_<map>.ff`，选图字段仍未知

### 40.1 trace 证据

播放 `cf_dvar.demo`（`d 2557` 已改成 cross_fire）时的文件访问里，地图包是：

```
.\client_shipRetail\chinese\patch_mp_crash_tropical.ff
```

即客户端**先找 `patch_` 前缀的补丁包**，再回退 `mp_crash_tropical.ff`。
overlay 里没有这些 `patch_*.ff`，所以回退到主包也能加载。

### 40.2 地图名在 demo 里的分布

`mp_crash_tropical` 独立出现（前后是引号或 NUL）共 **21 处**，首处 `0x11FB7`
（就是 `d 2557 "mp_crash_tropical" 1000`），其后在 0x136137、0x24A55D 等。
其余 6 处是 `mp_crash_tropical_tp` 之类的资产名。

### 40.3 结论

- 改 `d 2557` 不影响选图（上一轮已实测）；
- 选图字段要么在 demo 头，要么在更早的 gamestate 二进制消息里；
- 客户端地图包命名规则已确认：`patch_<map>.ff` → `<map>.ff` 回退。

### 下一步

1. 反汇编 FS 加载点（trace 里的 caller `0xC513D9`）的上游，看 `patch_...` 文件名由哪段代码拼出；
2. 从那个函数往回找"地图名来自哪个全局/dvar"，即可定位 demo 选图字段；
3. 或用一个更直接的办法：既然加载的是 `patch_<map>.ff`，把 `patch_mp_cross_fire.ff`（内容可用
   `mp_cross_fire.ff` 复制）放进 overlay，再想办法让客户端请求它（需要先知道选图字段）。

## 41. 2026-10-24 19:25–19:40：`patch_%s` 格式化点与地图加载入口

### 41.1 字符串与函数

| 项 | 值 |
|---|---|
| `patch_%s` | VA `0xDB5F28`（文件 0x9B5F28） |
| `localized_%s` | `0xDB5F34` |
| `patch_localized_%s` | `0xDB5F44` |
| 引用点 | `0x4842D4 / 0x4845EB / 0x48467E / 0x49E563 / 0x49EAB8 / 0x49EBBC` |

`0x4842C0` 是 **LoadMapFastfiles(mapname)**：

```asm
0x4842C2  call 0x49F180         ; 地图名有效性检查
0x4842D2  push esi               ; esi = 地图名
0x4842D3  push 0xDB5F28          ; "patch_%s"
0x4842DD  push 0xE9C5B80         ; 输出缓冲
0x4842E2  call 0x774900          ; sprintf -> patch_<map>
0x4842E7  push esi / 0xDB5F34    ; localized_<map>
0x4842FC  push esi / 0xDB5F44    ; patch_localized_<map>
0x484314  mov ecx, esi
0x484316  call 0x484C10          ; 逐个加载
```

调用者（5 处）：`0x4844EC / 0x484538 / 0x484585 / 0x4845A6 / 0x4845BB`。

### 41.2 地图名参数来源

`0x4844BB` 起是一段选择逻辑：

```asm
0x4844BB  mov esi, ebx            ; ebx = 地图名（函数参数）
0x4844BD  call 0x775BC0           ; 检查（可能 mp_ 前缀）
0x4844C6  mov esi, 0xDB5FFC       ; 否则用默认名
0x4844D6  mov edx, 0xDB468C       ; 与 gametype 比较
0x4844E7  mov esi, 0xDB6010       ; 某默认名
0x4844EC  call 0x4842C0           ; LoadMapFastfiles(esi)
```

→ 地图名来自调用 `0x4844xx` 那个函数的参数 `ebx`，且中间还有"是否 mp_ / 是否与某 gametype 匹配"的兜底。

### 下一步

1. 找 `0x4844xx` 所在函数的入口与调用者，看传入的地图名来自哪个全局/dvar；
2. 该全局很可能就是 demo/gamestate 设置的地图名——定位后即可把它改成 mp_cross_fire；
3. 已知客户端会按 `patch_<map>.ff` → `<map>.ff` 顺序加载。

## 42. 2026-10-24 19:40–19:55：demo 播放时的地图名来自 `connection+0x108394`

### 42.1 调用链

`0x484370` 只有两个调用者：

| 调用点 | 上下文 |
|---|---|
| `0x4FE7B6` | 前端菜单地图：`push 0xDB5DA4`（字符串 **"menu"**）→ `LoadMapFastfiles("menu")`，前面有 `CL_Shutdown(0x5C8A70)` + `CL_Init(0x5C83D0)` |
| **`0x49E63E`** | `0x49E600` 地图加载函数内部，参数来自 `ecx` |

`0x49E600` 的调用者有三个，其中 **`0x813ECC` 就在 CL_PlayDemo（0x813C20）内部**：

```asm
0x813E90  lea edi, [ebx + 0x108294]
0x813E96  lea esi, [ebx + 0x108394]   ; esi = connection + 0x108394
0x813EC9  push esi
0x813ECC  call 0x49E600               ; LoadMap(connection + 0x108394)
```

→ **demo 播放时的地图名就存在 `connection+0x108394`**（ebx = connection 对象）。

### 42.2 下一步

1. 找写 `connection+0x108394` 的代码（demo 播放器解析 demo 头/首包后写入），确认它从 demo 的哪个字节读地图名；
2. 或抢在 `0x813ECC` 之前把 `connection+0x108394` 改成 `"mp_cross_fire"`（需要精确时序，或 hook `0x813E96`）；
3. 找到写入点后，改 demo 对应字节即可让 demo 加载 mp_cross_fire，同时不破坏资产名。

## 43. 2026-10-24 19:55–20:10：`connection+0x108394` 只有一处读取，且 demo 播放不走那里

### 43.1 静态扫描

对 `0x108394` 做全 modrm 扫描（`lea`/`mov-imm`/`mov-reg`，0x80–0xBF）：

```
refs = 1: 0x813E96 lea esi,[ebx+0x108394]   (modrm 0xB3)
```

→ 这个字段**没有静态写入点**（写入只能是通过指针的 `strcpy`/`memcpy`，或它其实是
`connection` 之外的另一个结构）。

### 43.2 动态验证

在 `0x813E96` 下断点、跑 demo 播放（假 dvar + `cl_demo_play`）：**`MapName` 0 命中**。

→ demo 播放**没有走到 CL_PlayDemo 的 `0x813ECC` 分支**（那条 `push esi; call 0x49E600`），
也就是说 demo 的地图加载走的是 `0x49E600` 的另外两个调用者（`0x5156BF` / `0x5C7D51`）。

### 下一步

1. 在 `0x49E600` 入口下断点，看 demo 播放时是哪个调用者、参数（地图名指针）指向什么；
2. 在 `0x484370` 入口下断点，直接打印它收到的地图名字符串——这是"最终消费者"，
   一次就能确认 demo 用的是哪个地图名、来自哪块内存；
3. 拿到指针后改那块内存即可换图（不需要改 demo 文件）。

## 44. 2026-10-24 20:10–20:25：`0x484370` 只在前端菜单加载时命中

在 `0x484370`（LoadMapFastfiles）与 `0x49E600`（LoadMap）各下断点，跑 demo 播放：

| 断点 | 命中 | 说明 |
|---|---|---|
| `0x484370` | **1** | 栈解析：返回地址 `0x004FE7BB`，第一个参数 **`0x00DB5DA4` = "menu"** → 这是**启动时的前端菜单地图**，不是 demo |
| `0x49E600` | **0** | — |

→ **demo 播放根本不经过这两个函数**。它加载 `patch_mp_crash_tropical.ff` 的请求走的是另一条路径
（trace 里的 FS caller `0xC513D9`）。

### 下一步

1. 反汇编 `0xC513D9` 的上游（它所在函数），看 `patch_mp_crash_tropical.ff` 这个文件名由谁提供；
2. 或直接在 `0xC513D9` 附近下断点，看 demo 播放时栈上的文件名指针；
3. 拿到指针后改内存即可换图（不必改 demo 文件）。

## 45. 2026-10-24 20:25–20:40：FS 打开点断点可用，文件名需运行时读

### 45.1 `0xC513D9` 是什么

```asm
0xC513CE  push [ebp-0x14]      ; 共享模式
0xC513CA  lea eax,[ebp-0x30]
0xC513CD  push eax
0xC513C7  push [ebp-0x18]      ; 创建方式
0xC513BE  push [ebp-0x10]      ; 属性
0xC513BC  push 0
0xC513D4  push [ebp+0xC]       ; ← 文件名（第三个参数）
0xC513D7  call edi             ; [0xCA8208] = CreateFileA
0xC513D9  mov [ebp-0x20], eax  ; 返回点
```

→ `0xC513D9` 是 **CreateFileA 的返回点**，文件名在 `[ebp+0xC]`。

### 45.2 新工具

`tools/read_fs_names.py`：从断点事件里取 `ebp`，读 `[ebp+0xC]` 指向的字符串，
去重后打印前 N 个。第一次跑时 milestone 过滤漏了 `FSOpen`（已修）。

### 45.3 断点结果

`0xC513D9:FSOpen` 命中 **1 次**（`eax=0xFFFFFFFF`，即 CreateFileA 失败），
但那是启动早期的失败请求；客户端随后被清理，来不及读文件名。

### 下一步

带上修正后的 `read_fs_names.py` 重跑一次（客户端保持运行），
即可看到 demo 播放实际请求的 `patch_mp_crash_tropical.ff` 文件名及其提供者所在的栈帧。

## 46. 2026-10-24 20:40–20:55：FS 断点参数读不出文件名；trace 的请求时序需对齐

### 46.1 `0xC513D9` 断点

`0xC513D9:FSOpen` 只命中 **1 次**，用 `[ebp+0xC]` 读出的字符串是乱码
（`\x01 \x010\x01@\x01P\x01`）。可能原因：

1. 那次 `CreateFileA` 的"文件名"本来就是二进制/非文本；
2. 断点命中时 `ebp` 不是期望的帧（0xC513D9 可能被多处代码共用）；
3. 参数位置不是 `[ebp+0xC]`。

### 46.2 trace 时序

在 r64 里带 `--trace-files` 跑完整 demo 播放，12 秒后 grep `patch_mp_crash_tropical|mp_crash_tropical.ff`：
**matches=0**。而 r58（同样播 crash_tropical demo）的 trace 里**有** `patch_mp_crash_tropical.ff`。

→ 说明地图包的请求发生在**更早的阶段**（demo 播放前的地图加载），或 events 还没 flush 完。

### 下一步

1. 直接用 r58 的 `events.jsonl`（已知含 `patch_mp_crash_tropical.ff`）反查它记录的 caller 与 path，
   确认请求时机；
2. 若要抢在加载前换图，应该在 demo 播放**之前**（state 1 时）就改 `connection+0x108394` 或
   对应全局，而不是等 demo 播放中途；
3. 更稳的路线：放弃"改 demo 选图"，改为"先入 state 7，再由 gamestate 选图"——
   但 state 7 的唯一可靠写入点是 demo 路径，形成循环，需要另找入口。

## 47. 2026-10-24 20:55–21:10：`patch_mp_crash_tropical.ff` 的两个请求点

r58 的 trace 里精确找到（16 条 `mp_crash_tropical` 匹配中只有 2 条是 `.ff`）：

```json
{"file_missing": {"error": 2, "caller": "0xc513d9",
  "path": ".\\client_shipRetail\\chinese\\patch_mp_crash_tropical.ff"}, "time": 1792821500.44}
{"file_missing": {"error": 2, "caller": "0x776f80",
  "path": ".\\client_shipRetail\\chinese\\patch_mp_crash_tropical.ff"}, "time": 1792821502.68}
```

### 47.1 第二个请求点 0x776F80

`0x776F00` 是 **FileExists(path)**：

```asm
0x776F48  push 0xDDA780         ; 路径格式串（如 ".\\client_shipRetail\\chinese\\%s"）
0x776F59  call 0x774900         ; sprintf(path, fmt, name)
0x776F6E  push 0x80000000       ; GENERIC_READ
0x776F7A  call [0xCA8208]       ; CreateFileA(path, ...)
0x776F80  ...                   ; 返回点
```

- 唯一调用者：**`0x49EDA3`**；
- `0x49EXXX` 正是资源/地图加载区（`0x49E600` LoadMap、`0x49EAB8` 等都在此）。

### 47.2 下一步

1. 正确反汇编 `0x49EDA3` 附近（`0x49ED80`/`0x49ED90` 起，找到指令边界），看传给 FileExists 的
   路径/名字来自哪个参数；
2. 顺着这个参数回溯，就能找到"地图名"的最终来源——它同时决定
   `.\client_shipRetail\chinese\patch_<map>.ff` 与后续的 `<map>.ff`；
3. 拿到来源后改内存即可让 demo 加载 mp_cross_fire（不必改 demo 文件）。

## 48. 2026-10-24 21:10–21:25：fastfile 加载链完整打通

### 48.1 完整调用链（静态）

```
0x49E160(list, count, ...)            ← 通用 Com_LoadFastfiles，16 个调用者
  └─ 0x49E3BE: 0x49DE70(list, count)  ← 填充请求表
       └─ 0x49DEB9: strncpy(表项, list[i].name, 0x3F)   ; 表项 = 0x1D06440 + i*0x44
            └─ 0x49F2A8: LoadFastfile(表项, 表项+0x40)   ; 0x49F280 遍历表
                 └─ 0x49ED40: sprintf(buf, "%s.ff", name)   ; 0xDB617C = "%s.ff"
                      └─ 0x776F00: FileExists(buf) → CreateFileA
```

关键常量：

| 项 | 值 |
|---|---|
| 请求表基址 | `0x1D06440`，每项 **0x44** 字节，数量 `0x239B11C` |
| 名字字段 | 表项 +0x00（strncpy 目标），flags 表项 +0x40 |
| 路径格式 | `0xDB617C = "%s.ff"` |
| 加载模式 | `[0xE56FE0]`：0=FileExists，1=0x776FA0，2+=0x49EDB9 |

### 48.2 意义

- 地图名最终来自 `0x49E160` 的 **list 参数**（每个调用者传不同数组）；
- 只要在 `0x49E160` 下断点，看 demo 播放时是哪个调用者、list[0].name 是什么，
  就能直接锁定"patch_mp_crash_tropical"的来源；
- 拿到后改 list 里的字符串指针即可换成 mp_cross_fire（loader 只读名字）。

### 下一步

1. 在 `0x49E160` 下断点跑 demo 播放，记录命中调用者与 list 内容；
2. 在 `0x49ED40` 下断点，直接读参数（`[ebp+8]` = 名字指针），打印字符串；
3. 确认来源后，用"改内存"的方式把名字换成 `mp_cross_fire`，验证是否加载 cross_fire。

## 49. 2026-10-24 21:25–21:40：`0x49ED40` 断点只有启动时命中

新增 `tools/read_call_arg.py`：从断点事件里依次尝试 `[ebp+8]`、`[ebp+4]`、`[ebp+0xC]`、
`[esp+8]` 等位置取值并按字符串解析，用于泛型地读取函数第一个参数。

在 `0x49ED40:LoadFastfile` 下断点、跑 demo 播放：

```
LoadFastfile hits=1
（read_call_arg 过滤 'crash' → []）
```

→ demo 播放期间 **`0x49ED40` 只命中一次**（启动早期），说明：

1. demo 播放的地图 fastfile 在**启动阶段**就已加载（r58 trace 的 `patch_mp_crash_tropical.ff`
   请求时间 1792821500.44/1502.68 也早于 demo 播放）；
2. demo 播放器只是**复用**已加载的地图数据，不会重新请求 `patch_<map>.ff`。

### 下一步

1. 在 `0x49E160`（更上游，16 个调用者）下断点，记录命中调用者与 list；
2. 或在 demo 播放**之前**（state 1、刚启动时）就改地图名全局/表项——此时加载还没发生；
3. 若 demo 播放确实不重新加载地图，则"换图"只能在启动阶段做，需要更早地介入
   （例如 `fake_dvar` 同批操作里把地图表项名字改成 mp_cross_fire）。

## 50. 2026-10-24 21:40–21:55：`0x49E160` 只在启动加载时命中

在 `0x49E160:LoadFF`（通用 Com_LoadFastfiles，16 个调用者）下断点，跑完整 demo 播放：

```
hits = 1
返回地址 = 0x4FCC81
```

→ 整个运行期只有**启动阶段**一次 fastfile 批量加载（来自 `0x4FCC81`，属 `0x4FCCxx` 的启动初始化），
demo 播放期间**不再加载任何 fastfile**。

### 结论

1. `patch_mp_crash_tropical.ff` 的请求（r58 trace 时间 1792821500.44/1502.68）发生在**启动**，
   与 demo 播放无关；
2. 也就是说地图在启动时就已经被确定并加载，**demo 播放只是回放数据**；
3. "改地图名让 demo 加载 cross_fire"的思路不成立——要换图必须在**启动阶段**介入，
   或者走"服务端 gamestate 选图"的路线。

### 下一步

1. 读 `0x4FCC81` 处的启动加载列表（`0x49E160` 的 list 参数），看它包含哪些包、
   地图名从哪个字符串表来；
2. 如果地图名在启动表里是常量（如 "patch_ui_mp"），则 demo 的地图来自 demo 文件头的首次读取——
   需要找"启动时读 demo 目录"的代码；
3. 或在 `0x49ED40` 的 1 次命中里读参数（`read_call_arg`，不过滤 crash），确认它加载的包名。

## 51. 2026-10-24 21:55–22:10：`mp_crash_tropical` 是 `preloadmap` 参数，改写后启动不换图

### 51.1 常量位置

整个 exe 里 `mp_crash_tropical` 只出现一次：

```
0x9C6670: "mp_crash_tropical\0"   ; 前后是 "2930\0" "2931\0" 与 "g_difficulty %d; preloadmap"
```

`.rdata` 段，附近是 `preloadmap` 相关字符串 → 它是 **preloadmap 命令的参数**，
不是"启动时决定地图"的字段。

### 51.2 prewrite 实验

用 launcher 的 `--prewrite 0x9C6670=6d705f63726f73735f66697265000000000000`
（把常量改成 `mp_cross_fire` + 5×NUL）后启动（带 `--trace-files`）：

| 观测 | 结果 |
|---|---|
| `net_state` | 1 |
| `ui_state` | 0 |
| fastfile 请求数 | 11（全部是基础包，无 cross_fire / crash） |

→ 改写这个常量**不影响启动加载**：启动只加载 11 个基础包，地图包是之后由 demo/对局流程
用 `preloadmap` 加载的。

### 下一步

1. 找 `preloadmap` 命令的实现（注册点 + 其参数来源），确认它是 demo 播放时被调用的；
2. 若 demo 播放会调 `preloadmap mp_crash_tropical`，那么在播放**之前**把该常量改成
   `mp_cross_fire`（prewrite 已证明可行）就能让 demo 预加载 cross_fire；
3. 结合 `fake_dvar` + `cl_demo_play` 重跑，这次在 demo 播放前执行 prewrite。

## 52. 2026-10-24 22:10–22:25：prewrite 地图名常量后 demo 仍加载 crash_tropical

用 `--prewrite 0x9C6670="mp_cross_fire"+5×NUL` 启动，然后 `fake_dvar` + `cl_demo_play`：

| 观测 | 结果 |
|---|---|
| `net_state` | 1 → 8（t=15）→ **21 秒时进程退出** |
| fastfile 请求数 | 15 |
| 地图包 | **仍是 `patch_mp_crash_tropical.ff`** |

→ **`0x9C6670` 那个常量不是 demo 选图来源**（改了也没用），而且改写它可能破坏了别的逻辑导致 21 秒崩溃。

### 结论

demo 的地图名来自 **demo 文件本身**（头部或首包），不是 exe 里的常量，也不是 dvar `d 2557`。
之前"改 d 2557 / 改常量 / 改资产名"三条路都已被实验排除。

### 下一步

1. 逐字段解析 demo 头（0x100 字节），找出地图名所在字段——虽然头里没有明文字符串，
   但 demo 播放器可能用 `demo 头的某个 u32 → 内部 map id 表 → 名字`；
2. 或在 `0x49E160`（唯一一次启动加载之后的第二次调用）与 `0x484370` 都 0 命中的情况下，
   直接 hook `LoadFastfiles("patch_mp_crash_tropical")` 的调用点（0x4FCC81 所在函数），
   看它在 demo 播放时传入的地图名从哪里读；
3. 若 demo 头确实是唯一来源，则改 demo 头字段（而不是消息流）即可换图。

## 53. 2026-10-24 22:25–22:40：demo 头逐字节 + 一个矛盾点

### 53.1 demo 头（前 0x120 字节）

```
0000  1d 00 00 00      29         版本
0004  01 00 00 00      1          协议
0008  d6 00 00 00      0xD6(214)  checksum/长度
000c  00 00 00 00
0010  f5 47 81 3a 7b d4 28 ef 8 字节（时间戳）
0018  00 00 00 00
001c  05 00 00 00      5          某计数
0020  01 00 00 00      1
0024..0x52  全 0
0053  55 00 00 00      0x55(85)   ← 可能是"头长度"
0057  04 00 00 00      4
005b  01 00 00 00      1
005f  01 00 00 00      1
0063  c8 00 00 00      0xC8(200)
0067.. 全 0
```

头里**没有 mapname 明文**（地图名第一次出现在 0x11FB7 的 `d 2557 "mp_crash_tropical"` 消息里）。

### 53.2 矛盾点

| 实验 | 结果 |
|---|---|
| r58 trace（播放 cf_dvar.demo） | 有 `patch_mp_crash_tropical.ff` 请求（caller 0xC513D9 / 0x776F80） |
| r67 `0x49ED40`（LoadFastfile）断点 | demo 播放期间 **0 命中** |
| r68 `0x49E160`（Com_LoadFastfiles）断点 | 全程 **1 命中**（启动，返回 0x4FCC81） |

→ 说明 demo 播放的地图加载**不走** `0x49E160 → 0x49DE70 → 0x49F280 → 0x49ED40` 这条链，
而是另一个更直接的 FileExists 调用点（`0x776F80` 的 0x49EDA3 上游）。

### 下一步

1. 在 `0x776F00`（FileExists）入口下断点，用 `read_call_arg` 读 `[ebp+8]` 的字符串——
   它会直接告诉我们 demo 播放请求的每个文件名；
2. 从命中次数与内容即可确认 demo 的地图包请求路径；
3. 一旦定位到"名字写入表"的那一步，就能在播放前替换成 mp_cross_fire。

## 54. 2026-10-24 22:40–22:55：demo 播放期间 FileExists 也只命中 1 次

在 `0x776F00:FileExists` 下断点，跑 `fake_dvar` + `cl_demo_play`：

```
FileExists hits=1        （启动阶段，无 crash 相关）
```

→ demo 播放期间**既不经过 Com_LoadFastfiles 链，也不经过 FileExists**。
r58 trace 里那两条 `patch_mp_crash_tropical.ff` 请求（caller 0xC513D9 / 0x776F80）
发生在 **demo 播放之前/之外的阶段**（很可能是启动时客户端扫描 `main/demo` 目录、
读到 demo 头后预加载地图）。

### 结论（两条换图路线都关闭）

| 路线 | 结论 |
|---|---|
| 改 demo 内地图名（d 2557 / 全量） | 无效（§39/§35） |
| 改 exe 常量 0x9C6670 | 无效（§52） |
| 找 demo 播放时的 fastfile 加载点 | **不存在**：播放不加载地图（§54） |

→ demo 的地图在**播放之前**就已被选定。要换图，只能在"启动→demo 播放"之间介入，
且介入点不是 0x49E160/0x49ED40/0x776F00 任何一条链。

### 下一步

1. 在 `0x4FCC81`（0x49E160 的唯一启动调用点）反汇编，看它加载的 list 是否包含地图包；
2. 若包含，则"启动时加载列表"就是地图名的真正来源——改 list 里的名字即可；
3. 若不包含，则 demo 播放前必有一条独立的"地图预加载"路径，需要从 r58 的
   `patch_mp_crash_tropical.ff` 请求时间戳反推它发生在哪个会话阶段。

## 55. 2026-10-24 22:55–23:10：启动加载列表只有 4 个基础包

`0x4FCC81` 所在的启动函数（`0x4FCC3C`–`0x4FCC7C`）在栈上构造 4 项列表后调用 `0x49E160`：

```asm
0x4FCC3C  [ebp-0xA10] = 0xDBD6E0   ; "patch_code_pre_gfx_mp"
0x4FCC4C  [ebp-0xA04] = 0xDBD6F8   ; "code_pre_gfx_mp"（或 localized 变体）
0x4FCC5C  [ebp-0x9F8] = 0xDBD708   ; "patch_localized_code_pre_gfx_mp"
0x4FCC6C  [ebp-0x9EC] = 0xDBD728   ; "localized_code_pre_gfx_mp"
0x4FCC7C  call 0x49E160            ; LoadFastfiles(list, 4)
```

读字符串确认：

```
patch_code_pre_gfx_mp
code_pre_gfx_mp
patch_localized_code_pre_gfx_mp
localized_code_pre_gfx_mp
```

→ **启动只加载这 4 个基础包**，不含地图。

### 与 r58 的矛盾

- r58（play cf_dvar.demo）trace 里有 `patch_mp_crash_tropical.ff`；
- r70（只启动、不播 demo）fastfile 请求 11 个，**不含** crash_tropical；
- r67/r68/r72 在 `0x49ED40`/`0x49E160`/`0x776F00` 下断点、播放 demo，却都只有启动阶段的命中。

→ 结论：demo 播放**确实**触发地图包请求（r58 为证），但**不经过**我们下的三个断点，
说明它走了一条**直接拼路径并 CreateFile** 的快速通道（不是 FileExists/Com_LoadFastfiles）。

### 下一步

1. 在 r58 那样的配置下（play demo + trace-files）重新定位 `patch_mp_crash_tropical.ff`
   请求的精确时间，并对照 demo 播放（cbuf 注入）的时刻，确认请求发生在播放后多久；
2. 用 `0xC513D9`（CreateFileA 返回点）作为唯一权威断点，在**播放 demo 后**读该时刻的
   `[ebp+0xC]` 文件名（需要让客户端在命中时保持运行，用后台读脚本）；
3. 一旦读到文件名，回溯调用栈（`[ebp]` 链）即可找到地图名的最终来源。

## 56. 2026-10-24 23:10–23:25：只放 demo 文件不播放，启动不预加载地图

| 实验 | 配置 | fastfile 请求 |
|---|---|---|
| r70 | 只启动（无 demo 文件） | 11 个，无 crash/cross |
| **r74** | 启动 + 放 demo 文件、**不播放** | **12 个，无 crash/cross** |

→ 客户端**不会**在启动时扫描 `main/demo` 并预加载地图。

### 矛盾仍未解

- r58（play **cf_dvar.demo**，地图名已被改成 `mp_cross_fire`）：trace 有 `patch_mp_crash_tropical.ff`；
- r72/r73（play **原始 demo**，地图名 `mp_crash_tropical`）：`FSOpen`/`FileExists` 断点在播放期间 **0 命中**。

**推测**：r58 看到的是 `cf_dvar.demo` 的 **fallback** 路径——客户端按 `mp_cross_fire` 找包，
找不到后回退 `crash_tropical`，于是请求 `patch_mp_crash_tropical.ff`；
而原始 demo 的 `crash_tropical` 在启动或更早就已加载，播放时不再请求。

### 下一步

1. 用 `cf_dvar.demo`（地图名 cross_fire）跑一次 `FSOpen` 断点，若命中并读到
   `patch_mp_cross_fire.ff`（或 crash 的 fallback），即可确认 fallback 链条；
2. 若 fallback 成立，则在 overlay 放入 `patch_mp_cross_fire.ff`（内容用 mp_cross_fire.ff 复制）
   并让客户端在 fallback 前命中它——这是"让 demo 加载 cross_fire"的最后一条路；
3. 否则只能回到服务端路线（另找 net_state=7 入口）。

## 57. 2026-10-24 23:25–23:40：`0xC513D9` 在 demo 播放期间始终 0 命中

| 实验 | demo | 断点 | 播放期间命中 |
|---|---|---|---|
| r73 | 原始（crash_tropical） | 0xC513D9:FSOpen | **0**（仅启动 1 次） |
| **r75** | cf_dvar（cross_fire） | 0xC513D9:FSOpen | **0**（仅启动 1 次） |

→ 无论 demo 的地图名是什么，**demo 播放都不经过 0xC513D9（CreateFileA）**。

### 57.1 顺带发现的工具 bug

`read_call_arg.py` 在打印时遇到非 ASCII 字符触发 `UnicodeEncodeError: 'gbk' codec ...`
（Windows 控制台默认 GBK）。需要改成 `ensure_ascii=True` 或用 `errors="replace"`。

### 57.2 推论

demo 播放触发的地图加载**不经过 FS 层**（CreateFileA）。两种可能：

1. 地图 fastfile 在更早阶段已加载进内存（启动时的 4 个基础包之外，还有一条没被断点捕获的加载）；
2. demo 播放直接用内存里的地图数据（fastfile 已被预读进缓存），不重新打开文件。

### 下一步

1. 修 `read_call_arg.py` 的编码问题（`ensure_ascii=True`）；
2. 用 `--trace-files` 完整 trace 分析 demo 播放期间**所有**文件事件（不只 `.ff`），
   确认播放期间是否还有任何文件 IO；
3. 若播放期间完全没有文件 IO，则"换图"必须在播放前完成——此时唯一的入口是
   demo 播放器读取地图名的位置（`0x813C20` 内部或 `0x49E600` 的第三个调用者）。

## 58. 2026-10-24 23:40–23:55：**关键时间线 —— 地图包请求发生在 demo 播放后约 17 秒**

r76（原始 demo + trace-files）的完整 ff 时间线（启动 t0=1792822537.6）：

| 相对时间 | 请求 | caller |
|---|---|---|
| +1.3 s | patch_code_pre_gfx_mp.ff | 0x776f80 |
| +2.3 s | patch_ui_mp.ff / ui_mp_const.ff | 0xc513d9 |
| +13.6 s | patch_common_mp.ff | 0x776f80 |
| **+30 s** | **patch_mp_crash_tropical.ff** | **0xc513d9** |
| **+32 s** | **patch_mp_crash_tropical.ff** | **0x776f80** |

demo 播放（cbuf 注入）发生在约 +12 s，所以**地图包请求在 demo 播放后约 17–20 秒**，
正好对应 `state` 从 8 走向 10 的地图加载阶段。

### 结论

1. demo 播放**确实**加载地图（不是"复用启动数据"）；
2. 前几轮 `FSOpen` 断点 0 命中是**时序问题**：断点命中/恢复的开销让客户端跑不到 +30 s
   （或被断点拖慢后 demo 提前崩溃）；
3. 换图的窗口是 **demo 播放后 ~15 秒内**——只要在此之前改掉地图名字段，就能让加载走 cross_fire。

### 下一步

1. 不用断点（避免拖慢），改为：demo 播放后等 8 秒，直接 poke `connection+0x108394`
   （此前定位的 demo 地图名字段）为 `mp_cross_fire`，再观察 fastfile 请求变成
   `patch_mp_cross_fire.ff`；
2. 若该字段不对，再试 `connection+0x108294`（相邻字段）与 `0x1C2Bxxx` 系列全局；
3. 成功标志：trace 里出现 `patch_mp_cross_fire.ff` 且截图是 cross_fire。

## 59. 2026-10-24 23:55–00:10：poke `connection+0x108394` 无效；请求表在播放 9 秒时还是 marketplace 包

### 59.1 poke 地图名字段

新增 `tools/poke_map_name.py`：读 `[0x331C0C8] ^ 0xD362501F` 得到 connection，再写
`connection+0x108394`。demo 播放后 8 秒执行：

```
connection = 0x133faf68
before = ""              ← 该字段当时是空的
after  = "mp_cross_fire"
```

结果：地图包请求**仍是 `patch_mp_crash_tropical.ff`**。

→ `connection+0x108394` 不是当前有效的地图名字段（或写入后被重建的连接对象覆盖）。

### 59.2 请求表 0x1D06440 的内容（demo 播放后 9 秒）

| 项 | 名字 | flags |
|---|---|---|
| 0 | `patch_common_marketplace_lite` | 1 |
| 1 | `common_marketplace_lite` | 1 |
| 2 | `patch_common_marketplace_lite1` | 1 |
| 3 | `common_marketplace_lite1` | 1 |

→ 表里此时是 marketplace 包；地图包（+30 秒请求的 `patch_mp_crash_tropical`）还没进表。

### 下一步

1. 把读表时间推到 +25 秒（crash 请求前），看地图包项是否在表里、名字是什么；
2. 若在表里，就在下一次读取时（demo 播放前无法预知）提前把它改成 `patch_mp_cross_fire`；
   但更实际的是：表项只是**加载请求**，改它要抢在 `0x49F280` 遍历之前；
3. 另一个更根本的办法：找"谁把 `patch_mp_crash_tropical` 写进表"（`0x49DE70` 的调用者
   `0x49E3BE` 上游 `0x49E160` 的 16 个调用者），在 demo 播放时定位那一次调用。

## 60. 2026-10-25 00:10–00:30：**地图名来源 —— `CL_MapLoading(ecx, edx)` 与 server 表**

### 60.1 `0x5C7C70` = CL_MapLoading(mapname, gametype)

```asm
0x5C7C82  esi = ecx            ; gametype
0x5C7C85  edi = edx            ; 地图名
0x5C7C87  call 0x5C92B0        ; 有效性检查
0x5C7C95  call 0x775FF0        ; gametype 检查
0x5C7CA5  call 0x776170        ; 格式化
...
0x5C7D4F  mov ecx, edi
0x5C7D51  call 0x49E600        ; LoadMap(地图名)
```

### 60.2 调用点 `0x470760`（启动对局）

```asm
0x470765  ecx = [0x3306910]              ; idx
0x47076B  eax = [ecx*4 + 0x3306994]      ; 状态（>2 才加载）
0x47077E  edx = [ecx*4 + 0x33069D4]      ; server 表项
0x470785  edx = [edx + 8]                ; ← 地图名字符串
0x470794  eax = [ecx*4 + 0x33069D4]
0x47079B  ecx = [eax + 4]                ; gametype
0x47079E  call 0x5C7C70                  ; CL_MapLoading(gametype, mapname)
0x4707A5  ecx = 0xDAE091（默认）
0x4707AA  call 0x5C7C70
```

→ **地图名 = `[[0x33069D4 + idx*4] + 8]`**，gametype = `[... + 4]`，
idx 来自 `[0x3306910]`：这是"服务器信息表"，**可写**。

### 下一步

1. 断点 `0x5C7C70`（CL_MapLoading 入口，参数 edx=地图名）跑 demo 播放，
   看它是否命中、edx 指向什么字符串；
2. 若命中，读 `edx` 指向的字符串（应含 crash_tropical），把该内存改成
   `mp_cross_fire`（等长写入）即可换图；
3. 若 demo 不走这条，则还有 `0x5C7E63` / `0x5C82A9` 两个调用者待查。

## 61. 2026-10-25 00:30–00:50：demo 文件是**明文数据**，不需要播放时采集

### 61.1 用户问题的答案

- **不需要**在 demo 播放时采集；
- **demo 文件本身**就包含真实对局数据（明文，**无加密**）；
- 直接在文件里就能看到文本命令：

```
d 2557 "mp_crash_tropical" 1000
p 1305
s 0194 "OBJECTIVES_...
d 3635 UK_spawn_music_mp_crash_tropical
```

### 61.2 格式

demo = **头部 + 消息流**，每条消息：

```
[u8 type][u32 little-endian length][length bytes payload]
```

头部约 `0x55` 字节（含 1024 字节预留区、时间戳等）；第一条可辨识的消息
（`d 2557 "mp_crash_tropical" 1000`）出现在 `0x11FAE`，其前 5 字节是消息头候选
（`01 9C 00 00 00` 之类，精确对齐还需一次校验）。

### 61.3 为什么之前"播放时采集"失败

demo 播放器解析的是 **demo 自己的命令流**（`d`/`p`/`s`），不经过网络层的
`0x472D80`（gamestate 解析）与 `0x473420`（包分发）——所以这两个断点在播放时 0 命中。
数据在文件里，不在播放时的网络路径上。

### 下一步

1. 把 `tools/parse_demo.py` 的起点/对齐修对（从 0x11FAE 反推消息头），
   解析出完整的 `d`/`p`/`s` 命令序列；
2. 从命令序列里提取：mapname、gametype、configstring 列表、每帧 `p`（packetentities）
   的实体增量字节——这些就是真实服务器下发的原始内容；
3. 拿它们做模板，改 `server1649370` 的 gamestate/snapshot 下发格式。

## 62. 2026-10-25 00:50–01:10：demo 命令格式确认 `[0x01][u32 len][命令文本]`

### 62.1 直接证据

在 demo 前 200 KB 里扫到 **110+ 条文本命令**，每条前面的 5 字节头完全一致：

```
0x8f8e  00 | 01 18 00 00 00 | "d 2493 -3\0"
0x8f9d  01 19 00 00 00 | "d 2533 \xfeTTBuc3Rlcg==\xfe\0"
0x96e0  02 d1 00 | 01 1b 00 00 00 | "s 0201 \"1\"\0"
0xdd8c  ... | 01 1f 00 00 00 | "d 756 none\0" | 01 20 00 00 00 | "r 2\0" | 01 21 00 00 00 | "r 3\0" | 01 22 00 00 00 | "r 1\0" | 01 23 00 00 00 | "v 18\0"
0xddd8  ... | 01 26 00 00 00 | "s 0194 \"OBJECTIVES_WAR_HINT\"\0" | 01 27 00 00 00 | "w 0 12 0\0" | 01 28 00 00 00 | ...
```

→ 格式：`[0x01][u32 little-endian len][payload]`，payload 是**文本命令**：

| 前缀 | 含义 |
|---|---|
| `d <idx> <value>` | dvar / configstring 索引 + 值 |
| `p <idx>` | packetentities（实体帧） |
| `s <idx> "<text>"` | 字符串 configstring |
| `r <n>` / `v <n>` / `w <a> <b> <c>` | 其他命令 |

`len` 字段比纯文本长度略大（例：`d 756 none\0` 11 字节，len=0x1F=31），
说明 `len` 覆盖的是**命令条目**（可能含索引/内联数据），解析时按 len 整段跳过即可。

### 62.2 意义

- demo 里**完整保存**了真实服务器下发的 configstring/dvar/实体帧；
- 这些正是 `server1649370` 需要下发的模板；
- 且**明文可读**，不需要运行客户端采集。

### 下一步

1. 用"从 `0x01` 头 + 合理 len"做滑动解析，把 demo 全部命令提取成结构化列表；
2. 从 `d` 条目里提取 mapname/gametype（已知 `d 2557 "mp_crash_tropical" 1000`）；
3. 从 `p` 条目提取实体增量字节，作为 snapshot 的模板；
4. 用这些真实数据核对并修正 `server1649370` 的 gamestate/snapshot 下发。

## 63. 2026-10-25 01:10–01:25：扫描器完成，发现 len 覆盖"命令 + 尾部数据"

新增 `tools/scan_demo_msgs.py`：滑动扫描 `01 <u32 len> <可打印命令>` 的候选记录
（len 5..0x20000、payload 以 `d/p/s/r/v/w` + 空格开头）。

结果：前 40 条候选全部命中，payload 是文本命令，**但 len 比纯文本长**：

```
offset 35756  len=22  "d 12246 1267\0" + 0x02 0x17 0x00 0x00 0x00 0x20 0x00 ...
offset 36745  len=24  "d 2493 -3\0"    + 0x01 0x19 0x00 0x00 0x00 "d 2533 ..."
offset 36760  len=25  "d 2533 \xfeTTBuc3Rlcg==\xfe\0" + ...
```

→ `len` **覆盖了命令文本之后紧跟的下一条消息头**（例如 `\x02\x17\x00\x00\x00` = type 2、长度 23），
说明 `len` 不是"本命令长度"，而是某个更大的块长度（记录里可能有内联/尾部字段）。

### 结论

- 命令文本本身是**明文 + NUL 结尾**，可以可靠地用文本模式提取（不依赖 len 语义）；
- `len` 语义留待以后精修，不影响"取数据做模板"这一目标；
- 数据的权威来源仍是 demo 文件，客户端播放时采集不必要。

### 下一步

1. 改成"按文本命令 + NUL 分割"的提取器，输出全部 `d`/`p`/`s`/`r`/`v`/`w` 命令；
2. 从 `d` 里取 mapname/gametype/configstring 索引值，生成 `configstring` 模板；
3. 从 `p` 里取实体帧字节（`p <idx>` 之后的内联数据），作为 snapshot 模板；
4. 把模板接到 `server1649370` 的下发路径上验证。

## 64. 2026-10-25 01:25–01:40：demo 命令全量提取成功（2887 条）

新增 `tools/extract_demo_cmds.py`（按文本 + NUL 提取，不依赖 len 语义），对样本 demo：

```
total = 2887
  d: 540    dvar / configstring（idx + value）
  s: 14     字符串 configstring
  r: 62
  v: 20
  w: 526
  p: 1725   packetentities（实体帧）
```

样例：

```
d 2557 "mp_crash_tropical" 1000      ← mapname
d 3635 UK_spawn_music_mp_crash_tropical
s 0194 "OBJECTIVES_WAR_HINT"
s 0195 "UK_M2_"
r 2 / r 3 / r 1
v 18
p <idx>                                （1725 条实体帧）
```

### 意义

- demo 可以**完全离线**解析（不需要客户端、不需要播放）；
- 2887 条命令就是真实服务器下发的完整内容；
- `d` 540 条即 configstring/dvar 模板，`p` 1725 条即每帧实体数据。

### 下一步

1. 解析 `p <idx>` 之后的内联二进制（实体增量字节），提取每帧实体数据；
2. 从 `d` 建立 configstring 索引 → 值 的映射，找出 mapname/gametype/队伍等关键索引；
3. 把这两类数据整理成 `server1649370` 可下发的模板（configstring 列表 + 实体帧序列），
   再对照真实抓包校验字节级格式。

## 65. 2026-10-25 01:40–02:00：提取到 825 条记录（含 p 帧二进制），len 语义待定

新增 `tools/extract_demo_frames.py`：按 `01 <u32 len> <text\0><blob>` 解析，对 `p`
命令输出其后的二进制。结果：

```
records = 825
frames  = 6（示例）
```

样例（第一条 `p` 记录）：

```
offset 56901  frame "11"  record_len 42  text_len 5  blob_len 37
blob = 01 2b 00 00 00 "p 1578\0" 00 d6 51 00 00 01 04 a3 27 63 92 64 00 00 00 56 5f ...
```

→ `p 11\0` 之后的 blob 里**包含下一条记录**（`01 2b … p 1578 …`），说明当前
`len` 解析仍然偏大（覆盖了后续记录），与 §63 的观察一致。

### 但已确认的关键事实

1. `p <frame>\0` 之后**紧跟二进制帧数据**（例：`00 d6 51 00 00 01 04 a3 27 63 92 64 …`）；
2. `w <a> <b> <c>` 也是数据块命令（`w 0 12 0`、`w 2 4 0`、`w 2 384 0`）；
3. 这些二进制就是真实服务器下发的实体/快照内容。

### 下一步

1. 用"`p <n>\0` + 到下一个 `01 <type>` 头"的方式界定 blob（不依赖 len 语义）；
2. 统计每帧 blob 长度分布，确认它与快照头中"实体块长度"字段的关系；
3. 把 blob 作为 `server1649370` 的 snapshot 模板，替换现有手工构造的实体块。

## 66. 2026-10-25 02:00–02:15：记录切分成功 —— 1725 帧实体块可直接提取

新增 `tools/split_demo_records.py`：**不依赖 len 语义**，改用文本头本身定界
（每条 `01 <u32> <文本命令\0>`；两条头之间的字节 = 该命令携带的二进制）。

样本 demo 结果：

```
records = 2887
  d: 540    blob 平均 2673.9 B，最大 52445
  s: 14     blob 平均 7879.5 B
  r: 62     blob 平均 1158.6 B
  v: 20     blob 平均 7324.6 B
  w: 526    blob 平均 2615.9 B
  p: 1725   blob 平均 2351.4 B，最大 62474
```

实例：

```
p 1578   blob_len 443   blob = 00 d6 51 00 00 01 04 a3 27 63 92 64 00 00 00 56 5f ...
p 11     blob_len 0     （紧跟下一条）
p 1305   blob_len 0
```

### 意义

- **1725 条 `p` 帧都带真实实体块字节**（平均 2.3 KB），这正是真实服务器下发的
  快照内容；
- `d` 540 条带 configstring/dvar 更新块；
- 之前"`len` 覆盖后续"的问题被绕开：切分只用文本头，数据完整。

### 下一步

1. 提取**首帧**（baseline）与第 2、3 帧的 blob，逐帧对比（确认它是增量而非全量）；
2. 用已知快照头格式（8 位 last_changed + 5 个内容块）解析这些 blob，定位实体块边界；
3. 把首帧 blob 直接作为 `server1649370` 的 snapshot 内容模板（替换手工实体块）。

## 67–69. 2026-10-25 02:15–02:35：**demo 里的快照体 = 真实服务器下发内容，已导出**

### 67. 格式验证

从 demo 提取的最大 `p 15` 帧（62474 字节）开头：

```
00 d0 97 1a 00 01 04 05 d4 09 00 00 06 c8 10 bf ...
```

按 `docs/SNAPSHOT-FORMAT-VERIFIED.md` 解析：

| offset | 值 | 含义 |
|---|---|---|
| 0 | `00` | **svc_snapshot** ✓ |
| 1–4 | `d0 97 1a 00` | serverTime = 1742800 |
| 5 | `01` | delta_distance |
| 6 | `04` | flags |
| 7… | `05 d4 09 00 00` | 位字段（含 8 位 last_changed） |

→ **demo 的 `p` 帧 blob 就是真实快照体**，与已验证的快照头格式完全吻合。

### 68. 规模

| 指标 | 值 |
|---|---|
| 总 `p` 帧 | 1725 |
| ≥100 字节的帧 | **1050** |
| 最大帧 | **62474 字节**（baseline，含全量实体） |
| 次大 | 40982 / 37599 / 34930 / 33481 |

### 69. 导出模板

新增 `tools/export_demo_frames.py`，已导出到 `runs/demo-frames-big/`：

```
00-62474.bin   00 d0 97 1a 00 01 04 05 d4 09 ...
01-40982.bin   00 9c 56 17 00 01 04 15 64 6a ...
02-37599.bin   00 00 83 18 00 01 04 71 24 3b ...
03-34930.bin   02 31 04 ...            （非快照，另一类记录）
04-33481.bin   00 b8 2c 07 00 01 04 49 f4 49 ...
```

**这 4 个 `00-*.bin` 就是真实服务器下发的快照体**，可直接作为 `server1649370`
的 snapshot 内容模板（服务端只需加 ack 前 4 字节并按 netchan 规则发送）。

### 下一步

1. 让 `server1649370` 读 `runs/demo-frames-big/00-62474.bin` 作为 snapshot 载荷；
2. 在 demo 起状态（state 7+）后下发，验证客户端 `Entities=1` 且不报 stream error；
3. 成功后再把 configstring（`d` 命令）也按同样方式从 demo 提取并下发，完成"真实数据接管"。

## 70. 2026-10-25 02:35–02:50：demo 真实快照接入服务端（首次实验，客户端先崩）

### 70.1 服务端发送路径已确认

`server1649370/gameserver.py::send_due_snapshots`：

```python
data = path.read_bytes()                 # 读 --snapshot-file（svc 数据，从 svc_snapshot 开始）
payload = b"\x00\x00\x00\x00" + data     # 前 4 字节 ack
if payload[4] == 0:                      # svc_snapshot
    payload = payload[:5] + struct.pack("<I", 72192 + index*500) + payload[9:]   # 改写 serverTime
```

→ **demo 的 `p` 帧 blob（从 `00` svc_snapshot 开始）正是这个 `--snapshot-file` 需要的格式**，
不需要做任何转换。

### 70.2 首次实验

用 `runs/demo-frames-big/00-62474.bin`（62 KB baseline）作为 `--snapshot-file`，
流程：假 dvar → `cl_demo_play` → 8 秒后 connect → gs + forward + pump。

结果：

| 观测 | 值 |
|---|---|
| 客户端存活 | **否**（实验结束时已退出） |
| `Entities` 断点 | 0 |
| gs 记录 | `in connect/stats/inband 1`、`meta gamestate_source`，**没有 snapshot 发送记录** |

→ 客户端在 snapshot 发出前就退出了（demo 播放本身在 20 秒左右会崩），
所以这次不能判定"真实快照是否被接受"。

### 下一步

1. 先解决 demo 播放的稳定性（`state 8` 后约 20 秒退出）——可能是 §71 的 dvar 补丁或
   资源缺失导致；
2. 再用"客户端存活时间窗内"下发 demo 快照（把 `--snapshot-delay` 提前到 1–2 秒）；
3. 若客户端稳定，验证 `Entities=1` 与实体表是否被真实快照填充。

## 71. 2026-10-25 02:50–03:05：去掉断点后客户端 5 秒即崩 —— 是 gs 的 gamestate 触发

### 71.1 对照

| 实验 | 是否有 gs | 客户端存活 |
|---|---|---|
| r51（§34） | **无** | ≥ 24 秒（截图动态、state 10） |
| r82 | 有（delay 1、snapshot-delay 3） | 已退出 |
| **r83** | 有（delay 0.5、snapshot-delay 1、无断点） | **5 秒即退出** |

r83 的 gs 日志只有：

```
in oob 2 / connect 1 / out oob 3 / in stats 1 / in inband 1 / meta gamestate_source 1
```

**没有 snapshot 记录** —— 也就是说客户端是在**收到 gamestate 之后、快照发出之前**就崩了。

### 71.2 结论

- demo 播放本身是稳定的（r51 存活 24 秒+）；
- 崩溃由**服务端下发的 gamestate** 触发（越早发越早崩：delay 3 → 20 秒，delay 0.5 → 5 秒）；
- 因此"真实快照"这条链路当前卡在 **gamestate 让客户端崩溃**，与快照内容无关。

### 下一步

1. 定位 gamestate 触发崩溃的具体字节：用断点 `0x472D80`（gamestate 解析入口）和
   `0x470467`（`state=3` 写入点）观察 gamestate 被解析到哪一步；
2. 对比 `runs/gamestate-3426.bin`（真实抓包）与 gs 的 `--gamestate-source native`
   生成内容，检查 client_num / challenge / mapname 等字段；
3. 修好后重发 demo 快照（`00-62474.bin`），验证 `Entities=1`。

## 72. 2026-10-25 03:30–04:00：接手 Codex 交接；确认武器计数机制

### 72.1 接手内容

已读 `docs/DEEPSEEK-HANDOFF.md`、`tools/parse_demo_outer.py`、`tools/run_match.py`、
`evidence/experiments/20261024-demo-outer-and-weapon-blocker.json`、
`evidence/experiments/20261024-demo-delta-and-netchan-regression.json`。

关键事实（Codex 已确立）：

- netchan 已恢复：**gamestate 序号从 3 开始**、单分片 **10 字节头**（`086a140`）；
- demo 外层从 `0x8020` 解析：type 2 = `02 + u32 seq + u32 len + payload`，18,366 包；
- 精确导出（`runs/demo-outer-exact/`）：gamestate 6407（zlib 解压）、291 configstring、
  baseline 包 17 = 245 字节（delta_distance=0）、首个 p 增量包 113 = 259 字节（delta_distance=1）；
- **当前精确阻塞**：武器定义索引 — 本地 1136 vs demo 要求 1224（差 88）；
- 删 configstring 7184–7218（r104）→ 越过错误 181 但在 `0x58F3C0` 空指针崩溃。

### 72.2 环境确认

- demo 原路径 `E:\GAME\COD\使命召唤OL\main\demo\` **已不存在**；
  实际在 `E:\GAME\COD\1649370\workspaces\offline-runs\20261023-codex-delay-a2\runtime\main\demo\`；
- `runs/demo-outer-exact/` 完整保留（gamestate 6407/6411、baseline 245、p 增量 259/209/268/332/352）；
- `snapshot_due` 的 15 秒钳制已由 Codex 移除（第 321 行 `+ self.snapshot_delay`）。

### 72.3 武器计数机制（本轮新证据）

`0x42F432 inc dword ptr [0x1988634]` 的上下文：

```asm
0x42F424  mov ecx, [0x1988634]     ; 计数作为新索引
0x42F42A  call 0x431810            ; 创建复合武器
0x42F432  inc dword ptr [0x1988634] ; 只在"创建新复合武器"时递增
```

demo 播放采样：`0x1988634` 全程 **0**（从启动到播放 24 秒），`net_state` 1→0
（本次 demo 未进入 8/10，需复跑确认）。

→ **demo 播放路径不创建复合武器**（`0x42F2F0` 查找命中已有字符串），
而服务端 gamestate 路径会创建（索引 1136）。
这印证了 HANDOFF 的推断：**差异在"预注册"**，demo 的某个前置步骤把武器注册好了。

### 下一步

1. 复跑 demo 播放，确认 `0x42F2F0`（查找已有字符串）在 demo 路径的命中率；
2. 对比服务端 gamestate 路径（`0x42F3E0` 返回 miss → 创建 → 1136）；
3. 用 `run_match.py` 复现 Codex 的 r103（`--gamestate-file runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin`），
   确认武器错误可稳定复现后，再找 88 个缺失注册。

## 73. 2026-10-25 04:00–04:30：r105 复跑（run_match + 精确 gamestate 文件）

### 73.1 命令

```powershell
python tools/run_match.py --name r105 ^
  --gamestate-file runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin ^
  --snapshot runs/demo-outer-exact/baseline-outer17-245.bin ^
  --snapshot-delay 20 --seconds 70 --match-duration 45 ^
  --stage-loose --map mp_crash_tropical
```

### 73.2 gamestate 文件已确认格式正确

```
00 00 00 00 | 03 | 01 00 00 00 | "mp_crash_tropical\0" | "war\0" | 7e 6d b5 ff ...
ack(4)       svc  长度1
```

`registration_checksum=0xffb56d7e`（客户端本地值），configstring[0] =
`\g_gametype\war\mapname\mp_crash_tropical`。

### 73.3 服务端日志（r105-gs.jsonl）

```
in connect 1 / in stats 1 / in inband 53
out fragment gamestate 6
in gamestateupdate 4          ← 客户端回应了 gamestate
out fragment snapshot 31      ← 快照已排队并发送
```

### 73.4 结果与差异

| 项 | r105 |
|---|---|
| 采样 states | **[0, 0, 0, 0]**（t=20/35/50/65） |
| ui_state | 5 |
| snapshots_queued | 26 |
| 武器错误（0x59B560） | **未观察到**（events.jsonl 是 10-23 的旧文件，runtime 复用未刷新） |

→ 与 Codex 的 r103 不同：r103 到了 state 8+ 并在 `0x59B560` 报武器错误；
r105 的 `gamestateupdate` 有 4 次说明客户端确实收到了 gamestate，但采样 state 全 0。

### 下一步

1. 用 `--client-breakpoint 0x59B560:WeaponError` 复跑，直接确认是否触发武器错误；
2. 缩短采样间隔（run_match 固定 t=20/35/50/65 太疏，state 可能在 1–2 秒内变化）；
3. 若 r105 的 gamestate 被接受但 state 回 0，检查 `gamestateupdate` 的实际内容
   （gs 日志里有 4 次 update，可能是客户端的 ack 而非状态推进）。

## 74. 2026-10-25 04:30–05:00：**r105 稳定复现武器索引错误 181（用户截图确认）**

### 74.1 复现证据

`runs/r105-screenshot.png` 与用户提供的截图一致，客户端在大厅弹出：

```
错误
181 ** 646 0 0 8738 9321 1136 1224
[退出]
```

- **181**：错误码；
- `** 646 0 0 8738 9321`：武器字符串（configstring 7184）；
- **1136**：`0x42F3E0` 本地解析出的索引；
- **1224**：demo 数据要求的索引。

→ 用 `run_match.py --gamestate-file runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin`
**稳定复现**了 HANDOFF 的精确阻塞点（此前采样 state=[0,0,0,0] 是因为弹窗后客户端退回大厅）。

### 74.2 武器解析函数（`0x59B560`）

```asm
0x59B560  push ebp / mov ebp,esp / push esi
0x59B564  lea esi, [edi + 0x1748]    ; 武器字符串字段
0x59B56A  call 0x514880              ; 读 configstring
0x59B57B  cmp dword ptr [ebp+8], 0
0x59B581  cmp al, 0x2a               ; '*' 复合武器前缀
0x59B589  push 0 / push esi
0x59B58C  call 0x42F3E0              ; 解析/创建 → eax = 索引
0x59B594  cmp eax, edi               ; 与期望比较
0x59B596  jne 0x59B676               ; 不等 → 错误路径（181）
```

### 74.3 结论

- 错误稳定可复现，路径确定（`0x59B560` → `0x42F3E0` → `0x42F432` 创建 → 1136）；
- 与 demo 播放的差异是 **88 个先行注册**；
- 修复方向不变：先补齐这 88 个注册（或让 configstring 7184 的武器字符串在服务端路径也能命中已有定义）。

### 下一步

1. 用 `--client-breakpoint 0x59B560:WeaponIndex` 跑一次，记录 `eax`（1136）与 `edi`（期望 1224）的现场；
2. 在 demo 播放路径读 `0x42F2F0`/`0x1988634`，确认 1224 个定义是何时注册的；
3. 若 88 个来自 demo 早期数据，把它们并入服务端 gamestate 的 configstring 前置段。

## 75. 2026-10-25 05:00–05:20：武器引用循环定位（1700 次解析，edi=引用编号）

### 75.1 `0x59B560` 的调用者

```
0x454A54 / 0x454B55 / 0x60FDCB
```

其中 `0x454A30` 附近是一个**循环**：

```asm
0x454A4D  mov edi, 1
0x454A52  push 1
0x454A54  call 0x59B560      ; 逐引用解析（edi = 引用编号）
0x454A59  inc edi
0x454A5D  cmp edi, 0x6a4     ; 0x6A4 = 1700
0x454A63  jb 0x454A52
```

→ `0x59B560` 被调用 **1700 次**，`edi` 是**武器引用编号**（1..1700）。

### 75.2 比较语义

`0x59B594 cmp eax, edi`：

- `eax` = `0x42F3E0` 返回的**定义索引**（本地创建/查找结果）；
- `edi` = **引用编号**。

错误出现在引用 **1224**（字符串 `** 646 0 0 8738 9321`）：
本地定义索引 **1136** ≠ 引用编号 **1224**，差 **88**。

→ 说明本地在这之前只创建了 **1135 个定义**（引用 1..1135 各一个），
而 demo 数据里引用 1224 对应的定义正好在第 1224 位。
**缺失的 88 个 = demo 播放时多创建的定义**（同循环内，本地没创建）。

### 下一步

1. 在 **demo 播放**路径下断 `0x59B560`，记录引用 1224 时 `eax` 是多少（若也是 1224，说明 demo 多注册了 88 个）；
2. 对比 demo 播放与服务端路径在**同一循环**（`0x454A30`）的迭代次数与 `0x42F3E0` 返回差异；
3. 若 demo 播放确实多创建 88 个，找出它是从哪个 configstring/资源注册的，然后把这些注册补到服务端 gamestate 的前置段。

## 76. 2026-10-25 05:20–05:40：r106 断点复跑（断点未进 safe list；runtime 复用导致 events 不刷新）

### 76.1 命令

```powershell
python tools/run_match.py --name r106 ^
  --gamestate-file runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin ^
  --snapshot runs/demo-outer-exact/baseline-outer17-245.bin ^
  --client-breakpoint 0x59B560:WeaponIndex ...
```

### 76.2 结果

| 观测 | 值 |
|---|---|
| states | [0, 0, 0, 0] |
| ui_state | 5 |
| snapshots_queued | 26 |
| 断点提示 | `warning: 0x59B560:WeaponIndex is not in the safe list; if the run stalls at state 8 or loses all traces, this is why` |
| `WeaponIndex` 命中 | **0**（`runtime\events.jsonl` 仍是 10-23 13:57 的旧文件，未刷新） |

### 76.3 两个环境问题

1. `0x59B560` 不在断点 safe list（热路径，可能拖慢）；
2. `--reuse-runtime` 复用 `20261023-codex-delay-a2` 时 `events.jsonl` 不重建，
   无法看到本次断点命中。

### 下一步

1. 用**新 runtime**（`--runtime` 换新名、不加 `--reuse-runtime`）重跑断点实验，
   保证 events 是本轮的；
2. 或改用"轮询内存"代替断点：在连接后每 200 ms 读 `0x1988634` 与武器表，
   观察 1136 何时产生、1224 是否出现过；
3. 若断点确实不可用，则退回静态路径：`0x454A30` 循环 + `0x42F3E0` 返回值的
   计算方式（引用编号 vs 定义索引）已经明确，重点是"demo 播放为何多 88 个定义"。

## 77. 2026-10-25 05:40–06:00：r107 新 runtime 失败；gamestate 结构定位

### 77.1 r107（新 runtime 断点实验）

```powershell
python tools/run_match.py --name r107 --runtime r107flow ... --client-breakpoint 0x59B560:WeaponIndex
```

结果：`[run_match] engine never initialised`（exit 1）。

原因：`run_match` 固定给 launch 传 `--reuse-runtime <runtime>`，而 `r107flow` 这个 runtime
不存在（launch 的 reuse 语义要求目录已存在），所以客户端没有起来。

→ 需要先准备好 runtime（复制已验证的 `20261023-codex-delay-a2\runtime`），
或改 `run_match` 让它不带 `--reuse-runtime` 重建。

### 77.2 gamestate stream 结构（离线解析）

`runs/demo-outer-exact/gamestate-stream-6407.bin` 开头：

```
00: 03                       svc_gamestate
01: 01 00 00 00              某字段（=1）
05: "mp_crash_tropical\0"    mapname
17: "war\0"                  gametype
1B: 00 00 00 00
1F: 00
20: 04 23 01 af
24: \2482\2\2485\18\2490\214\2491\0\3056\2\g_gametype\war\g_hardcore\0\mapname\...
```

→ configstring 从 `0x24` 附近开始，第一条是 `\2482\2\2485\18...`（含 dvar 键值对）。

### 下一步

1. 复制 runtime 到新目录后重跑 r107（断点实验）；
2. 或改 `run_match` 支持"不带 --reuse-runtime 的新 runtime"；
3. 用 `parse_demo_outer.py` 的 `--registration-checksum` 一键再生 gamestate，
   再做断点实验（避免手工准备文件）。

## 78. 2026-10-25 06:00–06:20：r108 断点实验的 events 仍不可用

### 78.1 r108（就绪 runtime + 断点）

准备好 `r107flow\runtime`（复制 88,580 个文件）后重跑：

```
[run_match] engine ready
[run_match] states: [0, 0, 0, 0]
[run_match] delivery: snapshots_queued=20 ok=True
```

断点提示仍为 `0x59B560 not in the safe list`；截图 864,741 字节（与 r106 相同的错误弹窗）。

### 78.2 events 路径异常

`r107flow` 下唯一的 events 是：

```
r107flow\reuse-3b946d9a\events.jsonl  0 字节  2026-10-24 16:03:12
```

→ 0 字节：本次运行的断点/文件 trace **没有写入**（`--reuse-runtime` 的复用目录机制
把 events 放到 `reuse-<hash>` 子目录且未刷新），所以 `WeaponIndex` 命中数不可见。

### 结论

- 181 错误已稳定复现（r105/r106/r108 截图一致）；
- **断点路线在复用 runtime 下不可用**（events 为空），继续调断点性价比低。

### 下一步（改用轮询，不依赖 events）

1. 写 `tools/watch_weapon_count.py`：轮询 `0x1988634`（武器计数），记录每次变化；
2. 手动跑一次完整连接（LSG + launch + login + gs gamestate + forward + pump），
   同时轮询该计数，确认它从 0 → 1135 的过程与时机；
3. 若峰值确实是 1135，则"缺 88 个"的根因在**定义创建路径**（`0x42F2F0` 查找 vs
   `0x431810` 创建），而不是 configstring 数量。

## 79. 2026-10-25 06:20–06:50：武器计数采样脚本就绪；手动流程连不上（ui=5, conn_5e8=3）

### 79.1 新工具

`tools/watch_weapon_count.py`：轮询 `0x1988634`（武器定义计数）并记录每次变化
（同时记录 `net_state`、`ui_state`），支持 `--seconds/--interval/--output`。

### 79.2 手动流程（r110）结果

| 项 | 值 |
|---|---|
| 登录后 `net_state` | **0** |
| `ui_state` | 5 |
| `login_step` / `login_ready` | 0 / 2 |
| `auth_state` / `lsg_state` | 9 / 2 |
| `conn_5e8` | **3**（CA_LOADING） |
| gs 收到 | 只有 `in inband 17`（**没有 connect/stats**） |
| 武器计数采样 | 全程 0（1 个样本） |

→ 手动流程（LSG + launch + login + gs + forward）**没有建立连接**：
客户端停在 `ui_state=5 / conn_5e8=3` 的加载屏，gs 只收到 inband。

### 79.3 与 run_match 的差异

`run_match`（r105/r106/r108）能到弹 181 的阶段，而手动流程不能。差异在
`run_match` 的额外步骤：**ring-a-drain（block）**、**refresh hook**、`--reuse-runtime` 的
完整初始化序列。手动流程缺了这些，客户端网络状态机没有推进到 connect。

### 下一步

1. 用 `run_match` + **并行轮询**（run_match 在后台跑，轮询脚本同步采 `0x1988634`）；
2. 或把 `run_match` 的 ring-a-drain / refresh hook 步骤复制进手动流程；
3. 采样目标：确认武器计数峰值是 1135 还是更高，从而判定"缺 88 个"发生在
   定义创建路径还是 configstring 数量。

## 80. 2026-10-25 06:50–07:20：**拿到完整 state 迁移与武器计数时序（weapon_count 峰值=1）**

`run_match` 后台跑 + `watch_weapon_count.py` 并行轮询（0.2s）：

```
t=0.00   weapon=0  net=0  ui=5
t=8.62   weapon=0  net=4  ui=5    ← connect 发出
t=8.82   weapon=0  net=5  ui=5
t=9.62   weapon=0  net=7  ui=5    ← 越过 inband 门槛（0x5C22FC）
t=18.83  weapon=0  net=8  ui=5    ← gamestate 开始处理
t=20.04  weapon=1  net=8  ui=5    ← 武器计数首次递增（只 +1）
t=24.85  weapon=1  net=0  ui=5    ← 回 0（181 错误弹窗）
t=27.05  weapon=0  net=0  ui=5
t=27.25  weapon=1  net=0  ui=5
peak=1
```

### 80.1 三个关键结论

1. **state 确实到 8**（此前 run_match 采样 [0,0,0,0] 是因为采样点太晚，错误弹窗后已回 0）；
2. `0x1988634` **峰值只有 1** —— 它是"**本次连接新建的复合武器数**"，不是总数；
3. 结合 HANDOFF 的 1135/1136：**1135 = 预注册**（启动/资源加载时已有），
   **1 = 本次新建**，合计 1136，而 demo 要求 1224 → **缺的 88 个也在预注册侧**。

### 80.2 意义

- "缺 88 个"不在本次连接，而在**启动/资源加载阶段的预注册**；
- 下一步应查"1135 个预注册"是在哪里完成的（哪个资源/文件提供），
  以及 demo 播放时为什么会有 1223 个预注册。

### 下一步

1. 启动后（连接前）读 `0x1988634`（应为 0）与武器表基址，确认 1135 个预注册的存放位置；
2. 反汇编 `0x42F2F0`（查找已有字符串）看它遍历的表结构，找到 1135 条记录的来源；
3. 对比 demo 播放前的同一张表大小（1223 条），定位差异来源（可能是某个 patch 资源）。

## 81. 2026-10-25 07:20–07:40：**武器定义表结构定位（0x1988B50 / 0x827F738）**

### 81.1 `0x42F2F0`（查找已有复合武器字符串）

```asm
0x42F316  mov esi, [0x827F73C]      ; 查找索引
0x42F31D  mov edi, [0x827F738]      ; 表大小（预注册数量）
0x42F32E  mov edx, [esi*4 + 0x1988B50]   ; 表项 → 字符串指针
0x42F335  mov edx, [edx]
0x42F33D  call 0x7745E0             ; strcmp
0x42F345  test eax, eax
0x42F34A  mov eax, esi              ; 命中 → 返回索引
...
0x42F351  push ebx / mov ebx, 1
0x42F360  loop:
0x42F364    mov eax, [ebx*4 + 0x1988B50]
0x42F36B    mov esi, [eax]
0x42F37E    call 0x431A60           ; 解析复合武器
0x42F38A    imul eax, eax, 0x1474
0x42F390    add eax, 0x19E30F0      ; 定义表基址
```

→ **两个关键全局**：

| 全局 | 含义 |
|---|---|
| `0x1988B50` | 字符串表基址（**指针数组**，每项 4 字节） |
| `0x827F738` | 表大小（预注册数量） |
| `0x827F73C` | 当前查找索引 |
| `0x19E30F0` | 定义结构表基址（每项 **0x1474** 字节） |

### 81.2 启动后实测（r113，未登录）

```
table_count = 0   table_idx = 0   表项 1..5 全 null
```

→ 表在**登录/加载前是空的**，1135 个预注册发生在登录之后、gamestate 之前。

### 81.3 附：r112 启动失败原因

```json
"error": "动态 WFP 守卫未确认 ready；客户端保持挂起"
```

→ 忘了传 `--loopback-tcp-guard`；加上后 r113 正常（engine-init 5.569s）。

### 下一步

1. 在 **state 7→8 之间**（gamestate 处理前）读 `0x827F738` 与表项，确认 1135 是否已就位；
2. 在 demo 播放路径同一时刻读相同全局，对比是否 1223；
3. 若 demo 侧确实多 88 个，顺着 `0x42F360` 循环的 `0x431A60` 解析路径找它们从哪个资源注册。

## 82. 2026-10-25 07:40–08:00：**决定性数据 —— 武器表在 gamestate 时重建，只到 1136（demo 要 1224）**

`run_match` 后台 + 扩展后的 `watch_weapon_count.py`（同时采 `0x1988634` 与 `0x827F738`）：

```
t=0.00   weapon=0  table=1135  net=0  ui=5   ← 启动后预注册表已有 1135
t=8.22   weapon=0  table=1135  net=5  ui=5
t=9.02   weapon=0  table=1135  net=7  ui=5
t=18.24  weapon=0  table=0     net=8  ui=5   ← gamestate 处理：表被清空
t=19.24  weapon=0  table=676   net=8  ui=5   ← 重建中
t=19.44  weapon=1  table=1136  net=8  ui=5   ← 重建完成 = 1136，随即 181 错误
t=23.45  weapon=1  table=0     net=0  ui=5   ← 清空
t=25.65  weapon=0  table=581   net=0  ui=5
t=25.85  weapon=0  table=1135  net=0  ui=5   ← 回到 1135
peak_table = 1136
```

### 82.1 结论

1. **启动后预注册表 = 1135**（`0x827F738`）；
2. gamestate 到达时**表被清空（0）并按 gamestate 内容重建**；
3. 重建只到 **1136**（1135 + 本次新建 1），而 demo 要求 **1224**；
4. 所以"缺 88 个"发生在**重建阶段**——服务端 gamestate 提供的武器来源比 demo 少 88 个。

### 82.2 下一步（方向已明确）

1. 在 **demo 播放**路径做同样采样：看表从多少重建到多少（预期 1224），
   确认 demo 的 gamestate 比服务端多出 88 个来源；
2. 对比 `gamestate-network-ffb56d7e-6411.bin` 与 demo 原始 gamestate
   （`gamestate-stream-6407.bin`）的 configstring 差异（7184–7218 之外还有哪些）；
3. 把缺的 configstring 补进服务端 gamestate（用 `build_native_gamestate` 或直接拼接），
   使重建结果达到 1224。

## 83. 2026-10-25 08:00–08:20：**决定性对照 —— demo 播放表到 1258/1266，服务端只 1136**

### 83.1 demo 播放路径（r115）

```
t=0.00   weapon=0  table=0     net=1  ui=0
t=11.02  weapon=0  table=0     net=7  ui=0
t=11.42  weapon=0  table=0     net=8  ui=0
t=14.83  weapon=35 table=1258  net=8  ui=0   ← 表重建到 1258
t=15.03  weapon=35 table=1258  net=10 ui=0
t=15.23  weapon=43 table=1266  net=10 ui=0
peak_table = 1266
```

### 83.2 两条路径对照

| 路径 | 表重建峰值 | weapon_count | 结果 |
|---|---|---|---|
| **服务端 gamestate**（r114） | **1136** | 1 | **181 错误** |
| **demo 播放**（r115） | **1258 → 1266** | 35 → 43 | **正常**（ui=0、state 10） |

→ demo 路径的武器来源比服务端多 **122 个**（1258 - 1136），且 demo 的 `weapon_count`
是 35/43（多次新建），服务端只有 1。

### 83.3 来源判断

demo 播放走的是 **`d`/`p`/`s` 文本命令流**（540 条 `d`），而服务端只发 gamestate 的
configstring（291 条）。demo 的**命令流里有服务端 gamestate 缺失的武器定义**，
这解释了 122 个差距。

### 下一步

1. 从 demo 的 `d` 命令里筛出武器相关 configstring（7184–7218 之外还有哪些索引）；
2. 把这些命令按顺序补进服务端 gamestate（或改为下发 `d` 命令序列）；
3. 目标：让服务端路径的 `0x827F738` 至少到 **1224**，消除 181。

## 84. 2026-10-25 08:20–08:40：demo 的 `d` 命令**不含**武器定义 —— 122 个差距来自 fastfile

### 84.1 统计结果

对样本 demo 的 540 条 `d` 命令：

```
d commands        = 540
index range       = 13 .. 12278
unique indexes    = 200
composite (*)     = 0        ← 没有任何值以 * 开头
indexes 7184-7218 = 0        ← 也不在这个范围
```

→ demo 的文本命令流**不是**武器表来源。

### 84.2 那 122 个差距从哪来

对照事实：

| 路径 | 表重建峰值 | 额外加载 |
|---|---|---|
| demo 播放 | **1258 → 1266** | **播放会加载地图 fastfile**（`patch_mp_crash_tropical.ff` 等） |
| 服务端 gamestate | **1136** | 只有 gamestate 的 291 条 configstring |

→ demo 播放时表能到 1258，靠的是**加载地图 fastfile 后注册的武器定义**；
服务端路径没有加载这些 fastfile，所以只重建到 1136（差 122）。

### 84.3 下一步

1. 让服务端路径也触发地图 fastfile 加载（客户端在 ui=5 时不会主动加载）；
2. 或从 `mp_crash_tropical.ff`（及 patch）里离线提取武器定义，补进 gamestate 的 configstring；
3. 最直接：把 demo 播放时**已注册好的 1258 个武器表**在 state 7 后快照下来，
   作为服务端路径的预置表（需要写内存注入，风险较高）。

## 85. 2026-10-25 08:40–09:00：**demo 回放模式与网络注入互斥**（connect/inject 都会崩）

### 85.1 混合实验（r116/r117）

先 `cl_demo_play` 让客户端正常播放（`state 10`、武器表 `0x4F2 = 1266`），再尝试让服务端接管：

| 方式 | 结果 |
|---|---|
| `ring_bridge connect`（r116） | 客户端 **1 秒退出** |
| `inject_client_gamestate`（写 ring_b + state=3，r117） | 客户端 **2 秒内退出** |

→ **demo 回放模式（state 10）与网络模式互斥**：一旦触碰连接/环形缓冲，客户端立即崩溃。

### 85.2 与 HANDOFF 的印证

HANDOFF 记录的 r97 是反向（先服务端再 demo）：ACK 了 snapshot 1000/1001 后 demo delta 崩在 `0x421A73`。
现在正向（先 demo 再服务端）也是崩。**两条混合顺序都不可行**。

### 85.3 结论

- demo 能加载地图、能正常播放（武器表 1266）——这是**已验证的正面事实**；
- 但 demo 的"回放模式"是独立状态机，**不能与网络模式共存**；
- 所以必须**独立地**让服务端路径触发地图加载（等价于 demo 播放时做的 `CL_Init` + fastfile 加载），
  而不能"借" demo 的状态。

### 下一步

1. 找出 demo 播放时触发地图加载的**最小调用序列**（`CL_Init` → load fastfile → state 7/8/10）；
2. 在服务端连接路径（connect 之后、gamestate 之前）**手动调用**该序列；
3. 若成功，服务端 gamestate 就会落在"地图已加载"的状态里，武器表能从 1266 起算，
   181 错误应随之消失。

## 86. 2026-10-25 09:00–09:20：地图加载路径复核与"最小调用序列"计划

### 86.1 已知矛盾

- r58 trace：demo 播放时确实请求 `patch_mp_crash_tropical.ff`（**播放后 17–20 秒**，r76 时间线）；
- 但 `0x49E160`（Com_LoadFastfiles）、`0x49ED40`（LoadFastfile）、`0x776F00`（FileExists）
  在 demo 播放期间**都 0 命中**（r67/r68/r72）。

→ 说明 demo 播放时地图 fastfile 的加载**走第三条路径**（既不是 Com_LoadFastfiles，
也不是 LoadFastfile/FileExists 的已知调用点），或断点因热路径/时序未生效。

### 86.2 demo 播放的已知调用序列（0x813C20 内部）

```
0x813C20  CL_PlayDemo(name)
  0x5C8A70  CL_Shutdown
  0x5C83D0  CL_Init
  0x813D34  net_state = 7
  ...       （后续分支：0x813E96 lea esi,[connection+0x108394] → 0x49E600 LoadMap）
```

但 `0x813E96` 在 demo 播放时 0 命中（§43）→ 它走的是另一条子分支。

### 86.3 下一步（服务端路径独立触发地图加载）

在 `connect` 完成（state 5）后、gamestate 之前，尝试手工执行 demo 的初始化序列：

1. `call 0x5C8A70`（CL_Shutdown）；
2. `call 0x5C83D0(1)`（CL_Init）；
3. 观察 `net_state` 是否写 7（`0x813D34` 的等价效果）；
4. 若到 7，再发 gamestate/快照，检查武器表是否从 1135 起算而不是被清空重建到 1136。

用 `tools/call_fn_1649370.py`（已有）可以直接在主线程调用 `0x5C83D0`，
但它是热路径函数，必须先确认参数（`push 1`）。

### 备注

本轮为 round 79/80，接近轮次上限；以上是下一步的明确执行计划，
尚未执行（需要一次新客户端会话与调用序列验证）。

## 87. 2026-10-25 09:20–09:40（round 80/80）：手工调用 CL_Shutdown 挂起

### 87.1 实验

在 `state=0`（登录后但未连接）时通过 `call_fn_1649370.py` 调用：

```
call 0x5C8A70 (CL_Shutdown)          → returned_eip = "timeout"，客户端随后退出
call 0x5C83D0(1) (CL_Init，未执行到)   → 客户端已死
```

→ **在 state 0 手工调用 CL_Shutdown 会挂起/崩溃**，说明它依赖连接对象已就绪
（或在主线程之外有同步要求）。直接"抄 demo 的初始化序列"这条路不可行。

### 87.2 本轮（68–80）累计成果

1. 接手 Codex 交接（HANDOFF、parse_demo_outer、run_match、两份 evidence）；
2. `run_match + gamestate-network-ffb56d7e-6411.bin` **稳定复现 181 错误**（用户截图一致）；
3. 定位武器表结构：`0x1988B50`（字符串表）、`0x827F738`（表大小）、`0x19E30F0`（定义表，0x1474/项）；
4. 拿到完整 state 时序：`0 → 4 → 5 → 7 → 8`（t≈9.6 到 7、t≈18.8 到 8）；
5. **关键对照**：demo 播放表 **1258→1266**、weapon 35→43；服务端 gamestate 表 **1136**、weapon 1；
6. 排除 demo 的 `d` 命令（540 条无 `*` 值、无 7184-7218）→ 122 差距来自 **fastfile 注册**；
7. 确认 **demo 回放与网络互斥**（connect 1s 崩、inject 2s 崩）；
8. 手工 `CL_Shutdown` 在 state 0 挂起 → 不能直接抄 demo 初始化序列。

### 87.3 给下一次接手的起点

- **正面事实**：demo 能加载地图并注册 1266 个武器定义（地图加载机制没问题）；
- **核心障碍**：服务端路径没有触发地图 fastfile 加载，导致武器表只有 1136，触发 181；
- **下一步建议**：
  1. 找出 demo 播放时**真正触发 fastfile 加载**的第三条路径（在 `0x49E160/0x49ED40/0x776F00`
     之外，按 r58 trace 的 `patch_mp_crash_tropical.ff` 请求回溯）；
  2. 或在服务端 connect 完成（state 5）后再尝试 `CL_Init`（本次在 state 0 调用失败）；
  3. 或从 `mp_crash_tropical.ff` 离线提取 122 个缺失武器定义，补进 gamestate configstring。
- **目标状态**：未达成（ui_state=5、181 错误、无 mp_cross_fire 画面）。

## 88. 2026-10-25 09:40–10:10：**重大纠正 —— 0x49E600 是 LoadDemo，不是 LoadMap**

### 88.1 断点命中的明文证据（r121）

在 demo 播放中给 `0x49E600` 下断点（等满 32 秒），命中的 stack 里出现明文：

```
... 64 65 6d 6f 2f 30 43 2d 32 30 32 31 2d 38 2d 32 36 5b 31 39 2d 32 36 2d 32 34 5d 77 61 72 2e 64 65 6d 6f 00
    "demo/0C-2021-8-26[19-26-24]war.demo"
```

→ `0x49E600` 收到的参数是 **demo 文件路径**，不是地图名。
之前把它当作 `LoadMap(mapname)` 的分析**是错的**；它实际是 **LoadDemo(name)**。

这解释了为什么：
- `0x813E96 lea esi,[connection+0x108394]` 在 demo 播放时 0 命中（那条分支不是它）；
- 地图名从来没有出现在这个函数的参数里。

### 88.2 FileExists（0x776F00）在原始 demo 路径只命中启动

r122（原始 demo + `0x776F00:FileExists` 断点，等满 32 秒）：

```
FileExists hits = 1
stack: "patch_code_pre_gfx_mp.ff"   ← 启动基础包
```

→ **原始 demo 的地图 fastfile 请求不经过 0x776F00**；
r58 里 `patch_mp_crash_tropical.ff` 的 caller `0x776F80` 来自 **cf_dvar.demo（地图名被改）的 fallback 路径**，
不是原始 demo 的正常加载路径。

### 88.3 本轮结论

| 事实 | 状态 |
|---|---|
| `0x49E600` = LoadDemo（参数是 demo 路径） | ✅ 已证 |
| 原始 demo 地图加载**不经过** 0x49E600 / 0x484370 / 0x776F00 | ✅ 已证 |
| cf_dvar.demo 的 crash 请求是 fallback（0x776F80） | ✅ 已证 |
| 原始 demo 的地图加载入口 | ❓ 仍未定位 |

### 下一步

1. 在 `0x776F00` 入口之外，直接 hook **CreateFileA 本身**（`[0xCA8208]`）的调用者，
   抓原始 demo 播放 20 秒后所有 `.ff` 请求的返回地址；
2. 或在 LoadDemo（`0x49E600`）返回后，跟踪它如何触发地图加载（同一调用栈的后续调用）；
3. 拿到入口后，就能在服务端路径复刻"先加载地图 fastfile，再发 gamestate"。

## 89. 2026-10-25 10:10–10:30：FS_OpenFile 完全间接调用，静态扫描无果

### 89.1 扫描结果

| 目标 | 结果 |
|---|---|
| `0xC51196`（FS_OpenFile 入口）的 `call` 引用 | **0** |
| `0xC51196` 的 `push/mov/lea` 地址引用 | **0** |

→ 该函数**完全通过间接方式**（vtable / 函数指针 / 动态分配）被调用，
静态 xref 这条路走不通。

### 89.2 已有确凿证据（r120 trace）

原始 demo 播放 28 秒期间，`patch_mp_crash_tropical.ff` 的请求有两条：

```
caller 0xC513D9  (FS_OpenFile 内部，CreateFileA 返回点)
caller 0x776F80  (FileExists 内部，CreateFileA 返回点)
```

说明地图 fastfile **确实**经过 FileExists + FS_OpenFile 这两层；
但 r122 在 `0x776F00`（FileExists 入口）断点却只命中启动那次 —— 说明
**断点可能被热路径/时序绕过**（或 events 文件取错，`reuse-*` 子目录每次不同）。

### 下一步

1. 用**断点 + 栈回溯**代替静态 xref：在 `0xC513D9` 命中时读 `[ebp]` 链
   （返回地址 → 调用者 → 调用者的调用者），直接拿到"谁提供了地图名"；
2. 用 `--trace-files` 的 `caller` 字段已能确认 0xC513D9/0x776F80，问题只是
   "它们的上一级是谁"；
3. 拿到上一级后，在服务端路径复刻该调用（或直接手工调用它）。

## 90. 2026-10-25 10:30–10:50：断点与 trace 结果互相矛盾（events 文件问题）

### 90.1 r123（原始 demo + `0xC513D9:FSOpen` 断点，等满 32 秒）

```
alive = True
events = reuse-2e3cbe7b\events.jsonl  len=0  mtime=17:50:54（当前）
FSOpen hits = 1（无 crash/.ff 记录）
```

而 r120（同样原始 demo + `--trace-files`，无断点）明确记录到：

```
patch_mp_crash_tropical.ff  caller=0xC513D9
patch_mp_crash_tropical.ff  caller=0x776F80
```

→ **断点实验与 trace 结果矛盾**。可能原因：

1. `0xC513D9` 不在断点 safe list，命中被丢弃；
2. `reuse-*` 子目录的 events 写入有延迟/被截断（len=0 但能读到 1 条）；
3. 断点本身拖慢导致播放时序变化，地图加载未触发。

### 90.2 结论

- **trace（r120）是可信的**：原始 demo 播放确实请求 `patch_mp_crash_tropical.ff`，caller 0xC513D9 / 0x776F80；
- **断点路线在 `reuse-runtime` 下不可靠**（events 文件问题 + safe list 限制）；
- 应改用 **trace 的时间线**（r120 已给出请求时刻）来推断加载阶段，而不是靠断点。

### 下一步

1. 用 r120 的 trace 精确时间（1792835251.86 / 1792835252.63）对照 demo 播放时刻，
   确定 fastfile 请求发生在播放后第几秒；
2. 在该时刻前后用**轮询**读 fastfile 请求表 `0x1D06440` / `0x239B11C`（不用断点）；
3. 若能抓到表项，就能拿到"谁写入的"（表项内容 + 写入时序）。

## 91. 2026-10-25 10:50–11:10：参考文档《Fastfile校验绕过思路》的要点与结合点

### 91.1 文档要点

- IWff0100 容器：明文前缀（21 B）→ RSA PKCS#1 v1.5 密文（256 B）→ AES-192-CTR 加密头（8192 B）
  → 段表（8192 B）→ 数据块（N×8192，每块 IV = sha256(明文)）；
- 客户端校验顺序：魔数 → `hdr[0x14B]==0` → 摘要自比对 → **RSA 验签（唯一会失败的一步）** → zone 名；
- 绕过方式：**替换信任根**（自建 RSA-2048，覆盖 exe 内 270 字节 DER 公钥 + 用自建私钥重签所有 `.ff`）；
- 工程注意：**不要原地写**（.ff 常是硬链接，会污染源目录）、签名只做在每局临时目录、
  公钥补丁要幂等、每局重建 exe 时要重打公钥。

### 91.2 与当前卡点的关系

| 问题 | 是否相关 |
|---|---|
| 181 武器索引错误（本地 1136 vs demo 1224） | **不是验签问题**（当前 fastfile 是原版，验签本来通过） |
| 想修改 fastfile 注入武器定义/换地图 | **需要**这份方案（改内容必须重签） |
| 地图加载不走服务端路径 | 与本方案无关（是加载触发问题，不是校验问题） |

### 91.3 可选的下一步（用这份方案做什么）

如果"补齐 122 个武器定义"走**改 fastfile** 的路线：

1. 用 `1649370/src/codol_rebuild/resources/fastfile.py` 解码 `mp_crash_tropical.ff`；
2. 定位武器定义区（zone 目录中的 weapon asset），把 demo 多出的 122 个定义写进去；
3. 用参考文档的"替换信任根"方案重签该 .ff（需自建密钥 + 覆盖 exe 公钥）；
4. 在服务端路径加载这个改过的 .ff。

风险：工作量大、需要动客户端 exe 公钥；但这是**不依赖 demo 回放**的唯一"资源层修复"路径。

### 91.4 本轮结论

参考文档已归档并纳入方案库；当前主线仍是"让服务端路径触发 fastfile 加载"
（§88–§90），该方案作为**备选路线**记录。

## 92. 2026-10-25 11:10–11:30：Fastfile 解码器接口确认；当前 exe 的 RSA 指纹与 const.ff 不匹配

### 92.1 解码工具位置与接口

- 工具在 `E:\GAME\COD\1649370\src\codol_rebuild\resources\fastfile.py`（**不在 319 项目目录下**）；
- `inspect_fastfile(path) -> dict`：可用，实测 `mp_crash_tropical_const.ff`：

```
magic  IWff0100
version 461
signed True
body_size 90112
body_blocks 11
sha256 f7f138eb...
```

- `decode_fastfile(path, client_exe, output=None, *, max_zone_size=...) -> dict`：需要 **client_exe**
  参数（用来取 RSA 公钥指纹）。

### 92.2 解码失败原因

```
FastfileError: rsa_material 客户端版本的 RSA 公钥指纹不匹配
```

→ 当前 `bin\v1649370\codol1649370-offline.exe` 的公钥指纹与
`mp_crash_tropical_const.ff`（461 签名）**不匹配**。可能原因：

1. 该 exe 是**离线壳**（启动链打过补丁，公钥被替换过）；
2. ff 来自**另一个构建**（461 但不同 build 的签名密钥）；
3. `_load_keys` 读取的指纹位置随版本变化。

### 下一步

1. 找**未打补丁的原始 exe**（`E:\GAME\COD\Original Client` 下）再试 `decode_fastfile`；
2. 若仍不匹配，用 `inspect_fastfile` 的结构信息 + 手工解析（参考《Fastfile校验绕过思路》的
   IWff0100 布局：明文前缀 → RSA 密文 → AES 头 → 段表 → 数据块）；
3. 解码成功后，定位 zone 目录中的 weapon 资产，评估"注入 122 个武器定义"的可行性
   （备选路线 §91）。

## 93. 2026-10-25 11:30–12:00：**重大突破 —— Fastfile 解码全线打通，武器定义在 common_mp.ff**

### 93.1 解码器可用（原始 exe 是关键）

`decode_fastfile(path, client_exe)` 需要**原始客户端 exe**：

```
E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe   ✅ 指纹匹配（461）
E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe  ❌ 指纹不匹配（离线壳补丁过）
```

### 93.2 三个 ff 的解码结果

| 文件 | 大小 | asset_count | 备注 |
|---|---|---|---|
| `mp_crash_tropical_const.ff` | 90 KB | **17** | 全校验通过 |
| `mp_crash_tropical.ff` | 32 MB | **381** | 全校验通过；**不含武器定义**（只有 3 个 weapon 字符串，且是 tag_weapon） |
| **`common_mp.ff`** | 77 MB | **8557** | 全校验通过；**1723 个 weapon 字符串** |

`common_mp.ff` 的类型分布：

```
2:1845  4:170  5:395  9:209  10:39  11:3348  25:43  28:1134  30:798
31:1    36:250 37:25  40:3   43:285 44:12
```

weapon 字符串样例：

```
weapon/bowss/fx_wea_bowss_bj
weapon/csg12/fx_csg12_singularity
weapon/freeze_gun/fx_freezegun_body_shatter
mp_weapon_usa_sticky_grenade_lod0
```

→ **武器定义（含复合武器字符串）在 `common_mp.ff`**，不在 `mp_crash_tropical.ff`。

### 93.3 为什么这解释 181

- demo 播放会加载 `common_mp.ff`（启动基础包），注册 1266 个武器定义；
- 服务端路径只发 gamestate（291 条 configstring），**没有加载 `common_mp.ff` 的武器表**，
  所以只到 1136；
- 之前"122 差距来自 fastfile"的推断方向正确，现在**具体到 common_mp.ff**。

### 下一步

1. 从 `runs/ff-decoded/common`（77 MB zone 数据）里提取**武器定义表**（1723 个字符串的完整列表）；
2. 对照 demo 的 1224 个定义，找出服务端路径缺的 88 个；
3. 用 `build_native_gamestate` 把这些武器 configstring 补进 gamestate（或直接构造
   `d <idx> <weapon>` 命令序列下发）。

## 94. 2026-10-25 12:00–12:30：common_mp.ff 的武器字符串统计与 asset 名定位受阻

### 94.1 weapon 字符串统计

从 `runs/ff-decoded/common`（77 MB zone 数据）提取：

```
unique 'weapon/...' + 'mp_weapon*' 字符串 = 228
  weapon/... 前缀 = 219（多为 fx 特效，如 weapon/bowss/fx_wea_bowss_bj）
  mp_weapon_* = 9（武器名，如 mp_weapon_usa_sticky_grenade_lod0）
```

而总 "weapon" 出现 1723 次（含非独立字符串）。

### 94.2 asset 名不在数据开头

尝试对每个 asset 取数据开头的可打印串作为名字：

```
weapon-like asset names = 0
```

→ 只有 type 30 的 props 类资产在开头内联名字（`props/copypaper_...`），
武器类资产（type 11 的 3348 个）**不在开头内联名字**。

### 94.3 结论

- 武器定义（1224 个）在 `common_mp.ff` 里，但名字存储位置**还没定位**；
- 可能在 zone 的 string table（`string_count` 为 0，说明该 zone 没有独立 string table），
  或在 asset 结构内部的其它偏移。

### 下一步

1. 读 `codol_rebuild/resources/fastfile.py` 的 `zone` 解析实现，看它是否解析 asset 名；
2. 或对比 demo 播放时 `0x1988B50` 表里的字符串（运行时快照），直接拿到 1224 个名字，
   不必从 ff 里逆推；
3. 拿到 1224 个名字后，与 `common_mp.ff` 的 1723 个 weapon 字符串做差集，补进 gamestate。

## 95. 2026-10-25 12:30–13:00：**导出 demo 路径的完整 1266 个武器定义名**

### 95.1 表结构修正（双重指针）

`0x42F2F0` 的表项是**指针的指针**：

```asm
0x42F32E  mov edx, [esi*4 + 0x1988B50]   ; 表项 = char**
0x42F335  mov edx, [edx]                 ; 再解引用 → char*
0x42F33D  call 0x7745E0                  ; strcmp
```

第一次 dump 忘了第二层解引用（拿到乱码），修正后：

```
count = 1266
names = 1266
sample: ["defaultweapon_mp", "aa12_mp", "aa12anniversarya_mp",
         "aa12anniversaryb_mp", "aa12battlepass_mp", "aa12btf_mp"]
```

→ **demo 播放路径注册的 1266 个武器定义名全部拿到**（`runs\r126-weapon-table.json`）。

### 95.2 新工具

`tools/dump_weapon_table.py`：读 `0x827F738`（表大小）+ `0x1988B50`（双重指针表），
输出 JSON（count/names/entries）。

### 下一步

1. 用同样方法在**服务端路径**（connect + gamestate）在表重建到 1136、弹 181 **之前** dump，
   得到服务端路径的武器名列表；
2. 两份列表做差集：`1266 - 1136 ≈ 130`，即"服务端 gamestate 缺的武器名"；
3. 把这些名字补进 gamestate 的 configstring（或构造 `d <idx> <name>` 命令），使表达到 1266+。

## 96. 2026-10-25 13:00–13:30：服务端路径表导出时机未抓到（表 36 秒仍未到 1100）

### 96.1 工具状态

`tools/dump_weapon_table.py`（双重指针修正版）已可用，能导出 demo 路径的 1266 个名字
（`runs\r126-weapon-table.json`）。

### 96.2 服务端路径尝试

- r127：run_match 启动后立即轮询 → `client gone at 1s`（和 run_match 的 kill_stale 冲突）；
- r128：等 24 秒后轮询 40 次（约 12 秒）→ 表**始终 < 1100**，客户端存活但未到重建完成阶段。

→ 服务端路径的"表重建到 1136"窗口**比预期晚**（run_match 的 login 18s + connect 等步骤），
需要更长的轮询窗口（或直接等 run_match 输出 state 8 后再抓）。

### 下一步

1. 延长轮询到 60 秒，并记录表值随时间的变化（找 1136 的确切时刻）；
2. 或用 run_match 的 `--client-breakpoint` 不可靠，改在 gs 日志出现 `gamestate_source`
   后立即 dump（gs 日志可实时读）；
3. 若仍抓不到，改用"demo 路径 1266 个名字 vs common_mp.ff 的 1723 个 weapon 字符串"
   的离线差集（不依赖运行时快照）。

## 97. 2026-10-25 13:30–14:00：**130 个缺失武器清单确定（全是连杀奖励/空中支援）**

### 97.1 两份运行时快照

| 路径 | 表大小 | 文件 |
|---|---|---|
| demo 播放 | **1266** | `runs\r126-weapon-table.json` |
| 服务端 gamestate | **1136** | `runs\r130-weapon-table.json` |

抓取方法：读 `0x827F738`（表大小），命中 `gamestate_source` 后**连续采样**；
服务端路径在第 2 次采样（约 0.25–0.5 s）时表从 0 涨到 1136，窗口抓住。

### 97.2 差集

```
demo path   1266
server path 1136
missing (in demo, not server) = 130
extra   (in server, not demo) = 0
```

**缺失的 130 个全是连杀奖励 / 空中支援类武器**：

```
ac130_105mm_mp, ac130_105mm_pro_mp, ac130_25mm_mp, ac130_25mm_pro_mp,
ac130_40mm_mp, ac130_40mm_pro_mp, ac130_mp,
airdrop_marker_mp, airdrop_mega_marker_mp, airdrop_sam_marker_mp,
airdrop_sentry_marker_mp, airstrike_mp, artillery_mp, auto_tow_mp,
briefcase_bomb_defuse_mp, ...
```

清单存于 `runs\weapon-diff.json`。

### 97.3 结论与下一步

- **根因确认**：服务端 gamestate 未覆盖 `common_gametype_mp.ff`（或 `ui_mp.ff`）里的
  连杀奖励武器定义，导致表少 130 个，索引 1224 处对不上 → **181 错误**；
- **修复方向**：把这 130 个名字补进 gamestate 的 configstring（或构造 `d <idx> <name>` 命令），
  让服务端路径的表达到 1266；
- 下一步先验证这 130 个名字确实来自 `common_gametype_mp.ff`（解码该包搜索），
  再决定用"补 configstring"还是"触发加载 common_gametype_mp.ff"。

## 98. 2026-10-25 14:00–14:30：**根因锁定 —— 88 = common_gametype_mp.ff 武器，42 = 动态复合**

### 98.1 130 个缺失的构成

| 来源 | 数量 | 说明 |
|---|---|---|
| `common_gametype_mp.ff`（1400 asset） | **88** | 连杀奖励/空中支援武器（`ac130_*`、`airdrop_*`、`airstrike_mp`、`artillery_mp`、`auto_tow_mp`、`briefcase_bomb_defuse_mp` …） |
| 运行时动态复合（`** <idx> 0 0 <components>`） | **42** | 不在任何 ff 里，由 `0x431810` 在 demo 播放时动态合成 |

样例（动态复合）：

```
** 249 0 0
** 682 0 0 9930 8738 6747 10545 9321 6690 6825
** 320 0 0 6747 8738 9321 6825
...
```

### 98.2 数字对上

```
服务端路径表 = 1136
+ gametype 武器 88
= 1224  ← demo 数据要求的索引（181 错误里的 1224）
```

→ **181 的直接原因就是缺这 88 个 gametype 武器**，与 HANDOFF 的"差 88 个"完全一致。
42 个动态复合武器是 demo 播放时现场生成的，属于"正常增量"，不是缺失。

### 98.3 修复方向（明确）

1. **让服务端路径加载 `common_gametype_mp.ff`**（等价于 demo 播放时的 gametype 包加载）；
2. 或把 88 个武器名以 configstring 形式补进 gamestate（`build_native_gamestate` 的
   configstrings 参数，或直接构造 `d <idx> <name>` 命令序列）；
3. 验证：表到 1224+ 后，`0x59B560` 的 1224 比较应通过，181 消失。

### 98.4 产物

- `runs/weapon-diff.json`（130 个缺失）
- `runs/weapon-diff-sources.json`（88 in gametype / 42 nowhere）
- `runs/ff-decoded/gametype`（1400 asset 的 zone 数据）

## 99. 2026-10-25 14:30–15:00：0x49E160 参数确认（第三参数是模式），调用点反汇编待重定位

### 99.1 0x49E160 入口

```asm
0x49E160  push ebp / mov ebp,esp / and esp,-8 / sub esp,0x1C
0x49E169  push ebx/esi/edi
0x49E16C  call [0xCA8164]
0x49E172  cmp eax, [0x7886E6C]
0x49E178  je 0x49E184
0x49E17A  call 0xBEAA80
0x49E17F  call 0xC04BD0
0x49E184  call 0x49E130
0x49E189  cmp dword ptr [ebp+0x10], 2     ; ← 第三参数是"模式"
0x49E18D  jne 0x49E1A0
0x49E18F  mov dword ptr [0x82C488C], 1
0x49E199  mov dword ptr [ebp+0x10], 0
```

→ `[ebp+0x10]`（第三个参数）= **模式**（2 = 特殊模式，会置 `0x82C488C=1`）。

### 99.2 调用点定位受阻

之前记录的调用者 `0x4FE76C` 反汇编（0x4FE730 起）无输出/不符，
说明 0x49E160 的调用者列表或入口边界需要重新确认。

### 下一步

直接用 `call_fn` 调用 `0x49E160`：
1. `VirtualAllocEx` 一块内存，写入 `"common_gametype_mp"` 字符串 + 数组
   （`{char* name, u32 flags}` 每项 8 字节，count=1）；
2. 调 `0x49E160(list_ptr, 1, 0)`（第三参数 0 = 普通模式）；
3. 观察 `0x827F738`（表大小）是否从 1136 涨到 1224+。

风险：该函数内部有 `[0x7886E6C]` 比较与 `0xBEAA80/0xC04BD0` 调用，可能需要合法上下文；
先用 `call_fn` 试一次，失败则改在 connect 后（state 5）调用。

## 100. 2026-10-25 15:00–15:30：load_fastfile 工具就绪；首次调用成功但表未变（时机过早）

### 100.1 工具

`tools/load_fastfile.py <name>`：

1. `VirtualAllocEx` 分配 0x1000；
2. 写名字字符串 + 列表项（`{u32 header[2]; char* name; u32 flags; u32 pad}`，每项 0xC）；
3. 主线程调用 `0x49E160(list, 1, 0)`。

### 100.2 首次调用（启动后、未登录）

```
status = null（调用完成）
returned_eip = 0x77D9826C
alive = true
table_before = 0
table_after  = 0
```

→ 调用**成功返回**（没有崩），但 `0x827F738` 仍是 0 —— 因为**表在 login 之前根本没初始化**
（此前 r113 也测到启动后表为 0）。

### 100.3 第二次尝试

在已启动的客户端上先 login 再 `load_fastfile`：客户端在 login 流程中已退出（`client gone`），
本轮没有拿到"login 后表=1135 再加载"的数据。

### 下一步

1. 重跑：launch → login（到 ui=5/表=1135）→ **立即** `load_fastfile common_gametype_mp` → 读表；
2. 若表从 1135 涨到 1223+，则 88 个 gametype 武器的来源确认，181 应消失；
3. 若表不变，检查列表结构（`add [ebp+8], 8` 的 header 布局可能不同）或改调
   `0x49E3B6` 附近的内部函数。

## 101. 2026-10-25 15:30–16:00：load_fastfile 在表未初始化时调用会崩（timeout + 退出）

### 101.1 r132（手动流程：launch + login(5s) + load_fastfile）

```
after login: table = 0     state = 1
load_fastfile: status=null  returned_eip="timeout"  state=0  alive=false
```

→ 两个发现：

1. **手动 login 5 秒后表仍是 0**（而 r114 的 run_match 流程 login 18s 后表是 1135）——
   说明表初始化发生在 login 流程的更后段（run_match 的 ring-a-drain + refresh hook 之后）；
2. 在表为 0 时调 `0x49E160` → **timeout + 客户端退出**，说明该函数依赖
   `[0x7886E6C]` 等全局已初始化。

### 101.2 结论

`load_fastfile` 必须在"表已到 1135"之后调用，否则崩溃。

### 下一步

1. 用 `run_match` 跑（它能让表到 1135），在 `gamestate_source` 日志出现时
   并行调用 `load_fastfile common_gametype_mp`；
2. 或把手动流程补上 run_match 的 ring-a-drain + refresh hook 两步，等表到 1135 再调用；
3. 成功判据：表从 1135 涨到 1223+，且 `0x59B560` 的 1224 比较通过（181 消失）。

## 102. 2026-10-25 16:00–16:30：load_fastfile 在 gamestate 处理窗口调用仍崩（时机不对）

### 102.1 r133（run_match + 并行 load_fastfile）

```
gamestate_source at 18:06:03
table_now   = 0        ← gs 日志出现时表还没重建
load_fastfile → returned_eip="timeout"、state=0、alive=false
```

→ 在 `gamestate_source` 日志出现时调用仍然崩。原因：gs 日志是**发送前**记录，
此时客户端还没开始处理 gamestate（表为 0），而 `0x49E160` 依赖表已初始化。

### 102.2 正确的调用时机

已知表初始化的两个状态点：

| 阶段 | 表大小 |
|---|---|
| 启动后（未登录） | 0 |
| login 完成（run_match 的 18s + ring-drain + hook 之后） | **1135** |
| gamestate 处理中 | 0 → 676 → 1136（重建） |

→ `load_fastfile` 必须插在 **"login 完成、connect 之前"** 的窗口（表=1135 且客户端空闲）。

### 下一步

1. 监控 `runs/<name>-run.out` 的 `[run_match] driving login state machine` 之后、
   `[run_match] blocking ring-a` 之前，此时调 `load_fastfile common_gametype_mp`；
2. 若成功，表应从 1135 涨到 1223+，再让 run_match 继续 connect + gamestate，
   观察 181 是否消失；
3. 若该窗口仍崩，改在 demo 播放路径做对照（demo 播放到 state 10 后、地图加载前调用）。

## 103. 2026-10-25 16:30–17:00：**load_fastfile 在正确窗口（表=1135）仍 timeout —— 手工调用 0x49E160 不可行**

### 103.1 r134（精确卡窗口）

监控 `runs/r134-run.out` 的 `[run_match] blocking ring-a` 里程碑（login 完成、connect 前）：

```
milestone 'blocking ring-a' at 18:07:39
table_now = 0x46F = 1135        ← 时机正确
load_fastfile common_gametype_mp →
  status=null, returned_eip="timeout", state=0, alive=false（客户端退出）
```

→ **即使表已到 1135、客户端空闲，`0x49E160` 仍 timeout**。

### 103.2 结论

`0x49E160`（Com_LoadFastfiles）**不能被 `invoke_sequence` 的 cave 手工调用**：
它内部有 `[0x7886E6C]` 比较、`0xBEAA80` / `0xC04BD0` 调用，且可能要求
"游戏主循环的合法调用栈/全局状态"，cave 环境不满足 → 挂起。

**放弃"手工加载 fastfile"路线。**

### 103.3 转向：补 configstring（可行方向）

- 武器表 `0x1988B50` 由 `0x431810`（创建复合武器）填充；
- `0x431810` 的输入是 **`** <idx> 0 0 <components>` 形式的字符串**；
- 这 42 个复合字符串 + 88 个 gametype 武器名，可以作为 **configstring** 补进 gamestate；
- `build_native_gamestate(configstrings=...)` 支持自定义 configstring 列表。

### 下一步

1. 从 demo 的 1266 个武器名里取出 88 个 gametype 武器名 + 42 个复合字符串；
2. 用 `build_native_gamestate` 构造含这些 configstring 的 gamestate（索引 7184 起）；
3. 下发后观察表是否从 1136 涨到 1224+，181 是否消失。

## 104. 2026-10-25 17:00–17:30：补 configstring 只能补 42 个复合，88 个 asset 仍需 fastfile

### 104.1 构造器接口

```python
build_native_gamestate(registration_checksum, *,
    checksum_feed=23368560, client_number=0, configstrings=None,
    mapname=b'mp_cross_fire', gametype=b'mp') -> bytes
```

`DEFAULT_CONFIGSTRINGS` 只有 3 条（configstring 0/1/2），而 `--gamestate-source file`
用的是 `gamestate-network-ffb56d7e-6411.bin` 里的 291 条。

### 104.2 关键区分

| 缺失项 | 本质 | 能否用 configstring 补 |
|---|---|---|
| 42 个 `** <idx> 0 0 ...` 复合字符串 | **configstring 值**（`0x431810` 的输入） | ✅ 可以 |
| 88 个 `ac130_mp` 等 gametype 武器名 | **fastfile asset**（`0x1988B50` 表项） | ❌ 不行（表是 asset 注册的） |

→ 补 configstring 最多让表 +42（1136 → 1178），**到不了 1224**；
88 个 asset 必须通过加载 `common_gametype_mp.ff` 才能注册。

### 104.3 结论

- 手工调用 `0x49E160` 不可行（§103）；
- 补 configstring 只能补 42 个；
- **要消除 181，必须找到"客户端自己触发 gametype fastfile 加载"的路径**。

### 下一步

1. 回到 demo 播放：观察 demo 播放时 `common_gametype_mp.ff` 是**何时、由谁**加载的
   （r58/r120 trace 里有 `patch_mp_crash_tropical.ff`，但没看到 gametype 包）；
2. 若 demo 也没加载 gametype 包，则 88 个武器可能来自 `common_mp.ff`（启动已加载）的
   另一种注册方式（如 zone 内的 asset 引用）；
3. 重新检查 `0x42F2F0` 表的填充路径，确认 88 个是否真的来自 asset 注册。

## 105. 2026-10-25 17:30–18:00：**demo 播放请求 patch_common_gametype_mp.ff；服务端路径没有 → 88 差异根源**

### 105.1 demo 播放的 fastfile 请求统计（r120 trace）

```
ff requests = 14016
其中：
  m4a1techcommon_mp.ff  1676
  m21ebr_mp.ff          976
  aks74u_mp.ff          906
  ...（每把武器一个独立 ff，共 40+ 种）
  patch_common_gametype_mp.ff            4 次   ← gametype 的 patch 包
  patch_localized_common_gametype_mp.ff  4 次
```

### 105.2 武器独立 ff 全部缺失（但不影响播放）

全盘搜索 `ac130*_mp.ff` / `airstrike*_mp.ff`：**0 个**；
`Original Client\client_shipRetail\chinese` 下 `*_mp.ff`：**0 个**；
overlay：**12 个**（基础包）。

→ demo 播放请求的 14,016 个武器 ff 全部是"缺失回退"，**不影响 demo 播放**
（demo 的帧数据只需要 asset 名，不需要实际实现）。

### 105.3 关键差异

| 路径 | 请求 `patch_common_gametype_mp.ff` | 结果 |
|---|---|---|
| demo 播放 | ✅ 4 次 | 回退加载 `common_gametype_mp.ff` → 表 1266 |
| 服务端路径 | ❌ 没有 | 表 1136（少 88 个 gametype 武器） |

### 结论

88 个 gametype 武器来自 `common_gametype_mp.ff`，而 demo 播放**主动请求**了它的 patch 包
（`patch_common_gametype_mp.ff`），触发加载；服务端路径**没有触发**这次请求。

### 下一步

1. 找出 demo 播放时"谁发起 `patch_common_gametype_mp.ff` 请求"（在 trace 里看它的 caller
   与时间点，对照 demo 播放阶段）；
2. 在服务端路径复刻该触发（例如向客户端注入对应 configstring/命令）；
3. 或直接把 `common_gametype_mp.ff` 放进 overlay 并让它被启动加载（启动列表加一项）。

## 106. 2026-10-25 18:00–18:30：gametype 包与地图包同一时刻请求（同一批加载）

### 106.1 trace 时间对齐

`runs/r107flow/reuse-074c6159/events.jsonl`：

```
patch_common_gametype_mp.ff        caller 0xC513D9  time 1792835251.8613465
patch_common_gametype_mp.ff        caller 0x776F80  time 1792835251.9109170
patch_mp_crash_tropical.ff         caller 0xC513D9  time 1792835251.8626547
patch_mp_crash_tropical.ff         caller 0x776F80  time 1792835252.6339579
```

→ **gametype 包与地图包在同一批请求**（相差 1 毫秒），说明它们由**同一次批量加载**
（`0x49E160` 或等价路径）触发，列表里同时包含 `patch_mp_crash_tropical` 与
`patch_common_gametype_mp`。

### 106.2 服务端路径少加载 gametype

- 服务端路径（r105 trace）确实请求了 `patch_mp_crash_tropical.ff`（地图包被 gamestate 的 mapname 触发）；
- 但**没有** `patch_common_gametype_mp.ff`（gametype 字段 `war` 不足以触发该包）。

→ 服务端路径的批量加载列表**缺 gametype 项**，所以表少 88 个武器。

### 106.3 修复思路（最直接）

在地图加载的批量列表里**加入 gametype 项**：
1. 找到服务端路径触发地图加载的入口（gamestate 的 mapname → 某个加载函数）；
2. 该函数构造的列表若可被拦截/扩展，加入 `patch_common_gametype_mp`；
3. 或在 gamestate 里增加触发 gametype 包的字段（对比 demo 的 gamestate 与我们的差异）。

### 下一步

1. 对比 demo 的 gamestate（6407）与我们下发的（6411）字段差异（尤其 gametype 相关）；
2. 找客户端"根据 gamestate 构造 fastfile 列表"的代码，确认它为什么不加 gametype。

## 107. 2026-10-25 18:30–19:00：gamestate 只差 4 字节；demo 与 gamestate 都不含 gametype 加载信息

### 107.1 gamestate 对比（demo vs 下发）

```
demo len 6407, network len(no ack) 6407
diff count = 4
diffs = [(27, 0x00, 0x7e), (28, 0x00, 0x6d), (29, 0x00, 0xb5), (30, 0x00, 0xff)]
```

→ 两份 gamestate **只差 offset 27–30**（registration_checksum：demo 为 0，网络为 0xFFB56D7E）。
除此之外**完全相同**。

**结论：gamestate 不是"少加载 gametype 包"的原因。**

### 107.2 demo 文件里没有 gametype 字符串

在 7.2 MB 的 demo 里搜索：

```
b'common_gametype'        0 次
b'patch_common_gametype'  0 次
b'gametype'               0 次
```

→ demo 播放时虽然请求了 `patch_common_gametype_mp.ff`，但**名字不是从 demo 文件读的**，
而是**运行时拼接/代码里配置的**。

### 107.3 结论

加载列表（含 gametype 项）来自**代码路径**，不是 demo 数据、也不是 gamestate。
下一步要找"demo 播放时构造该列表的代码"，并让服务端路径复用。

### 下一步

1. 在 `0x49E160` 的 16 个调用者里，找 demo 播放会走的那一个（可用 trace 的 caller 或时序推断）；
2. 看它如何决定列表内容（是否包含 gametype / 是否读配置）；
3. 服务端路径若能复用同一构造逻辑，就能补上 gametype 包。

## 108. 2026-10-25 19:00–19:30：0x49E160 的 16 个调用者；CL_PlayDemo 内是空列表调用

### 108.1 调用者清单

```
0x49E67B  0x49EC93
0x4FCC7C  0x4FCD32  0x4FCE4F      ← 启动加载（code_pre_gfx 等）
0x4FE76C  0x4FE951                ← CL_Init 区域
0x515ED5
0x59B212
0x5BFBF9  0x5BFCBB
0x5C2C23  0x5C8448
0x5CB441  0x5CB451
0x813D09                          ← CL_PlayDemo 内部
```

### 108.2 CL_PlayDemo 内是一个空列表调用

```asm
0x813CF3  xor eax, eax
0x813CF5  push eax
0x813CF6  lea edx, [ebp-0x10]
0x813CF9  push 1
0x813CFB  push edx
0x813CFC  mov [ebp-0x10], eax
0x813CFF  mov [ebp-0xC], eax
0x813D02  mov [ebp-8], 6
0x813D09  call 0x49E160          ; 列表为空（[ebp-0x10]=0）
0x813D11  call 0x5C8A70          ; CL_Shutdown
0x813D25  call 0x5C83D0          ; CL_Init
0x813D34  mov [0x76446B0], 7     ; state = 7
```

→ CL_PlayDemo 里的 `0x49E160` 是**空列表**调用（只是初始化/清场），
**不是**加载 gametype 包的地方。

### 108.3 结论

gametype 包（`patch_common_gametype_mp.ff`）的加载在**另一个调用者**里，
可能在 `0x5C8448`（CL_Init 后）或 `0x5C2C23`（CL 层）附近。

### 下一步

1. 反汇编 `0x5C8448` / `0x5C2C23` / `0x5CB441` 三个调用点的上下文，找"含 gametype 名字的列表构造"；
2. 重点看它们的列表内容从哪个全局/配置读（是否与 demo 播放模式相关）；
3. 找到后在服务端路径复刻。

## 109. 2026-10-25 19:30–20:00：三个候选调用点都是空列表 —— gametype 加载不走 0x49E160

### 109.1 反汇编结果

| 调用点 | 列表内容 | 第三参数 |
|---|---|---|
| `0x5C2C23` | `[ebp-0xC]=0`、`[ebp-8]=0`、`[ebp-4]=0x18` | 0x18 |
| `0x5C8448` | `[ebp-0x70]=edi`（0 或空） | ebx |
| `0x5CB441` / `0x5CB451` | `[ebp-0xC]=0`、`[ebp-8]=0`、`[ebp-4]=0x20` | 0x20 |

→ 三个候选都是**空列表调用**（清场/初始化），不是"含 gametype 名字的列表"。

### 109.2 结论

`patch_common_gametype_mp.ff` 的加载**不经过 `0x49E160` 的这 16 个调用者**，
也不经过 `0x49E600`（LoadDemo）——它在**另一个加载函数**里。

### 下一步

1. 从 trace 的 caller（`0xC513D9` / `0x776F80`）反向找"谁调用了 FS_OpenFile 并传了
   `patch_common_gametype_mp.ff`"——之前静态 xref 失败（完全间接），改用**动态栈回溯**；
2. 或在 `0x776F00`（FileExists）入口断点，命中时读 `[ebp+8]`（文件名）与 `[ebp]`（返回地址链），
   直接拿到调用者；
3. 找到后看它从哪个全局/配置决定名字，再在服务端路径复刻。

## 110. 2026-10-25 20:00–20:30：**找到 gametype → 包名的分派表（0x49E8E0）与注册函数（0x49E540）**

### 110.1 包名表（.rdata 0xDB5F58–0xDB6578）

```
ui_mp / patch_ui_mp / patch_localized_ui_mp / localized_ui_mp
common_gametype_zm
common_gametype_survival
common_gametype_coop
common_gametype_zombie_arena
common_gametype_dmz
common_gametype_zombie_hunter
common_gametype_zhunt_humanoid
common_gametype_zhunt_zombie
common_gametype_zombie_survival
common_gametype_zombie_champions
common_gametype_td
common_gametype_mp            ← 0xDB60C8
common_gametype_hostage
common_gametype_asym
...
common_mp / patch_common_mp / patch_localized_common_mp / localized_common_mp
common_mp_reload
common_gametype_clash / common_gametype_spy
```

`common_gametype_mp` 在**整个 exe 里只有 1 处代码引用**。

### 110.2 引用点：0x49E8E0 的分派函数

```asm
0x49E8E9  mov eax, 6 / mov edx, 0xDCE314     ; 比较 gametype 名字（长度 6）
0x49E8F3  call 0x7745E0                      ; strncmp
0x49E914  mov ecx, 0xDB6090                  ; "common_gametype_zombie_champions"
0x49E919  jmp 0x49EA70

0x49E924  mov edx, 0xDD9D70                  ; 另一个 gametype 名
0x49E951  mov ecx, 0xDB60B4                  ; "common_gametype_td"
0x49E956  jmp 0x49EA77

0x49E977  lea eax, [ebp-0xE14]
0x49E97D  mov ecx, 0xDB60C8                  ; "common_gametype_mp"   ← 默认分支
0x49E982  call 0x49E540                      ; 注册该包

0x49E9C0  mov ecx, 0xDB60DC                  ; "common_gametype_hostage"
0x49E9C5  call 0x49E540

0x49E9F8  mov ecx, 0xDB60F4                  ; "common_gametype_asym"
```

→ `0x49E540` 是"注册/加载 gametype 包"的函数，按 gametype 名分派到具体包名。

### 110.3 意义

- 服务端路径缺 88 个武器，正是因为**没有走到 `0x49E540` 这条注册路径**；
- 若能让客户端执行 `0x49E540("common_gametype_mp", ...)`（或让它被游戏主循环调用），
  就能补上这 88 个注册。

### 下一步

1. 反汇编 `0x49E540`，确认参数（是否只吃一个包名 + 若干缓冲区指针）；
2. 看它是否可直接用 `call_fn` 调用（比 `0x49E160` 轻量）；
3. 若可行，在服务端路径的 login 完成后调用 `0x49E540`，验证表是否 +88。

## 111. 2026-10-25 20:30–21:00：**gametype 包加载发生在 LoadDemo（0x49E600）内部**

### 111.1 函数入口列表（0x49E000–0x49E8E0）

```
0x49E070  0x49E130  0x49E160(批量加载)  0x49E410  0x49E540(列表构造)  0x49E600(LoadDemo)
```

→ 含 `0x49EC93 call 0x49E160` 的那个大函数（0x49E8E0–0x49ECAB），入口就是 **0x49E600**。

### 111.2 LoadDemo 内部的完整流程

```asm
0x49E600  LoadDemo 入口
  ...
0x49E8E9  mov eax,6 / mov edx,0xDCE314      ; 比较 gametype 名
0x49E8F3  call 0x7745E0                     ; strncmp
0x49E914  mov ecx,0xDB6090                  ; zombie_champions
...
0x49E97D  mov ecx,0xDB60C8                  ; common_gametype_mp（默认）
0x49E982  call 0x49E540                     ; 构造 4 项列表（patch_/localized_/patch_localized_）
...
0x49EAA6  call 0xC3EB40                     ; 其它检查
0x49EAC5  call 0x774900                     ; sprintf → patch_%s
0x49EB0A  call 0x774900                     ; sprintf → %s_const
0x49EB59  call 0x775F50
...
0x49EC93  call 0x49E160                     ; ← 批量加载（含 gametype 包）
0x49ECA8  pop ebp / ret
```

→ **LoadDemo 在加载 demo 的同时，会按 gametype 名构造并加载**
`common_gametype_mp`（及其 patch/localized 变体）。

### 111.3 这解释了全部现象

| 事实 | 解释 |
|---|---|
| demo 播放请求 `patch_common_gametype_mp.ff` | LoadDemo 内部的 0x49E160 加载列表里有 |
| demo 播放表 1266 | gametype 包的 88 个武器被注册 |
| 服务端路径表 1136 | 没有 LoadDemo，从未加载 gametype 包 |
| demo 与 gamestate 内容几乎相同 | 差异不在数据，在**加载路径** |

### 下一步

1. LoadDemo（0x49E600）需要 demo 文件参数，不能直接调；
2. 但它的前段（0x49E8E0–0x49ECAB）**只依赖 gametype 名与栈缓冲**，可尝试：
   - 用 `call_fn` 直接跳到 `0x49E8E0` 附近的"gametype 分派"起点（需要合法 ebp/栈帧，风险高）；
   - 或写一个小 cave 脚本：手动构造列表（`0x49E540` 的格式）后直接调 `0x49E160`。
3. 推荐后者：列表格式已知（每项 `{char* name; u32 flags=4; u32 0}`，4 项分别是
   `patch_<name>`、`<name>`、`patch_localized_<name>`、`localized_<name>`）。

## 112. 2026-10-25 21:00–21:30：正确格式的 4 项列表仍 timeout —— 0x49E160 的 cave 调用不可行

### 112.1 工具

`tools/load_gametype.py`：按 `0x49E540` 的布局构造 4 项列表（`{u32 count=4;
{char*;u32 4;u32 0}×4}`，名字分别是 `patch_<name>` / `<name>` /
`patch_localized_<name>` / `localized_<name>`），然后调 `0x49E160(list, 4, 0)`。

### 112.2 结果（表=1135 的窗口）

```
table_now = 0x46F = 1135
names = [patch_common_gametype_mp, common_gametype_mp,
         patch_localized_common_gametype_mp, localized_common_gametype_mp]
status = null
returned_eip = "timeout"
客户端退出（alive=false）
```

→ **列表格式正确也没用**：`0x49E160` 在当前 `invoke_sequence` 的 cave 机制下
无法完成（内部 `call [0xCA8164]`、`cmp [0x7886E6C]`、`call 0xBEAA80/0xC04BD0`
依赖游戏主循环/线程上下文）。

### 112.3 结论

- cave 方式（挂起窗口线程 + 跳板）**不适配** `0x49E160` 这类重初始化函数；
- 已两次验证（空列表、正确 4 项列表）→ **放弃 cave 调用 0x49E160**。

### 下一步

1. 改用**注入远线程**（`CreateRemoteThread` 直接以 `0x49E160` 为入口，参数通过栈/寄存器传入），
   让它在自然线程里执行；
2. 或改用"**hook 游戏主循环的某个点**"，让游戏自己在正常上下文里调 `0x49E160`；
3. 或退回"补 configstring"方案（只能补 42 个复合，已知到不了 1224）。

## 113. 2026-10-25 21:30–22:00：远线程调用 0x49E160 也崩 —— 它必须跑在主线程

### 113.1 工具

`tools/load_gametype_thread.py`：写入 shellcode
（`push mode; push 4; push list; call 0x49E160; xor eax,eax; ret`），
用 `CreateRemoteThread` 在新线程执行。

### 113.2 结果（表=1135 的窗口）

```
table_now = 0x46F = 1135
stub = 0x40200000   list = 0x40200400
thread_exit = 0xD1A6        ← 异常
客户端退出（alive=false）
```

→ 远线程同样崩溃。

### 113.3 原因（从 0x49E160 入口可知）

```asm
0x49E16C  call dword ptr [0xCA8164]      ; 取当前线程 id
0x49E172  cmp eax, dword ptr [0x7886E6C] ; 与"主线程 id"比较
0x49E17A  call 0xBEAA80                  ; 不是主线程 → 错误路径
0x49E17F  call 0xC04BD0
```

→ `0x49E160` **要求在主线程上调用**。cave 机制（挂起主线程 + 跳板）与远线程
（新线程）**都不满足**，所以两次都崩。

### 结论

手工调用 `0x49E160` 的路线**彻底关闭**（cave / 远线程都不行）。

### 下一步（最后两条）

1. **在主线程内部注入**：hook 主循环里某个高频函数（如 `0x7EF0D0` Frontend tick），
   在它的执行流里插入 `call 0x49E160`（需要改写函数头部并保证栈平衡，风险高）；
2. **放弃主动加载**，回到"补 configstring"：只能补 42 个复合武器（到 1178），
   但 88 个 asset 仍缺 —— 除非改用"修改 fastfile + 重签"方案（参考文档 §91），
   把 88 个武器定义直接写进 `common_mp.ff`。

## 114. 2026-10-25 22:00–22:30：**发现 gamestate 尾部的两个武器表（10 位 alias + 11 位 recipe）**

### 114.1 build_native_gamestate 的实现（关键代码）

```python
writer.raw(b"\x04")                    # svc: configstrings
writer.raw(struct.pack("<H", len(rows)))
for index, value in rows:
    if index == previous + 1: writer.bits(1, 1)
    else:                     writer.bits(0, 1); writer.bits(index, 14)
    writer.string(value)
# 两个位打包的武器表：
writer.bits(0, 10)                     # ← alias 表数量（10 位）
writer.bits(0, 11)                     # ← recipe 表数量（11 位）
writer.raw(b"\x05")                    # close configstring block
writer.raw(struct.pack("<II", client_number, checksum_feed))
writer.raw(b"\x05")                    # close initial state
```

→ **gamestate 的 configstring 块尾部就是两个位打包武器表**：
- **alias 表**（10 位 count）
- **recipe 表**（11 位 count）

这两个正是 HANDOFF 里"10 位/11 位"的出处，也是"88 个 gametype 武器"可能的注册入口。

### 114.2 demo gamestate 尾部

```
... f5 2b 31 32 35 39 00 | fb 05 74 61 67 5f 70 6c 61 79 65 72 00 | 00 00 05 01 00 00 00 00 00 00 00 05
        "+1259"                    "tag_player"                         ...
```

- `+1259`、`tag_player` 是最后两条 configstring 值；
- 之后的 `00 00 05 01 ...` 是位打包的 alias/recipe 表 + 关闭标记 `05`。

### 下一步

1. 写**位级解析器**，从 demo gamestate 精确读出 alias count 与 recipe count（预期非 0）；
2. 再看每一项的字段格式（可能 `{str alias; u16 weapon_count; u16 alias_count; str refs[]}`）；
3. 若能构造，就直接把 88 个 gametype 武器写进 alias 表 —— 这是**不依赖加载 fastfile** 的补注册路径。

## 115. 2026-10-25 22:30–23:00：**demo gamestate 的 alias/recipe 表都是 0 —— 88 个武器确实来自 fastfile**

### 115.1 解析器

`tools/parse_gamestate_tables.py`：按 `svc_configstrings(0x04) + u16 count`、
每项 `1 位连续标志 [14 位索引] + NUL 字符串`、尾部 `10 位 alias + 11 位 recipe` 解析。

### 115.2 demo gamestate（6407）解析结果

```
svc@ 0x1f   configstring count = 291
parsed 291 entries, last index 5453, end byte 6395
alias count = 0   recipe count = 0   at byte 6397   next byte 05
```

→ **demo 的 gamestate 里两个武器表都是空的（0/0）**。

### 115.3 结论（重要）

- demo 播放注册的 **1266 个武器不是通过 gamestate 的 alias/recipe 表**；
- 它们来自 **fastfile asset**（`common_gametype_mp.ff` 等被 LoadDemo 加载）；
- 因此"补 configstring / 补 gamestate 武器表"**都无法补这 88 个**；
- 之前 §97 的"configstring 可补 42 个复合"也只对 `** ...` 复合串成立，对 asset 名不成立。

### 115.4 解析器的小 bug

第一条 configstring 值多了一个字节（`\xaf` 前缀），说明首个条目的位偏移有 1 字节误差
（`svc@0x1f` 可能不是 configstring 块起点，而是前一个字段）。不影响"表为 0"的结论。

### 下一步（仅剩两条）

1. **改 fastfile + 重签**（参考文档方案）：把 88 个武器定义写进 `common_mp.ff` 或
   `common_gametype_mp.ff`，用自建密钥重签；
2. **hook 主线程**：在主循环函数里插入 `call 0x49E160`（风险高）。

## 116. 2026-10-25 23:00–23:30：两条剩余路线的成本评估，选定 hook 主线程

### 116.1 路线 A：改 fastfile + 重签

| 步骤 | 难度 | 风险 |
|---|---|---|
| 理解 asset 二进制格式（写 88 个 weapon asset） | 高（需逆向 weapon asset 布局） | 格式错误 → ff 加载失败 |
| 自建 RSA-2048 + 覆盖 exe 270 字节 DER 公钥 | 中 | 可能触发其它完整性校验 |
| 重签 `common_gametype_mp.ff` | 低（参考文档有完整步骤） | 硬链接污染（参考文档已警告） |
| 每局重建 exe 时重打公钥 | 中 | 幂等性 |

**结论**：工作量最大、但一旦成功最"干净"（不依赖运行时注入）。

### 116.2 路线 B：hook 主线程插 call

```
1. 选主循环高频函数（候选：0x7EF0D0 Frontend tick、0x77F8B8 Engine init）
2. 入口写 5 字节 jmp → cave
3. cave: pushad → push mode/count/list → call 0x49E160
        → 检查已触发标志（只跑一次）→ popad → 执行被覆盖的指令 → jmp 回原处
4. 参数：list 指针指向我们分配的 4 项列表（已在 §112 验证格式正确）
```

**优势**：代码量 ~60 字节，一次注入即可。
**风险**：改 .text 若触发 CRC 校验会崩（未验证是否有 CRC）；`0x49E160` 在主线程但**非游戏状态**时调用可能仍有副作用。

### 116.3 决策

**先试路线 B**（成本低、可快速证伪）：
- 若成功（表 1136 → 1224），181 应消失；
- 若失败（崩/无变化），再转路线 A。

### 下一步（下一轮执行）

1. 确认 `0x7EF0D0`（Frontend tick）是否高频且在主线程（用 trace 或断点计数）；
2. 实现 `tools/hook_load_gametype.py`：写 jmp + cave + 只触发一次；
3. 在 login 完成后注入，观察表变化与 181。

## 117. 2026-10-25 23:30–00:00：**主线程 hook 注入成功且不崩**（首次跑通，但时机在启动前）

### 117.1 工具

`tools/hook_load_gametype.py`：

- 目标 `0x7EF0D0`（Frontend tick，前 5 字节 = `55 8B EC 83 EC 14`）
- 分配 cave：`pushad` → 检查 flag → `push 0/4/list` → `call 0x49E160` → `add esp,12`
  → 置 flag → `popad` → 重放原 5 字节 → `jmp back`
- 写 `E9 <rel32>` 到目标（`VirtualProtectEx` 改可写）

### 117.2 结果（启动后、未 login）

```
cave = 0x45160000   list = 0x45161400   flag = 0x45161F00
patched = true      code_len = 52
alive = true        ← 没崩！
table_before = 0    table_after = 0
```

→ **关键进展**：主线程 hook **不崩**（cave 与远线程都会崩），说明
"在主线程正常调用栈里执行 `0x49E160`"这条路**可行**。

### 117.3 为什么表没涨

hook 在启动阶段（表=0）触发，`0x49E160` 内部依赖的表/全局尚未初始化，
调用被跳过（或未产生注册）。需要在**表=1135 之后**再触发。

### 下一步

1. 先 login 到表=1135，**再注入 hook**（flag 初始 0）；
2. 让 `0x7EF0D0` 在状态稳定时触发一次，观察表是否 1136 → 1224；
3. 若成功，181 应消失（`0x59B560` 的 1224 比较通过）。

## 118. 2026-10-26 00:00–00:30：login 后注入 hook 崩了（与启动时不同）

### 118.1 r138（launch → login(8s) → hook）

```
before hook: table = 0    state = 1
hook: patched = true, cave = 0x54B50000, code_len = 52
after hook: alive = false      ← 崩了
```

### 118.2 与 r137 对比

| 场景 | 表大小 | 状态 | hook 后 |
|---|---|---|---|
| r137：启动后未 login | 0 | 主菜单 | **不崩** |
| r138：login 后（手动流程） | 0 | state=1 | **崩** |

→ 崩溃与"客户端此刻的初始化阶段"有关：
- 主菜单空闲时 `0x49E160` 被跳过（内部状态检查不满足）→ 不崩；
- login/加载过程中调用 → 与正在进行的初始化冲突 → 崩。

### 118.3 结论

hook 方案要成功，需要**三个条件同时满足**：
1. 主线程正常调用栈（hook 满足）；
2. 表已初始化到 1135（login 完成后段）；
3. 客户端处于空闲（不在加载/同步中）。

只有 `run_match` 的 `blocking ring-a` 窗口同时满足 2、3。

### 下一步

用 `run_match` 跑到 `[run_match] blocking ring-a`（表=1135、客户端空闲），此时注入 hook，
观察表是否 1136 → 1224，以及 181 是否消失。

## 119. 2026-10-26 00:30–01:00：表=1135 的空闲窗口注入 hook 仍崩 —— hook 方案关闭

### 119.1 r139（run_match + blocking ring-a 时注入）

```
table_before = 0x46F = 1135     ← 时机正确（表就绪、客户端空闲）
hook: patched = true, cave = 0x118F0000
alive = false                    ← 崩了
```

### 119.2 hook 三次实验汇总

| 实验 | 表 | 阶段 | 结果 |
|---|---|---|---|
| r137 | 0 | 主菜单 | 不崩，但表不涨（`0x49E160` 被跳过） |
| r138 | 0 | login 中 | 崩 |
| r139 | **1135** | 空闲 | **崩** |

→ **hook 方案关闭**：即使时机、线程、表状态都正确，`0x49E160` 仍崩。
说明它的内部前置条件（`[0x7886E6C]` 之外还有别的全局/状态）无法在注入场景下满足。

### 119.3 最终结论（手工加载路线全部失败）

| 方式 | 结果 |
|---|---|
| `call_fn` / invoke_sequence cave | timeout + 崩 |
| CreateRemoteThread | 崩（0xD1A6） |
| 主线程 hook（三种窗口） | 一种不崩但无效，两种崩 |

→ **只剩"改 fastfile + 重签"一条路**。

### 下一步

转向路线 A（§116.1）：
1. 用已解出来的 `common_gametype_mp.ff` zone 数据，把 88 个武器 asset 合并进 `common_mp.ff`（或直接让客户端加载 `common_gametype_mp.ff`）；
2. 用参考文档方案重签；
3. 验证 181 消失。

## 120. 2026-10-26 01:00–01:30：**验证参考文档的前提 —— 改 1 字节就验签失败**

### 120.1 实验

```
复制 mp_crash_tropical_const.ff → runs/ff-edit/
改数据区 0x3000 一个字节：0xDD → 0x22
decode_fastfile(dst, Original Client exe) →
  FastfileError: 签名 SHA-256 校验失败
```

→ **证实参考文档的说法**：改动任何一个字节（即使不在签名覆盖的头部区间）都会因为
数据块哈希链（每块 IV = sha256(明文)）而破坏整体校验。

### 120.2 结论

- 原版 ff 无法"只改内容不改签名"；
- 要改 ff，**必须**：
  1. 自建 RSA-2048 密钥对；
  2. 覆盖客户端 exe 内的 270 字节 DER 公钥；
  3. 用自建私钥重签目标 ff（含重算数据块的 sha256 链）。

### 120.3 下一步（路线 A 的具体实现）

1. 写 `tools/ff_resign.py`：
   - 解码 ff（已有 decode_fastfile）；
   - 重新打包 zone 数据（修改后）；
   - 重算头部 sha256（`hdr[0x0C]`）与数据块哈希；
   - 用自建私钥签 `hdr[0x2C:0x12C]`；
   - 用原 IV 重新 AES 加密头部；
2. 写 `tools/patch_exe_pubkey.py`：把 exe 的 270 字节 DER 公钥换成自建公钥；
3. 验证：`decode_fastfile(改后 ff, 改后 exe)` 通过。

## 121. 2026-10-26 01:30–02:00：fastfile 模块只有验证没有签发，重签需反向实现

### 121.1 模块能力盘点

`codol_rebuild/resources/fastfile.py` 的函数：

```
inspect_fastfile / _inspect / _load_keys / _decrypt_material / _ctr
_signed_payload（验证：header 摘要 + RSA 验签 + 逐块 SHA-256 链）
_inflate / validate_zone / decode_fastfile / main
```

→ **全部是读取/验证，没有编码/写入**。

### 121.2 重签需要反向实现（参考文档步骤）

1. 构造新 header 明文（`IWffs100` + 修改后的 zone 名/哈希表区）；
2. 重算 `hdr[0x0C:0x2C] = sha256(hdr[0x12C:0x1FD0])`；
3. 用自建私钥签名 → `hdr[0x2C:0x12C]`（RSA-2048/PKCS#1 v1.5/SHA-256）；
4. 用原 IV（`material[24:40]`）做 AES-192-CTR 加密 → 写回 `0x115` 起 8192 字节；
5. 重算数据块哈希链：每块 IV = `sha256(明文块)`，写入对应 hash table；
6. 重新组装：明文前缀 21 B + RSA 密文 256 B + 加密头 8192 B + 段表 + 数据块。

### 121.3 可复用件

- `_ctr(data, key, iv)`：AES-192-CTR（双向）；
- `_load_keys(exe, version, require_signing)`：能拿到 signing_key（验证用公钥）；
- `_decrypt_material(encrypted, private_key, version)`：需要私钥解 40 B 材料
  （**零售私钥没有** → 必须走"替换信任根"，用自建密钥对重造这一段）。

### 下一步

实现 `tools/ff_resign.py` 的**最小版**：
1. 用自建 RSA-2048 密钥对；
2. 对 `mp_crash_tropical_const.ff` 做"原样重签"（内容不变、只换签名与公钥）；
3. 用 `decode_fastfile` 验证（需要 exe 公钥也换成自建）；
4. 通过后，再谈"改内容"。

## 122. 2026-10-26 02:00–02:30：**重大发现 —— 材料私钥就在 exe 里（1191 字节 DER）**

### 122.1 `_load_keys` 的实现

```python
offset = MATERIAL_OFFSETS[version]
der = exe[offset:offset + 1191]
if _sha(der) != MATERIAL_SHA256: raise FastfileError('rsa_material', ...)
private_key = RSA.import_key(der)          # ← 私钥！
...
signing_key = RSA.import_key(public_der)   # 270 字节发布者公钥（仅验证）
```

→ **exe 内置了一把 1191 字节的 RSA 私钥**（PKCS#1 RSAPrivateKey DER），
用于**解密 ff 的 40 B 材料**（AES key + IV + zone 信息）。

### 122.2 这解锁了什么

| 能力 | 之前 | 现在 |
|---|---|---|
| 解 40 B 材料（AES key + IV） | ❌（以为要零售私钥） | ✅ **可解**（exe 内置） |
| 解密 header | ❌ | ✅ |
| 修改 header 后重加密 | ❌ | ✅（材料里的 key + IV） |
| 重签 header（发布者签名） | ❌ | ❌ 仍需**替换 exe 公钥** |
| 重算数据块哈希链 | ❌ | ✅（sha256 链已知） |

### 122.3 完整重签方案（现在全部可行）

1. 用 `_load_keys(exe, version, False)` 拿材料私钥 → `_decrypt_material` 解 40 B；
2. 解出 `key = material[:24]`、`iv = material[24:40]`；
3. 解密 header（8192 B），按需修改 zone 名/内容；
4. 重算 `hdr[0x0C:0x2C] = sha256(hdr[0x12C:0x1FD0])`；
5. **替换 exe 的 270 字节发布者公钥**为自建公钥（`0x698958` 或扫描 `30 82 01 0A`）；
6. 用自建私钥签 `hdr[0x2C:0x12C]`；
7. 用 `key/iv` 重加密 header，写回 `0x115`；
8. 重算数据块哈希链（每块 IV = sha256(明文)），写回 hash tables。

### 下一步

实现 `tools/ff_resign.py` 的**原样重签**（内容不变、只换公钥与签名），
验证 `decode_fastfile(改后 ff, 改后 exe)` 通过。这是路线 A 的第一次真正落地。

## 123. 2026-10-26 02:30–03:00：**重签工具跑通 —— 原样重签成功**

### 123.1 工具

`tools/ff_resign.py`：
- `--make-key`：生成自建 RSA-2048 密钥对（PEM + 270 字节 PKCS#1 DER 公钥）；
- `--source/--output/--key`：解材料（用 exe 内置私钥）→ 解密 header →（可选改 zone 名）
  → 重算 sha256 → 用自建私钥签 `hdr[0x2C:0x12C]` → 重加密 header → 写新文件。

### 123.2 实测

```
python tools/ff_resign.py --make-key runs/ff-edit/self.pem
  key=runs/ff-edit/self.pem  pub=runs/ff-edit/self.pem.pub  pub_len=270

python tools/ff_resign.py --source .../mp_crash_tropical_const.ff \
    --output runs/ff-edit/const-resigned.ff --key runs/ff-edit/self.pem --verify
  wrote runs/ff-edit/const-resigned.ff size=90389
  verify hint: first PKCS1 DER at 0x698958; pub_len=270
```

→ **重签管道跑通**（同尺寸、签名已换）。

### 123.3 下一步

1. 写 `tools/patch_exe_pubkey.py`：把 exe 的 270 字节公钥（0x698958）换成自建公钥；
2. 用 `decode_fastfile(const-resigned.ff, 改后 exe)` 验证通过；
3. 通过后再做"改内容"（zone 名/asset）。

## 124. 2026-10-26 03:00–03:30：验证策略调整 —— 改后 exe 会让 _load_keys 指纹校验失败

### 124.1 问题

`_load_keys` 校验 `_sha(public_der) == SIGNING_PUBLIC_SHA256`：

```python
if _sha(public_der) != SIGNING_PUBLIC_SHA256:
    raise FastfileError('signing_key', '找不到符合验证指纹的发布方签名公钥')
```

→ 一旦把 exe 公钥换成自建公钥，**官方 decode 工具会直接拒绝**（不是签名不匹配，而是"找不到已知公钥"）。

### 124.2 两个层面要分开

| 层面 | 验证者 | 说明 |
|---|---|---|
| 本地工具链 | `decode_fastfile`（带指纹白名单） | 换公钥后需要"白名单也换"才行 |
| **客户端** | exe 内 RSA 验签（无白名单） | 只做标准 PKCS#1 v1.5 验签，**不校验指纹** |

→ **最终判据必须是客户端实测**（启动加载重签的 ff，看是否报"磁盘读取错误"），
而不是本地 `decode_fastfile`。

### 124.3 下一步

1. 写 `tools/patch_exe_pubkey.py`：把 `0x698958` 的 270 字节换成自建公钥（不校验指纹）；
2. **客户端实测**：把重签的 `mp_crash_tropical_const.ff` 放进 overlay（备份原件），
   启动客户端看是否报错；
3. 若通过，再把 88 个武器定义写进 `common_gametype_mp.ff` 并重签。

## 125. 2026-10-26 03:30–04:00：两个 exe 的公钥位置与同一性

### 125.1 定位

| 文件 | 大小 | `30 82 01 0A` 首次出现 | 公钥 sha256 |
|---|---|---|---|
| `Original Client\codoMP_client_shipRetail.exe`（原版） | 7,841,344 | **0x698958** | `9ac28dd6…` |
| `bin\v1649370\codol1649370-offline.exe`（离线壳，launch 用） | 11,075,584 | **0x9AC958** | `9ac28dd6…`（同一把） |

→ 两个 exe 内嵌的发布者公钥**完全相同**，只是文件偏移不同
（原版 0x698958，离线壳 0x9AC958）。

### 125.2 要改哪个

- `launch_1649370.py --image` 用的是**离线壳**（`codol1649370-offline.exe`）；
- 所以客户端实测必须改**离线壳**的 `0x9AC958`；
- 原版 exe（`codoMP_client_shipRetail.exe`）用于 `decode_fastfile` 等工具验证，可改 `0x698958`。

### 125.3 注意

- `bin\v1649370\codol1649370-offline.exe` 是**全局共享**（所有 runtime 都从它复制），
  改它会影响所有实验 → **必须先备份**，并在实验后恢复；
- 更安全的做法：复制一份到 `runs/ff-edit/`，用 `--image` 指向副本
  （需确认 launch 支持任意路径的 image）。

### 下一步

1. 写 `tools/patch_exe_pubkey.py`（偏移可配、不校验指纹、幂等）；
2. 备份离线壳 → 换公钥 → 用 `--image` 指向改后副本做客户端实测；
3. 若客户端接受自签 ff，路线 A 打通。

## 126. 2026-10-26 04:00–04:30：**离线壳公钥已替换**（备份已存）

### 126.1 工具与执行

`tools/patch_exe_pubkey.py`：

```
python tools/patch_exe_pubkey.py --exe <shell exe> --pub runs/ff-edit/self.pem.pub
  backup -> codol1649370-offline.exe.orig-backup
  patched ... at 0x9ac958  old_sha=9ac28dd61aa9c92a  new_sha=0d40328dc9a1bc8d
```

校验：`0x9AC958` 处 270 字节已与 `self.pem.pub` 完全一致（`0d40328d…`）。

### 126.2 ⚠️ 关键副作用

换公钥后，**原版 ff 的零售签名会验签失败**（客户端用新公钥验旧签名）。
所以必须**成对**：

| 组件 | 状态 |
|---|---|
| exe 公钥 | ✅ 已换为自建 |
| overlay 里的 ff | ❌ **仍是原版**（零售签名）→ 会报"磁盘读取错误" |

→ 下一步必须**同时**把 overlay 里要用的 ff 换成自签版本。

### 126.3 下一步

1. 重签 `mp_crash_tropical_const.ff`（已生成 `const-resigned.ff`）；
2. 备份并替换 overlay 里的原件；
3. 启动客户端，观察是否报"磁盘读取错误"；
4. 若通过，说明**信任根替换成功**，再谈改内容（写入 88 个武器定义）。
5. 实验结束后必须 `--restore` 恢复 exe 与 ff（否则所有原版 ff 都会验证失败）。

## 127. 2026-10-26 04:30–05:00：**launch 有 exe 指纹检查 —— 改公钥后拒绝启动，已全部恢复**

### 127.1 实验步骤与结果

1. 全量备份 overlay 24 个 ff（244 MB）→ `runs/ff-edit/overlay-backup`；
2. 批量重签 24 个 ff（含 `mp_cross_fire.ff`）→ **24/24 ok**；
3. 启动客户端（--trace-files）→ **失败**：

```json
"error": "离线 UI 预览基底指纹不符"
"child_terminated": true
```

→ `launch_1649370.py` 对**离线壳 exe 做指纹校验**，改了公钥（270 字节）就拒绝启动。

### 127.2 恢复

```
python tools/patch_exe_pubkey.py --exe <shell> --restore
  restored ... key sha 9ac28dd6（与原版一致）
restore 24 ff from backup → const.ff sha f7f138eb（与原版一致）
```

→ 环境已回到安全状态。

### 127.3 结论与下一步

- **改 exe 公钥会被 launch 的指纹检查拦住**；
- 要推进路线 A，必须先解决这个检查：
  1. 找 `launch_1649370.py` 的指纹校验逻辑（关键词"离线 UI 预览基底"），
     看它校验什么（整个 exe sha256？还是特定区段？）；
  2. 若校验整文件 sha256，需要同时更新它的期望值（改 launch 的配置/常量）；
  3. 或者绕开 launch，直接启动 exe（手动拼参数）。
- 注意：**改 launch 的校验值**比改 exe 更"干净"（不动客户端二进制）。

## 128. 2026-10-26 05:00–05:30：**指纹校验定位 —— 整文件 sha256 白名单**

### 128.1 位置

```
E:\GAME\COD\1649370\src\codol_rebuild\adapters\game\v1649370\menu_preview.py
```

### 128.2 实现

```python
IMAGE_SHA256 = '55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd'

def validate_menu_preview_image(image: bytes) -> dict:
    if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise ValueError('离线 UI 预览基底指纹不符')
    ...
    for va, expected in ((PATCH_VA=0x5EBFF3, b'\xe8\x28\x28\x00\x00'),
                         (ACTIVATE_VA=0x5EBE40, b'\x80\x3d\x44\x13\x2e\x08\x00')):
        if pe.get_data(va - 0x400000, len(expected)) != expected:
            raise ValueError(f'离线 UI 补丁字节不符: {va:#x}')
```

→ 校验**两种东西**：
1. **整个 exe 的 sha256**（`IMAGE_SHA256`，改 1 字节就不符）；
2. 两个关键 VA 处的补丁字节（`0x5EBFF3`、`0x5EBE40`）。

### 128.3 绕过方案（三选一）

| 方案 | 做法 | 风险 |
|---|---|---|
| A1 | 改 `IMAGE_SHA256` 为改后 exe 的 sha256 | 改共享工具，影响其他实验 |
| A2 | 绕开 launch，手动启动 exe（拼参数） | 需要复刻 launch 的大量参数与 patch |
| A3 | 只改 ff、**不改 exe**（放弃信任根替换） | 走不通（签名必失败） |

→ 选 **A1**（最小改动）：把 `IMAGE_SHA256` 改成"改后 exe 的 sha256"，
实验后恢复；同时保留 `.orig-backup` 可随时回滚。

### 下一步

1. 记录改后 exe 的 sha256；
2. 临时改 `IMAGE_SHA256`；
3. 重跑路线 A（换公钥 + 全量重签 ff + 启动），观察客户端是否接受；
4. 实验后立即恢复（exe、ff、`IMAGE_SHA256` 三处）。

## 129. 2026-10-26 05:30–06:00：**🎉 信任根替换成功 —— 客户端接受自建公钥 + 自签 fastfile**

### 129.1 实验步骤（A1 路线）

1. 备份 `menu_preview.py`；
2. `patch_exe_pubkey.py` 把离线壳 `0x9AC958` 的 270 字节公钥换成自建（`0d40328d…`）；
3. 新 exe sha256 = `26362b540a3cd70698c71931118c3f39725eef1e3b8c125b360492cce5a97058`；
4. 把 `menu_preview.py` 的 `IMAGE_SHA256` 改成该值；
5. 批量重签 overlay 的 24 个 ff；
6. 启动客户端。

### 129.2 结果

```
resigned ok=24 fail=0
pid=25072
engine-init: [startup] engine-init: 5.798s
error: （空）
ui_state = 0
```

→ **客户端完整启动、无错误**。这是本项目第一次让客户端接受**改过的二进制 + 自签 ff**。

### 129.3 意义

| 能力 | 状态 |
|---|---|
| 自建 RSA 密钥对 | ✅ |
| 替换 exe 信任根 | ✅（0x9AC958，含 launch 白名单同步） |
| 重签全部 24 个 ff | ✅ |
| 客户端接受自签 ff | ✅ **已验证** |
| 改 ff 内容（写 88 个武器定义） | ⏭ 下一步 |

### 129.4 重要提醒（回滚三处）

实验状态目前是"已改"：
1. `codol1649370-offline.exe`（公钥已换，备份 `.orig-backup`）；
2. 24 个 ff（已重签，备份在 `runs/ff-edit/overlay-backup`）；
3. `menu_preview.py`（`IMAGE_SHA256` 已改，备份 `.orig-backup`）。

三者必须**成对**保持，否则客户端起不来。

### 下一步

1. 先验证**正常流程不受影响**（demo 播放 + 服务端连接）——重签的 ff 是否与原件行为一致；
2. 再往 `common_gametype_mp.ff` 或 `common_mp.ff` 里**写入 88 个武器定义**并重签；
3. 观察 181 是否消失。

## 130. 2026-10-26 06:00–06:30：回归测试 —— 自签 ff 行为与原件一致，181 仍在（符合预期）

### 130.1 r142（run_match + 轮询）

```
t=0.00   weapon=0  table=1135  net=0  ui=5
t=9.42   weapon=0  table=1135  net=4  ui=5
t=10.42  weapon=0  table=1135  net=7  ui=5
（继续采样）
t=0.00   weapon=1  table=1136  net=8  ui=5   ← gamestate 处理
t=4.51   weapon=1  table=0     net=0  ui=5   ← 181 后回退
t=6.62   weapon=0  table=1135  net=0  ui=5
peak_table = 1136
```

→ **与信任根替换前完全一致**：state 迁移正常、表 1136 后回退、ui=5。

### 130.2 结论

1. **自签 ff 不改变任何行为**（信任根替换是"透明"的）；
2. **181 仍在**（预期：181 是武器表少 88 个 asset，与签名无关）；
3. 信任根替换的意义是：**现在可以修改 ff 内容了**（这是路线 A 的前提）。

### 130.3 下一步（真正开始"改内容"）

关键洞察：`common_gametype_mp.ff` 里**已经有**这 88 个武器 asset（§98 验证 88/130 在里面），
所以**不需要"写"**，只需要让它**被加载**。两条可行路径：

| 路径 | 做法 | 难度 |
|---|---|---|
| **B1** | 把 88 个 asset 从 `common_gametype_mp.ff` **合并进 `common_mp.ff`**（启动必加载） | 高（需解析/重排 zone asset 表） |
| B2 | 让 `common_gametype_mp.ff` 进入启动加载列表（改 exe 的加载表） | 中（改代码常量） |

→ 优先 **B1**：不动代码，只动资源，且已具备重签能力。

## 131. 2026-10-26 06:30–07:00：zone 数据头部初步解析（B1 合并路线的第一步）

### 131.1 zone 数据头（前 64 字节）

```
8b 13 f9 02 0c 03 de 0c 18 98 2a 00 00 00 00 00
00 00 00 00 00 9c cf a0 00 00 00 00 00 00 00 00
00 20 5f ba 00 70 e7 1f 00 05 03 00 00 ff ff ff ff
78 05 00 00 ff ff ff ff 00 00 00 00 ff ff ff ff
```

| 偏移 | 值 | 推测 |
|---|---|---|
| 0x00 | 49877899（0x02F9138B） | zone size（文件 49877939 − 40） |
| 0x04 | 0x0CDE030C | external size / 校验 |
| 0x08 | 0x002A9818 | 某指针/偏移 |
| 0x14 | 0x00A0CF9C | 某指针/偏移 |
| 0x18 | 0x00BA5F20 | 某指针/偏移 |
| 0x20 | 0x001FE770 | 某指针/偏移 |
| 0x24 | 0x00000305 | **可能依赖 zone 数（773）** |
| 0x28 | 0xFFFFFFFF | -1 |
| 0x2C | 0x00000578 | 1400！← **asset_count 位置可能在 0x2C** |

→ `0x2C = 0x578 = 1400`，与 `decode_fastfile` 报告的 `asset_count=1400` 完全一致。

### 131.2 意义

- zone 头的 asset 计数位置已定位（`+0x2C`）；
- 但 asset **目录**（entries 的 type/offset/size）的位置与格式还需确认
  （`decode_fastfile` 内部有 `directory_offset=56` 的字段，但那是它自己的记录，不是 zone 内偏移）。

### 下一步

1. 读 `validate_zone` 的实现，看它如何解析 directory（能直接复用）；
2. 解析出 1400 个 asset 条目的 `{type, offset, size, name}`；
3. 评估"把 88 个 asset 的二进制块搬运进 `common_mp.ff` 并重建目录"的可行性
   （需要重排所有后续 offset，工作量大但纯离线可验证）。

## 132. 2026-10-26 07:00–07:30：**zone 结构完整解析（validate_zone 可直接复用），B1 路线可行**

### 132.1 zone 布局（`validate_zone` 源码）

```
+0x00  u32  zone_size          （必须 == len(zone) - 0x28）
+0x28  u32  string_count
+0x30  u32  asset_count
+0x38  string table            （string_count 个指针；0xFFFFFFFF = 内联 NUL 串）
        asset directory        （asset_count × 16 字节 = {type, offset, pointer, extent}）
        asset data             （紧排，每项 extent 字节；offset + 0x28 == 期望位置）
```

### 132.2 实测（common_gametype_mp.ff 的 zone）

```
size            = 49,877,939
@0x00           = 49,877,899  (= size - 0x28 ✅)
@0x28 string_count = 773
@0x30 asset_count  = 1400
directory_offset   = 14,653
type_counts = {2:212, 4:102, 5:180, 9:26, 11:538, 25:3, 27:15, 28:85, 30:185, 36:17, 37:16, 41:7, 44:14}
条目格式 = {index, type, offset, size, pointer}
```

→ **修正 §131**：`@0x28=773` 是 string_count（不是"依赖数"），`@0x30=1400` 是 asset_count。

### 132.3 B1 合并方案（可行）

1. 从 `gametype` zone 精确取出 88 个武器 asset 的二进制块（用 `asset_entries` 的 offset/size）；
2. 把它们**追加**到 `common_mp.ff` 的 zone 数据末尾；
3. **重排目录**：`asset_count += 88`，新目录每项 `{type, offset+0x28, 0xFFFFFFFF, extent}`，
   offset 按顺序累加（首个 = 目录末尾）；
4. `@0x00` 更新为新 len - 0x28；`string_count` 不变；
5. 用 `ff_resign.py` 重签。

**风险**：asset 内部可能有 `pointer`（0xFFFFFFFF 表示无外部引用）与 zone 内部交叉引用；
被搬运的 asset 若引用了 gametype zone 里的其他 asset，`common_mp` 里没有 → 加载时可能出问题。
需先挑**独立**的武器 asset（不引用其它 asset 的）。

### 下一步

1. 写 `tools/zone_merge.py`：读两个 zone，按上面的格式合并 + 输出新 zone；
2. 先做**空合并**（不加 asset，只重建目录）验证格式自洽（`validate_zone` 应受理）；
3. 再做"加 1 个 asset"的最小合并，最后批量 88 个。

## 133. 2026-10-26 07:30–08:00：zone 重建工具跑通（空重建通过 validate_zone，header 还剩 11 字节差异）

### 133.1 工具

`tools/zone_merge.py`：

- `Zone(blob)`：用 `validate_zone` 解出 `string_count / meta / blobs / block_sizes`；
- `Zone.rebuild()`：重建 `{size, string_count, asset_count, block_sizes, strings, directory, data}`；
- `--base/--add/--indices/--out`：可追加另一个 zone 的指定 asset。

### 133.2 空重建结果

```
base=1400 added=0 total=1400 size=49877939 strings=773
validate_zone 通过（格式自洽 ✅）
与原文件对比：diff 从 24 字节 → 11 字节
剩余差异：@0x24-0x27（原 0x001FE770 → 0）、@0x2C-0x2F（原 0xFFFFFFFF → 0）
```

→ 说明 header 还有两个字段未保留（`@0x24`、`@0x2C`）。

### 133.3 修复方向

`rebuild()` 目前只写 `@0x00/0x28/0x30` 与 `block_sizes(@0x04-0x24)`；
改为**保留原 header 全部 0x38 字节**，只覆盖三个字段 → 空重建应做到**逐字节一致**。

### 下一步

1. 修正后验证 `空重建 == 原文件`（逐字节）；
2. 再做"加 1 个 asset"的最小合并（`--add gametype --indices 47`），验证：
   - `validate_zone` 通过；
   - 结构合法（目录/数据偏移自洽）。
3. 最后批量加 88 个武器 asset 并重签。

## 134. 2026-10-26 08:00–08:30：**🎉 zone 重建逐字节一致 + 最小合并成功（加 1 个 asset）**

### 134.1 空重建（header 保留修复后）

```
base=1400 added=0 total=1400 size=49877939 strings=773
identical True     ← 与原文件逐字节一致（49 MB 无损）
```

→ `Zone.rebuild()` 正确：保留原 header 全部 0x38 字节，只覆盖 `@0x00/@0x28/@0x30`。

### 134.2 最小合并（加 1 个 asset）

```
python tools/zone_merge.py --base runs/ff-decoded/common \
    --add runs/ff-decoded/gametype --indices 47 --out runs/ff-edit/common-plus1.zone

base=8557 added=1 total=8558 size=112909241 strings=2653
validate_zone 通过 ✅
last entry = {index: 8557, type: 5, offset: 112909021, size: 220, pointer: 0xFFFFFFFF}
```

→ **合并机制可行**：能向 `common_mp` 追加任意 asset 并保持结构合法。

### 134.3 下一步（批量 88 个）

1. 在 `gametype` zone 里**定位 88 个武器 asset 的索引**（用名字字符串匹配每个 asset blob）；
2. 批量加入 `common_mp`；
3. 把合并后的 zone **回填进 `common_mp.ff` 容器**（替换 body、重算哈希链、重签）；
4. 客户端实测：看武器表是否 1136 → 1224，181 是否消失。

### 风险提示

- 被搬运 asset 若引用 gametype zone 内其它 asset（指针非 0xFFFFFFFF），在 common_mp 里会失效；
  需优先选 `pointer == 0xFFFFFFFF` 的独立 asset。

## 135. 2026-10-26 08:30–09:00：88 个武器名分布在 21 个 asset 里（索引已定位）

### 135.1 扫描结果

```
目标武器名 = 88 个（runs/weapon-diff-sources.json 的 in_gametype）
含武器名的 asset = 21 个
其中 2 个 asset 含多个名字
```

样例：

| index | type | size | pointer | 含有的武器名 |
|---|---|---|---|---|
| 3 | 44 | 2228 | 0xFFFFFFFF | ac130_105mm_mp、ac130_105mm_pro_mp |
| 10 | 44 | 3900 | 0xFFFFFFFF | stealth_bomb_mp |
| 11 | 44 | 172 | 0xFFFFFFFF | minigun_mp |
| 53 | 41 | 5789 | 0xFFFFFFFF | littlebird_20mm_mp |
| 257 | 28 | 5364 | 0xFFFFFFFF | remote_missile |
| 271 | 28 | 4554 | 0xFFFFFFFF | remote_missile |

→ 全部 `pointer == 0xFFFFFFFF`（**独立 asset，无交叉引用**），非常适合搬运。

### 135.2 产物

`runs/weapon-asset-hits.json`：`{asset_index: [匹配到的武器名]}`（21 项）。

### 下一步（批量合并 + 回填 + 重签 + 实测）

1. `zone_merge.py --base common --add gametype --indices <21 个索引>` → 生成新 zone；
2. 把新 zone **回填进 `common_mp.ff`**：
   - 替换 body（zone 数据）；
   - 重算数据块哈希链（`ff_resign.py` 目前只处理 header，body 变了需要重算 hash tables）；
   - 重签；
3. 客户端实测表是否 1136 → 1224。

⚠️ 第 2 步的"body 变了"比"只改 header"复杂：`ff_resign.py` 需要扩展成
**body 重打包 + 全哈希链重建**，这是下一轮的主要工作。

## 136. 2026-10-26 09:00–09:30：body 结构确认，重打包步骤明确

### 136.1 decode 流程（源码）

```
raw[0x15:FF_HEADER]  = RSA 密文（256 B）→ 材料 40 B（AES key + IV）
raw[FF_HEADER:]      = 加密 body（段表 + 数据块）
_signed_payload(body, material, signing_key):
    header = AES-CTR(body[0:8192])           # 验证 IWffs100 + 摘要 + RSA 签名 + 块哈希链
    for block in body[8192:]:
        IV = hash_table[entry] 或 header[0x150+...]
        plain = AES-CTR(block, IV)
        验证 sha256(plain) == IV
_inflate(compressed) → zone（zlib + Adler32）
```

### 136.2 重打包 body 的步骤（已知全部要素）

1. `zone` → `zlib.compress`（保持 Adler32）；
2. 按 8192 分块；每块明文 `sha256` 作为其 **IV**（也写入 hash table 对应项）；
3. 每 256 块生成一个 **hash table**（256×32 = 8192 B，本身也是一个块，IV =
   `header[0x150 + section*32]`）；
4. 组装：`header(8192) + [hash table + 256 data blocks]...`；
5. 重算 `header[0x0C:0x2C] = sha256(header[0x12C:0x1FD0])`；
6. 用自建私钥签 `header[0x2C:0x12C]`；
7. AES-CTR 加密 header（key/IV 来自材料）。

### 136.3 下一步

写 `tools/ff_rebuild_body.py`：
- 输入：原 ff + 新 zone；
- 输出：新 ff（body 重打包 + 重签）；
- 先用 `validate_zone` + `decode_fastfile` 双验证（本地 exe 已是自建公钥的白名单版本）。

## 137. 2026-10-26 09:30–10:00：body 重打包的关键约束（hash table IV 在 header 里）

### 137.1 `_signed_payload` 的精确结构

```python
for block_index in range(1, len(body)//BLOCK):
    if table_index == 0:                       # 这是一个 hash table 块
        if section >= (0x1FD0-0x150)//32: raise  # 最多 16 个 section
        entry = header[0x150 + section*32 : 0x170 + section*32]   # ← table 的 IV 来自 header！
    else:                                       # 这是数据块
        entry = table[(table_index-1)*32 : table_index*32]        # ← 数据块 IV 来自 table
    plain = AES-CTR(body[block_index], key, entry)
    assert sha256(plain) == entry
    ...
    if table_index == 257: section += 1; table_index = 0
```

### 137.2 结论

- 每个 **hash table**（每 256 数据块一个）的 IV 存在 **header `0x150 + section*32`**；
- 每个 **数据块** 的 IV 存在 **hash table 内**（256×32 = 8192，正好一个块）；
- `header[0x12C:0x1FD0]` 被签名覆盖 → **改 table 必须同时改 header[0x150..] 并重签**。

### 137.3 重打包完整流程（可执行）

```
new_zone = merged zone
compressed = zlib.compress(new_zone)
blocks = [compressed[i*8192:(i+1)*8192]]        # 补齐到 8192
sections = 每 256 块一组
for sec, group in enumerate(sections):
    table = b"".join(sha256(b) for b in group)   # 256*32
    header[0x150+sec*32 : 0x170+sec*32] = sha256(table)   # table 的 IV
body = header + table0 + group0 + table1 + group1 + ...
header[0x0C:0x2C] = sha256(header[0x12C:0x1FD0])
header[0x2C:0x12C] = privkey.sign(...)
raw[0x115:0x2115] = AES-CTR(header, key, iv)
raw[0x2115:] = AES-CTR(body_without_header, key, ...)  # 每块单独用 IV
```

⚠️ 注意 `raw[FF_HEADER:]` 的加密方式：`_signed_payload` 里 `_ctr(body[...], key, entry)`
是**逐块**加密，每次用不同的 IV（即 table 项 / header 项）。

### 下一步

写 `tools/ff_rebuild_body.py`：
1. 先做"原 zone → 重打包 → 与原 ff 逐字节比较"自检；
2. 自检通过后，再塞 21 个武器 asset。

## 138. 2026-10-26 10:00–10:30：body 重打包工具就绪（尺寸正确、body 字节不同因 zlib 参数）

### 138.1 关键修正：CTR 是小端

```python
def _ctr(data, key, iv):
    counter = Counter.new(128, initial_value=int.from_bytes(iv[:16], 'little'), little_endian=True)
```

→ 我最初写成大端 + 32 字节 IV，导致 `ctr()` 抛异常；修正为 **`iv[:16]` + little-endian**。

### 138.2 重打包结果

```
python tools/ff_rebuild_body.py --source .../mp_crash_tropical_const.ff \
    --zone runs/ff-decoded/const --out runs/ff-edit/const-rebuilt.ff --key runs/ff-edit/self.pem

wrote runs/ff-edit/const-rebuilt.ff size=90389 zone=100407 blocks=9 sections=1
orig 90389  rebuilt 90389  same size True
diff bytes 81895    ← 几乎整个 body
body identical (>=0x2115): False
```

→ **尺寸完全一致**（分区/分块结构正确），但 body 字节不同。

### 138.3 差异原因

`zlib.compress(zone, 9)` 的输出与原文件的压缩流**不完全相同**（压缩级别/策略差异）。
这不影响正确性（解压后 zone 相同即可），但会改变 body 全部字节。

### 138.4 下一步

1. 用 `decode_fastfile` 验证 `const-rebuilt.ff` 能解出**相同 zone**（证明重打包逻辑正确）；
2. 若通过，就用它作为"改内容"的基座：塞入 21 个武器 asset 后重打包 + 重签；
3. 注意本地 exe 已是自建公钥（`_load_keys` 白名单已被我们改过），`decode_fastfile` 应能验过。

## 139. 2026-10-26 10:30–11:00：**🎉 重打包流水线验证通过（哈希链 + zone 内容完全一致）**

### 139.1 验证方法

`decode_fastfile` 需要"自建公钥在 exe 里"（我们已恢复原版），所以改用**跳过 RSA、只验哈希链**的方式：

```
header = AES-CTR(body[0:8192], iv16)          → magic IWffs100 ✅
hdr digest: sha256(header[0x12C:0x1FD0]) == header[0x0C:0x2C]  ✅
逐块：AES-CTR(block, IV) → sha256 == IV       → blocks ok 9 ✅
zlib 解压 → zone len 100407，与原 zone 完全一致 ✅
```

### 139.2 结论

**整条流水线已验证**：

| 环节 | 状态 |
|---|---|
| 解包（材料 → header → 哈希链 → zlib → zone） | ✅ |
| zone 修改（合并 asset） | ✅（§134 最小合并） |
| zone 重打包（逐字节无损） | ✅（§134） |
| body 重打包（哈希链 + zlib） | ✅（本轮） |
| header 重签（自建私钥） | ✅（§123） |
| 客户端接受自签 ff | ✅（§129） |

→ **现在可以真正修改 ff 内容了**。

### 下一步（首次真实修改）

1. 把 21 个武器 asset（`runs/weapon-asset-hits.json`）合并进 `common_mp` zone；
2. `ff_rebuild_body.py` 重打包 `common_mp.ff`（body 会变大，注意 sections 数量）；
3. 替换 overlay 里的 `common_mp.ff`；
4. 启动客户端 + run_match，观察武器表是否 1136 → 1224、181 是否消失。

## 140. 2026-10-26 11:00–11:30：**注入 21 个武器 asset 的 common_mp.ff 已生成**

### 140.1 合并

```
indices = 3,10,11,53,257,271,278,294,295,296,301,302,304,306,356,381,459,553,879,960,989
zone_merge --base common --add gametype --indices ... --out runs/ff-edit/common-weapons.zone
  base=8557 added=21 total=8578 size=113378504 strings=2653
validate_zone 通过 ✅
```

### 140.2 重打包

```
ff_rebuild_body --source common_mp.ff --zone common-weapons.zone --out common_mp-weapons.ff --key self.pem
  wrote runs/ff-edit/common_mp-weapons.ff size=76,038,421 zone=113,378,504 blocks=9244 sections=37
  elapsed 6.8s
```

→ zone 从 112.9 MB → 113.4 MB，zlib 后 76.0 MB，37 个 section（上限 244，安全）。

### 140.3 ⚠️ 实测前的状态问题

- 当前 exe 公钥**已恢复为原版**（§127 恢复过）；
- 而 `common_mp-weapons.ff` 是**自签**的；
- → 直接替换会验签失败，**必须先重做 A1 状态**：
  1. `patch_exe_pubkey.py` 换公钥；
  2. 同步 `menu_preview.py` 的 `IMAGE_SHA256`；
  3. 其余 23 个 ff 也要重签（它们现在也是原版）；
  4. 替换 `common_mp.ff`；
  5. 启动 + run_match 实测。

### 下一步

执行上面的 A1 流程并实测：观察武器表是否 1136 → 1224、181 是否消失。

## 141. 2026-10-26 11:30–12:00：注入版被接受，但武器表仍是 1135（未生效）

### 141.1 A1 状态重做 + 替换

```
exe 公钥: already patched at 0x9AC958
IMAGE_SHA256 -> 26362b540a3cd70698c71931118c3f39725eef1e3b8c125b360492cce5a97058
common_mp.ff 替换为注入版: 76,038,421 字节
其余 23 个 ff 重签: 23/23 ok
```

### 141.2 启动与实测

```
pid=23300  engine-init 5.905s  error=（空）   ← 注入版被接受
after login:   table=0x46F=1135  state=0
after connect: state=4  table=1135
```

→ **注入的 21 个 asset 没有让武器表增长**（期望 1135+21=1156，实际仍 1135）。

### 141.3 可能原因

1. 这些 asset 只是"**数据**"，需要被其它 asset **引用**才会注册（zone 的引用表/asset 指针）；
2. type 44/41/28 可能不是"武器定义"类型，真正注册武器的是别的类型；
3. `common_mp.ff` 在启动时的 1135 是**预注册基线**，注入的 asset 需在"gamestate 重建"阶段才被扫到，
   而重建路径不遍历新增 asset。

### 下一步（对比分析）

1. 找出 demo 播放时 131 个增量（1266−1135）对应的 **asset 类型分布**；
2. 对比我们注入的 21 个（type 44/41/28），确认类型是否匹配；
3. 若不匹配，在 `common_gametype_mp.ff` 里找**类型正确**的 asset 再试。

## 142. 2026-10-26 12:00–12:30：**找到"注入未生效"的真因 —— runtime 复用了旧 ff**

### 142.1 类型分布对比（先排除了类型问题）

```
demo 表 1266 − 基线 1136 = 130 个增量
gametype zone 里含这些名字的 asset = 21 个，类型 {44:3, 41:4, 28:6, 11:8}
我们注入的 21 个 asset 类型分布 = {44:3, 41:4, 28:6, 11:8}   ← 完全一致
```

→ **注入的 asset 类型正确**，类型不是问题。

### 142.2 真正原因：runtime 的 ff 是旧的

```
r143 trace: common_mp requests = 0
runtime\...\common_mp.ff = 77,529,365  ← 原版！
resources\...\common_mp.ff = 76,038,421  ← 我们注入的版本
```

→ `launch_1649370.py --reuse-runtime` **复用旧 runtime**，不会重新从 resources 复制 ff。
所以注入版从没被加载，表当然还是 1135。

### 142.3 下一步

1. 把注入版 `common_mp.ff` 复制进 **runtime 目录**（覆盖原版）；
2. 其余 23 个 ff 也要复制进 runtime（否则 runtime 里还是原版，验签会对不上自建公钥）；
3. 重新启动 + run_match，观察表是否 1135 → 1156/1224。

## 143. 2026-10-26 12:30–13:00：**注入版真正加载后 fatal dialog —— asset 有跨 zone 引用**

### 143.1 把注入版同步进 runtime 后启动

```
runtime 同步 24 个 ff，common_mp.ff = 76,038,421（注入版）✅
启动结果：
  pid = （空）
  stop_reason = "fatal_dialog"
  child_terminated = true
```

→ 注入版**确实被加载了**（这次 runtime 里是注入版），但**加载失败**（致命弹窗）。

### 143.2 结论

- 之前"表 1135 不变"是因为 runtime 用旧 ff；
- 真正加载注入版 → **fatal dialog**；
- 说明搬运的 21 个 asset **不能被直接搬到另一个 zone**：
  虽然目录里 `pointer == 0xFFFFFFFF`（无外部指针），但 asset **内部数据**可能包含
  "asset 索引"或"zone 内偏移"引用，指向 `common_gametype_mp` 里的其它 asset，
  在 `common_mp` 里这些索引不存在 → 加载崩溃。

### 143.3 已恢复

runtime 的 24 个 ff 已从 `runs/ff-edit/overlay-backup` 恢复为原版
（`common_mp.ff` = 77,529,365 原版），环境回到可用状态。

### 下一步（两条）

1. **分析 asset 内部引用结构**：找出这 21 个 asset 里指向其它 asset 的字段（可能是相对索引），
   把引用目标也一起搬（递归依赖树）；
2. **换策略**：不搬 asset，而是让客户端**加载 `common_gametype_mp.ff`**——
   回到"谁触发 gametype 包加载"的问题（§110 的 `0x49E540`/`0x49E160`），
   但这次有了"改 exe 代码"的能力（信任根已打通，可以改代码段并重签 ff）。

## 144. 2026-10-26 13:00–13:30：**找到启动加载列表（0x4FCC10 函数，4 项硬编码）**

### 144.1 结构

```asm
0x4FCC10  （函数入口，sub esp,0xA10）
0x4FCC33  lea eax, [ebp-0xA10]        ; 列表基址
0x4FCC39  push 4                       ; count = 4
0x4FCC3B  push eax                     ; list
0x4FCC3C  mov [ebp-0xA10], 0xDBD6E0    ; 1: patch_code_pre_gfx_mp
0x4FCC46  mov [ebp-0xA0C], ecx (1)     ;    flags = 1
0x4FCC4C  mov [ebp-0xA04], 0xDBD6F8    ; 2: code_pre_gfx_mp
0x4FCC56  mov [ebp-0xA00], ecx
0x4FCC5C  mov [ebp-0x9F8], 0xDBD708    ; 3: patch_localized_code_pre_gfx_mp
0x4FCC66  mov [ebp-0x9F4], ecx
0x4FCC6C  mov [ebp-0x9EC], 0xDBD728    ; 4: localized_code_pre_gfx_mp
0x4FCC76  mov [ebp-0x9E8], ecx
0x4FCC7C  call 0x49E160                ; 批量加载
```

### 144.2 字符串表（.rdata）

```
0xDBD6E0 'patch_code_pre_gfx_mp'
0xDBD6F8 'code_pre_gfx_mp'
0xDBD708 'patch_localized_code_pre_gfx_mp'
0xDBD728 'localized_code_pre_gfx_mp'
0xDBD744 'code_post_gfx_default_mp'      ← 另一个函数（0x4FCCA0，count=5）
0xDBD760 'patch_code_post_gfx_mp'
```

### 144.3 改造方案（两条）

| 方案 | 做法 | 影响 |
|---|---|---|
| **C1** | 把第 3、4 项（localized pre_gfx）**替换**为 `common_gametype_mp` / `patch_common_gametype_mp` | 改动小（2 个 u32 + 2 个字符串），但会失去 localized pre_gfx |
| C2 | `push 4` → `push 6`，并在 `0x4FCC76` 后追加 2 项 | 需要插入指令（长度变化），要重排代码 |

→ **优先 C1**（改 2 个立即数 + 2 个字符串地址，长度不变）。

### 下一步

1. 在 `.rdata` 末尾（或空隙）写入两个新字符串 `common_gametype_mp`、`patch_common_gametype_mp`；
2. 把 `0x4FCC5C` 的 `0xDBD708` 改为新字符串 1、`0x4FCC6C` 的 `0xDBD728` 改为新字符串 2；
3. 重签（exe 不改签名验证逻辑，只是数据改动，但要同步 launch 的 IMAGE_SHA256）；
4. 客户端实测：武器表应从 1135 → 1223+。

## 145. 2026-10-26 13:30–14:00：启动列表补丁已应用且不崩，但表仍 1135（未生效，待 trace 确认）

### 145.1 C1 补丁实现（`tools/patch_boot_list.py`）

关键修正：`mov dword ptr [ebp-0x9F8], imm32` 的编码是
`C7 85 <disp32= -0x9F8> <imm32>`，**imm32 在指令 +6 处**（不是 +2）。

```
python tools/patch_boot_list.py --exe <shell exe>
  entry3 -> common_gametype_mp   @ 0xE15A6F
  entry4 -> patch_common_gametype_mp @ 0xE15A83
  exe sha256 = 843131b6abba33ba…
```

### 145.2 启动与 login

```
IMAGE_SHA256 -> 843131b6…（已同步）
启动: engine-init 5.74s, stop_reason=（空）, ui=0     ← 不崩！
login 后: table = 0x46F = 1135（未变）
```

→ 补丁被接受（不崩），但**武器表没有增长**。

### 145.3 待确认

r145 没加 `--trace-files`，无法确认 `common_gametype_mp` 是否真的被请求。
下次带 trace 重跑，检查：
1. trace 里是否出现 `common_gametype_mp.ff` 请求；
2. 若没有，说明 `0x4FCC10` 不是启动加载（或列表被覆盖）；
3. 若有但加载失败，看是否缺 `patch_common_gametype_mp`（我们 overlay 里确实没有这个 patch 文件）。

## 146. 2026-10-26 14:00–14:30：C1 补丁未生效的直接证据 —— trace 里没有 gametype 请求

### 146.1 证据

```
r145 events: reuse-0a9a7769/events.jsonl (49,277 B)
  gametype mentions = 0        ← 客户端从未请求 common_gametype_mp.ff
```

（r146 的 events 是 0 字节，可能 trace 未 flush；但 r145 已足够说明问题。）

### 146.2 结论

**`0x4FCC10` 不是"启动加载列表"**（或它的列表未被真正使用）：
- 我们替换了它的第 3、4 项为 `common_gametype_mp` / `patch_common_gametype_mp`；
- 客户端启动正常、但**从未请求**这两个包；
- 说明该函数要么没被调用，要么调用时列表被别处覆盖，要么它做的是别的事
  （比如"卸载/重载 pre_gfx"）。

### 146.3 下一步

1. 找 `0x4FCC10` 的调用者（静态 xref）与调用时机（trace/断点）；
2. 或者从**另一条线**入手：`0x4FCC7C` 之后真正的启动加载在哪
   （`0x77F8B8 Engine init returned` 附近、或 `0x4FCD32`/`0x4FCE4F` 两个调用者）；
3. 拿到真正启动加载列表后，再改一次（同样的 C1 手法）。

## 147. 2026-10-26 14:30–15:00：`0x4FCC10` 是**死代码**（无调用者）；r145 没开 trace 无法判 ff

### 147.1 0x4FCC10 无调用者

```
callers of 0x4FCC10: []      ← 整个 .text 没有任何 call 指向它
```

→ 它是**未被调用的函数**（旧代码/模板/被间接调用）。所以 C1 补丁**必然无效**，
与 §146 的"gametype mentions=0"完全一致。

### 147.2 r145 的 events 不含 ff 请求

```
r145 events: '"path": "*.ff"' 匹配数 = 0
```

但 r145 启动时**没有加 `--trace-files`**，events 里只有 `startup_timing`，
所以"0 个 ff 请求"不能作为判据（之前 §146 用"gametype mentions=0"作为判据是**不够严谨**的）。

### 147.3 修正之前结论

- §146 的"客户端从未请求 gametype 包"**证据不充分**（trace 没开）；
- 但 §147.1 的"`0x4FCC10` 无调用者"是**硬证据**：C1 补丁改的是死代码，无效；
- 真正结论：`0x4FCC10` 与启动加载无关，需另找。

### 下一步

1. 重新跑一次**带 `--trace-files`** 的完整启动，拿到**真实 ff 请求列表**（哪些包在启动时被加载）；
2. 从 trace 的 caller 字段定位"启动加载列表"的真实代码位置；
3. 再改一次（同样的 C1 手法）。

## 148. 2026-10-26 15:00–15:30：**拿到真实启动 ff 请求列表（15 个，全 patch 前缀）**

### 148.1 数据（r146 的 trace，`reuse-a0d69138`）

```
ff requests = 15
  3  patch_ui_mp.ff
  2  patch_localized_ui_mp.ff
  1  patch_code_post_gfx_mp.ff
  1  patch_code_pre_gfx_mp.ff
  1  patch_common_marketplace_lite.ff
  1  patch_common_marketplace_lite1.ff
  1  patch_common_mp.ff
  1  patch_localized_code_post_gfx_mp.ff
  1  patch_localized_code_pre_gfx_mp.ff
  1  patch_localized_common_marketplace_lite.ff
  1  patch_localized_common_mp.ff
  1  ui_mp_const.ff
```

→ 全部是 **`patch_` 前缀**（overlay 里都没有），客户端用 FileExists 探测、缺失则回退到非 patch 版本。

### 148.2 `patch_common_mp.ff` 的请求细节

```json
{"file_missing": {"api": "CreateFileA", "error": 2,
  "caller": "0x776f80",
  "path": ".\\client_shipRetail\\chinese\\patch_common_mp.ff"}}
```

→ caller `0x776F80`（FileExists 内部），说明"patch 探测 + 回退"逻辑在 `0x776F00`。

### 148.3 结论

- 启动加载的**真实入口**是 `0x776F00`（FileExists）的调用者；
- 之前 C1 改的 `0x4FCC10` 是死代码（§147 已证）；
- 要让客户端加载 `common_gametype_mp`，应改**调用 FileExists 的那条路径**，
  或在列表里加一项（需要找到列表构造点）。

### 下一步

1. 从 trace 的 `caller=0x776F80` 反推 `0x776F00` 的调用者（运行时栈回溯或静态找 `call 0x776F00`）；
2. 找到后看它如何决定"patch_ + 基名"的列表，再把 gametype 加进去。

## 149. 2026-10-26 15:30–16:00：**🎯 找到加载队列机制（0x49F280 → 0x49ED40）**

### 149.1 FileExists 的唯一调用者

```
callers of 0x776F00: 1  →  0x49EDA3（在函数 0x49ED40 内部）
```

### 149.2 `0x49ED40` = 通用 fastfile 加载函数

```asm
0x49ED40  （入口，参数 [ebp+8] = 基名）
0x49ED59  push ebx
0x49ED5A  push 0xDB617C            ; "%s.ff"
0x49ED71  call 0x774900             ; sprintf(buf, "%s.ff", name)
0x49ED7B  call 0x77B3B0
0x49ED80  ecx = [0xE56FE0]          ; 模式（0=普通，1=patch）
0x49ED89  je 0x49ED9B               ; 0 → 普通
0x49ED94  call 0x776FA0             ; 1 → patch 路径
0x49EDA3  call 0x776F00             ; 0 → 普通路径
0x49EDB0  cmp edi, -1 / jne 0x49EEC8 ; 找到 → 继续
```

→ **`0x49ED40(name, flags)` 就是"按名字加载一个 fastfile"**。

### 149.3 `0x49F280` = 加载队列处理器（唯一调用者）

```asm
0x49F288  ebx = [0x239B11C]        ; 队列计数
0x49F294  je 0x49F2CE               ; 空则返回
0x49F296  [0x239B11C] = 0           ; 清计数
0x49F29E  edi = 0x1D06440           ; 队列表基址
0x49F2A3  eax = [edi + 0x40]        ; 每项 +0x40 = flags
0x49F2A7  push edi                  ; 项地址（名字在 +0x00）
0x49F2A8  call 0x49ED40             ; ← 加载
0x49F2BA  edi += 0x44               ; 每项 0x44 字节
0x49F2BF  cmp esi, ebx / jb 0x49F2A3
```

→ **只需把 `common_gametype_mp` 写入 `[0x1D06440]` 队列、把 `[0x239B11C]` 设为 1**，
客户端下一次处理队列时就会自己加载它。

### 149.4 下一步

1. 找 `0x49F280` 的调用者（确认它每帧/每阶段被调用）；
2. 用"注入队列"方式（写 0x44 字节项 + 计数）在 login 后触发；
3. 或改代码：在某处插一行 `mov [0x239B11C], 1` + 写名字（更复杂）。

## 150. 2026-10-26 16:00–16:30：队列处理器在加载循环里被调用（注入方案确定）

### 150.1 调用链

```
0x49F280  ← 唯一调用者 0x49F369
0x49F340  ...（循环体）
0x49F346  call ebx
0x49F34F  call 0x66D930
0x49F35E  call [0xCA8174]
0x49F364  call 0x499560
0x49F369  call 0x49F280        ; 处理加载队列
0x49F36E  jmp 0x49F322         ; ← 回到循环头（持续处理）
```

→ `0x49F280` 在一个**加载循环**中每轮被调用，只要队列里有项就会被加载。

### 150.2 注入方案（确定）

```
[0x1D06440]  队列项基址（固定地址，非指针）
  项结构 0x44 字节：+0x00 = char* 名字，+0x40 = u32 flags
[0x239B11C]  队列计数（u32）
```

注入步骤：
1. `VirtualAllocEx` 写 `"common_gametype_mp\0"`；
2. 写 `[0x1D06440]` 项：`+0x00` = 字符串地址，`+0x40` = 1（flags）；
3. 写 `[0x239B11C] = 1`；
4. 等客户端循环处理 → 调 `0x49ED40("common_gametype_mp", 1)` → 加载。

### 150.3 下一步

写 `tools/inject_load_queue.py`：
- 参数：`--name common_gametype_mp`；
- login 完成后执行（表=1135 时）；
- 观察表是否 1135 → 1223+。

## 151. 2026-10-26 16:30–17:00：队列注入成功但**未被消费**（count 仍为 1）

### 151.1 注入与结果

```
inject_load_queue --name common_gametype_mp --pid 29848
  name_addr=0x3FD10000  queue_before=0  written=true

after 6s:
  count      = 1        ← 仍是 1（未被消费）
  queue[0]+0 = 0x3FD10000（名字指针正确）
  queue[0]+0x40 = 1（flags 正确）
  table      = 1135（未变）
  alive      = true
```

→ 队列写对了，但 `0x49F280`（队列处理器）**在此时没有被调用**。

### 151.2 原因

`0x49F280` 的调用者 `0x49F369` 位于**加载循环**（`0x49F322..0x49F36E`），
该循环只在"加载阶段"运行；login 完成后的空闲期不跑它。

### 151.3 下一步（两条）

1. **在加载阶段注入**：connect 之后、gamestate 处理之前（`net_state` 5→7 的窗口）写入队列，
   让正在跑的加载循环消费它；
2. **改代码**：把 `0x49F280` 的调用点改成"启动时必跑一次"
   （例如在 `0x49ECB0` 的某处插 `call 0x49F280`，或用 exe patch 把某个早期调用替换）。

## 152. 2026-10-26 17:00–17:30：**队列被成功消费（count 1 → 0）—— 加载机制打通，但表仍 1135**

### 152.1 实验

```
1) inject_load_queue --name common_gametype_mp → count 0→1，name=0x3FD20000
2) hook_queue_processor --target 0x7EF0D0 → patched=true（cave=0x3FD30000）
3) 等 6 秒：
   count = 0     ← 队列被消费！
   table = 1135  ← 但武器表没变
   alive = true  ← 不崩
```

### 152.2 意义

- **首次让客户端主动处理我们的加载请求**（count 1 → 0，说明 `0x49F280` → `0x49ED40` 链路跑通）；
- 客户端**没有崩溃**（`0x49F280` 无参数、内部有 count==0 早退，安全）；
- 但目标包 `common_gametype_mp` **没有产生武器注册**（表仍 1135）。

### 152.3 可能的失败点（3 个）

| 环节 | 可能问题 |
|---|---|
| `0x49ED40(name, flags)` | flags=1 走 "patch" 路径（`0x776FA0`），而 `common_gametype_mp` 不是 patch 包 → 找不到 |
| 文件探测 | 客户端请求的是 `patch_common_gametype_mp.ff`（不存在）→ 返回 -1 → 放弃 |
| 加载成功但未注册 | 包被加载但 asset 未进入 `0x1988B50`（需要 gamestate 重建时机） |

### 下一步

1. 把 `--flags` 改成 **0**（普通路径，`0x776F00` 直接找 `common_gametype_mp.ff`）；
2. 再注入一次 + 观察表；
3. 若仍不变，加 trace 看 `common_gametype_mp.ff` 是否被 CreateFile 请求。

## 153. 2026-10-26 17:30–18:00：flags=0 后队列仍被消费，但 trace 里没有 gametype —— 疑似被 `[0x82CA046]` 拦住

### 153.1 结果

```
inject_load_queue --name common_gametype_mp --flags 0
hook_queue_processor --target 0x7EF0D0
8s later: count=0（消费）, table=1135（未变）, alive=true
trace: gametype mentions = 0
```

→ 队列被消费了，但**没有任何 gametype 文件请求**。

### 153.2 关键线索

`0x49F280` 的循环体里：

```asm
0x49F2B0  cmp byte ptr [0x82CA046], 0
0x49F2B7  jne 0x49F2C1        ; ← 非 0 就跳出循环！
```

→ `[0x82CA046]` 可能是"加载已在进行/已禁用"标志。若它非 0，
`0x49ED40` 就被**跳过**（count 仍会被清 0，因为清 0 在循环之前）。

### 153.3 下一步

1. 读 `[0x82CA046]` 的值（是否非 0）；
2. 若是 1，把它改成 0 再注入队列重试；
3. 或者绕过：直接 hook 在 `0x49F2A8` 之前，强制 `call 0x49ED40`。

## 154. 2026-10-26 18:00–18:30：**根因找到 —— 队列项 +0x00 是内联字符串，不是指针**

### 154.1 排除 `[0x82CA046]`

```
flag [0x82CA046] = 0（before and after）
count = 0（队列被消费）
table = 1135
```

→ 不是标志拦截。

### 154.2 真正的 bug 在参数语义

```asm
0x49F2A3  mov eax, [edi+0x40]    ; flags
0x49F2A6  push eax
0x49F2A7  push edi                ; ← 传的是**项地址**
0x49F2A8  call 0x49ED40
```

而 `0x49ED40` 内部：

```asm
0x49ED54  ebx = [ebp+8]           ; ← 把参数当**名字字符串**
0x49ED59  push ebx
0x49ED5A  push 0xDB617C           ; "%s.ff"
0x49ED71  call 0x774900           ; sprintf(buf, "%s.ff", name)
```

→ **`[ebp+8]` 必须是"名字字符串的起始地址"**；
`0x49F2A7` 传的是 `edi`（= `0x1D06440 + i*0x44`），所以要求**队列项的开头就是内联字符串**。

### 154.3 我们的注入错在哪

`inject_load_queue.py` 写的是：

```
queue[0x00..0x04] = name_addr（指向 0x11930000 的字符串）
```

但引擎期望：

```
queue[0x00..] = "common_gametype_mp\0"（内联）
```

→ 引擎把 `0x1D06440` 处的 4 字节指针当作字符串首字节，得到乱码路径，文件自然不存在。

### 修复

`inject_load_queue.py` 改为**把名字直接写进队列项**（`+0x00` 起），flags 仍在 `+0x40`。

## 155. 2026-10-26 18:30–19:00：**内联字符串修复生效 —— 客户端开始加载 gametype 包，但随即崩溃**

### 155.1 修复

`inject_load_queue.py` 改为**把名字内联写进队列项**：

```
entry[+0x00 ..] = "common_gametype_mp\0"   （19 字节）
entry[+0x40]    = flags（0 = 普通路径）
[0x239B11C]     = 1
```

### 155.2 结果

```
inline_bytes = 19, queue_before = 0, written = true
hook_queue_processor patched = true
8s later: alive = False      ← 崩溃
```

→ **注入格式正确**（这次引擎真的去加载了），但加载 `common_gametype_mp` 导致客户端崩溃。

### 155.3 与之前对比

| 版本 | 队列项格式 | 结果 |
|---|---|---|
| v1（指针） | `+0x00 = name_addr` | 消费但不加载（文件名的乱码） |
| v2（内联） | `+0x00 = "common_gametype_mp"` | **真的去加载 → 崩溃** |

→ 说明"队列注入"这条路**格式已对**，剩下的问题是"加载 `common_gametype_mp` 为什么崩"。

### 155.4 可能原因

1. `common_gametype_mp.ff` 与当前 zone 状态冲突（它依赖 pre_gfx/code_post_gfx 的某些 asset）；
2. 加载过程中 asset 注册失败（缺依赖）；
3. flags=0 走的路径与预期不同（例如需要 flags=1 的 patch 语义）。

### 下一步

1. 用 `--flags 1` 再试（patch 路径，可能会找 `patch_common_gametype_mp.ff` 并回退）；
2. 检查崩溃地址（launch 的 `exit_va` 或 events）；
3. 若确定是"资源依赖"，考虑把 `common_gametype_mp` 的依赖也一起注入（转到 asset 合并路线）。

## 156. 2026-10-26 19:00–19:30：**flags=1 也崩，崩溃点定位到 0x7EF0DA（hook 返回后的第 5 字节）**

### 156.1 结果

```
inject --flags 1 → written=true
hook → patched=true
8s: alive=False
stop_reason = "unhandled_exception"
崩溃地址 = 0x7EF0DA（异常 c0000005，tid 与 hook 相同）
```

### 156.2 崩溃点在 hook 的"重放区之后"

```
0x7EF0D0  55              push ebp        ← 被 hook 覆盖的 5 字节
0x7EF0D1  8B EC           mov ebp,esp
0x7EF0D3  83 EC 14        sub esp,0x14
0x7EF0D6  A1 ...          mov eax,[0x849BA34]
0x7EF0DB  3B 05 ...       cmp eax,[0x849BA30]   ← 崩溃在 0x7EF0DA（此指令内）
```

→ cave 执行完（`pushad` + `call 0x49F280` + `popad` + 重放 5 字节 + `jmp 0x7EF0D5`）后，
原函数继续跑到 `0x7EF0DA` 就访问冲突。

### 156.3 推断

`popad` 已恢复全部寄存器与 `esp`，重放 5 字节也在**原栈**上进行，所以栈帧是对的。
最可能的原因：`0x49F280` 内部**破坏了一个全局状态**（例如 `[0x849BA30]`/`[0x849BA34]`
这对"帧计数器"，或 `0x49ED40` 失败后留下的错误状态），导致原函数的后续代码解引用失效。

### 下一步

1. 只在 `[0x239B11C] != 0` 时才调用 `0x49F280`（cave 里加判断），避免无谓地在每帧调用它；
2. 或者干脆**不 hook 每帧函数**，改成 hook 一次（如 `0x77F8B8` Engine init returned 之后）；
3. 若仍崩，说明 `0x49F280` 本身不适用于"非加载循环"上下文，需要换触发点。

## 157. 2026-10-26 19:30–20:00：**只装 hook（队列为空）就崩 —— hook 点本身有问题**

### 157.1 分步验证

```
1) launch + login → table=1135
2) 只安装 hook（不注入队列）→ 3 秒后 alive=False
   "hook alone crashed it"
```

→ **崩溃与 `0x49F280` 无关**：仅仅是 `0x7EF0D0` 处的 5 字节 jmp 就足以让客户端崩溃。

### 157.2 为什么之前 r137 不崩？

| 版本 | cave 内容 | 结果 |
|---|---|---|
| r137 | `pushad` + `cmp [flag]` + （跳）`call 0x49E160` + `popad` + 重放 | 不崩 |
| r142 | `pushad` + `call 0x49F280` + `popad` + 重放 | 8s 后崩 |
| r153 | `pushad` + `cmp [count],0` + （跳）`call 0x49F280` + `popad` + 重放 | **3s 后崩** |

差别在于**这次 `cmp` 读了 `[0x239B11C]`**——若该地址在早期还未映射，`cmp` 就读到无效页 →
访问冲突。而 r137 的 `cmp` 读的是我们自己分配的可写页（`cave+0x800`），安全。

### 157.3 结论

- cave 里**读引擎全局**（`0x239B11C`）有风险：该页可能还没映射；
- 正确做法：**先注入队列项**（写 `[0x239B11C]` 时页必然可写），**再装 hook**；
- 或者 cave 用 `try/except` 式的保护（做不到），只能调换顺序。

## 158. 2026-10-26 20:00–20:30：先注入再装 hook 仍崩 —— `0x7EF0D0` hook 本身有问题

### 158.1 结果

```
1) 注入队列（同时确认 [0x239B11C] 可读写，值为 0）
2) 再安装 hook（cave=0x40120000）
3) 6 秒后 alive=False
```

→ 换顺序**也没用**，说明不是"读未映射页"的问题。

### 158.2 与 r137 的差异

| 实验 | cave | 结果 |
|---|---|---|
| r137 | 52 字节（cmp flag + call 0x49E160 + popad + 重放） | 不崩（但表没变） |
| r142 | 16 字节（call 0x49F280 + popad + 重放） | 8s 崩 |
| r154 | 26 字节（cmp count + je + call 0x49F280 + popad + 重放） | 6s 崩 |

→ **r137 那次不崩的原因可能是"cave 里的 call 被 flag 跳过"**（flag=1 时直接跳），
而 r142/r154 都**真的执行了 `call 0x49F280`**。

### 158.3 结论（修正）

- `0x49F280` 在**非加载循环上下文**里被调用 → 崩溃（破坏状态或依赖未就绪）；
- r137 之所以没崩，是因为它的 `call 0x49E160` 实际**没执行**（被 flag 挡住）；
- 所以"hook 本身没问题"，问题在于**`0x49F280` 不能在任何上下文随便调**。

### 下一步

1. 不要再 hook 每帧函数调 `0x49F280`；
2. 改为**只在真实加载阶段触发**（客户端自己进入加载循环时，队列会被处理）——
   即"注入队列"后**什么都不做**，等客户端自己进加载阶段；
3. 或用 `0x49F280` 的**原始调用点** `0x49F369` 做"一次性触发"（通过条件断点式 patch）。

## 159. 2026-10-26 20:30–21:00：**关键对比 —— demo 播放时 `conn+0x5E8 == 0`（不是 3）**

### 159.1 三个状态点

| 场景 | net_state | ui_state | 表 | `conn+0x5E8` |
|---|---|---|---|---|
| 主菜单（未连接） | 0 | 0 | 0 | **0** |
| demo 播放 | **10** | **0** | **1266** | **0** |
| 服务端路径（历史观测） | 8 | **5** | 1136 | **3**（CA_LOADING） |

（`conn` 通过 `[0x331C0C8] ^ 0xD362501F` 取得，本次为 `0x139A283C`。）

### 159.2 结论

- **`[+0x5E8] = 3` 是"服务端路径卡在加载"的直接标志**；
- demo 播放时它**是 0**，且 `ui_state = 0`、地图可见；
- 所以目标判据可以精确化为：**让 `[+0x5E8]` 在服务端路径下也变成 0**（或走到清除它的那条路径）。

### 159.3 下一步（方向正确）

1. 在服务端路径下复读 `[+0x5E8]`，确认确实是 3；
2. 找"谁写 3"（`mov [conn+0x5E8], 3` 的代码）与"谁清 0"；
3. 对比 demo 路径为什么不需要这个字段（可能 demo 走 `CL_PlayDemo` 直接设 state=7 绕过 CA 状态机）。

## 160. 2026-10-26 21:00–21:30：**CA 状态机两端定位（设 3 与清 0）**

### 160.1 `[conn+0x5E8]` 的 6 个写入点

| 地址 | 写入值 | 含义 |
|---|---|---|
| `0xBA3252` | 1 | CA_CONNECTING |
| `0xBA3460` | 0 | 复位 |
| `0xBA3661` | 0 | 复位 |
| **`0xBA3C47`** | **3** | **CA_LOADING** |
| `0xBA3DA3` | 2 | CA_CHALLENGING |
| `0xBA40AA` | 0 | 复位（`0xBA4080` 函数内） |

读取点：`0x598361`、`0xBA44E8`。

### 160.2 设 3 的上下文（0xBA3C47）

```asm
0xBA3C05  push 8
0xBA3C0B  lea eax,[esi+0x5FC]
0xBA3C12  call 0x7B3FE0          ; 某校验/读取
0xBA3C1A  test eax,eax
0xBA3C1C  jne 0xBA3C62           ; 失败分支
0xBA3C1E  lea ebx,[eax+1]        ; ebx = 1
0xBA3C21  cmp [esi+0x644],eax
0xBA3C29  mov ecx,[esi+0x640]
0xBA3C30  call 0x8435D0
0xBA3C3B  mov [esi+0x5EC], ebx   ; +0x5EC = 1
0xBA3C41  mov [esi+0x5F0], ebx   ; +0x5F0 = 1
0xBA3C47  mov [esi+0x5E8], 3     ; ← CA_LOADING
0xBA3C5F  ret 0xC
```

→ 这是一个"**校验成功后进入加载**"的函数（`ret 0xC` 表示 3 个参数）。

### 160.3 清 0 的上下文（0xBA40AA）

```asm
0xBA4080  push ebp / mov ebp,esp / sub esp,0x20
0xBA4092  esi = [ebp+8]
0xBA4097  push edi
0xBA4098  lea eax,[ebx+0x5F4]
0xBA40A0  mov [ebx+0xC8], 1
0xBA40AA  mov [ebx+0x5E8], 0     ; ← 清 0
0xBA40B4  lea edi,[ebx+0x538]
0xBA40BA  mov ecx,0x2C / rep movsd   ; 拷贝 0x2C*4 = 0xB0 字节
0xBA40C2  call 0x6431B0
0xBA40DA  call 0xBA9970
```

→ 这是一个"**重置 + 拷贝状态块**"的函数，进入它就会清 0。

### 160.4 结论

- 服务端路径卡在 3，说明**从未调用 `0xBA4080`**（或调用时条件不满足）；
- 下一步：找 `0xBA4080` 的调用者与触发条件（是"加载完成回调"还是"主动重置"）。

## 161. 2026-10-26 21:30–22:00：**清 0 的触发点 = "设置加载单例（[+0x4F4]）"**

### 161.1 唯一调用链

```
0xBA4080（CA 状态重置）
  ← 唯一调用者 0xB82025
0xB82025 位于函数（入口更早，未定位）内，序列：
  0xB81FEB  ecx = [ebx+0x4F4]       ; 旧加载单例
  0xB81FF5  eax = [ecx] / call edx   ; 释放旧对象
  0xB81FFD  [ebx+0x4F4] = esi        ; ← 设置新加载单例
  0xB82011  ecx = [ebx+0x4F4]
  0xB82017  lea eax,[ebx+0x500]
  0xB8201E  byte [ebx+0x4F8] = 0
  0xB82025  call 0xBA4080            ; ← 重置 CA 状态（清 +0x5E8）
  0xB8202F  call 0xB7F7F0
```

### 161.2 意义

- `[+0x4F4]` 正是 HANDOFF 记录过的"**加载单例**"（`0x8269774 + 0x4F4`）；
- **"设置加载单例"这个动作本身会清 CA 状态（把 +0x5E8 归 0）**；
- 服务端路径卡在 3，说明**从未走到这个设置动作**（或走了但对象/参数不合法）。

### 161.3 下一步

1. 找到 `0xB81FD0` 所在函数的入口（向前扩大扫描）与调用者；
2. 看它接受什么参数（`esi` = 新单例对象），以及服务端路径下是否被调用；
3. 若确实没被调用，说明服务端路径缺"创建加载单例"的步骤 —— 这可能就是 `ui_state=5` 的真正原因。

## 162. 2026-10-26 22:00–22:30：**目标地图定为 mp_crash_tropical（用户决定）+ 找到"开始加载"触发函数 0x7F38C0**

### 162.1 目标地图的决定（用户）

- demo 已验证 `mp_crash_tropical`（坠机之地）能正常加载与渲染；
- 实机目标直接复用该地图，避免"换图导致加载不上"的额外风险；
- 确认：`gamestate-network-ffb56d7e-6411.bin` 的 mapname **本来就是 `mp_crash_tropical`**，
  gametype `war`，与 demo 完全一致。

→ **从现在起，验收目标为 "mp_crash_tropical 可见可玩 + ui_state != 5"**。

### 162.2 "开始加载"的触发函数（0x7F38C0）

```asm
0x7F38CB  eax = [0x84ABB08]        ; auth 源 1
0x7F38D0  test eax,eax
0x7F38D2  jne 0x7F38DD
0x7F38D4  eax = [0x84ABB14]        ; auth 源 3
0x7F38D9  test eax,eax
0x7F38DB  je 0x7F38F7              ; 两者都 0 → eax=0
0x7F38DD  ecx = [0x84ABB0C]        ; auth 源 2
0x7F38E3  test ecx,ecx
0x7F38E5  je 0x7F38EE
0x7F38E7  call 0xB983C0
0x7F38EC  jmp 0x7F38F9
0x7F38EE  ecx = eax
0x7F38F0  call 0xB9A0E0
0x7F38F7  xor eax,eax
0x7F38F9  push 1
0x7F38FB  push eax
0x7F38FC  sub esp,0x88
0x7F3902  lea edx,[ebp-0x90]
0x7F390B  call 0xB75340            ; 构造参数结构
0x7F3910  ecx = esi
0x7F3912  call 0xB82070            ; ← 开始加载
0x7F3919  test al,al
0x7F391B  setne cl
0x7F391E  [0x84ABA7C] = ecx        ; 记录成功标志
```

### 162.3 与 HANDOFF 的 auth_sources 对上了

HANDOFF 记录：`auth_sources: {'0x84abb08': '0x0', '0x84abb0c': '0x0', '0x84abb14': '0x2462bce0'}`

→ 当时 `[0x84ABB14] != 0`，所以走 `0x7F38EE`（`call 0xB9A0E0`）分支，
**理论上应该会继续到 `0x7F3912 call 0xB82070`**。

### 下一步

1. 找 `0x7F38C0` 的函数入口与调用者（谁触发"开始加载"）；
2. 在服务端路径实测：`0x7F38C0` 是否被调用？`0x84ABA7C`（成功标志）是否被置 1？
3. 若没被调用，说明缺"触发开始加载"的事件（可能是某个 gamestate 命令或 ui 动作）。

## 163. 2026-10-26 22:30–23:00：**"开始加载"（0x7F3890）的唯一调用点不可达 —— 服务端路径可能从未触发地图加载**

### 163.1 分派结构（0x7F3830）

```asm
0x7F3836  ecx = esi
0x7F3838  call 0xB7A670            ; 查询某状态
0x7F383D  cmp eax, 4
0x7F3840  ja 0x7F3870
0x7F3842  jmp [eax*4 + 0x7F3878]   ; 跳转表
0x7F3849  mov [0x84ABA7C], 0       ; case 0/3/4 → 清 0
0x7F385A  mov [0x84ABA7C], 2       ; case 2 → 设 2
0x7F386B  call 0x7F3890            ; ← 开始加载（唯一调用点）
0x7F3870  mov eax,[0x84ABA7C]      ; default → 返回当前
```

跳转表（`0x7F3878`，5 项）：

```
case 0 -> 0x7F3849（清 0）
case 1 -> 0x7F3870（返回）
case 2 -> 0x7F385A（设 2）
case 3 -> 0x7F3849（清 0）
case 4 -> 0x7F3849（清 0）
```

### 163.2 关键问题：`0x7F386B` 不可达

```
refs to 0x7F386B: 0
```

- 跳转表里 **case 1 指向 `0x7F3870`**，不是 `0x7F386B`；
- `0x7F386B` 前面 `0x7F386A` 是 `ret`（`0x7F385A` 分支的返回）；
- 所以 `0x7F386B call 0x7F3890` **没有任何路径能执行到**。

→ 这是"**死代码**"还是"**跳转表被改过**"？无论哪种，
**按当前二进制，`0x7F3890`（开始地图加载）永远不会被调用**。

### 163.3 意义

- 如果这条调用链确实不可达，那么**服务端路径（非 demo）从来不会主动"开始加载地图"**；
- 这与"`ui_state=5` 卡在 CA_LOADING、`[+0x5E8]=3` 一直不清"完全吻合；
- demo 能加载，是因为 `CL_PlayDemo` 走了**另一条路**（`0x813C20` 内部直接设 state=7）。

### 下一步

1. 在服务端路径下断点/trace 确认 `0x7F3890` 是否被执行（预期：不执行）；
2. 若确认不执行，则"补 88 个武器"根本不是问题所在——**缺的是"触发开始加载"**；
3. 修法：把 `0x7F3842` 的跳转表 case 1 指向 `0x7F386B`（让状态 1 时真的开始加载），
   或用其它方式让 `0x7F3890` 被调用。

## 164. 2026-10-26 23:00–23:30：实测 —— connect 后 `conn+0x5E8 = 0`（不是 3），`load_status = 2`

### 164.1 数据

**login 后（connect 前）**：

```
[0x84ABA7C] load_status = 2
[0x84ABB08] = 0x0
[0x84ABB0C] = 0x0
[0x84ABB14] = 0x246A4ED0   （非 0）
ui = 5   state = 0
```

**connect 后（state=4）**：

```
[0x84ABA7C] load_status = 2   （未变）
[0x84ABB08/0C/14] = 0x0 / 0x0 / 0x246A4ED0
ui = 5   state = 4
conn+0x5E8 = 0                ← 不是 3！
```

### 164.2 两个修正

1. **`conn+0x5E8` 在 connect 后是 0**（不是 3）—— 之前记录的"3"是**某个时刻**（很可能是 gamestate 处理中）的观测；
2. **`[0x84ABA7C]`（load_status）已经是 2**，不是 0 或 1 —— 说明"加载状态机"并不在起始态。

### 164.3 意义

- `ui = 5` 与 `conn+0x5E8` **没有直接关系**（后者是 0）；
- 真正卡住 `ui_state = 5` 的原因在别处（可能是 UI 层的"等待加载完成"标志）；
- 下一步必须**在 state 7/8（gamestate 处理）时刻**再读这些值，才能对上"卡在 CA_LOADING"的描述。

### 下一步

1. 在 `state` 从 4 → 5 → 7 → 8 的每个阶段采样 `[0x84ABA7C]`、`conn+0x5E8`、`ui`；
2. 找出"`ui` 从 5 变成别的值"的条件（或它为什么一直保持 5）。

## 165. 2026-10-26 23:30–00:00：分阶段采样 —— net 卡在 4，原因是 forward 启动顺序错误

### 165.1 采样结果

```
t=0.00  net=0  ui=5  load=2  table=1135  conn_5E8=0  conn_640=0
t=1.12  net=4  ui=5  load=2  table=1135  conn_5E8=0  conn_640=0
（之后 30 秒无变化）
```

→ `net` 只到 **4**（CONNECTING）就停住，`ui`/`load`/`conn_5E8` 全程不变。

### 165.2 根因：forward 没起来

```
gs 日志：只有 ('meta','start')，没收到任何包
fwd.err："codol1649370-offline.exe 未运行"
```

→ 我在**客户端启动之前**就启动了 `ring_bridge forward`，它启动时检查客户端进程，
发现不存在 → 直接退出。所以客户端 connect 到 `29000` 没人接，`net` 卡在 4。

### 165.3 修正

启动顺序必须是：

```
launch 客户端 → login → 启动 forward（此时客户端已运行）→ connect → pump
```

### 下一步

按正确顺序重跑分阶段采样，拿到 net 0→4→5→7→8 全过程的字段变化。

## 166. 2026-10-27 00:00–00:30：**完整时间线 —— 协议全通、net 到 7，但客户端在 gamestate 处理时崩溃**

### 166.1 采样时间线（r159，forward 正常）

```
t=0.00   net=0  ui=5  load=2  table=1135  conn_5E8=0
t=1.10   net=4  ui=5  load=2  table=1135  conn_5E8=0   ← connect 发出
t=25.30  net=5  ui=5  load=2  table=1135  conn_5E8=0
t=26.10  net=7  ui=5  load=2  table=1135  conn_5E8=0   ← 越过 inband 门槛
t=26.21  （全部 null）                                  ← 客户端崩溃
```

### 166.2 服务端日志（协议正常）

```
in inband 14 / in connect 1 / in stats 1 / out oob 4 / gamestate_source 1
```

→ connect → stats → gamestate 全部走通。

### 166.3 两个关键认识（修正之前的判断）

1. **`ui_state = 5` 从"登录后"就一直是 5**（net=0 时就是 5），
   不是"gamestate 处理失败导致的" —— `ui=5` 是**加载屏的初始状态**，
   需要某个事件把它推进；
2. **`net=7` 后客户端直接崩溃**（`unhandled_exception`），
   而不是像 r105 那样"弹 181 后回大厅"。

→ 两次实验（run_match 与手动流程）在 gamestate 处理阶段出现了**不同表现**
（弹窗 vs 崩溃），说明该阶段的状态很敏感，可能取决于传输细节（分片/时序）。

### 下一步

1. 从 events 里取崩溃地址（`exit_va=0x6193C8` 只是退出点）；
2. 对比 r105（弹 181）与 r159（崩溃）的差异（gamestate 分包方式/时序）；
3. 确认 `ui=5` 的推进条件（哪个事件会把 ui 从 5 变成别的值）。

## 167. 2026-10-27 00:30–01:00：**`ui=5` 的完整条件链（加载单例 → 状态查询 → UI 切换）**

### 167.1 UI 状态切换（0x8037D1）

```asm
0x8037BF  call 0xB7A670            ; 查状态
0x8037C9  esi = eax
0x8037D1  eax = [0x84ABA50]        ; 当前 ui_state
0x8037D6  cmp esi, 2
0x8037D9  je 0x8037FA              ; 状态==2 → 走 5 分支
0x8037DB  test eax, eax
0x8037DD  je 0x8037A9              ; 已是 0 → 返回
0x8037DF  [0x84ABA54] = eax
0x8037E4  [0x84ABA50] = 0          ; ← 回主菜单
0x8037EE  [0xE4EA3C] = 0xDE16F0    ; UI 脚本 A

0x8037FA  cmp eax, 5
0x8037FD  je 0x803818
0x8037FF  [0x84ABA54] = eax
0x803804  [0x84ABA50] = 5          ; ← 进加载屏
0x80380E  [0xE4EA3C] = 0xDE170C    ; UI 脚本 B
```

→ **`0xB7A670` 返回 2 → ui=5；返回非 2 → ui=0**。

### 167.2 状态查询（0xB7A670）

```asm
0xB7A673  ecx = [esi+0x4F4]        ; 加载单例
0xB7A679  test ecx, ecx
0xB7A67B  jne 0xB7A681
0xB7A67D  eax = 0                  ; ← 单例为 NULL → 返回 0
0xB7A680  ret

0xB7A681  call 0xBA0780            ; 查加载器状态
0xB7A686  cmp byte [esi+0x4F8], 0
0xB7A68D  jne 0xB7A699
0xB7A68F  cmp eax, 2
0xB7A692  jne 0xB7A699
0xB7A694  eax = 1                  ; 加载器==2 且 [+0x4F8]==0 → 返回 1
0xB7A699  ret
```

### 167.3 条件链总结

```
ui = 5  ⇔  [+0x4F4] != NULL  ∧  0xBA0780() == 2  ∧  ([+0x4F8] != 0 ∨ 0xBA0780() != 2 → 保持 2)
ui = 0  ⇔  [+0x4F4] == NULL  ∨  0xBA0780() != 2
```

→ **`[+0x4F4]`（加载单例）是 ui 状态的总开关**：
- 为 NULL → 回主菜单（ui=0）；
- 非 NULL 且加载器状态为 2 → 加载屏（ui=5）。

### 下一步

实测 demo 与服务端路径下 `[+0x4F4]` 与 `0xBA0780()` 的返回值，确认差异。

## 168. 2026-10-27 01:00–01:30：**条件链验证 —— demo 播放时 `[+0x4F4] == 0`（NULL）→ ui=0**

### 168.1 实测

| 场景 | `[0x8269774]`（holder） | `holder+0x4F4` | ui | load | state |
|---|---|---|---|---|---|
| 主菜单 | 读不到（None） | — | 0 | 0 | 1 |
| demo 播放 | `0x5211AA38` | **0（NULL）** | **0** | 0 | 10 |

### 168.2 与推导一致

按 §167 的条件链：

```
ui = 0  ⇔  [+0x4F4] == NULL  ∨  0xBA0780() != 2
```

demo 播放时 `[+0x4F4] = NULL` → `0xB7A670` 返回 0 → `ui=0` ✅ **完全吻合**。

### 168.3 推论

如果服务端路径 `ui=5`，那么按同一条件链，必然是：

```
[+0x4F4] != NULL  ∧  0xBA0780() == 2
```

→ 服务端路径下**加载单例被创建了**（而 demo 路径没有）。

### 下一步

实测服务端路径的 `holder+0x4F4`，确认它非 NULL，并进一步查它为什么被创建/没被销毁。

## 169. 2026-10-27 01:30–02:00：**🎯 决定性验证 —— 服务端路径 `[+0x4F4]` 非 NULL（0x4EE184A8），ui=5；登录后即创建**

### 169.1 两端对照（条件链闭环）

| 路径 | `holder+0x4F4` | `0xBA0780()` | ui | 结论 |
|---|---|---|---|---|
| demo 播放 | **0（NULL）** | — | **0** | 回主菜单 ✅ |
| 服务端路径 | **0x4EE184A8（非 NULL）** | 2（推断，因 ui=5） | **5** | 进加载屏 ✅ |

→ §167 推导的 `ui=5 ⇔ [+0x4F4]!=NULL ∧ 0xBA0780()==2` **两端都验证成立**。

### 169.2 关键时序

```
before connect (login 后):  holder=0x4EE16E40  +0x4F4=0x4EE184A8  ui=5  load=2  state=0
t+2s (connect 后, state4):  同上（完全没变）
t+9s:                       同上
```

→ **加载单例在 login 阶段就被创建了**（state=0 时 `[+0x4F4]` 已非 NULL，ui 已 5），
不是 connect 之后才创建的。

### 169.3 完整因果链（现在自洽）

```
登录流程 → 触发"开始加载"（0xB82070 → 0xB81EF0）
        → 创建加载单例 [holder+0x4F4] != NULL
        → ui 切到 5（加载屏，UI 脚本 0xDE170C）
        → 等待加载完成（0xBA0780 状态从 2 变成别的）
        → 服务端路径：gamestate 处理阶段崩溃/失败 → 状态永远停在 2
        → ui 永远 5（黑屏转圈）
```

### 169.4 下一步（关键判断点）

**服务端路径的加载在"等待完成"这一步失败**：
1. 需要 `0xBA0780()` 从 2 变成"完成"值；
2. 该值由加载器在"加载完成"时设置；
3. gamestate 崩溃可能正是让加载器停在 2 的原因。

→ 下一步：查 `0xBA0780` 返回值的来源（加载器状态字段），确认"完成"是哪个值、
以及 gamestate 崩溃如何阻止它被设置。

## 170. 2026-10-27 02:00–02:30：**`0xBA0780` 的完整逻辑 —— ui=5 的最终判据是 `[+0x5E8]==3`（或 `[+0x644]!=0`）**

### 170.1 反汇编

```asm
0xBA0780  cmp dword [ecx+0x644], 0
0xBA0787  eax = [ecx+0xC8]           ; 加载器状态
0xBA078D  je 0xBA079F                 ; [0x644]==0 → 走下面
0xBA078F  cmp eax, 2
0xBA0792  je 0xBA0799                 ; eax==2 → 返回 2
0xBA0794  cmp eax, 1
0xBA0797  jne 0xBA07B1                ; eax!=1 → 返回 eax
0xBA0799  eax = 2 / ret               ; eax==1 或 2 → 返回 2

0xBA079F  cmp eax, 2
0xBA07A2  jne 0xBA07B1                ; eax!=2 → 返回 eax
0xBA07A4  eax = 0
0xBA07A6  cmp dword [ecx+0x5E8], 3
0xBA07AD  sete al
0xBA07B0  inc eax                     ; eax = (5E8==3 ? 1 : 0) + 1
0xBA07B1  ret
```

### 170.2 两条路径

**A. `[+0x644] != 0`**：
```
[+0xC8] ∈ {1,2} → 返回 2（加载屏）
[+0xC8] 其它    → 返回 [+0xC8]
```

**B. `[+0x644] == 0`**：
```
[+0xC8] != 2 → 返回 [+0xC8]
[+0xC8] == 2 → 返回 (5E8==3 ? 2 : 1)
```

### 170.3 与实测的对照（需澄清）

- 我们实测：`[+0x5E8] = 0`、`ui = 5`、`load = 2`；
- 若走路径 B（`[+0x644]==0`）：`5E8==0` → 返回 **1** → `ui` 应为 **0**（不是 5）；
- 但实际 `ui=5` → 说明**走的是路径 A**（`[+0x644] != 0`），且 `[+0xC8] ∈ {1,2}`。

→ 所以 `[+0x644]` 和 `[+0xC8]` 才是关键；`[+0x5E8]` 只在路径 B 起作用。

### 下一步

实测 `[conn+0x644]` 与 `[conn+0xC8]`，确认走哪条路径。

## 171. 2026-10-27 02:30–03:00：**实测与推导矛盾 —— 按代码 ui 应被设 0，实际是 5**

### 171.1 实测

| 时刻 | `+0xC8` | `+0x644` | `+0x640` | `+0x5E8` | ui | load | state |
|---|---|---|---|---|---|---|---|
| 登录前（主菜单） | 0 | 0 | 0 | 0 | 0 | — | 1 |
| **登录后** | **0** | **0** | **0** | **0** | **5** | **2** | 0 |

`holder = 0x4D23BA80`、`+0x4F4 = 0x4D1BCF28`（非 NULL）

### 171.2 按代码推导

```
0xBA0780:  [+0x644]==0 → 路径B；[+0xC8]==0 (!=2) → 返回 0
0xB7A670:  [+0x4F4]!=NULL → call 0xBA0780 → eax=0
           cmp [esi+0x4F8],0 ; cmp eax,2 (0!=2) → 不设 1
           → 返回 0
0x8037D6:  cmp esi,2 (0!=2) → 走 0x8037DB
0x8037DB:  test eax,eax   (eax = [0x84ABA50] = 5, 非0)
           → [0x84ABA54]=5 → [0x84ABA50]=0     ← 应回主菜单！
```

### 171.3 矛盾

- 推导：`ui` 应被设成 **0**；
- 实测：`ui = 5`（没变）。

→ 说明 **`0x8037B0`（UI 状态切换函数）此刻没有被调用**，
`ui=5` 是**更早**（登录流程中）设置的，且之后没有代码把它改回来。

### 下一步

1. 找 `0x8037B0` 的调用者与调用频率（是否每帧/是否在 UI 更新时）；
2. 若它确实不常调用，那 `ui=5` 就是"设置后没人清"——需要找到"应该清它的那条路径"；
3. 结合 `load=2`（`[0x84ABA7C]`）：说明状态机认为"还在加载"，所以不清 ui。

## 172. 2026-10-27 03:00–03:30：**找到"跳过 UI 更新"的开关 —— `[0x849B5B0]`**

### 172.1 调用链

```
0x7EEBF0  （每帧/主循环函数）
0x7EEBF3  cmp dword [0x849B5B0], 0
0x7EEBFC  jne 0x7EED7D            ; ← 非 0 就跳过！
0x7EEC02  call 0x803400            ; ← UI 状态更新（含 ui 0/5 切换）
0x7EEC07  call 0x63A4D0
0x7EEC0C  call 0x4A2030
...
```

而 `0x803400` 内部（§167）在 `0x8037D1` 处读 `ui_state`、调 `0xB7A670`、按结果写 0 或 5。

### 172.2 这解释了矛盾

- 实测：`[+0xC8]=0`、`[+0x644]=0`、`[0x84ABA50]=5`；
- 按 `0x803400` 的逻辑，一旦执行就应该把 ui 写成 0；
- 但实测没变 → **`[0x849B5B0] != 0`，`0x803400` 根本没被调用**。

### 172.3 `[0x849B5B0]` 可能是什么

- 名字未知，位置在 `.data`（`0x849B5B0`）；
- 语义上像"**正在加载 / 暂停 UI 更新**"的开关；
- 若登录流程把它置 1 且从未清 0，UI 就会**永久停在加载屏**（ui=5）——
  这与"黑屏转圈"的现象完全吻合。

### 下一步

1. 实测 `[0x849B5B0]` 在登录前后/connect 前后的值；
2. 找它的写入点（谁置 1、谁清 0）。
