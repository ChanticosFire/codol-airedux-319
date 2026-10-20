"""Record round 107: 0xBBA1E0 is a pure getter, so the overwriter hypothesis is eliminated."""
from pathlib import Path

TEXT = """
### 12.122 `0xBBA1E0` 是纯 getter；"Add 之后被覆盖"这个假设也被排除（2026-10-25 00:5x）

#### 反汇编结果

```asm
0xBBA1C0  mov ecx, dword ptr [ebp - 4]
0xBBA1C3  xor eax, eax
0xBBA1C5  pop edi
0xBBA1C6  pop esi
0xBBA1C7  mov dword ptr [ebx + 0x120], eax   ; ★ 写 0（不是 3）
0xBBA1CD  mov dword ptr [ebx + 0x130], eax   ; 索引同时清零
0xBBA1D3  xor ecx, ebp
0xBBA1D5  pop ebx
0xBBA1D6  call 0xC3C20F
0xBBA1DB  mov esp, ebp
0xBBA1DE  ret

0xBBA1E0  mov eax, dword ptr [ecx + 0x120]   ; ★ 纯 getter
0xBBA1E6  ret
0xBBA1E7  int3
```

#### 两个结论

1. **`0xBBA1E0` 只读 `[ecx+0x120]` 并返回，不写任何东西。**
   pump 里 `0xBAE281 call 0xBBA1E0` 之后紧跟 `0xBAE286 cmp eax,1`，
   说明它的用途是"读状态并判断是否等于 1"——**是个 getter**。

2. **`0xBBA1C7` 写的是 0，不是 3。** 它是某个清理/复位函数的一部分
   （同一条路径还把 `[ebx+0x130]` 索引清零）。

**§12.121 提出的"Add 返回后紧跟的调用覆盖状态"假设由此排除。**

#### 于是覆盖者候选只剩这些

§12.70 记录过 `[ebx+0x120]` 的全部 8 个写入点：

```
0xBB76BB  -> 0
0xBBA0A4  -> esi
0xBBA1C7  -> eax (= 0)   ← 本轮确认
0xBBA2B6  -> 4
0xBBA33E  -> 0
0xBBA3D2  -> 1
0xBBA569  -> 2           ← Add 的成功路径
0xBBA62B  -> 3           ← Add 的容量满路径
```

**没有一个是"写 3 且在 Add 之外"**——写 3 的只有 `0xBBA62B`，而它在 `Add` 内部。

#### 这让矛盾更加尖锐

`Add` 内部的顺序是确定的：

```
0xBBA569  写 2        （count > 0 时必然执行）
0xBBA573..0xBBA5BE   日志/清理（不写 [ebx+0x120]）
0xBBA5C3  cmp [ebx+0x120], 1
0xBBA5CA  jne 0xBBA635  -> 状态是 2，必跳 -> 返回，状态保持 2
```

**按此推演，只要有一次 count > 0，状态就会永久变成 2。**

但 §12.102 的 20ms 采样显示状态从 1 直接跳到 3。

#### 两个仍可能的解释

1. **`0xBBA5C3` 的 `cmp` 读到的 `[ebx+0x120]` 不是 `0xBBA569` 刚写的那个地址**——
   若 `ebx` 在 `0xBBA573`–`0xBBA5BE` 之间被改（例如被某个 `call` 破坏），
   `cmp` 就会读到另一个对象的字段。**但 `Add` 的 callee-saved 约定应当保护 `ebx`**，
   除非某个被调函数违反约定。

2. **§12.102 的采样错过了状态 2**——尽管间隔是 20ms，但若状态 2 只存在极短时间
   （例如在同一帧内被 `0xBBA62B` 覆盖），仍可能漏掉。但这要求 `Add` 在同一次调用里
   先写 2 再走到 `0xBBA62B`，而 `jne` 本应拦住。

#### 下一步：直接计数 `0xBBA569` 与 `0xBBA62B`

既然已经掌握了"循环重试直到成功"的方法（§12.121 一次就抓到正数 count），
现在可以对**两个写入点**分别计数：

- `0xBBA569`（写 2）命中次数
- `0xBBA62B`（写 3）命中次数

**若两者在同一轮运行中都命中**，就证明"写 2 之后又写 3"确实发生，
那 `jne` 没拦住的原因就是 `ebx` 被改或 `cmp` 读错地址；
**若只有 `0xBBA62B` 命中而 `0xBBA569` 从不命中**，则说明 count > 0 时
根本没走到 `0xBBA569`——那 §12.106 采到的正数 count 与 `Add` 实际用的仍不是同一个。

**两个计数器同轮采集，是唯一能区分这两种情况的实验。**

注意：`0xBBA569` 直接挂钩曾导致客户端不启动（§12.116），
所以这次应改用**轮询 `[obj1+0x120]` 的 20ms 快照 + 记录每一次跳变**，
或者挂在 `0xBBA43A`（已验证安全）并在那里判断 count 正负。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.122"),
                         ("HANDOFF-CURRENT.md", "### 16.10")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.122", "### 16.10")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
