"""Record round 22: patch semantics clarified, all 15 verified applied."""
from pathlib import Path

TEXT = """
### 12.38 澄清补丁参数语义；15 补丁全部确认应用（2026-10-23 03:2x）

#### `patch_runtime.py` 的参数是 `RVA:NEW:EXPECTED`

```python
parts = spec.split(":")
rva      = int(parts[0], 0)
new      = bytes.fromhex(parts[1])      # 第 2 段 = 要写入的新字节
expected = bytes.fromhex(parts[2])      # 第 3 段 = 期望的原始字节
```

所以 `0x20C649:B000:B001` 的含义是「把 `b001` 改成 `b000`」，**方向一直是对的**。
上一节（§12.37）据此推断"补丁方向写反、22 轮从未生效"是**误读**，应予更正。

#### 运行内存实测原始字节（Build 1604220）

```
0x20C649: b001
0x403699: 741f
0x403659: 893540ba4a08
0x3F2A0A: 3dbc02000074…
0x3EE9DC: e82f2f0100
0x37C860: 558bec83e4…
```

与 M3 的 `patch.json` 记录逐条一致。

#### 15 个补丁全部 `applied=True, verified=True`

```
OK 0x403699  741f           -> eb1f
OK 0x403659  893540ba4a08   -> 909090909090
OK 0x3f2a0a  3dbc0200007407 -> b8bc0200009090
OK 0x3ee9dc  e82f2f0100     -> 9090909090
OK 0x37c860  558bec83e4f8   -> c39090909090
OK 0x20c649  b001           -> b000
OK 0x7ba295  7e1a           -> 9090
OK 0x7ba29d  7512           -> 9090
OK 0x7ba276  7439           -> 9090
OK 0x7bad4d  7572           -> 9090
OK 0x7adc27  feffffff       -> 01000000
OK 0x7adde0  feffffff       -> 01000000
OK 0x7ae754  feffffff       -> 01000000
OK 0x7ae76c  feffffff       -> 01000000
OK 0x7ae7b0  feffffff       -> 01000000
```

**补丁侧没有问题。** 之前 `patch.json` 缺失只是因为在 `Start-Job` 里用了
`--observe 200` 而 job 被提前 `Stop-Job`，进程没走到写证据那一步。

#### 剩余差异只有一个：FE 梯不自然前进

| 配置 | dw | G1 | gate | 71/9 | FE_state |
|---|---|---|---|---|---|
| 15 补丁，不强推，不激活，等 90 s | 5 | **0** | **0** | 否 | 5 |
| M3 的 6 补丁，不强推，不激活 | 5 | 0 | 0 | 是（+39 s） | — |
| 15 补丁 + 强推 G1=2 + 不修 firstlogin | 5 | 3 | 1 | 否 | 5 |

关键读数：`[D+0xC] = 0`，即 `0x6BBF30`（firstlogin）返回 0，FE 梯因此停在 `G1=0`。

M3 时它必然返回过 1 或走了别的路径，否则梯子不会动。而
`[D+0xC]` 的来源是客户端从存档里读出的账号状态——当前副本的
`config_mp.cfg` 已被多次运行改写（7864 B，比原始 7850 B 多 14 B），
不再包含有效的代号信息。

#### 结论

22 轮之后可以确定：**补丁、协议、坐标都不是问题**，唯一缺口是
**客户端存档里没有有效的"已建档"状态**，导致 `0x6BBF30` 返回 0、
FE 梯不前进、`0x730C50` 不报告 FE 加载、`onboarded` 不设位。

这个状态本应由「取一个代号」提交产生，而提交路径在 UI 层且不产生网络请求。

#### 下一步（二选一，需人工介入）

1. **人工**：由用户手动完成一次代号流程，之后把
   `runtime/client-1604220/players/config_mp.cfg` 备份为
   `config_mp.cfg.onboarded`。后续所有运行都用这份存档，即可稳定进大厅。
2. **自动**：直接对 `0x6BBF30` 打桩成 `mov eax,1; ret`，绕过 firstlogin 判断。
   风险是后续状态机可能因缺少配套字段而崩溃——但成本极低，值得一试。

建议先试 2，失败再走 1。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.38"),
                         ("HANDOFF-CURRENT.md", "### 15.26")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.38", "### 15.26")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
