"""Record round 54: the append source is the lobby server array entry, re-appended every frame."""
from pathlib import Path

TEXT = """
### 12.68 ★★★ 追加源就是 `[lobby+0x4D60]` 的那一条记录，每帧被重复追加（2026-10-23 19:2x）

#### `0xBBA370` 是初始化，不是追加

```asm
0xBBA376  cmp dword ptr [ebx + 0x120], 0
0xBBA37D  je 0xBBA38B                  ; 只有状态 0 才继续
0xBBA37F  call 0xBA4B20                ; 否则报错
0xBBA384  xor al, al / ret 0x14        ; 返回 false

0xBBA397  mov dword ptr [ebx], eax     ; 存参数 1
0xBBA39C  mov ecx, 0x22
0xBBA3A1  rep movsd                    ; 复制 136 字节到 [ebx+4]
0xBBA3A6  mov dword ptr [ebx + 0x130], 0     ; 索引清零
0xBBA3B0  call 0xBBAAE90
0xBBA3BE  mov dword ptr [ebx + 0x124], eax   ; ★ 容量 = [ebp+0x10]
0xBBA3C4  mov dword ptr [ebx + 0x128], ecx
```

这是 **`Init(this, arg1, srcArray, capacity, ...)`**：
它复制 136 字节、把索引清 0、**并把调用方传入的 `[ebp+0x10]` 写成容量 `+0x124`**。

所以**容量 5 是初始化参数决定的**，不是硬编码。而 `Init` 只在启动期跑，
这就是它在观测窗口内计数为 0 的原因（与 §12.65 的时序结论一致）。

#### 追加的参数来自一个 136 字节结构

`0xBAE276`（`call 0xBBA3F0` 的上一句是 `mov ecx,[ebx+0x1F8]`）之前的准备：

```asm
0xBAE24E  push esi
0xBAE24F  lea ecx, [ebp - 0x548]
0xBAE255  push ecx
0xBAE256  sub esp, 0x88                ; 136 字节
0xBAE25C  lea edx, [ebp - 0x768]
0xBAE262  mov ecx, esp
0xBAE26A  push edx
0xBAE26B  call 0xB753C0                ; 把 [ebp-0x768] 的 136 字节复制到栈顶
0xBAE270  mov ecx, [ebx + 0x1F8]       ; this = obj1
0xBAE276  call 0xBBA3F0                ; Add(this)
```

栈布局（自 `[ebp+8]` 起）：`esi`、`[ebp-0x548]`、然后 **136 字节结构**。
`Add` 里用的 `[ebp+0x90]` 与 `[ebp+0x94]` 落在该结构内部（`0x90-0x10 = 0x80`，
`0x94-0x10 = 0x84`），即：

- **`[结构+0x80]` = 源数据指针**
- **`[结构+0x84]` = 条目数（count）**

#### 这 136 字节就是 `[lobby+0x4D60]` 的数组条目

§12.49 已经查明 `0xBAE5DB` 那段：

```asm
0xBAE5FF  imul eax, eax, 0x88          ; 136 字节一条
0xBAE605  add eax, [ebx + 0x4D60]      ; 数组基址
0xBAE612  call 0xB753C0                ; 复制该条目
```

**同一个 `0xB753C0`、同样 136 字节的路由。** 所以 pump 每帧做的是：

```
取 [lobby+0x4D60] 数组里的下一条记录（136 字节）
  → 复制到 [ebp-0x768]
  → 作为参数传给 Add(obj1)
  → Add 往 obj1 的列表里追加一条
```

#### 于是重复追加的根源清楚了

实测 `[lobby+0x4D68]`（数组容量）= **1**，只有一个条目（127.0.0.1 那条）。

而 pump 每帧（约 51 次/秒）走一次上述流程，其中约有 20 次成功进入 `Add`。
**同一个条目被反复追加**，obj1 的索引以约 2 条/秒增长，容量 5 在 2.5 秒内填满，
然后 `0xBBA62B` 写 3，永久自锁。

#### 这把"缺什么"彻底说清了

不是缺应答、不是缺状态位，而是：

> **`[lobby+0x4D60]` 数组只有 1 条记录，而 pump 把它当成"每帧都该追加一次"的流。**
> 正常运行时这个数组应当只在**收到新一批服务器列表**时才被填充一次，
> 并且追加完就该把游标推到末尾，而不是每帧重放同一条。

#### 下一步（两个候选方向）

1. **查数组游标**：`[lobby+0x4D6C]`（索引）在 §12.49 实测为 0。若 pump 在
   "取条目"时不检查游标是否已到末尾，就会出现本轮的重复追加。
   反汇编 `0xBAE5A0`–`0xBAE5F0` 的游标推进逻辑即可确认；
2. **查 `Add` 的去重**：`0xBC1A50` 可能是"查找是否已存在"，若它本应返回假
   （已存在）从而跳过追加，那么它现在返回真就说明去重失效——同样会指向
   数组内容或比较字段不匹配的问题。

第 1 条更贴近根因，且只需看十几条指令。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.68"),
                         ("HANDOFF-CURRENT.md", "### 15.56")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.68", "### 15.56")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
