"""Record round 65: fetch function counted 0, but the auth service failed to start."""
from pathlib import Path

TEXT = """
### 12.79 数据获取函数计数为 0，但本轮环境有故障（2026-10-24 01:4x）

#### 观测结果

在 `0xBB15E0` 入口装计数器（字节 `55 8B EC 83 EC 18` 是完整的 6 字节指令，
边界确认无误，本轮**没有**崩溃）：

```
[fetch] hook 0xbb15e0 -> cave 0x58e10000, counter 0x58e10200
[fetch] total after 15s = 0
```

**`0xBB15E0` 在 15 秒内零次调用。**

同时采样对象字段：

```
[obj+0x20] = 0xC874A994   10 秒后仍为 0xC874A994   changed = False
[obj+4] = 11620   [obj+8] = 0   [obj+0xC] = 0
```

`[obj+0x20]` 与上一轮（`0x0B2FBF93`）不同——说明它是堆上某个随运行变化的值，
但**在 10 秒窗口内没有更新**。

#### 但本轮环境有故障

启动 auth 服务时 PowerShell 报错：

```
Start-Process: 无法绑定参数，因为多次指定了参数 'ArgumentList'
```

我在命令里把 `-ArgumentList` 写了两次（`"-m","server319"` 后面又跟了一串）。
**auth 服务很可能没有启动**，因此整个登录流程可能不完整。

**所以"`0xBB15E0` 零次"这个观测不能作为结论**，它可能只是"登录没走完"
导致 pump 没进入正常状态。必须重测。

#### 与既有结论的张力

如果 `0xBB15E0` 真的是 0 次，那与 §12.76 的静态分析矛盾：

- pump 每帧 `0xBAE245 call eax`，`eax = [[lobby+0xC]] + 0x1C = 0xC73FB0`；
- `0xC73FB0` 第一条实质指令之后就是 `0xC7400E call 0xBB15E0`；
- 所以只要 pump 跑到 `0xBAE245`，`0xBB15E0` 就必然被调用。

零次只能说明 **pump 没跑到 `0xBAE245`**，即：

1. `0xBAE20B cmp [ebx+0x1F4], 1` / `jne 0xBAE7C9` 跳走了（`1F4 != 1`）；
2. 或 pump 本身没被调用；
3. 或本次运行环境异常（上面提到的 auth 未启动）。

第 3 条最可能，必须排除后才有意义。

#### 下一步（先修环境，再重测）

1. **修正启动命令**：`Start-Process -FilePath python -ArgumentList @(...)` 用数组，
   不要重复写 `-ArgumentList`；
2. 确认 `lsg.jsonl` 里出现 `client_frame_verified` 与 `task_request`，
   证明登录流程真的走完了；
3. 然后同时装两个计数器：`0xC73FB0`（虚函数入口）与 `0xBB15E0`（数据获取），
   二者都从已知正确边界安装（前者 `55 8B EC 6A FF 68 EB 2D C9 00` 为 10 字节，
   后者 `55 8B EC 83 EC 18` 为 6 字节）；
4. 若 `0xC73FB0` 有命中而 `0xBB15E0` 为零，说明虚函数在到达 `0xC7400E` 之前
   就返回了——那时才需要从 `0xC73FB0` 入口逐条反汇编找早退点。

**在环境确认干净之前，不再基于本轮数据做推断。** 这是第 64 轮教训的延续：
观测工具（包括启动脚本）本身必须先自证可用。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.79"),
                         ("HANDOFF-CURRENT.md", "### 15.67")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.79", "### 15.67")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
