"""Record the /ipc dead end and the bdInt32 vtable identification."""
from pathlib import Path

TEXT = """
### 12.28 `/ipc` 判定为死胡同；`[lobby+0x1F0]` 是 Demonware 变量对象（2026-10-23 01:5x）

#### `/ipc` 的三个反证

上一节（§12.27）因为 `[lobby+0x8A8]` 里出现 `POST /ipc HT` 而怀疑本地 IPC 服务缺失。
本轮按计划验证，结论是**死胡同**：

1. **没有任何 `/ipc` 连接**。客户端运行期的 TCP 连接只有两条：
   ```
   LocalPort  RemoteAddress  RemotePort  State
        1096   0.0.0.0               0  Bound
        1096   127.0.0.1          4174  Established   <- 只有 LSG
   ```
2. **`[lobby+0x184]` 不是地址/端口结构**。`0xC699B0` 复制的那块内容是浮点参数：
   ```
   64 00 00 00 00 00 a0 40 05 00 00 00 ...   -> 5.0f
   05 d0 1a 00 00 00 00 3f 03 00 00 00 ...   -> 0.5f
   00 00 00 00 04 00 00 00 00 00 40 3f ...   -> 0.75f
   ```
   没有任何端口字段。
3. **`/ipc` 是残留字符串**。`[lobby+0x8A8]` 是一块 **22011 字节**的缓冲，前面的
   `c0 a8 01 03` 与末尾的 `POST /ipc HT` 是不同时期写入的内容，不是一条待发请求。

因此 `/ipc` 与 pump 判定无关，这条线关闭。

#### `[lobby+0x1F0]` 的真实类型

之前 RTTI 解析失败（`signature=0x4A5F4442` 即 `"BD_J"`、`type_desc=0`），
因为把 `[obj]` 的值当成了 vtable 地址却用模块基址去换算，超界。

改用 `tools/peek.py` 直接读运行期内存，`0xD5B12C` 处内容是：

```
0x00d5b12c  f0 b0 d5 00  e0 b0 d5 00  d0 b0 d5 00  c0 b0 d5 00   <- 函数指针
0x00d5b13c  b0 b0 d5 00  62 64 49 6e 74 33 32 00  62 64 55 49   <- "bdInt32", "bdUI
0x00d5b14c  6e 74 33 32 00  00 00 00 00  62 64 55 49 6e 74 36 34  <- "nt32", "bdUInt64"
0x00d5b15c  00 00 00 00  74 72 75 65 00 00 00 00  66 61 6c 73  <- "true", "fals"
```

**这是 Demonware 的变量类型系统 vtable 区**：`bdInt32` / `bdUInt32` / `bdUInt64` /
`true` / `false` 这些名字连同它们的虚函数表连续排列。

所以 `[lobby+0x1F0]` 是一个 **Demonware 变量对象**（`bdInt32` 一类），
`0xBAF040` 检查的是某个 dvar/属性对象，而不是网络连接。

#### 修正后的理解

`0xBAF040` 的判定针对 **Demonware 变量对象**，其中 `[lobby+0x6D0]` 首字段为 **15**，
不是 `0x17`(23)。判定成功需要「对象类型是 23」或「两个对象首字段不同」。

这更像是**在变量表里查找某个特定 dvar**：`0x17` 是某个哨兵类型，否则按类型去重。
`[lobby+0x8A8]` 的缓冲只是这个变量对象内部的存储区，之前看到的 `192.168.1.3`
和 `POST /ipc` 都是这块存储的历史残留，与判定无关。

#### 结论

- `/ipc` 线关闭，不再投入；
- `[lobby+0x1F0]`/`[lobby+0x6D0]` 是 Demonware 变量对象，不是连接对象；
- `[lobby+0x1F4]` 停在 1 的原因是变量查找/过滤未命中，与网络协议无关。

#### 下一步

既然 `[lobby+0x8A8]`/`[lobby+0x184]` 都是变量存储而非网络数据，说明
**pump 的这段逻辑根本不在协议路径上**，继续挖它对 M4 的直接帮助有限。

按「同一阻断连续 3 轮无进展则换方向」的规则，`[lobby+0x1F4]` 这条线已投入
第 10-12 三轮仍未打通，应当换方向。下一轮转回协议侧：直接实现 `svc21/task5`
的 room-list 应答并配合 `svc71/task9`，观察客户端在没有 pump 推进的情况下
是否仍能渲染房间列表——这更贴近 M4 的验收判据「房间列表可见」。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.28"),
                         ("HANDOFF-CURRENT.md", "### 15.16")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.28", "### 15.16")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
