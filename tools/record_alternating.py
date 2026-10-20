"""Record round 116: the index never resets, so Init runs once; and idx advances on separate frames."""
from pathlib import Path

TEXT = """
### 12.131 ★★★ 5ms 轨迹：索引单调递增、无重置；`idx` 与 `success` 在不同帧推进（2026-10-25 05:5x）

#### 完整轨迹

5ms 间隔、`--only-changes`，从进程出现开始：

```
     t   success  delta  bytes  status  idx  1F4
  0.00         0               0    None  None  None
 12.88         0     +0       0    None  None     1
 17.58         1     +1     351    None  None     1
 18.05         1     +0     351       1     0     1   ← obj1 出现，status=1, idx=0
 18.07         2     +1     382       1     0     1
 18.11         3     +1     414       1     0     1
 18.58         3     +0     414       1     1     1   ← idx +1（success 不变）
 18.61         4     +1     445       1     1     1   ← success +1（idx 不变）
 18.65         5     +1     477       1     1     1
 19.08         5     +0     477       1     2     1   ← idx +1
 19.12         6     +1     508       1     2     1
 19.15         7     +1     540       1     2     1
 19.59         7     +0     540       1     3     1   ← idx +1
 19.62         8     +1     571       1     3     1
 19.65         9     +1     603       1     3     1
 20.09         9     +0     603       1     4     1   ← idx +1
 20.12        10     +1     634       1     4     1
 20.15        11     +1     666       1     4     1
 20.59        11     +0     666       1     5     1   ← idx +1（满）
 20.62        12     +1     697       3     5     1   ← status 直接跳 3
 20.65        13     +1     729       3     5     1
```

#### 两个决定性结论

1. **`idx` 从 0 单调递增到 5，从未重置**——所以 `Init` 只运行了**一次**。
   §12.130 提出的"`Init` 运行两次"假设**被推翻**；

2. **`idx` 的 +1 与 `success` 的 +1 发生在不同时刻**：
   - `t=18.58`：`idx` 0→1，`success` 保持 3
   - `t=18.61`：`success` 3→4，`idx` 保持 1

   **即索引推进与成功接收是交替的、来自不同的帧。**

#### 这给出一个新的、更精确的图景

`idx` 每约 0.5 秒推进一次（`t=18.58, 19.08, 19.59, 20.09, 20.59`，间隔约 0.5 秒），
而 `success` 在同一 0.5 秒窗口内涨两次。

**这与 §12.88 的"virtualizer 每帧调用、51 次/秒"严重不符**——
若每帧都调用 `Add`，索引应当涨得远快于 0.5 秒一次。

**实际观测（约 2 次/秒）说明：`Add` 真正被调用的频率约为 2 次/秒，
而不是 51 次/秒。**

这直接颠覆了此前"每帧 +1"的模型。回溯 §12.81 的计数（`0xBB15E0` 约 21 次/秒），
那是**收包函数**的调用频率；而 `Add` 的调用频率受限于别的东西。

#### 于是"索引为何涨满"有了新的解释

- `Add` 约 2 次/秒；
- 其中一部分帧 `count <= 0`（推进索引），一部分帧 `count > 0`（写 2）；
- **从 `t=18.05` 到 `t=20.59` 约 2.5 秒内索引涨满 5**，与 2 次/秒吻合。

#### 下一步

既然 `idx` 与 `success` 交替推进，**说明 `Add` 的调用有两种结果轮换**：
一次 `count<=0`、一次 `count>0`。

**若 `count>0` 的那次真的写了 2，状态就该变 2。**

但观测到状态一直是 1，直到索引满才变 3。

**所以 `count>0` 的那次并未写 2**——这与 §12.106 采到 `esi=3/4` 直接冲突。

**需要重新确认 `0xBBA569` 的命中时机**：§12.108 只抓到 1 次命中（`dw=2`），
而 `t=18.05` 之后才是索引增长期。**若写 2 只在 `dw=2` 时发生过一次，
而之后的 `count>0` 帧都没走到它，那说明 `0xBBA442` 的 `jle` 在那些帧里仍然跳了**
——即那些帧的 `edi` 仍 <= 0。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.131"),
                         ("HANDOFF-CURRENT.md", "### 16.19")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.131", "### 16.19")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
