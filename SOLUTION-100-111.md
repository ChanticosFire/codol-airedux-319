# CODOL Build 1604220 离线大厅：`[100]` 与 `[111]` 的完整解法

> 目标版本：**3.19.26.17 / Build 1604220**（社区常称 3.19.26.13）
> 复现环境：Windows + CPython 3.13 + 客户端隔离副本
> 结果：Auth → LSG → `dw=5` → 前端激活 → **大厅完整渲染**
> 记录日期：2026-10-22

---

## 0. 先确认你手上的客户端是对的

用 SHA-256 判定，别看目录名或版本号：

| 文件 | SHA-256 | 大小 |
|---|---|---|
| `codoMP_client_shipRetail.exe` | `3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f` | 7,842,456 |
| `codoMP_client_shipRetailBase.dll` | `7bbc5fb07ebca9b4671ec0e9a953bbd4e1baaca6a9ca29888531c3213e400f64` | 61,137,048 |
| `IIPS/iips.dll` | `72ddb9d15626b5a0a001347da141fb944a9f862db713e01c06a964ec8dc35348` | 347,704 |
| `IIPS/IFS2.dll` | `5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421` | 601,656 |

EXE 或 Base 对不上，本文所有地址都不成立。

**必须在副本上操作**：`runtime\client-1604220`，原始包只读。

---

## 1. `[100]` 的成因与解法

`[100]`（`无法连接大厅服务`）在 **Auth 阶段**就决定了。两个独立原因：

### 1.1 客户端配置：`dwauth.ini` 是**三行纯文本**

写成 ini 节（`[Auth]` / `host1=`）完全无效，客户端会继续连腾讯服务器，然后报
`DW_DNS_ERROR` 或 `DW_ACCOUNT_ERROR`。

**正确格式**（`runtime\client-1604220\dwauth.ini`，ASCII、CRLF）：

```
127.0.0.1 4174
127.0.0.1 4175
03EA
```

`03EA` = title_id 1002。

同理：

`stun.ini`
```
127.0.0.1
127.0.0.1
127.0.0.1
```

`iips.ini`
```
enable_iips=1
iips_url="http://127.0.0.1/"
```

### 1.2 TLS：证书**必须自签（叶子即 CA）**

这是最容易卡住的一步。1604220 的 `codoMP_client_shipRetailBase.dll` 内含 OpenSSL，
**强制校验证书**（1649370 不校验，所以旧版什么都不做也能过 Auth）。

用「CA 签发叶子」的链式证书会得到：

```
tls_handshake_failed  SSLError: [SSL: TLSV1_ALERT_UNKNOWN_CA]
```

**正确做法**——生成单张自签证书：

```powershell
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 `
  -keyout auth.key -out auth.crt `
  -subj "/CN=127.0.0.1/O=offline-research" `
  -addext "subjectAltName=IP:127.0.0.1,DNS:localhost"
```

然后把这张证书写进**两个**信任库：

1. `runtime\client-1604220\cacert.pem` —— 追加到末尾
2. `C:\Program Files (x86)\Common Files\SSL\cert.pem` —— Base DLL 里的 OpenSSL 默认路径

> 单独做以下任一项都**不够**（实测均失败）：
> `certutil -addstore -user Root`、`certutil -addstore Root`、
> `SSL_CERT_FILE` 环境变量、`CURL_CA_BUNDLE` 环境变量。

成功标志：服务端 `auth.jsonl` 出现 `auth_request len=188` 紧跟 `auth_response 200`。

### 1.3 Auth 响应只回 **7 个字段**

客户端严格解析，多一个字段就 `DW_ACCOUNT_ERROR`。

```json
{
  "auth_task": "<请求值 + 1，字符串>",
  "code": "700",
  "iv_seed": "<请求原值>",
  "client_ticket": "<128 字节 Tiger 票据的 base64>",
  "server_ticket": "<同上>",
  "identity": "<请求原值，缺省 local>",
  "lsg_server_ticket": "<同上>",
  "lsg_server_ticket_size": "128"
}
```

要点：
- `auth_task` 是 **请求 + 1**，且是**字符串**
- `code` 是**字符串** `"700"`，不是数字
- 票据必须是**真实 Tiger 票据**，全零会让客户端同样报 `DW_ACCOUNT_ERROR`
- 请求 `auth_task == 32` 时额外回 `extra_data`（codoid 握手）

**必须删掉**的字段（我们最初全都有，导致 `DW_ACCOUNT_ERROR`）：
`result`、`success`、`member_position`、`estimated_wait_time`、`next_poll_after`、
`time_to_live`、`licenses`、`license_id`、`cd_key`、`ciphertext`、`extra_data`(非 32)、
`user_id`、`title_id`

---

## 2. `[111]` 的成因与解法

`[111]`（`与大厅服务失去连接`）有两层，**都要修**。

### 2.1 第一层：UDP 3074 必须有人应答

**LSG 握手走 UDP，不走 TCP。** `0xbb1420` 是 sendto 封装，构造
`"1E" + u16([session+0x12C])` 发到 `127.0.0.1:3074`。

如果 UDP 3074 上没有监听，握手无人应答——这是 `[111]` 反复出现的主因之一。

**做法**：在 `127.0.0.1:3074` 同时监听 **UDP + TCP**，把收到的包**原样回显**。

实测抓到并回显的包：

```
udp_in  127.0.0.1:22011  len=3  1e0300
udp_echo len=3
udp_in  127.0.0.1:22011  len=4  14020000
udp_echo len=4
```

### 2.2 第二层：lobby pump 的 **9 处**补丁

`[lobby+0x1F4]` 这个状态量以前撑不过 47 秒就翻成 `-2`。根因是 pump 匹配判定失败后走
清理路径把 `1F4` 写成 `-2`，客户端读到 `-2` 就认定连接已失去。

四类失败跳转改成 `9090`（NOP），五处「硬编码写 -2」的立即数改成 `1`：

| # | VA | 原始字节 | 补丁字节 | 说明 |
|---|---|---|---|---|
| 1 | `0xBBA295` | `7e 1a` | `90 90` | 握手失败跳转 |
| 2 | `0xBBA29D` | `75 12` | `90 90` | 握手失败跳转 |
| 3 | `0xBBA276` | `74 39` | `90 90` | 握手失败跳转 |
| 4 | `0xBBAD4D` | `75 72` | `90 90` | 握手失败跳转 |
| 5 | `0xBADC27` | `fe ff ff ff` | `01 00 00 00` | 写 -2 → 写 1 |
| 6 | `0xBADDE0` | `fe ff ff ff` | `01 00 00 00` | 写 -2 → 写 1 |
| 7 | `0xBAE754` | `fe ff ff ff` | `01 00 00 00` | 写 -2 → 写 1 |
| 8 | `0xBAE76C` | `fe ff ff ff` | `01 00 00 00` | 写 -2 → 写 1 |
| 9 | `0xBAE7B0` | `fe ff ff ff` | `01 00 00 00` | 写 -2 → 写 1 |

> ⚠️ **第 5 处是 `0xBADC27`，不是 `0xBADC26`**。
> 那条指令是 `be fe ff ff ff`（`mov esi, -2`），`be` 是操作码，**立即数从下一字节开始**。
> 我第一次按 `0xBADC26` 改，补丁工具报 `applied=false`，就是差这一个字节。

### 2.3 另外 6 处常规补丁（配合使用）

| VA | 原始 | 补丁 | 作用 |
|---|---|---|---|
| `0x803699` | `74 1f` | `eb 1f` | lobby pump：状态≠2 也走成功分支，让 `dw` 保持 5 |
| `0x803659` | `89 35 40 ba 4a 08` | `90 ×6` | 不写 `DWLOBBY_DELETED` |
| `0x7F2A0A` | `3d bc 02 00 00 74 07` | `b8 bc 02 00 00 90 90` | 账户状态强制为 2bc |
| `0x7EE9DC` | `e8 2f 2f 01 00` | `90 ×5` | 抹掉对 `0x801910` 的调用 → 不弹 `[111]`、不清理连接 |
| `0x77C860` | `55 8b ec 83 e4 f8` | `c3 90 90 90 90 90` | 提前返回 `WIN_ERROR` 弹窗函数，保留渲染窗口 |
| `0x60C649` | `b0 01` | `b0 00` | 隐藏「连接中」提示 |

> 注意：**不要**提前返回整个 `Com_Error`（`0x4F8270`）。那样能保住窗口，但 `dw` 到不了 5，
> 60 秒后会被清零。只返回它内部调用的弹窗函数 `0x77C860` 才是对的。

全部 15 处应用后，状态机应当走到：

```
dw=2 ui=6  DW_DNS_COMPLETE
dw=3 ui=9  lstate=1  DW_ACCOUNT_LOGIN_COMPLETE
dw=5 ui=9  lstate=2  DWLOGON_REGISTERCODOID_COMPLETE
```

---

## 3. `[111]` 之后：让大厅 UI 真正出现

`dw=5` 只代表大厅状态机到位，前端（Scaleform）还没激活。FE 梯 `0x5EBFD0` 的逻辑：

```
G1 = [0x82E1340]
G1==0: 调 0x6BBF30 (firstlogin)   → 离线会话恒返回 0，**永远停在 0**
G1==1: CS 必须=9
       0x730C50 (FE-loaded) 必须返回 1   ← 离线会话返回 0，**停在 1**
       ……
G1==2: 调 0x5EBE10 (cppActivate) → gate=1, G1=3
```

**关键**：直接把 `G1` 写成 **2**（跳过 firstlogin 和 FE-loaded 两道自检），
梯子会**自己**走完最后一步：

```
before  G1=0 gate=0 session_ready=0 CS=9
now     G1=2 gate=0 session_ready=1 CS=9
now     G1=3 gate=1 session_ready=1 CS=9    ← cppActivate 已执行
```

> ⚠️ **写 1 没用**。写 1 只会停在 `G1==1` 等 FE-loaded。
> 必须在 `dw=5` 之后、直接写 **2**。

### 3.1 另一种做法（跳板，效果不如上面干净）

在每帧泵 `0x7F25F0` 装一次性跳板，直接调 `0x5EBE10`：

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

社区提到的「强推补丁」就是它。它能让大厅出现，但 `gate` 不一定会被正确置位，
所以**推荐用 `G1=2` 让状态机自己走完**。

---

## 4. 完整操作顺序

```
1. 起服务（三个进程，全部只绑 127.0.0.1）
   ├─ UDP+TCP 3074 回显
   ├─ Auth 4175（自签证书）
   └─ LSG  4174（自签证书）

2. 打 15 处补丁 + 启动客户端（-q）

3. 等状态机到 dw=5, ui=9
   （约启动后 15–25 秒）

4. 把 [0x82E1340] 写成 2
   （可同时把 [0x84ABAFC] 写成 1）

5. 观察 [0x82E1340]=3、[0x82E1344]=1
   → 大厅渲染
```

---

## 5. 阴性结果（别重复踩）

| 尝试 | 结果 |
|---|---|
| `dwauth.ini` 用 ini 节格式 | 客户端不读，继续连腾讯，`DW_DNS_ERROR` |
| CA 签发叶子的链式证书 | `TLSV1_ALERT_UNKNOWN_CA` |
| `certutil` 用户级 / 机器级装 CA | 都不够，OpenSSL 不读系统库 |
| `SSL_CERT_FILE` / `CURL_CA_BUNDLE` 环境变量 | 都不生效 |
| Auth 响应带 `result`/`success`/`member_position` 等 | `DW_ACCOUNT_ERROR` |
| `server_ticket` 全零 | `DW_ACCOUNT_ERROR` |
| 客户端发零帧时服务端回零帧 | **反而抑制**后续请求，不要回 |
| 直接把 `G1` 写成 1 | 停在 1，等 FE-loaded，永远不动 |
| 提前返回整个 `Com_Error`(`0x4F8270`) | 窗口保住，但 `dw` 到不了 5，60 秒后清零 |
| 打 `0xBADC26` 而非 `0xBADC27` | `applied=false`，立即数错位 |
| 只监听 TCP 3074，不监听 UDP | `[111]` 反复出现 |

---

## 6. 判定成功的画面

大厅应显示：

- 左侧菜单：`公告` / `福利` / `任务`
- 主区四格：`多人游戏 (PVP)` / `特种行动` / `闯关模式 (PvE)` / `自定义游戏`
- 右上：玩家名 + 军衔（如 `Administrator` / `新兵`）
- 中间：`TextField` 模态弹窗（带「关闭」按钮）—— 社区记录里也有这个，属正常
- 底部：状态文案

到这一步 `[100]` 与 `[111]` 都已消失。

---

## 7. 尚未完成（供后续参考）

- `TextField` 弹窗需要点「关闭」
- 大厅业务数据（公告/任务/商城）为空，需 `svc80` / `svc255` 应答填充
- `svc71/task9`(FindSessions) 与 `task3` 在部分 run 中不到达，属客户端竞态

---

**最后更新**：2026-10-22
