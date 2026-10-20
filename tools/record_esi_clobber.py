"""Record round 89: Add loads [ebp+0x90] into esi at entry, so sampling esi proves nothing."""
from pathlib import Path

TEXT = """
### 12.104 对比无效：`Add` 入口就把 `[ebp+0x90]` 装进 `esi`（2026-10-24 15:2x）

#### 采样结果与矛盾

在 `0xBBA440` 同时采样 `esi` 与 `[ebp+0x94]`：

```
[esi94] n=0  esi=0x00000000  [ebp+0x94]=0x00000000
[esi94] n=1  esi=0x001ACFD0  [ebp+0x94]=0xFFFFFFFE
```

**两者不相等**，且 `esi` 是正数（`0x001ACFD0`），`[ebp+0x94]` 是 `-2`。
按 §12.103 的推断（count = `esi`）应当相等，实测不等。

#### 原因：`Add` 在入口就改写了 `esi`

```asm
0xBBA3F0  push ebp / mov ebp, esp
0xBBA3F3  push -1
0xBBA3F5  push 0xC90FBE                  ; SEH 记录
0xBBA3FA  mov eax, dword ptr fs:[0]
0xBBA400  push eax
0xBBA401  sub esp, 0x248                 ; ★ 584 字节局部
0xBBA407  mov eax, dword ptr [0xE3F240]  ; 栈 cookie
0xBBA40C  xor eax, ebp
0xBBA40E  mov dword ptr [ebp - 0x10], eax
0xBBA411  push ebx
0xBBA412  push esi                       ; 保存调用方的 esi
0xBBA413  push edi
0xBBA414  push eax
0xBBA415  lea eax, [ebp - 0xc]
0xBBA418  mov dword ptr fs:[0], eax
0xBBA41E  mov esi, dword ptr [ebp + 0x90]   ; ★ esi = 源指针参数
0xBBA424  mov ebx, ecx
0xBBA426  cmp dword ptr [ebx + 0x120], 1
0xBBA42D  mov dword ptr [ebp - 4], 0
0xBBA434  jne 0xBBA635
0xBBA43A  mov edi, dword ptr [ebp + 0x94]   ; ★ edi = count
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3
```

**`0xBBA41E` 把 `[ebp+0x90]` 写进 `esi`**，所以在 `0xBBA440` 采到的 `esi`
已经是**源指针**（`0x001ACFD0`，一个堆地址），而不是调用方传的 `esi`（虚函数返回值）。

**因此第 88 轮"在 `0xBBA440` 比对 `esi` 与 `[ebp+0x94]`"这个实验设计本身是错的**，
得到的"不相等"不能用来否定 §12.103。

#### 但 §12.103 的栈布局仍需复核

现在有一个新问题：`Add` 用的是 `[ebp+0x90]` 与 `[ebp+0x94]`，
而调用方在 `0xB753C0` 之后只留下了两块 4 字节数据：

```
[ebp+8]  ..  [ebp+0x8F]   136 字节结构
[ebp+0x90]                ← 按布局应是第 1 块（&[ebp-0x548]）
[ebp+0x94]                ← 按布局应是第 2 块（esi）
```

**若 `[ebp+0x90]` 真是第 1 块，它的值应当是 `ebp-0x548`（一个栈地址，
形如 `0x0012xxxx`），而不是 `0x001ACFD0`。**

实测 `0x001ACFD0` 是一个堆地址，形态上更像"指向对象的指针"而不是"栈地址"。
这暗示 `[ebp+0x90]` 可能**不是**调用方推的那块，而是结构内部或其它局部。

#### 需要一次干净的对齐

为避免继续在偏移上反复，下一轮应当：

1. 在 `0xBBA41E`（`mov esi,[ebp+0x90]`）**之前**的 `0xBBA418` 装探针，
   同时采样 `esi`（此时还是调用方的值）与 `[ebp+0x88]`、`[ebp+0x8C]`、
   `[ebp+0x90]`、`[ebp+0x94]` 四个槽位；
2. 这样能一次性看出**调用方推的两块**落在哪个偏移，以及 `Add` 读的
   `0x90/0x94` 与它们相差多少；
3. 顺便确认 `esi`（调用方值）在这几个槽位中的位置。

**这是把"偏移"这件事彻底钉死的唯一办法**：一次采样、五个位置、同一帧。

#### 目前仍然成立的结论

- `0xB753C0` 是 `ret 4`（stdcall），调用后 `esp` 回升 4 字节——**这条没变**；
- `Add` 的 `count` 来自 `[ebp+0x94]`——**这条也没变**（§12.99 已由 `edi` 验证）；
- **变的是**"`[ebp+0x94]` 里装的是什么"——它既不是容器 `+0x84`（§12.98 否定），
  也不是虚函数返回值（§12.103 未证实），**仍是未知**。

下一轮的多槽位采样应当能给出答案。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.104"),
                         ("HANDOFF-CURRENT.md", "### 15.92")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.104", "### 15.92")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
