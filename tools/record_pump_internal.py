"""Record round 187: the whole advance-to-4 path is pump-internal, plus a tool range bug."""
from pathlib import Path

TEXT = """
### 12.202 ★★★★ 结构性发现：整条"推进到 4"的路径完全在 pump 内部（2026-10-26 20:2x）

#### 全镜像调用者

```
callers of 0xBBADE0 : 0xBAE2C2    （1 个）
callers of 0xBBAAF0 : 0xBBAE3A    （1 个，位于 0xBBADE0 内）
```

#### 完整链条

```
pump (0xBAD800)
  └─ 0xBAE2C2  call 0xBBADE0(serverlist, &136字节结构)
       └─ 0xBBAE24  sub esp, 0x88        复制 136 字节
       └─ 0xBBAE3A  call 0xBBAAF0
            └─ 0xBBAB33  test edi,edi    检查长度
            └─ 0xBBAB57  call 0xBC1D20   解析
            └─ 0xBBAB66  call 0xBC1CB0   取类型
            └─ 0xBBAB6B  cmp al,0x15     类型必须 == 0x15
            └─ 0xBBAB7C  call 0xBBA900   状态 = 4
```

**所以"把服务器列表状态推进到 4"从来不是网络接收回调——
它是 pump 每帧主动调用的处理流程，输入是 pump 栈上的一份 136 字节副本。**

#### 数据来自 pump 的局部变量

```asm
0xBAE29A  push esi
0xBAE29B  lea eax, [ebp-0x548]
0xBAE2A1  push eax
0xBAE2A2  sub esp, 0x88
0xBAE2A8  lea edx, [ebp-0x768]     ; ★ 源
0xBAE2AE  mov ecx, esp
0xBAE2B6  push edx
0xBAE2B7  call 0xB753C0             ; 复制 136 字节
0xBAE2BC  mov ecx, [ebx+0x1FC]
0xBAE2C2  call 0xBBADE0
```

**`[ebp-0x768]` 是 pump 的栈局部变量——那 136 字节的来源在 pump 自己的栈帧里，
而不是直接来自 socket 缓冲区。**

**这解释了一件事**：我们向 3074 发 `0x15` 消息后状态变成 5 而不是 4，
**因为我们的消息根本没进入这条路径**——这条路径读的是 pump 栈上的数据，
那份数据由更早的某个环节填充（很可能就是我们没触发的环节）。

#### 工具缺陷（本轮发现）

**`branches_to.py` 的默认扫描范围是 `0xBB9000`–`0xBBC000`，
本轮第一次扫描因此漏掉了 `0xBAE2C2`（它小于 `0xBB9000`）。**

**用 `--lo 0x400000 --hi 0xDD0000` 全镜像扫描才找到调用者。**

**这是重要的工具教训：默认范围会给出假阴性。**

#### 下一步

**看 `0xBBAB1E`–`0xBBAB33`**——`0xBBAAF0` 如何得到 `edi`（长度）与那 136 字节的源指针。

**这与"pump 栈上那份数据由谁填充"是同一个问题。**

**若能定位填充点，就知道该由服务端提供什么。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.202"),
                         ("HANDOFF-CURRENT.md", "### 16.90")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.202", "### 16.90")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
