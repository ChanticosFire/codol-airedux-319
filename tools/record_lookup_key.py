"""Record round 36: the lookup key type and why 0xBBAD40 never satisfies it."""
from pathlib import Path

TEXT = """
### 12.54 容器查找的精确条件：类型 `0x14`、key `0`、长度 1288（2026-10-23 11:1x）

#### 长度检查是严格相等

回看 `0xBBA760` 在 `0xBC1C20` 返回之后的判断：

```asm
0xBBA7D2  test eax, eax
0xBBA7D4  jle 0xBBA7F3                 ; 读到 0 或负 -> 失败
0xBBA7D6  cmp eax, [ebp - 0x510]       ; 返回值 vs 记录长度
0xBBA7DC  jne 0xBBA7F3                 ; ★ 不相等 -> 失败
```

**是 `jne`（严格相等），不是 `<=`。** 所以 §12.53 提出的"也许 136 字节就够"
不成立——必须恰好是记录声明的长度，而查询时给的是 `push 0x508`（1288）。

#### 查询条件的构造

```asm
0xBC1C00  push ebp; mov ebp, esp
0xBC1C03  mov edx, [ebp + 8]           ; 参数 = key（调用方传 0）
0xBC1C06  mov eax, ecx                 ; 返回值 = 查询对象
0xBC1C08  mov ecx, 2
0xBC1C0D  mov byte ptr [eax], 0x14     ; ★ 类型标记 0x14
0xBC1C10  mov word ptr [eax + 2], cx   ; ★ 固定值 2
0xBC1C14  mov dword ptr [eax + 4], edx ; ★ key
0xBC1C18  ret 4
```

即查询对象是 **{类型 0x14, 子类型 2, key 0}**，交给 `0xBC1C20` → `0xB783E0` 做实际查找。

#### `0xBBAD40` 不构造这条记录

它的全部动作是：

1. `0xBBAD58` 把参数 1（`lobby[0xC]`，实测非空指针）存进 `[ebx]`；
2. `0xBBAD6B` `mov ecx, 0x22` + `rep movsd`——从局部复制 **136 字节**到 `[ebx+4]`；
3. `0xBBAD72` 把参数 3、4 存到 `[ebx+0x1B0]`；
4. `0xBBAD7D` 调 `0xBBAF00`——**该函数只做范围检查与浮点比较**（`cmp eax,0xA`、
   `cmp eax,2`、`fcomp`），**完全不写容器**；
5. `0xBBAD86` 调 `0xBBA8A0` 去查 **key=0 的 1288 字节**——查不到，返回 0；
6. `0xBBADCD` 写 `[+0x1A0] = 5`（失败码）。

**第 2 步写入 136 字节，第 5 步却要求 1288 字节，两者自相矛盾。**
这说明 `0xBBAD40` 在**当前调用方式**下本来就不该成功——它可能是"旧路径"，
真正的填充发生在别处，而 pump 现在走的是这条旧路径。

#### 另一个可能：`0xBBAD40` 的调用参数不对

`0xBAE735` 调用它时传的是：

```
[ebp+8]  = lobby[0xC]        （接口对象，非空）
[ebp+0xC] = &[ebp-0x658]     （局部缓冲）
[ebp+0x10], [ebp+0x14] = 5 和一个浮点常量
```

而 `0xBBAD40` 用 `[ebp+0xC]` 作为 `rep movsd` 的源，只拷 136 字节。
若正确用法应当由调用方先把 1288 字节准备好，那么问题就在调用方
（`0xBAE6C0`–`0xBAE750` 那段的准备逻辑），而不是被调方。

#### 结论与下一步

容器查找需要一条 **{类型 0x14, 子类型 2, key 0, 长度 1288}** 的记录，而当前
代码路径只准备 136 字节。两种解释：

1. **调用方准备不足**：`0xBAE6C0` 附近应当把 1288 字节准备好，但只给了 136；
2. **走的不是这条路**：`0xBBAD40` 是历史遗留，真正的登记在别处。

验证方式很直接：在 `0xBBAD40` 入口读 `[ebp+0xC]` 指向的缓冲，看它后面
1152 字节（1288−136）是什么内容——若全是 0 或垃圾，说明调用方确实没准备；
若像有效数据，说明拷贝长度写死错了。

这是本轮之后最小的一步，且能直接区分两种解释。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.54"),
                         ("HANDOFF-CURRENT.md", "### 15.42")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.54", "### 15.42")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
