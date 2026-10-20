"""Record round 51: all eight writers of +0x120, and why the counters missed the startup one."""
from pathlib import Path

TEXT = """
### 12.65 `+0x120` 的八个写入点全部定位；计数器装晚了（2026-10-23 17:4x）

#### 全量扫描结果

对 `0xBB0000`–`0xBBC000` 扫所有形式的 `+0x120` 写入（`89 /r`、`C7 /r`、`FF /0`）：

| 地址 | 形式 | 写入值 |
|---|---|---|
| `0xBB76BB` | `89 83 20 01 00 00` | `eax`（构造时 `xor eax,eax` → **0**） |
| `0xBBA0A4` | `modrm=86`（esi） | 寄存器值 |
| `0xBBA1C7` | `modrm=83`（ebx） | 寄存器值 |
| `0xBBA2B6` | `C7 86 … 04` | **4** |
| `0xBBA33E` | `C7 86 … 00` | **0** |
| `0xBBA3D2` | `C7 83 … 01` | **1** |
| `0xBBA569` | `C7 83 … 02` | **2**（已测 0 次） |
| `0xBBA62B` | `C7 83 … 03` | **3**（已测 0 次） |

**没有任何 `inc` / `or` / `add` 形式的写入**，所以 1/2/3/4 只可能来自上表那几条
`C7` 立即数指令。

#### 矛盾及其解释

实测 `[obj1+0x120] = 3`，但唯一写 3 的 `0xBBA62B` 计数为 0。两者必须调和，
只剩下一个可能：

**测试时计数器安装得太晚。** `count_calls.py` 是在 `dw=5` 之后约 30 秒才装上
hook 的，而写 3 若发生在**启动阶段**（`dw` 到 5 之前或刚到时），那时候 hook
还不存在，自然记录不到。

同理，写 1 的 `0xBBA3D2` 所在函数 `0xBBA370` 测出 0 次，也是同一原因——
它同样只在启动期运行。

#### 这解释了为什么状态停在 3

设计意图很可能是：

```
构造 → 0
启动期某处 → 1        （就绪，可添加）
生产者 0xBBA3F0 检查 ==1 → 添加条目 → 2（成功）或 3（满/失败）
```

而现在 `0x120` 停在 3，说明启动期有一次路径把它推到了 3，之后生产者每帧看到
`!= 1` 就直接返回，**永远不会再改变它**——一个自锁状态。

#### 下一步：把 hook 提前到启动阶段

需要让计数器在**客户端启动前**就装好，而不是等 `dw=5`。两条路：

1. **改 `patch_runtime.py`**：它已经在启动前写补丁，只要支持"补丁即 hook"
   ——把 `0xBBA62B` 前 10 字节替换成跳到我方代码的 `jmp`，而那段代码
   （`inc [counter]` + 重放原指令 + `jmp` 回）可以预先写在镜像的空白区；
2. **用独立的启动器**：先 `CreateProcess` 挂起，写 hook，再 `ResumeThread`。

第 1 条更省事：`patch_runtime.py` 已经是"启动前打补丁"的流程，只需把
trampoline 的机器码算好写进去。计数器地址可以固定选在镜像 `.data` 的一段
未用区域（例如 `0x82E1400` 附近），不需要 `VirtualAllocEx`。

#### 本轮确立的事实

| 事实 | 证据 |
|---|---|
| `+0x120` 在 `0xBB0000`–`0xBBC000` 内共 8 个写入点 | 全量模式扫描 |
| 其中写 1/2/3/4 的都是 `C7` 立即数形式 | 同上 |
| 没有 `inc`/`or`/`add` 形式 | 同上 |
| 生产者 `0xBBA3F0` 每秒被调 20 次 | `count_calls.py` 310 次/15s |
| 生产者入口要求 `0x120 == 1` | 反汇编 `0xBBA426` |
| 写 1 的函数 `0xBBA370` 在观测窗口内 0 次 | `count_calls.py` |

下轮目标：把计数器提前到启动前安装，抓出启动期的那一次写入，确认它走的是
`0xBBA62B`（写 3）还是别的路径。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.65"),
                         ("HANDOFF-CURRENT.md", "### 15.53")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.65", "### 15.53")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
