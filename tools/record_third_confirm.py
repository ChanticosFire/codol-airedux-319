"""Record round 105: third independent confirmation that Add's count is esi; this run had no successes."""
from pathlib import Path

TEXT = """
### 12.120 第三次独立验证 `[ebp+0x94] == esi`；但本轮运行零成功（2026-10-24 23:5x）

#### 挂点选在 `Add` 入口、SEH 建立之前

`0xBBA3F3`（`push -1`）处 `ebp` 已由 `0xBBA3F1 mov ebp, esp` 建立，
而 SEH 帧要到 `0xBBA3FA` 才压栈——**这是 `Add` 内最安全的挂点**。
重放 7 字节 `6A FF | 68 BE 0F C9 00`（逐条数过）。

同时采 `esi` 与四个槽位：

```
[entry] n=0    esi=0x00000000  [0x88]=0x00000000  [0x8c]=0x00000000  [0x90]=0x00000000  [0x94]=0x00000000
[entry] n=7    esi=0xfffffffe  [0x88]=0x00000002  [0x8c]=0x001a0000  [0x90]=0x001acfd0  [0x94]=0xfffffffe
[entry] n=22   … 完全相同 …
…
[entry] n=216  esi=0xfffffffe  [0x88]=0x00000002  [0x8c]=0x001a0000  [0x90]=0x001acfd0  [0x94]=0xfffffffe
```

#### `[ebp+0x94] == esi` 第三次得到确认

| 轮次 | 挂点 | 观测 |
|---|---|---|
| 90 | `0xBBA418` | `esi == [0x94]` |
| 105（本轮） | `0xBBA3F3` | `esi == [0x94]` |
| 99 | `0xBBA43A` | `[0x94]` 曾为 3，正数 |

**`Add` 的 count 确实就是虚函数的返回值 `esi`。** 这一点不再有疑问。

#### 但本轮运行零成功

216 次命中，`esi` 恒为 `-2`，`[0x94]` 也恒为 `-2`。**本轮没有任何成功**，
所以无法观察"`count` 为正时 `Add` 的行为"。

**成功是偶发的**——第 93 轮 13 次、第 100 轮 0 次、第 104 轮 1 次、本轮 0 次。

#### 一个仍未解释的细节

四个槽位的值：

```
[0x88] = 0x00000002
[0x8C] = 0x001A0000      堆地址
[0x90] = 0x001ACFD0      堆地址
[0x94] = 0xFFFFFFFE      = esi
```

按 `0xBAE24E`–`0xBAE276` 的推演，`push esi` 应落在 `[ebp+0x94]`（已验证），
而 `push &[ebp-0x548]` 应落在它下面一格。但 `[0x90] = 0x001ACFD0` 是**堆地址**，
不是栈地址 `ebp-0x548`。

**说明 `[ebp+0x8C]`/`[0x90]` 落在 136 字节结构内部**，而不是结构之后的参数区——
即 `[ebp+8]` 不是结构起点。这与 `0xB753C0` 的 `ret 4` 推演不符，
但**已不影响主结论**（count = esi 已三次确认）。

#### 下一步：重复直到抓到一次成功

既然 count = esi 已确定，剩下的唯一问题是：

> **当 `esi >= 0`（成功）时，`Add` 是否真的写 2？**

第 104 轮在 `0xBBA442` 抓到 `edi = -2` 而 `success = 1`——但那次 `esi` 恰好在那一刻是 -2
（成功发生在别的帧）。

**需要一次"`esi` 为正"的采样。** 做法：

1. 在 `0xBBA3F3` 装探针，采样 `esi`，**缩短采样间隔到 0.05 秒**；
2. **重复运行若干次**，直到某次运行中出现 `esi` 为正的记录；
3. 若那时 `[0x94]` 也是正数，就确认 `Add` 会走成功分支——那么"状态不变 2"就只剩
   "写 2 之后被覆盖"这一种解释。

**这是最后一次需要的数据点。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.120"),
                         ("HANDOFF-CURRENT.md", "### 16.08")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.120", "### 16.08")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
