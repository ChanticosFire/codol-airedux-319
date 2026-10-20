"""Record round 162: the logs contain no 0x15 message, only echo of two probe packets."""
from pathlib import Path

TEXT = """
### 12.177 日志确认：服务端只回声两个探测包，从未发过类型 `0x15`（2026-10-26 06:2x）

#### 日志结构

`lobby_udp.jsonl` 的事件类型只有三种：

```
{"event": "endpoint_up", "port": 3074, "echo": true}
{"event": "udp_in",   "src": "127.0.0.1:22011", "length": 3, "hex": "1e0300"}
{"event": "udp_echo", "length": 3}
{"event": "udp_in",   "src": "127.0.0.1:22011", "length": 4, "hex": "14020000"}
{"event": "udp_echo", "length": 4}
```

**统计 8 个最近日志、156 个事件：**

```
event=endpoint_up  x8
event=udp_in       x74
event=udp_echo     x74
```

#### 入站内容

`udp_in` 的 74 个事件全部是两种探测包：

| hex | 长度 | 说明 |
|---|---|---|
| `1e 03 00` | 3 | 探测包 A（§12.62） |
| `14 02 00 00` | 4 | 探测包 B |

**首字节分别是 `0x1E` 与 `0x14`——都不是 `0x15`。**

**没有任何一条消息的首字节是 `0x15`。**

#### 结论

**服务端（我们的 `lobby_udp.py`）对这两个探测包只做原样回声，
从未向客户端发送过任何构造的消息——更没有类型 `0x15` 的消息。**

**这与 §12.176 的结论完全吻合：**

```
服务端不发 0x15
  -> 客户端 0xBBAB35 的 edi 条件也无法满足（没有数据可解析）
  -> 状态码 [0x1A0] 永远是 1
  -> 0xBBA710 永远返回 1（pending）
  -> 标志 C 永远是 0
  -> 0xBAE2F7 je 0xBAE7B4 成立
  -> 0xBAE587 永不执行
  -> 1F4 永远是 1
  -> FE 梯永不推进
```

**整条因果链从"服务端不发消息"一直通到"客户端停在代号页"。**

#### 下一步：确定 `0x15` 该走哪条通道

两个待解：

1. **通道**：`0xBBAB30` 那段代码属于哪个函数？`esi`（数据指针）与 `edi`（长度）从哪来？
   反汇编该函数入口即可知道它是 UDP 收包处理还是 TLS 收包处理。
2. **格式**：`0xBC1D20` 是解析函数，反汇编它能得到消息的字段布局
   （长度前缀？类型字段位置？条目的结构？）。

**然后就能在 `lobby_udp.py` 里构造并发送一条类型 `0x15` 的消息。**

**注意**：`0x14`（20）是我们的探测包 B 的首字节，`0x15`（21）是它的下一个——
**类型码连续，暗示 `0x15` 很可能是同一协议族里"服务器列表应答"的消息类型。**

**若客户端在发 `0x14` 之后期待 `0x15` 应答，那修复就是：收到 `14 02 00 00` 时回一条 `15 …` 的消息。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.177"),
                         ("HANDOFF-CURRENT.md", "### 16.65")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.177", "### 16.65")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
