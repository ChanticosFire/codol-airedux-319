"""Read-only snapshot of Build 1649370's native LSG owner prerequisites."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ
    if not handle:
        raise OSError("OpenProcess failed")
    try:
        netobj = sc.u32(handle, 0x8269774)
        owner = sc.u32(handle, netobj + 4) if netobj else 0
        conn = sc.u32(handle, netobj + 0x4F4) if netobj else 0
        row = {
            "schema": 1, "build": 1649370,
            "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
            "netobj": hex(netobj), "owner": hex(owner),
            "owner_vtable": hex(sc.u32(handle, owner)) if owner else None,
            "conn": hex(conn),
            "conn_state": {
                "c8": sc.u32(handle, conn + 0xC8),
                "5e8": sc.u32(handle, conn + 0x5E8),
                "644": sc.u32(handle, conn + 0x644),
            } if conn else None,
            "global_state_0x84aba7c": sc.u32(handle, 0x84ABA7C),
            "auth_sources_present": {
                "0x84abb08": bool(sc.u32(handle, 0x84ABB08)),
                "0x84abb0c": bool(sc.u32(handle, 0x84ABB0C)),
                "0x84abb14": bool(sc.u32(handle, 0x84ABB14)),
            },
            "configured_lsg_port": sc.u32(handle, 0x81A9780) & 0xFFFF,
            "netobj_flag_0x4f8": hex(sc.u32(handle, netobj + 0x4F8)) if netobj else None,
        }
    finally:
        sc.k32.CloseHandle(handle)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = ROOT / "evidence" / "experiments" / f"{stamp}-1649370-lsg-owner-prereqs.json"
    output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), **row}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
