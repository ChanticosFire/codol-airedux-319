"""Record round 88: 0xB753C0 is stdcall, so Add's count is the virtual function's return value."""
from pathlib import Path

TEXT = """
### 12.103 ★★★ `0xB753C0` 是 stdcall；`Add` 的 count 就是虚函数的返回值（2026-10-24 14:5x）

#### 调用约定已确认

扫描 `0xB753C0` 的结尾：

```
0xB753E2  5d           pop ebp
0xB753E3  c2 04 00     ret 4        ← ★ stdcall，弹 4 字节
```

**`ret 4` 说明它由被调方弹参数**，`call 0xB753C0` 返回后 `esp` 已经回升 4 字节。

#### 重读调用序列（这次逐条对齐）

```asm
0xBAE24E  push esi                    ; ① 虚函数的返回值
0xBAE24F  lea ecx, [ebp - 0x548]
0xBAE255  push ecx                    ; ② &[ebp-0x548]
0xBAE256  sub esp, 0x88               ; ③ 136 字节结构
0xBAE262  mov ecx, esp
0xBAE26A  push edx                    ; ④ 0xB753C0 的源（ret 4 会弹掉）
0xBAE26B  call 0xB753C0
0xBAE276  call 0xBBA3F0               ; Add，push 返回地址
```

`0xB753C0` 返回后 `esp` 回到 ③ 的起点。因此 `Add` 帧里的布局是：

| 偏移 | 内容 |
|---|---|
| `[ebp+0x04]` | 返回地址 |
| `[ebp+0x08]` .. `[ebp+0x8F]` | **③ 的 136 字节结构** |
| `[ebp+0x90]` | **② 的内容 = `[ebp-0x548]`** |
| `[ebp+0x94]` | **① 的 `esi` = 虚函数返回值** |

#### 于是两个参数的真实含义

| `Add` 的偏移 | 之前的理解 | **实际内容** |
|---|---|---|
| `[ebp+0x90]` | 源数组指针 | **`[ebp-0x548]` = `127.0.0.1`**（§12.86 采到的 `edx` 就写在这里） |
| `[ebp+0x94]` | count | **`esi` = 虚函数的返回值** |

**§12.98/§12.99 的"参数块错位到 `[ebp-0x548]`"是错的**——错位存在，但落点相差一格：
`[ebp+0x90]` 才是 `[ebp-0x548]`，`[ebp+0x94]` 是 `esi`。

这完美解释了本轮与上轮的全部观测：

- §12.84 采到 `[ebp+0x94] = 0xFFFFFFFE`（-2）——**因为 `esi` 就是 -2**；
- §12.86 采到 `0xBB171F` 写入 `0x0100007F`——**那写的是 `[ebp-0x548]`，
  即 `Add` 的 `[ebp+0x90]`，不是 count**；
- 上轮把容量抬到 200、窗口撑到 40 秒仍无变化——**因为 count 取决于虚函数的
  返回值，而不是任何缓冲内容**。

#### 真正的因果链（最终形态）

```
pump 每帧:
  ① 虚函数 eax(lobby+0xC -> vt+0x1C)  = 0xC73FB0
       内部 0xBB15E0 收包
         成功 -> 返回 esi(>=0)
         无数据 -> 返回 -2 (WSAEWOULDBLOCK)
  ② esi = 返回值
  ③ Add(obj1, [ebp-0x548], esi, 137 字节结构)
       入口: cmp [obj1+0x120], 1 / jne -> 返回
       count = [ebp+0x94] = esi
       count <= 0 -> 跳过写 2, 推进索引
       count >  0 -> 写 2 并立即返回
```

**所以 `Add` 的 count 就是"这次收包成功与否 + 收到的字节数"这类返回值。**

#### 这改变了修复方向

- 之前的"改应答内容/频率/容量"全部作用在错误变量上；
- **正确变量是 `esi`，即 `0xBB15E0` 的返回值**；
- 而 `0xBB15E0` 成功路径返回 `esi`，`esi` 来自 `0xBB1642 mov esi, eax`，
  `eax` 是 `call [0xCA84D4]` 的结果——§12.97 采到过 `0x11050C02`（正数）。

**所以：只要有一次 `0xCA84D4` 返回正数、且此时状态仍是 1，`Add` 就会写 2。**

#### 下一步

1. **在 `0xBBA440` 同时采样 `esi` 与 `[ebp+0x94]`**，验证两者相等（一条命令即可定论）；
2. 若相等，则**追踪 `0xCA84D4` 何时返回正数**，并确保此时 `obj1[0x120]` 仍是 1；
3. 关键洞察：`0xBB15E0` 的返回是 `esi`，而 `0xBB1646 jns 0xBB170C` 只看 `esi` 的符号。
   若某次 `esi` 为正而状态已是 3，那次就浪费了；需要让"第一次正返回值"
   发生在状态变 3 之前——**窗口问题依然存在，但变量已经找对了**。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.103"),
                         ("HANDOFF-CURRENT.md", "### 15.91")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.103", "### 15.91")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
