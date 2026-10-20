"""Record round 97: hooking immediately fails because the image is not mapped yet."""
from pathlib import Path

TEXT = """
### 12.112 进程出现 ≠ 可挂钩：`.text` 尚未映射，读到全 0（2026-10-24 19:5x）

#### 本轮按计划"先装钩子"

给 `probe_reg.py` 加 `--wait`，让它等客户端进程出现后立刻装 hook，避免再一次
错过 `dw=5` 之后那 2 秒的窗口。

结果：

```
[early] client appeared after 0.2s
byte mismatch at 0xbb172b: want 8bc65e1115a45ce800 got 000000000000000000
```

**进程出现后 0.2 秒，目标地址读到的是全 0**——说明此时 PE 映像的 `.text` 段
还没被映射到该虚拟地址。`probe_reg.py` 的字节校验（这是第 64 轮教训的产物）
正确地拒绝了这次安装。

#### 三个相继失败揭示的时序结构

| 阶段 | 时间 | 状态 |
|---|---|---|
| 进程创建 | t=0 | 映像未映射，`.text` 读不到 |
| 映像映射完成 | t≈? | 可以挂钩 |
| `dw=5`（前端就绪） | t≈19s | 窗口开始 |
| 成功窗口关闭 | t≈21s | 此后永远静止 |

**所以可挂钩的时间窗是"[映射完成, dw=5)"**，而这一段的起点尚未测量。

#### 下一步：等字节就绪再装

`probe_reg.py` 应改为"轮询目标地址的字节，直到与预期一致为止，然后立刻装 hook"：

```
while 未超时:
    if read(hook, len(orig)) == orig:
        break
    sleep 20ms
安装 hook
```

这样既能避开"映像未映射"，又能在 `dw=5` 之前很久就把钩子装好——
因为从映射完成到 `dw=5` 之间约有十几秒的加载流程，足够宽裕。

**这是把"装钩子"这件事彻底做对的关键改动**，也应当是后续所有 hook 实验的
标准做法。实现上只需在 `--wait` 之后加一个"等字节就绪"的循环，
并在日志里打印"字节就绪用了多久"，从而顺便测出"映射完成"的时刻。

#### 附带的确定性收获

本轮虽然没采到数据，但确认了两件事：

1. `probe_reg.py` 的字节校验有效——它阻止了一次注定失败的安装；
2. 客户端从进程创建到可挂钩之间存在一个不可忽略的间隔，
   任何"立刻挂钩"的尝试都必须先过字节校验这一关。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.112"),
                         ("HANDOFF-CURRENT.md", "### 16.00")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.112", "### 16.00")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
