"""Record round 178: lobby+4 is never a live socket, and state 5 occurs without any reply."""
from pathlib import Path

TEXT = """
### 12.193 ★★★★ `lobby+4` 从未是有效 socket；状态 5 在无任何回复时也会自发出现（2026-10-26 15:5x）

#### 实测

从客户端可读的最早时刻开始，以 10ms 间隔采样 42 秒：

```
t=  0.00  lobby+4=None  1A0=None  1F4=None  dw=0
t= 12.53  lobby+4=    0  1A0=None  1F4=   1  dw=0
t= 17.97  lobby+4=    0  1A0=   1  1F4=   1  dw=2
t= 20.98  lobby+4=    0  1A0=   5  1F4=   1  dw=5

distinct lobby+4 values: {None: 1198, 0: 2816}
samples with a live socket: 0
```

**`lobby+4` 只有两种取值：不可读（对象未建立）与 0。**

**从未出现过任何有效句柄（非 0 且非 `0xFFFFFFFF`）。**

#### 第二个重要发现：状态 5 不需要我们的回复

**本轮没有设置 `LOBBY_UDP_REPLY` / `LOBBY_UDP_REPLY_MATCH`，服务端只做回声。
但状态码仍然自己从 1 变成 5。**

**所以状态 5 是客户端自发流程的一部分，不是"我们的消息被拒"的信号。**

#### 完整因果链（最终版）

```
lobby socket 从未创建（lobby+4 恒为 0）
  -> 0xBB143B 只挡 -1，0 被放行
  -> 0xBB1420 正常构造 sockaddr（family=2 / addr / port=3074）
  -> sendto(0, ...) 返回 -1（WSAENOTSOCK）
  -> 0xC73F30 返回 -1
  -> 0xBBA7D4 jle 成立 -> 失败
  -> 0xBBA7AC 写状态 5
```

**与 §12.176 的两条失败路径完全吻合，且排除了"消息内容"这个因素。**

#### 这解释了此前所有困惑

| 现象 | 解释 |
|---|---|
| 服务端只收到两种探测包 | 探测包走的是另一个**已经能用**的 socket |
| 状态码在 1 与 5 之间跳 | 1 = 等待，5 = 尝试发送失败 |
| `1F4` 永远是 1 | `0xBAE30F` 要求状态 2 或 4，而流程卡在 5 |
| FE 梯不动 | 同上 |
| 客户端停在代号页/模糊画面 | 无法完成列表往返 |

#### 下一步：找 socket 创建点

**`lobby+4` 的写入点就是 socket 创建的位置。**

`find_offset.py 0x4` 不可用（4 是到处都是）。**更可行的两条路：**

1. **搜 `sendto` / `WSASocket` 的导入表引用**——`0xBB1420` 里应当有 `sendto` 的调用，
   顺着同一模块（`0xBBxxxx`）找到 `socket` / `WSASocket` 的调用点；
2. **搜把 API 返回值写入 `[reg+4]` 的短指令序列**（`89 43 04` / `89 4x 04` 等），
   再筛选出 `reg` 是 lobby 的情况。

**第 1 条更可靠，因为 `socket()` 的导入引用是唯一的。**

**一旦找到创建点，就能判断"为什么它没被执行"——
这很可能直接指向某个我们尚未满足的服务端响应。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.193"),
                         ("HANDOFF-CURRENT.md", "### 16.81")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.193", "### 16.81")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
