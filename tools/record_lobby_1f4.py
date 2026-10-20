"""Record the [lobby+0x1F4] finding and the crash that follows it."""
from pathlib import Path

TEXT = """
### 12.22 ★★ [lobby+0x1F4] 是前端阶段机的扳机，但推到 2 会崩（2026-10-23 01:0x）

#### 完整因果链（全部反汇编验证）

```asm
; 0x621777 取 lobby 单例
0x621777  call 0x643280          ; mov eax,[0xE85C68]; 空则懒创建
0x62177C  mov esi, eax
0x621782  je 0x621A1A            ; 空 -> 跳过整段
0x62178A  mov ecx, esi
0x62178A  call 0xBAC350          ; = mov eax,[ecx+0x1F4]; ret
0x62178F  cmp eax, 1
0x621796  call 0xBAD800          ; == 1 时调用
0x62179D  mov ecx, esi
0x62179D  call 0xBAC350          ; 再读
0x6217A2  cmp eax, 2             ; ★ 必须等于 2
0x6217A5  jne 0x62199E           ; 否则跳过
0x6217AB  mov eax, [0xE59D20]    ; FE_state
0x6217B0  sub eax, 3
0x6217B3  je 0x6217CB            ; == 3 -> 写 4
0x6217B5  sub eax, 2
0x6217B8  jne 0x6217DF
0x6217BF  mov dword [0xE59D20], 6 ; ★ 我们的分支：5 -> 6
```

而 `0x730C50`（FE-loaded）又要求 `[0xE59D20] in {4,6}`，它返回 1 才会让
`0x6BBF60` 设置 `onboard_character_selected` 并推动 FE 梯。

#### 实测

`tools/probe_lobby_1f4.py` 通过 `[0xE85C68]` 找到 lobby 对象（本轮为
`0x37947E90`），读 `+0x1F4`：

```
[lobby+0x1F4] = 1     <- 代码要求 2
FE_state      = 5
dw            = 5
```

**写入 2 之后**（`--set 2`）：

```
01:03:49  [lobby+0x1F4]=1  FE_state=5  dw=5
01:03:50  [lobby+0x1F4]=2  FE_state=6  dw=5     <- 扳机生效
01:03:52  进程消失
```

**`FE_state` 确实从 5 跳到 6**，因果链完全成立。但客户端在 1-2 秒内崩溃。

#### 崩溃原因推测

`FE_state=6` 意味着前端进入"已加载"阶段，随后应该发生真正的 UI 资源加载。
崩溃可能因为：

1. 该阶段需要的资源（`.ff` 包）未就绪；
2. 通过强写得到的状态缺少配套的其它字段，前端初始化时解引用空指针；
3. `0xBAD800`（`== 1` 时才调用的那个函数）没被执行，留下了不一致状态。

#### 与社区结论的关系

社区文档（`PROGRESS.md` 与开发者口述）说：

> `[lobby+0x1F4]` 这个状态量以前从没撑过 47 秒就翻成 -2。根本原因是 pump 的匹配判定
> 失败后会走清理路径，把 1F4 写成 -2，而客户端再读到 -2 就认为连接已经失去。
> 一共改了 9 处运行期补丁……改完之后 `[lobby+0x1F4]` 首次稳定保持为 1。

关键差异：**社区让它保持 1**，而不是 2。我们观察到代码要求 2 才推进 FE_state，
但社区保持 1 时大厅就能正常渲染——说明在他们的环境里，FE 推进走的是另一条路径
（可能是时间顺序：先 `0xBAD800` 处理 1，再由别的逻辑写成 2）。

我们的 9 处 pump 补丁已经在用，`[lobby+0x1F4]` 稳定在 1——与社区一致。差别在于
社区能让客户端从 1 自然走到 2，而我们没有。

#### 下一步

1. 反汇编 `0xBAD800`（`== 1` 时调用），确认它是否负责把 1 推进到 2；
2. 若是，找出它失败的原因（可能依赖某个尚未实现的服务应答）；
3. 若不是，追踪 `[lobby+0x1F4]` 的全部写者，看谁在社区环境里写 2。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.22"),
                         ("HANDOFF-CURRENT.md", "### 15.10")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.22", "### 15.10")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
