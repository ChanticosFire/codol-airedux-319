"""Record round 96: the probe missed the window again - successes finish within 2s of dw==5."""
from pathlib import Path

TEXT = """
### 12.111 又一次错过窗口：`dw==5` 后 2 秒内成功就全部完成（2026-10-24 19:2x）

#### 本轮做法与结果

先锚定 `dw==5`（18.88 秒到达），用 `poll_counters` 采 3 秒：

```
  0.00  success=6   bytes=508  status=1  idx=2
  1.00  success=10  bytes=634  status=1  idx=4
  2.00  success=13  bytes=729  status=3  idx=5
```

**成功在 2 秒内从 6 涨到 13 并结束。**

随后在 `0xBB172B`（`mov eax,esi`，成功路径返回前的最后一条寄存器赋值）
装探针，重放 9 字节 `8B C6 | 5E | 11 15 A4 5C E8 00`（逐条数过）：

```
[ret] hook 0xbb172b -> cave 0x58cf0000  slot 0x58cf0100  reg esi
[ret] n=0  esi=0x00000000  chain[0xE85CB0]=0x00000000
[ret] final n=0  esi=0x00000000
```

**探针一次都没命中。**

#### 原因：装得太晚

`poll_counters` 先跑满 3 秒才退出，`probe_reg` 之后才装。而成功在 `dw=5` 后
**约 2 秒内**就全部结束（t=2.00 时已是 13），所以探针装上时窗口已经关闭。

**这是连续第三次因为"装得太晚"而错失窗口**：

| 轮次 | 做法 | 结果 |
|---|---|---|
| 91 | `dw=5` 后装 `0xBBA418` | 采 45 秒，`esi` 恒 -2（窗口已过） |
| 92 | 同上 | 同上 |
| **96** | 锚定后先跑 3 秒轮询，再装 `0xBB172B` | **0 次命中** |

**根本问题：探针必须在 `dw==5` 之前就装好。**

#### 这也再次印证了窗口的短暂

- `dw=5` 到达的那一刻，`success` 已经是 6；
- 之后 2 秒内冲到 13；
- 此后永远不变。

**这 2 秒就是全部机会。**

#### 下一步：先装探针，再等窗口

`probe_reg.py` 需要支持"等客户端出现再装 hook"：

1. 用 `run_verified.ps1 -SkipWait` 起服务与 patch（约 5 秒）；
2. 立刻执行 `probe_reg.py --wait 60 --at 0xBB172B ...`——它会等客户端进程出现，
   在其中 `VirtualAllocEx` 分配 cave 并写入 hook；
3. 客户端随后才跑到 `dw=5`，那时 hook 已就位，能捕获全部成功。

**要点**：hook 必须写在客户端**真正开始执行虚函数之前**。由于客户端从进程创建到
`dw=5` 有约 19 秒，而服务与 patch 只要 5 秒，这个顺序是完全可行的。

若 `0xBB172B` 能捕获到命中，就能直接读出成功时的 `esi`，从而一举判定
"`count` 是否应当为正"这个悬而未决的核心矛盾。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.111"),
                         ("HANDOFF-CURRENT.md", "### 15.99")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.111", "### 15.99")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
