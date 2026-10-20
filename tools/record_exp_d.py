"""Record experiment D: task3/7/9 all fire; only the reply shapes differ from M3."""
from pathlib import Path

TEXT = """
### 12.43 实验 D：`svc71/task3`、`task7`、`task9` 全部触发（2026-10-23 05:3x）

#### 客户端发出了完整的请求序列

配置：15 补丁 + 三处写入（`[D+0xC]=1`、`FE_state=3`、`[lobby+0x1F4]=2`），
`LSG_T9_MODE=error14`。

```
18:58  client_frame payload_len=8     task_request service=71 task=9
19:01  client_frame payload_len=141   task_request service=71 task=3
19:01  client_frame payload_len=389   task_request service=71 task=7
19:01  client_frame payload_len=8     task_request service=71 task=9
counts: client_frame=5, task_request=5
```

**这是 26 轮来第一次看到 `task3` 和 `task7`**——M3 那次的 `lsg.jsonl` 里
也只有 `task4 / task9 / task3`，而本次多出了 `task7`。

#### 但与 M3 有一处关键差异

| 项目 | M3 那次 | 本次 |
|---|---|---|
| `task9` 应答 | `terminal_task_reply error=14`（14 字节） | 同（`LSG_T9_MODE=error14`） |
| `task3` 应答 | `terminal_task_reply error=14` | `candidate_empty_task_reply`（空成功） |
| `task7` 应答 | 未出现 | `candidate_empty_task_reply` |

即：我们把 `task3`/`task7` 应答成了「空成功」，而 M3 应答的是「未实现错误」。
客户端随后仍然崩溃（写入后约 10 秒）。

#### 这提示下一步非常明确

`lsg_derived.py` 里 `task3`/`task7` 走的是 `candidate_empty_success_reply`
分支。**把这类"未实现"的应答统一改成 `terminal_unavailable_reply`（error=14）**，
与 M3 完全一致，再复跑：

- 若客户端不再崩溃 → 说明"空成功"帧的格式是崩溃原因，而"错误帧"是安全的；
- 若仍在 `task9` 后崩溃 → 说明问题不在应答形状，而在别处（例如 `FE_state=3`
  缺少配套字段）。

无论如何，这次实验已经把"客户端能否主动发请求"这件事彻底解决：
**三处写入是充分条件**。

#### 三处写入的作用已完全确定

| 变量 | 值 | 作用 | 单独验证 |
|---|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1: 0 → 1` | 实验 A |
| `[0xE59D20]` | 3 | 稳定中间态，不回滚 | 实验 B |
| `[lobby+0x1F4]` | 2 | **释放客户端请求**（task3/7/9） | 实验 C/D |

#### 待办

1. 把 `task3`/`task7`/`task11`/`task13` 等未实现分支统一改为 `error=14`；
2. 复跑实验 D，确认是否还崩溃；
3. 若不崩，观察客户端是否最终渲染出房间列表（M4.2 的第一个判据）。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.43"),
                         ("HANDOFF-CURRENT.md", "### 15.31")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.43", "### 15.31")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
