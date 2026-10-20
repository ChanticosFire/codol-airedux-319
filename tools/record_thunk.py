"""Record round 74: the response-parsing API is a dynamic thunk, so it cannot be resolved statically."""
from pathlib import Path

TEXT = """
### 12.89 成功路径的解析只做两件事；其 API 是动态 thunk（2026-10-24 07:2x）

#### 成功路径的核心只有 5 条有效指令

```asm
0xBB170C  mov ecx, dword ptr [ebp - 0x12]    ; 某个 word 参数
0xBB170F  push ecx
0xBB1710  call dword ptr [0xCA84D4]          ; ★ 一个 API
0xBB1716  mov edx, dword ptr [ebp - 0x10]
0xBB1719  mov ecx, dword ptr [ebp - 4]
0xBB171C  mov word ptr [ebx], ax             ; ★ 把 AX 写到 [ebx]
0xBB171F  mov dword ptr [edi], edx           ; ★ 把 EDX 写到 [edi]
0xBB1721  lea eax, [esi + 0x1c]
0xBB1725  add dword ptr [0xE85CA0], eax      ; 累计统计
0xBB172E  adc dword ptr [0xE85CA4], edx
0xBB1734  add dword ptr [0xE85CB0], 1        ; 计数 +1
0xBB174B  ret                                ; 返回 eax = esi
```

**它对收到的数据只做"取一个 word、调一次 API、把结果写两个输出参数"**，
没有循环、没有逐条解析。

`[0xE85CA0]` / `[0xE85CB0]` 是全局统计量（累加 + 计数），说明这里统计的是
"某类消息的条数与字节数"，而不是构造服务器列表。

#### 那个 API 是动态 thunk，无法静态解析

```
[0xCA84D4] = 0x1190EBCF   bytes = e9 32 55 8c 57   -> jmp 0x691D4106
[0xCA851C] = 0x1190F530   bytes = e9 e9 4b 8c 57   -> jmp 0x691D411E
[0xCA8128] = 0x1190D941   bytes = e9 9d c2 8b 57   -> jmp 0x691C9BE3
```

三点：

1. 三个指针都落在 `0x1190xxxx` 附近，**同一次运行内相邻**；
2. 目标地址是 `0x691xxxxx`，属于系统 DLL 区；
3. **上一次运行时这些指针是 `0x11A20C9D` / `0x11A22854` / `0x11A20CB6`** ——
   **每次运行地址都不同**。

**所以它们是运行时生成的跳转桩（thunk），可能是腾讯的 `TenProxy.dll` /
`TerSafe.dll` 做的 API hook，也可能是延迟绑定桩。** 无论哪种，都**无法通过
静态反汇编确定原始 API**，`modules.py` 也枚举不到承载它们的模块。

（对照：`[0xCA853C] = WS2_32 + 0x19EF0 = WSAGetLastError`，那个是**静态**
导入指针，能正常解析。差别明显。）

#### 这轮的净结果

- **成功路径已看清**：只做"取 word → 调 API → 写两个输出"，不解析列表结构；
- **那条 API 无法静态定位**：动态 thunk，且每次运行地址不同；
- **因此"从代码推断响应格式"这条路成本变高**。

#### 换个更省力的方向

既然客户端每 10 秒各发 6 次 `1e 03 00` 和 `14 02 00 00`，而我们把任何字节回给它
都能进入成功路径（echo 实验已证明），那么**不必先知道精确格式**：

1. **用一个可参数化的应答器**：让 `lobby_udp` 支持 `LOBBY_UDP_REPLY=<hex>`，
   把固定字节序列回给客户端；
2. **枚举候选形状**：按"可能的响应"逐个试
   （回显 + 改写首字节、`1e 03 00` 的对称应答 `1e 83 00`、带 2 字节计数的形式等），
   每轮只改一个字节，观察 `count` 是否变成非零、`0xBB170C` 是否进入；
3. 由于状态机一旦写 3 就永久短路，**每次试验都必须重启客户端**，
   这一点 `run_verified.ps1` 已经做到。

**这比继续解混淆 thunk 更划算**：客户端只要求"某条 UDP 消息里有一个 word 能转成
非零条目数"，而这条路可以用少量试验直接搜索。

#### 下轮的具体动作

给 `lobby_udp.py` 加 `LOBBY_UDP_REPLY`（十六进制字符串），收到任意 UDP 包时回它；
然后在一次运行内观察 `0xBB170C` 计数与 `obj1[0x120]`，逐个试候选应答。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.89"),
                         ("HANDOFF-CURRENT.md", "### 15.77")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.89", "### 15.77")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
