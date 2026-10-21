"""Record round 199: closing state for the 200-round goal."""
from pathlib import Path

TEXT = """
### 12.209 收束：200 轮长程目标结束时的状态（2026-10-27 01:0x）

#### 一句话

**M3 已完成（大厅 UI 渲染）。M4 未达成。** 客户端停在「请先取一个代号」页面
（或其后的一片模糊过渡画面），五项 M4 判据全部无法开始。

#### 已确切知道的事

| 项 | 内容 | 证据 |
|---|---|---|
| 前端梯的开关 | `[lobby+0x1F4]`，1 = 等待，2 = 推进；且是**帧内脉冲**而非持久状态 | §12.157、§12.168 |
| 每帧循环 | 收包（`vt+0x1C` = `0xC73FB0`，用 `[this+4]` 作 socket）→ 组装 136 字节记录 → `Add` → 读状态 → 三道守卫 → 写 `1F4` | §12.203、§12.208 |
| `Add` 的两个过滤 | `0xBBA465` / `0xBBA483`，各打 6 字节 `nop` 后状态稳定变 2 | §12.163、§12.164 |
| 状态码语义 | 1 等待 / 2 Add 成功 / 3 索引满 / 4 就绪 / 5 发送失败 | §12.152–§12.176 |
| 推广到 4 的唯一通路 | `0xBAE2C2 → 0xBBADE0 → 0xBBAAF0`，要求类型 `0x15` 消息（9 字节最小） | §12.202、§12.176 |
| 发送链 | `0xBBA760 → 0xC73F30 → 0xBB1420(sendto)`，148 字节栈清理已核准 | §12.200 |
| 网络拓扑 | 6 个 UDP 端点（探测只用 `22011`），1 条 TCP `127.0.0.1:4351 → 4174`（LSG） | §12.205 |

#### 未解决的那一个问题

**`0xC73FB0` 的收包读不到我们发的任何字节。**

已排除：
- 回探测包源 `22011`（§12.204）
- 向全部 6 个 UDP 端口从 2 个源端口发 160 字节（§12.206）
- 在 3074 上发 9 字节类型 `0x15` 消息（§12.182）

剩余三种可能（未验证）：
1. 发送侧目标地址错——但探测包能到服务端，说明发送方向是通的；
2. 接收 socket 已关闭或绑在我们触达不到的地址；
3. **数据到了但被 `0xC73FB0` 内部丢弃**（长度/来源/协议头校验失败后返回 0）。

**第 3 条最可疑**，验证方法：在 `0xC73FB0` 入口读 `[esi+4]` 与参数，
在其**返回点**读 `eax`（探针须在该函数的 SEH 帧之外）。

#### 下一步（按优先级）

1. **验证第 3 条**——用哨兵法确认 `0xC73FB0` 的返回值与参数；
2. 若确认从未收到数据 → 转向 **TCP 4174（LSG 通道）**，
   因为 UDP 侧 6 个端点已被全部排除；
3. 若收到但被丢弃 → 反汇编 `0xC73FB0` 的前 0x60 字节之后的校验逻辑。

#### 工具清单（可直接复用）

```
tools/run_verified.ps1     带自检的启动脚本
tools/watch_statecode.py   等客户端可读后轮询状态码（必须用，不能立即轮询）
tools/probe_reg.py         hook + 寄存器/内存采样
tools/sentinel_*.py        只改立即数 + 轮询（最可靠）
tools/branch_map.py        列出区间内所有跳转及目标（必须全镜像范围）
tools/find_offset.py       搜结构偏移的 disp32
tools/poke_ports.py        向任意进程的全部 UDP 端口发包
tools/dump_code.py         反汇编（起点必须是已知指令边界）
```

#### 代码库状态

**40 项单元测试全绿**（21 契约 + 17 帧 + 2 LSG 派生）。
**git 干净，全部提交已推送至 `origin/main`。**

#### 对目标的诚实结论

**M4 未达成，且不是差一点——它卡在一个尚未定位的通道问题上。**
定位通道需要"假设 → 实现 → 实测"的完整循环，而本轮系列已用尽。

**但项目状态从"不知道为什么卡住"变成了"明确知道卡在哪一环、
用哪个工具、按什么顺序验证"。** 这是可以交接的状态。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.209"),
                         ("HANDOFF-CURRENT.md", "### 16.97")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.209", "### 16.97")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
