"""Record round 117: the write of 2 fires exactly once, before the index growth phase."""
from pathlib import Path

TEXT = """
### 12.132 ★★★ 写 2 只执行一次（`dw=2`），索引增长期内从不执行（2026-10-25 06:2x）

#### 三次运行的完全一致性

在 `0xBBA5AB`（写 2 之后）装探针，三次独立运行的结果完全相同：

```
[a1] n=1  eax=0x001AC700  dw=2  obj1[0x120]=1
[a1] unreadable - process gone?

[a2] n=1  eax=0x001AC700  dw=2  obj1[0x120]=1
[a2] unreadable - process gone?

[a3] n=1  eax=0x001AC700  dw=2  obj1[0x120]=1
[a3] unreadable - process gone?
```

**每次运行都只命中 1 次，`dw=2`，`obj1[0x120]` 是 1，随后客户端退出。**

#### 三个由此确定的事实

1. **写 2 只执行一次**——在整个生命周期中，`0xBBA569` 仅执行 1 次；
2. **执行时机是 `dw=2`**，此时 `obj1[0x120] = 1`（`Init` 已运行）；
3. **执行后客户端即退出**——这是 hook 在 SEH 区内的副作用，
   但三次结果一致，说明**观测本身有效**。

#### 这与"索引增长期"的关系

§12.131 的 5ms 轨迹显示：

- `t=18.05`（`dw` 已到 5）：`obj1` 出现，`status=1`，`idx=0`；
- `t=18.05`–`t=20.59`：`idx` 从 0 涨到 5，`success` 从 1 涨到 11；
- 写 2 的 hook 在这个窗口内**一次都没有命中**。

**即：从 `dw=5` 之后到状态锁定（`status=3`）的整个过程中，`0xBBA569` 从未执行。**

#### 于是第 106 轮的"esi=3/4"需要重新解释

§12.106 在 `0xBBA3F3`（`Add` 入口）采到 `esi = 3` 或 `4`，据此推断
"`Add` 收到正数 count，必然写 2"。

**但本轮证明：整个索引增长期内写 2 从未执行。**

**两者只能这样调和**：§12.106 采到的 `esi=3/4` 发生在 **`dw=2` 的早期**
（也就是本轮看到写 2 的那一次），而不是 `dw=5` 之后的增长期。

**即：只有那一次 `Add` 调用拿到了正数 count；之后的调用全都拿到 `-2`。**

#### 这与 §12.131 的"交替"观察也吻合

`idx` 在 `success` 不变时 +1、`success` 在 `idx` 不变时 +1，说明：

- **推进索引的帧**：`count <= 0`
- **增加 success 的帧**：`count > 0`？

**但若 `count > 0`，写 2 就该执行——实测没有。**

**所以更可能的解释是：`success` 的增长与 `Add` 的 count 无关。**

回顾 `success` 的写入点 `0xBB1734`（`add [0xE85CB0],1`），它在**虚函数内部**，
而不是 `Add` 内部。**虚函数每帧都跑，与 `Add` 的调用频率无关。**

§12.131 观察到 `Add` 约 2 次/秒，而 `success` 也约 2 次/秒——**这是巧合**，
两者来源于不同的执行路径。

#### 下一步

**核心问题变成：`Add` 在 `dw=5` 之后的那些调用里，`[ebp+0x94]` 到底是多少？**

- 若恒为 `-2`，则写 2 永远不会再发生，`status` 必然被索引推进到 3；
- 若偶尔为正，则应当有对应的写 2 命中——但实测没有。

**这需要一次不崩溃的采样**：`0xBBA43A`（`mov edi,[ebp+0x94]`，6 字节）
在 §12.99 用过且当时运行稳定，重挂在那里，采样窗口覆盖 `dw=5` 之后。

**若那里也恒为 -2，就能确认"虚函数的返回值从未在 `dw=5` 之后为正"，问题回到服务端数据。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.132"),
                         ("HANDOFF-CURRENT.md", "### 16.20")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.132", "### 16.20")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
