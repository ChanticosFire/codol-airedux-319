"""Record round 71: the -2 exit matches the entry rate, so the socket is starved not dead."""
from pathlib import Path

TEXT = """
### 12.86 ★★★ `-2` 出口频率与入口一致；socket 是"几乎无数据"而非"完全无数据"（2026-10-24 05:4x）

#### 三个出口的完整计数

在同一个干净环境里分别测量（`0xBB15E0` 的三个出口）：

| 出口 | 地址 | 计数（10 秒） | 速率 |
|---|---|---|---|
| 入口 | `0xBB15E0` | — | **约 21 次/秒** |
| 成功（`>= 0`） | `0xBB170C` | **4** | 0.4 次/秒 |
| `-2`（`WSAEWOULDBLOCK`） | `0xBB166F` | **207** | **约 21 次/秒** |
| `-1`（默认桶） | `0xBB16F8` | 0 | 0 |

**`-2` 出口的频率与入口几乎完全一致。** 说明：

- 错误码绝大多数是 **10035 `WSAEWOULDBLOCK`**（§12.85 的跳表映射已确认）；
- `-1` 出口（其它错误码）**一次都没有**，说明没有 `WSAECONNRESET` 之类的硬错误；
- 成功出口**有 4 次**，不是 0。

#### 一个重要修正

此前倾向的说法是"对面没人，永远收不到数据"。**本轮的 4 次成功说明这个说法要收敛为
"socket 极少有数据"**：

```
52 次 WSAEWOULDBLOCK  :  1 次成功
```

也就是说这条 socket **确实有对端在回包**，只是频率极低（约 0.4 次/秒），
而客户端每帧都在轮询（21 次/秒），所以绝大多数轮询落空。

#### 这意味着什么

1. **对端存在且会响应**——这就排除了"STUN 服务器已下线、完全无回应"的简单解释；
2. 但那 4 次成功**没能让 `count` 变成非零**（本轮状态：`obj1[120]=3`、`idx=5`）。
   所以要么成功时读到的数据不是"条目列表"，要么数据内容为空；
3. 0.4 次/秒 的响应频率本身也偏低——正常的大厅会话应当是持续的数据流。

#### 新的、更精确的问题

**那 4 次成功时，`0xBB15E0` 到底读到了什么？**

三种可能：

- 读到的是**空包**（长度 0），因此写的条目数为 0；
- 读到的是**别的消息类型**（不是服务器列表），被上层丢弃；
- 读到的是**我们自己的 `lobby_udp` 回声**（3074 的 echo），内容不构成有效条目。

第 3 种很可疑：`lobby_udp` 是"收到什么回什么"的 echo，如果客户端往 3074 发探测包，
它会立刻回一个同文包，客户端就把这个回声当成"一条数据"处理——**其内容自然不是
服务器列表，解析出 0 条**。

这能同时解释"有 4 次成功"和"count 仍为 0"。

#### 下一步（可验证）

1. **确认这条 socket 是否就是 3074**：在 `0xBB15E0` 入口读 `ecx`（this）与 `[ecx+4]`
   （句柄），配合 `netstat -ano` 把句柄映射到本地端口；
2. 若是 3074，则 `lobby_udp` 的 echo 行为应当**改掉**——不再原样回包，而是
   回一个符合 `svc71/task4` 语义的应答（或者干脆不回，让 socket 保持无数据，
   避免客户端把回声当数据）；
3. 若不回包后 `count` 仍为 0，则说明这条通道不是数据来源，需要另找。

第 2 条成本极低（改 `lobby_udp` 的行为即可），且能立刻验证"回声被误当数据"这个假设。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.86"),
                         ("HANDOFF-CURRENT.md", "### 15.74")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.86", "### 15.74")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
