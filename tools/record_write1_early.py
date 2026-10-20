"""Record round 114: the write of 1 also runs at dw==2 with obj1 present, so it can overwrite the 2."""
from pathlib import Path

TEXT = """
### 12.129 ★★★ `Init` 的写 1 也在 `dw==2` 执行，且此时 `obj1` 已存在（2026-10-25 04:5x）

#### 采样

在 `0xBBA3D2`（`mov dword ptr [ebx+0x120], 1`，10 字节 `C7 83 20 01 00 00 01`）
装计数器，同时读 `obj1` 指针与 `dw`：

```
[w1] n=0  eax=0x00000000  obj1=0x00000000  dw=0
[w1] n=1  eax=0x001AD005  obj1=0x37F21E80  dw=2     ← ★ 写 1 时 obj1 已存在
[w1] unreadable - process gone?
```

**写 1 在 `dw=2` 时执行了一次，此时 `obj1` 已经存在（`0x37F21E80`）。**

#### 与写 2 的关系

| 位置 | 何时执行 | 作用对象 | 次数 |
|---|---|---|---|
| `0xBBA569`（写 2） | `dw=2`（§12.108） | `obj1`（§12.128 `ebx == obj1`） | 1 次 |
| `0xBBA3D2`（写 1） | `dw=2`（本轮） | `obj1`（`obj1` 已存在） | 1 次 |

**两者都在 `dw=2` 阶段、都作用在 `obj1` 上、各执行一次。**

**所以它们的先后顺序决定了最终状态：**

- 若 **写 2 在前、写 1 在后** → 状态最终被改回 **1** → 之后空闲帧推进索引 → 写 3 ✔ **与观测一致**
- 若 **写 1 在前、写 2 在后** → 状态最终是 **2** → `Add` 永久短路 ✘ **与观测不符**

**实测最终是 3，因此"写 2 在前、写 1 在后"是唯一自洽的顺序。**

#### 这完整解释了全部现象

```
dw=2  t≈12-17   某次 Add 收到 count>0 -> 写 obj1[0x120] = 2 -> jne 返回
dw=2  t≈17      Init 运行 -> 写 obj1[0x120] = 1，索引清零
                （obj1 此时才被"正式初始化"）
dw=2-5          空闲帧：入口 check 看到 1 不短路 -> 索引反复 +1
dw=5+           索引到达容量 5 -> 写 3 -> 永久锁定
```

**关键洞察：`obj1` 在 `Init` 之前就已经能被 `Add` 写入（写 2），
而 `Init` 之后又把状态重置为 1——这是初始化时序上的一个竞态。**

#### 这也解释了为什么"调节应答应答内容/频率/容量"全部无效

- 应答内容/频率影响的是 `0xBB15E0` 的返回值（`esi`），进而影响 `count`；
- 但**只要那次 `Init` 在后面运行一次，任何写成功的 2 都会被抹掉**；
- 容量只影响索引何时满，不改变"状态被重置为 1"这个事实。

#### 下一步：验证顺序

两种做法：

1. **在同一轮里分别记录两个写入点的首次命中时刻**（需要两个 hook，风险高）；
2. **轮询 `obj1[0x120]`，从 `obj1` 出现开始，间隔 5ms**，寻找 `1 -> 2 -> 1` 的序列。
   §12.127 用过 20ms 没看到 2，但 5ms 更细；不过若写 2 与写 1 之间只隔几微秒，
   任何轮询都抓不到。

**更可靠的第三条路**：**直接测试"如果让 `Init` 不覆盖会怎样"**。

即在 `0xBBA3D2` 处做一个**实验性补丁**，把 `mov dword [ebx+0x120],1` 改成
`mov dword [ebx+0x120],ebx`（即 `C7 83 ...` → `89 9B 20 01 00 00`，
写入 `ebx` 自身指针，一个非 1 的值）——这样 `Init` 之后状态就不是 1，
`Add` 的入口检查会短路，状态得以保留。

**但这会破坏 `Init` 的语义**（后续依赖状态为 1 的代码会异常），风险较高。

**更安全的做法**：把 `0xBBA569`（写 2）改成写一个**不会被 `Init` 覆盖**的时机——
不可行，因为 `Init` 只写一次。

**最实用的方向**：既然 `Init` 只运行一次且在启动早期，而 `Add` 的写 2 也在早期，
**真正的问题是"哪个先"**。若能用一次实验确定顺序，就能判断是否需要干预。

下轮先用"分别记录首次命中时刻"的方式确定顺序。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.129"),
                         ("HANDOFF-CURRENT.md", "### 16.17")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.129", "### 16.17")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
