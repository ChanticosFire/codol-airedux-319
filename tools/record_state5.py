"""Record round 167: the reply reaches the client but is rejected, moving the code to 5."""
from pathlib import Path

TEXT = """
### 12.182 ★★★ 九字节 `0x15` 消息到达客户端，但被判为错误（状态码变 5）（2026-10-26 09:2x）

#### 第一次实验的教训

首轮实验在 `run_verified.ps1 -SkipWait` 之后**立即**轮询，此时客户端进程尚未创建，
每次读取都失败，脚本打印 `gone` 就退出了。

**结论：任何轮询都必须先等客户端映像可读。** 新增 `tools/watch_statecode.py`
专门做这件事（轮询 `0xE85C68` 直到可读，再开始采样）。

#### 第二次实验（正确等待）

服务端环境：

```
LOBBY_UDP_ECHO=1
LOBBY_UDP_REPLY=150100000000000000
LOBBY_UDP_REPLY_MATCH=14020000
```

日志确认回复确实发出：

```
{"event": "udp_reply", "length": 9, "hex": "150100000000000000", "sent": 1}
{"event": "udp_reply", "length": 9, "hex": "150100000000000000", "sent": 2}
{"event": "udp_reply", "length": 9, "hex": "150100000000000000", "sent": 3}
```

客户端状态码变化：

```
t= 18.16  1A0=1  19C=0  status=1  1F4=1  dw=2
t= 19.04  1A0=1  19C=0  status=1  1F4=1  dw=3
t= 19.23  1A0=1  19C=0  status=1  1F4=1  dw=5
t= 20.72  1A0=1  19C=0  status=3  1F4=1  dw=5
t= 21.19  1A0=5  19C=0  status=3  1F4=1  dw=5    ← ★ 变成 5

state codes seen: {None: 251, 1: 148, 5: 1166}
samples with 1A0==4: 0
```

#### 三项重大结论

**1. 通道确认正确**

**消息确实到达客户端并被解析**——因为状态码从 1 变成了 5，
**而 5 是"错误"状态**（§12.174 记录 `0xBBAAAE` 与 `0xBBAC40` 都写 5）。

**所以 UDP 3074 就是这条消息的通道，`0xBBAB30` 那段代码确实在处理我们的回复。**

**2. 格式被拒绝**

**状态码没到 4，而是到了 5**——说明解析器接受了消息头（类型识别成功，
否则会走 `jne` 直接跳过、状态保持 1），**但在字段层判定为非法。**

**3. 因此 `0x15` 的类型是对的，字段内容不对**

**若类型错误，`0xBC1D20` 会在 `0xBC1D64`/`0xBC1D6D` 的类型范围检查处失败，
返回 0，`0xBBAB5E` 跳走，状态保持 1。**

**实际变成了 5——说明类型通过、字段读取也通过，但在后续校验里被判非法。**

#### 下一步：找状态 5 的来源

`0xBBAAAE` 与 `0xBBAC40` 都写 5。**反汇编 `0xBBAA90`–`0xBBAAE0` 与
`0xBBAC20`–`0xBBAC60`**，看各自的前置条件。

**很可能其中一处是"条目数超出上限"或"字段值非法"的错误分支。**

**也可能 5 表示另一种终态（例如"列表为空但请求已完成"）——
若如此，状态 5 也许能被 `0xBBA710` 接受？**

**需要回看 `0xBBA710`：它对 1/2/3 返回 1（pending），对 4 及**其他**返回 0。**

**5 不在 1/2/3 里——所以 `0xBBA710` 对状态 5 会返回 0！**

**这意味着标志 C 应当被置 1、第三道守卫应当通过、`1F4` 应当变成 2！**

**但实测 `1F4` 仍是 1。**

**所以还有别的环节挡着——这需要重新检查。**

**这是一个重要的新线索：状态 5 在 `0xBBA710` 的判定里等同于"已完成"，
那为什么 `1F4` 还没动？**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.182"),
                         ("HANDOFF-CURRENT.md", "### 16.70")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.182", "### 16.70")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
