"""Record round 85: [ebp-0x548] is the virtual function's second argument, written by the success path."""
from pathlib import Path

TEXT = """
### 12.100 `[ebp-0x548]` 是虚函数的第 2 个参数，仅由成功路径写入（2026-10-24 13:2x）

#### 三个引用全是 `lea`

在 `0xBAE000`–`0xBAF000` 内搜 `-0x548` 的 disp32（`B8 FA FF FF`），只有 3 处：

```
0xBAE22D  lea edx, [ebp - 0x548]     ; 作为参数传给虚调用
0xBAE24F  lea ecx, [ebp - 0x548]     ; 作为参数传给 Add
0xBAE29B  lea eax, [ebp - 0x548]     ; 作为参数传给 obj2 的 Add
```

**没有任何一处直接写它**——pump 只是把它的地址反复传出去。

#### 它作为虚函数的第 2 个参数

`0xBAE22B` 起的调用：

```asm
0xBAE22B  push 0x508              ; 第 3 参数（1288）
0xBAE230  lea edx, [ebp - 0x548]
0xBAE236  push edx                ; ★ 第 2 参数 = &[ebp-0x548]
0xBAE237  lea edx, [ebp - 0x768]
0xBAE23D  push edx                ; ★ 第 1 参数 = &[ebp-0x768]
0xBAE23E  mov dword ptr [ebp - 4], 0x17
0xBAE245  call eax                ; 虚函数
```

所以在 `0xC73FB0` / `0xBB15E0` 里，`[ebp+0xC]`（参数 2）就是 `&[ebp-0x548]`。

#### 成功路径恰好写它

```asm
0xBB15FB  mov edi, dword ptr [ebp + 0xc]   ; edi = &[ebp-0x548]
...
0xBB1719  mov ecx, dword ptr [ebp - 4]
0xBB171C  mov word ptr [ebx], ax           ; 写 [ebp+0x10] 指向处
0xBB171F  mov dword ptr [edi], edx         ; ★ 写 [ebp-0x548] = edx
```

**`[ebp-0x548]` 只在成功路径被写成 `edx`。**

#### 于是形成完整闭环

```
虚函数被调用（每帧）
  ├─ 0xBB15E0 接收
  │     ├─ 失败（WSAEWOULDBLOCK -> 返回 -2）
  │     │     不执行 mov [edi],edx，[ebp-0x548] 保持原值
  │     └─ 成功（返回值 >= 0）
  │           执行 mov [edi],edx，[ebp-0x548] = edx
  ↓
0xBAE24F 把 &[ebp-0x548] 作为第 2 参数传给 Add
  ↓
Add 的 [ebp+0x94] 落在结构之外的同一地址 → count = [ebp-0x548]
  ↓
count <= 0 → 跳过写 2 → 推进索引 → 满则写 3
```

**所以 `-2` 的来源是：失败帧里虚函数不写这个槽，而它之前已被写成过 `-2`。**

需要确认"最初是谁把它设成 -2"。两个候选：

1. `0xBB15E0` 的某个失败分支也会写（虽然未见 `mov [edi],…` 之外的写入）；
2. 它在 `0xBAE22D` 之前由别处初始化——但上面已证明 pump 内没有直接写入。

**因此更可能的是：`-2` 来自成功路径的一次写入，而 `edx` 那次恰好是 -2。**
即某次"成功"返回了负值的 `edx`，把它写进去后，后续失败帧不再更新，这个 -2 就一直留着。

#### 这解释了为什么 `[ebp+0x94]` 采样只看到 0 和 -2

- `n=0` 时读到 0：初始值（栈上原本就是 0）；
- `n=1` 时读到 -2：某次成功帧写了 `edx = -2`；
- 之后客户端崩溃，没能继续采。

#### 下一步

1. **延长采样窗口**（先解决稳定性），抓够几十次，看 `[ebp+0x94]` 是否出现正值；
2. **同时采样 `edx`**（在 `0xBB171F` 处 `--reg edx`），确认写进去的到底是什么；
3. 若 `edx` 恒为负，则说明虚函数的"成功"与 `Add` 期望的语义不一致，
   需要在服务端让那条通道返回真正带条目数的数据。

第 2 条最关键：它直接回答"写进去的值能不能为正"。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.100"),
                         ("HANDOFF-CURRENT.md", "### 15.88")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.100", "### 15.88")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
