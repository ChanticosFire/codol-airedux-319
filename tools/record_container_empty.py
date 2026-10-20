"""Record the container-ctor finding and close out the pump line."""
from pathlib import Path

TEXT = """
### 12.32 容器确认为空；pump 线到此收束（2026-10-23 02:2x）

#### `0xBBA810` 只做初始化，不预填

```asm
0xBBA810  push ebp; mov ebp,esp; ... 建立 SEH 帧
0xBBA835  mov esi, ecx
0xBBA83A  lea ecx, [esi + 4]
0xBBA83D  call 0xB753A0              ; 子容器 1
0xBBA844  lea ecx, [esi + 0x8c]
0xBBA84D  call 0xB753A0              ; 子容器 2
0xBBA852  lea ecx, [esi + 0x114]
0xBBA85C  call 0xB753A0              ; 子容器 3
0xBBA861  lea ecx, [esi + 0x1a8]
0xBBA86B  call 0xB753A0              ; 子容器 4
0xBBA86B  mov dword ptr [esi + 0x19c], 0
0xBBA871  mov dword ptr [esi + 0x1a0], 0   ; "未处理"标记
0xBBA877  mov byte ptr [esi + 0x1a4], 0
```

**四个子容器全部初始化为空，没有任何预填数据。**

这排除了「容器本来有内容、只是 key 查错」的可能：**容器确实是空的**，
所以 `0xBBA760(key=0, 0x508)` 必然查不到。

#### 查找实现的调用链

```asm
0xBC1C20  ...
0xBC1C36  push eax                   ; 期望长度
0xBC1C3E  mov cl, byte ptr [edi]     ; key 首字节
0xBC1C42  mov byte ptr [ebp + 0x17], cl
0xBC1C45  call 0xB783E0              ; 核心查找
0xBC1C4D  test al, al
0xBC1C4F  je 0xBC1C9D                ; 未命中
```

核心在 `0xB783E0`，但在容器为空的前提下这条路径不可能命中，
继续深挖它的收益很低。

#### pump 线的最终结论

经过第 10-16 共七轮的追踪，`[lobby+0x1F4]` 的机制已经完全清楚：

1. **`0xBAD800`（pump）每帧执行**，前置条件 `byte[lobby+8]!=0` 且
   `[lobby+0x1F4]==1` 实测都满足；
2. 每轮先销毁旧容器再新建一个 440 字节的空容器存于 `lobby+0x1FC`；
3. 然后调 `0xBBAD40` → `0xBBA8A0` → `0xBBA760(key=0, 0x508 字节)`；
4. 空容器查不到，返回 0；
5. pump 于是写 `[lobby+0x1F4] = 1`（失败标记）；
6. FE 主循环读到 1，不到 2，`FE_state` 停在 5，`0x730C50` 报告未加载，
   `onboarded` 不设置，FE 梯不前移。

而真正会填入那份数据的代码在游戏逻辑层——`0x7F58A0`（等待 `[lobby+0x1F4]`
变成非 1 的阻塞循环）的 7 个调用点全在那一层，客户端尚未到达。

**这是一个闭环，断点在「取代号」提交。**

#### 判断：这条线不再深入

按「同一阻断连续 3 轮无进展则换方向」，`[lobby+0x1F4]` 相关追踪已投入
第 10-16 共七轮。虽然每一轮都获得了新的代码级事实（这本身有价值），
但对 M4 验收判据没有产生可观测的推进。

因此**收束这条线**，把结论固化在文档里，后续只在出现新证据时回看。

#### 下一轮方向

回到「取代号」本身，但换一种探测方式：既然它不产生网络请求，且 UI 是
Scaleform，那么提交动作很可能写入了某个客户端全局或本地文件。可行的低成本
探测：

1. 在客户端运行、停在「取代号」界面时，对 `0x82xxxx`/`0x83xxxx` 数据区做
   **全量快照对比**——先截一次，人工或脚本输入代号后触发「继续」，再截一次，
   差异即为提交写入的落点；
2. 对 `players\\config_mp.cfg` 与 `settings_*.zip.iw4` 做哈希对比；
3. 若差异落在某个全局上，用 `find_stores.py` 反查该全局的写者，即可定位
   提交处理函数。

第 1 条不依赖人工输入也能做：用 `tools/type_text.py` 的 WM_CHAR 方式写入
输入框（之前失败可能只是坐标不对），再点「继续」。

#### 关于之前输入失败的解释

`type_text.py` 用了 SendInput 与 WM_CHAR 两种方式都未让文字进入输入框，
当时的判断是「Scaleform 不接受合成输入」。但采样表明客户端此时**处于
pump 每帧失败的循环中**，UI 线程可能根本没在处理输入消息。这也解释了
为什么用户手动输入能进（真实键盘事件优先级更高）。

若要自动化，需要在正确的时机（UI 完成一次完整帧）投递，而不是在启动后
固定等待 N 秒。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.32"),
                         ("HANDOFF-CURRENT.md", "### 15.20")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.32", "### 15.20")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
