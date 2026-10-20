"""Record round 179: sendto goes through IAT 0xCA8518 and errors are mapped by a jump table."""
from pathlib import Path

TEXT = """
### 12.194 `sendto` 的导入表位置 `0xCA8518`，错误码经跳表映射（2026-10-26 16:2x）

#### 发送与错误处理

```asm
0xBB1485  mov word ptr [ebp-0x12], ax          ; sockaddr.sin_port
0xBB1489  lea eax, [ebp-0x14]                   ; &sockaddr
0xBB148C  push eax                               ; 参数：sockaddr 指针
0xBB148D  push 0                                 ; 参数：flags
0xBB148F  push ecx                               ; 参数：长度
0xBB1490  push esi                               ; 参数：缓冲区
0xBB1491  push edi                               ; 参数：socket
0xBB1492  FF 15 18 85 CA 00      call dword ptr [0xCA8518]   ; ★ sendto
0xBB1498  8B C8                 mov ecx, eax
0xBB149A  85 C9                 test ecx, ecx
0xBB149C  0F 89 A8 00 00 00      jns 0xBB154A                 ; 返回 >= 0 -> 成功
0xBB14A2  FF 15 3C 85 CA 00      call dword ptr [0xCA853C]    ; ★ WSAGetLastError
0xBB14A8  8D 88 EC D8 FF FF      lea ecx, [eax-0x2714]        ; 错误码 - 10004
0xBB14AE  83 F9 3D               cmp ecx, 0x3D                ; 范围 0..61
0xBB14B1  0F 87 80 00 00 00      ja 0xBB1537                   ; 超出 -> 默认分支
0xBB14B7  0F B6 91 94 15 BB 00   movzx edx, byte [ecx+0xBB1594]  ; ★ 索引表
0xBB14BE  FF 24 95 7C 15 BB 00   jmp dword ptr [edx*4+0xBB157C]  ; ★ 跳表
0xBB14C5  …                       mov eax, 0xFFFFFFF8            ; 返回 -8
0xBB14DB  …                       mov eax, 0xFFFFFFFE            ; 返回 -2
```

#### 三项确认

1. **`sendto` 走 IAT `0xCA8518`**（`ws2_32` 的导入槽）；
2. **`WSAGetLastError` 走 IAT `0xCA853C`**（§12.62 已知）；
3. **错误码范围 `10004`–`10065`**（`0x2714` + 61），经
   **索引表 `0xBB1594`** 与 **跳表 `0xBB157C`** 映射到各自的返回值。

**返回值为负即判失败。`WSAENOTSOCK`（10038）落在这个范围内，
其对应分支返回某个负值。**

#### 关键意义

**`socket`、`connect`、`sendto` 等 API 的 IAT 槽位都集中在 `0xCA85xx` 这一小段。
其中 `sendto = 0xCA8518`、`WSAGetLastError = 0xCA853C`。**

**`socket` / `WSASocket` 的槽位必然也在这个邻域。**

**找到它之后，全镜像搜索对该槽的 `call dword ptr [...]` 引用，
就能定位"创建 socket"的代码——而 `lobby+4` 正是那个返回值应当被写入的地方。**

#### 下一步

**dump `0xCA84E0`–`0xCA8580`**，列出各槽位的函数指针，
并通过 `modules.py` 把每个指针归到 `ws2_32.dll + 偏移`，
从而认出 `socket`、`WSASocket`、`connect`、`bind`、`recvfrom` 等。

**然后用 `find_refs.py` 搜对 `socket` 槽的引用。**

**这是找到"为什么 socket 没被创建"的必经之路。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.194"),
                         ("HANDOFF-CURRENT.md", "### 16.82")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.194", "### 16.82")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
