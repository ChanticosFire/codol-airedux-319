"""Record the D-structure finding and the write-vs-stub distinction."""
from pathlib import Path

TEXT = """
### 12.40 `[0x3306D60]` 是全局静态的字符串表，不是账号对象（2026-10-23 04:1x）

#### 结构实测

`D = [0x3306D60] = 0x80FA044`。这是 **EXE 数据区里的全局静态**，不是堆对象
（地址落在 `0x400000 + 0x40FA044`，与模块基址一致）。转储 96 字节：

```
0x080fa044  68 d5 db 00  00 00 00 00  00 00 00 00  00 00 00 00   <- [D+0x00]=0x00DBD568
0x080fa054  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00   <- 0x081A76E8, 200.0f
0x080fa064  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00
0x080fa074  e8 76 1a 08  00 00 00 00  00 00 48 43  00 00 00 00
0x080fa084  00 00 00 00  00 00 00 00  00 00 00 00  70 d5 db 00
0x080fa094  00 00 00 00  06 00 00 00  01 00 00 00  00 00 00 00
```

**`[D+0x0C] = 0x80FA050`，值 0**——正是 `0x6BBF30` 检查的那个字段，
也正是 `fix_firstlogin()` 写入 1 的地址。

`[D+0x00]` 指向 `0x00DBD568`，读出来是：

```
2816    1858    1859    cod4master.activision.com    1860    1861    …
```

即一张**字符串/键值表**（端口号与 master server 域名混排），**不是玩家账号对象**。

#### 由此产生的关键区分

| 操作 | 结果 |
|---|---|
| 写 `[D+0xC] = 1`（`fix_firstlogin`） | **不崩溃**，画面停在代号页 |
| 强行把 `0x6BBF30` 改成 `mov eax,1; ret` | **24 秒后崩溃** |

两者都让 `0x6BBF30` 返回 1，但结局完全不同。差别在于**打桩跳过了函数体**，
而函数体里除了这个判断还有别的工作（返回路径前会经过
`0x6BBF46` 之后的代码，以及 `0x6BBF60` 的 `onboard_character_selected` 设置）。
直接 `ret` 把这些副作用全部跳过，后续阶段就拿到不一致的状态。

**写字段是安全的，打桩是不安全的。** 这一区分纠正了上一轮"写 1 有害"的判断
（§12.36 认为 firstlogin 修复把客户端推离大厅，但那可能是 `fix_fe_loaded`
同时改 `script_state`/`fe_final` 造成的，需要单独验证）。

#### 下一步（明确的分离实验）

依次测试三种配置，确定到底是哪一项导致画面停在代号页：

| 编号 | 补丁 | 内存写入 | 预期 |
|---|---|---|---|
| A | 15 处 | 只写 `[D+0xC]=1` | ？ |
| B | 15 处 | 写 `[D+0xC]=1` + `script_state=1` | ？ |
| C | 15 处 | 写 `[D+0xC]=1` + `script_state=1` + `fe_final=1` | 已知停在代号页 |

若 A 能进大厅，则说明 `fix_fe_loaded` 是多余的且有害，应从 `auto_lobby.py` 移除。
这一实验成本很低（每次约 2 分钟），优先做 A。

#### 新增工具

`tools/show_patches.py`（显示补丁应用状态）与 `tools/show_lsg.py`
（精简 LSG 事件视图）已加入工具集，后续所有实验都用它们核对。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.40"),
                         ("HANDOFF-CURRENT.md", "### 15.28")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.40", "### 15.28")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
