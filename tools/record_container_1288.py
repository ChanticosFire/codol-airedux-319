"""Record round 61: the count comes from a 1288-byte container filled by a virtual call."""
from pathlib import Path

TEXT = """
### 12.75 ★★★ `count` 来自一个 1288 字节容器，由虚调用填充（2026-10-23 23:2x）

#### `[ebp-0x768]` 的五个引用点

在 `0xBAE000`–`0xBAF000` 内搜 `98 f8 ff ff`（`-0x768` 的 disp32）共 5 处：

| 地址 | 指令 | 作用 |
|---|---|---|
| `0xBAE215` | `lea ecx, [ebp-0x768]` | 构造 |
| `0xBAE234` | `lea edx, [ebp-0x768]` | 作为虚调用的参数 |
| `0xBAE25C` | `lea edx, [ebp-0x768]` | 复制到栈，传给 `Add` |
| `0xBAE2A8` | `lea edx, [ebp-0x768]` | 同样复制，用于 obj2 |
| `0xBAE7B4` | `lea ecx, [ebp-0x768]` | 尾部析构 |

#### 它是一个 1288 字节容器

按原始字节手工解码 `0xBAE20B` 起（capstone 在该处错位，改用字节直读）：

```asm
0xBAE20B  cmp dword ptr [ebx + 0x1f4], 1
0xBAE212  jne 0xBAE7C9                     ; 0f 85 b1 05 00 00
0xBAE218  lea ecx, [ebp - 0x768]
0xBAE21E  call 0xB753A0                    ; ★ 构造容器
0xBAE223  mov ecx, [ebx + 0xc]
0xBAE226  mov eax, [ecx]
0xBAE228  mov eax, [eax + 0x1c]            ; 虚函数槽
0xBAE22B  push 0x508                        ; ★ 1288 字节
0xBAE230  lea edx, [ebp - 0x548]
0xBAE236  push edx
0xBAE237  lea edx, [ebp - 0x768]
0xBAE23D  push edx
0xBAE23E  mov dword ptr [ebp - 4], 0x17
0xBAE245  call eax                          ; ★ 由它填充容器
0xBAE247  mov esi, eax
```

**`0x508 = 1288` 正是 §12.36 追了很久的那个长度。** 同一份数据、同一个数字，
之前从 `0xBBA760` 那一侧看到，现在从 pump 这一侧看到——两个方向都指向
**1288 字节的容器记录**。

#### `count` 的确切位置

`Add` 的调用序列（`0xBAE24E`–`0xBAE276`）：

```asm
0xBAE24E  push esi                          ; [ebp+0x08] = 虚调用返回值
0xBAE24F  lea ecx, [ebp - 0x548]
0xBAE255  push ecx                          ; [ebp+0x0C]
0xBAE256  sub esp, 0x88                     ; 136 字节
0xBAE25C  lea edx, [ebp - 0x768]
0xBAE262  mov ecx, esp
0xBAE26A  push edx
0xBAE26B  call 0xB753C0                     ; 把容器前 136 字节复制到栈
0xBAE270  mov ecx, [ebx + 0x1f8]
0xBAE276  call 0xBBA3F0                     ; Add
```

栈上参数从 `[ebp+0x10]` 起是那 136 字节结构，所以：

- `[ebp+0x90]` = 结构 `+0x80` = **容器 `+0x80`**
- `[ebp+0x94]` = 结构 `+0x84` = **容器 `+0x84`**

**`Add` 的 count 就是那个 1288 字节容器的 `+0x84` 字段。**

#### 因果链到这里完整了

```
pump 每帧：
  0xBAE218  构造 [ebp-0x768]（1288 字节容器）
  0xBAE22B  push 0x508
  0xBAE245  虚调用 [lobby[0xC]]->vtable[0x1C]   ← 由它填充容器
  0xBAE26B  把容器前 136 字节复制到栈
  0xBAE276  Add(obj1, 栈结构)
              → count = 容器 +0x84
              → 若为 0：只推进索引 [obj1+0x130] += 1
              → 索引到容量后写 3，永久短路
```

**`count = 0` 意味着那个虚调用没有把条目数写进容器 `+0x84`。**

#### 这与服务端的关系

容器由 `[lobby+0xC]` 这个对象的虚函数填充。`[lobby+0xC]` 在 §12.30 已经被确认
是"接口对象、非空指针"。它请求 **1288 字节**，说明它期望一条完整的
**服务器描述记录**。

若这个虚调用读取的是服务端 `svc71/task4` 的应答内容，那么在应答缺字段时
条目数自然是 0。**这与 §12.54 的"容器要求 {类型 0x14, key 0, 1288 字节}"
是同一件事的两面**。

#### 下一步

1. 反汇编 `[lobby+0xC]` 的 vtable `+0x1C` 槽，确认那个虚函数到底从哪取数据；
2. 若它取的是 `0xBBA760` 那条 key-0 的记录，那么问题回到 **谁该插入那条
   1288 字节记录**——而 §12.54 已证明 `0xBBAD40` 只准备 136 字节；
3. 检查 `svc71/task4` 应答是否应携带一个"条目数"字段，使容器 `+0x84` 非零。

第 1 条最直接：读 `[lobby+0xC]` 的 vtable，取 `+0x1C` 槽的函数地址，反汇编它。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.75"),
                         ("HANDOFF-CURRENT.md", "### 15.63")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.75", "### 15.63")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
