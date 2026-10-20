"""Read [lobby+0x1F4], the state that gates the FE frontend stage.

0xBAC350 is simply:

    mov eax, [ecx + 0x1F4]
    ret

and callers require it to be 2. When it is, 0x6217BF sets FE_state ([0xE59D20])
from 5 to 6, which in turn lets 0x730C50 report FE loaded, which sets
onboard_character_selected and advances the FE ladder.

The lobby object pointer is found by scanning for the known static that holds it;
candidates are tried until the +0x1F4 value looks like a small state number.

    python tools/probe_lobby_1f4.py 40
    python tools/probe_lobby_1f4.py 40 --set 2      # try forcing it to 2
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
# static slots that have been recorded as holding the lobby object
# 0x643280 is the singleton getter: mov eax, [0xE85C68] and lazily fills it.
CANDIDATE_STATICS = [0xE85C68]
OFF = 0x1F4


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def u32(h, va: int):
    d = read(h, va, 4)
    return struct.unpack("<I", d)[0] if len(d) == 4 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds", nargs="?", type=int, default=40)
    parser.add_argument("--set", type=int, default=None,
                        help="write this value into [lobby+0x1F4] when it differs")
    args = parser.parse_args()

    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid}")
    try:
        deadline = time.time() + args.seconds
        last = None
        while time.time() < deadline:
            row = {}
            for static in CANDIDATE_STATICS:
                obj = u32(h, static)
                if obj:
                    val = u32(h, obj + OFF)
                    row[f"{static:#x}->{obj:#x}"] = val
                    row["+0x1F0 (obj)"] = u32(h, obj + 0x1F0)
                    row["+0x1F0->vtbl"] = u32(h, u32(h, obj + 0x1F0) or 0)
                    # 0xBAF040 is called with ecx = lobby+0x208 and does add ecx,0x4C8,
                    # so lobby+0x6D0 is the object it inspects (the cipher channel).
                    row["+0x6D0 (cipher?)"] = u32(h, obj + 0x6D0)
                    row["+0x6D4"] = u32(h, obj + 0x6D4)
                    # 0xBAFDA0 copies a blob from [ecx+0x1D8] with length
                    # [ecx+0x1D4], where ecx = lobby+0x6D0.
                    ch_len = read(h, obj + 0x8A4, 2)
                    row["chan_len @+0x8A4"] = struct.unpack("<H", ch_len)[0] if len(ch_len) == 2 else None
                    blob = read(h, obj + 0x8A8, 0x90)
                    if blob:
                        row["chan_head"] = blob[:16].hex()
                        # dump the full block once, in 16-byte rows
                        if not getattr(main, "dumped", False):
                            main.dumped = True
                            print("--- [lobby+0x8A8] 144 bytes ---")
                            for off in range(0, len(blob), 16):
                                chunk = blob[off:off + 16]
                                hx = " ".join(f"{b:02x}" for b in chunk)
                                tx = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                                print(f"  {obj + 0x8A8 + off:#010x}  {hx:<48} {tx}")
                    if args.set is not None and val is not None and val != args.set:
                        if write(h, obj + OFF, struct.pack("<I", args.set)):
                            print(f"  wrote {args.set} at {obj + OFF:#x} (was {val})")
            row["FE_state"] = u32(h, 0xE59D20)
            row["dw"] = u32(h, 0x84ABA40)
            if row != last:
                print(time.strftime("%H:%M:%S"), row, flush=True)
                last = row
            time.sleep(1.0)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
