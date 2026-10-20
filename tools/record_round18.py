"""Record round 18 results: resource extraction impossible, retrigger ineffective."""
from pathlib import Path

TEXT = """
### 12.35 重触发前端无效；资源提取确认为不可行（2026-10-23 02:5x）

#### 重触发测试（阴性）

按社区 `orch319.py` 的说法「45 秒后重触发前端，实测 46 秒可出 UI」，
用 `tools/ui_activate.py --reset` 清除一次性 guard 让 `0x5EBE10` 再执行：

```
=== waiting 50s for first activation to settle ===
before:  screens/r_before.png
=== reset guard (retrigger #1) ===
trampoline installed at 0xeed0000 (activates 0x5ebe10 once)
guard reset; activation will fire again
after1:  screens/r_after1.png
=== reset again (retrigger #2) ===
trampoline already installed, cave=0xeed0000
guard reset; activation will fire again
after2:  screens/r_after2.png
```

**三次截图（首次激活后、重触发一次、重触发两次）画面完全一致**，都停在
「欢迎来到使命召唤ONLINE！我是你的训练官。开始之前，请先取一个代号。」

所以「重触发前端」在我们当前的状态下**不产生任何可见变化**。

一个可能的原因：`--reset` 只是清了 guard，而 trampoline 挂在 FE 梯（`0x5EBFD0`）
上；如果 FE 梯在该阶段已不再被调用，guard 清得再多次也不会触发激活。
这一点无法从外部区分，因此不继续投入。

#### 资源提取（确认为不可行）

对 987 个 `.ifs` 包做 2 MB 与 6 MB 两档深度扫描：

| 关键词 | 命中 |
|---|---|
| `rankIconTable` | 0 |
| `weapons_mp` | 0 |
| `.csv` | 0 |
| `mp_rank`、`attachment` | 0 |

整个客户端目录下也不存在任何 `*.csv`。

而主程序里确实有这些路径（VA `0xABDE33`）：

```
mp/callsignTitle.csv
mp/rankIconTable.csv
mp/callsignBackground.csv
mp/callsignIcon.csv
mp/callsignFrame.csv
```

**结论**：它们是运行期由客户端从 fastfile 里按名加载的资源，不是 `.ifs` 容器中的
独立文件。fastfile 加密（`IWff0100` 头后从 `0x14` 起高熵，§12.19/§12.22 已验证），
因此**无法离线提取**。

这意味着 `LONG-RUN-GOAL.md` §9.3 的「资源最小集」中，
`rankIconTable.csv` 与武器/配件表**不能通过解包获得**，只能：
- 让客户端在运行期自己加载（需要先让 UI 进到对应页面），或
- 从社区参考数据抄录（社区仓库中不存在）。

#### 社区参考脚本的完整性

`launch319-reference/reference/launch/` 只有 `orch319.py` 一个文件，
其 `import` 的 6 个模块全部缺失：

```
patches319.py   runtime_patch.py   rank_hook319.py
hide_text319.py  preload_rank_icons319.py   lc319/
```

其中 `patches319.py` 才含 `PATCHES` 字典（`lobby-pump-ok` / `register-ok` /
`lobby-ok` 三组补丁的真实内容），`preload_rank_icons319.py` 是军衔图标预加载的实现。
**社区声称的"已验证"缺少可复现的脚本主体**，本项目的补丁集只能靠自身研究得出。

#### 本轮净结论

1. 重触发前端无效——不再尝试；
2. `rankIconTable.csv` 等资源无法离线提取——M4.2 的资源前置条件需重新定义；
3. 社区脚本不完整——不能作为实现参照，只能作为地址与手法线索。

#### 下一轮方向

既然资源路线和 FE 路线都受阻，回到 M4 的核心判据本身，做一件**不依赖客户端突破**
的事：把 `svc21/task5`（房间列表）与 `svc71/task9`（服务器信息）的应答帧结构
在离线单测中构造并自校验，同时补齐 `server319` 的服务能力测试。

这样即使客户端暂时进不去，服务端侧也已经"准备好"，一旦 UI 打通即可立即验证；
而且这部分工作有明确的 pass/fail，属于可交付的实质进展。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.35"),
                         ("HANDOFF-CURRENT.md", "### 15.23")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.35", "### 15.23")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
