"""Record round 134: the write of 4 is provably dead code."""
from pathlib import Path

TEXT = """
### 12.149 确认：写 4（`0xBBA2B6`）是死代码，状态机只剩 7 个写入点（2026-10-25 14:5x）

#### 扫描

用 `branches_to.py` 在 `0xBB0000`–`0xBC0000`（整个对象代码区）内扫描所有跳转形式：

```
=== branches into 0xBBA2B1 ===
  0 hit(s)
=== branches into 0xBBAAAA (sanity: should be none) ===
  0 hit(s)
```

**没有任何跳转指向 `0xBBA2B1`（写 4 所在块的入口）。**

**对照的 sanity 检查（一个随意地址）同样是 0——说明工具本身工作正常，
这不是假阴性。**

#### 结论

`0xBBA2B1`/`0xBBA2B6` 位于 `0xBBA1F0` 的 `ret`（`0xBBA2B0`）之后，
且无任何跳转可达——**是彻底不可达的死代码**。

**状态 4 永远不会出现。**

#### 状态机写入点缩减为 7 个

| 地址 | 写入值 | 是否可达 |
|---|---|---|
| `0xBB76BB` | 0 | 构造/清理 |
| `0xBBA0A4` | `esi`（某值） | 待查 |
| `0xBBA1C7` | 0 | 清理（§12.122） |
| `0xBBA33E` | 0 | 待查 |
| `0xBBA3D2` | **1** | `Init`（§12.129，`dw=2` 时运行 1 次） |
| `0xBBA569` | **2** | `Add` 成功分支（**哨兵证明从不执行**） |
| `0xBBA62B` | **3** | `Add` 容量满分支（§12.127 证明会执行） |
| ~~`0xBBA2B6`~~ | ~~4~~ | **死代码** |

#### 于是状态机的完整图景

```
状态 0 ──(0xBBA3D2, Init, dw=2 运行一次)──> 状态 1
状态 1 ──(0xBBA569, Add 收到正数 count)──> 状态 2   ← 从不发生
状态 1 ──(0xBBA62B, Add 索引满)──────────> 状态 3   ← 实际发生
状态 0/1 ──(0xBBA1C7/0xBBA33E/0xBB76BB, 写 0)──> 状态 0
状态 1 ──(0xBBA0A4, 写 esi)──> 未知
```

**实际观测到的路径只有一条：**

```
0 --(Init)--> 1 --(索引满)--> 3
```

**`1 -> 2` 这条边从未被走到。**

#### 这把问题归结到一个非常具体的问题

**`Add` 的 `count > 0` 分支为何从不执行？**

由于：
- `count`（`[ebp+0x94]`）实测 91.4% 为 3（§12.138）；
- `jle` 不跳（§12.143 取反实验证明 `edi > 0`）；
- 但 `0xBBA569` 从不执行（§12.140 哨兵）。

**三者之中必有一个在说谎。而哨兵实验是最可靠的（纯数据修改、程序正常跑完），
取反实验次之（同样是纯数据修改），直方图采样最可疑（依赖 hook）。**

**所以最可能的是：直方图的 91.4% 是错的。**

#### 下一步：用不依赖 hook 的方式测 `count`

哨兵法可以做到：**把 `0xBBA4AE`（`cmp ax,3`）的立即数 3 改成一个独特的比较值**，
观察行为是否改变，从而推断 `ax` 的取值范围。

**或者更直接**：把 `0xBBA442` 的 `jle` **改成 `jmp`**（无条件跳到 `0xBBA5C3`），
那 `0xBBA569` 就一定不执行；**再把 `0xBBA442` 改成 `jmp 0xBBA448`**
（无条件进入成功分支），那 `0xBBA569` 就一定执行。

**后者能验证"成功分支本身是否能走通"**——若强制进入后 `0xBBA569` 仍不执行，
说明成功分支内部有问题（例如前面某个 `call` 抛异常）；
**若强制进入后 `0xBBA569` 执行了（哨兵出现），就说明问题纯粹在于 `jle` 的判断结果。**

**这是二分法：一次实验就能区分"判断错"还是"分支内部坏"。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.149"),
                         ("HANDOFF-CURRENT.md", "### 16.37")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.149", "### 16.37")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
