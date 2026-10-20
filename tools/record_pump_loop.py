"""Record round 15: pump runs but fails every cycle."""
from pathlib import Path

TEXT = """
### 12.31 采样证明 pump 每轮都在跑、每轮都失败（2026-10-23 02:1x）

#### 高频采样结果

`tools/sample_1f4.py` 以 200 Hz 采样 5 秒：

```
lobby = 0x361a7c60
--- 921 samples over 5.00s ---
  distribution of [lobby+0x1F4]: 1:921
  transitions observed: 0
  final 1FC=0x381b0180  FE_state=5
```

**921 次采样值恒为 1，零次跳变，容器指针也不变。**

一度据此推断「pump 只跑了一次」，但这是错的——见下面的前置条件验证。

#### pump 的两个入口条件都满足

```asm
0xBAD83D  cmp byte ptr [edi], 0     ; edi = ebx+8
0xBAD840  je 0xBAE7C6               ; 为 0 -> 直接返回
0xBAD846  cmp dword [ebx+0x1F4], 1
0xBAD84D  jne 0xBAE7C6              ; 不等于 1 -> 直接返回
```

实测：

```
lobby      = 0x3793efe0
byte[+0x08] = 1        <- 非零，不提前返回
[+0x1F4]    = 1        <- 等于 1，继续
[+0x1FC]    = 0x37d92820
[+0x1F0]    = 0x3617ec60
```

**两个条件都满足，所以 pump 确实在执行。**

容器指针恒定并不表示没重建——`0xBAE6C2` 起的流程是先销毁旧容器、释放，再分配新的，
分配器极可能返回同一地址。因此 **pump 是每轮重建容器、每轮登记失败、每轮写 1**。

#### 完整死锁结构

```
每帧:
  FE 主循环 0x621750
    -> 读 [lobby+0x1F4] == 1
    -> call 0xBAD800 (pump)
         -> 重建 440 字节容器 -> lobby+0x1FC
         -> 0xBBAD40 登记数据 -> 0xBBA8A0 -> 0xBBA760(key=0, 1288 字节)
         -> 查不到 -> 0
         -> 写 [lobby+0x1F4] = 1
    -> 再读 [lobby+0x1F4]，仍为 1，不等于 2
    -> FE_state 不推进，停在 5
```

同时 `0x7F58A0`（一个「等 `[lobby+0x1F4]` 变成非 1」的阻塞重试循环，内部 sleep 10ms
后重调 pump）有 **7 个调用者**（`0x629319`、`0x62AA88`、`0x62F88F`、`0x634A98`、
`0x67578D`、`0x759A7E`、`0x7CA24D`），全在游戏逻辑层——这些地方**都没被执行到**，
因为客户端还没有进入游戏逻辑。

#### 因果关系的最终形态

这不是「FE 等 state」或「state 等 FE」的单向依赖，而是一个**闭环**：

- pump 需要容器里有 key=0 的 1288 字节数据才能成功；
- 容器每轮新建、每轮为空；
- 而填入这份数据的路径在游戏逻辑层（`0x7F58A0` 的 7 个调用点所在的那一层）；
- 游戏逻辑层又等待 FE 完成（`FE_state` 到 6、`onboarded` 置位）。

**闭环的断点在「取代号」提交**：只有玩家完成建档，FE 才会放行到游戏逻辑层，
游戏逻辑层才会去驱动 `0x7F58A0` 这条等待链，pump 才可能成功。

这也解释了为什么之前所有「绕过去」的尝试都会崩溃——闭环里任何一环被强行
置位，其它环仍然停在原处，状态不一致就崩。

#### 下一步

1. 反汇编 `0xBBA810`（容器构造），确认它是否预填内容；若预填，则 `0xBC1C20`
   查找失败说明预填的 key 不是 0，需要找出正确的 key；
2. 反汇编 `0x7F58A0` 的一个调用点（如 `0x67578D`），看它属于哪个功能，从而
   判断「游戏逻辑层」具体在等什么；
3. 确认「取代号」提交的落点：既然它不是网络请求，最可能是写 `config_mp.cfg`
   或某个全局，可从 `0x83xxxx` 区的写入点反查。

第 1 条最直接，优先。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.31"),
                         ("HANDOFF-CURRENT.md", "### 15.19")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.31", "### 15.19")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
