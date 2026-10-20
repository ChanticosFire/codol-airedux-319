"""Record round 60: the count<=0 branch is the one that writes +0x130."""
from pathlib import Path

TEXT = """
### 12.74 ★★★ 修正：`0xBBA5C3` 分支正是**写 `+0x130`** 的那段（2026-10-23 22:4x）

#### 先排除观测错误

重做第 52 轮实验二（`cap=200`、`idx=0`、`status=1`），这次同时记录
`lobby` 与 `obj1` 指针：

```
setup: lobby=0x37C97040  obj1=0x37D60008
after: status=1  cap=200  idx=0

t= 5s  lobby=0x37C97040  obj1=0x37D60008  status=1  cap=200  idx=10   1F4=1
t=10s  …                                                                 idx=20
t=20s  …                                                                 idx=40
t=40s  …                                                                 idx=80
t=60s  …                                                                 idx=119
```

**`lobby` 与 `obj1` 指针全程未变，索引以约 2 条/秒稳定增长。**
所以 §12.73 记录的矛盾**不是观测错误，是真实的**。

#### 真正的原因：我把指令顺序读反了

§12.65 扫描到的 `+0x130` 三个写入点是：

| 地址 | 形式 | 写入值 |
|---|---|---|
| `0xBB76BB` | `89 83 30 01 00 00` | `eax`（构造时 0） |
| `0xBBA3A6` | `C7 83 30 01 00 00 00…` | 0（初始化） |
| `0xBBA5F6` | `89 93 30 01 00 00` | `edx` |

前两轮我把 `0xBBA5F6` 判定为"位于 `0xBBA5C3` 之后、因此不可达"。**这是错的**。
按地址顺序重新对齐：

```asm
0xBBA5C3  …                       ; count <= 0 的跳转目标在这
0xBBA5EC  movzx ecx, byte [ebx + 0x124]     ; 容量
0xBBA5F3  lea edx, [eax + 1]
0xBBA5F6  mov dword ptr [ebx + 0x130], edx  ; ★ 写索引
0xBBA5FC  cmp eax, ecx
0xBBA5FE  jae 0xBBA613
0xBBA613  movzx eax, byte [ebx + 0x124]
0xBBA61A  cmp dword ptr [ebx + 0x130], eax
0xBBA620  jb 0xBBA635                       ; 未满 -> 正常返回
0xBBA62B  mov dword ptr [ebx + 0x120], 3    ; 满 -> 写 3
```

`0xBBA5C3` 到 `0xBBA5F6` 之间没有跳转，所以 **`count <= 0` 的分支会直接流到
`0xBBA5F6`，把 `+0x130` 写成 `eax + 1`。**

**这就是索引增长的来源。** 之前三轮之所以没看到，是因为我把"跳过追加"想成了
"跳过整段"，实际上它只跳过了 `0xBBA4A1`–`0xBBA55C`（搬运与判定），
而**索引推进和容量检查都在跳转目标之后**。

#### 完整路径首次真正闭合

```
Add(this, src, count)
  ├─ status != 1 ────────────────► 0xBBA635 直接返回
  ├─ count <= 0 ─────────────────► 0xBBA5C3 ─┐
  └─ count > 0 → 搬运/判定 ──────► 0xBBA55E ─┤
                                              ▼
                                     0xBBA5EC  读容量
                                     0xBBA5F6  [this+0x130] = eax + 1   ← 索引 +1
                                     0xBBA5FC  cmp eax, 容量
                                     0xBBA61A  idx >= 容量 ?
                                        否 → 0xBBA635 返回（状态不变）
                                        是 → 0xBBA62B 写 3
```

**所以每帧被调用一次，索引就 +1，与 count 无关。**

观测到约 2 条/秒而不是 51 条/秒，说明 `Add` 实际被调用的频率约 2 次/秒
（`0xBAE276` 每帧执行，但 `0xBAE246` 的 `[lobby+0x1F8]` 判空可能常为真、
或 pump 的调用频率低于 FE 循环）。这一点与"pump 51 次/秒"并列，说明 pump
内部对 `Add` 的调用有条件，值得单独计数。

#### 这解释了最初的状态

- 原始容量 5：索引从 0 起，约 2 条/秒，**2.5 秒后 `idx >= 5`**，写 3，之后
  `status != 1` 使 `Add` 永久短路；
- 把容量改到 200：索引继续涨到 200（约 100 秒），然后写 3；
- 把 `status` 改回 1：`Add` 恢复执行，索引继续推进，容量未满时状态保持 1，
  满了再写 3。

**每一次实验都在同一套逻辑下自洽。**

#### 下一步

索引推进与 count 无关、与 status 只在入口相关，那么 `status` 变成 1 的时机
就成了唯一的变量。而 `status = 1` 只由 `0xBBA3D2` 写（在 `0xBBA370` 里，
即 `Init`）。

**所以真正要问的是：`Init` 是否应当在每批服务器数据到来时被重新调用一次，
从而把 `status` 复位为 1、索引复位为 0？**

从 `0xBBA370` 的实现看，它做的正是"复位"：复制 136 字节、索引清零、容量重设、
`status` 由 `0xBBA3D2` 写 1。而它的两个调用者 `0xBADD0A` / `0xBAE6A8` 都在
pump 内——若它们只在启动时命中一次，索引就会单调增长到容量为止。

下轮：给 `0xBBA370` 的**两个调用点**分别装计数器，确认它们在稳态下是否还会被触发。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.74"),
                         ("HANDOFF-CURRENT.md", "### 15.62")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.74", "### 15.62")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
