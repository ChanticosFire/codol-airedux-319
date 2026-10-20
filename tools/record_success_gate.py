"""Record round 56: 0xBC1980 return value gates the success path."""
from pathlib import Path

TEXT = """
### 12.70 ★★ `0xBC1980` 的返回值 `< 3` 就直接写 2；`+0x8C` 才是列表基址（2026-10-23 20:4x）

#### `0xBC1A50`（追加实现）零次调用是必然的

给 `0xBC1A50` 装计数器，10 秒 **0 次**。原因是 `Add` 在 `0xBBA434 jne 0xBBA635`
就因为 `status != 1` 跳走了，根本没进主体。这与 §12.63 的结论一致。

#### 主体里的真正判定

```asm
0xBBA496  lea edi, [ebx + 0x8c]        ; ★ 列表基址是 +0x8C
0xBBA49C  mov ecx, 0x22
0xBBA4A1  rep movsd                     ; 复制 136 字节到 [ebx+0x8c]
0xBBA4A3  lea ecx, [ebp - 0x250]
0xBBA4A9  call 0xBC1980
0xBBA4AE  cmp ax, 3                     ; ★ 与 3 比较
0xBBA4B2  jb 0xBBA55E                   ; ★ < 3 -> 跳到 0xBBA55E（写 2 路径）
0xBBA4B8  lea ecx, [ebp - 0x250]
0xBBA4BE  call 0xBC1970
0xBBA4C3  lea edi, [ebx + 0x8c]
0xBBA4C9  push eax
0xBBA4CC  call 0xB75470                 ; 再检查一次
0xBBA4D3  je 0xBBA55E                   ; 失败 -> 同样到 0xBBA55E
...
0xBBA55E  push 0x63                     ; 两条路在此汇合
0xBBA560  lea edx, [ebp - 0x13b]
0xBBA566  push 0
0xBBA568  push edx
0xBBA569  mov dword ptr [ebx + 0x120], 2   ; ★ 写 2（成功）
```

**关键点：`0xBC1980` 返回 `< 3` 时直接跳到写 2；返回 `>= 3` 时再经一次检查，
失败也到写 2。** 所以这个分支整体是"判定通过就标记成功"。

`0xBC1980` 的返回值只与常数 **3** 比较，很可能是"当前已用槽位数"或"查找命中数"。
这一点需要单独反汇编确认。

#### `+0x8C` 才是列表数据区

之前一直把 `+0x120`（状态）、`+0x124`（容量字节）、`+0x130`（索引）当成主要字段，
但它们只是**头部**。真正的条目数据从 **`+0x8C`** 开始，每条 136 字节，由
`rep movsd`（`ecx = 0x22`）复制进去。

**这也解释了为什么 `+0x130` 会一路涨到容量**：每追加一条就往 `+0x8C` 复制一次，
同时把索引加一；索引到容量后，`0xBBA62B` 写 3。

#### 与第 52 轮实验二的对账

第 52 轮把容量抬到 200、索引清零、状态置 1 后，索引涨到 200 但**状态始终是 1**，
当时以为"写 2 的代码没执行"。现在看 `0xBBA4AE cmp ax,3` / `jb 0xBBA55E`：
`0xBC1980` 大概率返回了 **>= 3**，于是继续走 `0xBBA4BE` 那条；
而 `0xBBA4D3 je 0xBBA55E` 只有在 `0xB75470` 返回真时才跳过写 2——
也就是说当 `0xB75470` 返回真时，**流程并不写 2，而是继续往下**（`0xBBA4D9` 之后）。

**这意味着"写 2"其实不是成功路径，而是"放弃/结束本轮"路径。**
真正成功的分支在 `0xBBA4D9`–`0xBBA55C`，它做的是一串 `0xBC1970` / `0x848AD0` /
`0xB75660` 调用，最后 `0xBA4B20` 输出日志。

#### 下一步

1. 反汇编 `0xBC1980` 与 `0xBC1970`，确认返回值语义（很可能是容器内条目数）；
2. 反汇编 `0xB75470`（`push eax` + `call`，参数是 `0xBC1970` 的结果），
   确认它在比较什么；
3. 若 `0xB75470` 是在"检查新条目是否已存在"，那么它现在返回真、导致跳过写 2，
   正是重复追加的直接原因——因为它把每帧的同一份数据当成"已存在"之外的某种状态。

第 3 条最有解释力：如果 `0xB75470` 是去重判定，它返回真意味着"已存在"，
那么流程继续往下（不写 2）就说明**重复条目被识别出来了但没被拦住**，
而是走到了另一条不设置状态的路径上。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.70"),
                         ("HANDOFF-CURRENT.md", "### 15.58")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.70", "### 15.58")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
