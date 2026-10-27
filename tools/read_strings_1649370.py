"""Read NUL-terminated strings from a live client at given VAs."""
from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes as W

pid = int(sys.argv[1])
addrs = [int(part, 0) for part in sys.argv[2:]]
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = ctypes.c_void_p
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
handle = k32.OpenProcess(0x438, False, pid)
if not handle:
    raise SystemExit("OpenProcess failed")
out = []
for addr in addrs:
    buf = ctypes.create_string_buffer(96)
    got = ctypes.c_size_t()
    if k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, 96, ctypes.byref(got)):
        text = buf.raw[:got.value].split(b"\x00")[0].decode("latin-1", "replace")
    else:
        text = None
    out.append({"addr": hex(addr), "text": text})
print(json.dumps(out, ensure_ascii=False, indent=1))
k32.CloseHandle(handle)
