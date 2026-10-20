"""Record round 27: key-dump switch added; run had no client frames."""
from pathlib import Path

TEXT = """
### 12.45 请求体已捕获，新增密钥转储开关（2026-10-23 06:2x）

#### 请求体本来就有记录

`lsg.jsonl` 的 `client_frame` 事件包含 `body_hex`、`body_len`、`body_sha256`，
所以客户端的加密请求体是可以离线复现的。以一份 130 字节的样本为例：

```
7e000000 ab85 01000000 cf0b57c2 34e7199d 4e525b8a 336825d4 99ce1e1f …
```

`ab85` 是 magic，随后是计数器 1，再往后是加密载荷。要解出 TLV，
必须有当次会话派生的密钥（`LsgKeys` 的 `client_aes`）。

#### 新增 `LSG_DUMP_KEYS`

`server319/lsg_derived.py` 在读取每个客户端帧之前，若 `LSG_DUMP_KEYS=1`
则写一条 `session_keys` 事件，内容为 `LsgKeys` 各字段的十六进制：

```python
if os.environ.get("LSG_DUMP_KEYS") == "1":
    self.evidence.write("session_keys", session, reason="LSG_DUMP_KEYS=1",
                        keys_hex={f.name: getattr(keys, f.name).hex()
                                  for f in dataclasses.fields(keys)
                                  if isinstance(getattr(keys, f.name), (bytes, bytearray))})
```

`LsgKeys` 是 dataclass，字段为 `challenge`、`client_mac`、`server_mac`、
`client_aes`、`server_aes`（用 `dataclasses.fields` 而非 `keys.items()`，
后者在 dataclass 上不存在——这是本轮修掉的一个错误）。

#### 本轮那次运行没有产生任何客户端帧

`runs/20261023-exp-f/lsg.jsonl` 只有 5 条握手事件
（`plaintext_frame`、`gate_reply`、`plaintext_frame2`、`session_derived`、
`token_reply`），**没有 `client_frame`**，即客户端完成握手后没有发 `svc71/task4`。
同目录的 `auth.jsonl` 有正常的 `auth_request` / `auth_response`，
`patch.json` 也有 401 KB 的完整采样记录。

单独前台启动 LSG 服务可以正常监听，`import server319.lsg_derived` 也正常，
说明不是代码错误，而是那次客户端实例的时序问题（握手完成但业务帧未发出）。
前几轮同一配置下 `task4` 都在 6 秒内出现，因此判断为偶发。

#### 下一步

重跑实验 F（三处写入 + `LSG_DUMP_KEYS=1`，等待 60 秒），确认：

1. `client_frame` 是否恢复；
2. `session_keys` 是否写出；
3. 若两者都在，用 `client_aes` 解密 `task3`(141 B) 与 `task7`(389 B) 的
   `body_hex`，解析出客户端究竟在请求什么。

这是目前唯一能把"用错误帧试探"换成"给出真实应答"的路径。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.45"),
                         ("HANDOFF-CURRENT.md", "### 15.33")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.45", "### 15.33")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
