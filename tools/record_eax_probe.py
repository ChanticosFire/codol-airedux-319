"""Record round 200: the recv returns -2 (WSAEWOULDBLOCK) every frame - no data ever arrives."""
from pathlib import Path

TEXT = """
### 12.210 ★★★★ 决定性：收包每帧返回 `-2`（WSAEWOULDBLOCK）——数据从未到达（2026-10-27 01:5x）

#### 实验

在 `0xBAE244`（`0xBAE242 call eax` 之后的第一条指令）挂探针，采样 `eax`。
该处原始字节为 `8B F0 39 BB F8 01 00 00`（`mov esi,eax` + `cmp [ebx+0x1F8],edi`，共 8 字节），
符合工具的 5–16 字节要求。

**挂点选在收包调用之后，因此在 `0xC73FB0` 的 SEH 帧之外——安全。**

#### 结果

```
[0xbae244] client appeared after 0.2s
[0xbae244] image ready after 2.42s
[0xbae244] hook 0xbae244 -> cave 0x115f0000  slot 0x115f0100  reg eax
[0xbae244] n=0   eax=0x00000000
[0xbae244] n=1   eax=0xFFFFFFFE
[0xbae244] n=8   eax=0xFFFFFFFE
[0xbae244] n=37  eax=0xFFFFFFFE
[0xbae244] n=67  eax=0xFFFFFFFE
[0xbae244] final n=67  eax=0xFFFFFFFE
```

**67 次采样中，除第一次（对象尚未就绪）外，全部是 `0xFFFFFFFE`，即 `-2`。**

#### `-2` 的确切含义

§12.62 已确认：`0xBB15E0` 是 Winsock 接收包装，
**无数据时经 WSA 跳表返回 `-2`**（对应 `WSAEWOULDBLOCK`，错误码 10035）。

**所以：**

- **`0xC73FB0` 每帧都被调用**（67 次 / 18 秒 ≈ 3.7 次/秒，与 pump 频率一致）；
- **socket 是有效的**——若无效会返回 `WSAENOTSOCK` 而不是 `WSAEWOULDBLOCK`；
- **但那个 socket 上从未有过一个字节**。

#### 三方确认的完整闭环

| 事实 | 证据 | 推论 |
|---|---|---|
| 收包被调用 | 本轮 67 次采样 | pump 循环在跑 |
| socket 有效 | 返回 `WOULDBLOCK` 而非 `ENOTSOCK` | socket 已创建、已绑定 |
| 从未有数据 | 全程 `-2` | **我们的数据发到了别处** |
| `esi = -2` | `0xBAE244` 的 `mov esi,eax` | **长度是负数 → `Add` 走 `count <= 0`** |

**第 188 轮的推断得到最终确认：`Add` 的 `count` 是负的，
所以它永远走推进索引的分支，状态码永远到不了 2。**

#### 这确定了唯一未解决的环节

**不是"数据不足"，也不是"数据不合格"，而是"数据根本没到这个 socket"。**

**所以 §12.194 与 §12.206 的两项排除是正确的**：
回探测包源、向全部 6 个 UDP 端口发，都没有让这个 socket 收到任何东西。

**剩下的可能只剩两条：**

1. **业务数据走 TCP 4174（LSG 通道）**——客户端只有这一条 TCP 连接，
   而 UDP 侧 6 个端点已全部排除；
2. **这个 socket 已 `connect()` 到某个我们无法应答的外部地址**，
   内核只接受来自该对端的数据，因此我们发什么都进不来。

**第 2 条可以用 `Get-NetUDPEndpoint` 的 `RemoteAddress`/`RemotePort` 字段验证
（`Get-NetUDPEndpoint` 对已 connect 的 UDP socket 会显示对端）。**

#### 给接手者的结论

**这是整条链上最终的一个未知点。**

**下一步只需一次只读查询**：找出客户端那 6 个 UDP 端点中，
哪一个有非零的 `RemoteAddress` —— 那就是业务 socket 连接的目标。
**然后从那个目标地址/端口发包即可。**

**若全部 `RemoteAddress` 为 `0.0.0.0`，则业务数据走 TCP，
应在 LSG（4174）的 TCP 连接上下发。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.210"),
                         ("HANDOFF-CURRENT.md", "### 16.98")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.210", "### 16.98")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
