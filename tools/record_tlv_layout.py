"""Record the svc71 request TLV layout decoded from a real task4 frame."""
from pathlib import Path

TEXT = """
### 12.47 `svc71` 请求的 TLV 结构完全解开（2026-10-23 08:0x）

#### 帧头是 `47 03 <task>`

解密后的载荷以固定三字节开头：

```
0x47   事件标记
0x03   版本标记（固定）
0xNN   task 号
```

实测对应关系：`47 03 04` = task4、`47 03 07` = task7、
`47 03 03` = task3、`47 03 09` = task9。

#### 字段编码

| 标记 | 含义 | 说明 |
|---|---|---|
| `0x13` | **带长度前缀的字节串**（容器） | 后跟 `0x08` + u32 长度 + 内容 |
| `0x08` | u32 | 直接跟 4 字节 |
| `0x10` | 以 `0x10`+长度+内容 的纯字符串 | 见 task3/7 的日志文本 |
| `0x03` | u8 | |

#### `task4`（ListDedicatedServer）的完整参数

```
47 03 04                     EVENT ver=3 task=4
13 08 10 00 00 00            [u32 长度 16]
   6e 51 6c 6f 50 30 6f 43    "nQloP0oCVWR6RDJS"   <- 客户端会话标识
   56 57 52 36 52 44 4a 53
13 08 10 00 00 00            [u32 长度 16]
   2b x16                     "++++++++++++++++"    <- 占位/分隔串
08 97 cb e6 01               u32 = 0x01E6CB97       <- 某个序号或时间
13 08 00 00 00 00            [空串]
13 08 00 00 00 00            [空串]
10 31 43 2d 38 33 2d ...     "1C-83-41-CE-8D-EE"    <- 机器/网卡标识
```

即 task4 携带：**会话 ID + 占位串 + 一个 u32 + 两个空串 + 一个 MAC 风格标识**。
没有任何与房间列表相关的过滤条件——它是"列出所有可用服务器"，这与
`ListDedicatedServer` 的语义一致。

#### `task9` 是空请求

```
47 03 09 08 07 00 00 00      EVENT task=9, u32 = 7
```

只有一个 u32 参数（值为 7），符合"按 ID 查询会话"的形态。

#### 与 M3 对照

M3 那次 `task4` 请求 83 字节，本次也是 83 字节，`task9` 都是 8 字节。
**请求侧完全一致**，说明客户端发出的东西没有问题。

差异只在请求**之后**的行为：M3 的客户端继续跑 54 秒后正常结束，我们的客户端
在 `task9` 之后崩溃并上报 `ClientOffline`/`ClientException`。

#### 结论

请求侧已完全解析，且与 M3 逐字节同构。问题**确定在应答侧或客户端内部状态**：

1. 应答侧：`task4` 的应答是 4 字节的 `u32 0`（`LSG_T4_MODE=zero`），
   而 M3 也是这么回的，所以应答形状大概率不是原因；
2. 客户端状态：`[lobby+0x1F4]=2` 是我们强写的，pump 那条分支需要的后续数据
   并未准备好，客户端在 `task9` 之后检查时发现不一致 → 判定离线 → 上报日志 → 退出。

#### 下一步

按上一条推断，应当**放弃强写 `[lobby+0x1F4]=2`**，改为验证：
仅写 `[D+0xC]=1` + `FE_state=3`（实验 B 的配置）时，客户端能存活多久、
`ui_state` 会停在什么值。若它能稳定存活而不崩，则说明 1F4 的强写是崩溃源，
后续应转向让 pump 自己成功（即补上它期望的数据），而不是继续强写。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.47"),
                         ("HANDOFF-CURRENT.md", "### 15.35")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.47", "### 15.35")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
