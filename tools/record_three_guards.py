"""Record round 144: three conditional jumps to the reset path at 0xBAE7B4."""
from pathlib import Path

TEXT = """
### 12.159 ★★★ 找到三条跳到复位路径 `0xBAE7B4` 的条件跳转（2026-10-25 20:2x）

#### 新工具

`tools/branch_map.py`：列出指定区间内**所有**跳转（`E9`/`EB`/`0F 8x`/`7x`/`E8`）及其目标，
用于直接读出控制流，而不是猜"哪条指令是守卫"。

#### `0xBAE280`–`0xBAE460` 的关键分支

```
0xBAE2E4  je     -> 0xBAE7B4      ★ 跳到复位路径
0xBAE2EC  ja     -> 0xBAE2E4
0xBAE2F1  je     -> 0xBAE7B4      ★
0xBAE2F9  jp     -> 0xBAE2F1
0xBAE2FE  je     -> 0xBAE7B4      ★
0xBAE312  jne    -> 0xBAE5DB      （0xBAE5DB 在 0xBAE587 之后，不跳过写 2）
0xBAE326  jne    -> 0xBAE5DB      （同上）
0xBAE345  jnp    -> 0xBAE36F
0xBAE347  jbe    -> 0xBAE397
```

#### `0xBAE7B4` 的位置决定了它的语义

`0xBAE7AC` 是 `mov dword [ebx+0x1F4], 1`（写 1，§12.152 记录的三个复位点之一）。

**`0xBAE7B4` 紧跟其后（+8 字节），是复位路径的一部分。**

**三条 `je` 都跳过 `0xBAE587`（写 2）直达复位**——它们**就是**此前一直在找的守卫。

#### 而 `0xBAE312`/`0xBAE326` 的 `jne 0xBAE5DB` 不是

`0xBAE5DB` 位于 `0xBAE587` **之后**，所以这两条 `jne` 跳过去时
**已经执行过写 2** —— 它们不影响 `1F4` 能否变成 2。

#### 下一步：看这三条 `je` 各自检查什么

它们位于 `0xBAE2E4`、`0xBAE2F1`、`0xBAE2FE`，彼此只隔 0xD 字节，
且前面有 `ja 0xBAE2E4`、`jp 0xBAE2F1` 这类循环/浮点相关跳转。

**需要反汇编 `0xBAE2D0`–`0xBAE310`**，看清：

1. 三条 `je` 各自的前置 `cmp`/`test` 是什么；
2. 它们是否构成一个"连续检查失败则放弃"的序列；
3. 哪个条件最可能在我们环境里不满足。

**一旦确定，就能用哨兵法验证该条件是否成立——或直接绕过它。**

#### 同时值得注意

`0xBAE345 jnp 0xBAE36F` 与 `0xBAE347 jbe 0xBAE397` 这两条也可能改变控制流方向，
但它们的目标 `0xBAE36F`/`0xBAE397` 都在 `0xBAE452` 之前，**不跳过写 2**。

**所以真正的候选只有那三条 `je 0xBAE7B4`。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.159"),
                         ("HANDOFF-CURRENT.md", "### 16.47")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.159", "### 16.47")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
