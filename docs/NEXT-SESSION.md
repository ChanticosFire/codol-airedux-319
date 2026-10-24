# 新对话启动指引

> **2026-10-24 14:48 补记**：本文件早段的“第一件事播 demo”已经完成。`r51` 和本轮 `r88` 均显示 `mp_crash_tropical` 实景；`r88` 截图 `runs/r88-shot.png`，实测 `ui_state=0`。这只验证 demo 路径，**不是 server1649370 驱动的 mp_cross_fire 成功**。播放前须装配五包 loose 资源并运行 `tools/fake_dvar.py --name g_gametype --value war`；缺前者会报 `images/wavy_nml.iwi`，缺后者会在 `0x43204F` 空指针崩溃。服务端在 `r88` 发出 capture gamestate 和 62 KB 候选快照，demo 同时自行推进 state 10，因此尚未证明网络快照被客户端采用。下一步离线确定 demo gamestate/快照的**真实记录边界和顺序**，再单独走服务端路径。demo 记录 `01` 后的 `u32` 是**序号**（样本 22→5784，多数相邻 +1），不是长度；旧 `DEMO-ANALYSIS.md`/旧解析器的“len”说法已过时。

> 给**下一次会话**用。`docs/GOAL.md` 是目标全文；本文件只讲"第一件事"和"别踩的坑"。

---

## 1. 开场怎么说

```
恢复长程目标，继续 CODOL 1649370。先读 docs/GOAL.md 和 docs/NEXT-SESSION.md。
```

若新会话没有 goal，则说：`创建长程目标，objective 用 docs/GOAL.md 的全文。`

---

## 2. 状态速览（2026-10-24 收尾时）

| 层 | 状态 |
|---|---|
| 协议握手 | ✅ 通（net_state 可到 10） |
| 快照格式 | ✅ 逐字节已知（含 8 位 `last_changed`） |
| 实体列表 / 增量 | ✅ 可置计数=1、ID 可指定、模式 1 写真实浮点 |
| **资源层（fastfile）** | ✅ **已 settled**：overlay 现在是**全真 461**，客户端能启动并跑到 net 10 |
| **前端状态** | ❌ **卡在 `ui_state = 5`、`[+0x5E8] = 3`（CA_LOADING）** |
| 画面 | ❌ 黑屏 + 转圈（转圈在动 = 确实在等） |

**唯一判据**：`ui_state (0x84ABA50) != 5` **且截图里出现地图**。

---

## 3. 第一件事：让客户端播 demo（决定性）

**为什么是它**：`mp_crash_tropical`（所有 2021-08 demo 的地图）**已经是 overlay 里一套完整合法的真 461 资源**（`mp_crash_tropical.ff` 32,620,821 / `_load` 24,853 / `_const` 90,389，全部 `mod 0x2000 = 277`），22 个 demo 也在盘上。

**怎么做**：启动客户端，**跳过 server / ring_bridge 步骤**，执行

```
cl_demo_play <demo 文件名>
```

**两种结果都是决定性的**：

| 结果 | 含义 | 下一步 |
|---|---|---|
| 出现真实对局画面 | **渲染与地图管线完好**，缺的完全在"服务端该发什么" | 抓 demo 播放时的接收路径，或静态解析 demo 帧，提取 `gamestate`/`baseline`/快照 |
| 仍黑屏或报错 | 这个构建**无法渲染该地图**（硬限制） | 先确认错误来源，再决定是否继续走服务端路线 |

**不要**在这一步之前又去改快照字节。

---

## 4. 已证伪 / 已 settled（不要重复）

1. **`.ifs` 拼接规则不存在**（数学上不可能）。合法 fastfile 长度恒为 `0x115 + N*0x2000`；k 个成员拼接得 `(277k) mod 8192`，只有 k=1 等于 277（277 与 8192 互素）。`.ifs` 是「172 B 头 + CRLF 名单 + 16 B MD5 + 若干**完整签名 fastfile**」的容器；`lf_*` / `lf_hi_*` 里 `IWff` 出现 **0 次**，不参与 ff 构成。
2. **`41,648,405` 那个 `mp_cross_fire.ff` 是 2.6.9.7 的 365 二进制**，只把 `0x8` 一个字节 `0x6D→0xCD` 冒充 461。现已换成真 461（`37,331,221`）。
3. **`common_gametype_mp.ff` 的非法版（34,783,232，`mod=0`）已换成合法 34,693,397** —— 但**替换它不改变任何可观测行为**，所以它**不是**卡点。
4. **真 461 资源可用**：换成真 461 后 `engine_ready=True`、net 8/9/10 正常。此前"换成 461 会崩"是**启动器 30 秒超时误判**，不是不兼容。
5. 不要再用 `net_state == 10` 当成功判据。
6. 不要再改 `flags` 字节（`0x0C` / `0x08` 都试过，无效）。
7. 不要推进 `serverTime`（8 个递增快照试过，无效）。
8. 不要说"1649370 有 14 个 section"（**只有 5 个**）。
9. 实体 ID 不是 bit 1309 起的连续 12 位（**三段式、跳过 byte 164**）。
10. 不要在**从不会执行的分支**上加字段（早期最大浪费）。

---

## 5. 卡点的精确位置（若 demo 路线不通，回来查这里）

```
ui_state(0x84ABA50) == 5
  ← status 2  ←  0x803780 → 0xB7A670 → 0xBA0780 映射
  ← 决定字段 [sub+0x5E8] == 3        (sub = [0x8269774] + 0x4F4)
     实测：[+0xC8]=2  [+0x644]=0  [+0x5E8]=3
     0xBA07A4 处 sete al; inc eax  →  ==3 恰好产出 status 2
  ← [+0x5E8]=3 由 0xBA3C47 写入，前提是 [obj+0x5FC] 的 8 字节令牌比较成功
     （0xBA3C05..0xBA3C1A，call 0xB73FE0）
```

**未定位**：如何离开状态 3。写入点全表：`0xBA3C47`(=3)、`0xBA3DA3`(=2)、`0xBA3252`(=1)、`0xBA3460`/`0xBA3661`/`0xBA40AA`(=0)、`0xB83920`(=1 字节)、`0xB824AC`(析构)。

**旁证**：客户端连接状态名 `CA_DISCONNECTED / CA_CINEMATIC / CA_LOGO / CA_CONNECTING / CA_CHALLENGING / **CA_LOADING** / CA_CONNECTED` —— 我们卡在 `CA_LOADING`，而 demo 播放走同一条链。

**已确认 demo 读路径**（若要从 demo 提数据）：
`PlayDemo` VA `0x00DC5B98` → 代码 `0x0020967C`；`cl_demo_play` VA `0x00DC5BA4` → `0x002096B1`；`PopulateLocalDemoFileInformation` VA `0x00DC5BB8` → `0x0020977A`。
**注意**：字符串位置是**文件偏移**，代码引用用 **VA**，必须经 section 表换算，否则会误判"无引用"。

---

## 6. overlay 当前状态（勿随意改动）

```
E:\GAME\COD\1649370\resources\v1649370\offline-resources\client_shipretail\chinese\
  common_gametype_mp.ff      34,693,397   合法 461          ← 已修正（原 34,783,232 非法）
  mp_cross_fire.ff           37,331,221   真 461            ← 12:03 由另一会话写入
  mp_crash_tropical.ff       32,620,821   真 461
  mp_crash_tropical_load.ff      24,853
  mp_crash_tropical_const.ff     90,389
  其余 18 个 ff 全部 mod 0x2000 = 277（合法）
```

**校验方法**：合法 fastfile 必须 `size mod 0x2000 == 277`。
**备份**：`runs/overlay-backup-20261024-1210/`（含原来的非法 gametype 与 365 补丁版 cross_fire）。

---

## 7. 会话规矩

每轮更新 `1649370-STATUS.md` 与 `PROJECT_STATUS.md` 并本地 git commit；
不要在没拿到截图的情况下声称"进入地图"；不要因困难暂停工作流。
