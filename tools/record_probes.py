"""Record round 73: the client's 3-4 byte probes, and the send/recv vtable pair."""
from pathlib import Path

TEXT = """
### 12.88 ★★★ 客户端在 3074 上发 3–4 字节探测包；vtable 里 send/recv 成对（2026-10-24 06:5x）

#### 探测包的实测内容

新增 `tools/decode_udp_in.py`，解析 `lobby_udp.jsonl` 的 `udp_in` 事件并按长度归并。
在 `LOBBY_UDP_ECHO=0` 那次运行里：

```
udp_in events: 12
distinct lengths: [3, 4]

--- length 3 (6 个数据报, 1 种内容) ---
  1e 03 00

--- length 4 (6 个数据报, 1 种内容) ---
  14 02 00 00

sources: {'127.0.0.1:22011': 12}
```

**全部来自本地端口 22011，发往 3074，内容只有两种，各 3–4 字节。**

这与 `svc71` 的 TLV（`47 03 <task>` 后跟类型化字段）完全不同——**3074 上跑的是另一套
精简协议**，形态上是 `[操作码][子码][参数...]`：

```
1e 03 00       0x1E = 30, 0x03 = 3
14 02 00 00    0x14 = 20, 0x02 = 2
```

每 10 秒各发 6 次，约 1.2 次/秒——**典型的 keepalive / 探测节奏**。

#### vtable 里 send 与 recv 成对

`find_calls.py 0xBB1420`（UDP sendto 包装）只返回**一个**调用者：

```
call at 0x00C73F88
```

而 `0xC73F88` 落在 `0xC73F30` 之内，也就是说：

| vtable 槽 | 函数 | 作用 |
|---|---|---|
| `[vt+0x18]` | `0xC73F30` | **发包** → `0xBB1420`（sendto 包装） |
| `[vt+0x1C]` | `0xC73FB0` | **收包** → `0xBB15E0`（recv + WSA 错误分派） |

**同一个对象的 send/recv 是两个相邻的虚槽。** pump 每帧对两者各调一次，
所以现象是"每帧发一个探测包，每帧尝试收一次回应"。

`0xBB1420` 的开头还印证了它与 `0xBB15E0` 是同一族的写法：

```asm
0xBB1420  push ebp / mov ebp,esp / sub esp,0x14
0xBB1431  mov esi, [ebp + 0x94]      ; 长度参数（和 recv 一样在 0x94）
0xBB1438  mov edi, [ebp + 8]
0xBB143B  cmp edi, -1                 ; 句柄无效直接返回
0xBB1440  lea eax, [edi - 9]
```

参数偏移 `0x90` / `0x94` 与 recv 侧一致，说明两者是同一协议层的对称实现。

#### 这让下一步变得具体

客户端**已经在发包**，问题只是**没人按它期望的格式回**。要给出正确回应，
需要知道它期待什么形状的数据。三条线索按成本排序：

1. **`0xBB15E0` 的成功路径**（`0xBB170C` 之后）就是解析响应的代码。
   反汇编它，能看出它读什么字段、什么长度、如何得到"条目数"；
2. `1e 03 00` 与 `14 02 00 00` 这两个操作码可以在 EXE 里搜索构造它们的代码
   （例如 `mov word ptr [x], 0x031e`），从而找到发送方上下文与对应的预期应答；
3. 若成功路径里出现固定长度（例如期望 8 或 12 字节的头部），可以直接按那个形状
   造一个最小应答试。

**第 1 条最直接**：既然 `0xBB170C` 已经在计数里出现过（echo 打开时 4 次），
说明"收到任意包"就会进这条路径；顺着它往下看，就能知道它如何从包里取出条目数。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.88"),
                         ("HANDOFF-CURRENT.md", "### 15.76")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.88", "### 15.76")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
