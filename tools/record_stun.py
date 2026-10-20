"""Record round 68b: the external connections are STUN and Tencent QoS endpoints."""
from pathlib import Path

TEXT = """
### 12.83 ★★★ 外部连接是 STUN 与腾讯 QoS 端点（2026-10-24 03:4x）

#### 先确认地址不是硬编码

`tools/find_ip.py` 在 EXE 里搜 `42.187.183.162`、`116.130.229.213`、`223.109.218.119`
的字节形式与 ASCII 形式：**全部 0 命中**。配置文件里也没有。

**所以这些 IP 是运行时 DNS 解析得到的。**

#### EXE 里的域名表

从可执行文件中抽取域名样式字符串，得 22 条，其中与网络相关的：

```
0x00D5A9D4  stun.au.demonware.net
0x00D5A9EC  stun.jp.demonware.net
0x00D5AA04  stun.eu.demonware.net
0x00DC65F8  stun.us.demonware.net
0x00DBD580  cod4master.activision.com
0x00DD9890  ied-tqos.qq.com          （腾讯 QoS）
0x00E513DF  down-update.qq.com       （更新下载）
0x00E5BA2F  kf.qq.com                （客服页面）
```

**四个 `stun.*.demonware.net`** 是 STUN（Session Traversal Utilities for NAT）服务器，
用于 NAT 穿透。这与 §12.82 观察到的两个"已连接"状态 UDP socket 完全对应：

```
UDP  0.0.0.0:53792   42.187.183.162:8080
UDP  0.0.0.0:61562   116.130.229.213:8000
```

两类端点（STUN 与 QoS）都会表现为"发出去一个包、等一个回包"的形态。

#### 这给了 `count = 0` 一个物理原因

```
client 启动时仍按原设计探测 STUN / QoS
  -> 那些服务器早已随游戏停服而下线
  -> 从不回包
  -> 0xBB15E0 的 recv 永远 WSAEWOULDBLOCK
  -> 条目数恒为 0
  -> Add 走 count<=0 分支，索引涨到容量后写 3
  -> 1F4 恒为 1，FE 梯停住
```

**第一次为"数据为什么不来"给出了可验证的物质原因：对面没人。**

#### 但必须谨慎：`0xBB15E0` 是否就是 STUN 通道尚未证实

`0xBB15E0` 在一条 socket 上接收，但**目前没有任何直接证据**表明那条 socket
就是 STUN/QoS 之一。可能的替代解释：

1. 它是大厅通道，而我们提供的 UDP 3074 回声数据格式不对；
2. 它是另一个内部通道（例如 Demonware 的匹配服务）。

**验证方式**：给 `0xBB170C`（成功）与 `0xBB16F8`（失败，返回 -1）各装计数器。
两者字节都是干净的指令起点：

```
0xBB170C: 8b 4d ee 51 ff 15 d4 84 ...   mov ecx,[ebp-0x12] / push ecx / call [..]
0xBB16F8: 5e 5f 83 c8 ff 5b 8b 4d ...   pop esi / pop edi / or eax,-1 / pop ebx
```

- 若 `0xBB16F8` 每帧命中 → 接收一直失败，与"对面没人"一致；
- 若 `0xBB170C` 每帧命中而 `count` 仍为 0 → 接收成功但内容为空，
  说明**对面有回包但数据不完整**，那就是我们自己的服务端数据问题。

#### 下一步

1. 装上述两个计数器，确定走哪条；
2. 用 `netstat` 记录这两个 UDP socket 的**流量计数**（或抓包）——
   若客户端持续发 STUN Binding Request 而从不收到 Response，则"对面没人"成立；
3. 若确认是 STUN 阻塞，则最省事的做法是**在本机起一个最小 STUN 应答器**，
   或把这些域名解析到 `127.0.0.1` 并提供应答（注意：这属于客户端侧配置，
   不触碰主机网络设置，符合边界）。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.83"),
                         ("HANDOFF-CURRENT.md", "### 15.71")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.83", "### 15.71")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
