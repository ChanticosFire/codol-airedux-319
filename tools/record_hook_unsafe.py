"""Record round 101: hooking 0xBBA569 appears to stop the client reaching dw==5."""
from pathlib import Path

TEXT = """
### 12.116 挂在 `0xBBA569` 时 `dw` 始终为 0：客户端未跑到初始化（2026-10-24 21:5x）

#### 重测结果

同一挂点、同一流程再跑一次，并把 `dw`（`0x84ABA40`）也纳入采样：

```
[w2b] image ready after 2.75s
[w2b] hook 0xbba569 -> cave 0x10dd0000
[w2b] n=0  chain[0x84ABA40]=0x00000000  chain[0xE85CB0]=0x00000000
[w2b] final n=0  slots=(0, 0)
```

**`dw` 全程为 0。** 正常情况下它应当在约 19 秒后变成 5。

#### 两次连续失败指向同一个原因

| 轮次 | 挂点 | `dw` | `success` | 写 2 命中 |
|---|---|---|---|---|
| 100 | `0xBBA569` | 未测 | **0** | 0 |
| 101 | `0xBBA569` | **0** | **0** | 0 |

前一挂点 `0xBBA43A`（第 99 轮）与 `0xBB172B`（第 98 轮）都能让客户端正常跑到
`dw=5` 并产生成功，而**换到 `0xBBA569` 后连续两次都停在 `dw=0`**。

**高度怀疑 `0xBBA569` 这个挂点本身有问题。**

#### 可能的原因

`0xBBA569` 的指令是 `mov dword ptr [ebx+0x120], 2`，编码
`C7 83 20 01 00 00 02 00 00 00`，共 **10 字节**。

把它替换成 `jmp cave`（5 字节）+ 5 个 `nop`，再在 cave 里重放这 10 字节——
**问题在于这条指令写的是 `[ebx+0x120]`**，而 `ebx` 在 `Add` 里指向被操作的对象。
若 cave 中 `pushad`/`popad` 与重放之间有任何偏差，或 cave 所在内存页的
执行属性/缓存行为与 `.text` 不同，写入可能落到错误位置，进而破坏对象状态。

更直接的风险：**`pushfd`/`pushad` 会改变栈内容**，而这段代码处在
`Add` 的 SEH 保护区内（`0xBBA3F5` 已 `push 0xC90FBE` 建立异常帧）。
在 SEH 作用域内改动栈布局，可能让后续的异常处理/栈展开失效。

#### 结论与下一步

**`0xBBA569` 不适合作为挂点。** 之前能稳定工作的 `0xBBA43A`、`0xBB172B`
都不在 SEH 作用域内（前者在 `Add` 的判定段、后者在 `0xBB15E0` 内），
而 `0xBBA569` 位于 `Add` 的 SEH 保护区内。

**替代方案**：不挂钩，改为**轮询 `obj1[0x120]` 的高频快照**（0.02 秒间隔）。

从 §12.110 已知状态在 `dw=5` 后约 1.6 秒才变 3，若 `0xBBA569` 真的执行过，
状态会短暂变成 2 —— **0.02 秒的采样间隔足以捕获这个瞬态**（第 77 轮曾在
0.1 秒间隔下抓到过 `1/4` 的中间态）。

这比继续在 SEH 区内挂钩安全得多，且能直接回答"状态是否曾变成 2"。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.116"),
                         ("HANDOFF-CURRENT.md", "### 16.04")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.116", "### 16.04")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
