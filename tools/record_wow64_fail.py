"""Record round 38: CONTEXT fixed to 716B but Wow64GetThreadContext still returns nothing."""
from pathlib import Path

TEXT = """
### 12.56 CONTEXT 结构已修正，但线程上下文读取仍失败（2026-10-23 12:0x）

#### 已修正的部分

`tools/thread_ctx.py` 现在使用**完整的 716 字节** x86 `CONTEXT`：

```
ContextFlags        0
Dr0..Dr3, Dr6, Dr7  4..24
FloatSave          28   （112 字节）
SegGs..SegDs      140..156
Edi..Eax          156..180
Ebp, Eip          180, 184     <- Eip 在 184
SegCs, EFlags     188, 192
Esp, SegSs        196, 200
ExtendedRegisters 204   （512 字节）
总计 716
```

结构大小已由 `assert ctypes.sizeof(CONTEXT) == 716` 保证。

#### 但读取依然失败

```
pid=28100 threads=58 CONTEXT=716B
threads with a code-like Eip: 0/58
```

诊断显示 `OpenThread` 58/58 成功、`GetThreadContext` **58/58 也返回成功**，
但**读出的所有字段都是 0**：

```
ctx ok tid 27640 {'0xb4': '0x0', '0xb8': '0x0', '0xbc': '0x0', '0xc4': '0x0'}
```

#### 根因已定位：位数不匹配

```
python 3.13.14 bits 64
client machine 0x14c (x86, 32 位)
Wow64GetThreadContext 可用: True
```

**当前 Python 是 64 位，客户端是 32 位。** 64 位进程对 WOW64 目标调
`GetThreadContext` 是未定义行为——它返回 TRUE 却什么都不填，这正好解释了
"成功但全 0"。

改用 `Wow64GetThreadContext` 后**仍然 0/58**。可能原因：

1. 目标线程必须先 `SuspendThread`；
2. `OpenThread` 需要用 `Wow64` 兼容的访问权限组合；
3. `Wow64GetThreadContext` 在 64 位宿主上对已运行的 32 位线程有额外限制。

#### 这一系列失败的方法论教训

从第 37 轮开始，我连续两次把**测量工具的问题**误当成**被测对象的行为**：

| 轮次 | 错误工具 | 错误结论 |
|---|---|---|
| 37 | 204 字节 CONTEXT | "pump 不在跑" |
| 38 | 64 位读 32 位 | "pump 不在跑"（修正后） |

两次都是"返回成功但数据为空"，而我没有在**第一次使用工具时就做自检**。
`thread_ctx.py` 现在带有 `SELF-CHECK FAILED` 断言，这正是应该在第 37 轮就做的事。

#### 下一步（三种可选，按成本排序）

1. **加 `SuspendThread`**：在 `OpenThread` 后先 `SuspendThread`，读上下文，
   再 `ResumeThread`。成本最低，先试这个；
2. **改用调试器路径**：`CreateProcess` 带 `DEBUG_ONLY_THIS_PROCESS`，用
   `WaitForDebugEvent` 拿 `CREATE_THREAD_DEBUG_INFO` 的初始上下文，或用
   `DebugActiveProcess` 附加后接收 `EXCEPTION_DEBUG_EVENT`。这条路确定可行，
   但要重写启动流程；
3. **放弃线程采样**：改用纯静态分析 + 已有的内存读数（`[lobby+0x1F4]`、
   `obj1/obj2` 字段），这些数据本身已经足够支撑结论，只是时序描述不确定。

**建议先试 1**，若仍失败则接受方案 3——因为 §12.55 已确认那些静态事实不依赖
采样工具，且"pump 是否每帧运行"对最终目标（进大厅）并非必要条件。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.56"),
                         ("HANDOFF-CURRENT.md", "### 15.44")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.56", "### 15.44")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
