"""Record round 30: forcing [lobby+0x1F4]=2 is confirmed as the crash source."""
from pathlib import Path

TEXT = """
### 12.48 ★★★ 确认：强写 `[lobby+0x1F4]=2` 是崩溃源（2026-10-23 08:2x）

#### 对照实验 I（不写 1F4）

配置：15 补丁 + 只写 `[D+0xC]=1` 与 `FE_state=3`（**不写** `[lobby+0x1F4]`）。

```
写入后：G1=0  FE=3
t=10s   dw=5 ui=9 G1=0 gate=0 FE=3 1F4=1
t=20s   dw=5 ui=9 G1=1 gate=0 FE=3 1F4=1     <- FE 梯自发前进
t=30s…150s  同 t=20s，全程存活
```

**客户端稳定存活 150 秒，无崩溃、无 `ClientOffline` 上报。**
LSG 会话只有 `task4` 一次请求与 4 次保活，`raw_session_end` 是服务端主动关闭。

#### 与写 1F4 的对照

| 配置 | 存活 | G1 | gate | FE | 请求数 |
|---|---|---|---|---|---|
| `[D+0xC]=1` + `FE_state=3`（不写 1F4） | **150 s+** | 1 | 0 | 3 | 1（仅 task4） |
| 再加 `[lobby+0x1F4]=2` | **约 10 s 后崩** | 1 | 0 | 3 | 5（含日志上报） |

**结论：`[lobby+0x1F4]=2` 是崩溃的直接原因。**
第 26 轮把"5 个 client_frame 出现"当作进展是误判——那 5 个里有 3 个是崩溃日志。

#### 为什么写 2 会崩

按 §12.38/§12.47 的推断：`0x6217D0`（`FE_state: 3 → 4`）与
`0xBAE1AC`（pump 写 2）都在"整条链已完成"的分支上。我们只把最后一个字节
置成 2，前面该有的数据（容器内容、pump 的内部标记）全都没有，于是客户端在
`task9` 之后校验失败、判定离线、上报 `ClientOffline`/`ClientException` 并退出。

#### 当前可稳定复现的状态

```
dw = 5      （登录完成）
ui_state = 9（训练官/取代号页面）
G1 = 1      （FE 梯第一级，自发达到）
gate = 0
FE_state = 3（我们置的，稳定不回滚）
[lobby+0x1F4] = 1（pump 每帧写回，未强改）
```

**客户端可以永远停在这里，不会崩。** 这是一个干净的、可反复使用的基线。

#### 这意味着什么

要进大厅必须让 `FE_state` 到 4 或 6，而那需要 `[lobby+0x1F4]=2`，而强写 2 必崩。
所以**只能让 pump 自己把 1F4 写成 2**。

pump 里写 2 的两处（`0xBAE1AC`、`0xBAE587`）都是**无条件**的——只要执行流到达
就写。挡住执行流的是 `0xBAF040`（它要 `0xBBA760(key=0, 1288B)` 在容器里查到内容，
而容器每帧新建且为空）。

因此下一步的唯一正确方向是：**找出容器里那份 1288 字节数据应该由什么填充**。
它是 pump 自己新建的容器，填充者只能是 pump 内更早的代码——也就是说
`0xBBAD40` 之前还有一步我们没跟到。

#### 下一步

1. 反汇编 `0xBAE6C0` 之前（即 `0xBAE5A0`…`0xBAE6C0` 这段），看容器新建之前
   是否本该从别处拷入数据；
2. 特别关注 `[lobby+0x1FC]` 的**旧**容器（`0xBAE6C2` 先取它、销毁它）——
   如果它本来有内容，说明上一轮的填充成功了，问题在"为什么这一轮重建后丢了"。
3. 若确认容器的数据来自网络应答，则要改 `svc71/task4` 的应答形状：
   现在回的是 4 字节 `u32 0`，也许应当回一个带服务器条目的列表。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.48"),
                         ("HANDOFF-CURRENT.md", "### 15.36")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.48", "### 15.36")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
