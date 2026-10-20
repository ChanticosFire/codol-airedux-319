"""Record round 76: the reply only postpones the lock-up, and reveals a counter threshold."""
from pathlib import Path

TEXT = """
### 12.91 `1e 83 00` 只是推迟自锁；但暴露了一个计数器阈值（2026-10-24 08:2x）

#### 长时间观察结果

```
t=10s   G1=0 gate=0 FE=5 1F4=1 o1[120]=3 idx=5 cap=05 o2[1A0]=5 stat=13
t=20s   …完全相同…
t=120s  …完全相同…
```

**第 10 秒时状态已经是 3、索引已是 5。** 上一轮看到的 `1/4` 是**瞬态**：
`count > 0` 之后索引从 0 开始涨，约 2.5 秒涨到 5（容量），随即写 3。
整段过程发生在采样间隔之内，所以只看到了中间的 `1/4` 一次快照。

`[0xE85CB0] = 13` 说明成功路径这次只走了 13 次（上一轮是 11 次），两次运行一致。

#### 所以 `1e 83 00` 的效果是

**让 `count > 0`，仅此而已。** 追加仍会一路填满容量，然后写 3。

#### 但本轮暴露了一个之前没注意的判定

回看 §12.70 的代码：

```asm
0xBBA4A9  call 0xBC1980              ; 返回 [容器 + 2]
0xBBA4AE  cmp ax, 3
0xBBA4B2  jb 0xBBA55E                ; < 3 -> 跳到写 2 的路径
0xBBA4B8  lea ecx, [ebp - 0x250]
0xBBA4BE  call 0xBC1970
0xBBA4CC  call 0xB75470              ; 再检查
0xBBA4D3  je 0xBBA55E                ; 失败 -> 也写 2
```

而 `0xBC1980` 只是 `mov ax, word ptr [ecx + 2]`，`0xBC1CC0` 构造时把 `+2` 置 0。

**`0xBC1A50`（名为 "add" 的追加函数）会把它累加。** 我们每 10 秒给客户端回
**6 次**应答，于是这个计数器很快超过 3，`jb` 不再成立，写 2 的分支被跳过，
流程落到容量检查 → 满 → 写 3。

**即：追加次数太多，把"成功"判定挤掉了。**

#### 这给出一个明确、可试的调整

**减少应答次数**。若只在最初回 1–2 次，让 `[容器+2]` 保持在 3 以下，
`0xBBA4B2 jb` 就会成立，流程应当走到 `0xBBA55E` → `0xBBA569` 写 2，
`obj1[0x120]` 就会变成 2 —— 那正是 `Add` 入口要求的"就绪"状态。

实现上只需给 `lobby_udp` 加一个上限：

```
LOBBY_UDP_REPLY_MAX=N     只回应前 N 个数据报，之后静默
```

#### 需要注意的风险

- 每帧 `Add` 都会被调用（约 21 次/秒）；如果回复 1 次，`count > 0` 也只持续
  一帧，之后立刻回到 `count = 0`（无数据），索引仍会继续 +1。所以"回 1 次"
  可能只是让状态短暂变成 1，然后又回到 0 → 索引继续涨。
- 更稳的做法可能是**持续低频回应**（例如每 2 秒 1 次），让 `+2` 计数器
  始终低于 3，同时保持 `count > 0`。

下轮先试 `LOBBY_UDP_REPLY_MAX=1` 与 `MAX=2`，各跑一次，看 `1F4` 是否变化。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.91"),
                         ("HANDOFF-CURRENT.md", "### 15.79")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.91", "### 15.79")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
