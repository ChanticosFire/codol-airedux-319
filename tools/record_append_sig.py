"""Record round 53: the append function signature and its internal failure branches."""
from pathlib import Path

TEXT = """
### 12.67 `0xBBA3F0` 的完整签名与内部分支（2026-10-23 18:5x）

#### 签名

```asm
0xBBA3F0  push ebp / mov ebp,esp / push -1 / push 0xC90FBE
0xBBA3FA  mov eax, fs:[0] / push eax / sub esp,0x248
0xBBA41E  mov esi, [ebp + 0x90]     ; 参数 2：源数组指针
0xBBA424  mov ebx, ecx              ; this
0xBBA426  cmp dword [ebx + 0x120], 1
0xBBA434  jne 0xBBA635              ; ★ 状态 != 1 -> 直接跳到函数尾部
0xBBA43A  mov edi, [ebp + 0x94]     ; 参数 3：要追加的条目数
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3              ; ★ 条目数 <= 0 -> 走另一分支
```

即 **`bool Add(this, srcArray, count)`**：

- `[ebp+0x90]` = 源数组
- `[ebp+0x94]` = 条目数
- 只有 `count > 0` 且 `status == 1` 才真正追加

#### 追加的两道失败出口

```asm
0xBBA453  lea eax, [ebx + 4]
0xBBA456  push eax
0xBBA457  lea ecx, [ebp + 8]
0xBBA45E  call 0xB75440             ; 检查 1
0xBBA463  test al, al
0xBBA465  je 0xBBA5A5               ; ★ 失败 -> 0xBBA5A5

0xBBA46B  lea ecx, [ebp - 0x254]
0xBBA471  push ecx / push 0 / push edi / push esi
0xBBA47C  call 0xBC1A50             ; 检查 2 / 实际追加
0xBBA481  test al, al
0xBBA483  je 0xBBA5A5               ; ★ 失败 -> 0xBBA5A5
```

`0xBBA5A5` 与 `0xBBA5C3` 两条出口都汇到 `0xBBA5EC`（读容量 `+0x124`），
再经 `0xBBA61A cmp [ebx+0x130], eax` / `jb 0xBBA635` 决定是否写 3：

```asm
0xBBA5EC  movzx ecx, byte ptr [ebx + 0x124]    ; 容量
0xBBA5FC  cmp eax, ecx
0xBBA5FE  jae 0xBBA613
0xBBA61A  cmp dword [ebx + 0x130], eax
0xBBA620  jb 0xBBA635                          ; 未满 -> 正常返回
0xBBA62B  mov dword [ebx + 0x120], 3           ; 满了 -> 写 3
```

#### 两个调用者

`find_calls.py 0xBBA370`（与 `0xBBA3F0` 同族的另一个入口）返回**两个**调用点，
都在 pump 内部：

```
call at 0x00BADD0A
call at 0x00BAE6A8
```

这修正了 §12.65 的一个说法：`0xBBA370` **有调用者**，只是观测窗口内计数为 0
（同样是"只在启动期跑过"的时序问题，与 §12.65 结论一致）。

#### 由此得到的因果重构

`Add()` 每帧被调用（`0xBAE276`），携带 `count >= 1`，于是每帧追加 1 条；
索引涨到容量后 `0xBBA62B` 写 3，之后 `0xBBA434 jne` 使函数永久短路。

**真正要回答的是：`[ebp+0x94]`（count）为什么每帧都 > 0？**
两处调用者 `0xBADD0A` / `0xBAE6A8` 中必有一处每帧构造了一个非空的追加请求。

下一轮直接反汇编这两个调用点之前的参数准备代码（`0xBAE680` 与 `0xBADC90`
附近），确认请求来源是"某个容器每帧被重建并视为新数据"，还是"某个计数没有清零"。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.67"),
                         ("HANDOFF-CURRENT.md", "### 15.55")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.67", "### 15.55")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
