"""Record round 143: lobby+8 is 1, so the outer gate passes and the blocker is deeper."""
from pathlib import Path

TEXT = """
### 12.158 `[lobby+8]` 为 1：外层守卫通过，卡点在更深处（2026-10-25 19:5x）

#### 实测

在 `dw=5` 之后（19.01 秒时到达）读 `lobby` 的前 32 字节：

```
lobby = 0x37BB2030
lobby[0x00..0x1F] = d0a9d500 00000000 01 00fb55 08ddf037 c890f437 04000000 03000000 020c0000
```

逐字段解析：

| 偏移 | 值 | 说明 |
|---|---|---|
| `+0x00` | `0x00D5A9D0` | vtable |
| `+0x04` | `0x00000000` | 0 |
| **`+0x08`** | **`0x01`** | **字节，pump 的第一道检查** |
| `+0x0C` | `0x37F0DD08` | 指针（那个有 send/recv 虚槽的对象） |
| `+0x10` | `0x37F4C890` | 指针 |
| `+0x14` | `0x00000004` | 4 |
| `+0x18` | `0x00000003` | 3 |
| `+0x1C` | `0x00000C02` | 3074 |

**`[lobby+8] = 1`**，所以 `0xBAD83D` 的 `je 0xBAE7C6` **不成立**，
pump 会继续执行。

#### 因此外层守卫不是卡点

§12.157 的假设（"`[lobby+8]` 为 0 时 pump 跳走，所以写 2 不执行"）**被本轮否定**。

**pump 确实在正常执行。**

#### 那 `0xBAE587` 为什么不执行

回到 §12.155/§12.156 的结构：`0xBAE54B` 是汇合点，之后无条件下到 `0xBAE587`。

**所以要么执行流在 `0xBAE4BC`–`0xBAE54B` 之间跳走了，要么整段 `0xBAE452`–`0xBAE587`
属于一个当前不被执行的分支。**

`0xBAE4CB` 的 `cmp [ebx+0x4D6C],0` / `je 0xBAE52B` 只是跳过搬运，**不跳过写 2**。

#### 下一个可查的具体值：`[lobby+0x4D6C]`

`0xBAE4CB` 检查它。若它为 0，只跳过搬运（`0xBAE4D8`–`0xBAE525`），
但**仍会到 `0xBAE54B` 和 `0xBAE587`**。

**所以它也不是守卫。**

**真正的问题变成：`0xBAE452` 这一段属于哪个分支？它什么时候被执行？**

#### 唯一的办法：找出 `0xBAE452` 的入口

`branches_to.py` 已证明 `0xBAE4A0`/`0xBAE490` 都没有外部跳转来源。
**那 `0xBAE452` 之前的指令是什么？**

需要从 `0xBAD800` 起**完整反汇编到 `0xBAE452`**，顺着控制流看这段是否可达、
以及在什么条件下可达。

**这是目前唯一剩下的路**：不能再用"猜哪条指令是守卫"的方式，
而要从函数入口一路跟下来。

**`0xBAD800` 是干净边界，`0xBAE452` 距它 0xC52 字节——一次完整反汇编即可。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.158"),
                         ("HANDOFF-CURRENT.md", "### 16.46")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.158", "### 16.46")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
