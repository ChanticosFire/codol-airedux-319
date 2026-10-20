"""Write a standalone technical brief on the lobby pump state machine.

PROJECT_STATUS carries the findings as a chronological log across §12.19-§12.58,
which is hard for anyone else to reuse. This consolidates the mechanism into one
document with the evidence for each claim.
"""
from __future__ import annotations

from pathlib import Path

DOC = """# CODOL 1604220 大厅 pump 状态机技术说明

面向后续研究者。本文只写**有实证支撑**的结论，每条都标注证据来源（反汇编地址 /
运行时读数 / 日志）。未证实的一律标注为"未证实"。

适用 Build：**1604220**（产品标签 3.19.26.17，社区称 3.19.26.13）
EXE SHA-256：`3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f`
EXE 大小：7,842,456 字节

---

## 1. 结论摘要

客户端登录完成（`dw=5`）后，大厅前端能否显示取决于一条链：

```
FE 主循环 0x621750
  → 读 [lobby+0x1F4]，若 == 1 则调 pump 0xBAD800
  → pump 走"登记服务器条目"分支 0xBBAD40
       成功 → [容器+0x1A0] = 1，之后到 4
       失败 → [容器+0x1A0] = 5
  → pump 检查 [容器+0x1A0] == 4
       不等于 4 → 遍历数组 → 0xBAE781 → 写 [lobby+0x1F4] = 1
       等于 4   → 0xBAE182 → 0xBAE1AC → 写 [lobby+0x1F4] = 2
  → [lobby+0x1F4] == 2 才让 FE_state 5 → 6（0x6217BF）
  → FE_state ∈ {4,6} 才让 0x730C50 报告 FE 已加载
  → 0x730C50 为真才让 0x6BBF60 设置 onboard_character_selected 并推动 FE 梯
```

**离线环境下这条链断在第一步**：`0xBBAD40` 的登记永远失败，
`[容器+0x1A0]` 恒为 5，`[lobby+0x1F4]` 恒为 1。

---

## 2. 关键地址表

| 地址 | 作用 | 证据 |
|---|---|---|
| `0xBAD800` | lobby pump 主函数（约 4 KB） | 反汇编 |
| `0xBAD83D` / `0xBAD846` | pump 入口两道门：`byte[lobby+8]!=0` 且 `[lobby+0x1F4]==1` | 反汇编 + 实测两者均满足 |
| `0xBAE1AC` | 写 `[lobby+0x1F4] = 2`（成功） | 反汇编；**无任何跳转指向它**，只能顺序落到 |
| `0xBAE781` / `0xBAE7AA` | 失败尾部，写 `[lobby+0x1F4] = 1` | 反汇编；`0xBAE7AA` 仅由 `0xBAE786 jbe` 进入 |
| `0xBAE5DB` | 遍历服务器数组的循环头 | 反汇编；入口为 `0xBAE312`/`0xBAE326` 两个 `jne` |
| `0xBBAD40` | 服务器条目"登记"例程 | 反汇编 |
| `0xBBADCD` | `0xBBAD40` 的失败分支，写 `[容器+0x1A0] = 5` | 反汇编 + 模式扫描命中 |
| `0xBBA8A0` | 登记结果的验证包装 | 反汇编 |
| `0xBBA760` | 按 key 读取定长记录的实现 | 反汇编 |
| `0xBC1C00` | 构造查询对象 {类型 0x14, 子类型 2, key} | 反汇编 |
| `0xBC1C20` | 执行查找（转 `0xB783E0`） | 反汇编 |
| `0xBBA810` | 440 字节容器构造，四个子容器全空 | 反汇编 + 实测 |
| `0x730C50` | FE-loaded 判定 | 反汇编 |
| `0x6BBF30` | firstlogin 判定 | 反汇编 |
| `0x6BBF60` | 设置 onboard_character_selected | 反汇编 |
| `0x621750` | FE 主循环 | 反汇编 |
| `0x6217BF` / `0x6217D0` | `FE_state: 5→6` / `3→4` | 反汇编 |

### 2.1 关键数据地址

| 地址 | 含义 | 实测值 |
|---|---|---|
| `0x84ABA40` | `dw`（登录进度） | 5 = 登录完成 |
| `0x84ABA50` | `ui_state` | 9 = 训练官/取代号页面 |
| `0xE59D20` | `FE_state` | 5（见 §4） |
| `0xE85C68` | lobby 单例指针（`0x643280` 懒创建） | 运行时非零 |
| `0x3306D60` | 指向 `0x80FA044`，后者是**全局字符串表**，不是账号对象 | `[D+0x00]` → `cod4master.activision.com` 等 |
| `[lobby+0x1F0]` | 大厅连接对象 | 非空，有 vtable |
| `[lobby+0x1F4]` | pump 状态：1=失败/未完成，2=成功 | 恒为 1 |
| `[lobby+0x1F8]` | 对象 1（`+0x120` 是它的状态） | `+0x120` = 3（目标 2） |
| `[lobby+0x1FC]` | 对象 2：440 字节容器（`+0x1A0` 是状态） | `+0x1A0` = 5（目标 4） |
| `[lobby+0x4D60]` | 服务器数组基址 | 非空 |
| `[lobby+0x4D68]` | 数组容量 | 1 |
| `[lobby+0x4D6C]` | 数组当前索引 | 0 |
| `[lobby+0x8A8]` | 22011 字节缓冲，开头是 `192.168.1.3` | 内容为历史残留 |

---

## 3. 容器的状态机（`[lobby+0x1FC] + 0x1A0`）

全部写入点已定位：

| 值 | 地址 | 语义 |
|---|---|---|
| 0 | `0xBBA871` | 构造时初始 |
| 1 | `0xBBAD95` | `0xBBAD40` 登记成功 |
| 4 | `0xBBAD10`、`0xBBA951`、`0xBBA97D`、`0xBBA9F5` | **完成**（pump 要求的终态） |
| **5** | `0xBBAAAC`、`0xBBADB0`、**`0xBBADCD`**、`0xBBAC3E`、`0xBBACF4` | **失败** |

`0xBBADCD` 是 `0xBBAD40` 自己的失败分支：

```asm
0xBBAD86  call 0xBBA8A0
0xBBAD8B  cmp al, 1
0xBBAD8D  jne 0xBBADCD          ; 失败
0xBBAD95  mov [ebx+0x1a0], 1    ; 成功
0xBBADCD  mov [ebx+0x1a0], 5    ; 失败
```

**实测 `+0x1A0` = 5，所以登记是失败的，不是"进行中"。**

---

## 4. FE_state 与 FE 梯

`[0xE59D20]` 是一台状态机，写入点共 6 处：

| 地址 | 写入 | 条件 |
|---|---|---|
| `0x6216B9` | **3 或 5** | `lea edx,[edx+edx+3]`，由某布尔参数决定 |
| `0x6216E9` | 0 | 重置 |
| `0x62171C` | 1 | 启动 |
| `0x6217BF` | 6 | 原值 5 且 `[lobby+0x1F4]==2` |
| `0x6217D0` | 4 | 原值 3 且 `[lobby+0x1F4]==2` |
| `0x621A00` | 视 `edi` | — |

`0x730C50`（FE-loaded）的完整条件：

```asm
0x730C57  cmp [0xE59D20], 4      ; 必须 4 或 6
0x730C67  call 0x803700          ; 对象非空
0x730C79  cmp eax, 2             ; 0xB7A680 返回 2
0x730C90  cmp [0x84ABABC], 1     ; script_state
0x730CBE  cmp byte [0x82C4A86], 0; fe_final
```

**第一个条件不满足时，后两个写不写都无所谓**——这解释了为什么
`fix_fe_loaded`（改 `script_state`/`fe_final`）完全无效。

---

## 5. 容器查找的精确契约

`0xBBA760(this, key, out)` 期望的是一条定长记录：

```asm
0xBBA773  mov eax, [ebp + 8]        ; key
0xBBA787  call 0xBC1C00             ; 构造查询对象
0xBBA795  push 0x508                ; 期望长度 1288
0xBBA7A1  call 0xBC1C20             ; 查找
0xBBA7B8  jne fail                  ; 未命中
0xBBA7D6  cmp eax, [ebp - 0x510]
0xBBA7DC  jne fail                  ; ★ 长度严格相等，不是 <=
```

查询对象由 `0xBC1C00` 构造：

```asm
0xBC1C0D  mov byte ptr [eax], 0x14    ; 类型 0x14
0xBC1C10  mov word ptr [eax + 2], 2   ; 子类型 2
0xBC1C14  mov dword ptr [eax + 4], edx; key
```

**即需要 {类型 0x14, 子类型 2, key 0, 长度 1288} 的记录。**

而 `0xBBAD40` 只做：

```asm
0xBBAD58  mov [ebx], eax              ; 存 arg1
0xBBAD6B  mov ecx, 0x22               ; 34 dwords
0xBBAD70  rep movsd                   ; ★ 只复制 136 字节到 [ebx+4]
0xBBAD7D  call 0xBBAF00               ; 只做范围检查与浮点比较，不写容器
0xBBAD86  call 0xBBA8A0               ; 查 key=0 的 1288 字节 -> 必然失败
```

**复制 136 字节、却要求 1288 字节** —— 这是整条链的矛盾点，也是当前调查的
终止位置。（136 = 数组条目大小 `0x88`，1288 = 容器记录大小 `0x508`，两者
不是整数倍关系。）

---

## 6. 已排除的假设（含证据）

| 假设 | 结论 | 证据 |
|---|---|---|
| 136 字节是加密密钥 | 否 | 它是数组记录，`0xBAE5FF imul eax,eax,0x88` |
| 136 字节是服务器地址块 | 否 | 同上 |
| `svc71/task4` 应答形状不对 | 否 | 数组已存入 `127.0.0.1` 条目，容量 1 |
| `0xBAF040` 失败导致写 1 | **否** | 成败两条路都到 `0xBAE182`（§3.2） |
| 强写 `[lobby+0x1F4]=2` 能推进 | **否** | 它是崩溃源，10 秒内进程退出 |
| firstlogin 修复有害 | **否** | 写 `[D+0xC]=1` 让 FE 梯 `G1: 0→1`，是有效的 |
| 打桩 `0x6BBF30` 等价于写字段 | **否** | 打桩会跳过 `0x6BBF60` 等副作用，24 秒崩溃 |
| 9 处 pump 补丁可能有害 | **否** | 只用 M3 的 6 个补丁会崩溃 |
| `task3`/`task7` 是房间协议 | **否** | 解密后是 `ClientOffline`/`ClientException` 日志上报 |
| `rankIconTable.csv` 可从 `.ifs` 提取 | **否** | 987 个包深度扫描 0 命中，在加密 fastfile 内 |
| `[lobby+0x1F4]` 每帧被写 | **未证实** | 采样工具两次出错，结论作废 |

---

## 7. 可复用的工具

| 工具 | 用途 |
|---|---|
| `tools/patch_runtime.py` | 15 处运行期补丁，参数格式 `RVA:NEW:EXPECTED` |
| `tools/auto_lobby.py` | 等待 `dw=5` 并写状态位 |
| `tools/peek.py` | 任意地址读内存，支持指针跟随 |
| `tools/jump_map.py` | 在 `0xBAD800` 内枚举跳转来源 |
| `tools/find_stores.py` | 16 种编码的写入点扫描 |
| `tools/decrypt_frames.py` | 用 sidecar 密钥解密 `client_frame.body_hex` |
| `tools/parse_task_tlv.py` | 解析 `47 03 <task>` 的 TLV 字段 |
| `tools/show_lsg.py` / `show_patches.py` | 精简日志视图 |
| `tools/test_frames.py` / `test_contracts.py` | 40 项离线契约测试 |

---

## 8. 给后续研究者的建议

1. **先人工完成一次代号流程**。本文所有分析都停在"客户端无法离开代号页"这一步；
   一旦进过大厅，`config_mp.cfg` 就有了有效存档，后续可复用。
2. **不要强写内存状态**。`[lobby+0x1F4]`、`FE_state`、打桩 `0x6BBF30` 都会崩，
   各有记录。
3. **136 vs 1288 是唯一未解的矛盾**。若有人能读到一个**成功登记后**的容器内容，
   就能知道那 1288 字节该是什么。
4. **采样工具先自检**。两次"0 命中"都是工具 bug（204 字节 CONTEXT、
   64 位读 32 位），不是行为观测。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    path = root / "PUMP-STATE-MACHINE.md"
    path.write_text(DOC, encoding="utf-8")
    print(f"wrote {path.name}: {len(DOC)} chars, {len(DOC.splitlines())} lines")


if __name__ == "__main__":
    main()
