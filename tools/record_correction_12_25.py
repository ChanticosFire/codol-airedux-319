"""Record the correction: 0xBAF040 handles server-address data, not a cipher."""
from pathlib import Path

TEXT = """
### 12.25 修正：`0xBAF040` 处理的是服务器地址，不是加密通道（2026-10-23 01:3x）

#### 原来的判断

上一节（§12.24）因为 `0xBAF040` 里有 `rep movsd` 34 次（136 字节）而推断
它对应 1649370 的 `0xBA3010`（读 tag 1 的 136 字节），进而认为写 2 依赖
加密通道初始化。

#### 实测推翻

`0xBAF040` 的数据来源是：

```asm
0xBAF060  add ecx, 0x4C8        ; ecx 原本是 lobby+0x208 -> 变成 lobby+0x6D0
0xBAF066  call 0xBAFDA0          ; 取数据
```

而 `0xBAFDA0` 是：

```asm
0xBAFDA4  movzx eax, word [ecx+0x1D4]   ; 长度 = [lobby+0x8A4]，16 位
0xBAFDAF  add ecx, 0x1D8                 ; 数据 = [lobby+0x8A8]
0xBAFDC0  call 0xB753F0                  ; 复制
```

实测（`tools/probe_lobby_1f4.py`）：

```
chan_len @+0x8A4 = 22011 (0x55FB)
chan_head        = c0 a8 01 03 00 00 00 00 00 00 00 00 fe ff ff ff
                 = 192.168.1.3, 0, 0, -2
[lobby+0x6D0]    = 15
[lobby+0x6D4]    = 0
```

**`[lobby+0x8A8]` 里是 IP 地址与端口一类的服务器信息，不是密文。**
`136` 只是 `rep movsd` 的固定复制长度（34 dwords），与源数据实际长度（22011）
无关——复制的是前 136 字节。

#### 需要修正的结论

§12.24 里「两个版本的加密通道初始化是同一套代码」的判断**不成立**：
`0xBAF040` 与 `0xBA3010` 只是结构相似（都是「取一块数据 → 复制 → 判定」的
常见形态），处理的数据完全不同。

因此 `[lobby+0x1F4]` 停在 1 的原因**不是**加密通道未建立，而是
**`[lobby+0x8A8]` 这块服务器信息不符合 `0xBAF040` 的期望**。

#### 判定链

```asm
0xB77020  lea ecx,[ebp-0x88]
0xB7703C  call 0xB76F10          ; 构造临时对象
0xB77041  push eax
0xB77042  mov ecx, esi
0xB77044  call 0xB76FD0          ; 比较
0xB7704C  test al, al
0xB7704E  sete al                ; 返回 1 当比较结果为 0（相等）
```

即 `0xBAF040` 成功 = `0xB76FD0(对象, 临时对象) == 0`。

#### 下一步

1. 反汇编 `0xB76F10` 与 `0xB76FD0`，确认它在比较什么字段；
2. 结合 `[lobby+0x8A8]` 的实际内容（`192.168.1.3` 起）判断客户端期望的
   服务器信息格式；
3. 若确认为服务器地址结构，则**由服务端下发正确的大厅服务器信息**即可让
   `0xBAF040` 返回成功，`[lobby+0x1F4]` 自然走到 2——这比伪造加密帧简单得多。

#### 与协议的关系

`192.168.1.3` 是本机内网地址，说明客户端确实拿到了某个"服务器地址"，
但可能缺少配套的端口或服务器标识字段（后续 12 字节里有 `fe ff ff ff`，
像是 -2 的哨兵值）。这或许正是 pump 判定失败的原因。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.25"),
                         ("HANDOFF-CURRENT.md", "### 15.13")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.25", "### 15.13")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
