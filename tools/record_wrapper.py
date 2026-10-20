"""Record round 169: the validator is a thin wrapper around 0xBBA760 with a type of 3."""
from pathlib import Path

TEXT = """
### 12.184 验证器是一层薄封装：`0xBBA8C0` 调 `0xBBA760(this+4, 3)`（2026-10-26 11:0x）

#### 全文

```asm
0xBBA8C0  push ebx
0xBBA8C1  lea eax, [ecx+4]          ; ★ 参数：this + 4，即那 136 字节数据区
0xBBA8C4  push eax
0xBBA8C5  push 3                     ; ★ 参数：类型 3
0xBBA8C7  call 0xBBA760              ; ★ 真正的验证
0xBBA8CC  mov bl, al
0xBBA8CE  cmp bl, 1
0xBBA8D1  jne 0xBBA8D8
0xBBA8D3  call 0xBA4B20               ; 日志
0xBBA8D8  mov al, bl
0xBBA8DB  ret
```

**`0xBBA8C0` 只是把 `(this+4, 3)` 转交给 `0xBBA760`，返回它的结果。**

#### `0xBBA760` 此前已出现过

§12.161 记录过它被三处调用：

```
0xBBA8A7  call 0xBBA760   （在 0xBBA8A0 内，参数 2）
0xBBA8C7  call 0xBBA760   （本轮，参数 3）
0xBBA8EA  call 0xBBA760   （在 0xBBA8E0 内，参数 2）
```

**三个包装函数 `0xBBA8A0` / `0xBBA8C0` / `0xBBA8E0` 分别以类型 2 与 3 调用它，
把同一个 136 字节区的不同偏移（`+0x8C`、`+4`）交给它检查。**

#### 这是整条链的最后一层

状态机 → 状态码 → 消息格式 → 解析器 → 复制到 `[ebx+0x114]` → 验证器 →
**`0xBBA760`（真正的字段检查）**

**反汇编它就能知道那 136 字节里哪些字段必须满足什么条件。**

**届时就能构造一条真正通过验证的 `0x15` 消息，
状态应当从 5（失败）变成 2（通过），再经由 `0xBBA900` 路径走到 4，
最终让 `1F4` 变成 2 —— 这正是 M4 第一个里程碑的前置条件。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.184"),
                         ("HANDOFF-CURRENT.md", "### 16.72")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.184", "### 16.72")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
