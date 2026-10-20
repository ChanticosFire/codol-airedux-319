"""Record round 82: the value written into the container is the port 3074, not an entry count."""
from pathlib import Path

TEXT = """
### 12.97 ★★★ `[容器+0x84]` 里写的是**端口 3074**，不是条目数（2026-10-24 11:3x）

#### 新工具

`tools/probe_reg.py`——`count_calls.py` 的扩展版，cave 里除了 `inc [count]`
还做 `mov [slot], <reg>`，可以观察真实流经某个地址的数据：

```
pushfd / pushad
mov eax, [esp + reg_off]      ; 从 pushad 保存区取出目标寄存器
mov [slot], eax
inc dword [count]
popad / popfd
<重放被替换的指令>
jmp back
```

#### 第一次采样就给出了答案

在 `0xBB1716`（`call dword ptr [0xCA84D4]` 的**下一条**指令）装探针，采样 `eax`：

```
[afterapi] n=0  eax=0x00000000  (0)
[afterapi] n=4  eax=0x11050C02  (285543426)
```

**`0x11050C02` 的低 16 位是 `0x0C02` = 3074。**

而成功路径紧接着执行 `mov word ptr [ebx], ax`——**写进容器的正是 `0x0C02`**。

#### 这与第 59 轮的观测完全对上

§12.73 曾在 `[lobby+0x4D60]` 的 136 字节数组记录里读到 `+0x84 = 0x0C02`，
当时判断它是端口，后来在 §12.80 又因为 `0xB75420` 把参数 2 写进 `+0x84`
而改判为"条目数"。

**现在有了直接证据：两者是同一件事——`+0x84` 装的就是端口 3074。**

`0xCA84D4`（那个动态 thunk）返回的值形态也印证了这一点：
`0x11050C02` 高字是 `0x1105`、低字是 `0x0C02`，很像
"某结构 + 端口"的打包，而不是"条目计数"。

#### 于是 `Add` 拿端口当 count

`Add` 的 `[ebp+0x94]` 对应结构 `+0x84`，所以它读到的 `count = 0x0C02 = 3074`。

**这解释了为什么 `count` 从来不是 0 也不是有效条目数——它是端口号。**

#### 但状态仍停在 3，说明入口就没过

第 81 轮的 cap=200 实验里状态长期是 1、索引一路涨到 125。按"count = 3074 > 0"
应当走成功分支并写 2，实测没有。

唯一自洽的解释：**`Add` 在入口处就被拦住**：

```asm
0xBBA426  cmp dword ptr [ebx + 0x120], 1
0xBBA434  jne 0xBBA635           ; 状态 != 1 -> 直接返回，根本不看 count
```

第 81 轮实验里我们**手动**把状态置 1，理论上应当放行……但同一轮里索引一直在涨
（说明走的是 `count<=0` 分支）。两者仍冲突。

#### 剩下的可能性

1. `[ebp+0x94]` 并非 `+0x84`——参数块起点可能不是 `[ebp+0x10]`，而是别的偏移，
   导致 `Add` 读的是结构里另一个字段（那里确实是 0）；
2. `0xB75420` 写的 `+0x84` 与 `Add` 读的 `+0x84` 不是同一块内存
   （`0xB75420` 的 `ecx` 可能不是 `[ebp-0x768]`）；
3. 探针抓到的 4 次里有 1 次 `eax = 0`，说明**并非每次成功路径都得到 3074**；
   若 `Add` 恰好在那几次 `eax = 0` 之后被调用，`count` 就是 0。

第 3 条很值得注意：`n=0` 时 `eax=0`，`n=4` 时才变成 `0x11050C02`。
**头几次调用返回的是 0**，这与"连接刚建立、尚未收到数据"的状态吻合。
也就是说：**只有收到过真实数据的那些帧才会带出 3074**，其余帧仍然是 0。

#### 下一步

1. 在 `0xB75420` 入口（或 `0xC74053` 之后）采样 `ecx`（容器指针）与 `[ebp+0xC]`
   （写入值），确认写进 `+0x84` 的到底是不是 3074；
2. 同时在 `0xBBA4A5`（`Add` 刚进入、`[ebp+0x94]` 已可读）采样 `[ebp+0x94]`，
   直接看 `Add` 眼里的 `count` 是多少。

第 2 条最关键，成本也低：它是"客户端到底把什么当 count"的直接答案。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.97"),
                         ("HANDOFF-CURRENT.md", "### 15.85")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.97", "### 15.85")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
