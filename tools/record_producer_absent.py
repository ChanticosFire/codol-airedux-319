"""Record round 49: the pump runs every frame but the status producers never run."""
from pathlib import Path

TEXT = """
### 12.63 ★★★ pump 每帧都在跑，但两个状态写入分支**从不执行**（2026-10-23 16:2x）

#### 先纠正 §12.61

§12.61 根据「把 `[obj1+0x130]` 改成 0 之后 120 秒毫无变化」推断 pump 只跑一次。
用 `tools/count_calls.py` 在 `0xBAD800` 入口装计数器（重放 `55 8B EC 6A FF 68` +
4 字节立即数，共 10 字节），30 秒实测：

```
[pump] calls = 30, 59, 89, 119, 148, 178, 208, 227, 401, 594, 784, 973,
              1162, 1352, 1541
```

**pump 30 秒被调用 1541 次，约 51 次/秒。** 同一轮里 FE 主循环 `0x621753`
15 秒 335 次（约 22 次/秒）。§12.61 的"只跑一次"是**错的**，那条结论作废。

#### 但两个写入分支都是 0 次

在写 2 与写 3 的指令上各装一个计数器（各重放完整的 10 字节
`C7 83 20 01 00 00 <imm32>`）：

```
[write2] 0xBBA569  total after 12s = 0        <- [obj1+0x120] = 2
[write3] 0xBBA62B  total after 12s = 0        <- [obj1+0x120] = 3
```

**两个都是 0。** 这说明 `0xBBA4xx`–`0xBBA6xx` 这一段代码**根本没有被执行**，
而 `[obj1+0x120]` 实测确实是 3——所以那个 3 是**启动阶段**由别处写入的，
之后再也没有任何代码改动它。

#### 至此所有观测都能一致解释了

| 观测 | 解释 |
|---|---|
| pump 每帧跑 1541 次/30s | FE 循环在跑，`[lobby+0x1F4]==1` 恒成立，于是每帧调 pump |
| `[lobby+0x1F4]` 恒为 1 | pump 每帧走到 `0xBAE781`/`0xBAE7AA` 写 1 |
| `[obj1+0x120]` 恒为 3 | 启动时写一次，生产者 `0xBBA4xx` 之后从未运行 |
| `[obj2+0x1A0]` 恒为 5 | 同上，`0xBBADCD` 失败码也是启动期产物 |
| 改 `[obj1+0x130]` 无效 | pump 只**读** `0x120` 做判断，从不重算它 |
| `0xBAE1AC` 从未执行 | 它要求 `[obj1+0x120]==2`，而该值永远是 3 |

**pump 是一个纯消费者**：每帧读取两个状态字段，据此决定写 1 还是写 2。
而**状态的生产者**（`0xBBA4xx` 那一段）在我们的运行里从未被调用。

#### 这改变了整个问题的性质

之前一直想"让 pump 成功"，方向就错了——pump 的逻辑本身没问题，它每帧都在
忠实执行。真正缺的是**让状态字段达到目标值的那段代码先跑一遍**。

具体来说，需要让注册 **{类型 0x14, 子类型 2, key 0, 长度 1288}** 记录的那段
代码（`0xBBA4xx`–`0xBBA760` 这一族）被执行一次，把 `[obj1+0x120]` 从 3 推到 2、
把 `[obj2+0x1A0]` 从 5 推到 4。

#### 下一步

1. 找 `0xBBA4xx` 所在函数的**入口**（向前搜索 `55 8B EC` 或 `CC` 填充边界）；
2. 用 `find_calls.py` 找它的**调用者**，确认调用条件；
3. 若调用条件依赖某个服务应答或某个初始化步骤，把这个条件补上。

这是目前最直接的一条路：**与其让消费者满意，不如让生产者跑一次。**

#### 工具

`tools/count_calls.py`（本轮新增，可复用）：

```bash
python tools/count_calls.py --at 0xBAD800 --orig 558bec6aff6897fec800 --label pump --secs 30
```

它把目标地址前 N 字节换成 `jmp cave`，cave 里 `pushfd/pushad` → `inc [counter]`
→ `popad/popfd` → 重放被替换的原始字节 → 跳回，**不改变任何寄存器与标志位**。
这是本项目第一个经得起自检的观测工具——前三次"没观测到"（§12.55、§12.56、
§12.61）都是工具或推断本身的错误。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.63"),
                         ("HANDOFF-CURRENT.md", "### 15.51")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.63", "### 15.51")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
