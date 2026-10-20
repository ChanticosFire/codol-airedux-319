"""Record round 140: two conditionals found inside the block, but neither is the guard."""
from pathlib import Path

TEXT = """
### 12.155 `0xBAE54B` 是汇合点；两个条件跳转都不是守卫，守卫在更早处（2026-10-25 18:2x）

#### 块内结构

```asm
0xBAE4A0  je 0xBAE4B2                         ; 条件 A
0xBAE4A4  call 0xBBA670
0xBAE4AA  call 0xB742E0
0xBAE4B2  mov dword [ebx+0x1FC], 0            ; ★ 清 1FC
0xBAE4BC  lea edi, [ebx+0x4D60]               ; 数组基址
0xBAE4C6  call 0xB74DA0
0xBAE4CB  cmp dword [ebx+0x4D6C], 0           ; ★ 数组计数
0xBAE4D6  je 0xBAE52B                         ; 为 0 -> 跳过搬运
0xBAE4D8  mov eax, [edi]
0xBAE4E1  call 0xB753C0                       ; 复制 136 字节
0xBAE4F7  mov ecx, 0x22
0xBAE4FC  rep movsd
0xBAE50D  mov ecx, 0x22
0xBAE518  rep movsd
0xBAE520  call 0xB76EE0                       ; 毒化
0xBAE525  mov esi, [ebp-0x9A8]
0xBAE52B  lea eax, [ebx+0x170]                ; je 目标
0xBAE53D  test esi, esi                       ; 条件 B
0xBAE53F  je 0xBAE54B
0xBAE541  add esi, 4
0xBAE545  call [0xCA8128]
0xBAE54B  mov ecx, [ebx+0x1F0]                ; ★ 两条路汇合
0xBAE55A  call edx                            ; [vt+0xC] = 0xC73EC0
0xBAE566  call 0xBB1A60
0xBAE57F  call 0xC699B0
0xBAE587  mov dword [ebx+0x1F4], 2            ; 无条件写 2
```

#### 关键观察：`0xBAE54B` 是汇合点

`0xBAE4D6` 的 `je` 目标是 `0xBAE52B`，`0xBAE53F` 的 `je` 目标是 `0xBAE54B`。
**两条路径都汇入 `0xBAE54B`，之后没有任何条件跳转，一直到 `0xBAE587` 写 2。**

**因此只要执行流进入 `0xBAE52B` 之后（或 `0xBAE54B`），写 2 就必然发生。**

#### 但哨兵实验显示写 2 从不发生

所以**执行流根本没进入这个块**。

**守卫在 `0xBAE4A0` 之前。**

#### 这个块的语义

从代码看：

1. `0xBAE4B2` 清 `[ebx+0x1FC]`（服务器列表游标）；
2. `0xBAE4CB` 检查 `[ebx+0x4D6C]`（数组里的条目数）；
3. 若不为 0，把**当前条目**（`[ebx+0x4D60] + 0x4D6C*0x88` 那条 136 字节记录）
   复制到临时区，再覆盖回原位置——**看起来像"把游标处的条目移到数组前端"**；
4. 然后清 `1FC`，调用 `[vt+0xC]`，再推进 `1F4 = 2`。

**这读作："把选中的服务器条目整理到位，然后提交并推进前端"。**

**正是"进入大厅"那一步该做的事。**

#### 下一步：找 `0xBAE4A0` 之前的分支

需要从更早的干净边界反汇编（`0xBAE440` 之前），找出：

- 这个块是被哪个条件跳转守护的；
- 那个条件依赖谁（很可能就是 `[ebx+0x4D6C]` 非零，即"数组里确实有条目"）。

**若守卫就是"数组条目数 > 0"，那结论就非常清晰了**：
**客户端始终拿不到服务器列表条目 → 数组空 → 不进入这个块 → `1F4` 永远是 1 → FE 梯停住。**

**这会把整条链彻底闭合，并指向同一个根因：服务器列表从未被接收。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.155"),
                         ("HANDOFF-CURRENT.md", "### 16.43")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.155", "### 16.43")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
