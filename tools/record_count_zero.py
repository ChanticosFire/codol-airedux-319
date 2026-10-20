"""Record round 58: count is zero, so Add never appends; index growth has another source."""
from pathlib import Path

TEXT = """
### 12.72 ★★★ `count` 恒为 0，`Add` 从未真正追加过任何条目（2026-10-23 21:4x）

#### 决定性实验

先按第 52 轮实验二的条件设置（`cap = 200`、`idx = 0`、`status = 1`），
然后在 `Add` 的两个分支上各装一个计数器：

```
body 分支（0xBBA4A3，进入主体后）   total after 8s = 0
skip 分支（0xBBA5C3，count<=0 出口） calls = 1, 2, ...
                                                   随后 CLIENT GONE（崩溃）
```

**主体分支 0 次，跳过分支有命中。**

#### 结论：`count` 恒为 0

```asm
0xBBA43A  mov edi, [ebp + 0x94]     ; count
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3              ; ★ count <= 0 -> 跳到 0xBBA5C3
```

每帧都从这里跳走，所以 `0xBBA4A1`（`rep movsd`）、`0xBC1980`（条目数）、
`0xBBA569`（写 2）**全部从未执行**。

**`Add` 一次都没有真正追加过条目。**

#### 这推翻了 §12.66 关于索引增长的归因

第 52 轮观察到"容量抬到 200 后索引从 0 涨到 200，速度约 2 条/秒"，
当时归因于 `Add` 在追加。**现在证明 `Add` 的主体从未执行**，
所以索引增长必然来自**别处**。

候选：

1. `0xBAE4FE`–`0xBAE518` 那段（读 `[ebx+0x4d6c]`、`imul 0x88`、`rep movsd`）；
2. `0xBBA3F0` 之前的代码；
3. `0xBAE5F3 inc dword [ebx+0x4d6c]`（但那是数组游标 `0x4D6C`，不是 obj1 的 `0x130`）。

**注意**：实验二的观测是"`obj1` 的 `+0x130` 在涨"。而 `+0x130` 的写入点只有
`0xBB76BB`（构造，写 0）、`0xBBA3A6`（初始化，写 0）和 `0xBBA5F6`（追加路径，
`mov [ebx+0x130], edx`）。**`0xBBA5F6` 在 `0xBBA5C3` 之前**，
所以 count<=0 分支**不会**执行它。

那 `+0x130` 是怎么涨的？两种可能：

- **我上次观测的是另一个字段**（第 52 轮脚本读的是 `o1+0x130`）；
- **有第四个写入点**没被扫到（例如 `add [ebx+0x130], r` 之类）

第 51 轮的扫描覆盖了 `89 /r`、`C7 /r`、`FF /0` 三种形式，但没有覆盖
`01 /r`（`add [mem], reg`）。**这是一个可见的漏洞**。

#### 结构性结论

不管索引怎么涨，**当前最确定的事实**是：

> **`Add` 每次调用都收到 `count = 0`，因此从不追加；
> 它每帧直接跳到 `0xBBA5C3`，在那里由容量判断决定是否写 3。**

而 `0xBBA5C3` 之后流到 `0xBBA5EC`（读容量）→ `0xBBA61A cmp [ebx+0x130], eax` →
`jb 0xBBA635`（未满则正常返回）或写 3。

**实验二里容量 200、索引 0，`jb` 应当成立，状态应保持 1 —— 与观测一致。**
而原始状态（容量 5、索引 5）时 `jb` 不成立，写 3 —— 也与观测一致。

**所以整条路径第一次完全自洽了**：
`Add` 因 count=0 什么都不做，只在"索引已满"时把状态写成 3。

#### 下一步

1. **补扫 `01 /r`（`add [mem], reg`）与 `83 /0`（`add [mem], imm8`）**形式，
   找 `+0x130` 的第四个写入点；
2. **追问 `count = 0` 的来源**：那个 136 字节结构的 `+0x84` 字段为什么是 0。
   按 §12.71，`+0x84` 正是 `0xB75470` 用来比较的字段，说明它是"条目类型/数量"。
   如果数组条目里这一位一直是 0，那么 pump 每帧构造的请求就是"追加 0 条"，
   整个追加流程形同虚设。
3. 若 `+0x84` 应由服务端数据填充，则需要检查 `svc71/task4` 应答里是否少了这个字段。

第 2 条最可能是真正的根因。

#### 附带记录

两个 hook 同时安装后客户端崩溃（`CLIENT GONE`）。可能是连续两次
`VirtualAllocEx` + 改代码造成的，也可能只是这次运气不好。后续若需多点观测，
应改为"一次安装、共用一块 cave"。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.72"),
                         ("HANDOFF-CURRENT.md", "### 15.60")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.72", "### 15.60")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
