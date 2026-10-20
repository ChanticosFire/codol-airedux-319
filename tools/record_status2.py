"""Record round 149: status becomes 2 and holds - the first time since round 60."""
from pathlib import Path

TEXT = """
### 12.164 ★★★★ 状态变成 2 并保持：第 60 轮以来第一次越过卡点（2026-10-25 22:5x）

#### 实验

只打两个补丁（去掉哨兵，让 `0xBBA569` 写真实的 2）：

```
0xBBA465  0F 84 3A 01 00 00  ->  90 90 90 90 90 90   （消除过滤 A）
0xBBA483  0F 84 1C 01 00 00  ->  90 90 90 90 90 90   （消除过滤 B）
```

#### 结果

```
patched 0xbba465  filter A
patched 0xbba483  filter B
  t= 10.14  status= None  idx= None  1F4=1  FE=5  G1=0  dw=0
  t= 16.44  status=    1  idx=    0  1F4=1  FE=5  G1=0  dw=3
  t= 16.47  status=    2  idx=    0  1F4=1  FE=5  G1=0  dw=3

samples with status==2: 1883
final: status=2  1F4=1  FE=5  G1=0
```

#### 四项确认

1. **`obj1[0x120]` 从 1 变成 2 并稳定保持**（1883 次采样）——
   **这是第 60 轮以来第一次让状态越过 1**；
2. **`idx` 停留在 0**——写 2 之后 `jne 0xBBA5CA` 正确跳走，索引不再推进，
   与 §12.95 的判定链完全吻合；
3. **`dw` 到达 3**（而非此前的 5）——前端梯的形态变了；
4. **`FE` 仍是 5、`G1` 仍是 0、`1F4` 仍是 1**——**更上层的推进尚未发生**。

#### 这意味着什么

**`Add` 这条链路现在完全正常了**：

```
count > 0 -> jle 不跳 -> 过滤通过 -> 写 2 -> jne -> 返回
```

**`obj1` 进入"就绪"状态并保持。**

#### 但 `1F4` 仍是 1

`0xBAE30F cmp eax,2` 现在应当通过（状态确实是 2），
`0xBAE587` 应当执行——**但 `1F4` 仍是 1**。

**两种可能**：

1. `0xBAE587` 所在的整段（`0xBAE2DD`–`0xBAE587`）仍被更早的分支挡住
   （例如 `0xBAE2DD`/`0xBAE2EA`/`0xBAE2F7` 那三个字节标志中有一个为 0，走到
   `je 0xBAE7B4` 复位）；
2. `dw = 3` 说明前端已经切换到了另一个界面/状态，pump 走的是**另一条分支**，
   而 `0xBAE587` 属于 `dw=5` 那条路。

**第 2 条更值得注意**：`dw` 从 5 变成 3，说明流程**确实**变了——
只是变化的方向与预期不同。

#### 下一步：看界面

**截图**，确认 `dw=3` 时客户端显示什么。

- 若**已离开代号页**（进入大厅或选人页）→ 这是真正的进展，后续按新界面推进；
- 若**仍在代号页** → `dw=3` 只是另一个内部状态，需要继续解。

**同时**：`1F4` 仍是 1 说明 FE 梯的下一级还没触发，
需要看 `0xBAE2DD` 那三个字节标志的取值。

**截图是最快的信息来源。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.164"),
                         ("HANDOFF-CURRENT.md", "### 16.52")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.164", "### 16.52")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
