"""Record the firstlogin fix and the current M4 state."""
from pathlib import Path

TEXT = """
### 12.20 ★★ firstlogin 修复：选人界面被跳过（2026-10-23 00:2x）

#### 根因（反汇编 `0x6BBF30`）

FE 梯在 `G1==0` 时调用 `0x6BBF30`，只有返回 1 才前进。该函数完整逻辑：

```asm
0x6BBF30  mov eax, 1
0x6BBF35  cmp [0x331C5C0], eax      ; 全局标志 == 1 ?
0x6BBF3B  jne 0x6BBF46
0x6BBF3D  cmp [0x84ABA50], 4        ; ui_state == 4 ?
0x6BBF44  je  0x6BBF54              ; 是 -> eax=1 返回
0x6BBF46  mov ecx, [0x3306D60]
0x6BBF4C  cmp dword [ecx+0xC], 0
0x6BBF50  jne 0x6BBF54              ; 非零 -> eax=1 返回
0x6BBF52  xor eax, eax              ; 否则 0
0x6BBF54  ret
```

离线环境下两个条件都不成立（`ui_state=9`、`[[0x3306D60]+0xC]=0`），函数恒返回 0，
所以 FE 梯永远停在 `G1=0`，选人界面就一直挂着——这解释了为什么之前写
`onboard_character_selected` 完全没有效果（那个统计项根本不参与这个判定）。

#### 修复

把 `[[0x3306D60]+0xC]` 写成 1 即可满足第二条路径，不必碰 `ui_state`：

```python
ptr = read_u32(h, 0x3306D60)
write_u32(h, ptr + 0xC, 1)
```

已集成到 `tools/auto_lobby.py::fix_firstlogin()`，在 `dw>=2` 时自动执行。

#### 验证

截图确认画面从「选择角色」变成训练官欢迎页：

> 欢迎来到使命召唤ONLINE！我是你的训练官。开始之前，请先取一个代号。

输入框 + 「继续」按钮，**选人界面确实被跳过了**。

#### 「取代号」仍需协议配合

用户实测：在该页填入代号后点「继续」无法进入下一步——**提交需要服务端确认**。
但目前抓到的所有 session 里，客户端在该页**没有发出任何新的 task**
（`lsg.jsonl` 始终只有 `svc71/task4` 加保活），因此提交路径尚未定位。

#### 本轮排除的假设

| 假设 | 结果 |
|---|---|
| 零帧保活干扰后续请求 | 关掉 `LSG_ZEROFRAME` 仍只有 task4 |
| pump 9 处补丁导致行为变化 | 只用 6 处补丁仍只有 task4 |
| 强推 `G1=2` 让客户端不再要数据 | 不强推也只有 task4 |
| 6 处补丁 + firstlogin 能复现 `71/9` | 仍只有 task4 |

结论：`20261022-1604220-min` 那次出现的 `svc71/task9` 是客户端侧竞态，
目前无法稳定复现。

#### 新增工具

| 工具 | 作用 |
|---|---|
| `tools/find_refs.py` | 搜索引用某数据地址的 imm32（`0xDC3EA0` → 4 处引用） |
| `tools/dump_code.py` | dump + capstone 反汇编运行时代码 |
| `tools/dump_fe_state.py` | 采样 `0x82E1300` 区域，对比推进前后变化 |
| `tools/summarize_tasks.py` | 汇总全部 run 的业务 task |
| `tools/type_text.py` | SendInput / WM_CHAR 两种输入方式，含窗口激活点击 |

#### 下一步

「取代号」需要协议应答才能过关，但请求形态尚未抓到。可选路径：

1. 在客户端提交代号**前后**对比 `lsg.jsonl`，确认是否真的没有网络请求；
2. 若确实无请求，则该步骤可能读取本地/内存中的账号对象，需要从 UI 层
   （`first-page-routes.json` 提到的 `MatchService`）反查它等待的条件；
3. 同时继续 `svc71/task4` 的应答变体试验，看能否触发客户端进入房间流程。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.20"),
                         ("HANDOFF-CURRENT.md", "### 15.8")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.20", "### 15.8")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
