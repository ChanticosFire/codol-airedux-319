"""Record round 194: the client binds six UDP endpoints, only one of which sends the probes."""
from pathlib import Path

TEXT = """
### 12.205 ★★★ 客户端绑定 6 个 UDP 端点；探测只用了其中一个（2026-10-26 22:2x）

#### 实测

客户端进程 PID 1348，`Get-NetUDPEndpoint` / `Get-NetTCPConnection` 结果：

**UDP 端点（6 个，全部绑在 `0.0.0.0`）：**

```
62635
62634
62627
62626
62624
22011     ← ★ 探测包的源端口（日志确认 src="127.0.0.1:22011"）
```

**TCP 端点（1 个）：**

```
Bound       0.0.0.0:4351 → 0.0.0.0:0
Established 127.0.0.1:4351 → 127.0.0.1:4174      ★ LSG 通道
```

#### 三项结论

**1. LSG 是 TCP，不是 UDP**

`127.0.0.1:4351 → 127.0.0.1:4174`——**LSG 长连接走 TCP 4174**。

**所以类型 `0x15` 那条消息若要经 LSG，方向是"服务端在 4174 的 TCP 连接上下发"，
而不是 UDP。**

**2. 探测包只用了 `22011` 一个端口**

日志里所有 `udp_in` 的 `src` 都是 `127.0.0.1:22011`。

**另外 5 个端口（62624/62626/62627/62634/62635）从未向 3074 发过包。**

**3. 因此 §12.204 的阴性结果得到解释**

**我们在 3074 上回复探测包，数据回到 `22011` 那个 socket。
而 `vt+0x1C` 的收包用的是另一个 socket——它从未收到我们的任何字节。**

#### 这给出一个直接可测的假设

**如果那 5 个端点之一就是业务收包的 socket，
那么向它发送数据（而不是回 `22011`）应当能让 `vt+0x1C` 读到内容，
从而让 `Add` 的 `count > 0`。**

**验证方法（下一轮可做）：**

1. 启动客户端，等它到 `dw=5`；
2. 用 `Get-NetUDPEndpoint -OwningProcess <pid>` 取出全部 UDP 本地端口；
3. **对每个端口各发一条 160 字节的数据报**；
4. 轮询 `[serverlist+0x1A0]` 是否变成 2。

**这不需要改服务端代码，也不需要重启——一次运行内就能测完 6 个端口。**

#### 注意

**这 5 个端口每次运行都会变**（62624 等是临时端口），
所以不能用固定值，必须在运行时枚举。

**另外**：向这些端口发包时，源端口应当用一个普通的高位端口（不是 3074），
以免被客户端的来源校验拒掉——不过目前没有证据表明存在来源校验，
先直接用 3074 发也可以作为第一轮尝试。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.205"),
                         ("HANDOFF-CURRENT.md", "### 16.93")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.205", "### 16.93")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
