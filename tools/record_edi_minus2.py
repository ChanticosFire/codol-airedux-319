"""Record round 104: at the jle site edi is -2 even when success has occurred."""
from pathlib import Path

TEXT = """
### 12.119 ★★★ `0xBBA442` 处 `edi = -2`，即使成功已经发生（2026-10-24 23:2x）

#### 决定性采样

在 `0xBBA442`（`jle 0xBBA5C3`，6 字节 `0F 8E 7B 01 00 00`）采样 `edi`，
同时读成功计数：

```
[jle] image ready after 2.52s
[jle] n=0  edi=0x00000000  chain[0xE85CB0]=0x00000000
[jle] n=1  edi=0xfffffffe  chain[0xE85CB0]=0x00000001
[jle] unreadable - process gone?
```

**关键：`edi = 0xFFFFFFFE`（-2），而成功计数已经是 1。**

#### 这直接回答了核心问题

`edi` 在 `0xBBA442` 处就是 `Add` 用来判断的值（它由 `0xBBA43A` 从 `[ebp+0x94]` 载入）。
**该值是 -2，所以 `jle` 成立，流程跳到 `0xBBA5C3`，`0xBBA569` 的写 2 从不执行。**

**§12.117 观察到的"状态从未变成 2"由此得到完整解释：它不是被覆盖，而是从来没写。**

#### 与 §12.99 那次"采到 3"如何协调

第 99 轮在 `0xBBA43A` 采到 `[ebp+0x94] = 3`（两次，分别在 success=4 与 success=12 时）。
本轮在 `0xBBA442` 采到 `edi = -2`（success=1 时）。

两者并不矛盾，而是共同说明：

- `[ebp+0x94]` **绝大多数时候是 -2**；
- **偶尔**会变成 3（第 99 轮那两次）；
- **但即使它是 3，`success` 的增长与之并不同步**——第 99 轮 `[0x94]=3` 时
  `success` 恰好在 4 和 12，而本轮 `success=1` 时它是 -2。

**所以 `[ebp+0x94]` 与"虚函数是否成功"没有稳定的对应关系。**

#### 于是问题彻底变成

```
Add 的 count 来自 [ebp+0x94]
[ebp+0x94] 绝大多数是 -2，偶尔是 3
而虚函数成功时返回的是 esi（3 或 4，见 §12.113）
两者不是同一个值
```

**即：虚函数的返回值根本没有被传给 `Add`。**

回到调用序列：

```asm
0xBAE244  mov esi, eax                     ; 虚函数返回值 -> esi
0xBAE246  cmp dword [ebx+0x1F8], edi
0xBAE24C  je 0xBAE292                      ; 从不跳（§12.118）
0xBAE24E  push esi                         ; ★ esi 作为参数压栈
0xBAE255  push &[ebp-0x548]
0xBAE256  sub esp, 0x88
0xBAE26A  push edx
0xBAE26B  call 0xB753C0                    ; stdcall，ret 4
0xBAE276  call 0xBBA3F0                    ; Add
```

`esi` 确实被 `push` 了。按 §12.88 的栈布局推演，它应落在 `[ebp+0x94]`
（因为 `0xB753C0` 的 `ret 4` 弹掉了 `push edx`）。

**但实测 `[ebp+0x94]` 是 -2 而非 `esi` 的值**——说明这个布局推演仍是错的，
或者 `0xB753C0` 的 `ret 4` 之外还有别的栈调整。

#### 下一步：直接验证栈布局

应挂 `0xBBA3F0`（`Add` 入口，5 字节 `55 8B EC 6A FF 68` → 实际是
`55 | 8B EC | 6A FF | 68 BE 0F C9 00`，前 5 字节 `55 8B EC 6A FF` 是完整指令序列），
在 `Add` **刚进入、尚未改动任何寄存器**时，同时采样：

```
esi, [ebp+0x88], [ebp+0x8C], [ebp+0x90], [ebp+0x94]
```

**这样能一次性确定"调用方 push 的 esi 到底落在哪个偏移"。**

**注意**：本轮 `0xBBA442` 的 hook 导致客户端在 2 次命中后退出（`unreadable`），
说明该挂点仍不稳定。下一轮应挂在 `0xBBA3F0` 入口——那里在 SEH 帧建立**之前**，
最安全。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.119"),
                         ("HANDOFF-CURRENT.md", "### 16.07")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.119", "### 16.07")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
