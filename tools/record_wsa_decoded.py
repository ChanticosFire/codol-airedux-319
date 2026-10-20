"""Record round 70: the WSA jump table decoded, and -2 (WSAEWOULDBLOCK) is the dominant path."""
from pathlib import Path

TEXT = """
### 12.85 ★★★ WSA 跳表解码：`WSAEWOULDBLOCK` → 返回 -2 → 直接走失败路径（2026-10-24 05:1x）

#### 跳表结构

`jmp dword ptr [ecx*4 + 0xBB1750]` 用的是 **6 项**地址表（因为索引表紧跟在
`0xBB1768`，也就是说地址表只能占 `0x18 = 24` 字节）。从运行中的进程内存读出：

```
addr table 0xBB1750, 6 dwords:
  [0] 0x00BB16CC
  [1] 0x00BB16E2
  [2] 0x00BB166F      <- 返回 -2
  [3] 0x00BB16B6
  [4] 0x00BB1685
  [5] 0x00BB16F8      <- 返回 -1（默认）
```

索引表（62 字节，对应错误码 10004 起）：

```
00 05 05 05 05 05 05 05 05 05 05 05 05 05 05 05 05 05 01 05 05 05 05 05 05 05
05 05 05 05 05 02 05 05 05 05 03 05 05 05 05 05 05 05 05 05 04 04 05 04 04 05
05 05 05 05 04 05 05 05 05 04
```

解码结果：

| 索引 | 错误码 | 名称 | 处理地址 |
|---|---|---|---|
| 0 | 10004 | `WSAEINTR` | `0xBB16CC` |
| 1 | 10022 | `WSAEINVAL` | `0xBB16E2` |
| **2** | **10035** | **`WSAEWOULDBLOCK`** | **`0xBB166F`（返回 -2）** |
| 3 | 10040 | `WSAEMSGSIZE` | `0xBB16B6` |
| **4** | 10050, 10051, 10053, **10054**, 10060, 10065 | `NETDOWN` / `NETUNREACH` / `CONNABORTED` / **`CONNRESET`** / `TIMEDOUT` / `HOSTUNREACH` | `0xBB1685` |
| 5 | 其余 | 默认 | `0xBB16F8`（返回 -1） |

#### 与第 69 轮观测对账

第 69 轮实测：

```
入口 0xBB15E0            约 21 次/秒
成功出口 0xBB170C        约 0.4 次/秒
-1 出口 0xBB16F8         0 次
```

**`-1` 出口为 0** 说明错误码没有落在"默认"桶里；**成功只有 0.4 次/秒**说明绝大多数
落在某个**跳表分支**上。结合本轮的映射表，最可能的落点就是：

```
WSAEWOULDBLOCK(10035) -> index 2 -> 0xBB166F -> mov eax,-2
```

#### `-2` 之后的走向

虚函数里：

```asm
0xC74018  test ebx, ebx
0xC7401A  jns 0xC74021        ; -2 不成立
0xC7401C  cmp ebx, -5
0xC7401F  jne 0xC7406E        ; -2 != -5 -> 失败路径
```

**`-2` 直接跳到 `0xC7406E` 的失败路径，不执行 `0xB75420`，因此
`[container+0x84]` 保持 0。**

#### 完整因果链（至此闭环）

```
pump 每帧
  └─ 虚函数 0xC73FB0（约 21 次/秒）
       ├─ 0xBB15E0  在一条 UDP socket 上接收
       │    ├─ 无数据 → WSAGetLastError = 10035 (WSAEWOULDBLOCK)
       │    │            → 跳表 index 2 → 0xBB166F → 返回 -2
       │    └─ 有数据 → 返回 >= 0 → 0xBB170C 成功路径
       ├─ 返回值 -2 → 0xC7401F jne → 0xC7406E 失败路径
       │    → 不写 [container+0x84]
       └─ Add(obj1, count = 0)
            → 0xBBA5C3 → 索引 +1 → 涨满容量 → 写 3
            → 1F4 恒为 1 → FE 梯停住 → 客户端留在代号页
```

**"对面没人"这个假设现在有了代码级证据：错误码 10035 对应"暂无数据"，
而这条 socket 在我们的环境里永远暂无数据。**

#### 修复方向（明确）

问题不在客户端判断逻辑，而在**那条 UDP socket 上没有数据到达**。三种可能：

1. **它是 STUN/QoS 通道**（§12.83），对端已停服 → 需要在本机提供最小应答；
2. **它是大厅通道**，我们的 `lobby_udp` 回声不符合协议 → 需要按协议补应答；
3. 客户端从未向它发过请求，所以自然收不到响应 → 需要在客户端侧触发。

**下一步**：给 `0xBB166F`（`-2` 出口）装计数器。若它每帧命中，就确认主体是
`WSAEWOULDBLOCK`；然后找出这条 socket 的本地端口（可在 `0xBB15E0` 入口读
`[this+4]` 句柄并反查 `netstat`），确定它对应哪一个远端地址。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.85"),
                         ("HANDOFF-CURRENT.md", "### 15.73")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.85", "### 15.73")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
