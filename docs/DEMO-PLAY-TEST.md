# demo 播放实测记录（2026-10-24 12:0x–12:1x）

目的：用 2021-08 真实 demo（`0C-2021-8-26[19-26-24]war.demo`，地图 `mp_crash_tropical`）
把「渲染问题」与「数据问题」永久分开，并为进图链路找到缺失资源。

---

## 1. 已经做到的事（有截图/日志）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 客户端能正常启动到**主菜单/大厅**，UI 完整渲染（不是黑屏） | `runs/demo-run4-t0.png` |
| 2 | `cl_demo_play <demo>` 是**可用命令**：Cbuf 注入成功（stage=5，长度 0→46） | `runs/demo-run4-cbuf.json`、`demo-run5-cbuf.json`、`demo-run6-cbuf.json` |
| 3 | 命令执行后客户端**确实开始加载 demo 的地图资源**，并逐个报缺失文件 | 见 §2 |
| 4 | `mp_crash_tropical*.ff` 三个 461 签名 fastfile 已可从 `ff_init_mp_crash_tropical_V73.ifs` 正确提取并部署 | `docs/IFS-MERGE-RESULT.md` §9.2 |

**结论 1**：demo 播放路径是通的（命令被接受、进入地图加载），不是命令名/参数错误。

## 2. 缺失文件的序列（每次崩溃只报一个，逐个补齐）

| 顺序 | 客户端请求的路径 | 性质 | 解决方式 |
|---:|---|---|---|
| 1 | `images/loadscreen_mp_crash_tropical.iwi` | 地图专属加载画面 | 放入 `runtime/devraw_shared/images/`（来自 `runs/20261022-crash-tropical-loose-v461`） |
| 2 | `images/dpad_ks_uav.iwi` | **MP 通用 UI 图标** | 放入 `devraw_shared/images/`（来自 `runs/20261022-gametype-loose-v461`） |
| 3 | `localized_common_gametype_mp.ff` 的 zone | gametype 本地化 fastfile | 从 `ff_init_common_gametype_mp_V69.ifs` 的**成员 1** 提取（41,237 B，5 块，zone 63,100，892 asset） |

补齐方式（实测有效，3 秒）：

```powershell
# runtime 已装配后，把 5 个 loose 包整体并入 devraw_shared
robocopy runs\20261022-crash-tropical-loose-v461\main <runtime>\devraw_shared /E
robocopy runs\20261022-crossfire-loose-v461\main       <runtime>\devraw_shared /E
robocopy runs\20261022-gametype-loose-v461\main        <runtime>\devraw_shared /E
robocopy runs\20261022-dmz-loose-v461\main             <runtime>\devraw_shared /E
robocopy runs\20261022-survival-loose-v461\main        <runtime>\devraw_shared /E
```

共 3,301 个文件 / 336,823,002 B。

## 3. 同时修复的 overlay 坏件（离线，已复核）

`docs/IFS-MERGE-RESULT.md` §7 指出 overlay 有两个结构非法的 fastfile；本会话已替换并复核：

| 文件 | 旧 | 新 | 检查 |
|---|---|---|---|
| `common_gametype_mp.ff` | 34,783,232（`mod 0x2000 = 0`，结构非法） | **34,693,397**（4235 块，1400 asset） | `check_overlay_ff.py` OK |
| `mp_cross_fire.ff` | 41,648,405（2.6.9.7 365 原件 + 1 字节补丁） | **37,331,221**（4557 块，240 asset） | OK |
| `localized_common_gametype_mp.ff` | 缺失 | **41,237**（5 块，892 asset） | OK |

旧件备份在 `runs/ifs-merge/baseline_*.ff`。overlay 现在 23 个 `.ff` 全部结构合法。

## 4. 待验证（下一次运行）

替换 overlay 后重跑 `cl_demo_play`，观察：

- 是否越过 `WIN_ZONE_ERROR: [localized_common_gametype_mp.ff]`；
- 是否继续报新的缺失文件（若有，按 §2 方式补）；
- 是否出现 `mp_crash_tropical` 的真实对局画面（**唯一验收：截图里出现地图**）。

## 5. 已知干扰

本轮期间有另一个执行体在同一项目里并行跑联机实验（`runs/codex-r242-*`，12:11:25 起，
含自己的客户端 PID 24080）。两个客户端同时运行会争窗口/焦点，
因此 `cl_demo_play` 的最终判定应在其运行结束后进行。
