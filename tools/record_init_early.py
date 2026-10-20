"""Record round 111: Init runs at dw==2, during the same phase as the write of 2."""
from pathlib import Path

TEXT = """
### 12.126 `Init` 在 `dw==2` 时运行——与写 2 处于同一阶段（2026-10-25 03:1x）

#### 关键观测

在 `0xBBA370`（`Init`）装计数器，采样窗口从进程出现开始、覆盖整个启动过程：

```
[init] image ready after 2.73s
[init] n=0  eax=0x00000000  dw=0  success=0
[init] n=1  eax=0x37F15FA0  dw=2  success=1     ← ★ Init 在 dw=2 时运行
[init] unreadable - process gone?
```

**`Init` 确实在 `dw == 2` 时被调用**，而这正是 §12.108 观察到"写 2 执行"的同一阶段。

**这与 §12.94 并不矛盾**：第 94 轮只测了 `dw=5` 之后的 15 秒，看到 0 次；
本轮覆盖了启动早期，看到 1 次。**两者共同说明 `Init` 只在启动阶段运行，稳态不运行。**

#### 但只抓到 1 次，且客户端随即退出

`n=1` 之后立刻 `unreadable`——客户端在 1 次命中后崩溃了。

**原因可能是 `0xBBA370` 的 hook 干扰**：虽然 `Init` 本身不在 SEH 保护区内
（SEH 帧要到 `0xBBA3F5` 才建立，那属于 `Add`），但 `Init` 内部会调用
`0xBBA3D2`（写 1）等代码，hook 的 cave 落在模块外的内存页，
在某些时机仍可能出问题。

**需要重试才能判断这是偶发还是必然。**

#### 这条线索的价值

若 `Init` 在启动阶段被调用**多次**，就能解释全部矛盾：

```
dw=2   Init #1  -> 状态 = 1，索引 = 0
dw=2   Add(count>0) -> 写 2 -> jne 返回 -> 状态 = 2
dw=?   Init #2  -> 状态 = 1（把 2 覆盖掉）
dw=5   空闲帧 -> 索引推进到满 -> 写 3
```

**即：`Init` 会把 `Add` 刚写好的 2 覆盖回 1，使得 `Add` 的成功永远无法保持。**

而 `Add` 的入口检查 `cmp [ebx+0x120],1` 在状态为 1 时**不会**短路，
于是后续空闲帧继续走 `count<=0` 分支推进索引、直到写 3 锁定。

#### 下一步：重试并延长窗口

1. 用同样锚点重跑 2–3 次，看 `Init` 的命中次数是否稳定；
2. 若客户端总是在 1 次命中后退出，说明该 hook 不稳定，改用
   **轮询 `[obj1+0x120]` 的高频快照**代替——`Init` 会把状态设为 1，
   若能看到"状态从 2 变回 1"，同样能证实覆盖；
3. 更直接的做法：**轮询 `[obj1+0x120]` 以 20ms 间隔，从进程出现一直采到 `dw=5`**，
   记录状态的全部跳变序列。若序列中出现 `1 -> 2 -> 1 -> ... -> 3`，假设即成立。

**第 3 条最安全且信息量最大**，因为它不改变任何代码，且能直接看到状态的完整轨迹。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.126"),
                         ("HANDOFF-CURRENT.md", "### 16.14")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.126", "### 16.14")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
