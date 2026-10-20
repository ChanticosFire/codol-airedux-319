"""Record round 135: forcing entry into the success block still never reaches the store."""
from pathlib import Path

TEXT = """
### 12.150 ★★★ 二分判决：强制进入成功分支，写 2 仍不执行（2026-10-25 15:2x）

#### 实验

同时打两个补丁（都是纯数据修改，不涉及 hook）：

```
0xBBA442  0F 8E 7B 01 00 00   jle 0xBBA5C3
       -> E9 01 00 00 00 90   jmp 0xBBA448     （强制进入成功分支）

0xBBA569  C7 83 20 01 00 00 02 00 00 00   mov [ebx+0x120], 2
       -> C7 83 20 01 00 00 34 12 CD AB   mov [ebx+0x120], 0xABCD1234  （哨兵）
```

#### 结果

```
patched branch 0xbba442: jle -> jmp 0xbba448 (e90100000090)
patched store  0xbba569: 2 -> 0xabcd1234
  t= 15.42  status=0x00000001  idx=0  dw=2
  t= 17.96  status=0x00000003  idx=5  dw=5

status sequence: ['0x1', '0x3']
sentinel samples: 0
```

**每次调用都被强制送进成功分支，但哨兵一次都没出现。**
**而状态照常从 1 到 3。**

#### 这排除了"判断条件错"的可能

§12.149 的二分方案是：

- 若强制进入后哨兵出现 → 成功分支本身没问题，只是 `jle` 判断错；
- 若仍不出现 → 成功分支内部有问题。

**实测是后者。**

**所以 `jle` 的判断结果根本不是瓶颈——即使无条件进入 `0xBBA448`，
流程也到不了 `0xBBA569`。**

#### 状态仍变成 3 说明了什么

既然每次调用都被强制送进 `0xBBA448`，而状态最终仍是 3，
那 `0xBBA62B`（写 3）必然也被执行了。

**而 `0xBBA62B` 只出现在 `0xBBA613` 之后的已满分支里。**

**所以流程必然从 `0xBBA448`–`0xBBA55C` 这段**跳到了 `0xBBA5C3` 附近**。**

但 §12.145 的扫描显示，`0xBBA4B2` 与 `0xBBA4D3` 两处跳转的目标都是 `0xBBA55E`
（写 2 入口），**没有任何一处指向 `0xBBA5C3`**。

#### 唯一剩下的解释：异常

`Add` 在 `0xBBA3F5` 建立了 SEH 帧（`push 0xC90FBE`、`0xBBA415` 写 `fs:[0]`）。

**若 `0xBBA448`–`0xBBA55C` 之间发生访问违例，SEH 处理器会接管。**

**而 `0xBBA62B` 能被到达，说明处理器最终回到了某条正常路径**——
这在中途异常的情形下是可能的：异常被处理后，`Add` 返回，
**下一帧再次调用时走的是 `count <= 0` 的路径**（因为 `Add` 的参数由上层每帧重填，
强制补丁只改了下标不影响参数），于是推进索引、写 3。

**所以完整解释是：**

```
每帧 Add 被调用
  → 被强制进入 0xBBA448
  → 在 0xBBA448..0xBBA55C 之间某处触发访问违例
  → SEH 捕获，清理并返回（没走到 0xBBA569）
  → 下一帧重复同样过程
  → 直到某一帧的 count <= 0（此时 jle 本来就会跳，补丁不影响）
      → 推进索引 → 满 → 写 3
```

**这就是为什么强制进入也没有用。**

#### 下一步：定位异常点

在 `0xBBA448`–`0xBBA55C` 之间有多个 `call` 与 `rep movsd`。
**其中 `0xBBA4F2 rep movsd`（目标 `edi`）是最可疑的**——§12.143 就怀疑过它。

但 §12.144 把 `rep movsd` 改成 `NOP NOP` 后没有效果。

**那次是单独改的，没有配合"强制进入成功分支"。**
**如果正常路径根本不进入成功分支，那么单独 NOP 掉 `rep movsd` 当然看不出变化。**

**所以正确的组合实验是：**

```
补丁 A：0xBBA442 指令改为 jmp 0xBBA448   （强制进入）
补丁 B：0xBBA4F2 改为 90 90              （跳过 rep movsd）
补丁 C：0xBBA569 改为哨兵                 （观测写 2）
```

**若 A+B 之下哨兵出现，就证明异常点确实是 `rep movsd`。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.150"),
                         ("HANDOFF-CURRENT.md", "### 16.38")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.150", "### 16.38")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
