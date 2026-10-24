"""Transparent runtime hook for an arbitrary function in CODOL 1649370.

This build reaches its network code through encrypted function pointers, so
static call graphs and pointer scans both come back empty.  Hooking the function
entry is the only reliable way to observe "was it called, from where, with what
arguments".

The stub is fully transparent:

    pushad
    mov  eax, [esp+0x20]      ; caller's return address (pushad moved esp by 32)
    mov  [slot_ret], eax
    mov  eax, [esp+0x24]      ; first stack argument
    mov  [slot_arg0], eax
    mov  eax, [esp+0x28]      ; second stack argument
    mov  [slot_arg1], eax
    inc  dword [slot_count]
    popad
    <replay the stolen prologue bytes>
    jmp  target+len

    python tools/hook_any_1649370.py --target 0x7F4F10 --probe
    python tools/hook_any_1649370.py --target 0x7F4F10
    python tools/hook_any_1649370.py --target 0x7F4F10 --read
    python tools/hook_any_1649370.py --target 0x7F4F10 --restore
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
from ctypes import wintypes as W

import capstone

_MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
_MD.detail = False

k32 = C.WinDLL("kernel32", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL

SLOT_BASE_DEFAULT = 0xE54BD00



def aligned_length(blob: bytes, start_va: int, minimum: int = 5) -> int:
    """Smallest instruction boundary >= `minimum` bytes.

    Stealing a fixed 5 bytes corrupts any function whose prologue crosses an
    instruction boundary.  `0x7F4F10` starts `55 8b ec 53 8b` where that final
    `8b` is only the first byte of `mov ebx,[ebp+8]`; replaying five bytes and
    jumping to target+5 resumes in the middle of an instruction and crashes.
    Disassemble from the entry and take the first boundary at or past `minimum`.
    """
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    total = 0
    for ins in md.disasm(blob, start_va):
        total += ins.size
        if total >= minimum:
            return total
    return minimum


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--len", type=int, default=5)
    ap.add_argument("--slot", type=lambda v: int(v, 0), default=SLOT_BASE_DEFAULT,
                    help="base address of the four result slots")
    ap.add_argument("--capture", type=int, default=0,
                    help="copy this many bytes of the captured buffer, at call time")
    ap.add_argument("--capture-src", choices=("arg0", "ecx"), default="arg0",
                    help="which register/argument points at the buffer to copy")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    slot_count = args.slot
    slot_ret = args.slot + 4
    slot_arg0 = args.slot + 8
    slot_arg1 = args.slot + 12
    slot_ecx = args.slot + 0x10
    slot_eax = args.slot + 0x14
    slot_capture = args.slot + 0x40
    _head = read(args.target, 16) or b""
    if _head:
        args.len = aligned_length(_head, args.target, args.len)
    original = read(args.target, args.len)
    entry = read(args.target, 5)
    report: dict = {
        "pid": pid, "target": hex(args.target), "len": args.len,
        "original": original.hex() if original else None,
        "entry": entry.hex() if entry else None,
        "is_hooked": bool(entry and entry[0] == 0xE9),
        "counters": {"count": u32(slot_count), "ret": u32(slot_ret),
                     "arg0": u32(slot_arg0), "arg1": u32(slot_arg1),
                     "ecx": u32(slot_ecx), "eax": u32(slot_eax)},
    }
    for key in ("ret", "arg0", "arg1", "ecx", "eax"):
        if isinstance(report["counters"].get(key), int):
            report["counters"][key] = hex(report["counters"][key])
    if args.capture:
        blob = read(slot_capture, args.capture) or b""
        report["captured_hex"] = blob.hex()
        words = [struct.unpack_from("<I", blob, i)[0] for i in range(0, len(blob) - 3, 4)]
        report["captured_words"] = [hex(w) for w in words]
    if args.capture:
        blob = read(slot_capture, args.capture) or b""
        report["captured_hex"] = blob.hex()
        words = [struct.unpack_from("<I", blob, i)[0] for i in range(0, len(blob) - 3, 4)]
        report["captured_words"] = [hex(w) for w in words]

    if args.probe or args.read:
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        if not original:
            raise SystemExit("cannot read original bytes")
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), 0x40, C.byref(old))
        ok = write(args.target, original)
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(args.target), len(original))
        report.update(restored=ok, bytes_after=read(args.target, len(original)).hex())
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    if entry and entry[0] == 0xE9:
        print(json.dumps(dict(report, status="already_hooked"), indent=2))
        return 0
    if not original:
        raise SystemExit("cannot read original bytes")

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                          # pushad
    code += b"\x8B\x44\x24\x20"                              # mov eax,[esp+0x20] ret
    code += b"\xA3" + struct.pack("<I", slot_ret)
    code += b"\x8B\x44\x24\x24"                              # mov eax,[esp+0x24] arg0
    code += b"\xA3" + struct.pack("<I", slot_arg0)
    code += b"\x8B\x44\x24\x28"                              # mov eax,[esp+0x28] arg1
    code += b"\xA3" + struct.pack("<I", slot_arg1)
    code += b"\xFF\x05" + struct.pack("<I", slot_count)
    # pushad pushes EAX,ECX,EDX,EBX,ESP,EBP,ESI,EDI in that order, so afterwards
    # the caller ECX sits at [esp+0x18].  Some functions (0x484C10) receive their
    # argument in ECX only, so it must be recorded explicitly.
    code += b"\x8B\x44\x24\x18"                              # mov eax,[esp+0x18] ecx
    code += b"\xA3" + struct.pack("<I", slot_ecx)
    # pushad layout: [esp+0x18]=ECX, [esp+0x1C]=EAX -- the latter is the
    # callee entry EAX, which is how a return value is observed when the
    # hook sits right after a call (e.g. 0x5C2388 after Netchan_Process).
    code += b"\x8B\x44\x24\x1C"                              # mov eax,[esp+0x1c] eax
    code += b"\xA3" + struct.pack("<I", slot_eax)
    if args.capture and args.capture >= 4:
        # Copy the buffer `source` points at, *while the call is still live*.
        # Stack-passed name arrays die as soon as the function returns, so
        # reading them afterwards always yields zeros.
        count_words = args.capture // 4
        src_off = b"\x24" if args.capture_src == "arg0" else b"\x18"
        code += b"\x8B\x74\x24" + src_off                    # mov esi,[esp+src]
        code += b"\xBF" + struct.pack("<I", slot_capture)    # mov edi,capture_dst
        code += b"\xB9" + struct.pack("<I", count_words)     # mov ecx,words
        code += b"\xF3\xA5"                                  # rep movsd
    code += b"\x61"                                          # popad

    # Replay the stolen bytes, *relocating relative jumps*.
    #
    # A blind `code += original` is wrong whenever the stolen span contains a
    # relative branch: `0F 84 xx xx xx xx` means "jump to <target>" only while it
    # sits at its original address.  Copies into the cave keep the old
    # displacement and therefore jump to garbage -- that crash is what killed the
    # 0x5C2388 experiment in Round 39.
    replay_addr = cave + len(code)
    replay = bytearray()
    for ins in _MD.disasm(bytes(original), args.target):
        here = replay_addr + len(replay)
        raw = bytes(ins.bytes)
        if ins.mnemonic in ("call", "jmp") and ins.size == 5:
            tgt = int(ins.op_str, 16)
            replay += raw[:1] + struct.pack("<I", (tgt - (here + 5)) & 0xFFFFFFFF)
        elif ins.mnemonic.startswith("j") and ins.size == 6 and raw[0] == 0x0F:
            tgt = int(ins.op_str, 16)
            replay += raw[:2] + struct.pack("<I", (tgt - (here + 6)) & 0xFFFFFFFF)
        elif ins.mnemonic.startswith("j") and ins.size == 2:
            # A short branch cannot stay short from the cave: relocation may push
            # the distance past +-127.  Widen it to the rel32 form.
            tgt = int(ins.op_str, 16)
            if ins.mnemonic == "jmp":
                replay += b"\xE9" + struct.pack("<I", (tgt - (here + 5)) & 0xFFFFFFFF)
            else:
                jcc = raw[0] - 0x70
                replay += bytes([0x0F, 0x80 + jcc]) + \
                    struct.pack("<I", (tgt - (here + 6)) & 0xFFFFFFFF)
        else:
            replay += raw
    if len(replay) < args.len:
        raise SystemExit(f"relocated replay shorter than stolen span: "
                         f"{len(replay)} < {args.len}")
    code += bytes(replay)
    rel = (args.target + args.len - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)                 # jmp target+len

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), args.len, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (args.target + 5)) & 0xFFFFFFFF)
    jump += b"\x90" * (args.len - 5)
    hooked = write(args.target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), args.len, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(args.target), args.len)

    for slot in (slot_count, slot_ret, slot_arg0, slot_arg1):
        write(slot, b"\x00\x00\x00\x00")

    report.update(hooked=hooked, cave=hex(cave), code=bytes(code).hex(),
                  entry_after=read(args.target, args.len).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if hooked else 1


if __name__ == "__main__":
    raise SystemExit(main())
