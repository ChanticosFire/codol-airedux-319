"""Record that 0xBAF040 on 1604220 is the same routine as 0xBA3010 on 1649370."""
from pathlib import Path

TEXT = """
### 12.24 ★★ 写 2 的依赖回到了加密通道初始化（2026-10-23 01:3x）

#### `0xBAD800` 通往写 2 的路径

解码 `0xBAE0C0` 起的过程后，到 `0xBAE1AC`（写 2）之前的关键调用链是：

```asm
0xBAE0ED  call 0xBAF040          ; ★ 关键判定
0xBAE0F2  test al, al
0xBAE0F4  je 0xBAE10D            ; 失败 -> 走别的分支
...
0xBAE182  mov ecx, [ebx+0x1F0]   ; 大厅连接对象（实测非空）
0xBAE188  mov edx, [ecx]         ; vtable
0xBAE191  call edx               ; 虚调用
0xBAE1A7  call 0xC699B0          ; 设置服务器地址
0xBAE1AC  mov dword [ebx+0x1F4], 2
```

#### `0xBAF040` 与 1649370 的 `0xBA3010` 是同一套

```asm
0xBAF040  push ebp; mov ebp,esp; sub esp,0x8C
0xBAF059  lea eax, [ebp-0x8C]
0xBAF060  add ecx, 0x4C8         ; 子对象
0xBAF066  call 0xBAFDA0          ; 取数据源
0xBAF06D  mov ecx, 0x22          ; 34 dwords = 136 bytes
0xBAF072  mov edi, ebx
0xBAF074  rep movsd              ; ★ 复制 136 字节
0xBAF07C  call 0xB76EE0
0xBAF083  call 0x853A10
0xBAF08A  call 0xB77020          ; 判定
0xBAF092  test al, al
0xBAF094  je 0xBAF0A8            ; 失败
0xBAF096  mov al, 1
```

**136 字节**这个长度是决定性线索——1649370 上我们花了很长时间确认 `0xBA3010`
会读取 tag 1 的 **136 字节**（`0xB75DE0(obj, 1, 0x88)`），并因此判断需要构造
能让客户端自己建立加密通道的 `0x87` 帧。

1604220 的 `0xBAF040` 是同一个函数（偏移从 `0xBA3010` 变为 `0xBAF040`），
结构、136 字节复制、末尾判定顺序全部一致。**两个版本的加密通道初始化是同一套代码。**

#### 这意味着什么

`[lobby+0x1F4]` 停在 1 的根本原因，与 1649370 上「`crypt` 恒为 0」是**同一个问题**：
客户端需要完成一次加密通道初始化（`0x87` 帧 → `0xBAF040` → 136 字节数据 → 判定成功），
之后 pump 才会把状态推进到 2，进而让 `FE_state` 变 6、`onboarded` 被设置、FE 梯前移。

我们之前在 1649370 上的三条结论，对 1604220 同样适用：

1. **`crypt` 由 `0x87` 帧建立**（1649370 是 `0xBA3AE0` → `0xBA3590` → `0xBA3010`）；
2. **强写 `crypt`/`ready` 会被立刻回滚**（`0xBA3420` 会同时写 `cstate=4` 和 `crypt=0`）；
3. **伪造 `0x87` 帧的前提是知道 S2C 加密密钥**，而这需要 `packet_buffer` 派生。

#### 当前判断

M4.1 的真正阻断点不是「档案」也不是「FE 阶段机」，而是**加密通道从未建立**。
它与 M3 后期我们一直在攻的 `0x87` 帧问题是同一个问题，只是现在从 1604220 的
另一个入口（pump → FE_state → onboarded）再次遇到。

#### 下一步

两条并行路线：

1. **验证 crypt 状态**：在 1604220 上找 `crypt` 对应的字段（1649370 是 `conn+0x644`），
   确认它是否同样恒为 0；
2. **找 `0x87` 帧的正确构造**：既然两个版本同源，1649370 上积累的
   `AB 85` 帧格式、真 HMAC 尾、`bdproto319` 的密钥派生规则都可能直接适用。

建议优先做 2——它是唯一能让 `0xBAF040` 真正返回成功、进而让 `[lobby+0x1F4]`
自然走到 2 的途径。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.24"),
                         ("HANDOFF-CURRENT.md", "### 15.12")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.24", "### 15.12")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
