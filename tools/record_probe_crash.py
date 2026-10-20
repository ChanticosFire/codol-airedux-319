"""Record round 64: the probe address was not an instruction boundary and crashed the client."""
from pathlib import Path

TEXT = """
### 12.78 探测地址不是指令边界，客户端崩溃（2026-10-24 01:0x）

#### 发生了什么

计划在"失败路径"`0xC7406E` 装计数器。装之前读了该处 8 字节：

```
0xC7406E: c3 8b 4d f4 64 89 0d 00
```

**首字节 `C3` 是 `ret`。** 这说明 `0xC7406E` **不在函数体内**，而是函数返回之后的
位置。把 `ret` 换成 `jmp cave` 后，cave 里重放这 8 字节并跳回 `0xC74076`，
整段后续代码被破坏，客户端随即退出（计数器读不到、`[obj+0x20]` 也没来得及取样）。

#### 这是我的操作错误

`count_calls.py` 只在字节**匹配**时才装 hook，它确实匹配到了 `c38b4df4…`，
所以工具没有报错。但**我在指定地址前没有确认它是一条指令的起点**。

正确做法：

1. 先用 `dump_code.py` 从**已知干净的边界**（例如函数入口 `0xC73FB0`）反汇编，
   让 capstone 自己给出每条指令的地址，再从输出里挑跳转目标；
2. 或者用 `raw bytes + 手工解码`，但必须从函数入口一路解下来，不能跳着取。

上一轮我用的是"从 `0xC73FF0` 开始手工解码"，解到 `0xC74020` 左右就停了，
`0xC7406E` 这个地址是从**更早一轮的 capstone 输出**里抄来的——而那次 capstone
在 `0xC74000` 处已经错位，输出不可信。**我把一个来自错位反汇编的地址当成了真值。**

#### 教训

本项目里已经出现过的同类错误：

| 轮次 | 错误 | 后果 |
|---|---|---|
| 37 | `CONTEXT` 结构 204 字节（应为 716） | 采样全部无效 |
| 38 | 64 位 Python 读 32 位进程 | 采样全部无效 |
| 61 | 把 `0xBBA5C3` 的跳转范围读反 | 三轮误判 |
| **64** | **把错位反汇编里的地址当指令边界** | **客户端崩溃** |

共同点：**在"地址/结构/顺序"这类最基础的事实上凭印象而不是凭验证。**

#### 下一步（更稳妥的做法）

放弃"从错位输出里抄地址"。改为：

1. 从 `0xC73FB0`（函数入口，已知正确）完整反汇编到 `0xC74090` 之后，
   用 capstone 输出的地址列表作为唯一真值来源；
2. 若 capstone 中途错位，就只采用"错位点之前"的指令，并**明确记录可信边界**；
3. 只有在确认是跳转目标的地址上装 hook。

具体目标不变：判定 `0xBB15E0` 的返回值是 `>= 0`（成功但数据为空）还是负值（失败）。
替代手段：直接给 `0xBB15E0` 的**入口**装"调用计数器"（入口地址可靠，
第 62 轮已从 `0xC7400E` 的 call 解析得到），再给它的 `ret` 前后装一个
"返回值快照"——但后者需要写更复杂的探针。

**更简单的替代**：给 `0xBB15E0` 入口装计数器（确认它被调用），
再直接读它写出的容器内容。如果容器 `+0x84` 是 0 而函数被调用了 N 次，
就说明"成功但数据为空"是更可能的情况。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.78"),
                         ("HANDOFF-CURRENT.md", "### 15.66")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.78", "### 15.66")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
