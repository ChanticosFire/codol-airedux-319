"""Record round 180: the ws2_32 IAT layout, and the odd fact that the sendto slot did not resolve."""
from pathlib import Path

TEXT = """
### 12.195 `ws2_32` 导入槽布局；`sendto` 槽（`0xCA8518`）未能解析出模块归属（2026-10-26 16:5x）

#### 实测

```
ws2_32 module: WS2_32.dll  base=0x76BC0000  size=0x6A000

slot 0xCA8534 -> 0x76BD3890  WS2_32.dll+0x13890
slot 0xCA8538 -> 0x76BF34A0  WS2_32.dll+0x334A0
slot 0xCA853C -> 0x76BD9EF0  WS2_32.dll+0x19EF0   ← WSAGetLastError（§12.62 已确认）
slot 0xCA8540 -> 0x76BD9B00  WS2_32.dll+0x19B00
slot 0xCA8544 -> 0x76BD0170  WS2_32.dll+0x10170
slot 0xCA8548 -> 0x76BCFBE0  WS2_32.dll+0xFBE0
slot 0xCA854C -> 0x76BDA470  WS2_32.dll+0x1A470
slot 0xCA8550 -> 0x76BD9C20  WS2_32.dll+0x19C20
slot 0xCA8554 -> 0x76BCEE50  WS2_32.dll+0xEE50
slot 0xCA855C -> 0x76BF3340  WS2_32.dll+0x33340
slot 0xCA8564.. -> 0x654Axxxx  bink2w32.dll+…（另一组导入，与网络无关）
```

#### 一个反直觉的观察

**`0xBB1492` 处确实有 `call dword ptr [0xCA8518]`，但 `0xCA8518` 这个槽位
在本轮解析中没有任何模块归属。**

**可能的原因（都需要后续确认）：**

1. **IAT 被延迟绑定**（lazy binding），读取时该槽仍指向桩代码或为 0；
2. **`0xCA8518` 不在 IAT 段**，而是某个二级指针（例如函数指针变量）；
3. **读取时机太早**，解析尚未完成。

**这不影响 §12.194 的结论（`sendto` 确实经由该槽调用），但说明"靠槽位找 socket"
这条路需要先解决解析问题。**

#### 更稳的替代路线

**不必依赖 IAT。直接用 `WS2_32.dll` 的导出表反查：**

1. 读出 `WS2_32.dll` 的导出地址表（EAT），得到 `socket`、`WSASocketA`、
   `WSASocketW`、`connect`、`bind`、`sendto`、`recvfrom` 各自的 RVA；
2. 加上基址 `0x76BC0000` 得到绝对地址；
3. **在 `0xCA84xx`–`0xCA85xx` 区域内找值等于这些地址的槽位**——
   那样就不依赖"槽位解析"，而是直接按目标地址匹配。

**这比从槽位反推更可靠，因为 EAT 是静态的、不受延迟绑定影响。**

#### 下一步

**先 dump `WS2_32.dll` 的导出表**，取得 `socket` 的绝对地址。
**然后在 `0xCA8000`–`0xCA8600` 内搜索该地址**，找到 `socket` 的槽位。

**拿到槽位后，全镜像搜 `call dword ptr [槽位]` 的引用，
就能定位"创建 socket"的代码——也就是 `lobby+4` 应当被写入的地方。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.195"),
                         ("HANDOFF-CURRENT.md", "### 16.83")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.195", "### 16.83")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
