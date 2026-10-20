"""Append the FE-ladder findings to the two project documents."""
from pathlib import Path

TEXT = """
### 12.12 FE 梯（前端状态机）的卡点（2026-10-22 23:1x）

`他人文件参考/零补丁还债台账.md` 给出了 FE 梯 `0x5EBFD0` 的完整解码：

```
入口: call 0x5EE7C0(登录态查询)          ; eax!=1 -> 整梯 return
       G1=[0x82E1340], CS=[0x84ABA50]
 G1==0: call 0x6BBF30(firstlogin)         ; al==0 -> 留 0
            al==1 -> 推 cppFirstLogin 建 UI -> G1=1
 G1==1: cmp CS,9 ; !=9 -> 留 1
            call 0x730C50(FE-loaded) ; al==0 -> 留 1        ← 当前卡这里
            cmp [[0x3306D60]]+0xC,0 ; !=0 -> 跳过
            cmp byte [0x82E1346],0 ; !=0 -> 排队
            cmp [0x84ABAFC],0 ; ==0 -> 等待 ; 会话 ready 调用==1
            推 cppInLoginQueue 建 UI -> G1=2
 G1==2: call 0x5EBE10(cppActivate) -> gate=1 ; [G1]=3
```

新增 `tools/probe_fe_ladder.py` 采样全部门控量，实测稳定值：

```
G1=0  gate=0  queue=0  CS=9  dw=5  session_ready=0  D+0xC=0
FE_obj 由 0xFFFFFFFF 变为 695689256（0x2976E028）后稳定
```

**关键发现：`G1` 一直是 0。** 即 `0x6BBF30`（firstlogin）在离线会话里从不返回 1，
梯子第一步就停住，后面的 `cppActivate` 自然永远不会被它自己调用。

新增 `tools/force_fe_ladder.py` 把 `G1` 写成 1（仅进程内存）。实测：

```
before  G1=0 gate=0 session_ready=0 CS=9
now     G1=1 gate=0 session_ready=1 CS=9
after   G1=1 gate=0 session_ready=1 CS=9
```

**`G1` 停在 1，`gate` 仍为 0** —— 说明 `G1==1` 分支里 `0x730C50`（FE-loaded）
返回 0，梯子继续等待前端资源加载完成。

### 12.13 下一步

1. 反查 `0x730C50`（FE-loaded）的判定条件——它很可能检查某个 Scaleform 影片/资源
   是否就绪，若依赖客户端资源文件则需要让它以为已加载。
2. 或直接把 `G1` 写成 2（跳过 FE-loaded），观察 `cppActivate` 是否被执行、gate 是否置 1。
3. 注意 `tools/ui_activate.py` 的跳板是「绕过梯子直接调 cppActivate」，与此处的
   「让梯子自己走完」是两条不同路径，可分别验证。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name in ("PROJECT_STATUS.md", "HANDOFF-CURRENT.md"):
        path = root / name
        with path.open("a", encoding="utf-8") as stream:
            stream.write(TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.1", "### 15.1"))
        print(f"appended {len(TEXT)} chars to {name}")


if __name__ == "__main__":
    main()
