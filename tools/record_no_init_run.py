"""Record round 121: the run never initialised, so the call-rate question stays open."""
from pathlib import Path

TEXT = """
### 12.136 本轮运行未初始化（`dw=0`、`Add` 零调用），频率问题仍未回答（2026-10-25 08:2x）

#### 结果

在 `0xBBA3F3`（`Add` 入口，§12.105 曾稳定命中 216 次）装计数器，采样 12 秒：

```
[rate] image ready after 3.01s
[rate] n=0  eax=0x00000000  chain[0x84ABA40]=0x00000000  chain[0xE85CB0]=0x00000000
[rate] final n=0
```

**`Add` 一次都没被调用，`dw` 始终为 0。**

#### 这是环境失败，不是结论

`dw=0` 意味着前端从未到达就绪状态。结合前几轮的经验，这类失败已多次出现：

| 轮次 | 现象 | 当时处理 |
|---|---|---|
| 100 | `success=0`，写 2 计数器 0 | 记为环境失败 |
| 101 | `dw=0`，`0xBBA569` 挂钩后 | 疑为挂点问题 |
| **121（本轮）** | **`dw=0`，`0xBBA3F3` 挂钩后** | 本轮 |

**值得注意的是：本轮用的挂点 `0xBBA3F3` 在第 105 轮是稳定工作过的（216 次命中）。**
所以问题不在挂点本身，而在**这次运行本身没有跑到初始化**。

#### 可能的偶发原因

- 服务未及时就绪（`run_verified.ps1` 的 5 秒等待可能不够）；
- 客户端进程被上一次清理残留影响；
- TLS/LSG 会话建立失败（`login verified` 未检查——`-SkipWait` 模式跳过了那一步）。

**`-SkipWait` 跳过了登录验证**，这是本轮方法上的一个疏漏：之前用 `-SkipWait` 是为了
抢在窗口之前装钩子，但代价是**不再确认登录是否成功**。

#### 下一步：重试，并加一道登录确认

1. 重跑同样的实验（`0xBBA3F3` 计数），**连续 2–3 次**，取其中 `dw` 到达 5 的那些；
2. 若仍频繁失败，改用不带 `-SkipWait` 的启动流程，等 `login verified` 之后再装钩子——
   但那样会错过 `dw=2` 的早期窗口，对"测 `Add` 总调用次数"这个目的影响不大
   （因为关心的是 `dw=5` 之后的频率）。

**关键问题仍未回答**：`Add` 是 2 次/秒还是 21 次/秒。

这个数字决定 §12.135 的"巧合"解释是否成立。下轮必须拿到。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.136"),
                         ("HANDOFF-CURRENT.md", "### 16.24")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.136", "### 16.24")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
