"""Record round 202: final state at the end of the 200-round goal."""
from pathlib import Path

TEXT = """
### 12.212 长程目标结束时的最终状态（2026-10-27 02:5x）

#### 目标达成情况

| 阶段 | 状态 |
|---|---|
| M0 文件与社区基线 | **完成** |
| M1 完整性与跨版本映射 | 进行中 |
| 版本切换（1649370 → 1604220） | **完成** |
| M2 最小离线启动链 | 进行中 |
| **M3 原生前台与大厅** | **完成**（五项判据全达成） |
| **M4 玩法与数据** | **未达成** |
| M5 成果整理与协作 | 进行中 |

**M4 的五项判据全部未开始**，因为客户端从未离开「请先取一个代号」页面。

#### M4 的阻塞点（最终表述）

**收包 socket（`[[lobby+0xC]+4]` = `11648`）有效、可读、每帧被调用（3.7 次/秒），
但队列始终为空——67 次采样全部返回 `-2`（`WSAEWOULDBLOCK`）。**

**因此 `Add` 的 `count` 恒为负，永远走推进索引分支，
状态码到不了 2，`[lobby+0x1F4]` 永远是 1，前端梯永不推进。**

**我们发的任何数据都没有排进那个 socket 的接收队列。**
已排除：回探测包源 `22011`（§12.204）、向全部 6 个 UDP 端口发 160 字节（§12.206）、
在 3074 上发 9 字节类型 `0x15` 消息（§12.182）。

#### 边界

**要把句柄 `11648` 映射到具体本地端口，需要系统级句柄表查询
（`NtQuerySystemInformation` 等），超出本项目的授权边界**
（不做主机级网络改动、不加载驱动）。

**因此在当前边界内，本结论已是最深层次。**

#### 本系列的实质产出（可交接）

**1. 完整每帧循环**（`PUMP-STATE-MACHINE.md`）

```
收包（vt+0x1C，0xC73FB0，socket = [[lobby+0xC]+4]）
  -> 字节数 esi（实测恒为 -2）
  -> 组装 136 字节记录 -> Add(0xBBA3F0)
  -> 读状态 -> 三道守卫 -> 通过才写 1F4 = 2
```

**2. `Add` 的两个过滤分支及其实证**

`0xBBA465` / `0xBBA483`，各打 6 字节 `nop` 后状态稳定变 2（1883 次采样）。

**3. 类型 `0x15` 消息的格式与通路**

9 字节最小；通路 `0xBAE2C2 → 0xBBADE0 → 0xBBAAF0`，完全在 pump 内。

**4. 四项被修正的错误结论**

| 错误 | 修正 | 原因 |
|---|---|---|
| socket 从未创建 | 存在且有效 | 漏了 `[serverlist]` 一级 |
| `0x853A10` 按类型查表 | 恒等函数 | 直接反汇编 |
| 返回 ≥136 字节即可 | 通道不对 | 两次实验均无变化 |
| 收包 socket 在 `[[serverlist]+4]` | 在 `[[lobby+0xC]+4]` | 读错对象 |

**5. 六份文档完成收束，40 项单测全绿，309 次提交**

#### 下一步（若能突破边界）

1. **用系统级句柄查询把 `11648` 映射到本地端口**，然后向该端口发包；
2. 或**改用 TCP 4174（LSG 通道）下发数据**——客户端只有这一条 TCP 连接；
3. 或在 `0xC73FB0` 内部找 `getsockname` 的调用点，读出端口。

**三者都需要超出当前授权的手段，或改动客户端代码。**

#### 最终诚实结论

**M4 未达成。** 差距不是"再做一点"，而是**一个尚未定位的端口**，
而定位它需要越过本项目的授权边界。

**但整条链已经追到底：从"客户端停在代号页"到"某个 socket 的接收队列始终为空"，
每一环都有反汇编地址与运行时读数支撑。**

**这是一份可以让人从第 212 节接着做下去的交接。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.212"),
                         ("HANDOFF-CURRENT.md", "### 16.100")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.212", "### 16.100")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
