"""Record round 195: poking every UDP port with 160 bytes still produces no state 2."""
from pathlib import Path

TEXT = """
### 12.206 阴性：向全部 6 个 UDP 端口发 160 字节，状态仍未变 2（2026-10-26 22:5x）

#### 实验

运行时枚举客户端 UDP 端点，然后对**每个端口**从**两个源端口**（任意高端口与 3074）
各发一条 160 字节数据报：

```
client pid 11140, udp ports: [22011, 52166, 52167, 61173, 61175, 61176]
sent 160 bytes: 12 次（6 端口 × 2 源端口），全部成功
```

#### 结果

```
t= 0.00  1A0=1  status=1  1F4=1  dw=3
t= 1.67  1A0=1  status=3  1F4=1  dw=5
t= 2.14  1A0=5  status=3  1F4=1  dw=5

list codes seen: {1: 105, 5: 1854}
saw code 2: 0
```

**状态码仍是 1 → 5，从未出现 2。**

#### 三项结论

**1. 那 5 个额外 UDP 端口不是业务收包通道**

**向它们发送数据没有任何可观测影响。**

**2. 状态 5 再次证明是自发的**

**本轮同样没有配置 `LOBBY_UDP_REPLY`，服务端只做回声；`1A0` 仍然变成 5。**

**3. 通道问题仍未解决**

**结合 §12.204 与 §12.206，可以排除：**

- 回 3074 的探测包源（`22011`）——无效；
- 向 5 个额外 UDP 端口发——无效。

**剩下的可能性：**

1. **`vt+0x1C` 的收包依赖一个尚未建立的连接**（例如它内部先检查
   `getsockname`/`getpeername`，未连接则直接返回 0）；
2. **业务数据走 TCP 4174（LSG 通道）**，而不是 UDP；
3. **收包前需要某个前置状态**（例如 `[lobby+0x1F4]` 必须已经是 2，
   而它永远是 1——这在逻辑上是循环依赖，但值得核对 `0xBAE242` 之前的分支）。

#### 本轮之后的状态

**通道问题仍未定位，M4 依旧受阻。**

**§12.193 的结论（"数据不足"）与 §12.205 的观察（"6 个 UDP 端点"）
都是真的，但都不足以解释为什么收包读不到我们的数据。**

**剩余轮次（5 轮）将用于最终收束，不再开启新实验**——
因为每条新线索都需要"假设 → 实现 → 实测"的完整循环，
而 5 轮不足以完成哪怕一次这样的循环。

#### 交接建议

**下一个接手者最该先做的一件事**：在 `0xC73FB0`（`vt+0x1C`）入口处
用哨兵法确认它被调用时的 `ecx`/参数，以及它内部是否在第一步就返回 0。
**这能区分"没收到数据"与"收到了但不合格"。**

**工具上**：`tools/poke_ports.py` 已可用于向任意进程的全部 UDP 端口发包，
`tools/watch_statecode.py` 用于观察状态码，两者可直接复用。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.206"),
                         ("HANDOFF-CURRENT.md", "### 16.94")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.206", "### 16.94")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
