# 版本切换记录：1649370 → 3.19.26.17 / Build 1604220

> **状态**：已切换（2026-10-21 20:40 Asia/Shanghai）
> **决定人**：用户
> **影响范围**：工作目标版本、隔离副本、服务端适配方向、文档口径
> **旧版本去向**：Build 1649370 的研究全部保留，转为**参考源**

---

## 1. 为什么切换

用户提供了完整的 **3.19.26.13** 客户端包（实际 `version.xml` 标签为 3.19.26.17），并指出：

> 社区许多研究结论是基于此版本的，应该可以直接复用社区的很多进度快速推进。

这不是放弃 1649370 的成果，而是**换到证据更充分的目标**：社区对该 Build 已有可复现的「大厅渲染 + 关闭 TextField 弹窗」记录，而 1649370 在社区资料里被明确标注为「不是 1604220」，缺少同 Build 验证。

---

## 2. 身份确认（哈希级）

新包 `E:\GAME\COD\3.19.26.13` 的关键文件：

| 文件 | SHA-256 | 大小 |
|---|---|---|
| `codoMP_client_shipRetail.exe` | `3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f` | 7,842,456 |
| `codoMP_client_shipRetailBase.dll` | `7bbc5fb07ebca9b4671ec0e9a953bbd4e1baaca6a9ca29888531c3213e400f64` | 61,137,048 |
| `IIPS/iips.dll` | `72ddb9d15626b5a0a001347da141fb944a9f862db713e01c06a964ec8dc35348` | 347,704 |
| `IIPS/IIPSHostApp.exe` | `b507b47a80caf135ee95006ae1a3ad62777cb3df8aa339ea835117a1b508f0c8` | 290,360 |

**EXE 与 Base DLL 的哈希与下列社区记录逐字节一致**：

- `codol-ember/工具-tools/lobby-reproduction1604220/docs/SUCCESS-SUMMARY.md`（第 58–59 行）
- `codol-ember/工具-tools/launch319-reference/BUNDLE-VALIDATION.json`（`product_version: 3.19.26.13`）

> 注意：社区资料里的「3.19.26.13」是**历史称呼**，该副本 `version.xml` 与 GUI 标签显示 **3.19.26.17**；身份以 **EXE/Base SHA-256** 为准。

**IIPS 两个 DLL 与 1649370 完全相同**——说明 IIPS 层两版一致，已有 IIPS 结论可直接沿用。

---

## 3. 目录与隔离

| 路径 | 作用 | Git |
|---|---|---|
| `E:\GAME\COD\3.19.26.13` | 用户提供的原始包（只读，不在其上试验） | 否 |
| `runtime\client-1604220\` | **当前工作副本**（2173 文件 / 25.86 GB，已排除 DirectX 安装包） | 排除 |
| `runtime\client-1649370\` | 旧工作副本，保留作对照 | 排除 |
| `server319\` | 服务端（当前仍以 1649370 的地址/偏移写成，需按 1604220 重新核对） | 是 |

副本由 `robocopy /E /XD DirectX` 生成；原件不做任何修改。

---

## 4. 工作拆分（切换后）

### 4.1 当前目标：1604220

- 隔离副本：`runtime\client-1604220`
- 参考实现：`codol-ember/工具-tools/lobby-reproduction1604220/`（社区已验证的大厅复现包）
- 参考启动器：`codol-ember/工具-tools/launch319-reference/`（含 `dw_wire.py`、`dw_auth.py`、`lobby_service.py`、`patches319.py`、`orch319.py`）

### 4.2 参考源：1649370

以下成果**继续有效**，但只作为方法论与对照，不直接套用偏移：

- LSG 握手全链路（28B hello → 26B 门控 → 153B 0x82 → 0x83 → 130B 0x85）
- 0x85 的 AES-128-CBC 解密方法（`conn+0x604` 指针 + `[ptr+0x9C]`，IV 在帧内 offset 10）
- `ui_state` 语义：**4 是失败分支**、只有 **5 是成功**
- `bdproto319.py` 的协议算法（HMAC 反序派生、`AB 85` 帧、真 HMAC 尾）
- 协议实现 `他人文件参考/bdsvc319.py` + `bdproto319.py`
- 全部阴性结果清单（见 [HANDSHAKE-STATUS.md](HANDSHAKE-STATUS.md)）

### 4.3 已知缺口

`lobby-reproduction1604220` 的服务端缺两个「外部兼容模块」：

- `wire.py`（帧编解码 + 密钥派生）
- `iips.py`（IIPS 应答）

参考包里存在**同源但接口不同**的实现：

- `launch319-reference/reference/launch/demonware/dw_wire.py`（16 KB）
- `launch319-reference/reference/launch/demonware/dw_auth.py`（18.9 KB）

两者需比对后决定是直接适配，还是按 `lobby.py` 的调用签名重写一层 `wire.py`。

---

## 5. 复验入口

```powershell
cd E:\GAME\COD\codol-airedux\319

# 身份复核（应与第 2 节表格一致）
Get-FileHash runtime\client-1604220\codoMP_client_shipRetail.exe -Algorithm SHA256
Get-FileHash runtime\client-1604220\codoMP_client_shipRetailBase.dll -Algorithm SHA256

# 旧版会话（对照用）
pwsh -NoProfile -File runs\run_hb88.ps1 -RunId 20261022-ref1649370
```

---

## 6. 相关提交

| 提交 | 内容 |
|---|---|
| `4fb69af` | 切换目标版本并确认身份（PROJECT_STATUS §12） |
| `4928583` | `a20_of` 试算扩展到 2430 组（未命中） |
| 本文档所在提交 | 版本切换的正式记录 + README/长程目标同步 |

Git 标签：`checkpoint/1604220-switch-20261021`

---

**最后更新**：2026-10-21
