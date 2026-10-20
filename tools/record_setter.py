"""Record round 160: both branches of the setter write 4, so it simply is never called."""
from pathlib import Path

TEXT = """
### 12.175 ★★★ 状态设置函数的两条分支都写 4，因此它从未被调用（2026-10-26 05:2x）

#### 完整代码

```asm
0xBBA941  call 0xB75440                    ; 比较（§12.82：比 +0x84 字段）
0xBBA946  test al, al
0xBBA948  je 0xBBA976                       ; al == 0 -> 走另一支
0xBBA94A  call 0xBA4B20                     ; 日志
0xBBA94F  pop edi
0xBBA950  pop esi
0xBBA951  C7 83 A0 01 00 00 04 00 00 00     mov dword [ebx+0x1A0], 4
0xBBA95B  C7 83 9C 01 00 00 02 00 00 00     mov dword [ebx+0x19C], 2
0xBBA965  pop ebx
0xBBA966  mov ecx, [ebp-4]
0xBBA969  xor ecx, ebp
0xBBA96B  call 0xC3C20F                     ; __security_check_cookie
0xBBA970  mov esp, ebp
0xBBA972  pop ebp
0xBBA973  ret 8

0xBBA976  call 0xBA4B20                     ; 日志
0xBBA97B  pop edi
0xBBA97C  pop esi
0xBBA97D  C7 83 A0 01 00 00 04 00 00 00     mov dword [ebx+0x1A0], 4
0xBBA987  C7 83 9C 01 00 00 03 00 00 00     mov dword [ebx+0x19C], 3
0xBBA991  pop ebx
0xBBA992  …
0xBBA99F  ret 8
```

#### 决定性观察：两条分支都写 4

`0xBBA948` 的 `je` 只决定走哪一支，**而两支都以 `mov [ebx+0x1A0], 4` 结束**。

**区别仅在于 `[ebx+0x19C]` 被设为 2 还是 3。**

**所以：只要这个函数被调用一次，状态码必然是 4。**

**而实测状态码是 1（§12.173）——所以这个函数从未被调用。**

#### `[0x19C]` 的语义修正

§12.173 曾把 `[0x19C]` 称作"数据指针"，**现在看它不是指针，而是一个结果码**：
状态为 4 时它取 2 或 3。

**而 `0xBBA730`（`cmp [ecx+0x1A0],4` / `mov eax,[ecx+0x19C]`）返回的就是这个结果码。**

**所以两个访问器的语义是：**

| 函数 | 语义 | 返回 |
|---|---|---|
| `0xBBA710` | **是否仍在进行中（pending）** | `[0x1A0]` 为 1/2/3 时返回 1，否则 0 |
| `0xBBA730` | **取结果码** | `[0x1A0] == 4` 时返回 `[0x19C]`（2 或 3），否则 0 |

#### 因此 `0xBAE2D4` 的判断含义是

```asm
0xBAE2D4  jne 0xBAE2DD      ; pending != 0 -> 跳到守卫，C 保持 0
0xBAE2D6  mov byte [ebp-0x986], 1   ; 不 pending -> C = 1
```

**即：只有"列表查询已经完成"时，标志 C 才置 1。**

**这与"服务器列表请求从未完成"的结论完全一致。**

#### 下一步：找这个函数的调用者

函数以 `ret 8` 结束（两个参数的 stdcall），起点在 `0xBBA900` 之前。

**用 `branches_to.py` 找出所有 `call` 到该函数入口的位置**，
就能知道"谁负责把状态推进到 4"。

**若那个调用点位于某条从未执行的分支里，问题就变成"那条分支的前置条件是什么"——
很可能就是"收到了服务器列表应答"。**

**这将最终把整条分析线与协议问题接上。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.175"),
                         ("HANDOFF-CURRENT.md", "### 16.63")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.175", "### 16.63")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
