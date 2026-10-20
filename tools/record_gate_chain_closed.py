"""Record round 44: the pump gate chain is fully closed - only one field is off."""
from pathlib import Path

TEXT = """
### 12.60 ★★★ pump 门控链完整闭合：三个标志全满足，只差 `[obj1+0x120]`（2026-10-23 14:5x）

#### 先排除"瞬时值"假设

§12.59 之后怀疑 `1F4` 可能短暂变成 2 又被写回 1。用极限速度采样 30 秒：

```
samples=8163566 dist={1: 8163566} transitions=0
```

**816 万次采样全部为 1，零次跳变。** `0xBAE1AC` 确实从未执行。

同时用 `jump_map.py` 扫 `0xBAE000`–`0xBAE200` 的全部 24 个跳转，
**没有一个跳出该区域**——所以不存在"绕过 `0xBAE1AC`"的跳转。
它没执行，只能是因为执行流在更早处就离开了。

#### 三个前置标志的实际值

`0xBAE2DD` / `0xBAE2EA` / `0xBAE2F7` 依次检查三个字节，任一为 0 就跳
`0xBAE7B4`（什么都不写，`1F4` 保持 1）。逐个求出实际值：

| 标志 | 设置点 | 条件 | 实测 | 结果 |
|---|---|---|---|---|
| `[ebp-0x988]` | `0xBAD876 sete` | `[lobby+0x4D70] == [lobby+0x18]` | 两者都是 **3** | **1** ✅ |
| `[ebp-0x989]` | `0xBAE28B` | `[obj1+0x120] != 1` | 实测 **3** | **1** ✅ |
| `[ebp-0x986]` | `0xBAE2D6` | `0xBBA710(obj2)` 为**假** | 见下 | **1** ✅ |

`0xBBA710` 是判 `[obj2+0x1A0] ∈ {1,2,3}` 的谓词：

```asm
0xBBA710  mov ecx, [ecx + 0x1a0]
0xBBA718  cmp ecx, 1
0xBBA71B  je 0xbba727          ; 1 -> true
0xBBA71D  cmp ecx, 2
0xBBA720  je 0xbba727          ; 2 -> true
0xBBA722  cmp ecx, 3
0xBBA725  jne 0xbba729         ; 其它 -> false
0xBBA727  mov al, 1
```

实测 `[obj2+0x1A0] = 5`，不在集合内 → 返回**假** → `flag986 = 1`。

**三个标志全部满足**，所以执行流确实到了 `0xBAE304`。

#### 唯一的失败点

```asm
0xBAE304  mov ecx, [ebx + 0x1f8]
0xBAE30A  call 0xBBA1E0          ; = [obj1 + 0x120]
0xBAE30F  cmp eax, 2
0xBAE312  jne 0xBAE5DB           ; ★ 3 != 2 -> 跳去遍历后写 1
```

**`[obj1+0x120]` 实测 3，而这里要求 2。就这一个数字。**

若它等于 2，则继续到：

```asm
0xBAE318  mov ecx, [ebx + 0x1fc]
0xBAE31E  call 0xBBA750          ; = [obj2 + 0x1a0] = 5
0xBAE323  cmp eax, 4
0xBAE326  jne 0xBAE5DB           ; 5 != 4 -> 也会跳走
```

即**两个字段都差一步**：`obj1+0x120` 需 2（现 3），`obj2+0x1A0` 需 4（现 5）。
§12.51 观察到"各差 1"是对的，现在知道了它们在判定链里的确切位置。

#### 这条链的完整结论

```
pump 入口 (0xBAD83D/0xBAD846 两道门)          ✅ [lobby+8]=1, [lobby+0x1F4]=1
  → 三个前置标志 (0xBAE2DD/2EA/2F7)           ✅ 全部 = 1
  → [obj1+0x120] == 2 ?                       ❌ 实测 3
      ├─ 否 → 0xBAE5DB 遍历 → 0xBAE781 → 写 1
      └─ 是 → [obj2+0x1A0] == 4 ?
                ├─ 否 → 同上
                └─ 是 → 0xBAE32C … → 0xBAE1AC 写 2
```

**`0xBAD800` 这条路径上，全部条件都已满足，只有两个状态字段停在"差一步"的位置。**

#### 写 3 和写 5 的地方

| 值 | 地址 | 上下文 |
|---|---|---|
| `[obj1+0x120] = 3` | `0xBBA62B` | 与写 2 的 `0xBBA569` 相隔 0xC2 字节，同一函数的不同分支 |
| `[obj2+0x1A0] = 5` | `0xBBADCD` 等 5 处 | `0xBBAD40` 的失败分支 |

#### 下一步

要让 `[obj1+0x120]` 从 3 变 2，需要让 `0xBBA569` 所在分支执行。它和
`0xBBA62B` 在同一函数内，两者之间很可能只差一个条件判断。
**下一轮直接反汇编 `0xBBA520`–`0xBBA640` 这段，找出两个分支的分歧点。**

若该分歧点依赖网络数据，就需要补对应应答；若依赖 `[obj2+0x1A0]`，则先解决
`0xBBAD40` 的 136 vs 1288 矛盾（§12.54）。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.60"),
                         ("HANDOFF-CURRENT.md", "### 15.48")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.60", "### 15.48")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
