"""Record round 193: a 160-byte reply changes nothing, so the recv does not see our packets."""
from pathlib import Path

TEXT = """
### 12.204 阴性：160 字节记录也没有效果，收包看不到我们的回复（2026-10-26 21:5x）

#### 实验动机

§12.203 的结论是"收包只拿到 3–4 字节，不足以构成 136 字节记录，
所以 `Add` 走 `count <= 0` 分支"。**若该结论正确，那么发一条 ≥136 字节的回复
应当让 `count > 0`，`Add` 走成功分支写 2。**

#### 实验

`LOBBY_UDP_REPLY` 设为 160 字节全零，对**所有**入站包都回复（不设 `MATCH`）。

日志确认回复确实发出：

```
{"event": "udp_reply", "length": 160, "hex": "0000…0000", "sent": 1}
{"event": "udp_reply", "length": 160, "hex": "0000…0000", "sent": 2}
```

#### 结果

```
t= 18.28  1A0=   1  19C=    0  status=   1  1F4=1  dw=2
t= 19.34  1A0=   1  19C=    0  status=   1  1F4=1  dw=5
t= 20.88  1A0=   1  19C=    0  status=   3  1F4=1  dw=5
t= 21.35  1A0=   5  19C=    0  status=   3  1F4=1  dw=5

state codes seen: {None: 259, 1: 150, 5: 913}
```

**与 §12.178 的"完全不发回复"基线完全一致。**

#### 结论：收包根本看不到我们的回复

**`vt+0x1C`（`0xC73FB0`）读取的 socket 与我们回复的目标不是同一个。**

**证据链：**

1. **回复确实发出**（日志有 `udp_reply`，长度 160）；
2. **客户端状态序列与无回复时逐点相同**——
   若它收到了 160 字节，`Add` 的 `count` 就不该是 0，状态应变成 2；
3. **`1A0 = 5` 是自发的**（§12.178 已证即使零回复也会出现）。

**所以：我们的 UDP 回复被发到了探测包的源地址/端口，
但那个 socket 不是客户端用它做 `vt+0x1C` 收包的那个。**

**这也解释了 §12.167 与 §12.182 的观测**：发 9 字节类型 `0x15` 消息时状态变成 5，
**那不是"消息被拒"，而是自发的发送失败流程恰好同时发生。**

#### 对后续的直接影响

**"在 UDP 3074 上返回 ≥136 字节记录"这个方向，前提是错的**——
**因为客户端的业务收包不经由 3074 上那个与探测包通信的 socket。**

**正确的方向应当是：先确定 `vt+0x1C` 实际绑定/连接到哪个端口与地址，
再向那个目标发送数据。**

**判断方法（下一轮可做）**：用 `netstat -ano` 或 `modules.py` 侧的手段列出
客户端进程的全部 UDP 端点，看除 3074 外还有哪些本地端口在监听/连接。
**若存在另一个 UDP socket，那才是业务通道。**

#### 这条阴性结果的价值

**它排除了一整类做法**（往 3074 回大包），**并把问题从"数据内容不对"
收窄到"通道不对"**——这是一个更基础、也更容易验证的问题。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.204"),
                         ("HANDOFF-CURRENT.md", "### 16.92")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.204", "### 16.92")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
