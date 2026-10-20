"""Record round 166: one record is six bytes, so the whole message is nine."""
from pathlib import Path

TEXT = """
### 12.181 ★★★ 记录大小确定：一条 6 字节，整条消息 9 字节（2026-10-26 08:2x）

#### `0xB770F0` 全文

```asm
0xB770F0  push ebp / mov ebp,esp
0xB770F3  xor al, al                        ; 默认返回失败
0xB770F5  66 83 B9 80 00 00 00 17           cmp word ptr [ecx+0x80], 0x17
0xB770FD  74 1B                              je 0xB7711A      ; == 0x17 -> 不读，返回 0
0xB770FF  8B 45 14                          mov eax, [ebp+0x14]
0xB77102  8B 55 0C                          mov edx, [ebp+0xC]
0xB77105  6A 04                             push 4           ; ★ 读 4 字节
0xB77112  E8 39 13 00 00                     call 0xB78450    ; 读 dword
0xB7711A  5D                               pop ebp
0xB7711B  C2 10 00                         ret 0x10
```

#### 记录与消息的完整尺寸

| 部分 | 字节数 | 来源 |
|---|---|---|
| 类型码 | 1 | `0xBC1D42` 的 `push 1` |
| `this[2]` 的 word | 2 | `0xBC1D79` 的 `push 2`（须为 1 或 2） |
| 记录第一个字段 | **4** | `0xB770F0` 的 `push 4` |
| 记录第二个字段 | 2 | `0xB7574A` 的 `push 2` |
| **合计** | **9** | |

**所以一条合法的 `0x15` 消息是 9 字节：**

```
15 01 00  XX XX XX XX  YY YY
└类型┘ └word=1┘ └─dword─┘ └word┘
```

（`this[2]` 用 1 或 2 均可，二者都走短路径。）

#### 一个前提条件

`0xB770F0` 开头检查 `[ecx+0x80] == 0x17`，**相等则直接返回 0（解析失败）**。

`ecx` 是 `this`（那个 `0xBC1D20` 的输出结构）。

**所以如果客户端那个结构的 `+0x80` 恰好是 `0x17`，这条消息会被拒。
但正常初始化时该字段多半是 0，所以这个检查通常不会触发。**

#### 下一步：实测

在 `lobby_udp.py` 里，当收到探测包 `14 02 00 00` 时，回一条 9 字节消息：

```
15 01 00 00 00 00 00 00 00
```

（类型 `0x15`，word = 1，记录的两个字段都填 0。）

然后轮询 `serverlist[0x1A0]`：

- **变成 4** → 成功！服务器列表状态推进，`1F4` 应当随之变成 2，FE 梯可能开始走；
- **仍是 1** → 说明这条消息没走到 `0xBBAB7C`，需要检查通道
  （也许它不走 3074，而是 4174/4175 或 TLS）。

**这是整条链上第一个可以真正执行的修复实验，且完全在服务端侧，不需要再改客户端。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.181"),
                         ("HANDOFF-CURRENT.md", "### 16.69")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.181", "### 16.69")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
