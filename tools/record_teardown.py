"""Record round 141: the block is a teardown-then-advance sequence, guarded before 0xBAE452."""
from pathlib import Path

TEXT = """
### 12.156 该块是"清理旧对象 + 推进前端"，守卫在 `0xBAE452` 之前（2026-10-25 18:5x）

#### 从 `0xBAE440` 起的完整序列

```asm
0xBAE452  mov ecx, dword [ebx+0x1F8]        ; ★ obj1
0xBAE458  mov byte [ebp-4], 0x1D            ; SEH 状态
0xBAE45C  test ecx, ecx
0xBAE45E  je 0xBAE489                        ; obj1 == 0 -> 跳过
0xBAE460  call 0xBBA150                      ; 销毁前处理
0xBAE465  mov edi, dword [ebx+0x1F8]
0xBAE46B  test edi, edi
0xBAE46D  je 0xBAE47F
0xBAE46F  mov ecx, edi
0xBAE471  call 0xBBA070
0xBAE476  push edi
0xBAE477  call 0xB742E0                      ; 释放
0xBAE47C  add esp, 4
0xBAE47F  mov dword [ebx+0x1F8], 0           ; ★ 清 obj1
0xBAE489  mov ecx, dword [ebx+0x1FC]         ; 服务器列表对象
0xBAE48F  test ecx, ecx
0xBAE491  je 0xBAE4BC
0xBAE493  call 0xBBA6E0
0xBAE498  mov edi, dword [ebx+0x1FC]
0xBAE49E  test edi, edi
0xBAE4A0  je 0xBAE4B2
0xBAE4A2  mov ecx, edi
0xBAE4A4  call 0xBBA670
0xBAE4A9  push edi
0xBAE4AA  call 0xB742E0                      ; 释放
0xBAE4AF  add esp, 4
0xBAE4B2  mov dword [ebx+0x1FC], 0           ; 清 1FC
0xBAE4BC  lea edi, [ebx+0x4D60]              ; 之后继续到写 2
0xBAE587  mov dword [ebx+0x1F4], 2
```

#### 这是一段"拆除再推进"

- `0xBAE45E`–`0xBAE47F`：**销毁 `obj1`（`[ebx+0x1F8]`）并清零**
- `0xBAE491`–`0xBAE4B2`：**销毁服务器列表对象（`[ebx+0x1FC]`）并清零**
- `0xBAE4BC`–`0xBAE587`：整理列表、调 `[vt+0xC]`、推进 `1F4`

**典型的"销毁旧会话、建立新会话、推进前端"序列。**

#### 守卫比预想的更靠前

`branches_to.py` 检查结果：

```
跳转到 0xBAE4A0 的：0 个
跳转到 0xBAE4B2 的：1 个（0xBAE4A0 je 自己）
跳转到 0xBAE490 的：0 个
```

**`0xBAE4A0` 没有外部跳转来源——说明这一段是顺序执行到达的，
守卫在 `0xBAE452` 之前甚至更早。**

#### 这段的执行条件推断

"销毁 obj1 与服务器列表对象、然后重新推进前端"——
**它应当发生在"进入大厅"或"切换界面"的时刻，一次性执行。**

**而我们的客户端停在大厅渲染阶段（`dw=5`），从未发生这次切换。**

**所以守卫很可能就是"某个触发条件"（用户点击、某个状态到达），而该条件当前不满足。**

#### 下一步

从 `0xBAE452` 继续往回读，找出这段的入口。由于 `0xBAE440` 附近错位
（`0xBAE440` 是 `pop esp`，不可能是合法指令边界），需要从 `0xBAE400` 或更早的
已知函数起点开始反汇编。

**更实际的做法**：用 `branches_to.py` 查找是否有跳转指向 `0xBAE452` 之前的
一小段范围，例如 `0xBAE444`–`0xBAE452`。

**或者**：直接看 `0xBAE500` 这个整块属于哪个函数——`0xBAE000` 附近是 pump，
找出它的函数起点（`push ebp` / `mov ebp,esp`），从那里完整反汇编。

**后者更可靠**：定位 pump 的入口，然后顺着控制流看这段是否可达。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.156"),
                         ("HANDOFF-CURRENT.md", "### 16.44")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.156", "### 16.44")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
