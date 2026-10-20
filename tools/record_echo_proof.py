"""Record round 72: the four successes came from the blind UDP echo."""
from pathlib import Path

TEXT = """
### 12.87 ★★★ 那 4 次成功来自 `lobby_udp` 的盲目 echo（2026-10-24 06:2x）

#### 改动

`server319/lobby_udp.py` 的 `LobbyEndpoint` 一直以 `echo=True` 构造，即**收到什么就原样回什么**。
新增环境开关：

```python
echo = os.environ.get("LOBBY_UDP_ECHO", "1").strip().lower() not in ("0", "false", "no")
server = LobbyEndpoint(port, log, echo=echo)
```

解析逻辑已单独验证：

```
LOBBY_UDP_ECHO=None/'1'/'TRUE'/''  -> echo=True
LOBBY_UDP_ECHO='0'/'false'/'no'    -> echo=False
```

（顺带补了缺失的 `import os`——`py_compile` 不会发现函数体内的未定义名字，
运行时才会 `NameError`。）

#### 对照实验

在同一套已验证环境（`run_verified.ps1`）下，只改 `LOBBY_UDP_ECHO`：

| 配置 | `0xBB170C` 成功出口计数 |
|---|---|
| `LOBBY_UDP_ECHO=1`（默认） | **4 次 / 10 秒** |
| `LOBBY_UDP_ECHO=0` | **0 次 / 12 秒** |

**关闭 echo 后成功次数归零。**

#### 结论

客户端在 3074 上发出的探测包被 `lobby_udp` 原样回送，客户端把这份**回声**当成
"收到一条数据"，进入 `0xBB170C` 成功路径；但回声内容并不是服务器列表，
解析出的条目数为 **0**，所以 `[container+0x84]` 依然是 0。

**这把"52:1 的偶发成功"完全解释了：那 1 次就是回声。**

#### 但问题没有因此解决

关闭 echo 后：

```
dw=5  G1=0  1F4=1  obj1[0x120]=3  idx=5
```

**状态完全没有变化。** 说明：

- echo **不是**导致 `count=0` 的原因——它只是制造了"假成功"；
- 去掉假成功之后，客户端依然拿不到真正的服务器列表数据；
- 阻塞点仍然是**这条 UDP 通道上没有符合协议的服务端数据**。

#### 至此可下的结论

客户端侧的逻辑是完好的：

```
pump 每帧 → 虚函数 → 0xBB15E0 recv
   无数据 → WSAEWOULDBLOCK → -2 → 不写 count
   有数据（包括我们的回声）→ 成功 → 解析 → 但内容不是列表 → 0 条
```

**两条路都得到 count = 0**，而 `Add` 的 `count<=0` 分支会把索引推到容量、写 3、
永久短路。要打破这个环，只能**让那条通道上出现真正的服务器列表数据**。

#### 下一步

1. **确认这条 socket 的远端**：在 `0xBB15E0` 入口读 `ecx`（this）与 `[ecx+4]`（句柄），
   用 `WSAPROTOCOL_INFO` 或 `getsockname` 把句柄映射到本地端口，再与 `netstat` 对照。
   现在已知 3074 上的回声能进入成功路径，**大概率就是 3074**，但仍需证据；
2. **构造符合协议的应答**：若确认是 3074，则需要给 `lobby_udp` 增加"识别探测包
   并按 `svc71/task4` 语义回一个有效应答"的能力，而不是原样 echo；
3. 探测包的字节已经在 `lobby_udp.jsonl` 的 `udp_in` 事件里记录（`hex` 字段），
   可以直接对照 `decrypt_frames.py` / `parse_task_tlv.py` 解析出它想要的 task。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.87"),
                         ("HANDOFF-CURRENT.md", "### 15.75")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.87", "### 15.75")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
