"""Record the container lookup details from 0xBBA760 and the argument chain."""
from pathlib import Path

TEXT = """
### 12.30 失败点定位：容器里缺少 key=0 的 1288 字节数据（2026-10-23 02:1x）

#### `0xBBA760` 是一个「按 key 读取定长数据」的函数

```asm
0xBBA760  push ebp; mov ebp,esp; sub esp,0x518
0xBBA773  mov eax, [ebp + 8]        ; 参数1 = key（调用方传 0）
0xBBA779  mov edi, [ebp + 0xc]      ; 参数2 = 输出缓冲
0xBBA77C  mov esi, ecx              ; this
0xBBA77F  lea ecx, [ebp - 0x518]
0xBBA787  call 0xBC1C00             ; 用 key 构造查询条件
0xBBA795  push 0x508                ; ★ 期望长度 0x508 = 1288 字节
0xBBA7A1  call 0xBC1C20             ; ★ 在容器里查找
0xBBA7B6  cmp al, 1
0xBBA7B8  jne 0xBBA7F3              ; 找不到 -> 返回 0
0xBBA7BA  mov edx, [ebp - 0x510]    ; 实际长度
0xBBA7C2  mov eax, [ecx]
0xBBA7C4  mov eax, [eax + 0x18]     ; 虚表第 6 项
0xBBA7D0  call eax                   ; 读取
0xBBA7D2  test eax, eax
0xBBA7D4  jle 0xBBA7F3               ; 读 0 或负 -> 返回 0
0xBBA7D6  cmp eax, [ebp - 0x510]
0xBBA7DC  jne 0xBBA7F3               ; 长度不符 -> 返回 0
```

所以 `0xBBA8A0`（进而 `0xBBAD40`、进而 pump 的写 1）失败的原因只有可能是：
**容器里没有 key=0 对应的、长度为 0x508 的那份数据**。

#### 容器对象从哪来

`0xBAE6C2` 起的流程：

```asm
0xBAE6C2  mov esi, [ebx + 0x1fc]     ; 旧容器
0xBAE6C8  cmp esi, edi
0xBAE6CA  je 0xBAE6DC
0xBAE6CC  mov ecx, esi
0xBAE6CE  call 0xBBA670              ; 销毁旧容器
0xBAE6D3  push esi
0xBAE6D4  call 0xB742E0              ; 释放
0xBAE6DC  mov [ebx + 0x1fc], edi     ; 清空
0xBAE6E2  push 0x1b8                 ; ★ 440 字节
0xBAE6E7  call 0xB742C0              ; 分配
0xBAE6FF  call 0xBBA810              ; 构造容器
0xBAE712  mov [ebx + 0x1fc], eax     ; 保存到 lobby+0x1FC
0xBAE718  call 0xBBAEE0              ; 取两个 dword 作为参数
0xBAE71D  mov ecx, [eax + 4]
0xBAE720  mov edx, [eax]
0xBAE72F  mov ecx, [ebx + 0x1fc]     ; this = 新容器
0xBAE735  call 0xBBAD40              ; 登记数据
```

即 pump **每次都新建**一个 440 字节的容器，然后试图往里面登记，登记失败就写
`[lobby+0x1F4] = 1`。

#### 目前的完整因果链

```
pump 0xBAD800
  -> 新建容器（440 字节）存于 lobby+0x1FC
  -> 0xBBAD40(this=容器, addr, buf, len)
       -> 0xBBAD6B rep movsd 34     复制 136 字节
       -> 0xBBA8A0
            -> 0xBBA760(容器, key=0, out)   期望 0x508 字节
                 -> 0xBC1C20 查找失败
       -> 返回 0
  -> 写 [lobby+0x1F4] = 1           失败标志
  -> [lobby+0x1F4] != 2，于是 0x6217A2 的比较不过，FE_state 停在 5
```

#### 结论

一个**刚新建的空容器**里当然没有 key=0 的数据。这说明 `0xBBAD40` 的语义
不是「查询」，而更可能是「**注册/插入**」——`0xBBA760` 在插入失败后返回 0
是正常的首轮行为，真正的判断在别处。

也就是说：`0xBAE74E` 写 1 的那两个分支，可能对应的是「这次还没准备好」，
而不是「永远失败」。若如此，pump 后续应该还有把 1 推进到 2 的路径——
而 `0xBAE1AC`/`0xBAE587` 两处无条件写 2 正是它。

#### 下一步

1. 反汇编 `0xBBA810`（容器构造）与 `0xBBAEE0`（参数来源），确认容器类型；
2. 反汇编 `0xBBAD40` 尾部的失败分支 `0xBBADCD`，看它在什么情况下不走
   `[ebx+0x1A0]=1` 的成功路径；
3. 关键验证：在运行期**连续采样** `[lobby+0x1F4]` 与 `lobby+0x1FC`，
   确认 pump 是否周期性重建容器、值是否在 1 与其它值之间跳动。若只在 1
   上不动，说明这个阶段确实进不去；若跳动，则说明只是采样时机问题。

第 3 条成本最低，优先做。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.30"),
                         ("HANDOFF-CURRENT.md", "### 15.18")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.30", "### 15.18")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
