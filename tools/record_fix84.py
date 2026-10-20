"""Record round 175: the port getter reads +0x84, not +0x80, so the previous theory is wrong."""
from pathlib import Path

TEXT = """
### 12.190 修正：`0xB754C0` 读的是 `+0x84`（值为 2），不是 `+0x80`（2026-10-26 14:2x）

#### 实测代码

```asm
0xB754C0  66 8B 81 84 00 00 00   mov ax, word ptr [ecx+0x84]
0xB754C7  C3                     ret
```

**只有两条指令：读 `[ecx+0x84]` 处的 word 并返回。**

#### 于是 §12.189 的推断被推翻

§12.189 认为是 `+0x80` 为 0 导致 `sendto` 失败。**但实际读的是 `+0x84`，而实测该字段值为 2。**

**§12.189 的因果链（`[+0x80]=0` -> 端口 0 -> 发送失败）不成立。**

#### 顺带确认 `+0x84` 的性质

`0xB75440`（§12.82）同样读 `+0x84`：

```asm
0xB75443  66 8B 91 84 00 00 00   mov dx, word ptr [ecx+0x84]
0xB7544D  66 3B 90 84 00 00 00   cmp dx, word ptr [eax+0x84]
0xB75454  75 13                    jne 0xB75469
0xB75457  E8 74 1B 00 00           call 0xB76FD0
0xB7545E  …
```

**它比较两个对象的同一字段，相等后再调 `0xB76FD0` 比较别的东西。**

**所以 `+0x84` 是一个小的标识字段（值为 2），用于"这两条记录是否同类型"的判断，
不是端口。**

#### 那 `0xBB1420` 的端口从哪来

`0xC73F6C call 0xB754C0` 得到 `2`，`movzx edx,ax` 后 `push edx`——
**所以这个 2 被作为某个参数传给 `0xBB1420`。**

**但 `0xBB1420` 是 `sendto` 包装，它需要 `sockaddr`（IP + 端口）。
一个 2 不可能是端口。**

**所以有两种可能：**

1. **那个 2 是"类型"或"标志"，而真正的 `sockaddr` 由 `0xBB1420` 从别处取；
2. **`0xBB1420` 的签名里这个参数另有含义。**

#### 下一步

**反汇编 `0xBB1420`**——它是最终的执行点，看它如何组装 `sockaddr`、
从哪个对象字段取 IP 与端口。

**这将直接说明"为什么 sendto 会失败"，而不是继续猜测字段含义。**

**注意**：`[+0x88] = 3074` 这个值仍然可疑——它很可能就是真正的端口，
只是由另一条路径使用。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.190"),
                         ("HANDOFF-CURRENT.md", "### 16.78")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.190", "### 16.78")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
