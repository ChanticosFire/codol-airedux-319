"""Record round 174: the field the sender reads is zero, which explains state 5."""
from pathlib import Path

TEXT = """
### 12.189 ★★★ 发送读取的字段 `[+0x80]` 为 0，端口实际在 `[+0x88]`（2026-10-26 13:5x）

#### 实测

在九字节 `0x15` 回复生效的运行中读取服务器列表对象的字段：

```
t= 17.45  1A0=   1  [+0x80]=0  [+0x7C]=0  [+0x84]=2  [+0x88]=3074  1F4=1
t= 20.48  1A0=   5  [+0x80]=0  [+0x7C]=0  [+0x84]=2  [+0x88]=3074  1F4=1
```

**状态从 1 变成 5 时，`[+0x80]` 始终是 0。**

#### 这直接解释了状态 5

§12.188 追踪到发送链是：

```
0xC73F30 -> 0xB754C0（取端口）-> rep movsd 132 字节 -> 0xBB1420（sendto）
```

**而 `0xB754C0(ecx)` 读的是 `[ecx+0x80]` 处的 word——实测为 0。**

**端口为 0，`sendto` 必然失败，返回值不可能等于序列化长度，
于是 `0xBBA7D6` 的比较失败，状态被写成 5。**

#### 同时纠正一个旧结论

§12.73 曾把端口 3074 定位在 `+0x84`。**实测 `[+0x84] = 2`，而 `[+0x88] = 3074`。**

**所以端口在 `+0x88`，不在 `+0x84`。**

（§12.82 的 `0xB75440` 比较的是 `+0x84`，那个函数比较的是"类型/序号"之类的短字段，
不是端口——旧记录里把它当成端口是错的。）

#### 于是问题变成：谁该写 `[+0x80]`

`[+0x80]` 是发送时用的端口，**它一直是 0**，说明**从未被赋值**。

**两种可能：**

1. **它是从服务器列表条目里复制过来的**，而条目从未到达 → 保持 0；
2. **它应当由某个初始化步骤写入**（例如绑定 socket 时记录本地端口），而该步骤未执行。

**第 1 种与整体根因一致：列表数据没到，所以依赖它的字段都是 0。**

#### 下一步

**反汇编 `0xB754C0` 确认它真的读 `+0x80`**，并找出 `[+0x80]` 的所有写入点。

**若有写入点位于"解析列表条目"的代码里，那就确认了第 1 种解释——
只要我们的 `0x15` 消息能正确填出条目，`[+0x80]` 就会被赋值，发送就能成功，状态就能到 2。**

**这形成了一条清晰的因果：条目数据 → `[+0x80]` 端口 → 发送成功 → 状态 2 → 状态 4 → `1F4 = 2`。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.189"),
                         ("HANDOFF-CURRENT.md", "### 16.77")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.189", "### 16.77")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
