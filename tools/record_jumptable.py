"""Record round 69: most calls leave via the WSA error jump table, not success or the -1 exit."""
from pathlib import Path

TEXT = """
### 12.84 ★★★ 大多数调用走的是 WSA 错误跳表，不是成功也不是 -1 出口（2026-10-24 04:2x）

#### 两个分支的计数

`0xBB15E0` 入口约 **21 次/秒**（§12.80）。本轮分别计数它的两个已知出口：

```
[succ] 0xBB170C（jns 目标，返回值 >= 0）   calls = 4,  total after 10s = 4
[fail] 0xBB16F8（or eax,-1，返回 -1）     calls = 0,  total after 8s = 0
```

- **成功出口 10 秒只有 4 次**（约 0.4 次/秒）；
- **`-1` 出口从未命中**。

**两者相加远小于入口次数。** 说明绝大部分调用从**第三个出口**离开——
`0xBB1652` 之后的 WSA 错误码跳表。

#### 第三次探测时的操作错误

第一次测成功分支时我传了 **8 字节**重放，而 `0xBB170C` 处的指令是：

```
8b 4d ee          mov ecx, [ebp - 0x12]        3 字节
51                push ecx                     1 字节
ff 15 d4 84 ca 00 call dword ptr [0xCA84D4]    6 字节
```

合计 **10 字节**。我只重放了前 8 字节，把 call 的 rel32 截断了，客户端随即崩溃——
但在崩溃前已经记到 **2 次**命中，说明当时就在走成功分支。第二次改用正确的 10 字节，
得到稳定的 4 次。

**这是第 65 轮同类错误的翻版**：为 trampoline 选重放长度时必须逐条数清指令字节，
不能凭"看起来够长"。

#### 由跳表结构反推实际错误

```asm
0xBB164C  call dword ptr [0xCA853C]          ; WSAGetLastError
0xBB1652  lea ecx, [eax - 0x2714]            ; 减去 10004
0xBB1658  cmp ecx, 0x3d                      ; 0..61
0xBB165B  ja 0xBB16F8                        ; 超出范围 -> 返回 -1
0xBB1661  movzx ecx, byte ptr [ecx + 0xBB1768]   ; 索引表
0xBB1668  jmp dword ptr [ecx*4 + 0xBB1750]       ; 地址表
```

跳表在 `0xBB1750`（地址表）与 `0xBB1768`（索引表）。已看到的一个分支：

```asm
0xBB166F  pop esi / pop edi
0xBB1671  mov eax, 0xFFFFFFFE                ; 返回 -2
0xBB1676  pop ebx / ...
```

所以存在 `-2`、`-1` 等不同返回值，每个对应一类 WSA 错误。

#### 目前的结论

| 事实 | 数值 |
|---|---|
| `0xBB15E0` 入口调用 | 约 21 次/秒 |
| 成功出口（`>= 0`） | 约 0.4 次/秒 |
| `-1` 出口 | 0 次 |
| 其余 | 走 WSA 错误跳表 |

**即：这条 socket 绝大多数时间处于"有错误"状态，偶尔成功。**

若主体错误是 `WSAEWOULDBLOCK`（非阻塞无数据），那就完全支持 §12.83 的
"对面没人"假设；若是 `WSAECONNRESET` 之类，则说明对面有回包但连接被重置。

而"偶尔成功"的 4 次值得注意——**如果成功时能读到条目，`count` 就该变成非零**。
实测 `obj1[0x120]` 仍为 3、`idx` 仍为 5，说明那 4 次成功也没有带出有效条目。

#### 下一步

1. **读跳表内容**：`0xBB1750` 处 62 个 dword（地址），`0xBB1768` 处 62 个 byte（索引）。
   把 `0xBB1700`–`0xBB1800` 这段整块转储并解码，能列出所有已处理的错误类型；
2. **确定主体错误码**：在 `0xBB1652` 之后（例如 `0xBB1658`）装一个"记录 `ecx` 值"的探针，
   采样若干次看它最多落在哪个值上。`ecx` 加回 `0x2714` 就是 WSA 错误码；
3. 若确认是 `WSAEWOULDBLOCK`，则下一步应在**服务端**为该 socket 提供数据，
   而不是继续改客户端。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.84"),
                         ("HANDOFF-CURRENT.md", "### 15.72")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.84", "### 15.72")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
