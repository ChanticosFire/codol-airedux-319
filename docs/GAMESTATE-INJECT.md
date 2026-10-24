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
