"""Record round 81: both paths run, but the written count appears to be zero."""
from pathlib import Path

TEXT = """
### 12.96 抬容量后两条路径同时运行，但状态仍停在 1（2026-10-24 10:5x）

#### 组合实验结果

```
before: status=1  cap=5    idx=2
after:  status=1  cap=200  idx=0

t=5s    G1=0 gate=0 FE=5 1F4=1 status=1 idx=11  stat=20
t=10s   …                                idx=21  stat=31
t=30s   …                                idx=62  stat=72
t=60s   …                                idx=125 stat=135
```

三个量同时增长，速率一致（约 2/秒）：

- `idx`（`obj1+0x130`）—— 空帧推进；
- `stat`（`[0xE85CB0]`）—— `0xBB15E0` 的成功路径计数。

**所以"成功"确实在发生（`stat` 从 0 涨到 135），而且没有触发写 3（`idx` 远未到 200）。**

#### 但状态一直停在 1

按 §12.95 的结论，`count > 0` 时流程应当是：

```
0xBBA448 构造 → 0xBBA4A1 搬运 → 判定 → 0xBBA569 写 2 → 0xBBA5C3 检查(2≠1) → 返回
```

**状态应当变成 2 并永久保持。** 实测却是 1。

而 `idx` 每帧 +1，说明**每一帧都走了 `count <= 0` 那条路径**——即 `Add` 收到的
`count` 一直是 0。

#### 于是矛盾收敛到一个点

`stat` 在涨（`0xBB15E0` 成功 135 次），`0xB75420` 应当在每次成功后把
"条目数"写进容器 `+0x84`。若写的值 > 0，`Add` 就该走成功分支。

**唯一的解释是：`0xB75420` 写进 `+0x84` 的值就是 0。**

回看链路：

```asm
0xC74041  mov edx, dword ptr [ebp - 0x120]   ; 读 0xBB15E0 的输出参数
0xC74047  mov ecx, dword ptr [ebp - 0x11C]
0xC7404B  push edx                            ; 参数 2
0xC7404C  push eax                            ; 参数 1
0xC74053  call 0xB75420
```

`0xB75420` 里 `mov cx, word ptr [ebp + 0xc]` / `mov word ptr [esi + 0x84], cx`。
**所以 `[ecx+0x84] = (word)[ebp-0x120]`。**

而 `[ebp-0x120]` 是 `0xBB15E0` 的第几个参数？按 `0xC73FF7`–`0xC7400C` 的压栈顺序：

```asm
0xC73FF7  mov ecx, [ebp + 0x10]   ; 虚函数参数 3 = 0x508（长度）
0xC73FFA  push ecx
0xC73FFB  mov ecx, [esi + 4]
0xC73FFE  push edi                ; 虚函数参数 2
0xC73FFF  lea edx, [ebp - 0x120]
0xC74005  push edx                ; &[ebp-0x120]
0xC74006  lea eax, [ebp - 0x118]
0xC7400C  push eax                ; &[ebp-0x118]
0xC7400D  push ecx                ; [esi+4] 句柄
0xC7400E  call 0xBB15E0
```

所以 `0xBB15E0(handle, &buf, &out1, out2, size)`，`&[ebp-0x120]` 是**第三个参数**
（`[ebp+0x10]`）。而 `0xBB15E0` 在成功路径里写的是：

```asm
0xBB1719  mov ecx, dword ptr [ebp - 4]
0xBB171C  mov word ptr [ebx], ax        ; ebx 来自 [ebp+0x10]？
0xBB171F  mov dword ptr [edi], edx      ; edi 来自 [ebp+0xc]
```

`ebx` 与 `edi` 分别取自 `[ebp+0x10]` 与 `[ebp+0xc]`（见 `0xBB15F6`–`0xBB15FB`：
`mov ebx,[ebp+0x10]`、`mov edi,[ebp+0xc]`）。

**所以 `0xBB15E0` 写的是 `[ebp+0x10]`（word）与 `[ebp+0xc]`（dword）**，
而调用方传的是 `&[ebp-0x118]`（param2 → `[ebp+0xc]`）和 `&[ebp-0x120]`（param3 → `[ebp+0x10]`）。

**即：`[ebp-0x118]` 得到 dword，`[ebp-0x120]` 得到 word。**

而 `0xB75420` 读的是 `[ebp-0x120]`（word）——**它确实拿到了 word 值**。
那这个 word 应当就是 `ax` = `0xCA84D4`（`ntohs` 之类）的结果。

**所以关键变成：`0xBB15E0` 写入 `ax` 的那个值是多少。**

它来自 `call dword ptr [0xCA84D4]`，参数是 `[ebp-0x12]`。若 `[ebp-0x12]` 恒为 0，
`ax` 就是 0，`count` 也就是 0——**这与全部观测一致**。

#### 下一步

在 `0xBB171C`（`mov word ptr [ebx], ax`）之后读一次 `[ebx]`，或在 `0xBB1710`
（`call [0xCA84D4]`）之后读 `ax`。两者都能直接告出"写进去的条目数是不是 0"。

实现上用 `count_calls.py` 的 cave 不够（它不读寄存器），需要一个小变体：
在 cave 里 `mov [counter], eax` 再重放原指令。这是本轮之后最直接的验证。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.96"),
                         ("HANDOFF-CURRENT.md", "### 15.84")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.96", "### 15.84")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
