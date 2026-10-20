"""Record round 86: edx becomes 127.0.0.1, but only after the index has already filled."""
from pathlib import Path

TEXT = """
### 12.101 ★★★ 写进槽的值是 `127.0.0.1`（= 16777343），但来得太晚（2026-10-24 13:5x）

#### 采样 `edx`

在 `0xBB171F`（`mov dword ptr [edi], edx`）装探针（重放 5 字节
`89 17 | 8D 46 1C`，逐条数过），采样 `edx`：

```
[edx] n=0  edx=0x00000000  (0)
[edx] n=2  edx=0x0100007F  (16777343)
```

**`0x0100007F` 是 `127.0.0.1` 的网络字节序形式。**

所以虚函数成功时写进 `[ebp-0x548]` 的是**本地回环地址**，而不是一个条目计数。

#### `Add` 眼里它是巨大的正数

`Add` 的 count 就是这块内存（§12.99/§12.100），所以

```
count = 0x0100007F = 16,777,343 > 0
```

**按 `0xBBA440 test edi,edi` / `0xBBA442 jle`，这个值是正的，应当走成功分支、写 2。**

但实测状态仍是 3。

#### 矛盾的解释：时序

`probe_reg.py` 只在数值变化时打印，所以 `n` 是命中序号：

- **第 1 次（n=0）`edx = 0`**——那时虚函数还没拿到地址，
  于是 `[ebp-0x548] = 0`，`count = 0`，`jle` 成立，**跳过写 2**，然后 `0xBBA5E6`
  推进索引；
- 索引约 2 秒涨一个，容量 5，**约 2.5 秒后写 3**，状态锁定；
- **第 2 次（n=2）`edx = 0x0100007F`** —— 此时可能已经过了 2.5 秒窗口，
  或者状态已是 3，`Add` 在入口 `cmp [ebx+0x120],1` 就被拦住，根本走不到
  `mov [edi],edx` 之后的逻辑。

**即：正确的数据（`127.0.0.1`）确实出现过，但出现得太晚，窗口已经关闭。**

#### 这与 §12.82 的观察一致

客户端向 `127.0.0.1:3074` 发探测包，服务端（我们的 `lobby_udp`）回包，
客户端解析出 `127.0.0.1` 这个地址并写入槽位——**说明这条 UDP 通道工作正常，
对端就是本地**。

#### 于是真正的修复方向明确了

不是"数据没来"，而是**"数据来的时候状态已经锁死"**。两种做法：

1. **让服务端在客户端启动后尽可能早地回第一个包**——把 `[ebp-0x548]` 在
   2.5 秒内写成 `127.0.0.1`，赶在索引填满之前。`LOBBY_UDP_REPLY` 已经能
   立刻回包，问题在于客户端何时发出第一个探测包；
2. **让索引涨得慢或不涨**——第 52 轮已证明容量抬到 200 能拖到约 100 秒。
   若同时配合立即回包，窗口绰绰有余。

**第 2 条是可立即验证的组合**：

```
LOBBY_UDP_REPLY=1e8300（或原样 echo）
+ 运行期把 [obj1+0x124] 抬到 200、[obj1+0x130] 清零、[obj1+0x120] 置 1
+ 等服务端把 127.0.0.1 写进槽（约 2 次成功即可）
→ 期望：状态变 2，Add 永久短路，1F4 有机会变 2
```

第 81 轮做过类似实验但没成功，当时的观测是"索引一直在涨、状态保持 1"。
**差别在于那时回的是 `1e 83 00`，而本轮证明真正带出 `127.0.0.1` 的是
**原样 echo 之外的某条路径**——需要确认哪一种应答能让 `edx` 变成
`0x0100007F`。

**下轮的关键动作**：在 `LOBBY_UDP_REPLY` 与 `LOBBY_UDP_ECHO` 两种模式下分别
采样 `edx`，确定哪种应答能让它尽早变成 `127.0.0.1`。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.101"),
                         ("HANDOFF-CURRENT.md", "### 15.89")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.101", "### 15.89")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
