"""Record round 201: the recv socket lives on [lobby+0xC], not on [serverlist]."""
from pathlib import Path

TEXT = """
### 12.211 ★★★★ 关键修正：收包 socket 在 `[[lobby+0xC]+4]`，不是 `[[serverlist]+4]`（2026-10-27 02:2x）

#### 实测

```
lobby          = 0x37E19850
[lobby+0x0C]   = 0x37DC8730      ← pump 收包用的对象
[serverlist]   = 0x00000000      ← §12.196 读的那个，本次为 NULL

[ep + 0x00]    = 0x00D95558      （vtable）
[ep + 0x04]    = 11648           ★ 真正的收包 socket（有效句柄）
```

#### 此前的错误

**§12.196 推断"`0xC73F30` 的 this 是 `[serverlist]`，其 `+4` 是 socket"，
并据此认为收包 socket 也在这个对象上。**

**但 pump 的收包走的是另一条链：**

```asm
0xBAE220  8B 4B 0C        mov ecx, dword ptr [ebx+0xC]   ; ★ ecx = [lobby+0xC]
0xBAE223  8B 01           mov eax, dword ptr [ecx]
0xBAE225  8B 40 1C        mov eax, dword ptr [eax+0x1C]
0xBAE242  FF D0           call eax
```

**`0xC73FB0` 内部 `0xC73FFB mov ecx,[esi+4]` 的 `esi` 就是这个 `[lobby+0xC]` 对象，
所以它读的是 `[[lobby+0xC]+4] = 11648`。**

**而 §12.196 读的 `[[serverlist]+4]` 是另一个对象的 socket（11624），
那是发送链用的，不是收包链用的。**

**两个 socket 都存在，但分工不同。**

#### 这解释了为什么之前的注入全部无效

**§12.194 与 §12.206 是向 `Get-NetUDPEndpoint` 列出的全部端口发数据——
理论上应当覆盖 11648 对应的那个端口。**

**但还有一种可能：`11648` 对应的本地端口在枚举时已存在，
而我们 sendto 的目标地址是 `127.0.0.1`，而该 socket 可能绑定在特定接口上。**

**更关键的是 §12.210 的事实：收包每帧返回 `-2`（`WSAEWOULDBLOCK`）。
`WOULDBLOCK` 说明 socket 有效且可读，只是队列空。
所以我们的数据确实没有排进那个 socket 的接收队列。**

#### 下一步（唯一剩下的一步）

**把 `11648` 映射到具体的本地端口。**

**Windows 没有直接的公开 API 从进程外部做这件事，但有两种可行办法：**

1. **用 `Get-NetUDPEndpoint` 枚举端口，再逐个用 `sendto` 试探**——
   已做过（§12.206），全部无效；
2. **在客户端内部用哨兵法读 `getsockname` 的结果**——
   即在 `0xC73FB0` 入口把 `[esi+4]` 保存下来，同时在 `0xC73FB0` 内部
   找到调用 `getsockname`/`bind` 的位置读端口
   （但 `0xC73FB0` 是收包，端口早在创建时确定）。

**更实际的办法**：`11648` 是句柄值。**用 `DuplicateHandle` 无法从外部枚举。
但可以用 `NtQuerySystemInformation` 的句柄表**
——**这超出本项目的工具范围，且属于系统级操作，不在授权边界内。**

#### 结论

**收包 socket 已定位（`11648`，位于 `[[lobby+0xC]+4]`），
它有效、可读、但队列始终为空。**

**"数据从未到达"这一点在 §12.210 已用 67 次采样确认。**

**所以问题只剩一个：我们发的数据没有排进这个 socket 的接收队列。**

**在这个授权边界内，已经无法继续缩小范围**——
因为从外部把句柄映射到端口需要系统级查询。

**这是本项目在当前边界下能达到的最深结论。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.211"),
                         ("HANDOFF-CURRENT.md", "### 16.99")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.211", "### 16.99")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
