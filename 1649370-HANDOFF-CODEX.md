# 1649370 阶段性交接（给 codex）

> **2026-10-22 最新进度**：已从 1649370 原始 `lf_init_mp_cross_fire_V10.ifs` 解出并验过 538 件地图松散资源（含真实 loadscreen、compass），`--map-loose-crossfire` 只在私有 stage 按哈希装配。配合发行签名 v461 三份 FF、自然 Auth/LSG 登录，`preloadmap` 后仍黑屏并 `fatal_dialog`。本文件较旧的“缺 v461 load FF”及“仅缺注册表即可完成进图”均不能作为当前已证根因；G2 未通过。见 [本轮证据](evidence/experiments/20261022-codex-crossfire-resource-closure.json)。

> **2026-10-22 复核纠偏**：本文件的“缺 461 版 `mp_cross_fire_load.ff`”已过时。`ff_init_mp_cross_fire_V70.ifs` 内含 `mp_cross_fire.ff`、`_load.ff`、`_const.ff` 三件套，均为 v461 且发行签名/哈希链通过；仓库原有 `runs/20261021-1649370-crossfire-base` 与本轮独立提取 SHA-256 一致。使用 `--map-probe mp_cross_fire_native --map-command-mode none` 的私有 stage 已确认覆盖三件套。自然登录到大厅后注入 `preloadmap mp_cross_fire 1` 仍报 `WIN_FILE_NOT_FOUND`，所以 G2 尚未通过。现有 CreateFileA 钩子只记录打开尝试，不能凭 `loadscreen_*` 名称断定缺件。复核见 [本轮证据](evidence/experiments/20261022-codex-map461-assessment.json)；下轮抓 CreateFileA 返回值/错误码并关联 `0x4F4D30`/`0x4F5120`。旧的手写 `state=3` 配方仅作历史对照，当前以自然 Auth/LSG 登录链为基线。

> 生成时间：2026-10-22
> 目标：在 `E:\GAME\COD\codol-airedux\319` 推进 CODOL Build **1649370**，实现玩家与 AI 的本地 bot 对战、可退出回大厅。
> 约束：坚持 1649370 版本；其它版本（2.6.9.7、3.19.26.13、1604220）只能作参考实现，不能切换目标。

---

## 一、当前成果（已验证）

### 1. 启动链路（已完全打通）

| 环节 | 状态 | 关键点 |
|---|---|---|
| 客户端启动 | ✅ | overlay 必须是 **manifest 子集 + 20 个启动 ff** |
| 本地 Auth/LSG 登录 | ✅ | `server319.lsg` + `drive_login_state_machine.py` |
| 进入游戏大厅 | ✅ | 完整 UI（角色/任务/商城/QQ 窗）已截图 |

**overlay 正确配置**（`resources/v1649370/offline-resources`，当前 152 文件）：

- 按 `offline-loose-library/manifest.json` 的 `resources` 清单裁剪（18,154 条期望）
- **必须保留 20 个 `client_shipretail/chinese/*.ff`**（manifest 不含 ff，但引擎启动需要）
- 多一个 manifest 之外的文件 → `overlay数据冲突`，客户端起不来

### 2. 进图链路（部分打通）

已能稳定复现的配方：

```
1. patch 0x49EEA3 → E9 B8 02 00 00 90   (绕过 WIN_ZONE_ERROR 分支)
2. patch 0x6751F0 → B0 01 C3            (伪造 challenge 发送成功)
3. preloadmap mp_cross_fire 1           (Cbuf 注入)
4. connection+0x14 = netadr(127.0.0.1:28969, type=4)
5. state=3  → 0x76446B0 = 3
```

效果：客户端切到地图加载界面（「1 交叉火力」+ 进度条），但 **15 秒内退出**。

### 3. 静态分析成果（大量）

| 目标 | 地址/内容 |
|---|---|
| 游戏状态机 | `[0x76446B0]`（0=前端，3=游戏） |
| `state=3` 官方写入点 | `0x470467`（前有 `call 0x7F85C0`） |
| Cbuf 命令链 | `preloadmap→0x470750→0x5C7C70`（真地图加载） |
| fastfile 版本校验 | `0x483E3B cmp eax,0x1CD`（必须 461） |
| 版本不匹配报错 | `0x483E60 push 2; call Com_Error`（文本 `283 %s %d %d`） |
| **exe 内嵌 RSA 公钥** | **`0xDAC958`**，270B DER（`30 82 01 0A … 02 03 01 00 01`） |
| **公钥唯一引用点** | **`0x4836CE`（.text）＝验签函数** |
| 验签失败路径 | `0x483681` / `0x4836BC`（`32 C0` xor al,al → 返回 0） |
| CreateFileA IAT | `0xCA8208`（**游戏用 A 版本，不是 W**） |
| CreateFileW IAT | `0xCA8284` |
| 网络槽位表 | `0xE3F4DB0 + type*24`（每项 24B：对象指针/标志/状态） |
| raw send | `0x622040`，要求对象+状态+`vtable+0x24==2` |
| 资源注册表初始化 | `0x661A7C`（checksum 常量 `0x77DB834` → `[0x77D8240]`，资源组 `[0xE5701C]`） |
| Com_Error | `0x4F82E0` |
| Fatal error | `0x77C930` |
| 地图加载函数 | `0x5C7C70`（调 `0x81DF20` 加载、`[0x827606C]=1.0`） |

### 4. 协议层成果（来自协作仓库 `codol_server`）

```rust
// InitialState 编码
3 || server_command_sequence:u32le || map_name:NUL || zone_name:NUL
  || registration.checksum:u32le || 4 || configstrings || 5
  || client_number:u32le || checksum_feed:u32le || 5

// Registration
pub const SLOT_COUNT: usize = 12761;
struct Registration { checksum: u32, slot_types: [u8; 12761] }
// 文本槽：slot_types[i] >= 23 || slot_types[i] == 21
```

限制：`map_name`/`zone_name` ≤ 31B，`client_number` ≤ 18。

---

## 二、当前卡点（按优先级）

### 卡点 1：`state=3` 后为什么退不出大厅 / 闪退

- **现象 A**：多数情况下能进「地图加载界面」，15s 后退出。
- **现象 B**：最近一次（patch 免验签后）t=5/10s **仍停在大厅**，t=15s 退出。
- 待查：`state=3` 是否真的写入、是否被重置；`0x77C930` hook 是否抓到 fatal 文本。

### 卡点 2：fastfile 双层保护

`mp_cross_fire_load.ff` 报 `283 mp_cross_fire_load 365 461`：

- 本机所有副本都是 **365**（来自 2.6.9.7），1649370 需要 **461**。
- 已把 3 个 365 文件的**明文前缀版本号改成 461**（`0x8`，签名不覆盖），但**仍失败**。
- 社区反馈（Ri1o）：**"只动 ff 这辈子都进不去，除非启动的 exe 没有校验"**。
- 社区文档给了完整方案：**换信任根**（替换 exe 内嵌 270B 公钥 + 用自建私钥重签所有 ff），或**运行时 patch 验签函数**。

### 卡点 3：缺少真正的 461 版地图资源

- `ff_init_mp_cross_fire_V70.ifs`（37MB，**ver=461**）里有正确内容（`IWff` @ 偏移 358）。
- 从 nifs 提取的 `common_gametype_mp.ff`（34.8MB，ver 461）已验证可提取。
- **但**：nifs 提取的 `mp_cross_fire_load` 还没试过（V70 包只含主 zone？需确认）。

### 卡点 4：资源注册表（Registration）

协作仓库文档明确指出：

- 客户端需要 **12761 槽的 `Registration`**（类型+校验）
- 以及 **`game_initial_state`**（map/zone/checksum/configstring）
- 「**不发送空注册表冒充成功**」

→ 我们目前**完全没有提供这两样**，可能正是加载无法完成的原因。

---

## 三、走过的误区（避免重犯）

| 误区 | 事实 |
|---|---|
| 从 2.6.9.7 拷 ff 到 1649370 | 版本不匹配（365 vs 461），**不能混用** |
| 往 overlay 里加资源 | overlay 必须严格等于 **manifest 子集 + 20 个启动 ff**，多一个就冲突 |
| 只改 ff 版本号 | 不够，exe 有 **RSA 验签** |
| 认为「服务异常 742」是服务问题 | 实际是 **zone 文件缺失**（`WIN_ZONE_ERROR`） |
| 用 `CreateFileW` hook 抓文件 | 游戏用 **`CreateFileA`**（0xCA8208） |
| 用 `sendto` hook 抓网络 | 游戏走**内部 raw send**（`0x622040`），不经过 Winsock `sendto` |
| 前台运行 `launch_1649370.py` | 会阻塞整个命令到会话结束，**必须后台跑** |
| 直接调用 `0x621E50` / `0x5C05F0` | 会崩（前置条件不全） |
| `state=3` 当捷径 | 引擎未初始化，任何游戏侧调用都会崩 |

---

## 四、建议的下一步（给 codex）

### 优先级 1：确认当前 `state=3` 的真实效果

```
后台起会话 → 登录 → patch 三处 → preloadmap → netadr
→ 写 state=3 → 用 50ms 轮询读 0x77C930 hook（dump 地址）
→ 同时每个 patch 打印完整 JSON 确认 verified
```

### 优先级 2：解决 ff 校验（两条路）

**路 A（推荐先试）**：运行时 patch 验签

- 已定位：`0x483681` / `0x4836BC` 是失败返回 0 的两处
- 改为 `B0 01`（mov al,1）→ 需要**确认 patch 真的生效**（打印 verified）
- 若验签恒成功，则改过版本号的 ff 应该能加载

**路 B（社区文档完整方案）**：

1. 生成 RSA-2048 密钥对（65537）
2. 把 `0xDAC958` 的 270B 替换为自建公钥（等长）
3. 用自建私钥重签所有 ff（需要能解密头部——**这里需要原私钥或找其它解）
4. 两者必须成对

### 优先级 3：补资源注册表

- 按协作仓库的 `InitialState` / `Registration` 格式构造；
- 关键是拿到真实的 **12761 槽类型的数组**（可从 `[0xE5701C]` 资源组 + `[0x77D8240]` checksum 推导）；
- 然后通过 netadr 回路或注入方式提供给客户端。

---

## 五、常用操作（已验证可复现）

### 会话配方

```powershell
# 1) 服务器（后台）
python -m server319.lsg --cert runs/20261020-live-derived01/tls/auth.crt `
  --key runs/20261020-live-derived01/tls/auth.key --port 28969 `
  --log evidence/experiments/xxx.jsonl --seconds 220 --allow-auth-tls

# 2) 客户端（后台！）
python tools/launch_1649370.py --full --seconds 200 --local-profile `
  --loopback-tcp-guard --local-auth-lsg --name <会话名>

# 3) 登录（约 30 秒后）
python tools/drive_login_state_machine.py --set-ui-state 1 --ticks 30 --interval 0.3

# 4) 泵 socket（后台）
python tools/pump_lsg.py --seconds 120 --interval 0.1

# 5) 注入链路
python tools/patch_client_bytes.py --at 0x49EEA3 --bytes e9b802000090
python tools/patch_client_bytes.py --at 0x6751F0 --bytes b001c3
python tools/cbuf_command.py --command "preloadmap mp_cross_fire 1"
# 写 netadr + state=3 用 tools/*.py 里的内联脚本
```

### 关键工具

| 工具 | 用途 |
|---|---|
| `tools/launch_1649370.py` | 启动器（必须后台） |
| `tools/patch_client_bytes.py` | 运行时 patch（会打印 verified） |
| `tools/cbuf_command.py` | Cbuf 命令注入 |
| `tools/hook_com_error.py` | hook `0x4F82E0`/`0x77C930`，抓 fatal 文本 |
| `tools/hook_createfile.py` | hook `CreateFileA`（`--iat 0xCA8208`），抓文件访问 |
| `tools/sample_eips.py` | 采样全线程 EIP |
| `tools/udp_challenge.py` | UDP challenge 应答器 |
| `tools/transport_after_state.py` | state=3 后建通道（会崩，慎用） |

### 环境清理

```powershell
pwsh -NoProfile -File tools/net_rollback.ps1
# 杀 python server + codol1649370-offline
# git status 应为空
```

---

## 六、重要文件位置

| 内容 | 路径 |
|---|---|
| 客户端 exe | `E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe` |
| overlay | `E:\GAME\COD\1649370\resources\v1649370\offline-resources` |
| overlay 备份 | `...\offline-resources.bak-118`（352 文件） |
| manifest | `...\offline-loose-library\manifest.json`（18,154 条） |
| 协作仓库 | `E:\GAME\COD\codol-airedux\codol_server`（Rust，Gitea） |
| 社区文档 | `319\他人文件参考\Fastfile校验绕过思路.md` |
| 2.6.9.7 参考 | `E:\GAME\COD\codol-airedux\CODOL-2.6.9.7-Launcher` |
| IIPS 包 | `E:\GAME\COD\3.19.26.13\IIPS\IIPSDownload` |

---

## 七、红线（必须遵守）

1. **不得因问题判定目标受阻而暂停**；
2. **不得让本机断网**；
3. **不得要求用户手动点击**，必须自己模拟点击；
4. 每轮更新 `1649370-STATUS.md` / `PROJECT_STATUS.md` 并 **`git push origin main`**（核对 ahead=0）。
