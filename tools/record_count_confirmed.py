"""Record round 84: confirmed that Add's count is [ebp+0x94] and it holds -2."""
from pathlib import Path

TEXT = """
### 12.99 确认 `Add` 的 count 就是 `[ebp+0x94]`，其值为 `-2`（2026-10-24 12:5x）

#### 工具扩展

`tools/probe_reg.py` 增加 `--mem-ebp <hex>`：cave 里除了采样寄存器，还会

```
mov eax, [esp+8]        ; pushad 保存区里的 ebp
add eax, offset
mov eax, [eax]
mov [slot+4], eax
```

这样一次挂载就能同时看到"寄存器"和"该帧里的某个局部变量"。

#### 采样结果

在 `0xBBA440`（`test edi,edi`）同时采样 `edi` 与 `[ebp+0x94]`：

```
[both] n=0  edi=0x00000000  [ebp+0x94]=0x00000000  (0)
[both] n=1  edi=0xfffffffe  [ebp+0x94]=0xfffffffe  (-2)
```

**两个值逐次完全相同。**

这确认了两件事：

1. `Add` 的 `[ebp+0x94]` 确实就是它用的 count（`mov edi,[ebp+0x94]` 之后 `edi` 等于它）；
2. 该值是 **`-2`**，即 `0xBB166F`（`WSAEWOULDBLOCK` 分支）的返回值。

§12.98 的推断（参数块错位导致 `[ebp+0x94]` 指向结构之外、实际取到
`[ebp-0x548]`）由此得到直接验证。

#### 于是问题精确到一个变量

```
Add 的 count = [ebp+0x94] = 内容 of [ebp-0x548]
```

而 `[ebp-0x548]` 是 pump 在 `0xBAE24F lea ecx, [ebp-0x548]` 之后推给虚函数的
**第 2 个参数**（`0xBAE255 push ecx`）。虚函数把它继续传给 `0xBB15E0`
（作为 `&[ebp-0x118]` 还是 `&[ebp-0x120]` 需再核对），而失败帧里它被写成 `-2`。

**所以要让 `Add` 走成功分支，必须让 `[ebp-0x548]` 变成正数。**

#### 下一步：找 `[ebp-0x548]` 的写入点

在 `0xBAE000`–`0xBAF000` 内搜 `-0x548` 的 disp32（`B8 FA FF FF`），
列出所有 `lea`/`mov` 引用，定位：

- 谁在调用前把它初始化；
- 虚函数返回后是否有人把它改写；
- 失败帧里 `-2` 是从哪条路径写进去的（很可能是 `0xBB166F` 的返回值经
  `mov [edi], edx` 或类似途径落地）。

**`0xBB170C` 的成功路径里就有 `mov dword ptr [edi], edx`**，而 `edi` 正是
`[ebp+0xC]`——如果对端地址恰好是 `[ebp-0x548]`，那 `-2` 就是从别处带过来的；
若成功路径写入的是别的值，那说明失败帧根本没走到那里。

**关键对照**：成功帧里 `[ebp+0x94]` 是多少。本轮采样只抓到 2 次（n=0 与 n=1），
且第二次之后客户端退出了。下一轮应当先稳定环境、延长采样窗口，抓够几十次
成功帧的值分布，再判断"是否可能为正"。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.99"),
                         ("HANDOFF-CURRENT.md", "### 15.87")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.99", "### 15.87")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
