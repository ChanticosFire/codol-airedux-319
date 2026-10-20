"""Record round 41: contract tests added, two real bugs caught."""
from pathlib import Path

TEXT = """
### 12.58 服务端契约测试扩到 40 项；过程中修掉两个真 bug（2026-10-23 13:3x）

#### 新增 `tools/test_contracts.py`（21 项）

覆盖 `lsg_derived` 的每一个应答构造器与 `profile` 的两个编码器：

| 组 | 断言 |
|---|---|
| `candidate_svc71_task4_reply` | 事务号被携带；比条目短（是空成功而非列表） |
| `candidate_svc71_task9_reply` | 以 `make_server_entry` 结尾；长度 = 条目 + 26；端口同时出现在两处 |
| `terminal_unavailable_reply` | **恰好 14 字节**（M3 用它应答 task9 且客户端接受）；编码 `error=14`；事务号在前 |
| `candidate_empty_success_reply` | 携带 task id；不同 task 产生不同字节 |
| `ProfileStore.playerdata_bytes` | 24 字节；字段顺序 level/prestige/gp/cp/ents/flags 与 `bdsvc319` 一致 |
| `ProfileStore.balance_bytes` | 5 字节；首字节是货币号；数值取自 wallet |
| `ProfileStore` 持久化 | 写盘后重载一致；二次 `get_or_create` 复用同一条记录（`created` 不变） |
| `_typed_*` 编解码 | 四个 tag 互不相同；`u64` 9 字节；字符串 NUL 结尾；往返一致 |

#### 抓到的第一个 bug：`task9` 分支会在生产崩溃

`lsg_derived.py` 里改 `LSG_T9_MODE` 时留下了字符串格式化残留：

```python
reason=f"svc71/task9 mode={t9_mode} bytes={len(reply_payload)}; "
       "client consumption unverified"
       % os.environ.get("FINDSESS_PORT", "8466")   # <- 多余的 %
```

`f-string` 之后紧跟一个字面串再套 `%`，Python 会把它解释为对**整个拼接结果**
做格式化，而结果里没有占位符——抛 `TypeError: not all arguments converted`。

**这会让真实运行时任何 `svc71/task9` 请求把 handler 打断。** 由回归测试
（`test_synthetic_raw_handshake_and_candidate_reply`）暴露，已修为纯 f-string。

#### 抓到的第二个 bug（测试自身滞后）

同一测试原本断言 task3/7/9 全部返回 **21 字节空成功帧**，但我把默认改成了
`error14`（14 字节）。测试落后于实现，已更新为：默认 14 字节 + `error=14`，
并在注释里写明 `LSG_UNIMPL_MODE=empty` 仍可回到 21 字节形态。

顺带修正了事件计数：本测试实际有 **4 个**被应答的请求（task4 也算一次），
原断言写 3。

#### 当前离线测试总量

```
python -m unittest tools.test_frames tools.test_contracts server319.test_lsg_derived
Ran 40 tests in 0.037s
OK
```

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `tools/test_frames.py` | 17 | bdMatchMaking 条目与 task9 帧结构 |
| `tools/test_contracts.py` | 21 | 全部应答构造器 + profile 编码器 |
| `server319/test_lsg_derived.py` | 2 | 合成握手全流程（含真实 AES/HMAC） |

#### 意义

这轮是第 37 轮以来第一次**有确定产出**的工作：不依赖客户端、不依赖实机，
40 项断言全部通过，且抓出了两个如果留着会在真实运行时出问题的缺陷
（一个崩溃、一个契约漂移）。

M4 主体仍阻塞于 §9.0 的人工前置，但服务端侧的可靠性因此实质提升。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.58"),
                         ("HANDOFF-CURRENT.md", "### 15.46")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.58", "### 15.46")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
