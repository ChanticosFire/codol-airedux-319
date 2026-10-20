"""Record round 21: M3's actual recipe and the config experiment."""
from pathlib import Path

TEXT = """
### 12.37 ★★ M3 的真实配方被找出来了（2026-10-23 03:0x）

#### 关键证据：`runs/20261022-1604220-min/patch.json`

M3 达成大厅那次运行的记录只有 **6 个补丁**、**53 条采样事件**、**没有** `ui_activate`：

```json
"command_line": "…\\codoMP_client_shipRetail.exe -q"
"patches": [
  {"rva":"0x403699","original":"741f",         "replacement":"eb1f"},
  {"rva":"0x403659","original":"893540ba4a08", "replacement":"909090909090"},
  {"rva":"0x3f2a0a","original":"3dbc0200007407","replacement":"b8bc0200009090"},
  {"rva":"0x3ee9dc","original":"e82f2f0100",   "replacement":"9090909090"},
  {"rva":"0x37c860","original":"558bec83e4f8", "replacement":"c39090909090"},
  {"rva":"0x20c649","original":"b001",         "replacement":"b000"}
]
"notes": ["runtime-only patches; on-disk client unchanged"]
```

**注意最后一条是 `b001 -> b000`**。而本项目后来的补丁集写的是
`0x20C649:B000:B001`，方向正好相反。

#### 关键证据：那次运行的 `lsg.jsonl`

```
13:26:15 plaintext_frame / gate_reply / plaintext_frame2
13:26:15 session_derived challenge_verified; client-memory-read=false
13:26:15 token_reply
13:26:15 client_frame … payload_len=83
13:26:15 task_request service=71 task=4
13:26:15 candidate_task_reply svc71/task4
13:26:54 client_frame … payload_len=8          <- 39 秒后！
13:26:54 task_request service=71 task=9
13:26:54 unhandled_task service=71 task=9
13:26:54 terminal_task_reply svc71/task9 error=14
13:26:54 client_frame … payload_len=142
13:26:54 task_request service=71 task=3
…
```

两条决定性的事实：

1. **客户端在 `71/4` 之后约 39 秒才发 `71/9`**——之前本项目只等 30-35 秒，普遍
   差一点点；本轮按 75 秒和 90 秒重测，仍然只有 `71/4`，所以时间不是唯一条件；
2. **`71/9` 收到 `error=14`（未实现）后，客户端照样继续发 `71/3`**——说明客户端
   不要求应答正确，只要**有**应答就往下走。

#### 本轮实测对比

| 配置 | dw | G1 | gate | 客户端是否发 71/9 | 画面 |
|---|---|---|---|---|---|
| 15 补丁 + 强推 G1 + firstlogin 修复 | 5 | 3 | 1 | **否**（等 75s） | 「取一个代号」 |
| 15 补丁 + 强推 G1，**不修 firstlogin** | 5 | 3 | 1 | **否** | **空白前端背景** |
| **M3 的 6 补丁，不推 G1，不激活** | 5 | **0** | **0** | 否（等 90s） | 未观察 |

第三种配置下 `G1=0`、`gate=0`，FE 梯**完全没动**——但 M3 当时画面是大厅。
说明 M3 的 FE 梯是**自然前进**的，其触发条件在我们现在的环境里已不成立。

#### 一个失败的实验：恢复 2021 年原始存档

`E:\\GAME\\COD\\使命召唤OL\\players\\config_mp.cfg`（7850 B，2021-08-29）是用户
原始的在线存档。把它复制进隔离副本后**客户端直接崩溃**（`no visible CODO window`，
LSG 会话一条事件都没有），已回滚。

对比发现 `config_mp.cfg` **每次保存都用不同密钥加密**（原始 7850 B 与当前 7864 B
有 7825 字节不同），无法做字节级差异分析，也不能跨环境搬运。

#### 结论

M3 的成因已定位到**补丁集规模**（6 个而非 15 个）与**没有强推 G1**，
但直接复原 6 补丁后 FE 梯不前进，说明还缺一个当时自然发生的触发条件。
该条件最可能依赖 `config_mp.cfg` 里的有效存档（代号已存在），而当前副本的存档
已被多次运行改写。

#### 下一步

1. 用 6 补丁 + 只补 `firstlogin`（不动其它）测试，看 FE 梯能否前进到 `G1=1`；
2. 若不行，逐个回退 15 补丁中的 9 处 pump 补丁，找出哪一处让 `71/9` 不再发出；
3. 保留 `runs/20261022-1604220-min/patch.json` 作为唯一可信的"能进大厅"基线，
   后续所有实验都以它为参照做二分。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.37"),
                         ("HANDOFF-CURRENT.md", "### 15.25")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.37", "### 15.25")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
