"""1649370 传输通道层静态审计（只读，可复跑）。

回答 G2 的核心问题：为什么连接路径的 UDP 发送以索引 0x9D 查询通道表
0xE3F4DB0 失败并返回 -7（EXE_HOSTUNREACH），以及通道由谁创建。

审计内容（全部来自对精确离线镜像的 Capstone 反汇编，无任何运行进程）：
  1. 发送包装器 0x622040 的完整语义（索引来源 adr+0x14、越界 -7、表项结构）；
  2. StringToAdr 0x675390：localhost -> {type=2, channel=0x9D}；非 localhost 不写通道字段；
  3. 0x7F5DD0：索引==0x9D 直接返回成功（loopback 无需发送）；
  4. 通道表管理簇：0x7F5060/0x7F50E0/0x7F5330/0x7F54A0/0x7F5E40；
  5. 通道创建者 0x621E50（manager 单例 0x643300 -> 0xbac600，vtable+0x2c 建通道，
     0x7F5330 入表并回填 adr：type=4、adr+0x14=索引）及其全部调用者（网络泵）；
  6. 进程内 loopback 收发环（0x6750A0 写 / 0x674F30、0x675140 读）；
  7. OOB wire 串区（getchallenge/connect/challengeResponse/connectResponse）。

用法：
  python tools/audit_transport_channels_1649370.py [--out evidence/experiments/xxx.json]

不启动客户端/服务端/guard；不改任何文件；输出只写 --out 指定的 JSON。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
EXPECT_SHA256 = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"

IMAGE_BASE = 0x400000
TEXT_VA, TEXT_SIZE, TEXT_RAW = 0x401000, 0x8A689A, 0x1000
RDATA_VA, RDATA_RAW = 0xCA8000, 0x8A8000

CHANNEL_TABLE = 0xE3F4DB0      # 157 项 x 0x18：{+0 对象指针, +4 序号, +8 in_use, +0x10 最后发送时间}
ENTRY_157 = 0xE3F5C68          # 表尾之后第一个 0x18 对齐块（0x9D 槽位地址，被多处引用）
LOOPBACK_MARKER = 0x9D

SEND_WRAPPER = 0x622040
SEND_THIN = 0x77FB80           # (sock, adr0x18, buf, len, ...) -> 0x622040
SEND_DISPATCH = 0x6751F0       # 按 adr->type 分派：2=进程内 0x6750A0，否则 0x77FB80
LOOPBACK_SEND = 0x6750A0
LOOPBACK_GET = 0x675140
LOOPBACK_GET_A = 0x674F30
STRING_TO_ADR = 0x675390
TRANSPORT_RESOLVE_SEND = 0x621E50  # 取/建通道 + 加密发送 + 回填 adr
MANAGER_SINGLETON = 0x643300       # [0xE85C68] 为空则分配 0x4D78 并构造 0xBAD1A0
MANAGER_GETTER = 0xBAC600          # [ecx+0x1F0]
TABLE_INSERT = 0x7F5330
TABLE_DESTROY_ONE = 0x7F5060
TABLE_TEARDOWN_ALL = 0x7F50E0
TABLE_LOOKUP_SP = 0x7F54A0
SMARTPTR_ASSIGN = 0x7F5E40
NOSEND_GUARD = 0x7F5DD0            # idx==0x9D -> true

STR_LOCALHOST = 0xDBE518
STR_OOB_GETCHALLENGE = 0xDBFD04    # 'getchallenge 0 "%s"'
STR_OOB_CONNECT = 0xDBFE28         # 'connect %s "%s"'
STR_OOB_CHALLENGE_RESP = 0xDBFEE8
STR_OOB_CONNECT_RESP = 0xDBFF0C
STR_OOB_CONNECT_REJECT = 0xDBFEFC
STR_FMT_I_U = 0xDBFD54             # '%i %u'（connect userinfo 的 challenge/checksum 组装）
STR_DEFAULT_PORT = 0x7531          # 30001，StringToAdr 无端口参数时的默认值


def read_image() -> bytes:
    data = open(EXE, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != EXPECT_SHA256:
        raise SystemExit(f"EXE 指纹不符：{sha} != {EXPECT_SHA256}")
    return data


def va2off(va: int) -> int:
    rva = va - IMAGE_BASE
    if TEXT_VA <= va < TEXT_VA + TEXT_SIZE:
        return TEXT_RAW + (rva - 0x1000)
    if RDATA_VA <= va < RDATA_VA + 0x16DA70:
        return RDATA_RAW + (rva - 0x6A8000)
    raise KeyError(va)


def cstr(data: bytes, va: int, maxlen: int = 96) -> str:
    off = va2off(va)
    return data[off:off + maxlen].split(b"\0")[0].decode("ascii", "replace")


def disasm(data: bytes, va: int, size: int):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    off = va2off(va)
    return list(md.disasm(data[off:off + size], va))


def find_callers(text: bytes, target: int):
    hits = []
    for off in range(len(text) - 5):
        if text[off] == 0xE8:
            rel = struct.unpack_from("<i", text, off + 1)[0]
            if TEXT_VA + off + 5 + rel == target:
                hits.append(TEXT_VA + off)
    return hits


def find_imm32_refs(text: bytes, lo: int, hi: int):
    hits = []
    for off in range(len(text) - 4):
        v = struct.unpack_from("<I", text, off)[0]
        if lo <= v <= hi:
            hits.append((TEXT_VA + off, v))
    return hits


def audit(data: bytes) -> dict:
    text = data[TEXT_RAW:TEXT_RAW + TEXT_SIZE]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    out: dict = {"schema": 1, "exe_sha256": EXPECT_SHA256, "findings": {}}

    # --- 1. 发送包装器 0x622040：索引来自 adr+0x14（栈参数 [ebp+0x24]） ---
    ins = {i.address: i for i in disasm(data, SEND_WRAPPER, 0x80)}
    idx_src = ins[0x62205E]
    guard_cmp = ins[0x6220BA]
    out["findings"]["send_wrapper"] = {
        "address": hex(SEND_WRAPPER),
        "index_source": f"{idx_src.mnemonic} {idx_src.op_str}  # adr+0x14 = 第6个dword",
        "range_guard": f"{guard_cmp.mnemonic} {guard_cmp.op_str}  # idx>=0x9D 越界",
        "table_base": hex(CHANNEL_TABLE),
        "entry_size": "0x18",
        "entries": "157 (idx 0..0x9C)",
        "return_code_bad_index": "-7 (0xFFFFFFF7)",
        "entry_layout": {
            "+0x00": "channel 对象指针（refcount 智能指针，对象+0x14 携带自身索引）",
            "+0x04": "递增序号（全局计数器 0x84ABA88）",
            "+0x08": "in_use 标志",
            "+0x10": "最后成功发送时间戳（发送成功后写入）",
        },
        "actual_send": "channel 对象虚表 +0x24 校验类型==2，+0x28 执行发送（socket 在对象内）",
    }

    # --- 2. StringToAdr 0x675390：localhost 分支写 {type=2, channel=0x9D} ---
    ins2 = {i.address: i for i in disasm(data, 0x6753D9, 0x20)}
    out["findings"]["string_to_adr"] = {
        "address": hex(STRING_TO_ADR),
        "localhost_marker": f"{cstr(data, STR_LOCALHOST)!r} @ {hex(STR_LOCALHOST)}",
        "localhost_result": {
            "type": "2 (NA_LOOPBACK)",
            "ip": "0.0.0.0",
            "port": "htons(端口参数) 或默认 htons(30001)（0x7531）",
            "channel+0x14": f"{hex(LOOPBACK_MARKER)}  # {ins2[0x6753EB].mnemonic} {ins2[0x6753EB].op_str}",
        },
        "ip_result": {
            "type": "4 (NA_IP) 经 127.x 本机地址重写分支",
            "channel+0x14": "从不写入（残留调用方内存）——连接路径必须另行建通道",
        },
    }

    # --- 3. 0x7F5DD0：idx==0x9D 直接返回 true ---
    ins3 = {i.address: i for i in disasm(data, NOSEND_GUARD, 0x10)}
    out["findings"]["no_send_guard"] = {
        "address": hex(NOSEND_GUARD),
        "semantic": "adr.channel==0x9D => 无需发送（loopback 语义），直接返回 true",
        "insn": f"{ins3[0x7F5DD6].mnemonic} {ins3[0x7F5DD6].op_str}",
        "sends_via": "0x622040（buf 0x18 字节、'<3' 串 0xDA16C0、type 2 参数）",
    }

    # --- 4. 管理簇与插入函数 ---
    out["findings"]["table_management"] = {
        "destroy_one": hex(TABLE_DESTROY_ONE),
        "teardown_all": hex(TABLE_TEARDOWN_ALL),
        "insert_lru": hex(TABLE_INSERT),
        "lookup_smartptr": hex(TABLE_LOOKUP_SP),
        "smartptr_assign": hex(SMARTPTR_ASSIGN),
        "insert_semantics": (
            "0x7F5330(对象智能指针, out 索引, out 成功bool)：扫 157 项找空槽；"
            "无空槽则选 +0x14 时间戳最旧且 in_use 的 LRU 项用 0x7F5060 逐出；"
            "写入 [项+4]=++0x84ABA88 序号、[项+0x14]=0xA，回填索引"
        ),
        "entry157_addr": hex(ENTRY_157),
        "entry157_refs": "表尾紧邻块被 7 处引用（0x68D318/0x68D566/0x7F910A/0x7F917A/0x7F91F7/"
                         "0xC958A1/0xC95923/0xCA6D6A），属于 0x18 对齐的后续全局区，非发送通道",
    }

    # --- 5. 通道创建者 0x621E50 ---
    callers = find_callers(text, TRANSPORT_RESOLVE_SEND)
    ins5 = {i.address: i for i in disasm(data, TRANSPORT_RESOLVE_SEND, 0x60)}
    out["findings"]["channel_creator"] = {
        "address": hex(TRANSPORT_RESOLVE_SEND),
        "callers": [hex(c) for c in callers],
        "caller_context": "0x4F8D70 / 0x4F8FB0：网络泵循环（状态机 [0x84ABA50]<=5 跳表 0x4F9158）",
        "signature": "int 0x621E50(adr /*inout 0x18 字节*/, buf, len)",
        "flow": [
            f"manager = {hex(MANAGER_GETTER)}({hex(MANAGER_SINGLETON)}())  # [0xE85C68] 单例, [mgr+0x1F0]",
            "if (manager->vt+0x20() != 1) return -7;   # 传输未就绪，返回码与 EXE_HOSTUNREACH 同源",
            "rc = manager->vt+0x2c(&channel_sp, buf, len);   # 创建/取回 peer 通道",
            "if (rc==4 && buf[2..3]=='<''3') return 0;      # 心跳包：不入表不发送",
            f"ok = {hex(TABLE_INSERT)}(channel_sp, &idx, &flag);   # 入路由表得 idx",
            "加密/格式化后发送；成功回填 adr：[adr+0]=4(NA_IP)、[adr+8]=端口、[adr+0x14]=idx",
        ],
        "conclusion": "连接路径（getchallenge/connect OOB）从不经过此函数，因此通道表对连接地址永远为空",
    }

    # --- 6. loopback 环 ---
    out["findings"]["loopback_rings"] = {
        "writer": hex(LOOPBACK_SEND),
        "readers": [hex(LOOPBACK_GET_A), hex(LOOPBACK_GET)],
        "ring_A": {"base": "0x7872C08", "stride": "0x4F0", "slots": 64,
                   "cursors": ["[0x7886808] read", "[0x788680C] write"]},
        "ring_B": {"base": "0x7867768", "stride": "0x62C8", "slots": 16,
                   "cursors": ["[0x7872C00] read", "[0x7872C04] write"],
                   "note": f"数据区 {hex(0x786DBC0)}，{hex(LOOPBACK_GET)} 唯一消费者，被网络泵 0x4F8D70 调用"},
        "packet_layout": "adr(0x18) + len(4) + data(<=0x4E6)",
        "bridge_note": "包装层可从环读包转发到真实 UDP 服务端并把应答写回环（不动 EXE 的备选路线）",
    }

    # --- 7. OOB wire 串 ---
    out["findings"]["oob_wire_strings"] = {
        "client_getchallenge": [cstr(data, STR_OOB_GETCHALLENGE), hex(STR_OOB_GETCHALLENGE)],
        "client_connect": [cstr(data, STR_OOB_CONNECT), hex(STR_OOB_CONNECT)],
        "client_parses": {
            "challengeResponse": hex(STR_OOB_CHALLENGE_RESP),
            "connectResponse": hex(STR_OOB_CONNECT_RESP),
            "connectReject": hex(STR_OOB_CONNECT_REJECT),
        },
        "userinfo_keys": ["challenge", "checksum", "clantag", "xuid", "natType", "2490",
                          "statver", "session", "partyid", "qport(via %i %u)"],
        "challenge_response_parse": (
            "0x5C1678：匹配 challengeResponse 后 push 3; call 0x5C1300（连接状态->3），"
            "把应答方 adr 6 dwords 存入新连接对象 +0x14..+0x28 并 call 0x5BE030；"
            "未发现对 challenge 数值的二次校验，2697 只回一个 int 兼容"
        ),
        "server_2697": {
            "getchallenge": "忽略参数，回 \\xff\\xff\\xff\\xffchallengeResponse <NET_CookieHash(from)>",
            "connect": "argv1 必须 16 位 hex xuid；argv2 必须 \\ 开头 info 串、含匹配 xuid 键；"
                       "challenge 取 userinfo[challenge] 并校验；随后 lobby admission 可拒绝"
                       "（EXE_ERR_NOT_AUTHORIZED）；connectResponse 含 \\protocol\\1\\shortversion\\1.1.1.13",
            "source_ref": "319/runs/2697-native-src/src/sv_client.c SV_GetChallenge/SV_DirectConnect, "
                          "src/codol/net/codol_connect.c",
        },
        "open_questions": [
            "connect 第一个 %s 的确切内容（xuid 还是 challenge）需运行时捕获确认",
            "2697 的 lobby admission 是否可经配置关闭",
        ],
    }

    # --- 8. 全局引用清单（证据可核对） ---
    imm_refs = find_imm32_refs(text, CHANNEL_TABLE, CHANNEL_TABLE + 0xEB8)
    out["findings"]["table_imm32_refs"] = [
        {"va": hex(va), "target": hex(t),
         "entry": hex((t - CHANNEL_TABLE) // 0x18) if t >= CHANNEL_TABLE else "?"}
        for va, t in imm_refs
    ]
    for name, tgt in (("send_wrapper", SEND_WRAPPER), ("transport_resolve_send", TRANSPORT_RESOLVE_SEND),
                      ("table_insert", TABLE_INSERT), ("no_send_guard", NOSEND_GUARD),
                      ("string_to_adr", STRING_TO_ADR), ("send_dispatch", SEND_DISPATCH)):
        out["findings"].setdefault("callers", {})[name] = [hex(c) for c in find_callers(text, tgt)]

    # --- 9. 关键指令序列核对（防止后续镜像漂移导致结论失效） ---
    checks = {
        "string_to_adr_writes_9d": data[va2off(0x6753EB):va2off(0x6753EB) + 10].hex() == "c74614" + "9d000000"[:6] + "00" or
                                    struct.unpack_from("<I", data, va2off(0x6753EB) + 3)[0] == LOOPBACK_MARKER,
        "guard_cmps_9d": ins3[0x7F5DD6].op_str.endswith("0x9d"),
        "wrapper_cmps_9d": guard_cmp.op_str.endswith("0x9d"),
    }
    out["asserts"] = checks
    if not all(checks.values()):
        raise SystemExit(f"关键指令核对失败：{checks}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    data = read_image()
    result = audit(data)

    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写出 {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
