"""Record round 132: 0xBBA1F0 is the send path, reached after a successful append."""
from pathlib import Path

TEXT = """
### 12.147 ★★★ `0xBBA1F0` 是发包路径：`Add` 追加成功后经 vtable+0x18 发送（2026-10-25 13:5x）

#### 函数体（前 0xF0 字节）

```asm
0xBBA1F0  push ebp
0xBBA1F1  mov ebp, esp
0xBBA1F3  sub esp, 0x514                 ; 1300 字节局部
0xBBA1F9  mov eax, [0xE3F240]            ; 栈 cookie
0xBBA1FE  xor eax, ebp
0xBBA200  mov [ebp-4], eax
0xBBA203  push ebx
0xBBA204  push esi
0xBBA205  mov esi, ecx                   ; esi = this (obj1)
0xBBA207  xor ebx, ebx
0xBBA209  cmp dword [esi+0x120], 1       ; ★ 状态检查
0xBBA210  jne 0xBBA2C0                   ; 状态 != 1 -> 跳到 0xBBA2C0（不是返回）
0xBBA216  lea ecx, [esi+0x118]
0xBBA21C  call 0xB75E10
0xBBA221  movzx eax, word [esi+0x12C]    ; 某计数
0xBBA228  push eax
0xBBA229  lea ecx, [ebp-0x514]
0xBBA22F  call 0xBC18E0                  ; 构造临时容器
0xBBA234  push 0x507                     ; ★ 1287 字节
0xBBA247  call 0xC42D60                  ; memset
0xBBA24F  ...
0xBBA26F  call 0xBC1900
0xBBA274  test al, al                    ; 检查返回值
0xBBA276  90                             ; ★ NOP
0xBBA277  90                             ; ★ NOP
0xBBA278  mov eax, [ebp-0x510]
0xBBA27E  mov ecx, [esi]                 ; vtable
0xBBA280  mov edx, [ecx]
0xBBA282  mov edx, [edx+0x18]            ; ★ vtable+0x18 = 发包函数
0xBBA285  push eax
0xBBA286  lea eax, [ebp-0x50C]
0xBBA28C  push eax
```

#### 三项重要发现

**1. `vtable+0x18` 是发包函数**

§12.88 已确认 `[vt+0x18] = 0xC73F30`，其中 `0xC73F88` 调用 `0xBB1420`（UDP sendto 包装）。

**`0xBBA1F0` 在 `0xBBA282` 取 `[vtable+0x18]` 并调用它——即"把刚追加的数据发出去"。**

**所以 `Add` 的完整语义是"追加一条记录，然后发送"。**

**2. `0xBBA276`/`0xBBA277` 是两条 NOP**

`0xBBA274` 是 `test al, al`，随后紧跟两条 `nop`。

**正常的编译器输出里，`test` 之后必然跟着条件跳转。**
这两条 `nop` 极可能是**原始的 `je`/`jne`（2 字节）被替换后的残留**。

**但我们的补丁列表里没有 `0xBBA276`**——所以这是**原版二进制**就有的，
可能是开发者刻意留的（例如临时禁用某个失败分支），也可能是链接器产物。

**它意味着：`0xBC1900` 的返回值被 `test` 检查后，无论真假都继续执行。**

**3. `jne 0xBBA2C0` 不是返回，而是跳到另一段**

状态不是 1 时，`0xBBA1F0` 会跳到 `0xBBA2C0`——**那里才是 `0xBBA2B6`（写 4）所在的区域**。

#### 这串起了整条链

```
Add（0xBBA3F0）
  ├─ count > 0 -> 走成功分支 -> 写 2 -> jne 返回      （哨兵实验证明此路从未走通）
  └─ count <= 0 -> 推进索引 -> 未满时调用 0xBBA1F0
                     └─ 0xBBA1F0: 状态==1 -> 构造容器 -> 经 vtable+0x18 发包
                                  状态!=1 -> 跳到 0xBBA2C0（含写 4）
```

#### 下一步

反汇编 `0xBBA2C0` 之后的部分，确认：

1. `0xBBA2B6`（写 4）到底在哪个分支下执行；
2. `0xBBA0A4`（写 `esi`）是否也在这一段；
3. **`0xBBA1F0` 的发包是否就是"把客户端数据发给服务端"的路径**——
   若是，那我们此前关注的方向（服务端回什么）与这条链的关系就完全清楚了。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.147"),
                         ("HANDOFF-CURRENT.md", "### 16.35")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.147", "### 16.35")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
