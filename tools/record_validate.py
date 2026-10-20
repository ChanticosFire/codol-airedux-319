"""Record round 168: state 5 means the copied data failed validation at 0xBBA8C0."""
from pathlib import Path

TEXT = """
### 12.183 ★★★ 状态 5 的成因：136 字节数据经 `0xBBA8C0` 验证失败（2026-10-26 10:2x）

#### 第一处写 5（`0xBBAAAC`）的上下文

```asm
0xBBAA83  mov ecx, [ebp-0x3C]
0xBBAA86  call 0x848AD0                  ; 取数据指针
0xBBAA8B  mov esi, eax
0xBBAA8D  lea edi, [ebx+0x114]           ; 目标：对象内 136 字节区
0xBBAA93  mov ecx, 0x22                   ; 34 个 dword
0xBBAA98  rep movsd                       ; ★ 复制 136 字节
0xBBAA9A  call 0xBA4B20                   ; 日志
0xBBAA9F  mov ecx, ebx
0xBBAAA1  call 0xBBA8C0                   ; ★ 验证
0xBBAAA6  test al, al
0xBBAAA8  jne 0xBBAAC7                    ; 验证通过 -> 写 2
0xBBAAAA  pop edi / pop esi
0xBBAAAC  C7 83 A0 01 00 00 05 00 00 00   mov dword [ebx+0x1A0], 5   ; ★ 失败 -> 写 5
0xBBAAAC  …
0xBBAAC7  C7 83 A0 01 00 00 02 00 00 00   mov dword [ebx+0x1A0], 2   ; ★ 通过 -> 写 2
0xBBAAD1  C6 83 A4 01 00 00 00            mov byte [ebx+0x1A4], 0
```

#### 状态码的完整语义（更新）

| 码 | 含义 |
|---|---|
| 1 | 请求已发出，等待 |
| **2** | **数据验证通过（进入下一阶段）** |
| 3 | 另一中间态 |
| 4 | 有数据可取（`0xBBA900` 路径写入） |
| **5** | **数据验证失败（错误）** |

**我们的九字节回复让状态变成 5——说明数据确实被解析并放进 `[ebx+0x114]`，
但 `0xBBA8C0` 判定它不合法。**

#### 状态 2 意味着客户端会继续推进

**`0xBBAAA8` 的 `jne` 一旦成立（验证通过），状态变 2 并写 `[ebx+0x1A4] = 0`，
然后返回——客户端进入下一个阶段。**

**注意：状态 2 也在 `0xBBA710` 的 "pending" 集合（1/2/3）里，
所以仅到 2 还不足以让 `1F4` 推进；但 2 是通往 4 的必经之路。**

#### 下一步

**反汇编 `0xBBA8C0`**——它决定那 136 字节是否合法。

**这将是"如何构造正确的 `0x15` 负载"的最终答案。**

**所有字段的约束都会在那里一次性揭示。**

**同时可以提前推测**：136 字节是 §12.69 反复出现的记录大小（`ecx=0x22`），
而 `+0x84` 字段是端口（3074）。**所以验证很可能检查端口、IP、或者某些计数是否合理。**

**若验证只检查端口是否非零，那把 dword 字段填上 3074 就能通过。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.183"),
                         ("HANDOFF-CURRENT.md", "### 16.71")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.183", "### 16.71")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
