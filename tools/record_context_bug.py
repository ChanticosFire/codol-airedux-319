"""Record round 37: the thread-context sampler was broken, so "pump never runs" is unproven."""
from pathlib import Path

TEXT = """
### 12.55 采样工具本身有 bug——「pump 不在跑」的结论**不成立**（2026-10-23 11:4x）

#### 先说结论

本轮想验证 pump 是否每帧执行，写了 `tools/catch_pump_frame.py` 抓线程上下文，
结果 **0 命中**。但进一步检查发现**是工具错了**，不是 pump 不在跑：

```
CONTEXT size = 204 (expect 716)
```

我定义的 `CONTEXT` 结构只有 **204 字节**，而 Windows x86 的 `CONTEXT` 是 **716 字节**。
`GetThreadContext` 虽然返回成功（20/20），但**只填了前 204 字节**，`Eip`
读到的位置因此是错的——永远匹配不上任何函数地址。

**所以"25 秒内 pump/FE 梯/0xBBAD40 全部 0 采样"这个观测无效，不能据此
推断 pump 没有执行。**

#### 尝试修复时遇到的第二个问题

改用 1024 字节原始 buffer + `struct.pack_into("<I", buf, 0, 0x00010007)`
（`CONTEXT_FULL`）后，`GetThreadContext` **全部返回失败**——连之前"成功"的
那个版本也不成立，说明 204 字节结构下的"成功"其实是未定义行为。

正确的做法需要完整的 `CONTEXT` 定义（含 `FLOATING_SAVE_AREA` 与
`ExtendedRegisters[512]`），或者直接用 `ctypes` 按 Win32 头文件声明。
本轮**未完成**该修复。

#### 已知的候选偏移（待验证）

按 x86 `CONTEXT` 布局推算，`Eip` 应在偏移 **188** 附近（`ContextFlags` 4 +
`Dr0-Dr7` 28 + `FloatSave` 112 + `SegGs-SegDs` 16 + `Edi-Eax` 32 + `Ebp` 4 =
196，若 `Dr` 区或 `FloatSave` 有一处差 8 则为 188）。需要用正确结构实测确认，
不能靠推算。

#### 这修正了什么

§12.48 / §12.51 / §12.53 里关于"pump 每帧执行、每帧写 1"的表述，
**其证据链并不包含"观测到 pump 在运行"**——它是从"`[lobby+0x1F4]` 恒为 1"
加上"`0xBAE7AA` 写 1"推出的。如果 pump 其实只在启动时跑过少数几次，
那么"每帧失败"的说法也不准确，`0xBBAD40` 失败的时机描述需要相应调整。

**但下列事实不受影响**（它们来自静态反汇编 + 内存读数，与采样工具无关）：

| 事实 | 来源 |
|---|---|
| `[lobby+0x1F4]` 恒为 1 | 200 Hz × 5 s 采样，921 次（读内存，非线程上下文） |
| `obj2+0x1A0` = 5 | 直接读内存 |
| `obj1+0x120` = 3 | 直接读内存 |
| `0xBAE1AC` 写 2 且无跳转指向它 | 静态反汇编 + 跳转映射 |
| `0xBBADCD` 写 5 是 `0xBBAD40` 的失败分支 | 反汇编 + 模式扫描 |
| 容器查找要求 {类型 0x14, 子类型 2, key 0, 长度 1288} | 反汇编 |
| 长度检查是 `jne`（严格相等） | 反汇编 |

#### 下一步

把 `CONTEXT` 定义修正为完整的 716 字节结构，重新验证 pump 的实际执行频率。
这一步必须先做——否则"pump 每帧失败"这个前提一直是未证实的，
后续所有关于时序的推论都缺乏基础。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.55"),
                         ("HANDOFF-CURRENT.md", "### 15.43")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.55", "### 15.43")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
