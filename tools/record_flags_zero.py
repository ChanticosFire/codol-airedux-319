"""Record round 152: the three guard flags are initialised to zero near the pump entry."""
from pathlib import Path

TEXT = """
### 12.167 ★★★ 三个守卫标志在 pump 入口附近被初始化为 0（2026-10-26 01:2x）

#### 三处引用

用 `find_offset.py` 搜三个栈偏移的 disp32（`0xFFFFF678`/`0xFFFFF677`/`0xFFFFF67A`）
在 `0xBAD800`–`0xBAE000` 内：

```
[ebp-0x989]: 0xBAD864  C6 85 77 F6 FF FF 00   mov byte ptr [ebp-0x989], 0
[ebp-0x986]: 0xBAD86B  C6 85 7A F6 FF FF 00   mov byte ptr [ebp-0x986], 0
[ebp-0x988]: 0xBAD879  0F 94 85 78 F6 FF FF   sete byte ptr [ebp-0x988]
```

**每次运行只有一处引用，说明它们各只被写一次（在 pump 开头）。**

#### 解读

| 标志 | 写入方式 | 初始值 |
|---|---|---|
| `[ebp-0x989]` | `mov byte ..., 0` | **0** |
| `[ebp-0x986]` | `mov byte ..., 0` | **0** |
| `[ebp-0x988]` | `sete`（来自前一条 `call` 的返回值） | **0 或 1** |

**前两个被显式清零**——`0xBAE2EA` 与 `0xBAE2F7` 的 `cmp ...0` / `je 0xBAE7B4`
**在默认情况下必然跳转**，除非别处改了它们。

**但扫描结果显示它们在 `0xBAD800`–`0xBAE000` 内只有一处写入**，
所以在这个范围内它们**恒为 0**。

**这意味着 `0xBAE2EA` 与 `0xBAE2F7` 的两道守卫恒成立 → 流程总是跳到 `0xBAE7B4` 复位。**

#### 而 `[ebp-0x986]` 还有一个额外写入

§12.160 记录 `0xBAE2D6 mov byte ptr [ebp-0x986], 1`——在 `0xBAE2D2 test al,al` /
`0xBAE2D4 jne` 之后。

**`0xBAE2D6` 位于 `0xBAE000` 之后**，所以不在本轮扫描范围内。

**但 `0xBAE2F7` 的检查在 `0xBAE2D6` 之后**——所以 `[ebp-0x986]` 可能被改成 1，
从而通过第三道守卫。

**而 `[ebp-0x989]` 没有这样的补救写入——它始终是 0。**

#### 所以 `[ebp-0x989]` 是真正的死结

`0xBAE2EA cmp byte [ebp-0x989], 0` / `0xBAE2F1 je 0xBAE7B4`

**若 `[ebp-0x989]` 恒为 0，这道 `je` 就恒成立，流程永远跳到复位。**

**这与"`1F4` 永远是 1"完全吻合。**

#### 下一步：确认 `[ebp-0x989]` 是否在别处被写

扫描范围只覆盖了 `0xBAD800`–`0xBAE000`。**需要在全镜像范围搜** `77 F6 FF FF`：

- **若全镜像也只有那一处 `mov ...,0`** → `[ebp-0x989]` 恒为 0，
  这道守卫是硬编码的死路——**那就需要弄清它本应在什么情况下被置 1**；
- **若别处还有写入** → 那里就是触发条件。

**同时**：反汇编 `0xBAD840`–`0xBAD8A0`，看清这三个标志初始化前后的完整逻辑
（`0xBAD846 cmp [ebx+0x1F4],1` 就在其中），理解这段代码的整体意图。

**`[ebp-0x989]` 这个名字无法得知，但它的位置（第二道守卫）与恒定 0 的事实，
强烈暗示它是"某个前置条件尚未满足"的标记。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.167"),
                         ("HANDOFF-CURRENT.md", "### 16.55")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.167", "### 16.55")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
