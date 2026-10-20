"""Record round 87: a 40-second window still leaves the status at 1, contradicting the slot theory."""
from pathlib import Path

TEXT = """
### 12.102 窗口撑到 40 秒仍无效；`[ebp+0x94]` 并非 `[ebp-0x548]`（2026-10-24 14:2x）

#### 先说一个决定性的时间数据

新增 `tools/probe_timing.py`，从 `lobby_udp.jsonl` 里 `endpoint_up` 与第一个
`udp_in` 的 UTC 时间算出延迟：

```
runs/20261024-edx      first probe arrived +24.0 s after endpoint_up   (12 probes over 2.0 s)
runs/20261024-noecho   first probe arrived +23.0 s                     (12 probes over 3.0 s)
runs/20261024-reply1   first probe arrived +23.0 s                     (10 probes over 2.0 s)
```

**客户端在服务端起来后约 23–24 秒才发第一个探测包，而状态窗口只有约 2.5 秒。**

这一条本身就解释了为什么此前所有"改应答内容/频率"的尝试全部无效——**数据到的时候
状态早已锁死**。这是一个此前缺失的关键事实。

#### 于是做了"撑窗口"实验

用原样 echo（`LOBBY_UDP_ECHO=1`），在 `dw=5` 之后把容量抬到 200、索引清零、状态置 1，
然后观察 40 秒——覆盖了客户端发探测包的时刻：

```
t=5s    status=1 idx=11 stat=23
t=10s   status=1 idx=21 stat=33
t=20s   status=1 idx=41 stat=53
t=25s   status=1 idx=52 stat=64      ← 探测包已到达
t=40s   status=1 idx=83 stat=95
```

**窗口足够宽（索引远未到 200）、探测包也确实到达了（stat 从 23 涨到 95），
但状态始终是 1。**

#### 这与 §12.86 的观测直接冲突

§12.86 在 `0xBB171F`（`mov [edi],edx`）采到 `edx = 0x0100007F`（`127.0.0.1`）。
若 `[ebp+0x94]`（`Add` 的 count）真的就是 `[ebp-0x548]`（`mov [edi],edx` 的目标），
那么 count 应为 `16777343`，`jle` 不成立，应当写 2、状态变 2。

**实测没有。所以 §12.98/§12.99 的推断（参数块错位使 `[ebp+0x94]` 落在
`[ebp-0x548]` 上）是错的。**

#### 重新核对：`[ebp+0x94]` 究竟在哪

关键在 `0xB753C0` 的调用约定：

```asm
0xBAE256  sub esp, 0x88        ; 136 字节结构
0xBAE26A  push edx             ; 0xB753C0 的源指针
0xBAE26B  call 0xB753C0
0xBAE276  call 0xBBA3F0        ; Add
```

- 若 `0xB753C0` 是 **cdecl**（调用方弹参数），`esp` 在返回后仍指向 `edx` 副本，
  则 `[ebp+8]` = `edx` 副本、`[ebp+0x94]` = 结构之后 = `[ebp-0x548]`；
- 若 `0xB753C0` 是 **stdcall**（被调方弹参数），`esp` 已回升，
  则 `[ebp+8]` = 结构起点、`[ebp+0x94]` = 结构 `+0x8C`——**已越过 136 字节
  （0x88）的边界**，读到栈上别的数据。

**实测 `[ebp+0x94] = 0xFFFFFFFE`（-2）而 `[ebp-0x548] = 127.0.0.1`，
两者不同，说明实际是 stdcall 那种情形，`[ebp+0x94]` 指向结构之后 4 字节，
而那块内存恰好是 -2。**

**结论：`Add` 的 count 来自一块与业务数据无关的栈内存。** 这既解释了为什么
"怎么调都没反应"，也说明此前把 `[ebp-0x94]` 当作"容器 +0x84"的理解从头就是错的。

#### 下一步

1. **确认 `0xB753C0` 的调用约定**：读它的结尾指令——若是 `ret 4` 则为 stdcall，
   若是 `ret` 则为 cdecl。这能一举确定 `Add` 的参数基准；
2. 若确认是 stdcall，则 `Add` 的源数组与 count 分别是 `[ebp+8]` 与 `[ebp+0x94]`，
   而结构体在 `[ebp+0xC]`——**参数语义需要整体重写**；
3. 这也意味着 `0xBAE24E` 那串 push 里可能**少了一个** load 好的参数，
   值得再逐条核对 `0xBAE24E`–`0xBAE276` 的完整指令序列。

**第 1 条成本极低且能定论，下轮先做。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.102"),
                         ("HANDOFF-CURRENT.md", "### 15.90")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.102", "### 15.90")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
