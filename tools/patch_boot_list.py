"""Rewrite two entries of the boot fastfile list so the client loads gametype.

    python tools/patch_boot_list.py --exe <shell exe> [--restore]

Target: 0x4FCC10 (sub esp,0xA10) builds a 4-entry list and calls 0x49E160.
Entries 3 and 4 are the localized pre-gfx packages; this replaces their name
pointers with ``common_gametype_mp`` / ``patch_common_gametype_mp`` written into
the zero tail of .rdata, so the client registers the 88 gametype weapons itself.

Layout: entry = {char* name; u32 flags} (0xC bytes), list at [ebp-0xA10].
Immediates patched: 0x4FCC5C (0xDBD708) and 0x4FCC6C (0xDBD728).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
from pathlib import Path

PATCH_A = 0x4FCC5C      # mov dword ptr [ebp-0x9F8], <imm32>
PATCH_B = 0x4FCC6C      # mov dword ptr [ebp-0x9EC], <imm32>
OLD_A, OLD_B = 0xDBD708, 0xDBD728
SCRATCH = 0xE15A6F      # zero tail inside .rdata (verified present)
NEW_A = b"common_gametype_mp\0"
NEW_B = b"patch_common_gametype_mp\0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    path = Path(args.exe)
    backup = path.with_suffix(path.suffix + ".bootlist-backup")

    if args.restore:
        if not backup.exists():
            raise SystemExit("no backup")
        shutil.copy2(backup, path)
        print(f"restored {path}")
        return 0

    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"backup -> {backup}")
    data = bytearray(path.read_bytes())

    import pefile
    pe = pefile.PE(data=bytes(data), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    off_a = pe.get_offset_from_rva(PATCH_A - base)
    off_b = pe.get_offset_from_rva(PATCH_B - base)
    off_scratch = pe.get_offset_from_rva(SCRATCH - base)
    print(f"file offsets: A={off_a:#x} B={off_b:#x} scratch={off_scratch:#x}")

    imm_a = struct.unpack_from("<I", data, off_a + 6)[0]
    imm_b = struct.unpack_from("<I", data, off_b + 6)[0]
    if (imm_a, imm_b) == (OLD_A, OLD_B):
        pass
    elif (imm_a, imm_b) == (SCRATCH, SCRATCH + len(NEW_A) + 1):
        print("already patched")
        return 0
    else:
        raise SystemExit(f"unexpected immediates {imm_a:#x} {imm_b:#x}")

    # verify the opcode shape (C7 85 <disp32> <imm32>)
    for va, off in ((PATCH_A, off_a), (PATCH_B, off_b)):
        if data[off] != 0xC7 or data[off + 1] != 0x85:
            raise SystemExit(f"unexpected opcode at {va:#x}: {data[off]:#x}")

    data[off_scratch:off_scratch + len(NEW_A)] = NEW_A
    va_b = SCRATCH + len(NEW_A) + 1
    off_b2 = off_scratch + len(NEW_A) + 1
    data[off_b2:off_b2 + len(NEW_B)] = NEW_B
    struct.pack_into("<I", data, off_a + 6, SCRATCH)
    struct.pack_into("<I", data, off_b + 6, va_b)
    path.write_bytes(bytes(data))
    print(f"patched {path}")
    print(f"  entry3 -> {NEW_A[:-1].decode()} @ {SCRATCH:#x}")
    print(f"  entry4 -> {NEW_B[:-1].decode()} @ {va_b:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
