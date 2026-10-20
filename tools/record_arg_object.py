"""Record round 17: the arg source is a live interface object, so the failure is the empty container."""
from pathlib import Path

TEXT = """
### 12.33 登记参数是活的接口对象，失败仍归结为空容器（2026-10-23 02:2x）

#### 追清 `0xBBAD40` 的四个参数

`0xBAE718 call 0xBBAEE0` 返回的是一个 8 字节的临时结构，内容固定：

```asm
0xBBAEE0  fld dword ptr [0xCAEB8C]
0xBBAEE6  mov eax, ecx
0xBBAEE8  fstp dword ptr [eax + 4]     ; [eax+4] = 某个浮点常量
0xBBAEEB  mov dword ptr [eax], 5       ; [eax] = 5
0xBBAEF1  ret
```

即 `[eax]` 恒为 **5**，`[eax+4]` 是一个浮点常量。这两项作为中间两个参数传入。

真正重要的是**第一个参数**——`0xBAE72E` 最后 push 的是 `[ebx+0xC]`：

```asm
0xBAE71D  mov ecx, [eax + 4]
0xBAE720  mov edx, [eax]
0xBAE722  push ecx                    ; 浮点
0xBAE723  mov ecx, [ebx + 0xC]        ; ★ lobby+0xC
0xBAE726  push edx                    ; 5
0xBAE727  lea eax, [ebp - 0x658]
0xBAE72D  push eax                    ; &local
0xBAE72E  push ecx                    ; ★ lobby+0xC  -> [ebp+8]
0xBAE72F  mov ecx, [ebx + 0x1FC]      ; this = 容器
0xBAE735  call 0xBBAD40
```

在 `0xBBAD40` 内部：

```asm
0xBBAD4F  mov eax, [ebp + 8]          ; = lobby[0xC]
0xBBAD52  test eax, eax
0xBBAD54  je 0xBBADAB                 ; 为 0 才失败
0xBBAD58  mov dword ptr [ebx], eax    ; 容器首字段 = lobby[0xC]
```

#### 实测值

```
lobby       = 0x37c5f068
[lobby+0x0C] = 0x37fa6818   <- 非零，有效对象
[[lobby+0x0C]] = 0xd95558   <- 有 vtable
[lobby+0x1F4] = 1
[lobby+0x1F0] = 0x36c9ec60
```

**`lobby[0xC]` 是一个活的接口对象**（带虚表），所以 `0xBBAD54` 那处
`je` 不会触发，`0xBBAD40` 不会在这里失败。

#### 失败点因此唯一确定

排除了「参数为 0」之后，失败只剩一个出口：`0xBBA8A0` → `0xBBA760(key=0, 0x508)`
在空容器里查不到。

而 `0xBBA810` 已确认只做初始化、不预填，所以容器每轮都是空的。

#### 一个尚未消解的矛盾

`0xBBAD40` 会把 `&local` 的 136 字节复制进 `[容器+4]`（`0xBBAD6B rep movsd`），
而紧接着 `0xBBA8A0` 又要从 key=0 读 1288 字节**到** `[容器+4]`。前者写、后者读
同一块区域，语义上像是「先暂存、再校验是否与容器里的记录一致」——如果暂存内容
与容器记录不符就失败。

若这个解读正确，那么容器**本来就应该有内容**，而它为空说明**更早的某个填充步骤
没有发生**。那个步骤最可能依赖一次网络交互。

#### 结论与收束

第 10-17 轮共八轮围绕 `[lobby+0x1F4]` 追踪，得到的确定事实是：

- pump 每帧执行、每帧写 1（失败标记）；
- 失败原因是容器里没有 key=0 的 1288 字节记录；
- 容器每轮新建且为空；
- 登记参数（`lobby[0xC]`）是活的接口对象，不是空指针；
- 填充容器的那一步在游戏逻辑层，客户端尚未到达。

**这条线不再深入**。它需要的信息只能从「让客户端进入游戏逻辑层」获得，
而那又依赖「取代号」提交成功——闭环没有外部切入点。

#### 下一轮方向（明确）

转向可以**独立推进**的 M4 子目标，不再依赖 FE 闭环：

1. **`rankIconTable.csv` 与武器/配件表提取**——属于 M4.2 的资源最小集，
   完全独立，且已有 `tools/ifs_entries.py` 可用；
2. **`svc21/task5` 房间列表帧的结构验证**——在离线单测里构造并自校验，
   为将来客户端真的请求时做好准备；
3. **重新评估 M4.1 的判据**——若「代号流程」是客户端固有一环，
   考虑把 M4.1 重新定义为「档案持久化 + 每次启动可自动完成代号」，
   并用真实键盘事件（而非合成输入）验证自动化可行性。

第 1 条最稳，先做。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.33"),
                         ("HANDOFF-CURRENT.md", "### 15.21")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.33", "### 15.21")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
