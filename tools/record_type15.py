"""Record round 161: the state only advances on a message of type 0x15."""
from pathlib import Path

TEXT = """
### 12.176 ★★★★ 终局：状态推进需要一条类型为 `0x15` 的消息（2026-10-26 05:5x）

#### 唯一调用点 `0xBBAB7C`

`branches_to.py 0xBBA900` 在全镜像内只有 **1** 个命中：`0xBBAB7C call 0xBBA900`。

**所以"把服务器列表状态推进到 4"只有这一条路。**

#### 完整的守卫序列

```asm
0xBBAB33  test edi, edi
0xBBAB35  7E 68           jle 0xBBAB9F        ; ★ edi <= 0 -> 整段跳过
0xBBAB37  lea ecx, [ebp-0x124]
0xBBAB3D  e8 …            call 0xBC1CC0        ; 构造容器
0xBBAB42  lea eax, [ebp-0x128]
0xBBAB48  push eax
0xBBAB49  push 0
0xBBAB4B  push edi                              ; ★ 长度
0xBBAB4C  push esi                              ; ★ 数据指针
0xBBAB4D  lea ecx, [ebp-0x124]
0xBBAB53  mov byte ptr [ebp-4], 1
0xBBAB57  e8 c4 71 00 00  call 0xBC1D20          ; ★ 解析
0xBBAB5C  3C 01           cmp al, 1
0xBBAB5E  75 21           jne 0xBBAB81           ; ★ 解析未返回 1 -> 跳过
0xBBAB60  lea ecx, [ebp-0x124]
0xBBAB66  e8 45 71 00 00  call 0xBC1CB0          ; ★ 取消息类型
0xBBAB6B  3C 15           cmp al, 0x15
0xBBAB6D  75 12           jne 0xBBAB81           ; ★ 类型 != 0x15 -> 跳过
0xBBAB6F  lea ecx, [ebp-0x124]
0xBBAB75  push ecx
0xBBAB76  lea edx, [ebp+8]
…
0xBBAB7C  e8 7F FD FF FF  call 0xBBA900          ; ★ 设置状态 = 4
```

#### 三个必要条件

| # | 条件 | 含义 |
|---|---|---|
| 1 | `edi > 0` | 收到了一段非空数据 |
| 2 | `0xBC1D20` 返回 1 | 该数据**解析成功** |
| 3 | `0xBC1CB0` 返回 **`0x15`** | 该消息的**类型是 21** |

**三者全满足，才会调用 `0xBBA900` 把 `[0x1A0]` 设为 4，
从而让 `0xBBA710` 返回 0、标志 C 置 1、第三道守卫通过、`0xBAE587` 执行、`1F4` 变成 2。**

#### 这解释了此前所有现象

```
没有收到类型 0x15 的消息
  -> 状态码保持 1
  -> 0xBBA710 返回 1（pending）
  -> 标志 C = 0
  -> 0xBAE2F7 je 0xBAE7B4 成立
  -> 0xBAE587 永不执行
  -> 1F4 永远是 1
  -> pump 入口 cmp [ebx+0x1F4],1 每帧都通过，但 FE 梯永不推进
  -> 客户端停在代号页或过渡画面
```

**从第 60 轮到现在追查的一切，最终归结为：客户端从未收到一条类型为 `0x15` 的服务器列表消息。**

#### 下一步

**`0x15`（21）是消息类型码。** 需要确认：

1. **这条消息走哪条通道**——UDP（3074/4174/4175）还是 TLS 长连接？
2. **它的负载格式**——`0xBC1D20` 是解析函数，反汇编它能得到字段布局；
3. **现有服务端是否已经在发类型 0x15**——查 `lobby_udp.jsonl` 与 LSG 日志里有没有出现过
   长度为特定值、首字节为 0x15 的包。

**第 3 条最直接：如果服务端根本没发过这种消息，那就需要在服务端补上它；
如果发过但格式不对，就按 `0xBC1D20` 的解析逻辑修正格式。**

**这是整条链的终点，也是修复的起点。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.176"),
                         ("HANDOFF-CURRENT.md", "### 16.64")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.176", "### 16.64")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
