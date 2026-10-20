"""Record round 63: the handle is valid, so the early-return hypothesis is dead."""
from pathlib import Path

TEXT = """
### 12.77 句柄是 11628（有效），`0xBB15E0` 的早退假设被排除（2026-10-24 00:3x）

#### 实测对象字段

```
[lobby+0xC] = 0x37DAECD0

  +0x00 = 0x00D95558   ← vtable
  +0x04 = 0x00002D6C   ← 句柄 = 11628
  +0x08 = 0x00000000
  +0x0C = 0x00000000
  +0x10 = 0x00000000
  +0x14 = 0x00000000
  +0x18 = 0x00000000
  +0x1C = 0x00000000
  +0x20 = 0x0B2FBF93
```

`[obj+4] = 11628`，**不是 `-1`**。所以 `0xBB15E0` 里：

```asm
0xBB15FE  cmp edx, -1
0xBB1601  jne 0xBB1616       ; 11628 != -1 -> 跳过早退
0xBB1604  lea eax, [edx - 9] ; 只有 edx == -1 才走这里
```

**早退分支不会命中。** §12.76 提出的"句柄为 -1 导致 count 恒为 0"假设就此排除。

#### 剩下的可能

`0xBB15E0` 会正常往下执行，返回值经：

```asm
0xC74018  test ebx, ebx
0xC7401A  jns 0xC74021        ; >= 0 -> 继续
0xC7401C  cmp ebx, -5
0xC7401F  jne 0xC7406E        ; 其它负值 -> 失败路径
```

所以只剩三种情况：

1. `0xBB15E0` 返回了 `>= 0` 或 `-5`，成功路径执行，但 `0xB75420` 写出的数据里
   `+0x84` 就是 0（即**服务端数据本身没有条目**）；
2. `0xBB15E0` 返回了其它负值，直接走 `0xC7406E` 失败路径，什么都没写；
3. `0xBB15E0` 内部在别处（例如它自己的循环）提前返回，未填 `+0x84`。

三种都可以用**一个探针**区分：在失败跳转目标 `0xC7406E` 上装计数器。

- 若命中 → 情况 2 或 3（失败）
- 若 0 次 → 情况 1（成功但数据为空）

#### 附带观察

`[obj+0x20] = 0x0B2FBF93` 是一个 32 位值，量级像时间戳（约 1.87 亿），
可能是"最后一次同步时间"之类。若它随运行时间变化，就说明这个对象在活动；
若恒定，说明它从未被更新——那也能佐证"数据链路没有真正跑起来"。
值得在下一轮顺便记录两次读数比较。

#### 下一步

1. 在 `0xC7406E` 装计数器，判定"成功但数据为空"还是"失败"；
2. 同时记录两次 `[obj+0x20]` 的值，看是否变化。

这两项都只需一轮。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.77"),
                         ("HANDOFF-CURRENT.md", "### 15.65")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.77", "### 15.65")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
