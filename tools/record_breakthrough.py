"""Record round 148: the sentinel appears, so the two filters were the blocker."""
from pathlib import Path

TEXT = """
### 12.163 ★★★★ 突破：消除两条过滤后哨兵出现，`0xBBA569` 确实可达（2026-10-25 22:2x）

#### 实验与结果

```
patched 0xBBA465  filter A (dup check)    0F 84 3A 01 00 00 -> 90 90 90 90 90 90
patched 0xBBA483  filter B (append)       0F 84 1C 01 00 00 -> 90 90 90 90 90 90
patched 0xBBA569  store -> sentinel       …02 00 00 00 -> …34 12 CD AB

  t= 15.04  status=0x00000001  idx=0  dw=2
  t= 15.06  SENTINEL  status=0xabcd1234
  t= 15.06  status=0xabcd1234  idx=0  dw=2
  t= 15.08  SENTINEL  status=0xabcd1234
  …（持续到采样结束）
```

**哨兵值 `0xABCD1234` 反复出现并稳定保持。**

#### 三个确定结论

1. **`0xBBA569`（写 2）确实可达**——只要绕过 `0xBBA465` 与 `0xBBA483` 两条 `je`；
2. **写 2 之后 `jne 0xBBA5CA` 正常跳走**——哨兵值没有被覆盖，
   说明 `Add` 走的是"写 2 后立即返回"的路径；
3. **这两条 `je` 是唯一的过滤**——更深的路径（`0xBBA48F` 之后的 `call 0x848AD0` 等）都能正常执行。

#### 这两条过滤为什么成立

| 分支 | 检查 | 成立条件 |
|---|---|---|
| `0xBBA465` | `0xB75440(obj1+4, 结构)` 的返回值 | **返回 0**（两记录的 `+0x84` 不同或类型不符） |
| `0xBBA483` | `0xBC1A50(容器, …)` 的返回值 | **返回 0**（追加失败） |

**`je` 在 `test al,al` 之后——即"结果为零则跳走"。**

**所以：只有当"比较结果非零（相同）"**且**"追加成功"时，才会继续到写 2。**

等等——第一个条件的方向需要复核：

```asm
0xBBA45E  call 0xB75440
0xBBA463  test al, al
0xBBA465  je 0xBBA5A5          ; al == 0 -> 跳过写 2
```

**`0xB75440` 返回 1 表示"相同"、0 表示"不同"（§12.82）。**

**所以 `je` 成立意味着"不相同"——即"当前条目与容器已有记录不同"时**
**反而跳过写 2。**

**这个逻辑是反的？**

**更可能的是：`0xB75440` 的语义是"是否应当拒绝"**——即在某些条件下返回 0，
表示"这批数据不该被接受"。

#### 下一步：规范化验证

**去掉哨兵，只保留两条 `je` 的 NOP 补丁**，看 `obj1[0x120]` 是否变成 **2** 并保持。

若能，则：

- 状态变 2 ✔
- `0xBAE30F cmp eax,2` 通过 ✔
- `1F4` 被写成 2 ✔（`0xBAE587`）
- **FE 梯可能开始推进**

**这将是从第 60 轮以来第一次让客户端真正越过这个卡点。**

之后需要做的是把这两条 `je` 的补丁规范化、确认副作用、并考虑是否能通过
**提供正确的数据**让 `je` 自然不成立（那才是根本修复）。

**但首先验证：不掩盖，只是绕过过滤，系统是否真的能前进。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.163"),
                         ("HANDOFF-CURRENT.md", "### 16.51")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.163", "### 16.51")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
