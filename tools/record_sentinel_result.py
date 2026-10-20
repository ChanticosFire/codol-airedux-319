"""Record round 125: the sentinel never appears, proving the store at 0xBBA569 never executes."""
from pathlib import Path

TEXT = """
### 12.140 ★★★ 哨兵实验：`0xBBA569` 从未执行（2026-10-25 10:2x）

#### 方法（不依赖任何 hook）

把 `0xBBA569` 的立即数从 `2` 改成 `0xABCD1234`：

```
原  C7 83 20 01 00 00 02 00 00 00    mov dword [ebx+0x120], 2
改  C7 83 20 01 00 00 34 12 CD AB    mov dword [ebx+0x120], 0xABCD1234
```

**只改操作数，不改控制流、不插钩子、不动栈。** 然后在客户端出现后 2.70 秒
（`dw=0` 阶段，早于任何 `Add` 调用）就写入该补丁，再以 20ms 间隔轮询
`obj1[0x120]` 45 秒。

#### 结果

```
patched 0xbba569: writes 0xabcd1234 instead of 2 (after 2.70s)
  t=  5.00  status=None  dw=0
  t= 10.02  status=None  dw=0
  t= 15.03  status=1     dw=2
  t= 20.03  status=3     dw=5
  t= 25.05  status=3     dw=5
  …
  t= 40.09  status=3     dw=5

sentinel observed 0 time(s)
```

**哨兵值 `0xABCD1234` 一次都没有出现。**

**而状态照常从 1 走到 3**——说明补丁没有破坏程序的正常流程，
只是那条指令从未被执行。

#### 这推翻了第 108 轮

§12.108 曾在 `0xBBA5AB`（写 2 之后的指令）装钩子，命中 1 次，据此认为写 2 执行过。

**但那次是崩溃前的第 1 次命中**（§12.117、§12.119 已记录该挂点每次命中即崩），
**不能作为"写 2 执行过"的证据**。

**本轮的哨兵实验没有这个问题**：补丁是纯数据修改，程序全程正常运行到 `dw=5` 并锁定状态。

#### 于是得到一个不含推测的结论

> **`0xBBA569` 从未执行。`Add` 的成功分支从未被走到。**

#### 但 `count = 3` 是实测的

§12.138 的直方图显示 91.4% 的调用 `[ebp+0x94] = 3`。按判定链：

```asm
0xBBA43A  mov edi, [ebp+0x94]     ; edi = 3
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3            ; 3 > 0 -> 不跳
0xBBA448  …                       ; 应当继续
```

**`jle` 不该跳，`0xBBA448` 之后必然到 `0xBBA55E`/`0xBBA569`。**

**两者不能同时成立。**

#### 剩下的唯一可能：`0xBBA448`–`0xBBA55C` 之间发生了异常或提前返回

`Add` 是带 SEH 的函数（`0xBBA3F5 push 0xC90FBE` 建立异常帧，`0xBBA415` 设
`fs:[0]`）。若 `0xBBA448`–`0xBBA55C` 之间发生异常，控制流会被 SEH 处理器接管，
**直接跳到 `0xBBA635` 附近的清理代码**，从而跳过 `0xBBA569`。

**而 `0xBBA635` 正是 `0xBBA5CA jne` 的跳转目标**——这两条路径汇合于同一处，
完全符合"状态保持 1 并被索引推进"的观测。

#### 下一步：检查 `0xBBA635` 附近是否为 SEH 处理器

若 `0xBBA635` 之后有 `__except` 风格的代码（例如取 `fs:[0]`、恢复前一帧），
就证实"中途异常 → 跳到清理"这条路径存在。

**这样就能解释：`count=3` 是对的、`jle` 没跳是对的、写 2 没执行也是对的——
三者通过 SEH 路径统一。**

**这是本轮之后最有价值的一次反汇编。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.140"),
                         ("HANDOFF-CURRENT.md", "### 16.28")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.140", "### 16.28")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
