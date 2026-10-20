"""Record round 68: the client still holds six external connections."""
from pathlib import Path

TEXT = """
### 12.82 ★★★ 客户端仍在连接 6 个外部服务器（2026-10-24 03:2x）

#### netstat 实测（按 PID 过滤，客户端 pid = 18044）

UDP：

```
UDP    0.0.0.0:22011          *:*                                  18044
UDP    0.0.0.0:53791          *:*                                  18044
UDP    0.0.0.0:53792          42.187.183.162:8080                  18044   <- 外部
UDP    0.0.0.0:61562          116.130.229.213:8000                 18044   <- 外部
UDP    0.0.0.0:61563          *:*                                  18044
UDP    0.0.0.0:61971          *:*                                  18044
```

TCP：

```
TCP    127.0.0.1:13201        127.0.0.1:4174        ESTABLISHED     18044   <- 我们的 LSG
TCP    192.168.10.108:5500    223.109.218.119:80    ESTABLISHED     18044   <- 外部
TCP    192.168.10.108:5501    223.109.218.119:443   ESTABLISHED     18044   <- 外部
TCP    192.168.10.108:5502    223.83.231.50:49155   ESTABLISHED     18044   <- 外部
TCP    192.168.10.108:5503    223.111.147.249:49156 ESTABLISHED     18044   <- 外部
```

**除了我们自己的 `127.0.0.1:4174`，客户端还挂着 6 条外部连接。**
其中两条 UDP 是"已连接"状态（`42.187.183.162:8080`、`116.130.229.213:8000`），
说明客户端主动向它们发过包并期待回包。

#### 这对 §12.81 的意义

`0xBB15E0` 在一条 socket 上做接收，`count` 恒为 0 意味着那条 socket 上没有数据。
现在有了明确候选：**它等的很可能就是这些已被永久停服的外部通道之一**。

即：

```
client 仍按原设计连向腾讯的服务器
  -> 那些服务器早已下线，从不回包
  -> 0xBB15E0 的 recv 一直 WSAEWOULDBLOCK
  -> 条目数恒为 0
  -> Add 走 count<=0 分支，索引涨到容量后写 3
  -> 1F4 恒为 1，FE 梯停住，客户端留在代号页
```

**这条链与我们此前观测到的所有现象都一致**，而且第一次给出了"数据为什么不来"
的物理原因——**因为对面根本没人**。

#### 但这不构成"无法解决"

关键在于：**这些连接目标是可以在客户端侧改掉或拦掉的**。三种思路：

1. **找出这些地址的来源**（硬编码在 EXE / 配置文件 / 注册表），把它们改成
   `127.0.0.1` 指向我们的服务；
2. 若协议已知，直接在我们的服务上复现对应应答；
3. 若这些连接只是遥测/反作弊而非大厅数据通道，则在客户端侧让它们快速失败，
   观察 `0xBB15E0` 是否转而读取我们提供的 socket。

第 1 条最直接。**下一轮应当先在 EXE 里搜这些 IP 的字节形式**：

```
42.187.183.162  = 2A BB B7 A2
116.130.229.213 = 74 82 E5 D5
```

若命中，就能定位读取它们的代码；若不在 EXE 里，就去 `config_mp.cfg`、
`players/` 目录与注册表查。

#### 两个分支的边界已确认

```
0xBB170C: 8b 4d ee 51 ff 15 d4 84 ...    mov ecx,[ebp-0x12] / push ecx / call [..]
0xBB16F8: 5e 5f 83 c8 ff 5b 8b 4d ...    pop esi / pop edi / or eax,-1 / pop ebx
```

两处都是完整指令起点，可以安全装计数器（`0xBB16F8` 明确把返回值置 `-1`，
是"失败"出口）。下一轮一并测量。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.82"),
                         ("HANDOFF-CURRENT.md", "### 15.70")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.82", "### 15.70")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
