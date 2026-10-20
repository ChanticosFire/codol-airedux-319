"""Record round 80: 0xBBA5C3 tests status==1, so count>0 returns immediately after writing 2."""
from pathlib import Path

TEXT = """
### 12.95 ★★★ 修正：`0xBBA5C3` 是"状态是否为 1"的检查，`count>0` 写 2 后立即返回（2026-10-24 10:2x）

#### 真正的结构

从 `0xBBA573`（干净边界）解到 `0xBBA5F0`：

```asm
0xBBA573  mov byte ptr [ebp - 0x13c], 0
0xBBA57A  call 0xC42D60
0xBBA57F  add esp, 0xc
0xBBA582  push 0x64
0xBBA584  lea eax, [ebp - 0x13c]
0xBBA58B  lea ecx, [ebx + 0x8c]
0xBBA591  call 0xB75660
0xBBA59D  call 0xBA4B20
0xBBA5A2  add esp, 4
0xBBA5A5  lea ecx, [ebp - 0x1c4]
0xBBA5AB  mov byte ptr [ebp - 4], 2
0xBBA5AF  call 0xB76EE0
0xBBA5B4  lea ecx, [ebp - 0x24c]
0xBBA5BA  mov byte ptr [ebp - 4], 0
0xBBA5BE  call 0xB76EE0
0xBBA5C3  cmp dword ptr [ebx + 0x120], 1     ; ★ 检查状态是否仍为 1
0xBBA5CA  jne 0xBBA635                       ; ★ 不是 1 -> 直接返回
0xBBA5CC  lea ecx, [ebx + 0x118]
0xBBA5D2  call 0xB75E30
0xBBA5D7  fld dword ptr [ebx + 0x128]
0xBBA5DD  fcompp
0xBBA5E1  test ah, 5
0xBBA5E4  jp 0xBBA613
0xBBA5E6  mov eax, dword ptr [ebx + 0x130]   ; 索引
...
```

**关键修正**：`0xBBA5C3` 不是"`count<=0` 的跳过出口"，而是**写 2 之后的状态检查**。

#### 两条路径的真实走向

| 进入方式 | 到达 `0xBBA5C3` 时的状态 | 结果 |
|---|---|---|
| `count > 0`（`0xBBA448`→搬运→判定→`0xBBA569` 写 2） | **2** | `jne 0xBBA635` → **立即返回，索引不推进，2 保留** |
| `count <= 0`（`0xBBA442 jle 0xBBA5C3`） | **1** | 不跳 → 继续到 `0xBBA5CC` → **推进索引** → 容量检查 → 满则写 3 |

**所以 `count > 0` 是一条"写 2 然后立刻收手"的成功路径**——写完之后索引不再推进，
`Add` 的入口检查（`cmp [ebx+0x120],1` / `jne`）此后永远短路。

#### 于是全部机制说得通了

```
启动：Init 把状态置 1、索引清零（约 2.5 秒后会被填满）
  ↓
count <= 0 的每一帧：
  0xBBA5C3 检查 1 == 1 → 继续
  0xBBA5E6 读索引 → +1
  索引到 5 → 写 3                                  ← 2.5 秒后状态变 3
  ↓
此后 Add 入口 cmp [ebx+0x120],1 → 3 != 1 → jne 直接返回
  连"搬运/判定/写 2"都不再执行
```

**要在索引涨满前让 `count > 0`，才能抢到写 2 的机会。** 一旦错过这个窗口，
状态变 3，`Add` 就再也不会处理任何数据——这正是我们观测到的全部现象。

#### §12.86 / §12.91 的推断需要修正

之前认为"`count <= 0` 只推进索引、写 2 是兜底"，方向是反的：

- **写 2 才是真正的成功出口**；
- `count <= 0` 的那条只是"每帧空转时把索引 +1"，纯属副作用。

而第 52 轮实验二（把容量抬到 200）之所以能让状态长期停在 1，正是因为
索引涨得慢、`count<=0` 的副作用迟迟没有触发写 3。

#### 下一步：组合实验

第 52 轮已证明 `cap = 200` 能让状态长期保持 1。现在再加上"回一个应答让
`count > 0`"，就应当能在窗口内触发写 2：

```
实验：cap=200（运行期改 [obj1+0x124]）
    + LOBBY_UDP_REPLY=1e8300（限次或不限）
    → 期望：状态变成 2，随后 Add 永久短路，1F4 有机会变 2
```

若成立，就说明**唯一缺的是"在索引涨满前收到一条数据"**；那么真实修复方向是
**让服务端在启动后立刻（2.5 秒内）回第一个包**，而不是靠改容量。

这是目前最有把握的一步。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.95"),
                         ("HANDOFF-CURRENT.md", "### 15.83")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.95", "### 15.83")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
