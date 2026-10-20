"""Record round 39: six patches crash the client, and thread sampling is abandoned."""
from pathlib import Path

TEXT = """
### 12.57 六补丁组合导致崩溃；线程采样路线放弃（2026-10-23 12:4x）

#### 实验：M3 的六补丁 + 写 `[D+0xC]=1`

计划是验证「M3 只用 6 个补丁就进了大厅，也许我们的 15 个里那 9 处 pump 补丁
反而破坏了路径」。做法：只打 M3 记录的 6 处，`dw=5` 后写 `[D+0xC]=1`，
不强推 G1。

结果：

```
wrote patch.json
patch exit=0
TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'   <- [0x3306D60] 为 0
t=10s: EXITED  …… t=120s: EXITED
s1: no visible CODO window

19:47:53 task_request service=71 task=4
19:48:17 raw_session_end ConnectionResetError:[WinError 10054]
```

**客户端在 `task4` 之后约 24 秒崩溃**，`[0x3306D60]` 读到 0（连对象都没建立）。

**结论：9 处 pump 补丁是必需的**，缺了它们客户端撑不到 `dw=5`。
15 补丁的组合应当保留，§12.37 关于"可能那 9 处有害"的猜测可以排除。

#### 线程上下文采样：放弃

`SuspendThread` + `Wow64GetThreadContext` 仍返回 0/59：

```
pid=34344 threads=59 CONTEXT=716B
SELF-CHECK FAILED: no thread produced a sane Eip
```

三条路都试过了（完整 CONTEXT 结构、Wow64 API、SuspendThread），全部失败。
32 位目标 + 64 位宿主的组合比预期难处理。

**按"同一阻断连续 3 轮无进展则换方向"的规则**（第 37、38、39 轮都消耗在这里），
**放弃线程采样**。

好消息是它并非必要：§12.55 已确认下列事实全部来自**静态反汇编 + 直接读内存**，
不依赖采样工具：

| 事实 | 值 |
|---|---|
| `[lobby+0x1F4]` | 恒为 1（921 次采样，读内存） |
| `obj2+0x1A0` | 5（失败码） |
| `obj1+0x120` | 3 |
| `0xBBADCD` 写 5 | `0xBBAD40` 失败分支 |
| 容器要求 {type 0x14, subtype 2, key 0, 1288 B} | 反汇编 |
| 长度检查 `jne`（严格相等） | 反汇编 |

唯一失去的是"pump 执行频率"这一项，而它对"进大厅"不是必要条件。

#### 近三轮的净状态

| 轮次 | 投入 | 产出 |
|---|---|---|
| 37 | 采样工具（204 字节 CONTEXT） | 工具 bug，结论作废 |
| 38 | 采样工具（位数不匹配） | 工具 bug，结论作废 |
| 39 | SuspendThread + 六补丁实验 | 采样放弃；**六补丁崩溃**（有价值） |

三轮只有一个确定结论（九补丁必需），其余是自我纠错。这是效率很低的一段。

#### 下一步：转向可独立验证的产出

按规则换方向。候选：

1. **`server319` 服务能力测试扩充**——把 `svc71/task4`、`task9` 的应答与
   `test_frames.py` 的帧契约连起来，形成回归保护；
2. **`LONG-RUN-GOAL.md` / `MILESTONES.md` 重写 M4 判据**——把「必须先人工完成
   代号」作为显式前提写进去，并给出"若无法人工介入"的替代验收标准；
3. **`SOLUTION-100-111.md` 增补**——把第 12.36–12.57 节的机制发现（`0xBAD800`
   状态机全图、容器查找契约、`[D+0xC]` 与 FE 梯的关系）整理成可供他人复用的
   技术说明。

第 2 条最必要——当前 M4 判据与实际可达性脱节，文档却仍按"可自动完成"呈现。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.57"),
                         ("HANDOFF-CURRENT.md", "### 15.45")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.57", "### 15.45")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
