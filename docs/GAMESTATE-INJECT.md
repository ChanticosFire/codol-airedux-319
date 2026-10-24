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
