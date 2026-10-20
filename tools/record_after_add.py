"""Record round 154: the flag is set right after Add, based on the status it produced."""
from pathlib import Path

TEXT = """
### 12.169 ★★★ `[ebp-0x989]` 的置 1 条件紧跟在 `Add` 之后（2026-10-26 02:2x）

#### 完整序列

```asm
0xBAE270  mov ecx, dword ptr [ebx+0x1F8]   ; obj1
0xBAE276  call 0xBBA3F0                     ; ★ Add
0xBAE27B  mov ecx, dword ptr [ebx+0x1F8]   ; obj1
0xBAE281  call 0xBBA1E0                     ; 读状态（getter）
0xBAE286  cmp eax, 1                        ; ★ 状态 == 1 ？
0xBAE289  je 0xBAE292                       ; 是 -> 跳过置位
0xBAE28B  mov byte ptr [ebp-0x989], 1       ; ★ 不是 1 -> 标志置 1
0xBAE292  cmp dword ptr [ebx+0x1FC], edi    ; ★ 另一个分叉
0xBAE298  je 0xBAE2DD                       ; 相等 -> 跳到守卫处
0xBAE29A  push esi
…
```

#### 三个关键点

**1. 标志的置位条件非常明确**

```
Add(obj1) -> 读 obj1 状态 -> 状态 != 1 ? 置标志 : 不置
```

**§12.164 已经把状态做到 2 并稳定保持——所以这个标志现在应当为 1。**

**2. `0xBAE298` 是另一个分叉**

`cmp dword [ebx+0x1FC], edi` / `je 0xBAE2DD`。

- `edi` 在 pump 入口被设为 `ebx+8`（`0xBAD830 lea edi,[ebx+8]`）；
- `[ebx+0x1FC]` 是服务器列表对象指针。

**若两者相等 → 跳到 `0xBAE2DD`（三道守卫的入口）；不等 → 走 `0xBAE29A` 的分支。**

**`[ebx+0x1FC]` 通常是个堆指针，`ebx+8` 是栈/对象内部地址，两者相等的情形罕见。**

**所以正常情况下会走 `0xBAE29A`——而那条路可能绕过整个守卫段。**

**3. 这与 §12.164 的结果可能矛盾**

若 `0xBAE29A` 分支会绕过守卫，那状态变 2 后 `1F4` 应当能推进——
**但实测 `1F4` 仍是 1。**

**所以 `0xBAE29A` 之后的分支应当最终仍汇入 `0xBAE2DD` 或别的复位点。**

#### 下一步

**反汇编 `0xBAE292`–`0xBAE2E0`**，看清：

1. `0xBAE29A` 分支做了什么、最终去哪；
2. 它是否绕回 `0xBAE2DD`（守卫入口）；
3. `[ebx+0x1FC]` 与 `edi` 的比较结果在正常情况下是什么。

**这能确定状态变 2 之后流程究竟走到哪一步。**

**同时值得注意**：`0xBAD846 cmp [ebx+0x1F4],1` / `jne 0xBAE7C6` 要求 `1F4 == 1`。
**而 `0xBAE587` 会把 `1F4` 设为 2。若真的设成 2，下一帧 pump 就会直接复位返回——
即 `1F4 = 2` 只能存活一帧（§12.168 的"脉冲"推断）。**

**所以真正该测的判据是"`1F4` 是否曾经等于 2"，而不是"是否保持为 2"。**
**而 20ms 的采样间隔恰好等于一帧（51 帧/秒 ≈ 20ms），很可能抓不到。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.169"),
                         ("HANDOFF-CURRENT.md", "### 16.57")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.169", "### 16.57")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
