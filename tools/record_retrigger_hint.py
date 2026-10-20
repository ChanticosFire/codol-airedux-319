"""Record the incomplete community reference and the retrigger hint."""
from pathlib import Path

TEXT = """
### 12.34 社区参考脚本不完整；但暴露了「重触发前端」这一关键手法（2026-10-23 02:3x）

#### `rankIconTable.csv` 不在 `.ifs` 里

对 987 个 `.ifs` 包分别以 2 MB 与 6 MB 深度扫描 `rankIconTable`，命中 0；
扫描 `weapons_mp`、`.csv`、`mp/playlists` 等同样为 0。全客户端目录下也不存在
任何 `*.csv` 文件。

但在主程序字符串里找到了路径引用（VA `0xABDE33`）：

```
mp/callsignTitle.csv
mp/rankIconTable.csv
mp/callsignBackground.csv
mp/callsignIcon.csv
mp/callsignFrame.csv
```

即这些是**运行期由客户端按名字从 fastfile 里加载的资源**，不是 `.ifs` 容器里的
独立文件。fastfile 是加密的（§12.19 已确认 `mp_playlists.ff` 从 `0x14` 起高熵），
所以**无法离线提取**，必须在运行期让客户端自己去加载。

#### 社区脚本引用了不存在的依赖

`codol-ember/.../launch319-reference/reference/launch/` 只有 `orch319.py` 一个文件，
它 `import` 的下列模块**全部缺失**：

```
patches319.py          runtime_patch.py       rank_hook319.py
hide_text319.py        preload_rank_icons319.py       lc319/
```

其中 `preload_rank_icons319.py` 正是 `--preload-rank-icons` 调用的脚本，
`patches319.py` 里才有 `PATCHES` 字典（含 `lobby-pump-ok`、`register-ok`、
`lobby-ok` 三组补丁的实际内容）。**社区所说的"已验证"缺少可复现的脚本主体。**

#### 但 `orch319.py` 暴露了一个此前没试过的手法

```python
ap.add_argument("--retrigger-delay", type=float, default=45.0,
                help="首次激活后多少秒重触发前端（默认 45；越小进大厅越快）")
ap.add_argument("--retrigger-count", type=int, default=1,
                help="重触发次数（默认 1；可多触发几次抢时间）")
ap.add_argument("--activate-delay", type=float, default=0.0,
                help="dw=5 后再等 N 秒才激活前端（让数据先落地）")
```

以及循环里的注释：

```python
# dw=5 已调用一次；45 秒后重触发显示大厅（实测 46 秒可出 UI）。
```

**含义**：`0x5EBE10`（cppActivate）调一次不够，需要在约 45 秒后**再调一次**
才能真正显示大厅。我们的 `tools/ui_activate.py` 只调了一次。

这与我们观察到的现象一致：调一次后 `gate=1`、`G1=3`（前端 active），
但画面停在训练官/取代号页面——**前端被"激活"了但没"显示"**。

#### 另一批有用地址

`orch319.py` 里的钩子与常量清单：

```python
HOOKS = [
    (0xBA3BF0, "h81"),
    (0xBA3B20, "h83"),
    ...
]
```

- `0x5EBE10` cppActivate（前端激活）
- `0x4A6D50` 解锁判定（`--unlock-all` 桩成恒真）
- `0xBA3BF0` / `0xBA3B20` 与 `0x81`/`0x83` 帧相关（正是加密通道那两个入口）

#### 下一步

1. 给 `tools/ui_activate.py` 加 `--retrigger-delay` / `--retrigger-count`，
   在首次激活后按间隔重复调用 `0x5EBE10`；
2. 配合 `--activate-delay`（dw=5 后延迟再激活）测试不同时序组合；
3. 观察重复激活后画面是否从"取一个代号"变成真正的大厅。

这比继续挖 `[lobby+0x1F4]` 更有希望：社区明确说"越小进大厅越快"，
说明重触发确实是进大厅的必要步骤，而我们一直漏了它。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.34"),
                         ("HANDOFF-CURRENT.md", "### 15.22")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.34", "### 15.22")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
