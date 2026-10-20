"""Record round 50: the producer runs 20x/s but its entry gates on status == 1."""
from pathlib import Path

TEXT = """
### 12.64 ★★★ 生产者每帧被调用 20 次/秒，但入口要求状态 == 1，而实际是 3（2026-10-23 17:0x）

#### 生产者入口与其调用者

从 `0xBBA569` 向前扫 `CC` 填充，得到函数入口 **`0xBBA3F0`**：

```
0xBBA3EE  CC CC
0xBBA3F0  55 8B EC 6A FF 68 BE 0F C9 00 64 A1 00 00 00 00
          push ebp / mov ebp,esp / push -1 / push 0xC90FBE / mov eax,fs:[0]
```

`find_calls.py 0xBBA3F0` 只返回**一个**调用者：

```
call at 0x00BAE276
```

而 `0xBAE276` 就在 pump 内部：

```asm
0xBAE246  cmp dword ptr [ebx + 0x1f8], edi    ; obj1 为空则跳过
0xBAE24C  je 0xBAE292
0xBAE270  mov ecx, [ebx + 0x1f8]
0xBAE276  call 0xBBA3F0                        ; ★ 生产者
0xBAE27B  mov ecx, [ebx + 0x1f8]
0xBAE281  call 0xBBA1E0
0xBAE286  cmp eax, 1
0xBAE289  je 0xBAE292
0xBAE28B  mov byte ptr [ebp - 0x989], 1
```

#### 生产者确实在跑

用计数器挂在 `0xBBA3F0` 入口：

```
[producer] calls = 29, 59, 89, 119, 149, 179, 209, 238, 310
```

15 秒 **310 次**，约 **20 次/秒**。而 pump 约 51 次/秒——说明 pump 每次不是都走到
`0xBAE246`，或者 `[lobby+0x1F8]` 有时为 0。

#### 它为什么什么都没做

入口第一条实质判断就是：

```asm
0xBBA426  cmp dword ptr [ebx + 0x120], 1
0xBBA42D  mov dword ptr [ebp - 4], 0
```

**它要求 `[obj1+0x120] == 1` 才继续。** 而实测该字段是 **3**。

所以生产者每帧被调用、每帧因为状态不是 1 而提前离开，`0xBBA569` / `0xBBA62B`
（写 2 / 写 3）从未执行——这完全解释了 §12.63 的 0 次计数。

#### 完整闭环

```
启动阶段：某处把 [obj1+0x120] 写成 3（以及 [obj2+0x1A0] 写成 5）
   ↓
pump 每帧（51 次/秒）
   ├─ 0xBAE276 调生产者 0xBBA3F0（20 次/秒）
   │     └─ 0xBBA426 检查 0x120 == 1 → 实际 3 → 立即返回，什么都不写
   ├─ 0xBAE281 call 0xBBA1E0 → 返回 3
   ├─ 0xBAE30A cmp 3, 2 → 不等 → jne 0xBAE5DB
   └─ 0xBAE781 → 0xBAE7AA 写 [lobby+0x1F4] = 1
   ↓
1F4 恒为 1，FE 梯停在 G1=0/1，客户端留在代号页
```

**没有任何环节"卡住"或"未运行"——每个函数都在按设计执行。
问题是两个状态字段在启动阶段就被推到了 3 和 5，而后续所有代码都要求它们是 1 和 2。**

#### 由此得到的新方向

真正要查的是：**启动阶段是谁把 `[obj1+0x120]` 写成 3 的？**

- 若不是 `0xBBA62B`（本轮已证明它 0 次），那还有第三种写入方式；
- 之前用 `c7 /r` 立即数模式只找到 `0xBBA62B`，说明写入用的是寄存器形式
  （`mov eax,3` → `mov [ebx+0x120],eax`）或 `inc`/`or` 等；
- 找到它之后，就能判断那一步是否依赖某个服务应答或初始化顺序。

下一步：扫 `0xBBA*` 与 `0xBA*` 区间内所有 `mov [reg+0x120], r32`（`89 /r`），
并对候选逐个装计数器，找出启动期真正命中的那一个。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.64"),
                         ("HANDOFF-CURRENT.md", "### 15.52")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.64", "### 15.52")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
