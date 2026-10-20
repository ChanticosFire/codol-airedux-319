"""Record round 106: Add definitively receives a positive count of 3 or 4."""
from pathlib import Path

TEXT = """
### 12.121 ★★★ `Add` 确实收到正数 count（3/4），写 2 必然执行（2026-10-24 00:3x）

#### 一次抓到

用"循环重试直到出现正值"的方式，第一次尝试就捕获到：

```
[t1] n=2   esi=0x00000003  [0x94]=0x00000003
[t1] n=3   esi=0x00000004  [0x94]=0x00000004
[t1] n=18  esi=0x00000004  [0x94]=0x00000004
[t1] n=33  esi=0x00000004  [0x94]=0x00000004
[t1] n=48  esi=0x00000004  [0x94]=0x00000004
[t1] n=62  esi=0x00000003  [0x94]=0x00000003
```

**`esi` 与 `[ebp+0x94]` 逐次相等，值为 3 或 4。**

#### 这意味着写 2 必然执行

```asm
0xBBA43A  mov edi, [ebp+0x94]   ; = 3 或 4
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3          ; 3 > 0 -> 不跳
0xBBA448  …                     ; 构造容器、搬运、判定
0xBBA569  mov [ebx+0x120], 2    ; ★ 必然执行
0xBBA5C3  cmp [ebx+0x120], 1    ; 此时是 2
0xBBA5CA  jne 0xBBA635          ; 2 != 1 -> 立即返回，状态保持 2
```

**按这条链，状态必然变成 2 并永久保持。**

#### 但第 102 轮的 20ms 采样显示状态从未经过 2

```
t=1.51  success=11  status=1  idx=5
t=1.53  success=12  status=3  idx=5    ← 直接跳 3
```

**两者不可能同时为真。**

#### 唯一还站得住的解释

**写 2 与随后的覆盖发生在同一帧内、且覆盖来自 `Add` 之外。**

`Add` 内部从 `0xBBA569` 到 `0xBBA5CA` 之间只有日志/清理调用
（`0xBBA57A`、`0xBBA591`、`0xBBA59D`、`0xBBA5AF`、`0xBBA5BE`），
它们都不写 `[ebx+0x120]`。

**所以覆盖者只能是 `Add` 返回之后的代码。**

pump 里的顺序是：

```
0xBAE276  call 0xBBA3F0     ; Add 返回，状态 = 2
0xBAE27B  mov ecx, [ebx+0x1F8]
0xBAE281  call 0xBBA1E0     ; ★ 紧接着又一个调用
0xBAE286  cmp eax, 1
0xBAE289  je 0xBAE292
```

**`0xBBA1E0` 是紧跟在 `Add` 之后的调用**，它很可能就是覆盖者——
`0xBBA1E0` 与 `0xBBA3F0` 地址相邻，属于同一组操作（`0xBBA1E0` / `0xBBA3F0` /
`0xBBA370` 都在 `0xBBA1xx`–`0xBBA3xx` 区间，是同一个类的几个方法）。

而 §12.70 已记录 `0xBBA1C7` 是 `[ebx+0x120]` 的**一个写入点**（值为 `ebx`，
即某个寄存器）。**`0xBBA1C7` 很可能就在 `0xBBA1E0` 之前的函数体内。**

#### 下一步：确认覆盖者

1. **反汇编 `0xBBA1E0`**，看它是否写 `[ebx+0x120]`；
2. 若它内部有 `0xBBA1C7`（§12.70 记录的写入点之一），那覆盖链就闭合了：
   `Add` 写 2 → `0xBBA1E0` 写别的值（可能是 3）→ 状态锁定；
3. 若确认，修复方向就变成"让 `0xBBA1E0` 不覆盖"，而不是继续纠结 `Add`。

**这是把最后一环补上的实验，只需一次反汇编。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.121"),
                         ("HANDOFF-CURRENT.md", "### 16.09")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.121", "### 16.09")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
