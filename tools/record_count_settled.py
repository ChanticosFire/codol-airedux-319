"""Record round 90: esi equals [ebp+0x94], confirming the count is the virtual function's return."""
from pathlib import Path

TEXT = """
### 12.105 ★★★ 多槽位采样定论：`[ebp+0x94]` 就是 `esi`（虚函数返回值）（2026-10-24 15:5x）

#### 工具升级

`tools/probe_reg.py` 的 `--mem-ebp` 改为可重复：

```
--mem-ebp 0x88 --mem-ebp 0x8C --mem-ebp 0x90 --mem-ebp 0x94
```

cave 里对每个偏移各做一次 `mov eax,[ebp+off]` 并存入独立槽位，一次挂载采到
四个值 + 一个寄存器，**同一帧**。

#### 在 `0xBBA418`（`esi` 被改写前）采样

重放 12 字节 `64 A3 00 00 00 00 | 8B B5 90 00 00 00`（`mov fs:[0],eax` +
`mov esi,[ebp+0x90]`），逐条数清：

```
[slots] n=0   esi=0x00000000  [0x88]=0x00000000  [0x8c]=0x00000000  [0x90]=0x00000000  [0x94]=0x00000000
[slots] n=30  esi=0xfffffffe  [0x88]=0x00000002  [0x8c]=0x001a0000  [0x90]=0x001acfd0  [0x94]=0xfffffffe
[slots] n=60  … 完全相同 …
[slots] n=239 … 完全相同 …
```

**关键：`esi` 与 `[ebp+0x94]` 逐次完全相等。**

#### 这条结论一锤定音

```
Add 的 count = [ebp+0x94] = esi = 虚函数 0xBB15E0 的返回值
```

- 第 88 轮"count = 虚函数返回值"**成立**；
- 第 89 轮的"不相等"是**实验设计错误**（`esi` 已被 `0xBBA41E` 改写），
  该轮结论应作废；
- 第 84 轮采到 `[ebp+0x94] = -2` 也吻合——`esi` 就是 -2。

#### 完整因果链（最终、经实测确认）

```
pump 每帧:
  ① 虚函数 0xC73FB0 -> 0xBB15E0 收包
       有数据       -> 返回 esi >= 0
       无数据       -> 返回 esi = -2  (WSAEWOULDBLOCK, 0xBB166F)
  ② esi 作为 Add 的 count（经 [ebp+0x94]）
  ③ Add:
       入口 cmp [obj1+0x120], 1 / jne -> 返回
       count > 0 -> 写 2 并立即返回      ← 成功
       count <= 0 -> 跳过写 2, 推进索引
                    索引满 -> 写 3        ← 失败
```

#### 一个仍然开放的细节（但不影响主结论）

四个槽位的实测值：

```
[0x88] = 0x00000002
[0x8C] = 0x001A0000
[0x90] = 0x001ACFD0
[0x94] = 0xFFFFFFFE  ( = esi )
```

按"结构 136 字节 + `push ecx` + `push esi`"的推演，`esi` 应在 `[ebp+0x8C]`
而不是 `[ebp+0x94]`，中间差了 8 字节。可能的原因：

- `0xB753C0` 内部有未被计入的栈调整；
- 或者 `[ebp+8]` 与前一次推演相差两个槽位。

**但这已不影响结论**：`esi` 落在 `[ebp+0x94]`、而 `Add` 正是读 `[ebp+0x94]`，
两者吻合，count 的来源已确定。

#### 于是修复方向彻底明确

**让 `esi` 为正、且此时 `obj1[0x120]` 仍是 1。**

`esi` 来自 `0xBB1642 mov esi, eax`，`eax` 是 `call [0xCA84D4]` 的返回。
§12.82 曾采到该返回为 `0x11050C02`（正数），说明**正返回值确实会出现**，
只是出现时状态可能已变成 3。

因此下一轮的实验应当：**延长观察，抓"`esi` 为正"的那些帧，同时记录当时的
`obj1[0x120]`**。若发现"`esi` 为正时状态恒为 3"，则问题就是纯时序，
需要让状态别那么快变成 3；若发现"`esi` 为正时状态也是 1 却没写 2"，
则说明还有别的条件。

**这是下一步唯一需要回答的问题。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.105"),
                         ("HANDOFF-CURRENT.md", "### 15.93")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.105", "### 15.93")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
