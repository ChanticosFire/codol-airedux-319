"""Record round 47: the UI frame loop drives the FE loop which drives the pump - a contradiction with round 45."""
from pathlib import Path

TEXT = """
### 12.62 找到 UI 帧循环 → FE 主循环 → pump 的完整调用链，与 §12.61 矛盾（2026-10-23 15:5x）

#### 调用链

```asm
0x7EEAD0  push esi
0x7EEAD1  call 0x621750            ; ★ FE 主循环
0x7EEAD6  mov esi, 0xe56ffd0
0x7EEADB  jmp 0x7eeae0
0x7EEAE0  cmp dword ptr [esi], 1
0x7EEAE3  jne 0x7eeaec
0x7EEAE5  call 0x7fa3b0
0x7EEAEA  jmp 0x7eeaf3
0x7EEAEC  mov eax, esi
0x7EEAEE  call 0x7faf00
0x7EEAF3  add esi, 0x50
0x7EEAF6  cmp esi, 0xe5713d0
0x7EEAFC  jl 0x7eeae0               ; 遍历 0xE56FFD0..0xE5713D0，步长 0x50
0x7EEAFE  pop esi
0x7EEAFF  ret
```

`0x7EEAD0` 有 **6 个调用者**（`0x7EF0E3`、`0x7EF109`、`0x7EF1B5`、`0x7EF250`、
`0x7EF2C1`、`0x7EF2CC`），形态是标准的 UI 帧更新：先跑一次 FE 主循环，
再遍历一张 0x50 步长的对象表逐个更新。

而 FE 主循环在 `[lobby+0x1F4] == 1` 时必然调 pump：

```asm
0x621777  call 0x643280             ; 取 lobby
0x621782  je 0x621A1A               ; lobby 为 0 才跳过
0x62178A  call 0xBAC350             ; = [lobby+0x1F4]
0x62178F  cmp eax, 1
0x621792  jne 0x62179B
0x621794  mov ecx, esi
0x621796  call 0xBAD800             ; ★ pump
```

**所以只要 UI 帧循环在跑、lobby 非空、`1F4 == 1`，pump 就每帧被调用。**

#### 与 §12.61 的矛盾

§12.61 根据「把 `[obj1+0x130]` 改成 0 之后 120 秒毫无变化」推断 pump 只跑一次。
但本条调用链表明它应当每帧都跑。两者不能同时成立。

可能的解释：

1. **UI 帧循环未运行**——`0x7EEAD0` 的 6 个调用者都在某个"渲染帧"路径上，
   而客户端停在代号页时该路径可能停摆；
2. **lobby 指针为 0**——`0x621782 je 0x621A1A` 会跳过整段。但我们在别处读
   `[0xE85C68]` 一直非零，理论上 `0x643280` 返回同一个值；
3. **`0x621750` 存在早退**——它在入口 `0x621753 mov eax,0x2024` 与
   `0x621758 call 0xC43200` 是 `_alloca` 栈探测，若栈不足会抛异常；
4. **观测方法仍有问题**——「改索引无效」的观察本身可能受某个中间层影响。

#### 需要一个能自证的观测

前两次"没观测到"（§12.55、§12.56）都被证明是工具 bug。为避免第三次，
下一轮应先做一个**最小自证**：

在 `0x621750` 入口 `0x621750` 处读一个能区分"被调用过"的计数器——但客户端
没有这样的计数器。替代方案：用 `patch_runtime.py` 在 `0x621750` 前 5 字节
装一个 trampoline，把每次调用累加到一块可读内存，然后读那块内存。这个
trampoline 只要 20 字节，且**不改变任何行为**（`pushf/pushad` → `inc [counter]`
→ `popad/popf` → 原指令 → 跳回），比线程上下文采样可靠得多。

若计数为 0 → UI 帧循环确实没跑，问题在更上层；
若计数很大 → pump 每帧在跑，§12.61 的"只跑一次"结论错误，需回查索引实验。

#### 本轮确定的事实

| 事实 | 证据 |
|---|---|
| `0x621750` 唯一的直接调用者是 `0x7EEAD1` | `find_calls.py 0x621750` 只返回一条 |
| `0x7EEAD0` 是 UI 帧更新（先 FE 循环、再遍历 0x50 步长表） | 反汇编 |
| `0x7EEAD0` 有 6 个调用者 | `find_calls.py 0x7EEAD0` |
| FE 循环在 `1F4==1` 时调 pump | 反汇编 `0x62178F`/`0x621796` |

这三条都与"pump 每帧执行"一致，与"只跑一次"不一致。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.62"),
                         ("HANDOFF-CURRENT.md", "### 15.50")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.62", "### 15.50")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
