"""Record round 35: the 5 is the failure code written by 0xBBAD40's own failure branch."""
from pathlib import Path

TEXT = """
### 12.53 ★★★ `[obj2+0x1A0] = 5` 是 `0xBBAD40` 自己的失败码（2026-10-23 10:4x）

#### 状态机全貌

`obj2`（即 `[lobby+0x1FC]` 那个 440 字节容器）的 `+0x1A0` 字段是一台小状态机，
所有写入点都在 `0xBBA` 段，已全部定位：

| 写入值 | 地址 | 语义 |
|---|---|---|
| **0** | `0xBBA871`（构造） | 初始 |
| **1** | `0xBBAD95` | `0xBBAD40` **成功**登记 |
| **4** | `0xBBAD10`、`0xBBA951`、`0xBBA97D`、`0xBBA9F5` | **完成** |
| **5** | `0xBBAAAC`、`0xBBADB0`、**`0xBBADCD`**、`0xBBAC3E`、`0xBBACF4` | **失败** |

关键的一条：`0xBBADCD` 正是 `0xBBAD40` 内部的失败分支。回看该函数：

```asm
0xBBAD86  call 0xBBA8A0
0xBBAD8B  cmp al, 1
0xBBAD8D  jne 0xBBADCD          ; 失败 -> 0xBBADCD
0xBBAD8F  lea ecx, [ebx + 0x1a8]
0xBBAD95  mov dword ptr [ebx + 0x1a0], 1     ; 成功
...
0xBBADCD  mov dword ptr [ebx + 0x1a0], 5     ; ★ 失败
```

#### 完整因果链（终于闭合）

```
pump 0xBAD800
  └─ 0xBBAD40 登记服务器条目
       ├─ 成功 -> [+0x1A0] = 1
       └─ 失败 -> [+0x1A0] = 5      ← 我们在这里
  └─ pump 检查 [+0x1A0] == 4
       5 != 4  ->  jne 0xBAE5DB（遍历）-> 0xBAE781 -> 写 [lobby+0x1F4] = 1
```

而 `0xBBAD40` 失败的根源，就是 §12.32/§12.39 追过的那条：
`0xBBA8A0` → `0xBBA760(this, key=0, 1288 字节)` 在**每帧新建的空容器**里查不到数据。

#### `obj1` 同理

`[obj1+0x120]` 的写入点：

| 值 | 地址 |
|---|---|
| **2**（目标） | `0xBBA569` |
| **3**（当前） | `0xBBA62B` |

`0xBBA62B` 与 `0xBBA569` 相隔 0xC2 字节，属于同一函数的不同分支——
2 是"完成"，3 是另一种中间/失败态。当前是 3，同样未达目标。

#### 这终结了"差 1"的解释

§12.51 观察到"两个字段各差 1"，当时只能描述现象。现在可以确定：

- `obj2+0x1A0`：`5` 是**显式的失败码**，不是"进行中"；
- `obj1+0x120`：`3` 是另一条分支的落点，同样不是"进行中"。

**两者都是失败态**，因此 pump 每帧走到 `jne` 分支是必然的，不是时序问题。

#### 唯一剩下的问题

`0xBBAD40` 为什么失败 → `0xBBA760(key=0, 1288B)` 为什么查不到。

这已追到 §12.30/§12.32 的结论：容器每帧新建且为空，填充它的代码在
`0xBBAD40` 内部（`0xBBAD6B rep movsd` 把 136 字节从局部拷到 `[容器+4]`），
但拷贝的目标是 `+4`，而 `0xBBA760` 查的是 key=0 的 1288 字节记录——
**136 ≠ 1288**。

#### 新的、具体的猜测

`0xBBA760(this, 0, out)` 期望 **1288 字节**，而 `0xBBAD40` 只准备 **136 字节**。
两者相差 **9.47 倍**。若 `0xBBA760` 实际是「把容器内容序列化到 out」而非
「查询」，那么 1288 可能是**最大容量**而非精确长度要求。

这一点值得单独验证：读 `0xBBA760` 里 `0xBC1C20` 返回后对长度的**具体检查方式**
（是 `==` 还是 `<=`）。若为 `<=`，则 136 字节也许足够，失败原因就另在别处。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.53"),
                         ("HANDOFF-CURRENT.md", "### 15.41")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.53", "### 15.41")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
