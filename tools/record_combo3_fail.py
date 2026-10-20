"""Record round 136: skipping rep movsd alongside forced entry still does not reach the store."""
from pathlib import Path

TEXT = """
### 12.151 阴性：强制进入 + 跳过 `rep movsd` 三补丁后，哨兵仍不出现（2026-10-25 15:5x）

#### 实验

三个补丁同时生效：

```
0xBBA4F2  F3 A5    rep movsd      -> 90 90        （跳过）
0xBBA442  0F 8E …  jle 0xBBA5C3   -> E9 01 … 90   （强制进入成功分支）
0xBBA569  C7 83 … 02 00 00 00     -> … 34 12 CD AB（哨兵）
```

#### 结果

```
patched rep    0xbba4f2: F3A5 -> 9090 (rep movsd skipped)
patched branch 0xbba442: jle -> jmp 0xbba448 (e90100000090)
patched store  0xbba569: 2 -> 0xabcd1234
  t= 15.34  status=0x00000001  idx=0  dw=2
  t= 17.93  status=0x00000003  idx=5  dw=5

status sequence: ['0x1', '0x3']
sentinel samples: 0
```

**哨兵一次都没出现，状态照常到 3。**

#### 所以异常不在 `rep movsd` 处

§12.144 与 §12.150 分别是"单独跳过 `rep movsd`"与"强制进入"，两次都没有效果。
本轮把两者合并，仍无效果——**因此 `0xBBA4F2` 这条指令不是故障源。**

#### 剩下的候选：成功分支内的其它 `call`

`0xBBA448`–`0xBBA55C` 之间还有：

```
0xBBA4F9  call 0xC42D60      ; memset 类
0xBBA510  call 0xC42D60      ; memset 类
0xBBA524  call 0x848AD0      ; 未知
0xBBA52B  call 0xB75660      ; 访问器（§12.125 已知安全，push ebx）
0xBBA53F  call 0xBC1970      ; 取容器数据指针
0xBBA546  call 0xB75660
0xBBA556  call 0xBA4B20      ; 空函数
```

**其中 `0xBBA524 call 0x848AD0` 是唯一一个尚未检查过的。**

**但继续逐个猜下去成本很高，而且已经猜错两次。**

#### 换一条不依赖猜测的路线

既然强制进入成功分支后流程仍走不到 `0xBBA569`，而状态最终变成 3，
**那 `0xBBA62B`（写 3）必然被执行。**

**`0xBBA62B` 的地址是 `0xBBA62B`——用哨兵法直接验证它！**

**把 `0xBBA62B` 的立即数从 `3` 改成 `0xABCD1235`（一个独特值），观察 `obj1[0x120]` 是否出现它：**

- **出现** → 确认写 3 来自这里，也就确认流程确实走到了 `0xBBA613` 之后的已满分支；
- **不出现** → 写 3 来自别处（但 §12.70 的列表里只有这一处写 3）。

**这能验证"流程在强制进入后仍到达已满分支"这个推论，从而确认中间确实是从
`0xBBA448`–`0xBBA55C` 跳到了 `0xBBA5C3`。**

#### 但更值得问的是：为什么要让 2 出现

回顾整个目标：**玩家档案持久化、房间列表、建房、进入对局**。

这些都不依赖 `obj1[0x120] == 2` 这个具体值——**它只是 `Add` 的内部状态**。

**此前的分析把"让状态变 2"当成了必经之路，但这可能是个错误的中间目标。**

**真正需要的是：FE 梯推进（`1F4` 变成 2）、客户端离开代号页。**

**而 `1F4` 的写入条件（§12.70）是 `[obj1+0x120] == 2`——所以确实需要 2。**

**除非有别的路径能推进 `1F4`。**

#### 下一步

1. **用哨兵验证 `0xBBA62B` 是否执行**（成本低，能确认流程去向）；
2. **同时检查 `1F4` 的全部写入点**——若除 `0xBAE1AC` 之外还有别的写入路径，
   可能不必依赖状态 2。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.151"),
                         ("HANDOFF-CURRENT.md", "### 16.39")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.151", "### 16.39")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
