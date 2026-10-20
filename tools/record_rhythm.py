"""Record round 120: precise ordering - idx advances first, then two successes follow."""
from pathlib import Path

TEXT = """
### 12.135 ★★★ 精确时序：`idx` 先 +1，随后 0.03–0.05 秒内 `success` 连续 +2（2026-10-25 07:5x）

#### 轨迹（5ms 间隔）

```
     t   success  delta  bytes  status  idx
  0.00         0               0    None  None
 13.00         0     +0       0    None  None
 17.47         1     +1     351    None  None
 17.94         1     +0     351       1     0   ← obj1 出现
 17.96         2     +1     382       1     0
 18.00         3     +1     414       1     0
 18.47         3     +0     414       1     1   ← idx +1（success 未变）
 18.52         4     +1     445       1     1
 18.55         5     +1     477       1     1
 18.99         5     +0     477       1     2   ← idx +1
 19.02         6     +1     508       1     2
 19.05         7     +1     540       1     2
 19.49         7     +0     540       1     3   ← idx +1
 19.52         8     +1     571       1     3
 19.55         9     +1     603       1     3
 20.02         9     +0     603       1     4   ← idx +1
 20.05        10     +1     634       1     4
 20.09        11     +1     666       1     4
 20.53        11     +0     666       1     5   ← idx +1（满）
 20.56        12     +1     697       3     5   ← status 跳 3
 20.59        13     +1     729       3     5
```

#### 严格的节奏

**`idx` 每次 +1 的时刻**：`18.47`、`18.99`、`19.49`、`20.02`、`20.53`
→ **间隔约 0.52 秒**，非常规律。

**每次 `idx` +1 之后 0.03–0.05 秒内，`success` 连续 +2**（`+1` 两次，间隔 0.03 秒）。

**即：索引推进 → 短暂间隔 → 两次成功。**

#### 这意味着什么

1. **推进索引的那一帧**：`count <= 0`（走 `0xBBA5E6`），状态是 1 所以不短路；
2. **随后的两帧**：`count > 0`（`success` 增长），**按 §12.95 的判定链，它们应当写 2 并返回**。

**若如此，第一次 `count>0` 之后状态就该是 2，此后 `Add` 入口短路，
`idx` 再也不会推进。**

**但 `idx` 继续以 0.52 秒的节奏推进了 5 次，直到满。**

#### 唯一自洽的解释

**`count > 0` 的那两帧并没有真正执行到 `0xBBA569`。**

可能的原因只剩两个：

**（a）`success` 的增长与 `Add` 的 count 无关**

`success` 是 `[0xE85CB0]`，在 `0xBB1734`（**虚函数内部**）递增。
虚函数每帧都跑（§12.80 实测约 21 次/秒），而 `Add` 约 2 次/秒（§12.131）。
**所以"每次 `idx` +1 后 `success` +2"很可能只是两种不同频率的巧合叠加**——
虚函数按自己的节奏增长 `success`，`Add` 按自己的节奏推进 `idx`，两者恰好呈现 0.52 秒的关联。

**（b）`[ebp+0x94]` 在 `0xBBA43A` 处为正，但 `Add` 实际用的 `edi` 不是它**

这需要 `mov edi,[ebp+0x94]` 没有正确执行——但 cave 重放了完整指令，理论上等价。

**（a）的可能性大得多**，因为它与"虚函数 21 次/秒、`Add` 2 次/秒"这两个独立测量吻合。

#### 下一步：直接测 `Add` 的调用频率

在 `0xBBA3F3`（`Add` 入口，已验证稳定，§12.105）装计数器，**只数命中次数、不看值**，
比较 5 秒内的命中数：

- 若约 10 次（2 次/秒）→ 与 `idx` 推进节奏吻合，说明 `Add` 调用频率就是 2 次/秒；
- 若约 105 次（21 次/秒）→ 说明 `Add` 每帧都跑，那 `idx` 的 0.52 秒节奏需要另找解释。

**这是判定 (a) 是否成立的关键，且 `0xBBA3F3` 是已验证稳定的挂点。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.135"),
                         ("HANDOFF-CURRENT.md", "### 16.23")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.135", "### 16.23")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
