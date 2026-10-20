"""Record round 91: in steady state the virtual function always returns -2; success is startup-only."""
from pathlib import Path

TEXT = """
### 12.106 ★★★ 稳态下 `esi` 恒为 `-2`；成功只发生在启动初期（2026-10-24 16:2x）

#### 工具升级

`probe_reg.py` 增加 `--mem-chain`，可按"绝对基址 + 偏移链"读内存：

```
--mem-chain 0xE85C68,0x1F8,0x120
  -> mov eax,[0xE85C68]      ; lobby
  -> mov eax,[eax+0x1F8]     ; obj1
  -> mov eax,[eax+0x120]     ; status
```

与 `--reg` / `--mem-ebp` 组合，一次挂载能同时看到"返回值 + count + 对象状态"。

#### 45 秒采样结果

```
[trio] n=0    esi=0x00000000  [0x94]=0x00000000  status=0x00000000
[trio] n=29   esi=0xfffffffe  [0x94]=0xfffffffe  status=0x00000003
[trio] n=59   … 完全相同 …
…
[trio] n=537  esi=0xfffffffe  [0x94]=0xfffffffe  status=0x00000003
```

**整个 45 秒窗口内，537 次调用全部是 `esi = -2`、状态恒为 3。**

`esi` 与 `[0x94]` 依然逐次相等（再次验证 §12.105），但**没有任何一次为正**。

#### 这与"成功计数非零"并不矛盾

此前多次读到 `[0xE85CB0] = 13`，而该全局量只在 `0xBB1734`（成功路径）被 `add`。
若 45 秒内一次成功都没有，那 13 次必然发生在**采样开始之前**——即客户端
**启动初期**。

**这解释了一个长期困惑**：为什么早先偶尔能观测到 `0xBB170C` 被命中几次
（第 69 轮 4 次、第 75 轮 11 次、第 76 轮 13 次），却始终无法让状态变化。
那些成功都挤在启动后的极短时间里，而探针通常是在 `dw=5` 之后才安装的，
**恰好错过了它们**。

#### 于是真正的窗口结构是

```
t=0        客户端启动
t≈?        虚函数短暂成功若干次（0xBB15E0 返回 >= 0）
           —— 此时如果 count > 0 且状态仍是 1，就会写 2
t≈2.5s     索引涨满 -> 写 3 -> 状态锁定
t≈23-24s   客户端才发出第一个 UDP 探测包（§12.102）
```

**关键矛盾：探测包在 23 秒才发出，而成功窗口在启动初期；两者根本不重叠。**

`0xE85CB0 = 13` 的那 13 次成功，是在**没有任何 UDP 应答**的情况下发生的——
说明它们不是由我们回包触发的，而是客户端启动流程内部的某种收发
（可能是 TLS/LSG 通道，或本地初始化）。

#### 这彻底改变了问题的性质

之前一直在想"怎么让应答赶上窗口"。现在看清了：

- 窗口在**启动初期**（约 0–2.5 秒）
- 探测包在**23 秒后**才发
- **中间差了 20 秒，任何针对探测包的应答都不可能进入窗口**

**所以要么：**

1. **把窗口往后移**——让状态不要那么快变成 3（抬容量、或阻止索引推进）；
2. **把成功提前**——在客户端启动初期就让那条 UDP 通道有数据
   （但客户端那时还没发探测包，服务端无从回应）；
3. **让 `Add` 在状态已为 3 时仍能写 2**——这需要改判定逻辑（运行期补丁）。

#### 下一步

**第 1 条最可行且已有基础**：抬容量到 200 后窗口约 100 秒，覆盖 23 秒的探测时刻。
但第 87 轮试过抬容量 + echo，状态仍是 1（且 `esi` 恒 -2）——**因为稳态下虚函数
根本不成功**。

**关键新疑问**：为什么第 87 轮抬容量后 `stat` 从 23 涨到 95（说明成功在增加），
而本轮 45 秒内 `esi` 恒为 -2？

两者可能矛盾，也可能 `stat` 的增长来自**另一条** `add`（`0xE85CB0` 或许
不止一个写入点）。**下轮应当先确认 `0xE85CB0` 的所有写入点**，再继续推理。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.106"),
                         ("HANDOFF-CURRENT.md", "### 15.94")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.106", "### 15.94")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
