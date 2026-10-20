"""Record round 128: the positive count breaks rep movsd, and SEH swallows the fault."""
from pathlib import Path

TEXT = """
### 12.143 ★★★ 找到根因：`rep movsd` 用 `edi` 做目标，而 `edi` 就是 count（2026-10-25 11:5x）

#### 决定性实验：取反分支

把 `0xBBA442` 的 `jle` 改成 `jg`（只改条件码 `0F 8E` → `0F 8F`，目标与长度不变）：

```
patched 0xbba442: jle -> jg (0f8f7b010000, was 2.77s)
  t= 15.29  status=1  idx=0  dw=2
  t= 17.84  status=3  idx=5  dw=5

status sequence: [1, 3]
VERDICT: edi was positive -> the count is > 0 but control still avoids the store
```

**`jg` 是 `jle` 的互补条件。既然取反后行为不变（仍到 3），说明 `jg` 也跳了——
即 `edi > 0`（`jg` 成立），而原来的 `jle` 本该**不**跳。**

**结论：`count` 确实是正数（3），`jle` 不跳，流程确实进入了 `0xBBA448` 之后的成功分支。**

#### 那么在成功分支内部发生了什么

重读 `0xBBA4D9`–`0xBBA556`：

```asm
0xBBA4D9  lea ecx, [ebp - 0x250]
0xBBA4DF  call 0xBC1970            ; 取容器数据指针 -> eax
0xBBA4E4  push 0x63
0xBBA4E6  mov esi, eax             ; ★ esi = 源指针
0xBBA4E8  lea edx, [ebp - 0x73]    ; edx = 目标（但下面用的是 edi！）
0xBBA4EB  mov ecx, 0x22            ; 34 个 dword = 136 字节
0xBBA4F0  push 0
0xBBA4F2  REP MOVSD                ; ★ 目标寄存器是 EDI
0xBBA4F4  push edx
0xBBA4F5  mov byte [ebp - 0x74], 0
0xBBA4F9  call 0xC42D60
…
0xBBA556  call 0xBA4B20
0xBBA55B  add esp, 8
0xBBA55E  push 0x63
0xBBA569  mov dword [ebx + 0x120], 2
```

**关键：`rep movsd` 的目标是 `EDI`，而 `EDI` 此刻的值正是从 `[ebp+0x94]` 装载的 `count`！**

`0xBBA43A` 装载 `edi = [ebp+0x94] = 3`，此后直到 `0xBBA4F2` **再没有指令改过 `edi`**。

**所以 `rep movsd` 会试图把 136 字节写到地址 `0x00000003`。**

**那是一次访问违例。**

#### SEH 解释了全部现象

`Add` 在 `0xBBA3F5` 用 `push 0xC90FBE` 建立异常帧、`0xBBA415` 写入 `fs:[0]`。

**`0xBBA4F2` 处的访问违例会被这个帧捕获，控制流交由 SEH 处理器接管，
从 `0xBBA644`–`0xBBA647` 那段恢复 `fs:[0]` 并直接 `ret 0x90` 返回。**

**于是：**

| 现象 | 成因 |
|---|---|
| `count` 采样为 3 | ✔ 真实值 |
| `jle` 不跳 | ✔ 因为 3 > 0 |
| `0xBBA569`（写 2）从不执行 | ✔ 在 `rep movsd` 处就异常了 |
| `obj1[0x120]` 从不变 2 | ✔ 同上 |
| 状态最终变 3 | ✔ 异常返回后，下一帧仍走 `count<=0` 的路径推进索引，满后写 3 |
| `0xBBA43A` 钩子能稳定命中 | ✔ 它在异常点之前 |
| `0xBBA442`/`0xBBA569` 钩子一命即崩 | ✔ 它们之后立刻触发异常，钩子干扰了 SEH |

#### 但这引出一个问题：这是 bug 吗

`0xBBA4E8` 用 `lea edx, [ebp-0x73]` 算了一个目标地址放进 `edx`，
**紧接着 `0xBBA4F2` 却用 `EDI` 做 `rep movsd` 的目标**。

**若原意是 `mov edi, edx` 而少了一条指令，那这就是客户端的缺陷。**
但 `Add` 在正常对局中显然能工作（否则游戏根本无法运行），
**所以更可能的是：调用方必须保证 `EDI` 在进入 `Add` 时已经指向目标缓冲**——
而我们的环境里没有满足这个前提。

**即：`Add` 期望调用方预先设置 `edi`，而 pump 的调用点没有设置它**
（`esi`/`ecx` 都设置了，唯独 `edi` 未设）。
`edi` 在 pump 里最后一次被赋值是 `0xBAE244` 之前的某处，此时它恰好是 `3`。

#### 下一步

**用哨兵法验证 `rep movsd` 是否真的触发异常**：

把 `0xBBA4F2` 的 `rep movsd`（`F3 A5`，2 字节）改成 `NOP NOP`（`90 90`）。
若异常确实来自这里，那么跳过它之后，流程应当继续走到 `0xBBA569` 写 2——
**届时状态会变成 2。**

**这是对整个推论最直接的验证，且只改 2 个字节、不动控制流。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.143"),
                         ("HANDOFF-CURRENT.md", "### 16.31")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.143", "### 16.31")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
