"""Record round 113: the store of 2 targets obj1 itself, so obj1's status really is written."""
from pathlib import Path

TEXT = """
### 12.128 ★★★ 写 2 确实作用在 `obj1` 上（`ebx == obj1`）（2026-10-25 04:2x）

#### 采样

在 `0xBBA5AB`（写 2 之后的第一条指令）采样 `ebx`，与当时的 `obj1` 指针
（`[[0xE85C68]+0x1F8]`）及 `dw` 一起记录：

```
[ebxobj] n=0  ebx=0x00000000  obj1=0x00000000  dw=0
[ebxobj] n=1  ebx=0x37DC89A0  obj1=0x37DC89A0  dw=2     ← ★ 完全相等
[ebxobj] unreadable - process gone?
```

**`ebx` 与 `obj1` 指针完全相同，且此时 `dw = 2`。**

#### 这推翻了一个假设，同时确认了另一件事

**推翻**：§12.127 提出的"写 2 可能作用在临时对象上、与 `obj1` 无关"——不成立。
`obj1` 在 `dw=2` 时**已经存在**，写 2 直接改的正是它的 `[+0x120]`。

**确认**：`obj1[0x120]` 确实被写成了 2。

**但最终它是 3。**

#### 于是覆盖链只剩一种可行形式

`Add` 内部从写 2 到 `cmp` 之间（§12.124/§12.125 已证明五个 `call` 全部安全），
`jne` 应当跳走、状态保持 2。**但状态没保持。**

**唯一能改它的只有 `0xBBA3D2`（写 1），而它属于 `Init`（`0xBBA370`）。**

§12.126 已证实 **`Init` 在 `dw=2` 时运行**，与写 2 处于同一阶段。

**所以完整时序是**：

```
dw=2   Add(count>0)  -> 写 obj1[0x120] = 2 -> jne 跳走 -> Add 返回，状态 = 2
dw=2   Init          -> 写 obj1[0x120] = 1，并清零索引 0x130
dw=2-5 空闲帧         -> Add 入口 cmp [0x120],1 成立（不短路）-> 索引推进
dw=5+  索引满          -> 写 3
```

**`Init` 把 `Add` 刚写好的 2 覆盖回 1**，使得 `Add` 的成功永远无法保持。

#### 这与全部观测吻合

| 观测 | 解释 |
|---|---|
| 写 2 执行过（§12.108） | ✔ `0xBBA5AB` 命中 |
| 写 2 作用在 obj1（本轮） | ✔ `ebx == obj1` |
| 状态从未是 2（§12.127） | ✔ 被 `Init` 立即覆盖 |
| `success` 与 `idx` 同步增长（§12.127） | ✔ 状态回到 1 后走 `count<=0` 分支 |
| `Init` 在 `dw=2` 运行（§12.126） | ✔ 与写 2 同时段 |
| `Init` 稳态 0 次（§12.94） | ✔ 只在启动阶段 |

#### 下一步：验证"`Init` 在写 2 之后运行"

需要确定两者在 `dw=2` 阶段内的**先后顺序**。做法：

1. **同时挂两个计数器**——`0xBBA569`（写 2）与 `0xBBA370`（`Init`）——
   记录各自的时间戳，比较先后。但两个 hook 同时装曾导致崩溃（早期教训），
   改为**分别记录首次命中时刻**；
2. 更稳妥：**轮询 `obj1[0x120]` 的 20ms 轨迹**，从 `obj1` 出现（`dw=2`）开始。
   若看到 `1 -> 2 -> 1` 的序列，直接证实覆盖。§12.127 的轨迹从 `t=17.59`
   开始是 `status=1`，但**采样间隔 20ms 可能错过 `2` 的短暂存在**；
3. **最直接**：在 `0xBBA3D2`（写 1，6 字节 `C7 83 20 01 00 00 01`）装计数器，
   看它在 `dw=2` 阶段是否执行、执行几次。

**第 3 条成本最低且直接针对"谁把 2 改回 1"这个具体问题**，下轮先做。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.128"),
                         ("HANDOFF-CURRENT.md", "### 16.16")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.128", "### 16.16")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
