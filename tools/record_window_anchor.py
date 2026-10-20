"""Record round 94: the success window is relative to dw==5, not to process start."""
from pathlib import Path

TEXT = """
### 12.109 成功窗口相对 `dw==5` 而非进程启动；高频采样的锚点要改（2026-10-24 18:2x）

#### 本轮做了什么

给 `poll_counters.py` 加了两个选项：

```
--wait <secs>       等客户端进程出现再开始采样
--with-state        额外读 lobby/obj1 的 status、idx 与 [lobby+0x1F4]
```

然后用 `run_verified.ps1 -SkipWait` 先把服务与 patch 启起来，紧接着以 **0.1 秒**间隔
轮询 15 秒——目的是看清"启动后 0–3 秒"内 `success` 与 `status` 的演化。

#### 结果：采到的是尚未初始化的阶段

```
  0.00    success=0  bytes=0  status=None  idx=None  1F4=None
  0.10    success=0  bytes=0  status=None  idx=None  1F4=None
  …
  3.71    success=0  bytes=0  status=None  idx=None  1F4=None
```

`status` 为 `None` 说明 `ReadProcessMemory` 失败——因为此时 `[0xE85C68]`（lobby 指针）
仍是 0，顺着它读 `+0x1F8` 自然失败。

**即：客户端进程已经存在，但还没跑到初始化 lobby 的阶段。**

#### 这修正了一个重要理解

§12.108 说的"成功后 0–3 秒"是**相对于客户端初始化完成**（`dw` 变成 5）而言的，
不是相对于进程创建。二者之间隔着十几秒的加载与登录流程。

**所以高频采样必须锚定在 `dw == 5` 那一刻，而不是进程出现那一刻。**

#### 下一步的具体做法

把轮询器改成：

1. 先等客户端进程出现；
2. 再循环等待 `dw`（`0x84ABA40`）变成 `5`；
3. 一旦 `dw == 5`，立刻以 0.05–0.1 秒间隔记录
   `success`、`status`、`idx`、`1F4`，持续 10 秒。

这样能看清：在 `dw=5` 之后，`success` 是否还会从 13 继续增长、`idx` 何时到 5、
`status` 何时从 1 变 3、以及**有没有任何一刻 `status == 1` 而 `success` 在增长**。

**那最后一问就是全部问题的核心**：

- 若存在"`status == 1` 且 `success` 增长"的瞬间 → 说明 `Add` 本该写 2，需查为何没写；
- 若 `status` 在 `success` 增长前就已变 3 → 说明窗口更早关闭，必须让索引涨得更慢，
  或让 `dw=5` 之后的第一次收包提前。

#### 附带确认

本轮也验证了 `run_verified.ps1 -SkipWait` 可用：它会在约 5 秒内起好服务、应用补丁并
返回，把控制权交回调用方——这让"启动后立刻观测"成为可能。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.109"),
                         ("HANDOFF-CURRENT.md", "### 15.97")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.109", "### 15.97")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
