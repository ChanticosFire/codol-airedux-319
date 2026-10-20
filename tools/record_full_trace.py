"""Record round 112: the full startup trace, and the first success predates obj1 itself."""
from pathlib import Path

TEXT = """
### 12.127 ★★★ 完整启动轨迹：状态从未经过 2；首次成功早于 obj1 的创建（2026-10-25 03:5x）

#### 首次拿到从进程出现到 `dw=5` 之后的完整轨迹

以 20ms 间隔轮询，`--only-changes` 只输出变化：

```
     t   success  delta  bytes  status  idx  1F4
  0.00         0               0    None  None  None
 12.86         0     +0       0    None  None     1
 17.08         1     +1     351    None  None     1   ← ★ 成功时 obj1 还不存在
 17.59         1     +0     351       1     0     1   ← obj1 出现，状态=1
 17.67         3     +2     414       1     0     1
 18.10         3     +0     414       1     1     1
 18.14         4     +1     445       1     1     1
 18.17         5     +1     477       1     1     1
 18.62         5     +0     477       1     2     1
 18.64         6     +1     508       1     2     1
 18.68         7     +1     540       1     2     1
 19.11         7     +0     540       1     3     1
 19.15         8     +1     571       1     3     1
 19.17         9     +1     603       1     3     1
 19.62         9     +0     603       1     4     1
 19.64        10     +1     634       1     4     1
 19.68        11     +1     666       1     4     1
 20.11        11     +0     666       1     5     1   ← 索引已满，状态仍 1
 20.15        12     +1     697       3     5     1   ← 直接跳 3
 20.19        13     +1     729       3     5     1
```

#### 三个确定的结论

1. **状态从未经过 2**——从 `None` 直接到 `1`，再从 `1` 直接到 `3`。
   20ms 间隔不可能漏掉一个"持续存在"的 2。若写 2 之后 `jne` 正确跳走，
   状态 2 应当保持到 `dw=5` 之后很久，必然被采到；

2. **首次成功（t=17.08）发生在 `status=None` 时**——那时 lobby 指针还是 0，
   `obj1` 尚未创建，`Add` 自然也还不存在。
   **所以那一次成功与 `Add` 完全无关**，它来自客户端的其它收发流程（可能是 TLS/LSG 通道）；

3. **`obj1` 出现后（t=17.59）**，`success` 从 1 增到 13、`idx` 从 0 增到 5，
   **两者严格同步**（每次 `success` +2 的间隔里，`idx` 恰好 +1 一次）。
   **这种同步只在 `count<=0` 路径上成立**——成功路径写 2 后会立即返回，不推进索引。

#### 于是得到一个尖锐的推论

若 `Add` 在 t=17.59 之后任何一次调用中拿到了正数 `count`（§12.106 已证实会发生，
值为 3/4），它就应当写 2、`jne` 跳走、**索引不再推进**。

**但索引在每次成功后仍然 +1。**

**所以：`Add` 在 `obj1` 存在之后的每次调用中，拿到的 `count` 都是 `<= 0`。**

#### 这与 §12.106 的"抓到 esi=3/4"如何协调

§12.106 的采样是在 `0xBBA3F3`（`Add` 入口）做的，抓到 `esi=3`、`[0x94]=3`。
而 §12.108 在 `0xBBA5AB`（写 2 之后）抓到过命中。

**两件事可能发生在启动的不同阶段**：

- `0xBBA5AB` 的命中发生在 **`dw=2`**（§12.108 记录），即 **t≈12–17 之间**；
- 而 `obj1` 出现在 **t=17.59（`dw` 从 2 走到 5 的过程中）**。

**若写 2 发生在 `obj1` 创建之前，那它写的是另一个对象**——`[ebx+0x120]` 的 `ebx`
在 `Init` 之前可能指向临时对象，写 2 与后续的 `obj1` 无关。

**这能解释一切**：

```
t≈12-17 (dw=2)   某临时对象的 Add 被调用，count>0，写 2 —— 但那不是 obj1
t=17.59          obj1 创建，Init 置 status=1、idx=0
t=17.59-20        obj1 的 Add 每次调用 count<=0 -> 索引推进
t=20.15          索引满 -> 写 3
```

#### 下一步：确认 `ebx` 在 `0xBBA569` 处指向的是哪个对象

在 `0xBBA569` 之前（例如 `0xBBA5AB`）采样 `ebx`，与当时的 `obj1` 指针比较：

- **若 `ebx != obj1`** → 写 2 作用在别的对象上，与 `obj1` 无关，
  那"obj1 的状态为何是 3"就纯粹是索引推进的结果，与写 2 无关；
- **若 `ebx == obj1`** → 写 2 确实作用在 obj1 上，问题回到"为何被覆盖"。

**这是目前最有信息量的采样点**，且 `0xBBA5AB` 已验证可挂（§12.108）。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.127"),
                         ("HANDOFF-CURRENT.md", "### 16.15")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.127", "### 16.15")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
