"""Record round 110: none of the three candidates clobber ebx, so the corruption model fails."""
from pathlib import Path

TEXT = """
### 12.125 三个候选全部排除：`ebx` 在写 2 与检查之间应当完好（2026-10-25 02:4x）

#### 反汇编结果

```asm
0xBA4B20  C3                     ret                    ← ★ 空函数，只有一条 ret
0xBA4B21  CC ×...                int3

0xB75660  55                     push ebp
0xB75661  8B EC                  mov ebp, esp
0xB75663  8B 45 08               mov eax, [ebp+8]
0xB75666  53                     push ebx               ← ★ 保存 ebx
0xB75667  56                     push esi
0xB75668  57                     push edi
0xB7566E  8B D9                  mov ebx, ecx

0xC42D60  8B 54 24 0C            mov edx, [esp+0xc]     ← CRT memset 类
0xC42D64  8B 4C 24 04            mov ecx, [esp+4]
          …（无 ebx）
```

| 函数 | 是否破坏 `ebx` |
|---|---|
| `0xBA4B20` | **否**——它只是个空的 `ret` |
| `0xB75660` | **否**——`push ebx` 保存了 |
| `0xC42D60` | **否**——CRT 例程，只用 eax/ecx/edx |
| `0xB76EE0` | **否**——`mov [ecx],0xDEADBEEF; ret`（§12.124） |

**写 2 与 `cmp` 之间的五个 `call` 全部不会破坏 `ebx`。**

#### 于是"ebx 被破坏"这个模型也失败了

按此推演：

```asm
0xBBA569  mov [ebx+0x120], 2     ; 状态 = 2
0xBBA573..0xBBA5BE                ; 五个安全调用
0xBBA5C3  cmp [ebx+0x120], 1     ; 读到 2
0xBBA5CA  jne 0xBBA635           ; 2 != 1 -> 跳，返回
```

**`Add` 应当返回，状态保持 2；随后 pump 的 getter `0xBBA1E0` 读到 2，
`cmp eax,1` 不成立，状态继续是 2。**

**但实测状态是 3。**

#### 剩下的可能性已经很少

1. **`0xBBA569` 之后并未执行到 `0xBBA5C3`**——中间有异常、长跳转或提前返回。
   但 §12.108 已确认 `0xBBA5AB`（在两者之间）被执行，说明流程确实在往前走；
2. **`0xBBA62B` 在另一条路径上被到达**——例如 `Add` 被**再次调用**时走
   `count<=0` 分支：第一次 `count>0` 写了 2 并返回，第二次 `count<=0` 时
   **入口检查 `cmp [ebx+0x120],1` 会拦住**（状态是 2 → `jne` → 返回）。
   **除非 `[ebx+0x120]` 在两次调用之间又被改回 1。**
3. **`0xBBA3D2`（写 1）在两次调用之间执行了**——它是 `Init` 的一部分，
   而 §12.94 已确认 `Init` 在稳态下 0 次调用。**但 `dw=2` 的早期阶段呢？**
   §12.108 观察到写 2 发生在 `dw=2`，那是**初始化期间**——`Init` 完全可能在那时运行！

**第 3 条是最有希望的解释**：

```
t≈? (dw=2)   Init 运行 -> 状态 = 1, 索引 = 0
t≈? (dw=2)   Add 收到 count>0 -> 写 2 -> jne 返回 -> 状态 = 2
t≈?          Init 再次运行 -> 状态 = 1（覆盖了 2）
t≈?          后续 count<=0 帧 -> 索引推进 -> 满 -> 写 3
```

**即：`Init` 与 `Add` 在初始化期间交替运行，`Init` 把 2 覆盖回 1。**

§12.94 只测了 `dw=5` 之后的稳态，**从未测过 `dw=2` 阶段**。

#### 下一步

**在 `dw` 从 0 到 5 的整个启动过程中计数 `0xBBA370`（`Init`）**。

用 `probe_reg.py --wait --ready-timeout`，在 `0xBBA370` 装计数器（13 字节
`55 8B EC 53 8B D9 83 BB 20 01 00 00 00`，§12.94 已验证可用），采样窗口覆盖启动全过程。

**若 `Init` 在启动期间被调用多次（>1），就证实了"2 被覆盖回 1"**，
那修复方向就是"阻止第二次 `Init`"，或"让 `Add` 在 `Init` 之后立刻执行"。

这是一条全新的、此前未考虑过的线索。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.125"),
                         ("HANDOFF-CURRENT.md", "### 16.13")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.125", "### 16.13")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
