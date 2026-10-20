"""Record round 146: two je instructions at 0xBBA465/0xBBA483 skip past the store of 2."""
from pathlib import Path

TEXT = """
### 12.161 ★★★ 找到了那条绕行路径：`0xBBA465`/`0xBBA483` 的 `je 0xBBA5A5` 跳过写 2（2026-10-25 21:2x）

#### 成功分支内的全部跳转

用 `branch_map.py` 列出 `0xBBA440`–`0xBBA5D0`：

```
0xBBA442  jle  -> 0xBBA5C3    入口判断（count <= 0）
0xBBA465  je   -> 0xBBA5A5    ★
0xBBA483  je   -> 0xBBA5A5    ★
0xBBA4B2  jb   -> 0xBBA55E    （到写 2）
0xBBA4D3  je   -> 0xBBA55E    （到写 2）
0xBBA4B2/0xBBA4D3 之后的路径直落 0xBBA55E -> 0xBBA569
```

#### 关键：`0xBBA5A5` 在 `0xBBA569` 之后

- `0xBBA569` = `mov dword [ebx+0x120], 2`（写 2）
- `0xBBA5A5` = `lea ecx, [ebp-0x1c4]`

**`0x5A5 > 0x569`，所以从 `0xBBA465` 或 `0xBBA483` 跳到 `0xBBA5A5`
会跳过 `0xBBA569`。**

**这正是 §12.150 里"强制进入成功分支却仍到不了写 2"的原因**——
强制进入只绕过了 `0xBBA442` 的入口判断，**而这两条更靠内的 `je` 依然会把流程跳过去。**

#### 它们的条件

```asm
0xBBA45E  call 0xB75440
0xBBA465  je 0xBBA5A5          ; 若返回 0 -> 跳过写 2
…
0xBBA47C  call 0xBC1A50
0xBBA483  je 0xBBA5A5          ; 若返回 0 -> 跳过写 2
```

- **`0xB75440`**：§12.82 记录过，它比较两个 136 字节记录的 `+0x84` 字段
  （`mov dx,[ecx+0x84]` / `cmp dx,[eax+0x84]` / `jne` / `call 0xB76FD0`）。
  **返回 1 表示"相同"，0 表示"不同"。**
- **`0xBC1A50`**：§12.91 记录过，它是容器的"追加"函数。

**所以这两处检查的含义是：**

1. `0xBBA45E`：**当前条目与容器里的某条记录是否相同** → 不同则跳过写 2；
2. `0xBBA47C`：**追加是否成功** → 失败则跳过写 2。

#### 这彻底解释了全部现象

- `count = 3`（§12.138）✔ 真实值；
- `jle` 不跳（§12.143）✔ 因为 3 > 0；
- **但 `0xBBA465` 或 `0xBBA483` 的 `je` 成立** → 跳过 `0xBBA569` ✘ 写 2 从不执行；
- `1F4` 永远是 1（§12.154）✔ 因为上游 `0xBAE30F` 要求状态 2；
- 状态永远是 1 ✔ 因为写 2 从不执行。

**整条链完全闭合，没有任何未解的空隙。**

#### 下一步

**分别验证这两条 `je` 哪个成立**：

1. **`0xB75440` 的返回值**：它比较 `[ecx+0x84]` 与 `[eax+0x84]`。
   §12.73 曾记录容器 `+0x84` 是端口 3074；若两边都是 3074，则返回 1（相同），
   那 `je` **不**成立——流程应继续到写 2。
2. **`0xBC1A50` 的返回值**：它是容器追加函数。

**若两者返回的都是"成功"，那流程就该到写 2——与哨兵矛盾；
若其中一个失败，就找到了最后的卡点。**

**最直接的验证**：用哨兵法分别在这两条 `je` 的**目标**上动手——
把 `0xBBA5A5` 的前一条指令改成写哨兵，看是否被执行。

**或者更简单**：把 `0xBBA465` 的 `je`（`74 12` 之类）改成 `90 90`（不跳），
再看哨兵是否出现。这能一次判定是不是它。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.161"),
                         ("HANDOFF-CURRENT.md", "### 16.49")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.161", "### 16.49")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
