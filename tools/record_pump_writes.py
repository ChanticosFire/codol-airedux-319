"""Record the pump write-site map and the server-address dependency."""
from pathlib import Path

TEXT = """
### 12.23 `[lobby+0x1F4]` 的全部写者与写 2 的两条路径（2026-10-23 01:1x）

#### 8 处写入点（全部位于 `0xBAD800`，即社区所说的 lobby pump）

用 `find_refs.py --pattern c783f4010000`（`mov dword [ebx+0x1F4], imm32`）扫描：

| 地址 | 写入值 | 备注 |
|---|---|---|
| `0xBADB40` | `0xFFFFFFFF`（-1） | 失败路径 |
| `0xBADDDA` | —— | 社区补丁 `baddDA+6` 的目标 |
| `0xBADFA2` | —— | 前置调用 `0xC699B0`（`0xBADF9D`） |
| **`0xBAE1AC`** | **2** | ★ 正常推进路径 A |
| **`0xBAE587`** | **2** | ★ 正常推进路径 B |
| `0xBAE74E` | —— | 社区补丁目标 |
| `0xBAE766` | **1** | 社区补丁改成写 1 |
| `0xBAE7AA` | —— | 社区补丁目标 |

**关键发现：写 2 的两处（`0xBAE1AC`、`0xBAE587`）是无条件写入**——只要执行流到达
那里就会写 2，中间没有 `test al,al` 之类的分支。

#### 写 2 的前置调用

两处写 2 之前都调用 `0xC699B0`，参数相同：

```asm
; 路径 A @ 0xBAE193
0xBAE193  mov ecx, [ebx+0x1F0]     ; 参数 1 = lobby[0x1F0]（服务器地址/端口）
0xBAE199  lea eax, [ebx+0x184]     ; 参数 2 = &lobby[0x184]
0xBAE19F  push eax
0xBAE1A0  push ecx
0xBAE1A1  lea ecx, [ebx+0x1A0]     ; this = lobby+0x1A0
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword [ebx+0x1F4], 2 ; 无条件

; 路径 B @ 0xBAE56B 结构相同
```

#### `0xC699B0` 的语义（设置服务器地址）

```asm
0xC699B0  cmp dword [esi+0x1C], 0  ; 已设置过？ -> 返回 0
0xC699D1  mov ecx, [ebp+8]         ; 参数 1
0xC699D4  test ecx, ecx
0xC699D6  je 0xC699C2              ; 为 0 -> 返回失败
0xC699D8  mov [esi], ecx           ; 保存
0xC699DA  call 0xBB1A80            ; 计算标识，存 [esi+0x38]
0xC699E2  mov eax, [ebp+0xC]       ; 参数 2 指向的结构
0xC699E7  mov [esi+0x3C], [eax+0]  ; 复制 4 个字段到 +0x3C..+0x48
0xC699F9  mov [esi+0x1C], 1        ; 标记成功
0xC699FC  mov al, 1                ; 返回成功
```

即：**只有拿到非零的服务器地址，才会标记成功**。

#### 推断

`[lobby+0x1F0]` 是客户端从服务端拿到的**大厅服务器地址/端口**。它目前为 0，
所以 `0xC699B0` 走失败分支。但由于写 2 本身无条件下达，真正的问题可能不是
`0xC699B0` 的返回值，而是**执行流根本到不了 `0xBAE1AC` / `0xBAE587`**。

两条路径都在 `0xBAD800` 内部较深的位置，前置条件尚未解析清楚——反汇编在
`0xBAE100` 处因字节对齐中断（把 `0xBAE100` 当成指令边界解出了 `stc`）。
下一步应从 `0xBAE0C0` 或更早的函数头部开始解码，或直接在这两个地址上看
哪些跳转能到达。

#### 与社区补丁的关系

社区 9 处补丁覆盖了 `0xBADC26`、`0xBADDDA+6`、`0xBAE74E+6`、`0xBAE766+6`、
`0xBAE7AA+6`，即把「写 -2」改成写 1。**他们没有动写 2 的两处**——说明在社区
环境里客户端能自然到达写 2。我们的客户端停在写 2 之前。

#### 结论

`[lobby+0x1F4]` 停在 1 并非某个补丁缺失，而是 pump 内部某个前置判断让执行流
提前返回。强写 2 能让 `FE_state` 到 6（已验证），但会崩溃。正确做法是让客户端
自己走到写 2——这需要先弄清 `0xBAD800` 从入口到 `0xBAE1AC` 的完整路径。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.23"),
                         ("HANDOFF-CURRENT.md", "### 15.11")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.23", "### 15.11")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
