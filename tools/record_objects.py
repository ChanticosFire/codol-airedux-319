"""Record round 182: p holds the socket, the address lives on serverlist, and one dump was misaligned."""
from pathlib import Path

TEXT = """
### 12.197 `p` 持有 socket，地址/端口在 `serverlist` 上；`0xC73F62` 反汇编错位（2026-10-26 17:5x）

#### 实测字段

```
p = [serverlist] = 0x37D3BA80
  p+0x00 = 0x00D95558    （已知的 lobby vtable）
  p+0x04 = 11624          ★ socket 句柄
  p+0x08 = 0
  p+0x7C = 0xBDBD
  p+0x80 = 12
  p+0x84 = 0
  p+0x88 = 0x37D3BB44    （指针）
  p+0x8C = 0x37D3BCF4    （指针）
  p+0x90 = 0x0E60CAE8

serverlist+0x84 = 2
serverlist+0x88 = 3074           ★ 端口
serverlist+0x8C = 0xFF00FF00     ★ 地址
state 1A0 = 1
```

#### 两个对象分工不同

| 对象 | 持有 |
|---|---|
| **`p = [serverlist]`** | **socket 句柄（`+4` = 11624）**、一组指针（`+0x88`/`+0x8C`） |
| **`serverlist`** | **类型（`+0x84` = 2）、端口（`+0x88` = 3074）、地址（`+0x8C` = 0xFF00FF00）、状态码（`+0x1A0`）** |

**所以：`p` 是"网络端点"对象，`serverlist` 是"服务器列表"对象。**

**而 `0xC73F5E call 0xB770A0` 很可能返回指向 `serverlist`（或其中的地址结构）的指针，
`esi` 因此指向真正的目标地址。**

#### 但 `0xC73F62` 处反汇编错位

```
0x00c73f60  31 f0                    xor eax, esi
0x00c73f62  ff 8b 4d 10 51 56        dec dword ptr [ebx + 0x5651104d]   ← 明显错位
0x00c73f68  8b cf                    mov ecx, edi
0x00c73f6c  e8 4f 15 f0 ff           call 0xb754c0
```

**`dec dword ptr [ebx+0x5651104d]` 是不可能的指令边界。**

**正确的边界应当在 `0xC73F63`：**

```
0xC73F62  FF ...                      （前一条的尾巴）
0xC73F63  8B 4D 10                    mov ecx, [ebp+0x10]     ; param 3 = 长度
0xC73F66  51                          push ecx                 ; push 长度
0xC73F67  56                          push esi                 ; push 地址指针
0xC73F68  8B CF                       mov ecx, edi             ; ecx = param 1
0xC73F6A  8B F0                       mov esi, eax
0xC73F6C  E8 4F 15 F0 FF              call 0xB754C0
```

**这样 `0xC73F63` 的 `mov ecx,[ebp+0x10]` 与 `0xC73F66` 的 `push ecx`、
`0xC73F67` 的 `push esi` 组成一组完整的"压长度、压缓冲区"，
符合 `sendto` 的参数顺序。**

#### 这修正了 `0xB754C0` 的调用语义

**此前的困惑是"`0xC73F68` 把 `ecx` 设成类型值（3），再调一个读 `[ecx+0x84]` 的函数"，
那会读取地址 0x87。**

**按对齐后的边界，`ecx = edi` 仍然是参数 1。但结合 §12.196 的发现——
`0xC73F30` 的 `this` 是 `p`（网络端点对象），其 `+0x84` 为 0——
如果 `edi` 实际是 `p` 而不是类型，那么 `0xB754C0(p)` 读 `[p+0x84]` = 0 是合法的。**

**所以参数顺序可能需要再核对一次：`0xBBA7CF push edi` 里 `edi` 究竟是什么，
需要回到 `0xBBA760` 的调用点确认。**

#### 下一步

**重新核对 `0xBBA760` 的三个压栈参数与 `0xC73F30` 的三个形参的对应关系**，
确认 `edi` 是"类型"还是"对象指针"。

**这决定了 `0xB754C0` 读的到底是 `[类型+0x84]`（非法）还是 `[对象+0x84]`（合法，值 0）。**

**同时确认目标地址 `0xFF00FF00` 的性质**——它显然不是合法 IPv4 目标。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.197"),
                         ("HANDOFF-CURRENT.md", "### 16.85")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.197", "### 16.85")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
