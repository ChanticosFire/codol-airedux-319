"""Record round 109: 0xB76EE0 is a poison helper, not a destructor that clobbers ebx."""
from pathlib import Path

TEXT = """
### 12.124 `0xB76EE0` 只是毒化函数：`mov [ecx],0xDEADBEEF; ret`（2026-10-25 02:0x）

#### 反汇编

```asm
0xB76EE0  mov dword ptr [ecx], 0xDEADBEEF
0xB76EE6  ret
0xB76EE7  int3 ×9
```

**整个函数只有两条指令**：把一个哨兵值 `0xDEADBEEF` 写进 `[ecx]`，然后立即返回。

- **不碰 `ebx`**，也不碰任何其它寄存器；
- 不调整栈，没有序言/结尾；
- 作用是**调试期的"毒化"**——把对象首字段标记为已销毁，
  防止重复析构或使用已销毁对象。

#### 覆盖者候选缩小到三个

`0xBBA569`（写 2）与 `0xBBA5C3`（检查状态）之间的全部 `call`：

```asm
0xBBA57A  call 0xC42D60      ← 候选
0xBBA591  call 0xB75660      ← 候选
0xBBA59D  call 0xBA4B20      ← 候选
0xBBA5AF  call 0xB76EE0      ← 已排除（毒化，安全）
0xBBA5BE  call 0xB76EE0      ← 已排除（毒化，安全）
```

**只剩 `0xC42D60`、`0xB75660`、`0xBA4B20` 三个。**

其中：

- **`0xBA4B20`** 在 §12.93 里已出现，用作日志/断言（`0xBBA556 call 0xBA4B20`）；
  若它在某些路径上不返回或改动大量寄存器，是最可疑的；
- **`0xB75660`** 与写 `+0x84` 的 `0xB75420` 相邻，属于同一组访问器；
- **`0xC42D60`** 是 CRT 相关（`0xC3C20F` 是 `__security_check_cookie`，
  `0xC42D60` 可能是 `memset` 一类）。

#### 但还有一个更简单的可能

回顾 `0xBBA5C3` 的语义：

```asm
0xBBA5C3  cmp dword ptr [ebx + 0x120], 1
0xBBA5CA  jne 0xBBA635
```

**若 `ebx` 完好，这里读到 2，`jne` 必跳，状态保持 2。**

而 §12.102 的 20ms 采样显示状态**从未**是 2——连一瞬间都没有。

**若覆盖发生在同一次 `Add` 调用内（写 2 → 几条指令 → 写 3），20ms 采样确实抓不到。**
但如果写 2 之后 `jne` 正确跳走、状态保持 2，那么它应当**持续存在**，
20ms 采样必然能看到。

**实测看不到 → 说明状态 2 的存在时间极短 → 覆盖发生在同一帧内 → `jne` 没有跳。**

**这与"`ebx` 被某个 `call` 破坏"完全吻合。**

#### 下一步：逐个检查那三个 `call`

按成本排序：

1. **`0xBA4B20`**——它同时也被 `Add` 的成功路径调用（`0xBBA556`），
   若它改 `ebx`，会影响很多地方。先看它的序言；
2. **`0xB75660`**——同样是访问器，看一眼；
3. **`0xC42D60`**——CRT 函数，一般遵守约定，但仍需确认。

**三个都只需反汇编前几条指令，看有没有 `push ebx` / `mov ebx,...`。**

下轮一次性把这三个函数的序言都 dump 出来。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.124"),
                         ("HANDOFF-CURRENT.md", "### 16.12")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.124", "### 16.12")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
