"""Drive the loopback ring and sample parser hooks inside one process.

The client crashes ~163ms after reaching state 7, so a separate process cannot
read the hook counters in time.  This script does the forwarding itself and
reads the counters the instant the state flips.

    python tools/fast_forward_1649370.py --pid 1234 --port 29150 --seconds 6
"""
from __future__ import annotations

import argparse
import ctypes
import socket
import struct
import sys
import time
from ctypes import wintypes as W

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import ring_bridge_1649370 as rb  # noqa: E402

STATE = rb.STATE


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", W.DWORD), ("Dr0", W.DWORD), ("Dr1", W.DWORD), ("Dr2", W.DWORD),
                ("Dr3", W.DWORD), ("Dr6", W.DWORD), ("Dr7", W.DWORD), ("FloatSave", ctypes.c_byte * 112),
                ("SegGs", W.DWORD), ("SegFs", W.DWORD), ("SegEs", W.DWORD), ("SegDs", W.DWORD),
                ("Edi", W.DWORD), ("Esi", W.DWORD), ("Ebx", W.DWORD), ("Edx", W.DWORD),
                ("Ecx", W.DWORD), ("Eax", W.DWORD), ("Ebp", W.DWORD), ("Eip", W.DWORD),
                ("SegCs", W.DWORD), ("EFlags", W.DWORD), ("Esp", W.DWORD), ("SegSs", W.DWORD),
                ("ExtendedRegisters", ctypes.c_byte * 512)]


def thread_ids(pid: int) -> list[int]:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x4, 0)
    entry = (W.DWORD * 7)()
    # THREADENTRY32
    class TE(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
                    ("th32OwnerProcessID", W.DWORD), ("tpBasePri", ctypes.c_long),
                    ("tpDeltaPri", ctypes.c_long), ("dwFlags", W.DWORD)]
    te = TE()
    te.dwSize = ctypes.sizeof(te)
    ids = []
    if k.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                ids.append(te.th32ThreadID)
            if not k.Thread32Next(snap, ctypes.byref(te)):
                break
    k.CloseHandle(snap)
    return ids


def sample_eips(pid: int, tids: list[int]) -> list[tuple[int, int, int]]:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    rows = []
    failed = 0
    for tid in tids:
        th = k.OpenThread(0x1F03FF, False, tid)
        if not th:
            failed += 1
            continue
        k.SuspendThread(th)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = 0x1003F
        ok = k.Wow64GetThreadContext(th, ctypes.byref(ctx))
        k.ResumeThread(th)
        k.CloseHandle(th)
        if ok:
            rows.append((tid, ctx.Eip, ctx.Esp))
        else:
            failed += 1
    if failed:
        print(f"   [{failed}/{len(tids)} threads unreadable]", flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--target", default="127.0.0.1:28969")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--hook", type=lambda v: int(v, 0), action="append", default=[],
                    help="hook slot base (count is the first dword)")
    args = ap.parse_args()
    ctypes.WinDLL("kernel32", use_last_error=True)

    host, port_text = args.target.rsplit(":", 1)
    target = (host, int(port_text))

    client = rb.Client()  # finds the pid itself
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", args.port))
    sock.setblocking(False)

    deadline = time.monotonic() + args.seconds
    sent = received = injected = 0
    last_state = None
    seen7 = None
    samples = []

    while time.monotonic() < deadline:
        state = client.u32(STATE)
        if not client.read(STATE, 4):
            print(f"[t={time.monotonic():.3f}] client gone", flush=True)
            break
        if state != last_state:
            print(f"[t={time.monotonic():.3f}] state {last_state} -> {state}", flush=True)
            last_state = state
        if state == 7 and seen7 is None:
            seen7 = time.monotonic()
            for slot in args.hook:
                samples.append((round(time.monotonic(), 4), hex(slot), client.u32(slot)))
            eips = sample_eips(client.pid, thread_ids(client.pid))
            enc = client.u32(0x331c0c8)
            dec = enc ^ 0xD362501F
            fn = client.u32(dec + 0x109244) if 0x10000 < dec < 0x7FFFFFFF else None
            flag = client.u32(dec + 0x100260) if 0x10000 < dec < 0x7FFFFFFF else None
            print(f"   CL: enc={enc:#010x} dec={dec:#010x} [+0x109244]={fn if fn is None else hex(fn)} "
                  f"[+0x100260]={flag if flag is None else hex(flag)}", flush=True)
            trace = []
            good_tid = eips[0][0] if eips else None
            for _ in range(100):
                rows = sample_eips(client.pid, [good_tid]) if good_tid else []
                if rows:
                    good_tid = rows[0][0]
                    trace.append(rows[0][1])
                time.sleep(0.0002)
            uniq = []
            for e in trace:
                if not uniq or uniq[-1] != e:
                    uniq.append(e)
            print("   eip-trace:", " -> ".join(f"{e:#010x}" for e in uniq[:20]), flush=True)
            if eips:
                _tid, _eip, esp = eips[0]
                blob = client.read(esp, 0x60)
                if blob:
                    vals = struct.unpack("<24I", blob)
                    print("   stack:", flush=True)
                    for i in range(0, 24, 4):
                        print(f"    +{i*4:#04x}: " + " ".join(f"{v:#010x}" for v in vals[i:i+4]),
                              flush=True)
            print(f"[t={seen7:.3f}] STATE=7 samples={samples}", flush=True)
            for tid, eip, esp in sorted(eips, key=lambda r: r[0]):
                print(f"   tid={tid} eip={eip:#010x} esp={esp:#010x}", flush=True)

        # forward client -> gs
        for packet in client.drain_ring_a():
            sock.sendto(packet["payload"], target)
            sent += 1

        # gs -> client
        for _ in range(64):
            try:
                data, _src = sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            received += 1
            result = client.inject_oob_raw(data, 2, 0, b"\0\0\0\0")
            if result.get("status") == "queued":
                injected += 1

        time.sleep(0.0005)

    state = client.u32(STATE)
    print(f"sent={sent} received={received} injected={injected} "
          f"final_state={state} seen7={seen7}", flush=True)
    if seen7 is not None and args.hook:
        for slot in args.hook:
            print(f"hook {slot:#x} = {client.u32(slot)}", flush=True)
    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
