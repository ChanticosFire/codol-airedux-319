"""Record the /ipc discovery and what it implies."""
from pathlib import Path

TEXT = """
### 12.27 `[lobby+0x8A8]` 里是 HTTP 请求缓冲，含 `POST /ipc`（2026-10-23 01:4x）

#### 实测内容

`tools/probe_lobby_1f4.py` 现在会完整转储 `[lobby+0x8A8]` 的 144 字节：

```
0x36b56900  c0 a8 01 03 00 00 00 00 00 00 00 00 fe ff ff ff   ← 192.168.1.3 + -2
0x36b56910  00 00 00 00 00 00 00 00 18 a6 1a 00 9e 5f f6 76
0x36b56920  ec 3c e1 0e 19 17 f2 76 d0 3c e1 0e fe ff ff ff
0x36b56930  00 00 00 00 18 ac 3c 4f 38 a6 1a 00 9e 5f f6 76
...
0x36b56980  02 00 91 49 50 4f 53 54 20 2f 69 70 63 20 48 54   ← "POST /ipc HT"
```

**末行明文 `POST /ipc HT`**（HTTP 的开头）说明这块内存是一个 **HTTP 请求缓冲区**，
目标地址是 `192.168.1.3`（本机内网）。

#### 由此修正对 `0xBAF040` 的理解

`0xBAF040` 检查的不是游戏大厅连接，而是**一个 HTTP 客户端对象**：

```asm
0xBAF040  ... add ecx,0x4C8 -> lobby+0x6D0
0xBAF066  call 0xBAFDA0       ; 取 [lobby+0x8A8] 的请求缓冲
0xBAF074  rep movsd 34        ; 复制 136 字节
0xBAF08A  call 0xB77020       ; 判定
```

被判定的是「这个 HTTP 请求/连接对象是否符合预期」，而请求是发往 `192.168.1.3`
的 `POST /ipc`。

#### `/ipc` 的来源

在主程序与 Base DLL 中都**搜不到** `/ipc` 或 `POST /ipc` 字符串（各 0 命中），
说明它要么运行时拼接，要么来自外部组件。客户端目录里有：

```
Cross\\CrossProxy.exe     1,040,976 B
Cross\\CrossShell.dll       364,624 B
Cross\\CrossInstaller*.dll
```

`CrossProxy.exe` 是腾讯的外挂代理进程，但：

- 它当前**没有运行**；
- 它自身也**不含** `/ipc` 字符串（0 命中）。

主程序里的 `HTTP/1` 字符串集中在 `0x621180` 附近（`Content-Encoding`、`x-compress`、
`gzip`、`Keep-Alive`），那是 demonware 的标准 HTTP 库，不是 `/ipc` 的实现。

#### 这一发现的意义

`POST /ipc` 是**本地 IPC**，与认证/大厅/对局都无关。但它出现在 pump 判定的路径上，
说明 `[lobby+0x1F4]` 卡在 1 可能与**某个本地 IPC 服务没起**有关，而不是与游戏服务器
协议有关。

这既可能是突破口，也可能是死胡同：

- **突破口**：若能提供 `/ipc` 服务（哪怕只是返回 200），`0xBAF040` 的判定可能通过，
  pump 自然推进到 2；
- **死胡同**：`/ipc` 只是 CrossProxy 的遥测/心跳，与大厅状态机无关。

需要先确认 `POST /ipc` 的目标端口与响应期望，才能判断。

#### 下一步

1. 在内存中定位该 HTTP 请求对象的**目标端口**字段（`[lobby+0x8A8]` 前的
   `[lobby+0x6D0...]` 结构里，或 `lobby+0x184` 那块被 `0xC699B0` 复制的区域）；
2. 观察运行期是否有进程监听该端口（`netstat` 对比 `CrossProxy` 起停）；
3. 若确认为本地服务缺失，写一个最小 `/ipc` 应答器再测 pump 是否推进。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.27"),
                         ("HANDOFF-CURRENT.md", "### 15.15")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.27", "### 15.15")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
