"""Record round 108: the write of 2 does execute, so it is overwritten afterwards."""
from pathlib import Path

TEXT = """
### 12.123 ★★★ 写 2 确实执行了（`0xBBA5AB` 命中），因此必定被覆盖（2026-10-25 01:3x）

#### 第一次尝试：字节读错

先按记忆里的 dump 用了 `C6 45 FC 02 | 8D 8D B4 FD FF FF`，被字节校验拦下：

```
byte mismatch at 0xbba5ab: want c645fc028d8db4fdffff got c645fc02e82cc9fbff8d
```

实际是 `C6 45 FC 02`（`mov byte [ebp-4], 2`）后面紧跟 `E8 2C C9 FB FF`
（`call 0xB76EE0`），不是 `lea`。**字节校验再一次防止了错误的安装**。

#### 第二次：用正确字节，一次命中

```
[w2ok] image ready after 2.75s
[w2ok] n=0  eax=0x00000000  dw=0  success=0
[w2ok] n=1  eax=0x001AC700  dw=2  success=2
[w2ok] unreadable - process gone?
```

**`0xBBA5AB` 确实被执行了一次**，此时 `dw = 2`（前端尚未就绪）、`success = 2`。

#### 由此得到的确定结论

1. **`0xBBA569` 的写 2 执行过**——因为 `0xBBA5AB` 紧跟其后；
2. **执行时 `dw = 2`**，即发生在**早期初始化**阶段，而不是 `dw=5` 之后；
3. **但最终 `obj1[0x120]` 是 3**（§12.102 及历次观测）。

**所以状态在被写成 2 之后，又被改成了 3。**

#### 覆盖者只剩 `0xBBA62B`，而它被 `jne` 拦着

`Add` 内部的顺序：

```
0xBBA569  mov [ebx+0x120], 2       ← 已确认执行
0xBBA573  mov byte [ebp-0x13c], 0
0xBBA57A  call 0xC42D60
0xBBA582  push 0x64 / lea / push
0xBBA591  call 0xB75660
0xBBA59D  call 0xBA4B20
0xBBA5A5  lea ecx, [ebp-0x1c4]
0xBBA5AB  mov byte [ebp-4], 2      ← 已确认执行
0xBBA5AF  call 0xB76EE0            ★ 析构
0xBBA5B4  lea ecx, [ebp-0x24c]
0xBBA5BA  mov byte [ebp-4], 0
0xBBA5BE  call 0xB76EE0            ★ 析构
0xBBA5C3  cmp dword [ebx+0x120], 1
0xBBA5CA  jne 0xBBA635             ← 若 ebx 完好，状态为 2 -> 必跳
0xBBA5E6  mov eax, [ebx+0x130]     ← 索引推进
0xBBA62B  mov [ebx+0x120], 3       ← 覆盖者
```

**两次 `call 0xB76EE0` 都发生在 `cmp` 之前。** 若其中任一次破坏了 `ebx`，
`0xBBA5C3` 的 `cmp` 就会读到一个**不同的地址**，`jne` 不成立，
流程继续到 `0xBBA5E6` 推进索引、`0xBBA62B` 写 3。

**这完全解释了所有观测**：

- 写 2 执行 ✔（本轮证实）
- 状态仍变 3 ✔
- 索引在成功后仍增长 ✔（§12.102 观察到 idx 与 success 同步）
- 20ms 采样抓不到状态 2 ✔（写 2 到写 3 之间只隔几条指令）

#### 下一步：检查 `0xB76EE0` 是否保存/恢复 `ebx`

反汇编 `0xB76EE0`，看它的序言与结尾：

- **若有 `push ebx` / `pop ebx`** → 它不破坏 `ebx`，那 `ebx` 的破坏来自别处，
  需要另找；
- **若没有** → 它就是元凶，覆盖链闭合。

**这是最后一块拼图**，只需一次反汇编。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.123"),
                         ("HANDOFF-CURRENT.md", "### 16.11")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.123", "### 16.11")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
