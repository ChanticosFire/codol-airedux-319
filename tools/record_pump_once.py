"""Record round 45: obj1 is a size-5 list, and the pump stops being called after startup."""
from pathlib import Path

TEXT = """
### 12.61 ★★★ `obj1` 是容量 5 的列表；pump 启动后不再被调用（2026-10-23 15:0x）

#### 写 3 与写 2 的分歧点已定位

```asm
0xBBA5EC  movzx ecx, byte ptr [ebx + 0x124]   ; 容量（字节）
0xBBA5F3  lea edx, [eax + 1]
0xBBA5F6  mov dword ptr [ebx + 0x130], edx     ; 索引 = eax+1
0xBBA5FC  cmp eax, ecx
0xBBA5FE  jae 0xBBA613
...
0xBBA613  movzx eax, byte ptr [ebx + 0x124]
0xBBA61A  cmp dword ptr [ebx + 0x130], eax
0xBBA620  jb 0xBBA635                          ; 索引 < 容量 -> 跳过写 3
0xBBA622  push eax
0xBBA623  call 0xBA4B20
0xBBA62B  mov dword ptr [ebx + 0x120], 3       ; ★ 索引 >= 容量 -> 写 3
```

**`[obj1+0x120] = 3` 的含义是"这个列表已满"**，容量在 `+0x124`（一字节），
当前索引在 `+0x130`。

#### 实测：列表确实是满的

```
[obj1+0x120] (status)   = 3
[obj1+0x124] (capacity) = 5
[obj1+0x130] (index)    = 5
=> index >= capacity    = True
```

原始转储（`0x37E8D078` 起）也印证：

```
0x37E8D088  03 00 00 00 05 d0 1a 00 00 00 00 3f 03 00 00 00
            ^^^^^^^^^^^ status=3   ^^ cap=5
0x37E8D098  05 00 00 00 ...                                  index=5
```

#### 实验：把索引清零

写入 `[obj1+0x130] = 0` 并保持 120 秒：

```
t=10s   dw=5 ui=9 G1=0 gate=0 FE=5 1F4=1 o1[120]=3 o1[130]=0
t=20s   dw=5 ui=9 G1=1 gate=0 FE=5 1F4=1 o1[120]=3 o1[130]=0
t=120s  同上
```

三点结论：

1. **索引清零成功且稳定**（120 秒未变），说明没有代码把它写回去；
2. **`G1` 前进到 1**——`[D+0xC]=1` 依然有效，FER 梯第一级照常；
3. **`[obj1+0x120]` 仍是 3，`[lobby+0x1F4]` 仍是 1**——**pump 没有重新执行那段判定**。

#### 由此确认：pump 在启动后不再被调用

结合第 44 轮的 816 万次采样（`1F4` 恒为 1、零跳变），以及本轮"改了索引却
毫无变化"，可以确定：

**`0xBAD800`（pump）只在登录早期被调用过有限次数，之后不再执行。**

`0x6216BF` 是 pump 的调用点之一，它在 `0x6216B9` 把 `FE_state` 写成 3 或 5 之后
立刻调用一次。此后是否有循环驱动没有证据——之前关于"pump 每帧执行"的说法
（§12.31）**应予撤回**，那是从"`1F4` 恒为 1"和"`0xBAE7AA` 写 1"反推的，
从未观测到 pump 运行。

#### 这改变了对 `1F4` 的解释

| 旧解释 | 新解释 |
|---|---|
| pump 每帧跑、每帧失败、每帧写 1 | pump 只在登录早期跑过，`1F4` 停留在它最后一次写入的值 |
| 需要让 pump "这一轮"成功 | 需要在 **pump 还被调用的那个时间窗口内**让它成功 |
| 改状态字段应当让下一帧生效 | 改状态字段没有任何效果，因为之后没有下一帧 |

**即：这是一个时机问题，不是条件问题。** 第 44 轮把三个标志算出来全部满足，
现在知道即使条件满足也不会重试——因为根本不会再调用。

#### 下一步（方向明确）

需要在 **`FE_state` 被写成 3/5 之前或同时** 让两个状态字段达到目标值，这样
`0x6216BF` 那一次 pump 调用就能走成功分支。

具体做法：`auto_lobby.py` 目前是等 `dw=5` 之后才写状态位，**太晚了**。
应改为在 `dw` 到达 2（`0x6216B9` 执行前）就预先设好：

- `[D+0xC] = 1`
- `[obj1+0x120] = 2`
- `[obj2+0x1A0] = 4`

但 `obj1`/`obj2` 的指针在 `dw=2` 时可能还不存在。所以更稳的做法是**先跑一次
让对象建立，记下地址，然后重启客户端并在早期写入**——但对象地址每次运行都变，
这条路走不通。

**更现实的方向**：接受 pump 只跑一次，去查它**为什么只跑一次**——
`0x621750`（FE 主循环）是否被周期调用？若被调用，`0x62178F cmp eax,1` 之后
的 `0x621796 call 0xBAD800` 为什么没触发？这是下一轮的问题。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.61"),
                         ("HANDOFF-CURRENT.md", "### 15.49")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.61", "### 15.49")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
