"""Record round 151: nop'ing the three pump guards crashes the client."""
from pathlib import Path

TEXT = """
### 12.166 消除三道 pump 守卫导致客户端崩溃（2026-10-26 00:5x）

#### 实验

在 §12.164 的两个 `Add` 过滤补丁之外，再加三个：

```
0xBAE2E4  0F 84 CA 04 00 00  ->  90 90 90 90 90 90   （pump guard A，[ebp-0x988]）
0xBAE2F1  0F 84 BD 04 00 00  ->  90 90 90 90 90 90   （pump guard B，[ebp-0x989]）
0xBAE2FE  0F 84 B0 04 00 00  ->  90 90 90 90 90 90   （pump guard C，[ebp-0x986]）
```

#### 结果

```
patched 0xbba465  Add filter A
patched 0xbba483  Add filter B
patched 0xbae2e4  pump guard A
patched 0xbae2f1  pump guard B
patched 0xbae2fe  pump guard C
  t=  0.00  status=None  idx=None  1F4=None  FE=2  G1=0  dw=0
  t= 10.04  status=None  idx=None  1F4=   1  FE=5  G1=0  dw=0
  process gone

samples with 1F4==2: 0
```

**客户端在 `dw` 仍为 0、`obj1` 尚未创建时就退出了。**

#### 这说明三道守卫是必要的保护

`0xBAE2DD`/`0xBAE2EA`/`0xBAE2F7` 检查的三个字节标志
（`[ebp-0x988]`、`[ebp-0x989]`、`[ebp-0x986]`）**不是冗余的**：
它们守护的是**后续代码对某些对象/数据的有效性假设**。

**强制跳过 → 代码在对象未就绪时访问它 → 访问违例 → 进程退出。**

（`obj1` 在 `t=10.04` 时仍是 `None`，说明崩溃发生在 `obj1` 创建之前的那段代码里。）

#### 所以正确做法不是跳过，而是满足

必须弄清这三个标志各自的含义与赋值来源，**让它们自然为非零**，
而不是用 NOP 绕过去。

#### 下一步：找三个标志的赋值点

它们是 pump 帧上的局部变量，偏移分别为 `-0x988`、`-0x989`、`-0x986`。

**用 `find_offset.py` 搜这三个 disp32 在 `0xBAD800`–`0xBAE000` 内的引用**，
就能找到所有读写点：

```
-0x988 = 0xFFFFF678  ->  78 F6 FF FF
-0x989 = 0xFFFFF677  ->  77 F6 FF FF
-0x986 = 0xFFFFF67A  ->  7A F6 FF FF
```

**找到写入点后，就能知道在什么条件下它们会变成非零，
从而判断我们环境里缺的是什么。**

**这比继续打补丁更接近根本。**

**注意**：`[ebp-0x986]` 已知在 `0xBAE2D6` 被置 1（当 `0xBAE2D2` 的 `al != 0` 时），
所以它的来源比较清楚；`-0x988` 与 `-0x989` 需要查。

**同时**：本轮崩溃也说明"一次性消除所有关卡"这种做法行不通——
必须逐个理解、逐个满足。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.166"),
                         ("HANDOFF-CURRENT.md", "### 16.54")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.166", "### 16.54")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
