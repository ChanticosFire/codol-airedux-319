"""Record round 115: Init runs before the write of 2, overturning the assumed order."""
from pathlib import Path

TEXT = """
### 12.130 ★★★ `Init` 在写 2 之前运行：`obj1[0x120]` 在写 1 前是 **0**（2026-10-25 05:2x）

#### 采样

在 `0xBBA3D2`（`Init` 的写 1）装探针，同时读 `obj1[0x120]`、`obj1[0x130]`、`dw`：

```
[ord] n=0  eax=0x00000000  [0x120]=0x00000000  [0x130]=0x00000000  dw=0
[ord] n=1  eax=0x001AD005  [0x120]=0x00000000  [0x130]=0x00000000  dw=2     ← ★ 写 1 之前状态是 0
[ord] unreadable - process gone?
```

**写 1 执行的那一刻，`obj1[0x120]` 仍是 `0`，索引也是 `0`。**

#### 这推翻了"写 2 在前"的推断

§12.129 曾推理"写 2 在前、写 1 在后"，依据是"最终状态是 3"。但本轮直接测到
**写 1 之前状态是 0**——说明 `Init` 是 `obj1` 的**第一次**初始化，
它把状态从 0 置为 1。

**而 `Add` 的入口检查是 `cmp [ebx+0x120], 1` / `jne`——状态为 0 时会直接返回，
根本走不到写 2。**

**所以写 2 必然发生在 `Init` 之后。**

#### 于是时序是

```
obj1 创建      -> status = 0（未初始化）
Init           -> status = 1，索引 = 0
Add(count>0)   -> 写 status = 2 -> jne -> 返回（索引不推进）
后续帧          -> 入口 check: status=2 -> jne -> 返回
```

**按此推演，状态应当永久保持 2。** 但实测是 3。

#### 矛盾重新打开

三条已知事实放在一起：

| 事实 | 来源 |
|---|---|
| `Init` 先把 status 置 1 | 本轮 |
| 写 2 在 `dw=2` 执行，且 `ebx == obj1` | §12.108 / §12.128 |
| 最终 status 是 3，且 `Init` 只运行 1 次 | §12.94 / §12.127 |

**若写 2 在 `Init` 之后，`jne` 应拦住后续推进，status 保持 2。**
**但 status 是 3，说明 `0xBBA62B`（写 3）执行了，而它需要 `jne` 不成立。**

#### 唯一剩下的可能：`Init` 运行了不止一次

本轮只抓到 `n=1` 一次命中就崩溃了，**不能排除更早或更晚还有一次**。
若 `Init` 实际运行两次：

```
Init #1  -> status = 1, idx = 0
Add      -> status = 2
Init #2  -> status = 1, idx = 0     ← 抹掉 2，同时把索引也清零
空闲帧    -> status=1 不短路 -> idx 推进
idx 满    -> status = 3
```

**这与所有观测一致，且解释了"索引为何能从 0 重新涨到 5"**
（§12.127 的轨迹里 `obj1` 出现时 `idx=0`，随后涨到 5）。

#### 下一步：用轮询而非 hook 数 `Init` 的次数

`0xBBA370` 与 `0xBBA3D2` 的 hook 每次都导致客户端在 1 次命中后退出
（§12.111、§12.114、本轮），**说明 `Init` 内部的挂点不稳定**。

**改用零干扰的方式**：轮询 `obj1[0x120]` 与 `obj1[0x130]` 的 5ms 轨迹，
从 `obj1` 出现（`[0xE85C68]+0x1F8` 非零）开始。

**若 `Init` 运行两次，会看到索引被"重置回 0"的现象**——
即 `idx` 从某个值突然变回 0。**这是 `Init` 的签名特征**（它同时写 status=1 与 idx=0）。

**这比 hook 安全得多，且能直接数出 `Init` 的次数。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.130"),
                         ("HANDOFF-CURRENT.md", "### 16.18")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.130", "### 16.18")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
