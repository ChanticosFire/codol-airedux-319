"""Record round 32: 0xBAE182 is reached either way, so the write-1 path has another entry."""
from pathlib import Path

TEXT = """
### 12.50 `0xBAE182` 在 `0xBAF040` 成败两条路上都会被到达（2026-10-23 09:2x）

#### 成功分支的完整形态

从 `0xBAE0F0`（干净边界）反汇编：

```asm
0xBAE0ED  call 0xBAF040             ; 判定
0xBAE0F2  test al, al
0xBAE0F4  je 0xBAE10D               ; 失败 -> 0xBAE10D
0xBAE0F6  lea edx, [ebp - 0x5d0]    ; 成功：准备数据
0xBAE0FC  push edx
0xBAE0FD  lea ecx, [ebp - 0x6e0]
0xBAE103  call 0xB75440
0xBAE108  call 0xBA4B20
0xBAE10D  push 0xa8                 ; ★ 两条路在此汇合（分配 168 字节）
0xBAE112  call 0xB742C0
0xBAE124  test eax, eax
0xBAE126  je 0xBAE148
0xBAE128  mov ecx, [ebx + 0xb4]
0xBAE12F  lea edx, [ebp - 0x5d0]
0xBAE13F  call 0xB75060             ; 构造对象
0xBAE144  mov esi, eax
0xBAE146  jmp 0xBAE14A
0xBAE148  xor esi, esi
0xBAE14A  mov [ebp - 0x99c], esi
0xBAE150  test esi, esi             ; 只是判断是否要释放
0xBAE152  je 0xBAE15E
0xBAE154  lea edx, [esi + 4]
...
0xBAE176  je 0xBAE182               ; 释放后跳到 0xBAE182
0xBAE182  mov ecx, [ebx + 0x1f0]    ; ★ 大厅连接对象（实测 0x36c9ec60 非空）
0xBAE193  mov ecx, [ebx + 0x1f0]
0xBAE199  lea eax, [ebx + 0x184]
0xBAE1A1  lea ecx, [ebx + 0x1a0]
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword ptr [ebx + 0x1f4], 2    ; ★ 写 2
```

**关键结论：`0xBAE182` 是成功分支的必经点，而它由 `0xBAE10D` 无条件到达，
`0xBAE10D` 又是 `0xBAF040` 失败时的跳转目标。** 也就是说 `0xBAF040` 的成败
**不影响**是否会写 2。

#### 这意味着什么

之前（§12.24/§12.31）认为「`0xBAF040` 失败 → 写 1」，**这个因果链是错的**。
写 1 的 `0xBAE74E` / `0xBAE766` 一定在**另一条**入口分支上，而不是这条线性路径。

`0xBAD800` 是一个约 4 KB 的大函数，有多处 `jmp 0xBAE7xx` 汇聚到写 1 的尾部
（`0xBAE7AA` 也写 1），说明它是**多分支状态机**，每条分支对应一种事件。
我们当前走的既不是 `0xBAE182`（写 2）也不是 `0xBAE7AA`（写 1）——需要先确定
实际执行的是哪条。

#### 下一步（改为观测而非推理）

在 `0xBAE1AC`（写 2）与 `0xBAE74E` / `0xBAE7AA`（写 1）这三处各放一个
**只记录不干预**的探针（写一个字节到约定地址），运行一次即可知道 pump 实际
走的是哪条分支。这比继续静态推理更快，也避免再次基于错误前提走远。

工具上可以复用 `ui_activate.py` 的 trampoline 框架：把目标地址的指令替换成
`jmp cave`，在 cave 里记录后执行原指令再跳回。

#### 已排除的假设（累计）

| 假设 | 结论 |
|---|---|
| 136 字节是加密密钥 | 否，是数组记录（§12.49） |
| 136 字节是服务器地址块 | 否，同上 |
| `svc71/task4` 应答形状不对 | 否，数组已存入 127.0.0.1 条目 |
| `0xBAF040` 失败导致写 1 | **否，两条路都到 0xBAE182** |
| 强写 `[lobby+0x1F4]=2` 能推进 | 否，它是崩溃源（§12.48） |
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.50"),
                         ("HANDOFF-CURRENT.md", "### 15.38")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.50", "### 15.38")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
