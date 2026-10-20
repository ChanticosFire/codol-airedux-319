"""Record experiment C: [lobby+0x1F4]=2 is what finally triggers svc71/task9."""
from pathlib import Path

TEXT = """
### 12.42 ★★★ 实验 C：`[lobby+0x1F4]=2` 是触发 `svc71/task9` 的开关（2026-10-23 05:1x）

#### 这是 25 轮来第一次让客户端主动发出 `svc71/task9`

配置：15 处补丁 + 写 `[D+0xC]=1` + 写 `FE_state=3` + 写 `[lobby+0x1F4]=2`。

LSG 记录：

```
18:58:58 client_frame_verified counter=5 inner=0x86 payload_len=8
18:58:58 task_request service=71 task=9 bytes=8          ★ 第一次自发出现
18:58:58 candidate_task_reply svc71/task9 bdMatchMaking entry 127.0.0.1:8466
18:58:58 raw_session_end EOFError:peer_closed
```

`counts` 从之前的 `client_frame: 1` 变成 **`client_frame: 5`**、`task_request: 5`。

**对比**（同一 15 补丁集、同样的 auth/LSG 服务）：

| 配置 | client_frame 数 | 是否发 71/9 |
|---|---|---|
| 只强推 G1=2（§12.38 基线） | 1 | 否（等 90 s） |
| 写 `[D+0xC]=1`（实验 A） | 1 | 否 |
| 写 `[D+0xC]=1` + `FE_state=3`（实验 B） | 1 | 否 |
| **再加 `[lobby+0x1F4]=2`（实验 C）** | **5** | **是** |

**结论：`[lobby+0x1F4] == 2` 才是客户端继续发请求的必要条件。**
之前所有"等 39 秒/90 秒仍无 task9"的阴性结果，根因就是这一位一直是 1。

#### 但客户端随后崩溃

写入后约 10 秒进程退出（`no visible CODO window`）。最可能的原因在
`svc71/task9` 的应答：

- 我们回的是 **114 字节的 bdMatchMaking entry**（`candidate_svc71_task9_reply`）；
- **M3 达成大厅那次回的是 `terminal_task_reply error=14`（14 字节）**，
  即"未实现"错误帧，而客户端照样继续往下走（§12.37 已记录它不要求应答正确）。

**也就是说：给出一个"正确的"条目反而让客户端崩溃，给出错误帧却能继续。**
这暗示 114 字节条目的字段格式与客户端期望不符，客户端解析到非法值后崩溃。

#### 下一步（明确且成本很低）

1. 把 `svc71/task9` 的应答改回 **`terminal_unavailable_reply`（error=14）**，
   复跑实验 C。若客户端不再崩溃并继续发 `71/3`，则完全复现 M3 的行为；
2. 之后再逐个字段校准 114 字节条目，使客户端能真正消费服务器条目。

#### 环境变量开关

`lsg_derived.py` 已有 `LSG_T4_MODE`（`zero`/`entry`）控制 `71/4` 的应答形状。
本轮应在同一处增加 `LSG_T9_MODE`（`entry`/`error14`），默认取 `error14`
以复现 M3 基线。

#### 三个中间态的作用（汇总）

| 变量 | 写入值 | 效果 |
|---|---|---|
| `[D+0xC]` | 1 | FE 梯 `G1` 从 0 前进到 1（实验 A 单独验证） |
| `[0xE59D20]` | 3 | 稳定保持，不被回滚；为 `3→4` 转换做准备 |
| `[lobby+0x1F4]` | 2 | **触发客户端继续发请求**（本次突破） |

三者缺一不可：只写前两个时 `G1=1` 且无 `71/9`；加上第三个才出现 `71/9`。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.42"),
                         ("HANDOFF-CURRENT.md", "### 15.30")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.42", "### 15.30")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
