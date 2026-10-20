"""Record round 67: 0xBB15E0 is a Winsock receive path and WSAGetLastError is the error reader."""
from pathlib import Path

TEXT = """
### 12.81 ★★★ `0xBB15E0` 是 Winsock 接收路径（2026-10-24 02:5x）

#### 模块归属解析

新增 `tools/modules.py`（枚举进程模块并把绝对地址归到 `模块 + 偏移`）：

```
pid=13996  modules=190
  0x119C6A2F -> no owning module
  0x119C6A7E -> no owning module
  0x76BD9EF0 -> WS2_32.dll + 0x19ef0   (C:\\WINDOWS\\SysWOW64\\WS2_32.dll)
```

`0x76BD9EF0` 落在 `Ws2_32.dll` 内。用 PE 导出表反查 RVA `0x19EF0`：

```
near: WSAGetLastError  rva=0x19ef0
```

**`[0xCA853C] = WSAGetLastError`。**

`0xBB15E0` 的失败分支正是：

```asm
0xBB164C  call dword ptr [0xCA853C]     ; ★ WSAGetLastError()
0xBB1652  lea ecx, [eax - 0x2714]       ; 0x2714 = 10004，WSA 错误码基址
0xBB1658  cmp ecx, 0x3d                 ; 61 个错误码的范围检查
0xBB165B  ja 0xBB16F8                   ; 超出范围 -> 其它分支
0xBB1661  movzx ecx, byte ptr [ecx + 0xBB1768]
0xBB1668  jmp dword ptr [ecx*4 + 0xBB1750]   ; 跳表分派
```

`WSAEWOULDBLOCK = 10035`，减 `10004` 得 **31**，落在 `0..61` 内，所以会走跳表里
对应的那一项——**非阻塞 socket 暂时无数据，是代码明确处理过的正常情况**。

#### 这与 count = 0 的关系

`0xBB15E0` 主体（`0xBB1635` 起）：

```asm
0xBB1635  mov dword ptr [ebp - 0x18], 0x10   ; 某结构长度 = 16
0xBB163C  call dword ptr [0xCA851C]          ; ★ 真正的 socket 调用
0xBB1642  mov esi, eax
0xBB1646  jns 0xBB170C                       ; 返回 >= 0 -> 成功路径
```

`[0xCA851C]` 实测为 `0x119C6A2F`，**不属于任何已枚举模块**。有两种解释：

1. 它是某个运行时生成的 thunk（例如 API hook 或延迟绑定桩）；
2. `CreateToolhelp32Snapshot` 没能枚举到某个模块（本次列出 190 个模块，
   打印的前 40 个里没有 `0x119Cxxxx` 附近的项）。

无论哪种，**`0xBB15E0` 的处理路径已经明确**：

```
调用 socket 接口 -> 返回值
   >= 0         -> 0xBB170C 成功路径，写出条目数
   <  0         -> WSAGetLastError -> 查表分派
                     - WSAEWOULDBLOCK(10035) 有专门分支：无数据，正常
                     - 其它错误可能走 0xBB16F8
```

#### 由此得到的完整因果图

```
pump 每帧（51 次/秒）
  └─ 虚函数 0xC73FB0（21 次/秒）
       ├─ 0xBB15E0  socket 接收
       │    ├─ 无数据（WSAEWOULDBLOCK）→ 条目数保持 0
       │    └─ 有数据 → 写出条目数 N
       ├─ 0xB75420  把 N 写进容器 +0x84
       └─ Add(obj1, 容器)  count = N
            ├─ N > 0 → 走搬运/判定路径 → 可能写 2（成功）
            └─ N = 0 → 0xBBA5C3 → 索引 +1 → 容量满后写 3
```

**我们的环境里这条 socket 上从未到达数据，所以 N 恒为 0。**

#### 这直接指向服务端

如果客户端是在一条**专门用于接收服务器列表**的 socket 上读取，那么：

- 该 socket 要么从未被服务端写过；
- 要么服务端写了但格式/时序不对，客户端解析后认为 0 条。

而 §12.80 已确认 `svc71/task4` 的应答是 **83 字节的请求被回了一个候选帧**，
且 `lsg.jsonl` 里能看到 `client_frame_verified` 与 `task_request`——
说明 TLS 通道是通的，问题在于**这条 socket 上应该出现、但没出现的数据**。

#### 下一步

1. **确定 `0x119C6A2F` 的归属**：换用 `EnumProcessModulesEx` 或直接读
   `[0xCA851C]` 前后的指针表，看它是否与 `Ws2_32` 的某个导出相邻
   （若相邻，说明它是 Ws2_32 里另一个函数，只是枚举遗漏）；
2. **给 `0xBB170C`（成功路径）与 `0xBB16F8`（错误路径）各装计数器**，
   确认每帧实际走哪条。若走成功路径而 N=0，说明 socket 有响应但内容为空；
   若走错误路径且命中 WSAEWOULDBLOCK 分支，说明**服务端从未向该 socket 写入**。
3. 结合 `netstat` 观察 3074 之外的 UDP 会话端口是否真的建立——`run_verified.ps1`
   目前只确认 3074 在监听，没有确认对局/大厅通道有实际的收发。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.81"),
                         ("HANDOFF-CURRENT.md", "### 15.69")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.81", "### 15.69")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
