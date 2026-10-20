"""Record round 137: a second write of 2 to the 1F4 gate that round 70 missed."""
from pathlib import Path

TEXT = """
### 12.152 ★★★ `1F4` 在 pump 区有 6 个引用，其中 `0xBAE589` 是此前漏掉的第二个"写 2"（2026-10-25 16:2x）

#### 新增工具

`tools/find_offset.py`：把结构偏移当作小端 disp32 在指定区间内搜索，并打印命中点前后的字节上下文。
`find_refs.py` 只能搜**绝对地址**，对"结构偏移"无能为力——而 `1F4` 是 `lobby` 的相对偏移，
必须用这种方式找。

#### 全镜像搜索与收窄

在 `0x400000`–`0xDD0000` 内搜 `F4 01 00 00` 得 **337 个命中**——绝大多数是立即数巧合
（`0x1F4` = 500，常作为循环上限、缓冲区大小等出现）。

收窄到 pump 所在的 `0xBAE000`–`0xBAF000`，只剩 **6 个**：

```
0xBAE1AE  C7 83 F4 01 00 00 02 00 00 00   mov dword [ebx+0x1F4], 2   ← 第 70 轮已知
0xBAE20A  83 BB F4 01 00 00 01            cmp dword [ebx+0x1F4], 1   ← pump 的入口检查
0xBAE589  C7 83 F4 01 00 00 02 00 00 00   mov dword [ebx+0x1F4], 2   ← ★ 第二个"写 2"
0xBAE750  C7 83 F4 01 00 00 01 00 00 00   mov dword [ebx+0x1F4], 1   ← 复位
0xBAE768  C7 83 F4 01 00 00 01 00 00 00   mov dword [ebx+0x1F4], 1   ← 复位
0xBAE7AC  C7 83 F4 01 00 00 01 00 00 00   mov dword [ebx+0x1F4], 1   ← 复位
```

#### 这推翻了"只有一条路能推进 FE 梯"的假设

§12.70 只记录了 `0xBAE1AC` 一处写 2，并据此认为 FE 梯的推进必然依赖
`[obj1+0x120] == 2`。

**现在发现 `0xBAE589` 也写 2，而且位于完全不同的位置**（`0xBAE1AE` 与 `0xBAE589`
相差 0x3DB，属于 pump 内不同的代码段）。

**它可能有一条完全不同的触发条件——甚至可能不检查 `obj1` 的状态。**

#### 三个"写 1"是复位点

`0xBAE750`、`0xBAE768`、`0xBAE7AC` 三处都写 1——**它们把 `1F4` 复位**，
解释了为什么观测到的 `1F4` 绝大多数时候是 1：

- 某一帧被写成 2 → 短暂生效 → 下一帧某处复位为 1；
- 若对应的处理没有及时完成，就表现为"永远是 1"。

#### 下一步

**反汇编 `0xBAE540`–`0xBAE5B0`**，弄清 `0xBAE589` 的前置条件：

- 若它的条件里**不**包含 `[obj1+0x120] == 2`，那这就是一条绕过整条卡点的路径；
- 若它的条件同样要求状态 2，那它只是另一条同样被卡住的路径。

**同时反汇编 `0xBAE730`–`0xBAE7C0`**，看三个复位点的条件——
理解"谁在把 1F4 打回 1"，有助于判断 2 能维持多久。

**这是本轮之后最有价值的两次反汇编。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.152"),
                         ("HANDOFF-CURRENT.md", "### 16.40")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.152", "### 16.40")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
