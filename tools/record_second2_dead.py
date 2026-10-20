"""Record round 139: the second 1F4 path never executes, so an upstream gate blocks it."""
from pathlib import Path

TEXT = """
### 12.154 ★★★ 第二条 `1F4` 路径从不执行：上游存在前置门槛（2026-10-25 17:5x）

#### 哨兵实验

把 `0xBAE587` 的立即数从 2 改成 `0xABCD1240`：

```
原  C7 83 F4 01 00 00 02 00 00 00   mov dword [ebx+0x1F4], 2
改  C7 83 F4 01 00 00 40 12 CD AB   mov dword [ebx+0x1F4], 0xABCD1240
```

补丁在客户端出现后 2.64 秒写入（`dw=0` 阶段），随后以 20ms 间隔轮询 45 秒。

#### 结果

```
patched 0xbae587: writes 0xabcd1240 into 1F4 (was 2.64s)
  t= 10.10  1F4=           1  dw=0
  t= 15.11  1F4=           1  dw=2
  t= 20.13  1F4=           1  dw=5
  …
  t= 40.18  1F4=           1  dw=5

sentinel observed: 0
distinct 1F4 values seen:
    0x00000001  x1712
```

**1712 次采样，`1F4` 无一例外都是 1。**

#### 结论

**`0xBAE587` 所在的分支从未被执行。**

这不是"被复位覆盖"（若执行过，至少会有一两次采样落在那 20ms 的窗口内；
1712 次采样足够密）。

**而是根本没进入那个代码块。**

#### 这意味着什么

`0xBAE587` 那段的功能序列是：

```
① call [vt+0xC]   = 0xC73EC0
② call 0xBB1A60
③ call 0xC699B0
④ mov [ebx+0x1F4], 2
```

**它整段都不执行——包括那个虚调用在内。**

**所以"第二条推进 FE 梯的路径"当前是关闭的，需要满足某个前置条件才会打开。**

#### 下一步：找进入该代码块的守卫

从 `0xBAE587` 往回读，直到遇到第一个条件跳转，那个跳转的条件就是守卫。

`0xBAE540` 之前还有若干指令（本轮的 dump 从 `0xBAE540` 开始且前两条是错位的），
需要从更早的干净边界反汇编。

**同时值得查**：`0xBAE587` 所在函数（pump 的一部分）的入口在哪、
它在 pump 中的位置相对于 `0xBAE245`（虚调用收包）与 `0xBAE276`（`Add`）是什么关系。

**若这段在 `Add` 之后、且守卫依赖某个 `Add` 的结果，那整条链就串起来了**：
`Add` 不成功 → 守卫不通过 → `1F4` 永远是 1 → FE 梯停住。

**这会把前面二十多轮关于 `Add` 的分析与本轮发现的第二条路径统一起来。**

接下来应当反汇编 `0xBAE4A0`–`0xBAE590`，找出守卫条件。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.154"),
                         ("HANDOFF-CURRENT.md", "### 16.42")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.154", "### 16.42")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
