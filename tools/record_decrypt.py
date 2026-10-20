"""Record round 28: decrypted client frames show task3/7 are crash log uploads."""
from pathlib import Path

TEXT = """
### 12.46 ★★★ 解密客户端请求：`task3`/`task7` 是崩溃日志上报，不是房间请求（2026-10-23 07:0x）

#### 先修掉一个自己造成的 bug

`LSG_DUMP_KEYS` 的第一版把密钥写进 `evidence.write(..., keys_hex=...)`，而
`EvidenceWriter.write` 有字段白名单：

```python
allow = {"body_len", "body_sha256", "reason", "buffered_bytes"}
if set(fields) - allow:
    raise ValueError("evidence field not allowlisted")
```

`keys_hex` 不在白名单，抛出的 `ValueError` **不在** session 的
`except (LsgProtocolError, EOFError, OSError, TimeoutError)` 里，于是整个 handler
崩溃、连接被关闭——客户端因此根本发不出 `svc71/task4`。

这解释了实验 F/G 为什么"握手正常但没有 client_frame"：**是转储代码自己把会话
打断了**，不是客户端时序问题。

修法：改为写 sidecar 文件 `<log>.keys.jsonl`，并用
`try/except Exception` 包住，任何失败都不影响会话。修复后 5 个 client_frame 立即恢复。

#### 解密结果（`tools/decrypt_frames.py`）

用 `LsgKeys.client_aes` 回放 `body_hex`，得到的 TLV 载荷是**纯文本**：

| 帧 | 长度 | 内容 |
|---|---|---|
| #1 | 83 | `nQloP0oCVWR6RDJS` + 一串 `+` + `1C-83-41-CE-8D-EE`（会话/机器标识） |
| #2 | 275 | **`ClientOffline`**`|${TIMESTAMP}|1604220|1234605616436508552|934477427295145000|7|4|11|12|0|…` |
| #3 | 141 | **`UserWarning`**`|${TIMESTAMP_OFFSET(0)}|1604220|…|${CODOID(934477427295145000)}|Add r…` |
| #4 | 389 | **`ClientException`**`|${TIMESTAMP}|1604220|…|${CODOID(…)}||Windows 1…` |
| #5 | 8 | `47 03 09 08 07 00 00 00`（`task9`，空请求） |

#### 这彻底改变了理解

**`svc71/task3` 与 `svc71/task7` 是客户端的日志上报通道**
（`ClientOffline` / `UserWarning` / `ClientException`），**不是房间列表查询**。

含义有三层：

1. **客户端在崩溃过程中上报日志**——`ClientOffline` 说明它已经认为自己掉线了，
   所以这些请求是**结果**而不是**原因**；
2. **不需要为它们构造真实应答**——`error=14` 已经足够（M3 当时也是这么回的），
   它们重试是因为客户端每条日志都会单独发一次，而不是因为应答不被接受；
3. **真正要解决的问题变成了：客户端为什么会进入 `ClientOffline`。**

#### 结论

第 25-26 轮把 `task3/7/9` 的出现当成"客户端开始要数据"是**误判**。
它们只是崩溃前的日志上报。真正的进展是**解密通路打通**——现在可以随时看到
客户端发出的任何请求内容。

#### 下一步

1. **解码帧 #1**（83 字节，`task4` 的请求体）：`nQloP0oCVWR6RDJS` 是会话标识，
   末尾 `1C-83-41-CE-8D-EE` 像是 MAC 地址。这是真正的大厅查询请求，值得细看；
2. **查明 `ClientOffline` 的触发条件**：它是客户端在检测到与 LSG 连接异常时才发
   的，而我们的 LSG 一直正常——所以可能是别的原因（例如 `[lobby+0x1F4]=2` 让
   pump 进入"已完成"分支，而客户端在那条分支上发现数据不一致）。
3. 若确认是 1F4 的副作用，则应放弃强写 2，改用**让 pump 自己成功**的路径。

第 1 条成本最低，先做。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.46"),
                         ("HANDOFF-CURRENT.md", "### 15.34")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.46", "### 15.34")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
