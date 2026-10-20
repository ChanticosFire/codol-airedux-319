"""Record round 62: the virtual fill chain resolves down to 0xBB15E0."""
from pathlib import Path

TEXT = """
### 12.76 虚调用链解析到 `0xBB15E0`；`+0x80` 是类型标记不是数量（2026-10-23 23:5x）

#### vtable 解析

```
[lobby+0xC] = 0x37D93150
vtable      = 0x00D95558          （EXE 内静态表，.rdata）
[vt+0x00] = 0x00C74160
[vt+0x04] = 0x00C73E50
[vt+0x08] = 0x00C73E30
[vt+0x0C] = 0x00C73EC0
[vt+0x10] = 0x00C740B0
[vt+0x14] = 0x00C73EA0
[vt+0x18] = 0x00C73F30
[vt+0x1C] = 0x00C73FB0   <- pump 每帧调用的那个
[vt+0x20] = 0x00C74090
[vt+0x24] = 0x00C74B10
```

虚拟表地址落在镜像内，说明 `[lobby+0xC]` 是标准 C++ 对象，其类定义在 EXE 里。

#### 填充函数的实际结构

`0xC73FB0` 手工解码（capstone 在该处错位，改字节直读）：

```asm
0xC73FF7  mov ecx, [ebp + 0x10]      ; 参数 3 = 0x508（1288）
0xC73FFA  push ecx
0xC73FFB  mov ecx, [esi + 4]         ; this + 4
0xC73FFE  push edi                   ; 参数 2
0xC73FFF  lea edx, [ebp - 0x120]
0xC74005  push edx
0xC74006  lea eax, [ebp - 0x118]
0xC7400C  push eax
0xC7400D  push ecx
0xC7400E  call 0xBB15E0              ; ★ 真正的数据获取
0xC74013  mov ebx, eax
0xC74015  add esp, 0x14
0xC74018  test ebx, ebx
0xC7401A  jns 0xC74021               ; 返回值 >= 0 -> 继续
0xC7401C  cmp ebx, -5
0xC7401F  jne 0xC7406E               ; 其它负值 -> 失败
0xC74021  sub esp, 0x84
0xC74029  mov ecx, 0x21              ; 33 dwords = 132 字节
0xC74034  rep movsd
0xC7403C  call 0xB76EF0
0xC74041  mov edx, [ebp - 0x120]
0xC74047  mov ecx, [ebp - 0x11C]
0xC74053  call 0xB75420              ; ★ 写入输出
0xC74069  mov eax, ebx
```

**`0xBB15E0` 是所有数据的真正入口**，参数是 `[this+4]`、`edi`、两个局部地址、1288。
它的返回值决定成功与否（`>= 0` 或 `== -5` 都算继续）。

#### `0xBB10A0` 只是设置标记

```asm
0xBB10A0  mov eax, ecx
0xBB10A2  mov ecx, 2
0xBB10A7  mov dword ptr [eax], 0xFF00FF00     ; 无效标记
0xBB10AD  mov word ptr [eax + 0x80], cx       ; +0x80 = 2
0xBB10B4  ret
```

`+0x80 = 2` 是**类型标记**（`0xFF00FF00` 是"未初始化"哨兵），**不是条目数**。

#### 由此修正一处理解

`Add` 的 `[ebp+0x90]`（结构 `+0x80`）是**类型标记**，`[ebp+0x94]`（结构 `+0x84`）
才是 **count**。而 `0xBB10A0` 只设了前者，后者默认为 0——**除非后续
`0xBB15E0` 成功填充**。

这与 §12.72 的实测完全吻合：`count = 0` 说明 `0xBB15E0` 没有填充 `+0x84`。

#### 下一步

反汇编 `0xBB15E0` 的主体（已解密前 0x50 字节，尚未到关键分支）。它开头有：

```asm
0xBB15F0  mov edx, [ebp + 8]        ; 参数 1 = [this+4]
0xBB15FE  cmp edx, -1
0xBB1601  jne 0xBB1616
0xBB1604  lea eax, [edx - 9]        ; edx==-1 时返回 -10
```

说明参数 1 是一个"句柄/句柄类值"，`-1` 表示无效。若 `[this+4]` 是 `-1`，
函数立刻返回 `-10`，`count` 就永远是 0。

**所以下一轮的第一件事：读 `[lobby+0xC] + 4` 的值，看它是不是 `-1`。**
这条判定成本极低，却可能直接给出答案。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.76"),
                         ("HANDOFF-CURRENT.md", "### 15.64")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.76", "### 15.64")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
