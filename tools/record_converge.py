"""Record round 155: all paths converge on the guards, and flag C depends on one call's result."""
from pathlib import Path

TEXT = """
### 12.170 ★★★ 三条路都汇入守卫入口；标志 C 取决于 `0xBBA710` 的返回值（2026-10-26 02:5x）

#### `0xBAE292`–`0xBAE2D6` 全文

```asm
0xBAE292  cmp dword ptr [ebx+0x1FC], edi    ; 服务器列表对象 vs ebx+8
0xBAE298  je 0xBAE2DD                        ; 相等 -> 直接到守卫
0xBAE29A  push esi                            ; 不等 -> 构造一份副本
0xBAE29B  lea eax, [ebp-0x548]
0xBAE2A1  push eax
0xBAE2A2  sub esp, 0x88                       ; 136 字节
0xBAE2A8  lea edx, [ebp-0x768]
0xBAE2B7  call 0xB753C0                       ; 复制
0xBAE2BC  mov ecx, dword ptr [ebx+0x1FC]
0xBAE2C2  call 0xBBADE0
0xBAE2C7  mov ecx, dword ptr [ebx+0x1FC]
0xBAE2CD  call 0xBBA710                       ; ★ 关键调用
0xBAE2D2  test al, al
0xBAE2D4  jne 0xBAE2DD                        ; al != 0 -> 到守卫（C 保持 0）
0xBAE2D6  mov byte ptr [ebp-0x986], 1         ; ★ al == 0 -> C = 1
```

#### 结构

```
                    ┌─ je (相等) ──────────────────────┐
0xBAE292 ──────────┤                                   │
                    └─ 不等 → ... → call 0xBBA710 ─┬── jne (al != 0) ──┤
                                                    └── al == 0 → C=1 ──┤
                                                                        ▼
                                                                  0xBAE2DD（三道守卫）
```

**三条路径全部汇入 `0xBAE2DD`，没有绕过守卫的可能。**

#### 三个标志的最终状态取决于

| 标志 | 来源 | 条件 |
|---|---|---|
| `[ebp-0x988]` | `0xBAD876 sete` | `[ebx+0x4D70] == [ebx+0x18]` |
| `[ebp-0x989]` | `0xBAE28B mov 1` | `Add` 之后 `obj1` 状态 != 1 |
| `[ebp-0x986]` | `0xBAE2D6 mov 1` | `0xBBA710` 返回 0 |

#### 而 §12.164 已经让第二项成立

状态已稳定为 2，所以 `[ebp-0x989] = 1`。

**所以现在只需要 `[ebp-0x988]` 与 `[ebp-0x986]` 也非零。**

- `[ebp-0x986]` 需要一个返回 0 的 `0xBBA710`；
- `[ebp-0x988]` 需要 `[ebx+0x4D70] == [ebx+0x18]`。

#### 下一步：读这两个字段

**`[ebx+0x18]` 与 `[ebx+0x4D70]`** 是 lobby 上的两个 dword。

**直接轮询读它们就能知道 `sete` 的结果。**

**同时在 §12.164 的补丁下再跑一次，读三个标志的实际值**——
虽然它们是栈变量，但可以用哨兵法把 `0xBAD876` 的 `sete` 目标改成固定写 1，
观察 `1F4` 是否变成 2。若变，则确认 `[ebp-0x988]` 是最后一个缺口。

**这是最直接的一步：强制 `[ebp-0x988] = 1`（把 `sete [ebp-0x988]` 改成
`mov byte [ebp-0x988],1`），其余保持原样，看 `1F4` 是否推进。**

**该处编码为 `0F 94 85 78 F6 FF FF`（7 字节），改成
`C6 85 78 F6 FF FF 01`（7 字节）——长度完全一致，是安全的纯数据修改。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.170"),
                         ("HANDOFF-CURRENT.md", "### 16.58")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.170", "### 16.58")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
