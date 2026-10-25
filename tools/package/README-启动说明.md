# CODOL Build 1649370 自建服务端 —— 运行包

**包版本**：20261025　**客户端**：Build 1649370 / 3.19.26.22　**协议**：`shortversion = 1.1.1.13`
**运行时 exe**：`runtime/codol1649370-offline.exe`，SHA256 = `141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380`

---

## 一、包里有什么

```
CODOL-1649370-runtime-package/
├── README-启动说明.md          ← 本文件
├── CODOL-1649370-服务端实现文档.md   完整技术文档（协议/数据位/流程）
├── HANDOFF-1649370.md               交接总结（状态、卡点、排除项）
├── LONGTERM-GOAL-1649370.md         长程目标（供新会话接续）
├── MANIFEST.json                    全包 3532 个文件的 路径/大小/SHA256
├── sync-missing-resources.ps1       从已有 runtime 补 main/ + hires/
│
├── runtime/                    ★ 客户端补丁运行副本（已排除 main/ 与 hires/）
│   ├── codol1649370-offline.exe      已打补丁的 exe（哈希校验通过）
│   ├── *.dll / *.dat / *.pak         必需依赖
│   ├── players/                      玩家配置（config_mp.cfg 等 4 个）
│   ├── dwauth.ini                    本地认证开关
│   ├── client_shipretail/            244 MB / 26 文件
│   ├── devraw_shared/                321 MB / 3301 文件（.iwi 材质 + 音效）
│   ├── locales/                      3.1 MB / 53 文件
│   └── main/  hires/                 **本包未含**，需用脚本同步（共约 14.5 GB）
│
├── codol_rebuild/             ★ launcher 的 Python 依赖（131 文件 / 1 MB）
├── server1649370/             自建游戏服（UDP）
├── server319/                 LSG 认证服务（TCP + TLS）
├── tools/                     启动/转发/注入/gamestate 编解码 等 9 个工具
├── patches/_patch_r336.py     16 处运行时补丁 + 全局对象初始化
└── data/
    ├── v1649370/              game-settings.sqlite3 / local.sqlite3
    ├── gamestate-demo-6411.bin    从 2021-08 真实对局 demo 提取的 gamestate
    ├── gamestate-client0.bin      同上，client_number 改为 0
    ├── baseline-outer17-245.bin   真实 baseline 快照
    ├── snap-nospec-1.bin          ★ 推荐快照（0x35 置 0）
    ├── offline-menu-patches.json  菜单补丁配置
    └── tls/                   auth.crt / auth.key（LSG 用自签证书）
```

---

## 二、前置条件

| 项 | 要求 |
|---|---|
| Python | 3.10+ |
| 第三方包 | **`pycryptodome`**（仅 `server319` 需要：`from Crypto.Cipher import AES`） |
| 磁盘 | 完整 runtime 约 **15.3 GB**（本包 721 MB + 需同步的 14.5 GB） |
| 原版客户端 | 需 `E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe`（launcher 用于 PE 解析与校验） |
| 端口 | 28969（TCP 与 UDP 复用） |

```powershell
pip install pycryptodome
```

---

## 三、部署步骤

### 1) 放置 runtime

launcher 的 `--reuse-runtime <name>` 会在
`E:\GAME\COD\1649370\workspaces\offline-runs\<name>\runtime` 查找运行副本。

把本包的 `runtime\` 整个放到该位置：

```powershell
$dst = 'E:\GAME\COD\1649370\workspaces\offline-runs\r900\runtime'
New-Item -ItemType Directory -Path $dst -Force | Out-Null
robocopy .\runtime $dst /E /NFL /NDL /NJH /NJS
```

### 2) 补 main/ 与 hires/

从任意一个已有 runtime（或原版客户端安装目录）同步：

```powershell
.\sync-missing-resources.ps1 -Source "E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime"
```

同步完成后 runtime 应约为 **15.3 GB / 88,581 文件**。

### 3) 校验完整性

```powershell
# 校验 runtime exe
(Get-FileHash .\runtime\codol1649370-offline.exe -Algorithm SHA256).Hash
# 期望：141215DD38754D39A45E9B112345049293579006EA98573A0BA51CC4D55AD380

# 全量校验（按 MANIFEST.json）
python -c "import json,hashlib,pathlib;m=json.load(open('MANIFEST.json',encoding='utf-8'));bad=[f['path'] for f in m['files'] if hashlib.sha256(pathlib.Path(f['path']).read_bytes()).hexdigest()!=f['sha256']];print('mismatch:',len(bad));[print(' ',b) for b in bad[:10]]"
```

### 4) 把服务端与工具放到项目根

`server1649370/`、`server319/`、`codol_rebuild/`、`tools/`、`patches/`、`data/` 需放到
`E:\GAME\COD\codol-airedux\319\` 下对应位置（`launch_1649370.py` 里的 `COMMUNITY_ROOT`
和 `sys.path` 是按这个布局写死的）。

---

## 四、启动序列

```powershell
cd E:\GAME\COD\codol-airedux\319

# 1) LSG 认证（TCP 28969，TLS）
python -m server319.lsg `
    --cert runs\20261020-live-derived01\tls\auth.crt `
    --key  runs\20261020-live-derived01\tls\auth.key `
    --port 28969 --allow-auth-tls --seconds 600 --log runs\r900-lsg.jsonl

# 2) 游戏服（UDP 28969）
python -m server1649370.gameserver --port 28969 --delay-send 1 `
    --gamestate-source file `
    --gamestate-file runs\demo-outer-exact\gamestate-network-ffb56d7e-6411.bin `
    --gamestate-gametype war --gamestate-map mp_crash_tropical `
    --snapshot-file runs\snap-nospec-1.bin `
    --snapshot-delay 1 --snapshot-seq 4 --snapshot-repeat 5000 `
    --snapshot-interval 0.1 --match-duration 600 --log runs\r900-gs.jsonl

# 3) 启动客户端
python -B -X utf8 tools\launch_1649370.py --name r900 --reuse-runtime r900 `
    --until-close --local-profile --full --local-auth-lsg --loopback-tcp-guard

# 4) 等客户端起来后（约 20 秒），取 pid 并打补丁
$p = (Get-Process -Name 'codol1649370-offline' | Select-Object -First 1).Id
python tools\patch_retry_ms_1649370.py --pid $p --ms 0
python tools\drive_login_state_machine.py --ticks 20 --interval 0.35 --set-ui-state 1
python runs\_patch_r336.py $p

# 5) UDP 转发桥
python tools\ring_bridge_1649370.py forward --target 127.0.0.1:28969 `
    --bind-port 29000 --start-challenge --retry-seconds 0 --seconds 400
```

**注意**：`--reuse-runtime r900` 必须与步骤 1 里放置 runtime 的目录名一致。

---

## 五、退出对局

```powershell
python tools\cbuf_1649370.py --pid $p --command disconnect
```

`disconnect` 会安全回到大厅（`cls.state` 10 → 0，进程存活）。
**不要用 `switchtomainmenu`，它会杀进程。**

---

## 六、当前状态

| 验收项 | 状态 |
|---|---|
| gs 日志出现真实 `connect`/`stats` 包 | ✅ |
| 客户端 `net_state` 由握手推进 | ✅ `CA_ACTIVE(10)` |
| 对局可结束并返回大厅 | ✅ |
| `ui_state != 5` | ✅ |
| 截图是「可自由操作的对局」 | ❌ **未达成** |

**卡点**：客户端停在「按 空格↓」（configstring 1424 = `PLATFORM_PRESS_TO_SPAWN`），
玩家角色未 spawn。输入层已彻底排除（4 种注入方式 × 全部 7 个窗口均无效、
`GetKeyboardState` 调用计数恒 0、无 DirectInput/RawInput）。
**问题在服务端下发的玩家数据**：玩家 configstring 条目 + 快照实体。

详见 `CODOL-1649370-服务端实现文档.md` 第 8 章。

---

## 七、已知限制

1. 玩家无法 spawn（唯一未达成项）
2. gamestate 来自 demo 抓包，`client_number = 1`，含 291 条 configstring 但无玩家名 bank
3. 快照为静态 baseline，世界不推进时间，无 AI 与其他玩家
4. 不实现真实对局逻辑（得分/回合/出生点/武器）
5. 依赖 `_patch_r336.py` 的 16 处客户端运行时补丁
6. `--local-auth-lsg` 强制 loopback guard，端口只能用 28969

---

## 八、安全提示

`data/tls/auth.key` 是**本机自签测试证书的私钥**，仅用于本地联调。
对外分发前请自行替换或移除。
