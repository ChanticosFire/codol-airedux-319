"""Record round 177: the socket handle is zero, so sendto fails regardless of payload."""
from pathlib import Path

TEXT = """
### 12.192 ★★★★ 决定性的一个 dword：socket 句柄是 0，从未创建（2026-10-26 15:2x）

#### 实测

```
t= 18.15  1A0=   1  +78=0x0  +7c=0x0  +80=0x0  +84=0x2  +88=0xc02  +8c=0xff00ff00  +90=0x0  1F4=1
t= 21.22  1A0=   5  +78=0x0  +7c=0x0  +80=0x0  +84=0x2  +88=0xc02  +8c=0xff00ff00  +90=0x0  1F4=1

udp_reply count: 6
```

#### 字段含义全部对上了

| 偏移 | 值 | 含义 |
|---|---|---|
| `+0x84` | `0x2` | 类型/标识（§12.190 已确认） |
| **`+0x88`** | **`0xC02`** | **端口 3074**（大端存储） |
| `+0x8C` | `0xFF00FF00` | 地址字段 |

**所以目的地址与端口都是齐全的。发送失败与它们无关。**

#### 而 socket 句柄是 0

§12.176 的发送链：

```asm
0xC73F74  8B 43 04              mov eax, dword [ebx+4]      ; ★ 取 socket
0xC73F77  52                    push edx                     ; 端口/类型
0xC73F78  81 EC 84 00 00 00     sub esp, 0x84
0xC73F86  F3 A5                 rep movsd                    ; 复制 132 字节
0xC73F88  E8 93 D4 F3 FF        call 0xBB1420                ; 发送
```

**`ebx` 是 `0xC73F30` 的 `this`（`0xC73F52 mov ebx,ecx`），
而它以 `[ebx+4]` 作为 socket 传给 `0xBB1420`。**

**`ebx` 来自 `0xBBA7C0 mov ecx,[esi]`，即 `0xBBA760` 的 `this`——
也就是 lobby 对象本身。**

**所以 `[lobby+4]` 就是 socket 句柄。**

**§12.158 记录过 `lobby[0x04] = 0x00000000`——它是 0。**

#### 这就完全解释了状态 5

```
socket = 0（不是 INVALID_SOCKET 的 -1，所以 0xBB143B 的检查放行）
  -> 0xBB1420 继续构造 sockaddr（family=2、addr、port 都正常）
  -> sendto(0, ...)  ->  WSAENOTSOCK  ->  返回 -1
  -> 0xC73F30 返回 -1
  -> 0xBBA7D4  jle 成立  ->  失败
  -> 0xBBA7AC 写入状态 5
```

**注意 `0xBB143B` 只挡 `-1`，不挡 `0`——所以一个未初始化的 0 会一路走到 `sendto` 才失败。
这与观测完全一致。**

#### 根因终于落到一个具体的东西上

**客户端的 lobby socket 从未创建（`[lobby+4]` 恒为 0）。**

**所有下游现象——状态码停在 1 或跳到 5、`1F4` 恒为 1、FE 梯不动、
客户端停在代号页或模糊过渡画面——都源自此：**

**没有 socket，就无法发送，就无法完成列表请求的往返，就无法进入大厅。**

#### 下一步

**找出 `[lobby+4]` 的写入点**——即创建 socket 的位置。

**用 `find_offset.py` 搜 `+4` 不可行（太常见），改用别的办法：
搜索 `WSASocket` / `socket` 的导入表调用点，
或者搜索把某个 API 返回值写入 `[reg+4]` 的指令。**

**更实际的做法**：在运行中观察 `[lobby+4]` 是否曾短暂非零——
如果从未非零，说明创建代码从未执行；若曾非零后归零，则是被关闭了。

**这与"服务端只回声探测包"的发现能对上：客户端用另一个 socket 发探测包（那个是通的），
但 lobby 的业务 socket 从未建立。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.192"),
                         ("HANDOFF-CURRENT.md", "### 16.80")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.192", "### 16.80")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
