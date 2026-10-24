# IFS「合并规则」反验证结果

日期：2026-10-24（本会话实测）  
工作目录：`E:\GAME\COD\codol-airedux\319`  
分析对象：CODOL Build 1649370，`E:\GAME\COD\使命召唤OL\IIPS\IIPSDownload\` 中 20 个含 `mp_cross_fire` 的 `.ifs`  
基准样本：`E:\GAME\COD\1649370\resources\v1649370\offline-resources\client_shipretail\chinese\mp_cross_fire.ff`（41,648,405 B）  
方式：纯离线只读；未启动游戏；**本轮未修改客户端目录任何文件**（写入只发生在 `runs/` 与 `docs/`）。

本文取代 `docs/GOAL.md` 中「一个可用 `.ff` = `ff_*` + `lf_*` + `lf_hi_*` 拼接」的假设。

---

## 0. 判定（先给结论）

| 问题 | 判定 |
| --- | --- |
| 「一个可用 `.ff` = `ff_*` + `lf_*` (+ `lf_hi_*`) 拼接」 | **不成立**，而且是**数学上不可能**（见 §5.1） |
| 41,648,405 B 能否由这 20 个包拼出 | **不能**。k=1/2/3 穷举，长度恰好相等的组合数 = **0** |
| 真实的包内规则 | **1 个 `IWff` 成员 = 1 个完整签名 fastfile**；`.ifs` 是「清单 + 若干完整 `.ff` 顺序存放」的容器，不存在需要再拼装的碎片流 |
| 41,648,405 B 是什么 | **不是 1649370 的产物**：它是 CODOL **2.6.9.7（fastfile 版本 365）** 的 `mp_cross_fire.ff`，被人工改了 `0x8` 处 **1 个字节**（`0x6D`→`0xCD`，365→461）后放进 1649370 的 overlay |
| 因此「与 41,648,405 逐字节相同」这条验收条件 | **必须撤销**。它要求的是一份外来版本二进制，任何 461 包都不可能复现 |

一句话：**「差 4.28 MB」不是缺了某块资源，而是整个 fastfile 来自另一个游戏版本。**

---

## 1. 关键发现：基准样本的真实身份

`mp_cross_fire.ff` 在本机有 3 组同尺寸副本，逐字节比对（`runs/ifs-merge/baseline_provenance.json`）：

| 副本路径 | 大小 | 版本字 @0x8 | SHA-256 | 与基准差异 |
| --- | ---: | ---: | --- | --- |
| `1649370\resources\…\chinese\mp_cross_fire.ff`（基准） | 41,648,405 | **461** (`cd 01 00 00`) | `2c398b006e0ccf589f8d54eeeb01e434fcfe151caea24a36a36d7a0738cb1cf2` | — |
| `codol-airedux\CODOL-2.6.9.7-Launcher\runtime\game\server2697\runtime-assets\chinese\mp_cross_fire.ff` | 41,648,405 | **365** (`6d 01 00 00`) | `19f5b16fff93c03d5530610b2b5cd8d9bd80832c9fa46218382c3cc8cbcc8807` | **仅 1 字节，@0x8** |
| `codol-airedux\CODOL-2.6.9.7-Launcher\runtime\game\training-resources\mp_cross_fire\decoded\client_shipretail\chinese\mp_cross_fire.ff` | 41,648,405 | **365** | `19f5b16f…`（同上） | **仅 1 字节，@0x8** |
| `E:\GAME\COD\client\resources\v1649370\offline-resources\…\chinese\mp_cross_fire.ff`（备份） | 41,648,405 | 461 | `2c398b00…`（与基准完全相同） | 0 |

```
基准    0x00: 49 57 66 66 30 31 30 30 | cd 01 00 00 | 01 00 00 00 | 00 00 00 00
2.6.9.7 0x00: 49 57 66 66 30 31 30 30 | 6d 01 00 00 | 01 00 00 00 | 00 00 00 00
                                          ↑ 唯一差异（365 → 461）
```

这与仓库既有证据一致：`evidence/experiments/20261022-fastfile-version-patch.json` 记录把 `mp_cross_fire_load.ff` 的 0x8 由 365 改成 461，并把 `mp_cross_fire.ff (41648405)`、`mp_cross_fire_const.ff (49429)` 列为「still 365、待改」；`20261022-ff-version-mismatch.json` 也写明 1649370=461、2.6.9.7=365。本轮实测说明这两件后来也被改了（连 `E:\GAME\COD\client\resources\…` 那份备份都已是 461）。

### 1.1 为什么改 1 个字节能骗过版本检查

`evidence/experiments/20261022-ff-encrypted-structure.json` 与 `他人文件参考/Fastfile校验绕过思路.md` 已说明：版本号在明文前缀里，不在 RSA 签名覆盖区。本轮用项目自带解码器实测复核：

- 基准（0x8 已改成 461）解码 **成功**，`publisher_signature_verified: true`，5084 块，zone 80,628,189 / 239 asset；
- 365 原件用同一 exe 解码 **失败**：`FastfileError: 客户端版本或 RSA 材料指纹不匹配`（461 的材料偏移 `0x6984B0`，365 是 `0x8AE880`）。

也就是说：**只改版本字 → 1649370 的客户端会按 461 的路径接受它，但内容仍是 2.6.9.7 的 zone。** 对「文件能打开、签名也过，但世界起不来」这类现象，这是高度可疑的根因方向。

> 早前一种解释是「客户端现有的是更新/更全的一份构建」。**该解释被上表推翻**：它是来自另一个客户端版本的 365 原件，不是 1649370 的更新版。

---

## 2. `.ifs` 的真实结构（本轮实测）

```
偏移          内容
0x0000        "nifs"
0x0004        u32 = 0xAC  (172 = 头部长度)
0x0008..0xAB  容器头（含若干 20 字节摘要等，未逐一命名）
0x00AC        CRLF 分隔的成员名清单，首行为 "<pack>.lst"
              e.g. "ff_init_mp_cross_fire.lst\r\n"
                   "client_shipRetail/chinese/mp_cross_fire.ff\r\n"
                   "client_shipRetail/chinese/mp_cross_fire_load.ff\r\n"
                   "client_shipRetail/chinese/mp_cross_fire_const.ff\r\n"
清单之后      16 字节 = MD5(该清单原文，即 [0xAC, 首个成员起点−16))   ← 实测 4 个包逐一命中
              (cross_fire: f0de1beb837e04ed87f9851ca34f5209)
+0x166        "IWff0100" = 成员 0（完整签名 fastfile）
成员 0 结束    36,464 字节高熵容器数据（不是 fastfile 的一部分）
              "IWff0100" = 成员 1（_load）
成员 1 结束    32 字节容器数据
              "IWff0100" = 成员 2（_const）
成员 2 结束    50,345 字节容器数据 → EOF
```

要点：

1. **成员就是完整的 fastfile**，长度恒为 `0x115 + N*0x2000`：`0x115`=277 是 21 B 明文前缀 + 256 B RSA 签名；之后每 `0x2000` 块用 AES-192-CTR 加密，块摘要串成 SHA-256 链，文件尾是 zlib 流。
2. 成员之间/末尾的容器数据长度不定（0 … 50,345 B），**块对齐上界不可靠**：`mp_cross_fire_const` 的块对齐上界是 98,581，真实只有 49,429；主件上界 37,363,989，真实 37,331,221。**真实长度只能靠哈希链 + zlib 结束标记确定。**
3. 容器没有内容级摘要（那 16 字节 MD5 覆盖的是名字清单），完整性完全由 fastfile 自身签名与块哈希链保证。
4. `lf_*` / `lf_hi_*` 包里 **`IWff` 出现 0 次**，是纯散文件包（`.iwi` / `.mp3`）。
5. `nifs` 头里的长度字段就是 0xAC=172，与既有认知一致；「内部 fastfile 从第一个 `IWff` 开始」也对，但那只是**成员起点**，不是「待拼接片的起点」。
6. 那 16 字节 MD5 已在 4 个包上逐一验证命中（`ff_init_mp_cross_fire_V70`、`ff_init_mp_crash_tropical_V73`、`ff_init_coop_defense_mp_crash_tropical_V64`、`ff_init_coop_survival_mp_cross_fire_V61`），可用来快速判断「名字清单有没有被改过」，但它**不覆盖成员内容**。

---

## 3. 20 个 `.ifs` 清单

`IWff` 列为真实 `IWff0100` 魔数出现次数；「真实成员大小」为经签名/哈希链验证的长度。

| # | 包名 | 大小 (B) | 清单条目 | `IWff` 偏移 | 真实成员大小 |
| --: | --- | ---: | --: | --- | --- |
| 1 | `ff_init_hp_addon_mp_cross_fire_V4.1.ifs` | 32,818 | 0 | 0xAC | 24,853 |
| 2 | `ff_init_hp_addon_mp_cross_fire_V4.ifs` | 32,818 | 1 | 0x115 | （ver 460，未验签） |
| 3–6 | `lf_init_mp_cross_fire_V10.1/.2/.3/.4.ifs` | 98,422 ×4 | 0 | — | 无（散文件） |
| 7 | `ff_init_sdp_addon_mp_cross_fire_V4.1.ifs` | 131,224 | 0 | 0xAC | 114,965 |
| 8 | `ff_init_sdp_addon_mp_cross_fire_V4.2.ifs` | 131,224 | 0 | 0xAC | 123,157 |
| 9 | `ff_init_sdp_addon_mp_cross_fire_V4.ifs` | 131,224 | 1 | 0x117 | （ver 460，未验签） |
| 10–13 | `lf_hi_init_mp_cross_fire_V6.1/.2/.3/.4.ifs` | 344,437 ×4 | 0 | — | 无（散文件） |
| 14 | `lf_init_coop_survival_mp_cross_fire_V4.ifs` | 1,771,324 | 1 | — | 无（散文件） |
| 15 | `ff_init_coop_survival_mp_cross_fire_V61.ifs` | 2,115,745 | 3 | 0x19E / 0x1F6A93 / 0x1FCBC8 | 2,056,469 / 24,853 / 24,853 |
| 16 | `ff_dlc19_clash_addon_mp_cross_fire_V29.ifs` | 2,410,963 | 1 | 0x11C | 2,392,341 |
| 17 | `ff_dlc19_zsurv_addon_mp_cross_fire_V29.ifs` | 8,856,556 | 1 | 0x11C | 8,823,061 |
| 18 | `lf_init_mp_cross_fire_V10.ifs` | 22,764,604 | 114 | — | 无（散文件） |
| 19 | **`ff_init_mp_cross_fire_V70.ifs`** | **37,492,702** | 3 | **0x166 / 0x23A30EB / 0x23A9220** | **37,331,221 / 24,853 / 49,429** |
| 20 | `lf_hi_init_mp_cross_fire_V6.ifs` | 59,027,215 | 111 | — | 无（散文件） |

补充：

- 第 2/9 行是基础增量包，版本字 **460**（`IWff0100 cc 01 00 00`），现有解码器只支持 334/365/461，故记为未验签；不影响结论（它们既不是 461 主件，也不参与拼接）。
- 多组包内容完全重复（同 SHA-256）：`lf_init_mp_cross_fire_V10.1`=`V10.3`、`V10.2`=`V10.4`、`lf_hi_init_mp_cross_fire_V6.1`=`V6.3`、`V6.2`=`V6.4`。**去重不改变结论。**
- `ff_dlc19_clash_addon_*` / `ff_dlc19_zsurv_addon_*` 的成员是 `clash_addon_mp_cross_fire.ff` / `zsurv_addon_mp_cross_fire.ff`，是**独立附加 zone**，不是地图主 zone 的碎片。

---

## 4. 成员块表

全部 461 成员的块内前 16 字节都是：

```
49 57 66 66 30 31 30 30 cd 01 00 00 01 00 00 00   IWff0100 + 461 + 1
```

每个成员前 64 字节的 hexdump 见 `runs/ifs-merge/probe.log` 的 `[2]` 段。**与基准的前 16 字节一致没有区分力**：0x15 起是 RSA 签名，天然每个文件都不同。

| 包 | # | 成员 | 起始 | naive 跨度 | 块对齐上界 | **真实大小** | 块数（头+表+数据） | zone | asset |
| --- | --: | --- | ---: | ---: | ---: | ---: | --- | ---: | --: |
| `ff_init_mp_cross_fire_V70` | 0 | `mp_cross_fire.ff` | 0x166 | 37,367,685 | 37,363,989 | **37,331,221** | 4557 = 1+18+4538 | 75,189,466 | 240 |
| 同上 | 1 | `mp_cross_fire_load.ff` | 0x23A30EB | 24,885 | 24,853 | **24,853** | 3 = 1+1+1 | 2,217 | 6 |
| 同上 | 2 | `mp_cross_fire_const.ff` | 0x23A9220 | 99,774 | 98,581 | **49,429** | 6 = 1+1+4 | 43,400 | 13 |
| `ff_init_coop_survival_…_V61` | 0 | `coop_survival_mp_cross_fire.ff` | 0x19E | 2,058,485 | 2,056,469 | **2,056,469** | 251 | 3,717,828 | 56 |
| 同上 | 1 | `…_load.ff` | 0x1F6A93 | 24,885 | 24,853 | **24,853** | 3 | 2,008 | 5 |
| 同上 | 2 | `…_const.ff` | 0x1FCBC8 | 31,961 | 24,853 | **24,853** | 3 | 3,174 | 2 |
| `ff_dlc19_clash_addon_…_V29` | 0 | `clash_addon_mp_cross_fire.ff` | 0x11C | 2,410,679 | 2,408,725 | **2,392,341** | 292 | 5,981,870 | 10 |
| `ff_dlc19_zsurv_addon_…_V29` | 0 | `zsurv_addon_mp_cross_fire.ff` | 0x11C | 8,856,272 | 8,855,829 | **8,823,061** | 1077 | 13,610,846 | 129 |
| `ff_init_sdp_addon_…_V4.1` | 0 | （无清单） | 0xAC | 131,052 | 123,157 | **114,965** | 14 | 294,965 | 7 |
| `ff_init_sdp_addon_…_V4.2` | 0 | （无清单） | 0xAC | 131,052 | 123,157 | **123,157** | 15 | 306,485 | 7 |
| `ff_init_hp_addon_…_V4.1` | 0 | （无清单） | 0xAC | 32,646 | 24,853 | **24,853** | 3 | 43,915 | 9 |

「naive 跨度」= 该 `IWff` 到**下一个 `IWff`**（无下一个则到文件尾）的字节数，即此前「初步提取」的口径；它与真实大小之差就是容器的成员尾部数据（cross_fire 主件为 36,464 B）。

---

## 5. 拼接尝试与结果

`runs/ifs-merge/combos.json`。对比方式：与基准做流式逐字节比较，记录长度差、前 16 字节是否一致、**第一个不同字节**、按 4096 步长取 64 字节窗口的相同率。

| # | 组合 | 总长 (B) | Δ vs 41,648,405 | 头部 16B 一致 | 第一个不同 | 采样相同率 |
| --: | --- | ---: | ---: | --- | ---: | --- |
| 1 | 单成员：`mp_cross_fire.ff`（真实长度） | 37,331,221 | −4,317,184 | 是 | 0x15 | 0/9114 |
| 2 | 单成员：`mp_cross_fire_load.ff` | 24,853 | −41,623,552 | 是 | 0x15 | 0/6 |
| 3 | 单成员：`mp_cross_fire_const.ff` | 49,429 | −41,598,976 | 是 | 0x15 | 0/12 |
| 4 | **naive 跨度：首 IWff→次 IWff**（此前口径） | 37,367,685 | **−4,280,720** | 是 | 0x15 | **0/9122** |
| 5 | 2 块：主件 + load | 37,356,074 | −4,292,331 | 是 | 0x15 | 0/9120 |
| 6 | 2 块：load + 主件（反序） | 37,356,074 | −4,292,331 | 是 | 0x15 | 0/9120 |
| 7 | 2 块：主件 + const | 37,380,650 | −4,267,755 | 是 | 0x15 | 0/9126 |
| 8 | 3 块：主件 + load + const | 37,405,503 | −4,242,902 | 是 | 0x15 | 0/9132 |
| 9 | ff 主件 + `lf_init` 载荷 | 60,095,632 | +18,447,227 | 是 | 0x15 | 0/10168 |
| 10 | `lf_init` 载荷 + ff 主件 | 60,095,632 | +18,447,227 | 否（0x0） | 0x0 | 0/10168 |
| 11 | `lf_init` 载荷 + `lf_hi_init` 载荷 | 81,791,430 | +40,143,025 | 否（0x0） | 0x0 | 0/10168 |
| 12 | ff 主件 + `lf_init` + `lf_hi_init` | 119,122,651 | +77,474,246 | 是 | 0x15 | 0/10168 |
| 13 | ff 主件 + `lf_hi_init` | 96,358,240 | +54,709,835 | 是 | 0x15 | 0/10168 |
| 14 | 整个 `ff_init_mp_cross_fire_V70.ifs` | 37,492,702 | −4,155,703 | 否（0x0） | 0x0 | 0/9153 |

穷举（成员池 = 11 个已验签成员）：

| k | 长度恰好等于 41,648,405 的组合数 |
| --: | --: |
| 1 | **0** |
| 2 | **0** |
| 3 | **0** |

### 5.1 为什么拼接在数学上不可能

每个合法成员满足 `L_i = 0x115 + n_i·0x2000`。k 个成员拼接：

```
ΣL_i = k·0x115 + (Σn_i)·0x2000   ⇒   ΣL_i mod 0x2000 = (277k) mod 8192
```

而合法签名 fastfile 必须 `L mod 0x2000 = 277`，于是

```
277k ≡ 277 (mod 8192)  ⇔  277(k−1) ≡ 0 (mod 8192)  ⇔  k ≡ 1 (mod 8192)
```

（277 为奇数，与 8192 互素，解唯一。）即 **k = 2、3、…、8192 全部非法**，只有 k=1 或 k≥8193 才可能。这条不变量与内容无关：**任何「两块/三块拼接」方案在结构上就被排除**，无论排序、去重还是取子区间。

---

## 6. 差异分析：为什么是 0/9122，为什么「差 4.28 MB」

| 指标 | 基准 41,648,405 | IFS 提取 37,331,221 |
| --- | --- | --- |
| 大小形式 | `0x115 + 5084·0x2000` | `0x115 + 4557·0x2000` |
| 块数（头 / 哈希表 / 数据） | 5084 = 1 + 20 + 5063 | 4557 = 1 + 18 + 4538 |
| 版本字 @0x8 | 461（**由 365 改来**） | 461（原生） |
| 发行方签名 | 有效 | 有效 |
| 解出的 zone 大小 | **80,628,189**（sha256 `c1f5c146…b5f1b030`） | **75,189,466** |
| asset 数 | **239** | **240** |
| string 数 | 311 | — |

- 两者都是**合法、签名有效**的 fastfile，但不是同一份东西：zone 相差 5,438,723 B，asset 数差 1，块数差 527。**527 × 8192 = 4,317,184**，正是两者大小之差。「差的 4.28 MB」= **527 个加密数据块**，属于不同构建的 zone 内容差异，而不是「少了某个包」。
- 首个不同字节在 **0x15**：前 21 字节是明文前缀（`IWff0100` + 版本 + 标志 + 保留），同版本 ff 必然相同；0x15 起是 RSA 签名，天然不同。
- 按 4096 步长采样 0/9122 相同：每块都用 AES-CTR（IV 来自该块 SHA-256）加密，**密钥流逐块不同**，换版本后连「相同明文块」也会变成不同密文。该指标只在「同一文件」时才会全中。

### 6.1 此前观测口径的两个偏差

| 项目 | 数值 | 说明 |
| --- | ---: | --- |
| 此前「提取出」的长度 | 37,367,685 | = 真实成员 37,331,221 + **36,464 B 容器尾部数据**（不是 fastfile） |
| 它与基准的差 | 4,280,720 | 其中 36,464 是口径误差，4,244,256 是真实版本差异 |
| 真实成员与基准的差 | **4,317,184** | = 527 块 |

---

## 7. 附带发现：overlay 里还有一个「结构性非法」fastfile

用同一套结构检查逐个扫 `1649370\resources\v1649370\offline-resources\client_shipretail\chinese\*.ff`（23 个），22 个通过，**1 个失败**：

```
FAIL  common_gametype_mp.ff   34,783,232   outer_header: 签名块边界或文件长度不合法
```

- `34,783,232 mod 0x2000 = 0`，而合法签名 ff 必须 ≡ 277 → 它**不可能是任何版本的合法签名 fastfile**（比上一个合法长度 34,775,317 多 7,915 B，比下一个 34,783,509 少 277 B）。
- 仓库里 `runs/20261022-gametype-ff-v461/common_gametype_mp.ff` 才是从 `ff_init_common_gametype_mp_V69.ifs` 正确提取的 461 版本：**34,693,397 B**，签名有效，4235 块，zone 49,877,939，**1400 asset**（SHA-256 `13e7ec15…`，与 `1649370-RESOURCE-HANDOFF-20261022.md` 一致）。两者相差 89,835 B，**不是同一个文件**。
- 也就是说 overlay 里既有「外来版本」的 `mp_cross_fire.ff`（365 + 1 字节补丁），也有「结构非法」的 `common_gametype_mp.ff`。后者恰是 MP 公共 zone，客户端读到它几乎必然在 zone 装载阶段失败，与「`preloadmap` 后黑屏转圈 / `WIN_ZONE_ERROR`」的旧观测方向一致，**建议优先替换验证**。

复扫命令：`python runs/ifs-merge/check_overlay_ff.py`。

---

## 8. 复现方法

```powershell
# 在 E:\GAME\COD\codol-airedux\319 下
python runs/ifs_merge_probe.py                 # cross_fire 全量：清单/成员/验签/拼接/溯源
python runs/ifs_merge_probe.py --no-verify     # 只做结构分析（不解密，秒级）
python runs/ifs_merge_probe.py --map mp_crash_tropical --out runs/ifs-merge/crash-tropical
python runs/ifs-merge/check_overlay_ff.py      # 扫 overlay 里每个 ff 的结构合法性

# 等价的既有提取器（另一路会话用它产出 extracted/）
python runs/ifs-merge/extract_members.py --out runs/ifs-merge/extracted
```

产物：

| 文件 | 内容 |
| --- | --- |
| `runs/ifs_merge_probe.py` | 可重复运行的探针（本报告全部数据由它生成） |
| `runs/ifs-merge/inventory.json` | 20 个包的头部/清单/成员表 + 长度穷举结果 |
| `runs/ifs-merge/members.json` | 每个成员的偏移、块大小、前 64 字节 |
| `runs/ifs-merge/combos.json` | 14 组拼接对比 + k=1/2/3 穷举 |
| `runs/ifs-merge/baseline_provenance.json` | 基准与孪生副本的差异、解码结论 |
| `runs/ifs-merge/probe.log` | 全过程日志（含每个成员前 64 B hexdump） |
| `runs/ifs-merge/crash-tropical/` | 同一脚本对 `mp_crash_tropical` 37 个包的结果 |
| `runs/ifs-merge/check_overlay_ff.py` | overlay 22 个 ff 的结构检查 |
| `runs/ifs-merge/extracted/` | 正确提取出的 6 个 `.ff`（cross_fire 3 + crash_tropical 3） |

---

## 9. 下一步（可执行）

### 9.1 先修 overlay 里的两个坏件

1. `common_gametype_mp.ff`：用 `runs/20261022-gametype-ff-v461/common_gametype_mp.ff`（34,693,397 B，`13e7ec15…`，1400 asset）替换 34,783,232 B 的那份 —— 这是本轮发现的**唯一结构非法文件**，且正好是 MP 公共 zone。
2. `mp_cross_fire.ff`：如要用 1649370 本体内容，用 `runs/ifs-merge/extracted/mp_cross_fire.ff`（37,331,221 B，`45b964b1…`，240 asset，签名有效）替换 41,648,405 B 的 365 补丁件；后者只保留作「365 对照」。
3. 替换后用 `check_overlay_ff.py` 复核 **23/23 结构合法**，再做「只准备不启动」的构建。

> 注：`mp_crash_tropical*.ff` 三个文件已由另一路会话于 2026-10-24 12:03 部署到上述 overlay 目录（`32,620,821 / 24,853 / 90,389`，本轮结构检查全部通过）。本轮未向该目录写入任何内容。

### 9.2 `mp_crash_tropical`（同一规则，已实测跑通）

`lf_*` / `lf_hi_*` 全部丢掉（不含 fastfile）。只需 `ff_init_mp_crash_tropical_V73.ifs`：

| 成员 | 包内偏移 | 真实大小 | 块数 | zone | asset |
| --- | ---: | ---: | --- | ---: | --: |
| `mp_crash_tropical.ff` | 0x176 | **32,620,821** | 3982 | 66,603,647 | 381 |
| `mp_crash_tropical_load.ff` | 0x1F23F0B | 24,853 | 3 | 2,258 | 6 |
| `mp_crash_tropical_const.ff` | 0x1F2A040 | 90,389 | 11 | 100,407 | 17 |

```powershell
python tools/extract_signed_ifs_fastfiles_1649370.py `
  "E:\GAME\COD\使命召唤OL\IIPS\IIPSDownload\ff_init_mp_crash_tropical_V73.ifs" `
  --out runs/20261024-crash-tropical-ff-v461
```

预期产出与上表一致（本轮已用探针独立复算：`runs/ifs-merge/crash-tropical/inventory.json`，37 个包、全部 `lf_*` 的 `IWff` 计数为 0）。注意 `ff_init_coop_defense_mp_crash_tropical_V64.ifs` 的主 zone 是另一张图（42,959,125 B，555 asset），**不要**与 `mp_crash_tropical.ff` 混用；`ff_dlc19_*` 同理是附加 zone。

### 9.3 验收条件要改

原判定「能与 41,648,405 逐字节相同 = 规则成立」应替换为三条可自动检查的条件：

1. `size ≡ 0x115 (mod 0x2000)`；
2. `publisher_signature_verified == true`，且全部块 SHA-256 链、zlib EOF、Adler32 通过；
3. zone 目录自洽（`directory_coverage_verified`）且 asset 数符合预期（cross_fire 240、crash_tropical 381、gametype 1400）。

### 9.4 如果仍想追「41,648,405 的原始来源」

它来自 **2.6.9.7 客户端**，不是 1649370 的 IIPS。要找「原包」应去 2.6.9.7 的 IIPS / decoded-resources，而不是在 1649370 的 975 个 `.ifs` 里找；本机 3 组副本都已是 365 原件或其 461 补丁版。**即使找到原包，其 zone 内容与 1649370 也不同源，不能作为 1649370 的验收基准。**

---

## 10. 证据边界

- 全部结论来自本机只读字节分析与项目自带解码器（`1649370/src/codol_rebuild/resources/fastfile.py`：客户端 RSA 材料 + AES-192-CTR + 块哈希链）。未启动游戏、未联网、**本轮未写入任何客户端目录**。
- 「基准来自 2.6.9.7」的依据：3 组同尺寸副本中 2 组版本字为 365 且位于 `CODOL-2.6.9.7-Launcher` 的 runtime 目录，与基准**仅差 0x8 一个字节**；且仓库既有证据已记录该 365→461 人工补丁。这只证明「基准 = 365 原件 + 1 字节补丁」，不额外推断补丁动机。
- 版本字 460 的 4 个基础增量包现有解码器不支持，只做结构统计、未验签；不影响任何结论。
- 拼接表中的「lf 载荷」指该 `.ifs` 从名字清单到文件尾的字节段（这类包没有 `IWff`，只能这样取），用于验证「把 lf 当成分片」的假设；结果自然全不匹配。
