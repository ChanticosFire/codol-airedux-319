"""Record round 26: full request sequence achieved, reply shapes still wrong."""
from pathlib import Path

TEXT = """
### 12.44 请求序列已完整；剩余问题是应答内容而非触发条件（2026-10-23 06:0x）

#### 实验 E 结果

15 补丁 + 三处写入 + `LSG_T9_MODE=error14` + `LSG_UNIMPL_MODE=error14`：

```
19:04:59 client_frame payload_len=8    task_request service=71 task=9
19:04:59 client_frame payload_len=275  task_request service=71 task=7
19:04:59 client_frame payload_len=141  task_request service=71 task=3
19:04:59 client_frame payload_len=389  task_request service=71 task=7    <- 重试
19:04:59 client_frame payload_len=8    task_request service=71 task=9    <- 重试
counts: client_frame=5, task_request=5
```

**客户端在 `task7` 上重试**（275 B 与 389 B 两次），说明它没有接受
`error=14` 的应答，改换了请求内容再来一次。

#### 与 M3 的差异对照

| 项目 | M3 达成大厅那次 | 本次 |
|---|---|---|
| `task4` | 83 B，被应答 | 同 |
| `task9` | 8 B，`error=14` | 8 B，`error=14` |
| `task3` | **142 B**，`error=14` | **141 B**，`error=14` |
| `task7` | **未出现** | 275 B / 389 B，重试两次 |
| 崩溃时机 | 无（54 秒后正常结束） | 写入后约 10 秒崩溃 |

**`task3` 的请求长度差 1 字节**（142 vs 141），且 `task7` 在 M3 里根本没出现。
这两点说明客户端的**内部状态与我们不同**，因此发出的请求也不同——它并不是
在"走同一条路"，而是在一个略有偏差的状态下探索。

#### 已达成的确定性成果

| 变量 | 值 | 作用 |
|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1: 0 → 1`（实验 A 单独验证） |
| `[0xE59D20]` | 3 | 稳定中间态，不回滚（实验 B） |
| `[lobby+0x1F4]` | 2 | **释放客户端请求**（实验 C/D/E） |

**这三处写入是"客户端愿意继续通信"的充分条件**，26 轮来第一次稳定复现
`task3`/`task7`/`task9` 的请求链。

#### 剩余问题

客户端在收到"未实现"应答后仍会崩溃。可能原因：

1. `task3`(141 B) 与 `task7`(389 B) 的**请求语义**需要真实应答，`error=14`
   只能让它重试一次，之后仍失败；
2. `FE_state=3` 缺少配套字段，客户端在处理应答时解引用到无效内容；
3. `[lobby+0x1F4]=2` 让 pump 进入"已完成"分支，而我们没有提供它期望的后续数据。

#### 新增环境开关

`server319/lsg_derived.py` 现有三个应答形状开关，便于后续对照：

| 环境变量 | 取值 | 作用 |
|---|---|---|
| `LSG_T4_MODE` | `zero` / `entry` | `svc71/task4` 的应答形状 |
| `LSG_T9_MODE` | `error14` / `entry` | `svc71/task9` 的应答形状 |
| `LSG_UNIMPL_MODE` | `error14` / `empty` | `svc71/task3`、`task7` 等未实现服务的应答 |

三者默认均为 M3 基线（`error14`/`error14`），便于复现。

#### 下一步

1. 解码 `task3`（141 B）与 `task7`（389 B）的请求内容——它们都是**加密**的，
   但长度与 M3 的 142 B 只差 1 字节，可用同一套 `parse_client_frame85` 解出
   TLVs，从而知道客户端在要什么；
2. 按解码结果构造真实应答，替换 `error=14`；
3. 观察是否还会崩溃，以及 `ui_state` 能否从 9 变为大厅对应的值。

第 1 条是关键：只要知道客户端在 `task7` 里问什么，就能给出它接受的数据，
而不是继续用错误帧试探。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.44"),
                         ("HANDOFF-CURRENT.md", "### 15.32")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.44", "### 15.32")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
