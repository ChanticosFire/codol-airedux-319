"""Record round 197: final verification and a summary of what this series produced."""
from pathlib import Path

TEXT = """
### 12.207 最终验证与系列小结（第 128–196 轮）（2026-10-26 23:5x）

#### 验证结果

```
契约测试   21 项 OK
帧测试     17 项 OK
LSG 派生    2 项 OK
合计       40 项全绿

git status 干净，全部提交已推送
```

文档规模（行数）：

```
PROJECT_STATUS.md         10737
HANDOFF-CURRENT.md        10420
PUMP-STATE-MACHINE.md       255
MILESTONES.md                19
SOLUTION-100-111.md         216
VERSION-SWITCH.md            75
```

#### 本系列（第 128–196 轮）的实质性产出

**1. 找到了整条链的终点结构**

从"状态码卡在 1"一路追到"pump 每帧循环"：

```
收包（vt+0x1C，0xC73FB0）-> 字节数 esi
  -> 组装 136 字节记录 -> Add(0xBBA3F0)
  -> 读状态 -> 三道守卫 -> 通过才写 1F4 = 2
```

**2. 定位了 `Add` 的两个过滤分支并实证**

`0xBBA465`（条目重复）与 `0xBBA483`（追加成功）——各打 6 字节 `nop` 后，
状态从 1 稳定变成 2（1883 次采样）。**这是第 60 轮以来第一次让状态越过 1。**

**3. 解出了类型 `0x15` 消息的格式与完整通路**

格式：`[类型 1B] [word 2B，须为 1 或 2] [dword 4B] [word 2B]`（9 字节最小）。
通路：`0xBAE2C2 → 0xBBADE0 → 0xBBAAF0`，**完全在 pump 内部**，
要求长度 > 0、解析成功、类型 == 0x15。

**4. 完整反汇编了发送链并核对了栈平衡**

`0xBBA760 → 0xC73F30 → 0xBB1420(sendto)`，
148 字节的栈清理与 5 个 push/分配完全吻合。

**5. 修正了三处此前的错误结论**

| 错误结论 | 修正 | 原因 |
|---|---|---|
| "socket 从未创建" | **socket 是 11624，有效** | 漏了 `[serverlist]` 一级间接 |
| "`0x853A10` 是按类型查表" | **是恒等函数** | 直接反汇编可见 |
| "服务端返回 ≥136 字节即可" | **通道不对，发多少都没用** | 两次实验均无变化 |

**6. 六份文档完成收束**

每份都能独立回答"卡在哪、为什么、下一步做什么"，
且互相指向、口径一致。

#### 仍未解决的问题

**`vt+0x1C` 的收包读不到我们发的任何字节。**

已排除：回探测包源 `22011`、向全部 6 个 UDP 端口发、在 3074 上发大记录。

未验证的三个方向：
1. 收包依赖一个尚未建立的连接，未连接则返回 0；
2. 业务数据走 **TCP 4174（LSG 通道）**；
3. 收包前需要某个永远不满足的前置状态。

**建议的第一个动作**：在 `0xC73FB0` 入口挂哨兵——确认是否被调用、
参数是什么、是否首步即返回 0。**这能区分"没收到"与"收到了但不合格"。**

#### 对 M4 的诚实评估

**M4 未达成。** 五项判据都要求客户端处在真实大厅，
而它停在代号页（或模糊过渡画面）。

**但项目状态从"不知道为什么卡住"变成了"明确知道卡在哪一环、
以及该用什么方法验证"。** 这是可以交接的进展。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.207"),
                         ("HANDOFF-CURRENT.md", "### 16.95")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.207", "### 16.95")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
