"""Record round 145: the real guard is cmp eax,2 - the ladder requires status 2, which requires the ladder."""
from pathlib import Path

TEXT = """
### 12.160 ★★★ 真正的守卫：`0xBAE30F cmp eax,2`——一个自我强化的死锁（2026-10-25 20:5x）

#### 完整代码

```asm
0xBAE2D0  …                          ; （前一指令的尾部）
0xBAE2D2  test al, al
0xBAE2D4  jne 0xBAE2DD
0xBAE2D6  mov byte ptr [ebp-0x986], 1      ; 标志置 1
0xBAE2DD  cmp byte ptr [ebp-0x988], 0      ; ★ 检查 A
0xBAE2E4  je 0xBAE7B4                       ; A == 0 -> 复位
0xBAE2EA  cmp byte ptr [ebp-0x989], 0      ; ★ 检查 B
0xBAE2F1  je 0xBAE7B4                       ; B == 0 -> 复位
0xBAE2F7  cmp byte ptr [ebp-0x986], 0      ; ★ 检查 C
0xBAE2FE  je 0xBAE7B4                       ; C == 0 -> 复位
0xBAE304  mov ecx, dword ptr [ebx+0x1F8]   ; obj1
0xBAE30A  call 0xBBA1E0                     ; 读 obj1 状态
0xBAE30F  cmp eax, 2                        ; ★★ 检查状态是否等于 2
0xBAE312  jne 0xBAE5DB                      ; ★★ 不等于 2 -> 跳到 0xBAE5DB
```

#### 这才是真正的守卫

前面三轮（§12.157/§12.158/§12.159）分别排除了：

- `[lobby+8]`（实测为 1，守卫生效）
- `0xBAE4CB` 的数组计数（只跳过搬运）
- 前三条 `je 0xBAE7B4`（它们只跳到复位，属于更外层的先决条件）

**真正的阻断点是 `0xBAE30F`：它读取 `obj1` 的状态并要求等于 2，
不等则 `jne 0xBAE5DB` 跳过整个"推进 `1F4`"的段落。**

#### `0xBAE5DB` 在写 2 之后

`0xBAE587` 是写 2，`0xBAE5DB` 比它更靠后。
**所以这条 `jne` 一旦成立，`0xBAE587` 就被跳过——`1F4` 永远保持 1。**

#### 这是一个自我强化的死锁

```
要让 1F4 变成 2   -> 必须执行到 0xBAE587
要执行到 0xBAE587 -> 必须先通过 0xBAE30F（状态 == 2）
而状态变成 2      -> 需要 Add 的成功分支执行写 2（0xBBA569），但哨兵证明它从不执行
```

**即：**

- **`1F4 -> 2` 要求 `obj1[0x120] == 2`**
- **`obj1[0x120] -> 2` 要求 `Add` 的成功分支**
- **`Add` 的成功分支从不执行**（§12.140 哨兵证明）

**三者构成一个闭环，任何一环不打开，整个系统就停在"状态 1 / `1F4` = 1"。**

#### 这把问题彻底归结到一个点

**唯一需要打开的是：让 `Add` 的成功分支执行一次**（即 `0xBBA569` 写 2）。

而 `Add` 的成功分支需要：
1. `[ebp+0x94]`（count）非零——**实测 91.4% 是 3** ✔
2. `jle` 不跳——**取反实验证明 `edi > 0`** ✔
3. 成功分支内部不异常——**但 §12.150 强制进入后仍到不了写 2** ✘

**所以问题回到那个"成功分支内部为何到不了写 2"——这是 §12.150 留下的未解点。**

#### 但注意一个此前被忽略的事实

`0xBAE312 jne 0xBAE5DB` 跳到的 `0xBAE5DB` **不是复位路径**，
它只是跳过 `1F4` 的推进。

**所以即使状态是 1，`pump` 仍会继续执行 `0xBAE5DB` 之后的代码。**

**值得看看 `0xBAE5DB` 之后做了什么——也许那里才是真正影响 FE 梯的地方，
而 `1F4` 只是一个表象指标。**

#### 下一步

1. **反汇编 `0xBAE5DB` 之后**，看跳过去之后执行什么；
2. 同时确认 `0xBAE2DD`/`0xBAE2EA`/`0xBAE2F7` 三个字节标志在正常流程中是否为非零
   （若它们中任何一个为 0，同样会复位）。

**第 1 条更关键：它可能揭示"即使 `1F4` 不是 2，前端仍有别的推进机制"。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.160"),
                         ("HANDOFF-CURRENT.md", "### 16.48")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.160", "### 16.48")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
