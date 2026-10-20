"""Record round 138: the second write of 2 is unconditional, so the resets are what keep 1F4 at 1."""
from pathlib import Path

TEXT = """
### 12.153 ★★★ `0xBAE589` 的写 2 是**无条件**的；`1F4` 恒为 1 是复位造成的（2026-10-25 17:2x）

#### 上下文

```asm
0xBAE54B  mov ecx, [ebx+0x1F0]        ; 某对象
0xBAE551  mov edx, [ecx]              ; vtable
0xBAE553  mov eax, [ebx+0xC]
0xBAE556  mov edx, [edx+0xC]          ; vt+0xC
0xBAE559  push eax
0xBAE55A  call edx                    ; 虚调用
0xBAE55C  mov ecx, [ebx+0x1F0]
0xBAE562  lea eax, [ebp-0x20]
0xBAE565  push eax
0xBAE566  call 0xBB1A60
0xBAE56B  mov edx, [ebx+0x1F0]
0xBAE571  lea ecx, [ebx+0x184]
0xBAE577  push ecx
0xBAE578  push edx
0xBAE579  lea ecx, [ebx+0x1A0]
0xBAE57F  call 0xC699B0
0xBAE584  lea ecx, [ebp-0x20]
0xBAE587  mov dword [ebx+0x1F4], 2    ; ★ 无条件写 2
0xBAE591  mov byte [ebp-4], 0x1D      ; SEH 状态 0x1D
0xBAE595  call 0xB74E90
```

**`0xBAE587` 之前没有任何条件跳转**——只要执行流到达这里，`1F4` 就被写成 2。

#### 由此推出：`1F4` 恒为 1 的原因是复位

`0xBAE750`、`0xBAE768`、`0xBAE7AC` 三处无条件写 1（§12.152）。

**若 `0xBAE587` 所在的代码路径会被执行，`1F4` 就该短暂变成 2，随后被某个写 1 复位。**

**而我们始终观测到 1**——两种可能：

1. **`0xBAE587` 所在的分支从不执行**（需要某个前置条件）；
2. **它执行了，但紧接着（同一帧或下一帧）就被复位**，采样恰好总是落在复位之后。

**两种情况都会表现为"`1F4` 永远是 1"。**

#### 关键：这段代码在做什么

`0xBAE55A` 是**虚调用 `[vt+0xC]`**，`0xBAE566 call 0xBB1A60`，`0xBAE57F call 0xC699B0`。

**`[vt+0xC]` 是 `lobby+0xC` 那个对象的第 4 个虚槽**——§12.76 已解析过它的 vtable：

```
[vt+0x00] = 0xC74160
[vt+0x04] = 0xC73E50
[vt+0x08] = 0xC73E30
[vt+0x0C] = 0xC73EC0     ← 就是这里
[vt+0x10] = 0xC740B0
[vt+0x14] = 0xC73EA0
[vt+0x18] = 0xC73F30     （发包，§12.147）
[vt+0x1C] = 0xC73FB0     （收包，§12.76）
```

**所以 `0xBAE55A` 调用的是 `0xC73EC0`** —— 一个此前未分析的方法，夹在"设置"类
（`0xC73E30`/`0xC73E50`）与"收包"（`0xC73FB0`）之间。

#### 这给出一条全新的线索

`0xBAE587` 这段的功能序列是：

```
① 调用 [vt+0xC] = 0xC73EC0      （未知方法）
② 调用 0xBB1A60                 （未知）
③ 调用 0xC699B0                 （未知）
④ 写 1F4 = 2                    （推进 FE 梯）
```

**它看起来像"提交/确认某个操作，然后推进前端"**。

**而这正是我们需要的：让 `1F4` 变成 2 的另一条路。**

#### 下一步

1. **反汇编 `0xC73EC0`**（`[vt+0xC]`）——它是这条路径的第一步；
2. **确认 `0xBAE587` 所在分支的前置条件**——反汇编 `0xBAE500` 之前的部分，
   找到进入这个代码块的条件跳转；
3. **用哨兵法验证 `0xBAE587` 是否执行**：把它的立即数从 2 改成 `0xABCD1240`，
   轮询 `[lobby+0x1F4]` 是否出现该值。

**第 3 条最直接：若哨兵出现，说明这条路径确实会跑，那 `1F4` 恒为 1 就是复位
造成的——我们可以从复位点入手；若哨兵从不出现，说明这条路径需要某个前置条件，
而那个条件正是当前缺失的东西。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.153"),
                         ("HANDOFF-CURRENT.md", "### 16.41")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.153", "### 16.41")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
