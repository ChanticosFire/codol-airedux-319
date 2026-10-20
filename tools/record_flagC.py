"""Record round 156: forcing flag A does not help, so flag C is the last gate."""
from pathlib import Path

TEXT = """
### 12.171 强制标志 A 后 `1F4` 仍不变，标志 C 是最后一道门（2026-10-26 03:2x）

#### 实验

三个补丁：

```
0xBBA465  0F 84 3A 01 00 00  ->  90 x6                （Add 过滤 A）
0xBBA483  0F 84 1C 01 00 00  ->  90 x6                （Add 过滤 B）
0xBAD876  0F 94 85 78 F6 FF FF  ->  C6 85 78 F6 FF FF 01  （标志 A 强制置 1）
```

第三个补丁把 `sete byte [ebp-0x988]` 改成 `mov byte [ebp-0x988], 1`，两者都是 7 字节，
纯数据替换。

#### 结果

```
patched 0xbba465  Add filter A
patched 0xbba483  Add filter B
patched 0xbad876  flag A forced to 1
  t=  0.00  status=None  1F4=None  FE=2  G1=0  dw=0
  t= 10.19  status=None  1F4=   1  FE=5  G1=0  dw=0
  t= 15.02  status=   1  1F4=   1  FE=5  G1=0  dw=2
  t= 15.06  status=   2  1F4=   1  FE=5  G1=0  dw=2

samples with 1F4==2: 0
final: (2, 1, 5, 0)
```

**状态成功到达 2，但 `1F4` 从未变成 2。**

#### 三个标志的排除进度

| 标志 | 状态 | 依据 |
|---|---|---|
| `[ebp-0x988]` | **已强制为 1** | 本轮补丁 |
| `[ebp-0x989]` | **已为 1** | 状态 = 2（§12.164） |
| `[ebp-0x986]` | **未知** | 取决于 `0xBBA710` 返回值 |

**前两个都已满足，`1F4` 仍不推进——所以第三个是唯一的剩余缺口。**

#### 标志 C 的条件

```asm
0xBAE2C7  mov ecx, dword ptr [ebx+0x1FC]
0xBAE2CD  call 0xBBA710
0xBAE2D2  test al, al
0xBAE2D4  jne 0xBAE2DD           ; al != 0 -> 不置位
0xBAE2D6  mov byte ptr [ebp-0x986], 1   ; al == 0 -> 置 1
```

**需要 `0xBBA710` 返回 0（`al == 0`）。**

#### 下一步

**反汇编 `0xBBA710`**，看它的返回条件。

- 若它返回的是"某个查询成功/失败"的标志，那就需要让那个查询成功；
- 若它返回的是容器状态（例如"是否为空"），那可能需要容器里有数据。

**这是最后一道门，弄清它就能知道客户端究竟缺什么。**

#### 一个重要的旁证

`0xBAE2C7` 的 `ecx` 是 `[ebx+0x1FC]`——**服务器列表对象**。

**所以 `0xBBA710` 检查的是服务器列表的状态。**

**若它返回非零表示"列表无效/为空"，那 `1F4` 推不动就直接对应"服务器列表从未被正确接收"**
——这与前面几十轮在 `Add`/收包路径上的所有发现指向同一个根因。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.171"),
                         ("HANDOFF-CURRENT.md", "### 16.59")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.171", "### 16.59")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
