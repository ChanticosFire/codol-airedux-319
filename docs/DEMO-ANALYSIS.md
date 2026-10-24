# demo 分析：用 2021-08 的真实录制复原对局

> 目标：从停服当月（2021-08）的 `.demo` 里取出**真实服务器下发的数据**，作为 `server1649370` 的模板。
> 本文只写已经核实的东西，附可复现的命令与产物路径。

---

## 1. demo 在哪、是什么

位置：`E:\GAME\COD\使命召唤OL\main\demo\`（`E:\GAME\COD\Original Client\main\demo\` 是同一份副本）

**22 个 `.demo` + 一个 `202108demo.7z`**，时间跨度 **2021-08-24 ~ 2021-08-29**，两种模式：

| 前缀 | 模式 | 数量 |
|---|---|---|
| `0C-...` / `C-...` | **war**（多人对战） | 21 |
| `0C-2021-8-24[14-38-52]cha.demo` | **cha** | 1 |

最大的：`0C-2021-8-26[19-26-24]war.demo`（7.29 MB），本文用它做样本。

**已确认 demo 内容**（逐个字符串定位得到）：

- **地图**：`mp_crash_tropical`
- **模式**：`war`
- **configstring 更新流**：`d 3635 UK_spawn_music_mp_crash_tropical`、`s 0194 "OBJECTIVES_WAR_HINT"`、`p 1578`、`w 0 12 0` …
- **UI 事件**：`"EXE_MATCHENDED"`、`s ui_match_complete "1"`
- **dvar 流**：`d 2557 "mp_crash_tropical" 1000`、`d 3694 UK_winning_music_mp_crash_tropical`
- **尾部 asset 清单**（0x6E0000 之后）：`projectile_m67fraggrenade_*`、`body_chameleon_*`、`mp_crash_tropical` …（2595 条字符串）

**结论**：demo 是**真实对局的完整录制**，含服务端下发的数据。**这正是此前缺失的"正确样本"。**

---

## 2. 为什么它现在播不了（以及资源在哪）

demo 回放需要该地图的 fastfile。而客户端里：

```
E:\GAME\COD\1649370\resources\v1649370\offline-resources\client_shipretail\chinese\
    mp_cross_fire.ff            41,648,405   ← 唯一的地图 fastfile
    mp_cross_fire_const.ff          49,429
    mp_cross_fire_load.ff           24,853
    mp_playlists.ff                 49,429
```

**只有 `mp_cross_fire`。** demo 用的是 `mp_crash_tropical`，所以直接播会缺资源。

**但资源并没有丢**——它们在原始客户端的 IIPS 分发目录里：

```
E:\GAME\COD\使命召唤OL\IIPS\IIPSDownload\     ← 975 个 .ifs
    ff_init_mp_crash_tropical_V73.ifs            32,818,417
    lf_init_mp_crash_tropical_V21.ifs            59,043,616
    lf_hi_init_mp_crash_tropical_V19.ifs        178,639,708
    ff_init_mp_cross_fire_V70.ifs                37,492,702
    ...
```

`.ifs` 就是 CODOL 的资源分包格式，**地图 fastfile 在里面**。

---

## 3. `.ifs` 解包方法（已用 `mp_cross_fire` 验证）

### 3.1 容器结构

```
offset 0x0000  "nifs"            magic
offset 0x0004  ac 00 00 00       = 172   头部长度
offset 0x0008  ...               若干 u64 块偏移/长度（数据区约 0x23B8000 起）
offset 0x0150  “...t.ff”         目录里的文件名
offset 0x0166  "IWff0100"        ← 真正的 fastfile 从这里开始
```

**`IWff` 头在文件里只出现 2~3 次**，所以一块 fastfile 就是 **从第一个 `IWff` 到下一个 `IWff`**。

### 3.2 fastfile 头

```
49 57 66 66 30 31 30 30   "IWff0100"
cd 01 00 00               = 0x1CD = 461   ← fastfile 版本号
01 00 00 00
```

**客户端里那份能用的 `mp_cross_fire.ff` 头也是 `49 57 66 66 30 31 30 30 cd 01 00 00 01 00 00 00`，逐字节相同。**

### 3.3 提取结果

```python
# runs/_ifs_extract.py 的核心逻辑
hits = 所有 "IWff" + 4 位 ASCII 版本号 的位置
blob = data[hits[0] : hits[1] if len(hits) > 1 else len(data)]
```

| 源 `.ifs` | `IWff` 出现位置 | 提取出 | 大小 |
|---|---|---|---|
| `ff_init_mp_cross_fire_V70.ifs` | `0x166`, `0x23a30eb`, `0x23a9220` | `init_mp_cross_fire.ff` | 37,367,685 |
| `ff_init_mp_crash_tropical_V73.ifs` | `0x176`, `0x1f23f0b`, `0x1f2a040` | `init_mp_crash_tropical.ff` | 32,652,693 |

**校验**：提取出的 `cross_fire` 头与客户端里能加载的 `.ff` **完全一致**；但两者的 64 字节窗口采样**0/9122 相同**，且大小差 4.2 MB。

**这说明：一个可用的地图 `.ff` 不是单个 `ff_*` 包，而是 `ff_*` + `lf_*`（+ 可能 `lf_hi_*`）合并的结果**（37.4 + 4.2 ≈ 41.6 MB，与差值吻合）。**这是下一步要确认的点。**

产物在 `runs/ifs-extract/`。

---

## 4. demo 的读取器在客户端里的位置

demo 的格式不必猜——**客户端自己会读**。

| 字符串 | `VA` | 代码里的引用 |
|---|---|---|
| `PlayDemo` | `0x00DC5B98` | `0x0020967C` |
| `cl_demo_play %s` | `0x00DC5BA4` | `0x002096B1` |
| `PopulateLocalDemoFileInformation` | `0x00DC5BB8` | `0x0020977A` |

（**注意**：字符串位置在文件里是**文件偏移**，代码引用用 **VA**；换算必须走 section 表，否则会得出"没有引用"的错误结论——这一点已踩过。）

另外，命令名 `record` / `demo` / `stoprecord` 在 `0x9C08D0` 附近，并且**紧邻连接状态名表**：

```
CA_DISCONNECTED, CA_CINEMATIC, CA_LOGO, CA_CONNECTING, CA_CHALLENGING, CA_LOADING, CA_CONNECTED
```

**`CA_LOADING` 正是我们自建服务端时卡住的状态。** demo 回放会走同一条状态链，**因此 demo 是这条链的"正确答案"。**

---

## 5. 复原对局的两条路线

### 路线 A —— 先让 demo 播起来（最快拿到"画面基准"）

1. **合并出完整 `.ff`**：把 `ff_init_mp_crash_tropical_V73.ifs`、`lf_init_mp_crash_tropical_V21.ifs`、`lf_hi_init_mp_crash_tropical_V19.ifs` 里的 fastfile 块按顺序拼接（先拿 `cross_fire` 的三个包做对照，验证拼出的 41.6 MB 与现有 `.ff` 一致）。
2. **放到** `offline-resources\client_shipretail\chinese\mp_crash_tropical.ff`。
3. **在客户端执行** `cl_demo_play <demo 文件名>`。
4. **判定**：画面出现 = **渲染与地图加载链路完好**，那么黑屏纯粹是"服务端数据不对"；画面仍黑 = 资源仍有问题。

**这一步的价值**：它能把"渲染问题"和"数据问题"**永久分开**，而这两者在此前的排查里一直混在一起。

### 路线 B —— 从 demo 提取真实消息流（复原对局的主线）

1. **反汇编 `0x2096B1` 附近的 demo 播放入口**，得到 demo 的帧记录格式（头 + 帧类型 + 长度 + 负载）。
2. **提取进图前的消息序列**：`gamestate` → **`baseline`** → 首帧快照。**baseline 是否存在，是我此前推断的关键未知。**
3. **把这些消息的字节结构当模板**，套用到 `mp_cross_fire`（该图有 `.ff`）。
4. **服务端按模板下发**，并用 `ui_state != 5` + 截图作为验收。

> demo 里已确认存在明文 configstring（`d 3635 ...`、`s 0194 "..."`），说明 **demo 存的是解密后的数据**，不是密文——这对路线 B 是有利的。

---

## 6. 回答一个前提问题：对局到底哪些由服务端下发

用户判断"对局和人物模型要服务端下发"——**需要分成两部分**：

| 内容 | 来源 |
|---|---|
| 地图几何、材质、模型、贴图、动画资源、武器模型 | **客户端 fastfile**（所以必须先解 `.ifs`） |
| 实体位置/角度、玩家状态、血量、武器配置、命中、比赛状态机、每帧快照、baseline | **服务端下发** |

**两者缺一不可**：没有 fastfile 画不出东西，没有下发的实体数据就没有可动的内容。
**我们此前的处境是**：只有 `mp_cross_fire` 的 fastfile（够），但下发的数据形态不对（缺 baseline 一类的前置消息）。

---

## 7. 立即可执行的下一步

1. `cross_fire` 三个 `.ifs` 合并 → 与现有 `mp_cross_fire.ff` 对比（**验证合并规则**，不需游戏）；
2. 用同一规则合并 `crash_tropical` 三个 `.ifs` → 落盘为 `mp_crash_tropical.ff`；
3. 启动客户端执行 `cl_demo_play` → **截图判定**；
4. 若播通，立刻抓 demo 播放期间的**接收路径**（或直接静态解析 demo 帧），提取 `gamestate`/`baseline`/快照三段。

---

## 8. 附：可复现产物

- 解包脚本：`runs/_ifs_extract.py`
- 已提取：`runs/ifs-extract/init_mp_cross_fire.ff`（37,367,685）、`runs/ifs-extract/init_mp_crash_tropical.ff`（32,652,693）
- demo 样本：`E:\GAME\COD\使命召唤OL\main\demo\0C-2021-8-26[19-26-24]war.demo`
- 相关证据记录：`evidence/experiments/`（demo 相关记录随本轮一并提交）
