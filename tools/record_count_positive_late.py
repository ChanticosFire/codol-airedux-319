"""Record round 118: count is positive after dw=5, and round 117's conclusion was an artefact of crashing."""
from pathlib import Path

TEXT = """
### 12.133 ★★★ `dw=5` 之后 `count` 确实为正；第 117 轮的结论是崩溃造成的假象（2026-10-25 06:5x）

#### 这次采样稳定

`0xBBA43A`（`mov edi, dword ptr [ebp+0x94]`）在 §12.99 用过且运行稳定，本轮重挂同样位置，
**77 次命中、客户端未崩溃**：

```
[late] n=0   edi=0  [0x94]=0x00000000  dw=0
[late] n=3   edi=0  [0x94]=0x00000004  dw=2
[late] n=9   edi=0  [0x94]=0xfffffffe  dw=2
[late] n=15  edi=0  [0x94]=0xfffffffe  dw=2
[late] n=21  edi=0  [0x94]=0xfffffffe  dw=2
[late] n=27  edi=0  [0x94]=0xfffffffe  dw=2
[late] n=33  edi=0  [0x94]=0x00000004  dw=5     ← ★ dw=5 之后仍出现正数
[late] n=39  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=45  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=51  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=57  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=63  edi=0  [0x94]=0x00000004  dw=5     ← ★
[late] n=69  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=75  edi=0  [0x94]=0xfffffffe  dw=5
[late] n=77  edi=0  [0x94]=0x00000003  dw=5     ← ★
[late] final n=77  slots=(3, 5)
```

**`dw=5` 之后 `[ebp+0x94]` 反复出现 3 和 4。**

（`edi` 恒为 0 是正常的——采样在 `0xBBA43A` 执行**之前**，此时 `edi` 尚未被装载。）

#### 这推翻了第 117 轮的结论

第 117 轮在 `0xBBA5AB` 装钩子，**三次运行全部在第 1 次命中后崩溃**（`unreadable`），
因此得出"写 2 只执行 1 次"的结论。

**但那是崩溃造成的假象**：钩子一命中就破坏客户端，只能记录到第一次，
自然看不到后续的命中。

**正确的结论是**：`0xBBA5AB` 这个挂点（位于 `Add` 的 SEH 保护区内）**无法可靠观测**，
第 117 轮的"只执行一次"不能作为证据。

#### 于是矛盾重新变得尖锐

- `dw=5` 之后 `[ebp+0x94]` 反复为正（3/4）→ `jle` 不成立 → 必然经过 `0xBBA569` 写 2；
- 但 `obj1[0x120]` 始终为 1（20ms/5ms 采样均未见过 2），直到索引满才变 3。

**若写 2 真的反复执行，状态就该在第一次时就变成 2 并永久保持。**

#### 一个此前被忽略的可能：`Add` 根本走不到 `0xBBA569`

`0xBBA43A` 处 `[0x94]` 为正，只说明"即将装载的值是正的"。但 `0xBBA440`
的 `test edi,edi` / `0xBBA442` 的 `jle` 依赖的是**装载后的 `edi`**。

**正常情况下两者相同。但若 `0xBBA43A` 这条 `mov edi,[ebp+0x94]` 本身没有被正确执行
（例如被我们的 cave 替换后行为异常），`edi` 就还是旧值 0，`jle` 就会跳。**

**然而本轮 cave 的字节校验通过、且重放了完整的 6 字节指令，理论上等价。**

#### 下一步：直接观察 `edi` 在 `0xBBA442` 处的值

`0xBBA442`（`jle 0xBBA5C3`，6 字节 `0F 8E 7B 01 00 00`）装载后 `edi` 才有效。

**在 `0xBBA442` 采样 `edi`**：

- 若为正 → `jle` 不成立 → 必到 `0xBBA569`，那"状态不变 2"只能由**写 2 被覆盖**解释；
- 若为 0 或负 → 说明 `mov edi,[ebp+0x94]` 没生效，问题在我们的观测方式上。

**这是最后一个分支点。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.133"),
                         ("HANDOFF-CURRENT.md", "### 16.21")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.133", "### 16.21")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
