"""Record round 158: the server list sits at state code 1 with a null data pointer."""
from pathlib import Path

TEXT = """
### 12.173 ★★★★ 根因确认：`serverlist[0x1A0] = 1`，数据指针为 0（2026-10-26 04:2x）

#### 实测

```
lobby    = 0x37DEB850
obj1     = 0x37EC4640
serverlist = 0x37EC47B8

obj1 status = 1     idx = 2
1F4 = 1     dw = 5     FE = 5     G1 = 0

*** serverlist[0x1A0] = 1
    serverlist[0x19C] = 0x00000000
```

`serverlist[0x180..0x1BF]` 的原始字节：

```
00000000 00000000 00000000 00000000 00000000 02000000 00000000 00000000
00000000 01000000 02000000 9c5291e4 08010000 05000000 00003f00 00000000
```

（可见 `0x1A0` 处的 `01000000` 即状态码 1；`0x1A4` 处是 `02000000`。）

#### 这彻底验证了 §12.172 的推断

| 事实 | 后果 |
|---|---|
| `[0x1A0] = 1` | `0xBBA710` 返回 1 |
| 返回 1 | `0xBAE2D4 jne` 跳转，标志 C 保持 0 |
| 标志 C = 0 | `0xBAE2F7 je 0xBAE7B4` 成立，跳到复位 |
| 跳复位 | `0xBAE587` 不执行，`1F4` 永远是 1 |
| `1F4` 永远 1 | 下一帧 pump 继续，但 FE 梯不动 |

**而且 `[0x19C] = 0`——那个"数据指针"是空的。**

#### 这是整条链的根

从第 60 轮开始追查的 `count = 0`、状态停在 1、`1F4` 恒为 1、
FE 梯不动、客户端停在代号页/过渡画面——**全部是"服务器列表状态码停在 1"的下游后果**。

**状态码语义（依据 §12.172 的两个函数）：**

| 码 | 含义（推断） |
|---|---|
| 0 | 未初始化 |
| **1** | **进行中 / 请求已发出，等待数据** |
| 2、3 | 其他中间态 |
| **4** | **有数据（`0xBBA730` 返回 `[0x19C]`）** |

**当前停在 1——请求已发出，但数据从未到达。**

#### 下一步：找 `[0x1A0]` 的写入点

**用 `find_offset.py` 搜 `0x1A0` 的 disp32，找出所有把状态码设为 4（或其他值）的位置。**

那些位置就是"数据到达后推进状态"的代码。

**若能确定"谁把状态码从 1 改成 4"，就能知道缺的是什么条件——
很可能就是：某个 UDP 应答里带了服务器列表条目，被解析后写入。**

**这将把整条分析线与最初的协议/数据问题彻底汇合。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.173"),
                         ("HANDOFF-CURRENT.md", "### 16.61")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.173", "### 16.61")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
