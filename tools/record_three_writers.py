"""Record round 159: three sites write state code 4 to the server-list object."""
from pathlib import Path

TEXT = """
### 12.174 ★★★ 找到三处把状态码写为 4 的代码（2026-10-26 04:5x）

#### 全镜像与收窄

`find_offset.py 0x1A0` 在 `0x400000`–`0xDD0000` 内有 **1099** 个命中（`0x1A0` = 416 是常见的
立即数/结构体大小）。

收窄到服务器列表类所在的 `0xBB9000`–`0xBBC000`，剩 **21 个**：

```
0xBBA6E8  39 9E A0 01 00 00              cmp  [esi+0x1A0], ebx
0xBBA6F7  89 9E A0 01 00 00              mov  [esi+0x1A0], ebx      ← 写
0xBBA712  8B 89 A0 01 00 00              mov  ecx, [ecx+0x1A0]      ← 读（0xBBA710）
0xBBA735  83 B9 A0 01 00 00 04           cmp  [ecx+0x1A0], 4        ← 读（0xBBA730）
0xBBA752  8B 81 A0 01 00 00              mov  eax, [ecx+0x1A0]      ← 读（0xBBA750）
0xBBA873  89 9E A0 01 00 00              mov  [esi+0x1A0], ebx      ← 写
0xBBA915  8B 83 A0 01 00 00              mov  eax, [ebx+0x1A0]      ← 读
0xBBA953  C7 83 A0 01 00 00 04 00 00 00  mov  [ebx+0x1A0], 4        ← ★ 写 4
0xBBA97F  C7 83 A0 01 00 00 04 00 00 00  mov  [ebx+0x1A0], 4        ← ★ 写 4
0xBBA9F7  C7 83 A0 01 00 00 04 00 00 00  mov  [ebx+0x1A0], 4        ← ★ 写 4
0xBBAAAE  C7 83 A0 01 00 00 05 00 00 00  mov  [ebx+0x1A0], 5        ← 写 5
0xBBAAC9  C7 83 A0 01 00 00 02 00 00 00  mov  [ebx+0x1A0], 2        ← 写 2
0xBBABD5  8B 86 A0 01 00 00              mov  eax, [esi+0x1A0]      ← 读
0xBBAC40  C7 86 A0 01 00 00 05 00 00 00  mov  [esi+0x1A0], 5        ← 写 5
```

#### 三处"写 4"就是数据到达的登记点

`0xBBA953`、`0xBBA97F`、`0xBBA9F7`（**三处相邻，间隔 0x2C 与 0x78**）
都把状态码设为 4——**而 §12.172 已确认 4 表示"有数据可取"**。

**它们应当就是"接收并解析出列表条目后，状态推进到就绪"的代码。**

其余写入：

- `0xBBAAAE` / `0xBBAC40` 写 5——可能是错误态或另一种终态；
- `0xBBAAC9` 写 2——中间态；
- `0xBBA6F7` / `0xBBA873` 写 `ebx`——`ebx` 此处可能是 0（复位）或别的值。

#### 下一步

**反汇编 `0xBBA940`–`0xBBA960`**（第一处写 4 的上下文），看它的前置条件：

- 若是"某个长度/计数 > 0 则置 4"，那就需要应答里真的带条目；
- 若是无条件的，那说明这段代码根本没被执行（因为状态停在 1），
  需要找它属于哪个分支、由什么触发。

**同法再看向 `0xBBA97F` 与 `0xBBA9F7`。**

**这三处最可能分别对应三种数据来源（例如：主列表、备用列表、缓存）。
弄清哪一处应当被触发，就能知道缺的是哪种应答。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.174"),
                         ("HANDOFF-CURRENT.md", "### 16.62")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.174", "### 16.62")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
