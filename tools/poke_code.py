"""Write bytes into the running client's memory (code patch), with read-back.

    python tools/poke_code.py --address 0x432049 --bytes EB53909090909090

Used for controlled experiments that must happen after the client reached the
menu (the launcher's --prewrite only runs inside its own cbuf injector).
"""
from __future__ import annotations

import argparse
import ctypes as C
import json

import start_conn as sc

k32 = sc.k32
k32.OpenProcess.argtypes = [C.c_uint32, C.c_int, C.c_uint32]
k32.OpenProcess.restype = C.c_void_p
k32.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t,
                                   C.POINTER(C.c_size_t)]
k32.CloseHandle.argtypes = [C.c_void_p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", required=True, type=lambda v: int(v, 0))
    ap.add_argument("--bytes", required=True)
    ap.add_argument("--output")
    args = ap.parse_args()
    data = bytes.fromhex(args.bytes)
    pid = sc.find_pid()
    handle = k32.OpenProcess(0x0438, False, pid)
    if not handle:
        raise SystemExit("OpenProcess failed")
    row = {"pid": pid, "address": hex(args.address), "bytes": data.hex()}
    try:
        before = C.create_string_buffer(len(data))
        got = C.c_size_t()
        ok = k32.ReadProcessMemory(handle, C.c_void_p(args.address), before, len(data), C.byref(got))
        row["before"] = before.raw.hex() if ok and got.value == len(data) else None
        wrote = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(args.address),
                                    C.create_string_buffer(data, len(data)), len(data), C.byref(wrote))
        if not ok or wrote.value != len(data):
            row["status"] = "write_failed"
            row["error"] = C.get_last_error()
        else:
            after = C.create_string_buffer(len(data))
            got = C.c_size_t()
            ok = k32.ReadProcessMemory(handle, C.c_void_p(args.address), after, len(data), C.byref(got))
            row["after"] = after.raw.hex() if ok else None
            row["status"] = "ok" if row["after"] == data.hex() else "readback_mismatch"
    finally:
        k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(text + "\n")
    print(text)
    return 0 if row.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
