"""Record round 66: environment fixed, both functions confirmed running, and the count writer found."""
from pathlib import Path

TEXT = """
### 12.80 ★★★ 环境修好；虚函数与数据获取都在跑；count 的写入点确认（2026-10-24 02:2x）

#### 启动脚本的问题已修复

第 65 轮的 `Start-Process` 报错（`-ArgumentList` 写了两遍）导致 auth 服务未启动。
新增 `tools/run_verified.ps1`，改用参数数组，并**在测量前自检环境**：

```
[3/5] checking listeners on 3074 / 4175 / 4174
      TCP 127.0.0.1:3074  LISTENING
      TCP 127.0.0.1:4174  LISTENING
      TCP 127.0.0.1:4175  LISTENING
      UDP 127.0.0.1:3074
[5/5] waiting for login to complete (up to 45 s)
      login verified after 20 s
```

脚本会检查 `lsg.jsonl` 中是否出现 `client_frame_verified`，只有出现才认为登录真的走完。

#### 两个函数都在正常运行

在干净环境上分别计数：

```
[vfn]   0xC73FB0（虚函数入口）   calls = 30, 60, 90, 120, 150, 179, 209
[fetch] 0xBB15E0（数据获取）     calls = 30, 59, 89, 119, 149, 179, 209
```

**两者都约 21 次/秒。** 所以第 65 轮那个"0 次"确实是环境故障，不是真实行为。

#### 找到了写 count 的函数

`0xB75420`（虚函数在 `0xC74053` 调用）：

```asm
0xB75420  push ebp / mov ebp,esp
0xB75423  mov eax, [ebp + 8]
0xB75427  push eax
0xB75428  mov esi, ecx
0xB7542A  call 0xB76F50                 ; 复制数据到容器
0xB7542F  mov cx, word ptr [ebp + 0xc]  ; ★ 参数 2
0xB75433  mov word ptr [esi + 0x84], cx ; ★★ 直接写进容器 +0x84
0xB7543C  ret 8
```

**`0xB75420` 的第二个参数就是条目数，一字不差地写进 `+0x84`。**

而 `0xC74053` 传给它的参数 2 是 `[ebp-0x120]`——那正是 `0xBB15E0` 的输出参数
（`0xC74005 push edx` 传进去的）。

**所以链条是**：

```
0xBB15E0(handle, out_count, buf, size)   -> 把条目数写进 out_count
   ↓ 0xC74041 mov edx,[ebp-0x120]        （读回 out_count）
   ↓ 0xC7404B push edx
   ↓ 0xC74053 call 0xB75420
0xB75420: [container+0x84] = out_count
   ↓
Add 读到 count = container+0x84 = 0
```

**`count = 0` 的直接含义是：`0xBB15E0` 没有写出任何条目数（或写出 0）。**

#### 需要修正 §12.73 的一个判断

第 59 轮从数组条目转储里看到 `+0x84` 是 `0x0C02`（3074），据此判断 `+0x84` 是端口。
现在确认 `+0x84` 在**容器**里是**条目数**。

两者不冲突：那条 136 字节数组记录与这个 1288 字节容器是**不同结构**，
偏移相同纯属巧合。`0xB75470` 里比较 `+0x84` 的那个判定，也应当重新理解为
"比较条目数"而不是"比较端口"——不过这已不影响主线。

#### `0xBB15E0` 调用的是外部接口

它主体（`0xBB1620` 之后）执行：

```asm
0xBB1635  mov dword ptr [ebp - 0x18], 0x10
0xBB163C  call dword ptr [0xCA851C]
0xBB1642  mov esi, eax
0xBB1646  jns 0xBB170C                  ; 返回 >= 0 -> 成功
0xBB164C  call dword ptr [0xCA853C]     ; 失败时取错误码
0xBB1652  lea ecx, [eax - 0x2714]
0xBB1658  cmp ecx, 0x3d
0xBB165B  ja 0xBB16F8                   ; 超出范围 -> 另一个错误分支
0xBB1661  movzx ecx, byte ptr [ecx + 0xBB1768]
0xBB1668  jmp dword ptr [ecx*4 + 0xBB1750]   ; 跳表分派
```

实测指针值：

```
[0xCA851C] = 0x119C6A2F
[0xCA853C] = 0x76BD9EF0      （系统 DLL 区间）
[0xCA8128] = 0x119C6A7E
```

`0x119C6A2F` 既不在 EXE（`0x00Cxxxxx`）也不在常见的 `0x7xxxxxxx` 系统 DLL 区间，
说明它是某个被加载模块的地址（WOW64 下 DLL 基址可能落在 `0x1xxxxxxx`）。

#### 下一步

1. **列出进程模块，确定 `0x119C6A2F` 属于哪个 DLL、对应哪个导出函数**。
   这能直接说明 `0xBB15E0` 到底在调用什么（网络查询？文件读取？注册表？）；
2. 给 `0xBB170C`（成功路径）与 `0xBB16F8`（错误路径）各装计数器，
   判断它每次调用走的是成功还是失败；
3. 若走成功路径而条目数仍为 0，说明接口本身返回"0 条记录"——那时问题
   就在**数据源**（服务端应答），而不在客户端逻辑。

第 1 条信息量最大且成本低。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.80"),
                         ("HANDOFF-CURRENT.md", "### 15.68")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.80", "### 15.68")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
