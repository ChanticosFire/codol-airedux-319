"""Append the 1604220 breakthrough record to PROJECT_STATUS.md and HANDOFF-CURRENT.md."""
from pathlib import Path

STATUS = """
### 12.11 ★★ 111 消除 + 大厅背景渲染（2026-10-22 22:5x–23:5x）

社区开发者提供的信息是决定性的，分三层，全部验证成立。

#### 第一层：UDP 3074 必须有人应答

握手走 **UDP，不走 TCP**。`0xbb1420` 是 sendto 封装，构造 `"1E" + u16([session+0x12C])`
发到 `127.0.0.1:3074`。我们此前只监听 4174/4175，UDP 3074 上没人应答——这被认为是
`[111]` 反复出现的直接原因之一。

新增 `server319/lobby_udp.py`（TCP+UDP 3074，回环，原样回显）。实测日志：

```
endpoint_up
udp_in 127.0.0.1:22011 len=3  1e0300
udp_echo len=3
udp_in 127.0.0.1:22011 len=4  14020000
udp_echo len=4
```

一轮会话 25 次往返，格式与社区描述完全一致。

#### 第二层：lobby pump 的 9 处补丁

`[lobby+0x1F4]` 这个状态量以前撑不过 47 秒就翻成 -2；根因是 pump 匹配失败后走清理路径
把 1F4 写成 -2，客户端读到 -2 就认定连接已失去。

四类跳转改为 `9090`，五处硬编码「写 -2」的立即数改为 1：

| 地址 (VA) | 原始 | 补丁 | 说明 |
|---|---|---|---|
| `0xBBA295` | `7e1a` | `9090` | 握手失败跳转 |
| `0xBBA29D` | `7512` | `9090` | 同上 |
| `0xBBA276` | `7439` | `9090` | 同上 |
| `0xBBAD4D` | `7572` | `9090` | 同上 |
| `0xBADC27` | `feffffff` | `01000000` | **注意是 +1**：指令为 `be fe ff ff ff`（mov esi,-2），立即数从下一字节开始 |
| `0xBADDDE0` | `feffffff` | `01000000` | 写 1 |
| `0xBAE754` | `feffffff` | `01000000` | 写 1 |
| `0xBAE76C` | `feffffff` | `01000000` | 写 1 |
| `0xBAE7B0` | `feffffff` | `01000000` | 写 1 |

> `0xBADC26` 首次尝试报 `applied=false`，正是因为立即数在 `0xBADC27`，差一个字节。

加上原有 6 处（`0x803699`、`0x803659`、`0x7F2A0A`、`0x7EE9DC`、`0x77C860`、`0x60C649`），
共 **15 处**运行期补丁，全部 `applied=true` / `verified=true`。

状态机随之推进：

```
dw=2 ui=6  DW_DNS_COMPLETE
dw=3 ui=9  lstate=1  DW_ACCOUNT_LOGIN_COMPLETE   ← lstate=1 首次出现
dw=5 ui=9  lstate=2  DWLOGON_REGISTERCODOID_COMPLETE
```

**`[111]` 消失，截图显示大厅背景。**

#### 第三层：强推补丁（cppActivate）

`codol-ember/.../launch319-reference/reference/launch/orch319.py::install_ui_activate`
即社区所说的「强推补丁」：在每帧泵 `0x7F25F0` 入口装一次性跳板，调用 `0x5EBE10`
（cppActivate）激活前端；**dw=5 先调一次，45 秒后再重触发一次**。

已移植为 `tools/ui_activate.py`（`--wait-dw5` / `--reset`）。cave 布局：

```asm
pushf; pushad
cmp  byte [cave+0x800], 0
jne  skip
mov  byte [cave+0x800], 1
call 0x5EBE10
skip:
popad; popf
<原 6 字节>
jmp  0x7F25F6
```

实测 `trampoline installed at 0x59bf0000`，之后截图（`runs/20261022-1604220-activate`、
`runs/20261022-1604220-retrig`）均为大厅背景。

#### 当前唯一缺口：大厅 UI 层

背景与 HUD 几何层渲染正常，但**没有按钮和文字**。`lsg.jsonl` 显示客户端拿到
`svc71/task4` 应答后不再请求任何数据，只有 `idle_control` / `zero_frame` 保活。

下一步需要主动给它 player/lobby 数据（`svc80` playerdata 或未请求的事件帧），
以及 `svc10` 文件清单（若 UI 需要资源）。
"""

HANDOFF = """
---

## 15. Build 1604220：111 已消除，大厅背景已出（2026-10-22 23:5x）

### 15.1 这一步做了什么

`[100]` 与 `[111]` 均已消除，客户端渲染出大厅背景。三层修复缺一不可：

1. **UDP 3074 回显**（`server319/lobby_udp.py`）——握手走 UDP，此前无人应答。
2. **lobby pump 9 处补丁**——绕握手失败跳转 + 把「写 -2」改成写 1，
   注意 `0xBADC27` 而非 `0xBADC26`（`mov esi,-2` 的立即数偏移）。
3. **强推补丁**（`tools/ui_activate.py`）——`0x7F25F0` 跳板调用 `0x5EBE10`（cppActivate），
   dw=5 调一次、45 秒后 `--reset` 重触发。

完整 15 处补丁列表见 `PROJECT_STATUS.md` §12.11。

### 15.2 当前状态

```
dw=5, ui=9, lstate=2, DWLOGON_REGISTERCODOID_COMPLETE
```

截图：大厅背景（蓝雾 + 半透明几何层 + HUD 边框），**无 111 弹窗**。
但**UI 层（按钮/文字）为空**。

### 15.3 缺什么

`lsg.jsonl` 显示：`svc71/task4` → 应答 → 客户端不再请求，只有保活帧。
即前端框架已激活，但没有数据可渲染。

下一步：主动推送 player/lobby 数据（参考 `bdsvc319.py` 的 `svc80` 形状），
必要时补 `svc10` 文件清单。

### 15.4 复验命令

```powershell
cd E:\\GAME\\COD\\codol-airedux\\319

# 1) 起三个本机服务
python -m server319.lobby_udp 3074 200 runs\\X\\lobby_udp.jsonl
python -m server319 --client-dir runtime\\client-1604220 --auth \\
  --cert runs\\20261022-tls-selfsigned\\auth.crt \\
  --key  runs\\20261022-tls-selfsigned\\auth.key \\
  --port 4175 --seconds 195 --evidence runs\\X\\auth.jsonl
python -m server319.lsg --cert runs\\20261022-tls-selfsigned\\auth.crt \\
  --key runs\\20261022-tls-selfsigned\\auth.key \\
  --port 4174 --log runs\\X\\lsg.jsonl --seconds 195

# 2) 打 15 处补丁并启动客户端
python tools\\patch_runtime.py --client-dir runtime\\client-1604220 \\
  --evidence runs\\X\\patch.json --wait 12 --observe 175 \\
  --patch 0x403699:EB1F:741F --patch 0x403659:909090909090:893540BA4A08 \\
  --patch 0x3F2A0A:B8BC0200009090:3DBC0200007407 \\
  --patch 0x3EE9DC:9090909090:E82F2F0100 \\
  --patch 0x37C860:C39090909090:558BEC83E4F8 --patch 0x20C649:B000:B001 \\
  --patch 0x7BA295:9090:7E1A --patch 0x7BA29D:9090:7512 \\
  --patch 0x7BA276:9090:7439 --patch 0x7BAD4D:9090:7572 \\
  --patch 0x7ADC27:01000000:FEFFFFFF --patch 0x7ADDE0:01000000:FEFFFFFF \\
  --patch 0x7AE754:01000000:FEFFFFFF --patch 0x7AE76C:01000000:FEFFFFFF \\
  --patch 0x7AE7B0:01000000:FEFFFFFF

# 3) dw=5 后装强推跳板（另开窗口）
python tools\\ui_activate.py --wait-dw5 60
# 45 秒后重触发
python tools\\ui_activate.py --reset

# 4) 置前截图
pwsh -NoProfile -File tools\\capture_screen.ps1 -OutFile runs\\X\\shot.png -DelayMs 3000
```

### 15.5 新增文件

| 文件 | 作用 |
|---|---|
| `server319/lobby_udp.py` | UDP+TCP 3074 回显端点 |
| `tools/ui_activate.py` | cppActivate 强推跳板 |
| `tools/find_calls.py` | 扫描指定 VA 的全部 call 调用点 |
| `tools/watch_patch_sites.py` | 监视补丁点是否被还原 |
| `tools/probe_pump_sites.py` | 读取 pump 补丁九处字节 |
| `tools/dump_state_mapper.py` | 转储 ui_state 映射与全局量 |
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, text in (("PROJECT_STATUS.md", STATUS), ("HANDOFF-CURRENT.md", HANDOFF)):
        path = root / name
        with path.open("a", encoding="utf-8") as stream:
            stream.write(text)
        print(f"appended {len(text)} chars to {name}")


if __name__ == "__main__":
    main()
