"""Record round 157: the last gate is a state code at [serverlist+0x1A0]."""
from pathlib import Path

TEXT = """
### 12.172 ★★★ 最后一道门是状态码 `[serverlist+0x1A0]`（2026-10-26 03:5x）

#### `0xBBA710` 全文

```asm
0xBBA710  mov ecx, dword ptr [ecx+0x1A0]   ; ★ 读 [serverlist + 0x1A0]
0xBBA716  xor al, al                        ; al = 0（默认）
0xBBA718  cmp ecx, 1
0xBBA71B  je 0xBBA727                       ; == 1 -> al = 1
0xBBA71D  cmp ecx, 2
0xBBA720  je 0xBBA727                       ; == 2 -> al = 1
0xBBA722  cmp ecx, 3
0xBBA725  jne 0xBBA729                      ; 其他 -> 返回 0
0xBBA727  mov al, 1
0xBBA729  ret
```

**逻辑极简：`[serverlist+0x1A0]` 等于 1、2 或 3 时返回 1，否则返回 0。**

#### 与标志 C 的关系（注意方向）

```asm
0xBAE2CD  call 0xBBA710
0xBAE2D2  test al, al
0xBAE2D4  jne 0xBAE2DD           ; al != 0 -> 跳到守卫，C 保持 0
0xBAE2D6  mov byte ptr [ebp-0x986], 1   ; al == 0 -> C = 1
```

**所以：**

| `[serverlist+0x1A0]` | `0xBBA710` 返回 | 标志 C | 第三道守卫 |
|---|---|---|---|
| 1、2、3 | 1 | **0** | **跳（复位）** |
| 0 或 ≥4 | 0 | **1** | **通过** |

**即：要让第三道守卫通过，`[serverlist+0x1A0]` 必须**不**是 1、2、3。**

#### 相邻函数给出了状态码的语义

```asm
0xBBA730  push esi
0xBBA731  xor esi, esi
0xBBA733  cmp dword ptr [ecx+0x1A0], 4     ; ★ 检查是否 == 4
0xBBA73A  jne 0xBBA744                       ; 不是 4 -> 返回 0
0xBBA73C  mov eax, dword ptr [ecx+0x19C]     ; == 4 -> 返回 [ecx+0x19C]
0xBBA743  ret
0xBBA744  call 0xBA4B20                       ; 日志
0xBBA749  mov eax, esi                        ; 返回 0
```

**`0xBBA730` 在状态为 4 时返回 `[ecx+0x19C]`（某个数据指针/长度），否则返回 0。**

**所以状态码 4 表示"有数据可取"。**

#### 于是整个逻辑拼齐了

```
状态 1/2/3  -> "列表在进行中/无效"  -> 0xBBA710 返回 1 -> 标志 C = 0 -> 守卫跳 -> 1F4 不推进
状态 4      -> "列表有数据"        -> 0xBBA710 返回 0 -> 标志 C = 1 -> 守卫通过 -> 1F4 可推进
状态 0      -> "未初始化"          -> 同样返回 0 -> 标志 C = 1 -> 守卫通过
```

**这与"服务器列表从未被正确接收"的根因假设完全一致：**
**列表对象停在 1/2/3 这类中间状态，永远到不了 4。**

#### 下一步：读这个字段

**`[serverlist+0x1A0]`** 是一个可以直接轮询的 dword
（`serverlist = [lobby+0x1FC]`）。

**读它就能立刻知道当前是几。**

- **若是 1/2/3** → 确认列表卡在中间状态，问题在"列表如何变成 4"；
- **若是 4** → 那 `0xBBA710` 应当返回 0、标志 C 应当为 1，
  说明我前面的推理有误，需要重新检查。

**这一次读取直接决定整条链的方向。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.172"),
                         ("HANDOFF-CURRENT.md", "### 16.60")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.172", "### 16.60")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
