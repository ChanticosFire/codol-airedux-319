# 私有仓库范围

GitHub：<https://github.com/ChanticosFire/codol-airedux-319>；所有者 `ChanticosFire`，可见性经 GitHub API 核验为 `PRIVATE`。本地根目录为 `E:\GAME\COD\codol-airedux\319`，分支 `main`，远端 `origin` 使用 HTTPS。Git 凭据只由本机 GitHub CLI 管理，不写入仓库。

此仓库保存 Build 1649370 的自有源码、可复核的文件身份清单和阶段交接文档。`runtime/` 是用户客户端的隔离副本，`runs/` 含本机实验后像和截图，`他人文件参考/` 是第三方输入，`codol-ember/` 是另一项目的克隆；四个目录均不纳入本仓库。

不提交游戏二进制、归档、密钥、凭据或第三方资料。`evidence/client-inventory.json` 只保存原始客户端的文件名、大小与摘要及本机输入路径，用于本项目私有复核。未来如需公开成果，应重新审阅文件、去除本机路径和运行数据，并按适用 Build、方法、结果及限制整理。

每个可复用增量先更新 `PROJECT_STATUS.md`、`MILESTONES.md` 和必要的证据，再提交。运行后像保留在本机 `runs/`，在提交说明中引用相对路径和哈希即可。
