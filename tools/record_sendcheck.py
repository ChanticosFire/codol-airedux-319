"""Record round 171: the send must return exactly the serialised length."""
from pathlib import Path

TEXT = """
### 12.186 ★★★ `0xBBA760` 的发送是 `vt+0x18`，且要求返回值恰好等于序列化长度（2026-10-26 12:2x）

#### 关键代码

```asm
0xBBA7BA  mov edx, dword ptr [ebp-0x510]   ; 序列化后的长度
0xBBA7C0  mov ecx, dword ptr [esi]          ; this 的 vtable 指针所在
0xBBA7C2  mov eax, dword ptr [ecx]          ; vtable
0xBBA7C4  mov eax, dword ptr [eax+0x18]     ; ★ vt+0x18（= 0xC73F30，发送）
0xBBA7C7  push edx                           ; 参数：长度
0xBBA7C8  lea edx, [ebp-0x50C]               ; 参数：序列化缓冲
0xBBA7CE  push edx
0xBBA7CF  push edi                           ; 参数：类型（本函数第 2 参数）
0xBBA7D0  call eax                           ; ★ 发送
0xBBA7D2  test eax, eax
0xBBA7D4  jle 0xBBA7F3                        ; ★ 返回值 <= 0 -> 失败
0xBBA7D6  cmp eax, dword ptr [ebp-0x510]
0xBBA7DC  jne 0xBBA7F3                        ; ★ 返回值 != 长度 -> 失败
0xBBA7DE  pop edi / pop esi
0xBBA7E0  mov al, 1                            ; 成功
0xBBA7F0  ret 8
```

#### 成功条件

**三个条件同时满足才算成功：**

1. **序列化成功**（`0xBBA7B8` 的 `cmp al,1`）；
2. **发送返回值 `> 0`**；
3. **发送返回值 `== 序列化长度`**。

#### `vt+0x18` 已确认

§12.88 记录 `[vt+0x18] = 0xC73F30`，其内部 `0xC73F88` 调用 `0xBB1420`（UDP `sendto` 包装）。

**所以这里就是真正的网络发送点。**

#### 状态 5 的成因进一步收窄

`0xBBA8C0` 发送的是 **`this+4` 处的数据，类型 3，序列化后 1288 字节以内的长度**。

**若 `sendto` 返回的字节数与长度不符（例如部分发送、或返回 SOCKET_ERROR），
就判定失败 → 状态 5。**

**可能的具体原因：**

- **`0xC73F30` 内部有对长度上限的检查**，超过就返回 0；
- **`this+4` 那部分数据尚未初始化**，序列化出来的长度异常；
- **`sendto` 因为目标地址问题失败**。

#### 一个重要观察

**`0xBBA8C0` 用类型 3 发送 `this+4`——这不是服务器列表请求，而是某种"响应确认"。**

**所以状态 5 未必与我们的服务器列表消息直接相关：它可能是客户端在收到我们的回复后，
试图回发一条确认（类型 3）却失败了。**

**若如此，那么我们的回复其实是被接受的，只是客户端回发确认这一步出了问题。**

**下一步**：反汇编 `0xC73F30`，看它在什么条件下返回非正数或与长度不符的值。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.186"),
                         ("HANDOFF-CURRENT.md", "### 16.74")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.186", "### 16.74")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
