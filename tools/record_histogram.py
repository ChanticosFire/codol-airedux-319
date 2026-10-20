"""Record round 123: 91 percent of Add's calls receive a positive count of 3."""
from pathlib import Path

TEXT = """
### 12.138 ★★★ 直方图：91.4% 的调用 `count = 3`（正数），却从未写 2（2026-10-25 09:2x）

#### 给探针加直方图

`probe_reg.py` 新增 `--histogram`：把第一个 `--mem-ebp` 槽位的每次采样值累加统计，
结束时输出正/零/负的比例与出现最多的几个值。

#### 结果

在 `0xBBA43A` 采样 12 秒、1151 次命中：

```
[HISTOGRAM] over 1151 samples: positive=1052 (91.4%) zero=3 negative=96 (8.3%)
    0x00000003  x1045
    0xfffffffe  x96
    0x00000004  x7
    0x00000000  x3
```

**`[ebp+0x94]` 有 91.4% 的采样是正数，其中 1045 次恰好等于 3、7 次等于 4。
只有 8.3%（96 次）是 `-2`。**

#### 这个分布把矛盾劈到了极端

- **1052 次调用** `count = 3` 或 `4` → `jle` **不成立** → 按判定链**必须**写 2；
- **只有 96 次** `count = -2` → `jle` 成立 → 走 `0xBBA5C3` 推进索引。

**而实测 `idx` 在 12 秒内只推进了……**按 0.52 秒一次计算约 23 次，
远少于 96——但更关键的是：**1052 次 `count>0` 的调用竟然没有一次把状态变成 2。**

#### 至此所有解释路径都已封闭

| 可能 | 状态 |
|---|---|
| count 从来不是正数 | **否**——91.4% 是 3 |
| count 为正但不写 2 | 说明 `jle` 仍跳——但 3 > 0，不可能 |
| 写 2 后立即被覆盖 | `Init` 只 1 次（§12.131），五个中间调用安全（§12.124/125） |
| `Add` 调用频率低 | **否**——27 次/秒（§12.137） |
| 写 2 在 SEH 内被破坏 | 写 2 本身是 `mov [ebx+0x120],2`，不涉及控制流 |
| 状态读的不是同一对象 | `ebx == obj1`（§12.128） |

#### 一个此前从未考虑的可能：观测本身改变了行为

`0xBBA43A` 的钩子用 cave 替换了 `mov edi, dword ptr [ebp+0x94]`，并在 cave 里
`pushad` / 读 `[ebp+0x94]` / `popad` / 重放原指令。

**关键问题：`pushad` 会压入 32 字节到栈上，而 `[ebp+0x94]` 是一个栈地址的引用。
若 cave 执行期间 `esp` 的变化恰好使 `[ebp+0x94]` 指向位置的内容被覆盖，
采样到的值就不是原来的值。**

**但 `[ebp+0x94]` 是相对于 `ebp` 寻址的，`ebp` 在 `pushad`/`popad` 之间不变，
所以读到的是同一块内存。** 这个可能站不住。

**更可能的是**：cave 中 `pushad` 写入的栈区域**恰好落在 `[ebp+0x94]` 附近**
（pushad 压 32 字节，而 `[ebp+0x94]` 在 `ebp` 之上 0x94 处——
**若 `esp` 与 `ebp` 的关系使得 `pushad` 的写入区间覆盖到 `ebp+0x94`**，
那 sampling 时的 `pushad` 就会**污染**被采样的槽位本身）。

**这是唯一还能解释"91.4% 的正数"与"从不写 2"并存的可能性：
采样到这个正数的是 pushad 残留，而不是真正的参数。**

#### 下一步：换一个不写栈的采样方式

不用 `pushad`，改用**只保存必要寄存器**的最小 cave：

```
pushfd
push eax
mov eax, [ebp+0x94]
mov [slot], eax
pop eax
popfd
<重放原指令>
```

**`push eax` 只压 4 字节，不会覆盖 0x94 深的栈区域。**

若用这种方式采样到的 `[0x94]` 变成 `-2` 或别的值，**就证明此前的 91.4% 是
`pushad` 污染造成的假象**，整条矛盾立刻消解。

**这是目前最值得做的一次验证。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.138"),
                         ("HANDOFF-CURRENT.md", "### 16.26")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.138", "### 16.26")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
