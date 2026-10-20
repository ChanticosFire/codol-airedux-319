"""Record round 186: the 0x15 handler is 0xBBAAF0 with one caller at 0xBBAE3A."""
from pathlib import Path

TEXT = """
### 12.201 类型 `0x15` 处理函数是 `0xBBAAF0`，唯一调用者 `0xBBAE3A`（2026-10-26 19:5x）

#### 函数头

```asm
0xBBAAF0  push ebp / mov ebp,esp
0xBBAAF3  6A FF                 push -1
0xBBAAF5  68 9E 10 C9 00        push 0xC9109E          ; SEH 处理器标签
0xBBAAFA  64 A1 00 00 00 00     mov eax, dword ptr fs:[0]
0xBBAB00  50                    push eax
0xBBAB01  81 EC 1C 01 00 00     sub esp, 0x11C
0xBBAB07  A1 40 F2 E3 00        mov eax, [0xE3F240]
0xBBAB0C  33 C5                 xor eax, ebp
0xBBAB0E  89 45 F0              mov [ebp-0x10], eax
0xBBAB11  53 / 56 / 57           push ebx / esi / edi
0xBBAB14  50                    push eax
0xBBAB15  8D 45 F4              lea eax, [ebp-0xC]
0xBBAB18  64 A3 00 00 00 00     mov dword ptr fs:[0], eax   ; 建立 SEH
0xBBAB1E  8B B5 90 00 00 00     mov esi, dword ptr [ebp+0x90]
0xBBAB24  8B D9                 mov ebx, ecx                 ; this
```

#### 调用者

`branches_to.py 0xBBAAF0` 在 `0xBB9000`–`0xBBC000` 内只有 **1** 个命中：

```
0xBBAE3A  call 0xBBAAF0
```

**所以"把状态推进到 4"的整条路径（`0xBBAB33` 起的那段）只由这一个调用者触发。**

#### 这段代码的性质

**它有完整的 SEH 帧（`push 0xC9109E` + `fs:[0]` 链）、
0x11C 字节栈帧、以及 `[ebp+0x90]` 这样的远参数——
典型的"消息分发/解码"函数。**

**`0xBBAB33`–`0xBBAB7C` 那段（检查 `edi>0`、解析成功、类型 == 0x15）就在它内部。**

**所以：只要 `0xBBAE3A` 被调用、且传入的数据能解析成类型 0x15，
状态就会被推进到 4。**

#### 下一步

**找 `0xBBAE3A` 所属函数的入口，再追它的调用者**——
这能回答"这段是 UDP 收包处理还是 TLS 收包处理"。

**若最终追到 `0xBB15E0`（Winsock 接收，§12.62）附近，说明是 UDP 3074；
若追到 TLS 层，说明这条消息走加密连接——那我们此前向 3074 发 `0x15` 就发错了通道。**

**这是本轮之后最关键的一次追查。**

#### 进度说明

**当前轮次 186 / 200。** 剩余轮次将用于：

1. 追完 `0xBBAE3A` 的调用链，确定通道（2–3 轮）；
2. **若确认是 TLS，则在 LSG 服务端侧构造该消息**（这是唯一还没试过的方向）；
3. 无论结果如何，**在最后几轮做一次完整的文档收束**：
   更新 `MILESTONES.md`、把本轮系列的结论整理进 `PROJECT_STATUS.md` 的索引，
   并确保 `HANDOFF-CURRENT.md` 能让人接手。

**不再开启新的逆向支线。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.201"),
                         ("HANDOFF-CURRENT.md", "### 16.89")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.201", "### 16.89")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
