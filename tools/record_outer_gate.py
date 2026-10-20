"""Record round 142: the pump's very first test is on the byte at lobby+8."""
from pathlib import Path

TEXT = """
### 12.157 ★★★ pump 的第一道检查：`[lobby+8]` 为 0 则跳到 `0xBAE7C6`（2026-10-25 19:2x）

#### pump 的入口 `0xBAD800`

```asm
0xBAD800  push ebp
0xBAD801  mov ebp, esp
0xBAD803  push -1
0xBAD805  push 0xC8FE97
0xBAD80A  mov eax, dword ptr fs:[0]
0xBAD810  push eax
0xBAD811  sub esp, 0x9A4                    ; 2468 字节局部
0xBAD817  mov eax, [0xE3F240]               ; 栈 cookie
0xBAD81C  xor eax, ebp
0xBAD81E  mov [ebp-0x10], eax
0xBAD821  push ebx / push esi / push edi
0xBAD825  lea eax, [ebp-0xC]
0xBAD828  mov dword ptr fs:[0], eax         ; 建立 SEH 帧
0xBAD82E  mov ebx, ecx                       ; ebx = this (lobby)
0xBAD830  lea edi, [ebx+8]
0xBAD833  mov dword ptr [ebp-0x9A8], 0
0xBAD83D  cmp byte ptr [edi], 0              ; ★ 检查 [lobby+8] 的一个字节
0xBAD840  je 0xBAE7C6                        ; ★ 为 0 -> 直接跳到 0xBAE7C6
0xBAD846  cmp dword ptr [ebx+0x1F4], 1       ; 检查 1F4
```

#### 这是一道位于最外层的守卫

**`0xBAD83D` 是 pump 里第一条实质性判断**，它检查 `[lobby+8]` 的一个**字节**。

**若该字节为 0，直接跳到 `0xBAE7C6`。**

而 `0xBAE7C6` 位于 `0xBAE7AC`（写 `1F4 = 1`）之后不远处——**很可能是"复位并返回"的路径**。

**这完美解释了 §12.154 的观测：`0xBAE587`（写 2）从不执行。**

**因为当 `[lobby+8] == 0` 时，pump 根本不会执行到那里。**

#### 这条路径与之前所有分析的统一

```
pump(0xBAD800)
  └─ cmp byte [lobby+8], 0
       ├─ == 0 -> 0xBAE7C6（复位返回，1F4 保持 1）
       └─ != 0 -> 继续
            ├─ cmp [lobby+0x1F4], 1
            ├─ … 收包（0xBAE245）、Add（0xBAE276）…
            └─ 0xBAE587 写 1F4 = 2（推进 FE 梯）
```

**`[lobby+8]` 就是那个"总开关"。**

#### 下一步：读 `[lobby+8]` 的实际值

在客户端跑到 `dw=5` 之后，读 `[lobby+8]` 的字节：

- **若为 0** → 确认这是卡点，需要弄清什么代码会把它置为非 0；
- **若非 0** → 说明守卫通过了，问题在别处。

**这是下一步唯一要做的事，成本极低。**

同时值得查 `0xBAE7C6` 处的代码，确认它确实是复位路径。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.157"),
                         ("HANDOFF-CURRENT.md", "### 16.45")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.157", "### 16.45")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
