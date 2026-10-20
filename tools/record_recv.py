"""Record round 188: the pump calls the recv slot each frame and passes the byte count on."""
from pathlib import Path

TEXT = """
### 12.203 ★★★★ 找到了收包调用：`0xBAE242` 调 `vt+0x1C`，返回值即字节数（2026-10-26 20:5x）

#### 完整序列

```asm
0xBAE215  8D 8D 98 F8 FF FF     lea ecx, [ebp-0x768]     ; ★ 目标缓冲
0xBAE21B  E8 80 71 FC FF        call 0xB753A0             ; 初始化
0xBAE220  8B 4B 0C              mov ecx, dword [ebx+0xC]  ; ★ lobby+0xC 对象
0xBAE223  8B 01                 mov eax, dword [ecx]      ; vtable
0xBAE225  8B 40 1C              mov eax, dword [eax+0x1C] ; ★ vt+0x1C = 收包
0xBAE228  68 08 05 00 00        push 0x508                ; 1288 字节
0xBAE22D  8D 95 B8 FA FF FF     lea edx, [ebp-0x548]
0xBAE233  52                    push edx                   ; 输出缓冲
0xBAE234  8D 95 98 F8 FF FF     lea edx, [ebp-0x768]
0xBAE23A  52                    push edx                   ; 上下文
0xBAE23B  C7 45 FC 17 00 00 00  mov dword [ebp-4], 0x17
0xBAE242  FF D0                 call eax                   ; ★ 收包
0xBAE244  8B F0                 mov esi, eax                ; ★ esi = 收到的字节数
0xBAE246  39 BB F8 01 00 00     cmp dword [ebx+0x1F8], edi
0xBAE24C  74 44                 je 0xBAE292
0xBAE24E  56                    push esi                    ; ★ 字节数
0xBAE24F  8D 8D B8 FA FF FF     lea ecx, [ebp-0x548]
0xBAE255  51                    push ecx                    ; 数据
0xBAE256  81 EC 88 00 00 00     sub esp, 0x88
0xBAE25C  8D 95 98 F8 FF FF     lea edx, [ebp-0x768]
0xBAE262  8B CC                 mov ecx, esp
0xBAE26B  E8 50 71 FC FF        call 0xB753C0              ; 复制 136 字节
0xBAE270  8B 8B F8 01 00 00     mov ecx, [ebx+0x1F8]        ; obj1
0xBAE276  E8 75 C1 00 00        call 0xBBA3F0               ; ★ Add
0xBAE27B  8B 8B F8 01 00 00     mov ecx, [ebx+0x1F8]
0xBAE281  E8 5A BF 00 00        call 0xBBA1E0               ; 读状态
0xBAE286  83 F8 01              cmp eax, 1
0xBAE289  74 07                 je 0xBAE292
0xBAE28B  C6 85 77 F6 FF FF 01  mov byte [ebp-0x989], 1
```

#### 三件事一次确认

**1. `vt+0x1C` 就是收包，返回值是字节数**

`[lobby+0xC]` 的 vtable 第 8 槽（`+0x1C`）在 §12.76 已确认是 `0xC73FB0`（收包）。

**`0xBAE242` 调用它，`0xBAE244` 直接把 `eax` 存进 `esi`——
`esi` 在 `0xBAE24E` 作为长度压栈，与"收到多少字节"的语义完全一致。**

**2. `[ebp-0x768]` 的填充者就是这次收包**

§12.187 曾困惑"136 字节的源在哪里"。**现在清楚：它由 `vt+0x1C` 填入
（或由 `0xB753A0` 初始化后再由收包填充），随后被复制给 `Add`。**

**3. 顺序固定为：收包 → Add → 读状态 → 视状态决定是否置标志**

```
0xBAE242  收包          -> esi = 字节数
0xBAE276  Add(obj1)     -> 追加一条记录
0xBAE281  读 obj1 状态   -> eax
0xBAE286  cmp eax,1
0xBAE28B  状态 != 1 时置 [ebp-0x989] = 1
```

**而 `[ebp-0x989]` 是三道守卫里的第二道。**

#### 于是整条链的完整形态

```
pump 每帧：
  ① 收包（vt+0x1C）-> 得到字节数 esi 和 1288 字节缓冲
  ② 把缓冲复制成 136 字节记录，交给 Add(obj1)
  ③ Add 内部：count>0 走成功分支写 2；否则推进索引
  ④ 读 obj1 状态；状态 != 1 则置 [ebp-0x989]
  ⑤ 检查三道守卫标志
  ⑥ 全通过则调 0xBBADE0 -> 0xBBAAF0 -> 若类型 == 0x15 -> 状态 = 4
  ⑦ 状态 == 2 或 4 时，1F4 才会被写成 2
```

**这就是完整的每帧循环。**

#### 为什么现在卡住

**我们的环境里 `0xBAE242` 的收包返回的字节数是 3 或 4（那两个探测包），
不足以构成一条 136 字节的记录；`Add` 因此走 `count <= 0` 分支推进索引，
状态停在 1，第二道守卫标志永远为 0，`1F4` 永远是 1。**

**这与所有观测吻合。**

#### 剩余轮次的收尾

**本轮 188 / 200，剩余 12 轮。** 这条主线已经追到"每一帧如何流转"的完整图景，
**但要在剩余轮次内构造出能让 `Add` 成功、并让类型 0x15 走通的完整数据流并不现实。**

**后续轮次用于：**

1. **把这条完整循环写进 `PUMP-STATE-MACHINE.md`**（已有文件，需大幅更新）；
2. **更新 `MILESTONES.md`**，把 M4 的阻塞点精确定位到"服务端需返回至少 136 字节的记录"；
3. **在 `PROJECT_STATUS.md` 顶部加一份"最新结论索引"**，让接手者不必读 800 行；
4. **最后做一次完整回归**：跑契约测试、确认 git 干净、写交接说明。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.203"),
                         ("HANDOFF-CURRENT.md", "### 16.91")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.203", "### 16.91")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
