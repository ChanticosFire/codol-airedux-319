"""Record round 100: the write-2 site never ran, but neither did any success this time."""
from pathlib import Path

TEXT = """
### 12.115 `0xBBA569` 计数为 0，但本轮运行的成功计数也是 0（2026-10-24 21:2x）

#### 结果

按计划在 `0xBBA569`（`mov dword ptr [ebx+0x120], 2`，10 字节
`C7 83 20 01 00 00 02 00 00 00`）装计数器，同时读成功计数：

```
[w2] image ready after 2.93s
[w2] hook 0xbba569 -> cave 0x11200000
[w2] n=0  eax=0x00000000  chain[0xE85CB0]=0x00000000
[w2] final n=0  eax=0x00000000  slots=(0,)
```

**写 2 的指令一次都没执行。**

#### 但这个结果无法解读，因为成功计数也是 0

`chain[0xE85CB0]` 全程为 **0**，而此前多次运行在 `dw=5` 之后都会涨到 **13**。
**本轮运行根本没有产生任何成功**，所以"写 2 未执行"是必然的——它没有机会执行。

**这不是阴性证据，只是这轮环境没跑到那个状态。**

#### 一个重要的新事实：成功不是每次都会发生

| 运行 | 成功计数 |
|---|---|
| 第 93 轮 | 13 |
| 第 95 轮 | 13（`dw=5` 后从 5 涨到 13） |
| 第 98 轮 | 12（`dw=5` 后继续涨） |
| 第 99 轮 | 12 |
| **第 100 轮** | **0** |

**成功计数在不同运行间从 0 到 13 不等。** 这本身是有价值的信息——说明那 13 次
成功依赖某个**不稳定条件**（例如某次连接是否建立、某个服务是否及时响应），
而不是每次启动都必然发生。

**这直接影响后续实验的可重复性**：任何关于"写 2"的实验都必须先确认
`[0xE85CB0]` 已经非零，否则测的是"没机会执行"而不是"执行了但被覆盖"。

#### 下一步：先确认成功再挂点

下一轮的做法应当是：

1. 启动后先轮询 `[0xE85CB0]`，**等它涨到 >= 1**（最多等 30 秒）；
2. 一旦确认非零，再装 `0xBBA569` 的计数器；
3. 但——`0xBBA569` 只在成功帧执行，而成功集中在 `dw=5` 之后 2 秒内，
   **等发现计数非零时窗口已过**。

**所以更可行的顺序是**：

1. 提前装好 `0xBBA569` 的计数器（`--wait` + `--ready-timeout`，约 3 秒完成）；
2. **同时**让 `probe_reg` 的采样窗口覆盖到 `dw=5` 之后足够久（如 60 秒）；
3. 事后检查 `n`（`0xBBA569` 命中数）与 `chain[0xE85CB0]`（成功数）是否**同时**非零。

**若某次运行 `success > 0` 而 `n == 0`，才能证明"写 2 未执行"；**
若两者都非零，就证明"写 2 确实执行了"，那状态是 3 就说明它**被后续覆盖**。

本轮已把 `probe_reg` 的采样窗口设为 50 秒（覆盖 `dw=5`），但仍未捕获成功——
说明这次真的是环境层面的偶发失败，而非观测时机问题。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.115"),
                         ("HANDOFF-CURRENT.md", "### 16.03")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.115", "### 16.03")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
