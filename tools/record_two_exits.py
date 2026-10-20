"""Record round 133: 0xBBA1F0 has two exits, and the write of 4 sits after a ret."""
from pathlib import Path

TEXT = """
### 12.148 ★★★ `0xBBA1F0` 只有两条出口；写 4 位于 `ret` 之后（2026-10-25 14:2x）

#### 函数尾部

```asm
0xBBA2A0  mov al, 1                     ; 成功标志
0xBBA2A2  pop ebx
0xBBA2A3  mov ecx, [ebp-4]
0xBBA2A6  xor ecx, ebp
0xBBA2A8  call 0xC3C20F                 ; __security_check_cookie
0xBBA2AD  mov esp, ebp
0xBBA2AF  pop ebp
0xBBA2B0  ret                           ; ★ 正常出口（返回 al = 1）

0xBBA2B1  call 0xBA4B20                 ; ┐
0xBBA2B6  mov dword [esi+0x120], 4      ; │ 位于 ret 之后
0xBBA2C0  mov ecx, [ebp-4]              ; ★ jne 0xBBA2C0 的目标
0xBBA2C3  pop esi
0xBBA2C4  mov al, bl                    ; bl = 0 -> 返回 0
0xBBA2C6  xor ecx, ebp
0xBBA2C8  pop ebx
0xBBA2C9  call 0xC3C20F
0xBBA2CE  mov esp, ebp
0xBBA2D0  pop ebp
0xBBA2D1  ret                           ; 失败出口
```

#### 两条出口

| 入口条件 | 走向 | 返回值 |
|---|---|---|
| `[esi+0x120] == 1` | 构造容器 → 发包 → `mov al,1` → `ret` | **1（成功）** |
| `[esi+0x120] != 1` | `jne 0xBBA2C0` → `mov al,bl`（bl=0）→ `ret` | **0（失败）** |

**清晰、对称，没有任何第三条路径。**

#### 写 4 是死代码（或另有入口）

`0xBBA2B1`（`call 0xBA4B20`）与 `0xBBA2B6`（`mov [esi+0x120],4`）**位于
`0xBBA2B0` 的 `ret` 之后**，正常执行流不会到达。

**除非有某处的跳转直接指向 `0xBBA2B1`。**

§12.70 记录过 `0xBBA2B6` 是 `[ebx+0x120]` 的 8 个写入点之一——**但它可能是永远不执行的**。

#### 这澄清了一个长期误解

此前（§12.70 起）一直把 `0xBBA2B6`（写 4）当作一条**可能生效**的状态转移。
**现在看它很可能根本不会执行**，这就解释了为什么从未观测到状态 4。

#### 于是 `Add` 与 `0xBBA1F0` 的关系彻底清楚了

```
pump 每帧调 Add（27 次/秒）
  Add:
    ├─ count > 0  → 成功分支 → 写 2 → 返回        （哨兵实验：从不执行）
    └─ count <= 0 → 推进索引
                     ├─ 旧索引 < 容量 → 调 0xBBA1F0 → 发包 → 返回 1
                     └─ 旧索引 >= 容量 → 写 3 → 返回
```

**`0xBBA1F0` 只在"索引未满"时被调用，它的职责是把累积的数据发出去；
状态不是 1 时它直接返回 0，什么也不做。**

#### 下一步

用 `branches_to.py` 检查是否有跳转指向 `0xBBA2B1`：

- **没有** → 确认写 4 是死代码，可以从状态机分析中彻底排除；
- **有** → 找出那条路径。

**同时**：既然 `Add` 的 `count > 0` 分支从不执行，而 `count <= 0` 分支会发包——
**那客户端实际上一直在"发包"（`0xBBA1F0` 的发包路径），却从不"接收处理"**。

**这可能就是问题的本质：发送方向在工作，接收方向的入口（写 2）被卡住。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.148"),
                         ("HANDOFF-CURRENT.md", "### 16.36")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.148", "### 16.36")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
