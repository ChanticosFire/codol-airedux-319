"""Record round 165: the entry handler reads through 0xB770F0 then a word."""
from pathlib import Path

TEXT = """
### 12.180 条目处理器 `0xB75720`：先调 `0xB770F0`，再读 2 字节（2026-10-26 07:5x）

#### 代码

```asm
0xB75720  push ebp / mov ebp,esp / push ecx
0xB75724  mov eax, [ebp+8]            ; 参数 1：数据指针
0xB75728  mov ebx, [ebp+0xC]          ; 参数 2：剩余长度
0xB7572C  mov esi, [ebp+0x14]         ; 参数 5：游标
0xB75730  mov edi, [ebp+0x10]         ; 参数 4：偏移
0xB75733  push esi / push edi / push ebx / push eax
0xB7573A  mov [esi], edi
0xB7573C  call 0xB770F0               ; ★ 第一个读函数
0xB75741  test al, al
0xB75743  je 0xB75779                  ; 失败返回
0xB75745  mov eax, [esi]
0xB7574A  push 2                       ; ★ 再读 2 字节
0xB75754  call 0xB78450
```

#### 结构

一条记录由两部分组成：

1. **`0xB770F0` 负责读取的部分**（长度未知）；
2. **一个 2 字节 word**。

`0xB75720` 的参数与 `0xBC1D20` 完全相同（数据指针、长度、游标、偏移），
**所以它是"读一条记录"的子程序。**

#### 下一步

**反汇编 `0xB770F0`**——它是记录的第一个字段的读取器。

**若它也只是一次"读 N 字节"，那整个记录就是两个定长字段，可以精确算出消息总长度。**

**届时就能构造一条真正合法的 `0x15` 消息。**

#### 一条实用的退路

即使数据格式还没完全解清，**也可以先做一次"最小触发实验"**：
在 `lobby_udp.py` 里对探测包 `14 02 00 00` 回一条 `15 01 00` + 若干填充字节，
然后轮询 `serverlist[0x1A0]` 是否变成 4。

**如果解析失败，状态不会变——但也不会崩**（`0xBBAB5E` 的 `jne` 会跳过）。
**这能安全地验证通道是否正确**（即这条消息是否走 UDP 3074、是否被 `pump` 处理到）。

**这个实验值得先做，因为它能立刻回答"通道对不对"这个更基础的问题。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.180"),
                         ("HANDOFF-CURRENT.md", "### 16.68")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.180", "### 16.68")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
