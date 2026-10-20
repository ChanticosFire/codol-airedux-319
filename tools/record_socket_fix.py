"""Record round 181: the socket handle is 11624, not zero - round 177 read the wrong address."""
from pathlib import Path

TEXT = """
### 12.196 ★★★★ 重要修正：socket 句柄是 11624，不是 0（2026-10-26 17:2x）

#### 实测

```
lobby                = 0x35C57E80
serverlist           = 0x38062498
[serverlist + 0x00]  = 0x37F37D70     <- 0xC73F30 实际收到的 this
lobby + 4            = 0              <- §12.177 读的地址
[p + 0x04]           = 11624          <- ★ 0xC73F74 真正装载的值
[p + 0x00]           = 0x00D95558     <- 已知的 lobby vtable
```

#### 寻址链推导（此前漏了一级）

```asm
0xBBA7C0  mov ecx, dword ptr [esi]      ; ecx = [serverlist] = 0x37F37D70
…
0xBBA7D0  call eax                        ; 调用 vt+0x18，ecx 仍是 0x37F37D70
```

```asm
0xC73F30  …                               ; 所以 this = 0x37F37D70
0xC73F52  mov ebx, ecx                    ; ebx = 0x37F37D70
0xC73F74  mov eax, dword ptr [ebx+4]       ; ★ eax = [0x37F37D74]
```

**所以 socket 在 `[[serverlist]+4]`，而不是 `lobby+4`。**

**§12.177 与 §12.178 读的是 `lobby+4`（恒为 0），结论"lobby socket 从未创建"
因此是错的，现予撤销。**

**实际值 11624 是一个正常的 Windows socket 句柄（小整数，符合 HANDLE 特征）。**

#### 这也解释了另一件事

`[p+0x00] = 0x00D95558` 正是 §12.76 记录的 lobby vtable。

**所以 `p` 指向的对象本身就是一个带 lobby vtable 的实例——
`0xC73F30` 的 `this` 不是"服务器列表对象"，而是另一个对象，
它的 `+4` 存放 socket 句柄。**

**而 `[serverlist]` 指向它，说明服务器列表对象内部持有这个对象的指针。**

#### 影响：状态 5 的成因需要重新推导

**socket 是有效的，所以"sendto 收到无效句柄而失败"这条解释不再成立。**

**状态 5 的成因必须重新查。可能的方向：**

1. **目的地址 `0xFF00FF00` 非法**（§12.177 观察到 `+0x8C = 0xFF00FF00`）；
2. **`sendto` 成功但返回值与序列化长度不符**（例如序列化长度算出异常值）；
3. **`0xBBA760` 在序列化阶段就失败**，根本没走到发送。

**第 1 条最可疑**：`0.255.0.255` 不是合法目标地址，`sendto` 会返回 `WSAEADDRNOTAVAIL`。

#### 下一步

**读 `[serverlist]` 指向对象的完整字段**（尤其 `+0x84`、`+0x88`、`+0x8C`），
确认目标地址与端口是否合理。

**若地址是 `0.255.0.255` 这类无效值，那么"目标地址从未被正确设置"就是新的根因——
而这依然指向"没有收到带服务器地址的数据"。**

**这次的教训要记住**：读结构字段前必须先确认寻址链的每一级，
否则会得出完全相反的结论。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.196"),
                         ("HANDOFF-CURRENT.md", "### 16.84")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.196", "### 16.84")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
