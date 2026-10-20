"""Record round 147: both filter branches confirmed as six-byte je rel32."""
from pathlib import Path

TEXT = """
### 12.162 确认两条过滤分支的编码，并读出完整上下文（2026-10-25 21:5x）

#### 从 `0xBBA448`（`jle` 之后）起的完整序列

```asm
0xBBA448  lea ecx, [ebp-0x250]
0xBBA44E  call 0xBC1CC0            ; 构造容器（§12.91：把 +2 字段清零）
0xBBA453  lea eax, [ebx+4]
0xBBA456  push eax                  ; 参数：obj1+4
0xBBA457  lea ecx, [ebp+8]          ; 参数：136 字节结构的起点
0xBBA45A  mov byte ptr [ebp-4], 1   ; SEH 状态
0xBBA45E  call 0xB75440             ; ★ 比较两个记录的 +0x84
0xBBA463  test al, al
0xBBA465  0F 84 3A 01 00 00   je 0xBBA5A5   ; ★ 若结果为 0 -> 跳过写 2
0xBBA46B  lea ecx, [ebp-0x254]
0xBBA471  push ecx
0xBBA472  push 0
0xBBA474  push edi
0xBBA475  push esi
0xBBA476  lea ecx, [ebp-0x250]
0xBBA47C  call 0xBC1A50             ; ★ 容器追加
0xBBA481  test al, al
0xBBA483  0F 84 1C 01 00 00   je 0xBBA5A5   ; ★ 若结果为 0 -> 跳过写 2
0xBBA489  lea ecx, [ebp-0x250]
0xBBA48F  call 0x848AD0             ; 继续处理
```

#### 两条分支的编码

```
0xBBA465  0F 84 3A 01 00 00    je +0x13A    （6 字节）
0xBBA483  0F 84 1C 01 00 00    je +0x11C    （6 字节）
```

**都是 6 字节的 `je rel32`，可以整条替换为 6 个 `nop`（`90 90 90 90 90 90`）
使其永不跳转，而不改变任何长度或后续编码。**

#### 两处检查的含义

**`0xB75440`（`0xBBA45E` 调用）**——§12.82 记录：

```asm
0xB75440  mov dx, word [ecx+0x84]
0xB7544A  mov eax, [ebp+8]
0xB7544D  cmp dx, word [eax+0x84]
0xB75454  jne 0xB75469
0xB75456  push eax
0xB75457  call 0xB76FD0
0xB7545C  test al, al
0xB7545E  je 0xB75469
0xB75460  mov eax, 1
0xB75469  xor eax, eax
```

**返回 1 表示"两个记录在 `+0x84` 字段相同且类型一致"，0 表示不同。**

**`0xBC1A50`（`0xBBA47C` 调用）**——§12.91 记录为容器的追加函数，
成功返回非零。

#### 于是逻辑是

```
若 (当前条目 == 容器里已有条目)  ->  je  -> 跳过写 2
若 追加失败                      ->  je  -> 跳过写 2
否则                            ->  继续 -> 写 2
```

**即：只有当"条目不重复且追加成功"时才会写 2。**

#### 下一步：一次判定

同时打三个补丁（都是纯数据修改）：

```
0xBBA465  0F 84 3A 01 00 00  ->  90 90 90 90 90 90
0xBBA483  0F 84 1C 01 00 00  ->  90 90 90 90 90 90
0xBBA569  …02 00 00 00       ->  …34 12 CD AB（哨兵）
```

**若哨兵出现** → 确认卡点就是这两条 `je`，接着只需搞清哪一个成立、
以及为什么（很可能是"条目重复"或"追加失败"）。
**若哨兵仍不出现** → 说明还有更深的过滤，但已排除的范围又扩大了一圈。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.162"),
                         ("HANDOFF-CURRENT.md", "### 16.50")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.162", "### 16.50")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
