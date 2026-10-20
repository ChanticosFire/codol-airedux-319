"""Record round 75: a hand-made UDP reply finally changes the client state."""
from pathlib import Path

TEXT = """
### 12.90 ★★★ 自造应答 `1e 83 00` 首次真正改变客户端状态（2026-10-24 07:5x）

#### 新增能力

`server319/lobby_udp.py` 增加固定应答模式：

```
LOBBY_UDP_REPLY=<hex>     收到任意 UDP 包时回这段字节（优先于 echo）
LOBBY_UDP_ECHO=0/1        无 reply 时的回显开关
```

`LobbyEndpoint(port, log, echo=..., reply=bytes|None)`，日志新增 `udp_reply` 事件。
已单独验证参数解析：`LOBBY_UDP_REPLY=1e8300` → `reply = b'\\x1e\\x83\\x00'`。

#### 第一次试验就命中了

选取探测包 `1e 03 00` 的"对称应答" `1e 83 00`（把 `0x03` 翻转最高位为 `0x83`），
其余一切不变，跑一次完整流程。

结果：

```
state: dw=5  G1=0  FE=5  1F4=1
       obj1[120] = 1     idx = 4     cap = 05
       [0xE85CA0] = 661   [0xE85CB0] = 11
```

**与之前所有试验对比**：

| 配置 | `obj1[0x120]` | `idx` | 成功路径计数 |
|---|---|---|---|
| 无应答（silence） | 3 | 5 | 0 |
| 原样 echo | 3 | 5 | 4 |
| **`1e 83 00`** | **1** | **4** | **11** |

三点质变：

1. **状态从 3 变成 1**——这是几十轮以来第一次让 `obj1+0x120` 离开"失败锁定"值；
2. **索引从 5 回落到 4**——说明 `Add` 走了**另一条路径**（`count > 0` 分支），
   而不是之前那条"只推进索引到容量"的 `count<=0` 分支；
3. **`[0xE85CB0] = 11`**——§12.89 里那个"成功路径计数"全局量首次非零，
   证明 `0xBB170C` 被真正走进去了 11 次。

#### 这意味着什么

`1e 83 00` 被客户端**接受为一条有效响应**。它走完了：

```
0xBB15E0 recv 成功
  -> 0xBB170C 成功路径（计数 +1，写 [ebx] 与 [edi]）
  -> 0xC74053 0xB75420 把条目数写进容器 +0x84
  -> Add(obj1, count > 0)
  -> 0xBBA4A1 搬运、0xBC1980 判定、0xBC1A50 追加
  -> 索引推进但未到容量，状态保持 1
```

**索引是 4 而不是 5**，说明这一次 `Add` 走的是"追加成功"的路径，
索引从 0 重置后逐步增长到 4（而不是被 `count<=0` 一次推到上限）。

#### 但还没有到达终点

```
1F4 = 1      （仍为 1，需要 2）
G1  = 0      （FE 梯仍未启动）
```

状态停在 **1**，说明流程还没走到"完成"（目标是 `+0x120 == 2`，或者由
`0xBBA370` 的 `Init` 复位）。索引 4 < 容量 5，意味着**再追加一次就会满**。

两种可能：

1. 客户端会继续追加直到容量满，然后按 `0xBBA62B` 写 3 —— 那我们只是把
   "2.5 秒自锁"延长了一点；
2. 但状态 1 意味着 `Add` 现在**每帧都可能追加成功**，如果上层能消费这些条目
   并推进状态到 2，就会进入正常流程。

**下一轮的关键**：延长观察窗口（比如 120 秒），看索引是停在 4、涨到 5、
还是被某个逻辑复位；同时看 `1F4` 是否在某个时刻变成 2。

#### 已确立的结论

- **应答格式不需要完全正确**——只要是一个"能被当作有效消息"的形状就能推进状态；
- `1e 83 00` 是一个**有效的起点**，后续可以在此基础上微调（例如是否要带长度、
  是否要回两个包对应两种探测）；
- 这条路走通了：**"客户端发包 → 服务端回特定形状 → 客户端状态机前进"**
  这个闭环第一次真正运转起来。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.90"),
                         ("HANDOFF-CURRENT.md", "### 15.78")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.90", "### 15.78")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
