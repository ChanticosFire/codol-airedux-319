"""Record round 198: direct disassembly confirms 0xC73FB0 is the socket receive."""
from pathlib import Path

TEXT = """
### 12.208 ★★★ 直接反汇编确认：`0xC73FB0` 确实是 socket 收包（2026-10-27 00:2x）

#### 为什么这一条值得单独记录

**从第 62 轮起，`[vt+0x1C] = 0xC73FB0` 一直被当作"收包函数"使用，
但这个结论此前只是间接推断（vtable 布局 + 行为特征），从未直接读过它的代码。**

**本轮直接反汇编，确认了这个前提。**

#### 代码

```asm
0xC73FB0  push ebp / mov ebp,esp
0xC73FB3  6A FF                 push -1
0xC73FB5  68 EB 2D C9 00        push 0xC92DEB          ; SEH 处理器
0xC73FBA  64 A1 00 00 00 00     mov eax, fs:[0]
0xC73FC0  50                    push eax
0xC73FC1  81 EC 14 01 00 00     sub esp, 0x114
0xC73FC7  A1 40 F2 E3 00        mov eax, [0xE3F240]
0xC73FCC  33 C5                 xor eax, ebp
0xC73FCE  89 45 F0              mov [ebp-0x10], eax
0xC73FD1  53 / 56 / 57           push ebx / esi / edi
0xC73FD4  50                    push eax
0xC73FD5  8D 45 F4              lea eax, [ebp-0xC]
0xC73FD8  64 A3 00 00 00 00     mov fs:[0], eax         ; 建立 SEH
0xC73FDE  8B 45 08              mov eax, [ebp+8]         ; 参数 1
0xC73FE1  8B 7D 0C              mov edi, [ebp+0xC]       ; 参数 2
0xC73FE4  8B F1                 mov esi, ecx             ; this
0xC73FE6  8D 8D E8 FE FF FF     lea ecx, [ebp-0x118]
0xC73FEC  89 85 E4 FE FF FF     mov [ebp-0x11C], eax
0xC73FF2  E8 A9 D0 F3 FF        call 0xBB10A0            ; 构造中间对象
0xC73FF7  8B 4D 10              mov ecx, [ebp+0x10]      ; 参数 3
0xC73FFA  51                    push ecx
0xC73FFB  8B 4E 04              mov ecx, [esi+4]         ; ★ [this+4] —— socket
0xC73FFE  57                    push edi
```

#### 确认的事实

**`0xC73FFB mov ecx, [esi+4]` 取的正是 `[this+4]`。**

**而 §12.196 实测：`p = [serverlist]`，`p+0x04 = 11624`（有效 socket 句柄）。**

**所以 `0xC73FB0` 确实以 `[this+4]` 为 socket 做网络接收——
此前 136 轮的假设被证实。**

#### 这对当前阻塞的意义

**收包函数本身没问题，socket 也有效。所以"读不到我们的字节"
只能来自以下三者之一：**

1. **`sendto` 那一侧的目标地址错**（客户端发出去的包我们没收到）——
   但探测包确实到了服务端，所以至少发是通的；
2. **接收时该 socket 已关闭或未绑定到我们能触达的地址**；
3. **数据确实到了 socket，但在 `0xC73FB0` 内部被丢弃**
   （例如长度校验、来源校验、或协议头校验失败后直接返回 0）。

**第 3 条现在最可疑**，而且**可以用哨兵法直接验证**：
在 `0xC73FB0` 入口读 `[esi+4]`（socket）与三个参数，
在其返回点读 `eax`。**若 `eax` 恒为 0 而 socket 非 0，就是第 3 条。**

#### 给接手者的最后一条建议

**`tools/probe_reg.py` 已支持 `--at <地址> --orig <原始字节> --reg <寄存器> --mem-ebp <偏移>`，
可直接挂在 `0xC740??` 的返回点读 `eax`。**

**注意**：该工具用 `pushfd/pushad` 包裹，**不要挂在 SEH 保护区内**
（`0xC73FB0` 有 `push 0xC92DEB` 帧，需选在其外部的返回点），
否则会破坏异常帧导致崩溃——这是 §12.119 以来的已知问题。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.208"),
                         ("HANDOFF-CURRENT.md", "### 16.96")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.208", "### 16.96")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
