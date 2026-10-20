"""One-shot: bring the lobby up without manual steps.

After every client restart the FE ladder resets to G1=0 and the frontend stays
on the empty haze screen. This polls until the client reports dw=5, writes G1=2
(and session_ready=1), waits for gate=1/G1=3, then optionally clicks the
TextField dialog's 关闭 button.

    python tools/auto_lobby.py                 # wait, force, click
    python tools/auto_lobby.py --no-click      # wait and force only
    python tools/auto_lobby.py --timeout 120
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
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.CreateRemoteThread.restype = ctypes.c_void_p
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]

EXE = "codomp_client_shipretail.exe"
STAT_SETTER = 0x6B03D0
ONBOARDED = 0xDC3EA0
FIRSTLOGIN_FLAG = 0x331C5C0
D_COND_PTR = 0x3306D60
DW = 0x84ABA40
CS = 0x84ABA50
G1 = 0x82E1340
GATE = 0x82E1344
SESSION_READY = 0x84ABAFC


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


def read_u32(h, va: int):
    data = read(h, va, 4)
    return struct.unpack("<I", data)[0] if len(data) == 4 else None


def read_u8(h, va: int):
    data = read(h, va, 1)
    return data[0] if data else None


def write_u8(h, va: int, value: int) -> bool:
    buf = ctypes.create_string_buffer(bytes([value & 0xFF]), 1)
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, 1, ctypes.byref(wrote))
    return bool(ok) and wrote.value == 1


def write_u32(h, va: int, value: int) -> bool:
    data = struct.pack("<I", value & 0xFFFFFFFF)
    buf = ctypes.create_string_buffer(data, 4)
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, 4, ctypes.byref(wrote))
    return bool(ok) and wrote.value == 4


def call_stat(h, name_va: int) -> bool:
    """Run "mov eax, name_va ; call 0x6B03D0 ; xor eax,eax ; ret" in a cave."""
    MEM = 0x3000
    RX = 0x40
    cave = k32.VirtualAllocEx(h, None, 0x1000, MEM, RX)
    if not cave:
        return False
    cave = int(cave)
    rel = STAT_SETTER - (cave + 10)
    code = (b"\xb8" + struct.pack("<I", name_va)
            + b"\xe8" + struct.pack("<i", rel) + b"\x33\xc0\xc3")
    buf = ctypes.create_string_buffer(code, len(code))
    wrote = ctypes.c_size_t()
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(cave), buf, len(code), ctypes.byref(wrote)):
        return False
    thread = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(cave), None, 0, None)
    if not thread:
        return False
    k32.WaitForSingleObject(ctypes.c_void_p(thread), 3000)
    k32.CloseHandle(ctypes.c_void_p(thread))
    return True


def fix_firstlogin(h) -> bool:
    """
    0x6BBF30 returns 1 when either
        [0x331C5C0]==1 and [0x84ABA50]==4, or
        [[0x3306D60]+0xC] != 0
    Offline both are false, so the FE ladder never leaves G1=0 and the character
    screen stays up. Writing a non-zero value at [D+0xC] satisfies the second
    path without touching ui_state.
    """
    ptr = read_u32(h, D_COND_PTR)
    if not ptr:
        print("D condition pointer is null")
        return False
    ok = write_u32(h, ptr + 0xC, 1)
    if ok:
        print(f"firstlogin: wrote 1 at {ptr + 0xC:#x} so 0x6BBF30 returns 1")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=90,
                        help="seconds to wait for dw=5")
    parser.add_argument("--no-click", dest="click", action="store_false", default=True)
    parser.add_argument("--at", nargs=2, type=int, default=[1405, 621],
                        metavar=("X", "Y"), help="close-button client coordinates")
    args = parser.parse_args()

    deadline = time.time() + args.timeout
    pid = 0
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            break
        time.sleep(1)
    if not pid:
        print("client not running", file=sys.stderr)
        return 2

    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error(), file=sys.stderr)
        return 3
    print(f"pid={pid}")
    try:
        onboarded_done = False
        while time.time() < deadline:
            dw = read_u32(h, DW)
            cs = read_u32(h, CS)
            # Mark onboarding as early as the code is usable (dw>=2 means the
            # module decrypted and DNS finished) so the character screen never
            # appears; at dw=5 it is already too late, and at process start the
            # stat setter is not ready yet (writing that early crashed it).
            if dw is not None and dw >= 2 and not onboarded_done:
                if call_stat(h, ONBOARDED):
                    onboarded_done = True
                    print(f"dw={dw} -> onboard_character_selected set (early)")
                fix_firstlogin(h)
            if dw == 5 and cs == 9:
                print(f"dw={dw} cs={cs} -> forcing G1=2")
                if not onboarded_done and call_stat(h, ONBOARDED):
                    print("onboard_character_selected set (late fallback)")
                break
            time.sleep(0.5)
        else:
            print("timed out waiting for dw=5", file=sys.stderr)
            return 4

        deadline2 = time.time() + 40
        while time.time() < deadline2:
            g1 = read_u8(h, G1)
            gate = read_u8(h, GATE)
            if g1 == 3 and gate == 1:
                print(f"gate={gate} G1={g1} -> frontend active")
                break
            if g1 in (0, 1) or g1 is None:
                write_u8(h, G1, 2)
                if read_u32(h, SESSION_READY) == 0:
                    write_u32(h, SESSION_READY, 1)
            time.sleep(0.5)
        else:
            print("warning: gate never became 1", file=sys.stderr)
    finally:
        k32.CloseHandle(h)

    if args.click:
        time.sleep(6)
        cmd = [sys.executable, str(PathHelper.tool("click_at.py")),
               "--window", "CODO", "--at", str(args.at[0]), str(args.at[1])]
        print("clicking close button")
        subprocess.run(cmd, check=False)
    print("lobby ready")
    return 0


class PathHelper:
    @staticmethod
    def tool(name: str) -> str:
        from pathlib import Path
        return str(Path(__file__).resolve().parent / name)


if __name__ == "__main__":
    raise SystemExit(main())
