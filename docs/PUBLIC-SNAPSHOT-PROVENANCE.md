# 公开前仓库检查（2026-11-05）

本仓库继续使用原来的 2,844 次历史和 `main` 分支，未改写历史，也没有分立的长期开发仓库。用户确认历史中的 UID 与社区来源二进制可公开；`codol_server/` 属独立社区仓库，未加入本仓。

整理过程中建立的临时快照仓库因当前 GitHub 凭据缺少 `delete_repo` 权限而无法删除；它已经转为私有并归档，且本机临时副本已移除。它不接受后续开发提交。

公开前检查了当前跟踪的 2,610 个文件以及全部可达历史中的 8,899 个小于 20 MB 的 blob；未检测到 GitHub/GitLab token、带账号密码的 HTTP URL 或 OpenSSH 私钥标记。按历史路径名检查只发现用于本地 TLS 的 `runs/20261020-live-derived01/tls/auth.key`，没有 `id_rsa` / `id_ed25519` 或其他 Git/SSH 私钥路径。大于 20 MB 的对象未作全文凭据扫描；上述结果不能解释为全类型安全审计。

`server1649370/gameserver.py` 与 `tools/session_up_1649370.py` 通过 `python -m py_compile`；本轮脱敏 JSON 通过 `python -m json.tool`；所提交的本轮改动通过 `git diff --check`。这些检查不等于对局、背包、比分板、权威射击或赛后流程验收。当前进度和限制见[当前交接](../1649370-HANDOFF-CURRENT.md)与[r825–r830 审计](../evidence/experiments/20261105-r825-r830-reliable-transport-audit.json)。

后续开发只向本仓 `main` 提交、推送。`resources/1649370/local/`、本机活库和 Git/SSH 凭据继续保留在本机；新实验需先看忽略规则，避免重新跟踪大体积运行时或原始账号数据。
