# CODOL 1649370 自建服务端 — 交接文档（给 codex）

> **2026-10-23 续进度（优先于下文旧假设）**：✅已验证：1649370 客户端识别的 OOB 命令是单数 `statResponse`，自建服已从 `statsResponse` 改正；实测客户端 state 4→7，收到 3 片 gamestate 后发 `gamestateupdate 1`，随后 `Com_Error(EXE_POSSIBLECONFIGSTRINGMISMATCH)` 并回 state 0。`stage=5`、`messageAck=1`，尚未达成进图判据。✅已验证（静态）：`connection+0x34` 在 OOB 重试路径自增，不是原先猜测的 incomingSequence。⚠️推断：当前 2697 来源 gamestate 的配置字符串不符合 1649370。❌未知：具体失配字段。下一步 instrument `0x4731B0` 的参数与 `[0x77D8240]`。实验复用 `20261023-codex-delay-a2/runtime`，不再生成完整运行副本。证据见 [本轮 JSON](evidence/experiments/20261023-codex-statresponse-state7.json)。

> 生成时间：2026-10-23 · 基于 100 轮长程工作
> 目标版本：**CODOL 3.19.26.22 / Build 1649370**（关服最后版本）
> 目标：**自建 `server1649370`**，让 1649370 客户端完成握手 → 进入真实地图 `mp_cross_fire` 并交互 → 对局可结束 → 返回大厅。
> 红线：**不依赖 2697 dedrun 作为最终运行环境**（它只作协议参考/抓包来源）。

---

## 1. 结论速览（先看这个）

| 项 | 状态 |
|---|---|
| 客户端启动、登录、进大厅 | ✅ |
| 自建认证/大厅（LSG） | ✅ |
| 自建游戏服握手（getchallenge/connect/stats） | ✅ |
| challenge 被客户端真正采用 | ✅ 已内存验证 |
| 2697 gamestate 完整解密/重组（3426 字节） | ✅ |
| 分片格式、密钥、加密 | ✅ 逐字节验证与参考一致 |
| 我们发出分片的投递与消费 | ✅ 环 B read == write |
| **客户端接受 gamestate（离开大厅/进图）** | ❌ **卡在这里** |

**唯一阻塞**：客户端把我们的 gamestate 分片**读走了但不接受**（`stage` 停在 5，`messageAck` 停在 1）。

---

## 2. 目录与关键文件

```
E:\GAME\COD\codol-airedux\319\
├─ runtime\client-1649370\          工作客户端（源: E:\GAME\COD\使命召唤OL，2445 文件）
├─ server319\                       自建认证/大厅（LSG，端口 28969）
├─ server1649370\gameserver.py      自建游戏服（端口 28971）★核心
├─ tools\
│  ├─ ring_bridge_1649370.py        ★客户端内存桥（status/connect/forward/start-challenge/patch-bytes）
│  ├─ launch_1649370.py             启动客户端
│  ├─ drive_login_state_machine.py  驱动登录
│  ├─ install_refresh_hook.py       安装刷新钩子
│  ├─ reassemble_2697_gamestate.py  ★分片重组工具（格式权威来源）
│  └─ read_dedrun_client.py         2697 客户端内存读取
├─ runs\
│  ├─ final-in.jsonl                5533 个真实出站数据报（解密素材）
│  ├─ gamestate-3426.bin            ★完整 gamestate 明文（3 分片重组）
│  └─ 2697-server-test\             2697 dedrun（仅参考）
└─ evidence\experiments\            每轮证据 JSON（按日期命名）
```

客户端关键地址（每次会话可能变，需实时读）：

| 名称 | 值/获取方式 |
|---|---|
| 客户端 exe SHA-256 | `36997674B18F2896DE5E9D755686F6922AF10708F355175714058D0A0172B537` |
| 进程名 | `codol1649370-offline.exe` |
| 游戏连接对象 | `ring_bridge status` 的 `connection` 字段 |
| 入站序号 | **`connection + 0x34`**（实测值 1） |
| 对端地址结构 | **`connection + 0x14`**：`{int32 type=2; ip[4]; u16 port}` |
| `address_string` | `connect --address` 写入（实测变 `"localhost"`） |

---

## 3. 协议事实（全部已验证）

### 3.1 数据报分片格式（权威：`tools/reassemble_2697_gamestate.py`）

```
u32  sequence | 0x80000000        (小端，bit31 = FRAGMENT_BIT)
u8   index                        (0 .. count-1)
u8   count - 1
u16  stride                       (小端，实测 1162)
u16  chunk                        (小端，本片数据字节数)
byte data[chunk]                  (XOR 编码)
```

- **前 10 字节头不加密**；
- **`data` 用 `key = (challenge ^ sequence) & 0xFF` 逐字节 XOR**；
- **特例：`index == 0` 时 `data[:4]` 不加密**。

### 3.2 参考轨迹（来自 `runs/final-in.jsonl`）

```
seq=3 : 3 分片 (1162 + 1162 + 1102 = 3426 字节) —— gamestate
seq=5..14 : 各 10 分片 —— 快照
之后 : 13~15 分片
```

- **同一消息的所有分片共享同一个 `seq`**，只有 `index` 不同；
- 参考流最小序号是 **3**（1、2 属于 OOB 握手阶段）。

### 3.3 gamestate 明文结构（`runs/gamestate-3426.bin`）

```
00000000 | 03 00 00 00 00 | mp_cross_fire\0 | mp\0
| \g_gametype\war\mapname\mp_cross_fire\2485\12\2492\CODOL 2.6.9.7 Local Server\2482\2
| cod / 1537 / @0.0 / 619800 / 3231 -2496 10 ...
| rank_majgen1 / rank_ltgen1 / specialty_emergency_airdrop_crate ...
| 尾部 '_' 与 '.A.'（疑似 EOF）
```

### 3.4 握手与 OOB

```
getchallenge              -> challengeResponse <challenge>
connect (410B, userinfo)  -> connectResponse
stats (84B)               -> statsResponse <challenge>   ← 必须回显 challenge，不能回 0
inband (206B, 空 ACK)     -> 客户端心跳，messageAck=1
```

客户端 `connect` 关键字段实测：`name` 为 base64、`2490 = -695030357`、`challenge` 回显、`statver "19 1248641861"`、`uid 0cf7ee44e08c4c28`。

### 3.5 客户端 → 服务端的 in-band 头是明文

`seq(4) + serverId(1) + messageAck(4) + body`，`serverId` 恒 0，`messageAck` 恒 1。

---

## 4. 实现方式

### 4.1 自建游戏服（`server1649370/gameserver.py`）

- 单文件 UDP 服务，默认端口 **28971**，日志 JSONL（每包一行，`runs/*.jsonl`）；
- 处理 OOB：`getchallenge` / `connect` / `stats`（`statsResponse` 已改为回显 challenge）；
- 处理 in-band：解析 `seq/serverId/messageAck/body`；
- **出站 gamestate**：读取 `runs/gamestate-3426.bin`，切成 3 个 1162 字节分片，按 3.1 格式发出，**同一消息共享一个 seq**。

### 4.2 客户端内存桥（`tools/ring_bridge_1649370.py`）

子命令：

| 命令 | 作用 |
|---|---|
| `status` | 读客户端状态：`stage/state/connection/ring_b/ring_a/address_string/connection_adr` |
| `connect --address <ip:port>` | 让客户端认定对端地址（写入 `address_string`） |
| `forward --target <ip:port> --dump-in <file>` | **核心**：把客户端出站转发到服务端，把服务端回包注入客户端入站环 |
| `start-challenge` | 武装 challenge（**注意：它本身不触发服务端发送**） |
| `ring-a-drain block` | 清空客户端出站环 |
| `patch-bytes` | 直接改客户端内存 |

**投递验证**：`status` 的 `ring_b {read,write}` —— **两者相等即证明客户端读走了我们的包**。

### 4.3 一轮标准实验流程

```powershell
# 1. 起服务
python -m server319.lsg --cert runs/20261020-live-derived01/tls/auth.crt `
  --key runs/20261020-live-derived01/tls/auth.key --port 28969 --log runs/x-lsg.jsonl `
  --seconds 480 --allow-auth-tls
python -m server1649370.gameserver --port 28971 --log runs/x-gs.jsonl

# 2. 起客户端
python tools\launch_1649370.py --full --seconds 380 --local-profile `
  --loopback-tcp-guard --local-auth-lsg --name 20261023-x

# 3. 驱动登录到大厅（ui_state=5）
python tools\drive_login_state_machine.py --set-ui-state 1 --ticks 40 --interval 0.4 `
  --output runs\x-login.json

# 4. 桥接
python tools\ring_bridge_1649370.py --output runs\x-drain.json ring-a-drain block
python tools\install_refresh_hook.py --install
python tools\ring_bridge_1649370.py --output runs\x-connect.json connect --address 127.0.0.1:29000 --settle 2
python tools\ring_bridge_1649370.py --output runs\x-forward.json forward --target 127.0.0.1:28971 `
  --seconds 20 --adr-type 2 --fake-stats --keepalive --bind-port 29000 `
  --reliable-until-state 0 --max-events 150

# 5. 观察
python tools\ring_bridge_1649370.py --output runs\x-status.json status
Select-String -Path runs\x-gs.jsonl -Pattern '"kind": "fragment"'
```

**操作纪律**（血泪教训）：
- **必须 `--reliable-until-state 0`**，否则桥会把我们的包当快照丢掉；
- **每轮前后清理**：`ring_bridge` / `server319.lsg` / `server1649370.gameserver` / `codol1649370-offline`；
- 结束跑 `pwsh -NoProfile -File tools\net_rollback.ps1`；
- **`forward` 的统计文件只在正常退出时写**，别提前 kill；
- **一次只开一个客户端会话**，避免残留 forward 污染实验。

---

## 5. 已排除的假设（不要再重复试）

以下全部**已验证不是原因**：

1. 分片头布局（`seq/index/count/stride/chunk`）；
2. 分片数量与 `chunk` 大小；
3. 分片共享 `seq`；
4. 起始 `seq` 值（我们与参考同为 3）；
5. 密钥推导（`challenge ^ seq`）——**客户端内存里确实有我们签发的 challenge**；
6. 加密应用——**三个分片重加密结果与参考密文逐字节相同**；
7. payload 内容——**3426 字节逐字节还原**；
8. `statsResponse` 内容（已修为回显 challenge，仍不 ack）；
9. 对端地址（`address_string` 已置 `localhost`，仍不 ack）；
10. 传输与消费（`ring_b read == write`，多轮均成立）。

---

## 6. 卡点（当前唯一）

### 6.1 现象

- 服务端发出 3 个分片（`seq=3`, index 0/1/2）；
- 桥注入成功，**客户端环 B `read == write`**（读了）；
- **`stage` 仍 5（大厅）**，**`messageAck` 仍 1**。

### 6.2 最强剩余假设

**客户端在解析 payload 之前，先按 `incomingSequence` 做乱序判定并丢弃。**

**依据**：
- 两次独立的「已填充连接对象」读取中，**`connection + 0x34 == 1`**；
- 若该字段是 `incomingSequence`，**客户端期待的下一个服务端序号是 2**；
- **我们发的是 3** → 直接丢弃，与 payload 是否正确无关。

### 6.3 顺序悖论（为什么之前的实验没做成）

- **gamestate 只在 `forward` 触达服务端时才发出**；
- 但 **`forward` 自己会重连，把我们先前 patch 的 `conn+0x34` 冲掉**；
- **`start-challenge` 只「武装 challenge」，不触发发送**；
- 结果：**patch 在发送之前 → 被冲掉；patch 在发送之后 → 已经晚了**。

---

## 7. 下一步实验（按优先级）

### 方案 A（推荐）：服务端延迟发送 + 发送前 patch

给 `server1649370` 加一个 `--delay-send N`：收到 `connect` 后**等 N 秒**再发 gamestate。

```powershell
# 1. 服务端带延迟
python -m server1649370.gameserver --port 28971 --log runs/a-gs.jsonl --delay-send 8

# 2. 起客户端 → 登录 → 桥接
# ...（同第 4 节步骤 2~4，forward 保持运行）

# 3. forward 运行期间，立刻 patch 序号
python - <<'PY'
# 读 status 拿 connection；写 int32 2 到 connection+0x34
PY

# 4. 等延迟到点，观察
python tools\ring_bridge_1649370.py --output runs\a-status.json status
```

**判据**：
- **`stage` 离开 5** 或 **`messageAck` > 1** → **根因确认**；
- 仍无变化 → 序号假设排除，转向「可靠命令层 / 状态机前置」。

### 方案 B：服务端连发两遍

第一遍在错误序号下被丢，**第二遍（patch 之后）到达**。改动最小，不需要精确时序。

### 方案 C：反向对齐（改服务端）

用**专用字段**强制 gamestate 序号（不要复用会自增的计数器）：

```python
self.gamestate_seq = getattr(self, "gamestate_seq", 1) + 1   # 首次 = 2
seq_word = (self.gamestate_seq | 0x80000000) & 0xFFFFFFFF
```

**注意**：`getattr(self, "server_seq", 1)` 这种写法**无效**——属性已存在时默认值不生效（第 98 轮踩过）。

---

## 8. 如果序号假设被排除，下一个方向

1. **可靠命令层**：客户端可能要求先收到一条**非分片**的可靠消息（`opcode(1) + seq(4) + NUL 文本`），才启用分片接收；
2. **状态机前置**：客户端在 `stage=5` 时可能还在等某个它自己发起、而我们未应答的请求；
3. **instrument 客户端接收函数**：直接看它对我们数据报是否执行了解码（最彻底，成本最高）。

---

## 9. 证据索引（按主题）

| 主题 | 文件 |
|---|---|
| 分片格式权威 | `tools/reassemble_2697_gamestate.py` |
| 完整 gamestate 重组 | `evidence/experiments/20261023-codex-gamestate-3426.json` |
| 加密逐字节验证 | `evidence/experiments/20261023-codex-encrypt-verified.json` |
| challenge 被采用 | `evidence/experiments/20261023-codex-challenge-adopted.json` |
| 投递与消费计数 | `evidence/experiments/20261023-codex-bridge-counters.json` |
| 地址假设排除 | `evidence/experiments/20261023-codex-address-excluded.json` |
| 入站序号发现 | `evidence/experiments/20261023-codex-inseq-found.json` |
| 序号 patch 与顺序问题 | `evidence/experiments/20261023-codex-inseq-patched.json` |
| 最后一轮（顺序悖论） | `evidence/experiments/20261023-codex-final2-challenge-armed.json` |

---

## 10. 交接要点（给 codex 的三句话）

1. **不要重新逆向协议**——分片格式、密钥、加密、payload 全部已验证，直接复用 `runs/gamestate-3426.bin` 与第 3 节；
2. **不要重复试第 5 节列出的 10 个假设**，它们都已被证伪；
3. **只做第 7 节的方案 A/B/C**——核心是「**让 patch 生效的时机早于 gamestate 到达**」，判据只看 `stage` 是否离开 5、`messageAck` 是否超过 1。
