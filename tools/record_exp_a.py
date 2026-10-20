"""Record experiment A: writing [D+0xC]=1 makes the FE ladder advance by itself."""
from pathlib import Path

TEXT = """
### 12.41 ★★ 实验 A：只写 `[D+0xC]=1` 即可让 FE 梯自然前进（2026-10-23 05:0x）

#### 这是 25 轮来第一次观测到 FE 梯自发推进

配置：15 处补丁，**不强推 G1**，**不改** `script_state`/`fe_final`，只在 `dw=5`
后写一次 `[D+0xC]=1`。

```
dw=5  G1=0  gate=0  [D+0xC]=0
  wrote [D+0xC]=1
  after: [D+0xC]=1
t=10s:  dw=5 ui=9 G1=0 gate=0 FE=5
t=20s:  dw=5 ui=9 G1=1 gate=0 FE=5   <- ★ 自发从 0 前进到 1
t=30s…100s: G1=1 gate=0 FE=5          <- 稳定停在 1
```

**对比**：不写这一位时（§12.38 的基线），`G1` 在 90 秒内始终为 0。

所以 `[D+0xC]=1` 确实是 FE 梯第一级（`G1: 0 -> 1`）的**唯一必要条件**，
`fix_firstlogin` 这一步本身是**正确且有效**的。

#### 但停在 G1=1

`G1=1` 之后梯子需要 `0x730C50`（FE-loaded）返回 1 才能继续，而该函数要求
`[0xE59D20] ∈ {4,6}`——实测 `FE_state = 5`，所以卡住。

`FE_state` 从 5 到 6 的唯一途径是 `0x6217BF`，它要求
`[lobby+0x1F4] == 2`；而 pump 每帧把 `[lobby+0x1F4]` 写回 1（§12.31/§12.38）。

#### 这推翻了 §12.36 的判断

§12.36 认为「firstlogin 修复把客户端推离大厅」，理由是加了它之后画面
从空白前端变成代号页。但本实验证明：

- 写 `[D+0xC]=1` 单独存在时，FE 梯前进到 `G1=1`，画面停在代号页；
- 不写时，FE 梯停在 `G1=0`，画面是空白前端。

两者都不是大厅。**真正的问题不是写不写这一位，而是 `G1=1` 之后被
`0x730C50` 挡住**。§12.36 的结论应修正为：**写这一位是必要的**，
而 `fix_fe_loaded`（改 `script_state`/`fe_final`）是无效的，因为它改的两个
变量都不参与 `0x730C50` 的判定（该函数看的是 `[0xE59D20]`）。

#### `script_state` / `fe_final` 确认无效

`0x730C50` 的完整判定条件（§12.21）是：

```
[0xE59D20] ∈ {4, 6}     <- FE 阶段
0x803700 非空
0xB7A680(obj) == 2
[0x84ABABC] == 1        <- 这是 script_state
0x7F68A0 ×2 为真
[0x82C4A86] != 0        <- 这是 fe_final
```

`script_state` 与 `fe_final` 确实是判定条件之一，但**第一个条件
`[0xE59D20] ∈ {4,6}` 不满足时，后两个写不写都无所谓**。这就解释了为什么
`fix_fe_loaded` 没产生任何可见效果。

#### 下一步：把 G1 从 1 推到 2

需要 `FE_state` 变成 4 或 6。两条途径：

1. **让它自然发生**：需要 `[lobby+0x1F4]` 变成 2，而 pump 的判定
   `0xBAF040` 需要 `0xBBA760(key=0, 1288B)` 在容器里查到内容（§12.32/§12.33）。
   容器每帧新建且为空，填充代码在游戏逻辑层——闭环。
2. **直接试 `FE_state` 的其它转换**：`0x6216B9` 会写 3 或 5，`0x6217D0` 写 4
   要求原值 3。若能把 `FE_state` 置 **3**，pump 的判定分支会走 `0x6217D0`
   写 4，从而满足 `0x730C50` 的第一个条件——**这比强写 4 更接近原生路径**。

第 2 条值得一试：写 `FE_state = 3` 而不是 4，让客户端自己走到 4。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.41"),
                         ("HANDOFF-CURRENT.md", "### 15.29")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.41", "### 15.29")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
