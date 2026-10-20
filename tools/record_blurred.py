"""Record round 150: with status 2 the screen shows a blurred background and no UI elements."""
from pathlib import Path

TEXT = """
### 12.165 状态为 2 时的画面：模糊背景，无界面元素（2026-10-26 00:2x）

#### 本轮观测

```
patched 0xbba465  filter A
patched 0xbba483  filter B
  t= 10.14  status= None  idx= None  1F4=1  FE=5  G1=0  dw=0
  t= 15.36  status=    2  idx=    0  1F4=1  FE=5  G1=0  dw=2

samples with status==2: 246
final: status=2  1F4=1  FE=5  G1=0

=== after screenshot ===
  dw=5  FE=5  G1=0  1F4=1
  obj1 status=2  idx=0
```

**`dw` 这次走到了 5（上一轮是 3），`status` 稳定为 2，`idx` 为 0。**

#### 截图内容

画面是一片**模糊的蓝色背景**（雾状的浅蓝渐变、零散的几何线条与数字碎片），
**没有任何界面元素**——没有代号输入框、没有按钮、没有文字标签。

**这与 §12.55 记录的那张完整大厅截图（玩家名 `AdministraClient`、可见大厅 UI）明显不同。**

#### 这说明了什么

1. **状态变 2 确实改变了流程**——画面不再停在代号页；
2. **但客户端卡在了"过渡"状态**——既不是代号页，也不是可用的大厅；
3. **`FE` 仍是 5、`G1` 仍是 0、`1F4` 仍是 1**——更上层的状态变量一个都没动。

**所以 `obj1` 到达 2 只是让 `Add` 内部正常了，并没有推动 FE 梯。**

#### `1F4` 为何仍是 1

`0xBAE30F cmp eax,2` 现在应当通过（状态确实是 2），但 `0xBAE587` 显然仍未执行。

**回到 §12.145/§12.160 的结构**：`0xBAE2DD`、`0xBAE2EA`、`0xBAE2F7` 三处
`cmp byte [ebp-…], 0` / `je 0xBAE7B4` 是 `0xBAE30F` **之前**的三道检查。

**它们检查的是 pump 栈上的三个字节标志（`[ebp-0x988]`、`[ebp-0x989]`、`[ebp-0x986]`）。**

**若其中任何一个为 0，流程直接跳到 `0xBAE7B4` 复位，根本到不了 `0xBAE30F`。**

**`[ebp-0x986]` 在 `0xBAE2D6` 被置 1（当 `0xBAE2D2` 的 `al != 0` 时）；
`[ebp-0x988]` 与 `[ebp-0x989]` 的来源尚未确认。**

#### 下一步

**需要知道这三个字节标志的实际取值。**

由于它们是 pump 帧上的局部变量，**无法用轮询读取**（地址随帧变化）。

**可行方法**：**哨兵法改 `0xBAE2DD` 的 `cmp` 立即数**——
用它来推断：把 `cmp byte [ebp-0x988], 0` 改成 `cmp byte [ebp-0x988], 0xFF`
（即要求等于 255 才不跳），若行为改变（`1F4` 变成 2），说明该标志原本就是 0；
若行为不变，说明它是非零。

**三条依次测试，就能确定哪个标志是 0。**

**但这需要三轮实验。更快的办法**：一次性把三条 `je` 全部 NOP 掉，
看 `1F4` 是否变成 2——若是，则确认卡点在这三道检查；再逐个恢复以定位具体是哪一条。

**这只需两轮实验。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.165"),
                         ("HANDOFF-CURRENT.md", "### 16.53")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.165", "### 16.53")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
