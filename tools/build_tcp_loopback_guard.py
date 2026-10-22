"""Build a private dynamic WFP guard allowing loopback port 28969.

Reads the separate 2.6.9.7 launcher source; never edits that repository.
The output is an ignored local experiment artifact under runs/guard-build.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "CODOL-2.6.9.7-Launcher/source/client/client_loopback_guard.cpp"
SOURCE_SHA256 = "0bb3faed5fbafc62c9145833396d74e220c2da4c56720faa92bd7da6a2de3dea"
OUT = ROOT / "runs/guard-build"

SHIM = """#define FWPM_SESSION_FLAG_DYNAMIC 1
static const GUID FWPM_CONDITION_ALE_APP_ID={0xd78e1e87,0x8644,0x4ea5,{0x94,0x37,0xd8,0x09,0xec,0xef,0xc9,0x71}};
static const GUID FWPM_CONDITION_IP_REMOTE_ADDRESS={0xb235ae9a,0x1d64,0x49b8,{0xa4,0x4c,0x5f,0xf3,0xd9,0x09,0x50,0x45}};
static const GUID FWPM_CONDITION_IP_REMOTE_PORT={0xc35a604d,0xd22b,0x4e1a,{0x91,0xb4,0x68,0xf6,0x74,0xee,0x67,0x4b}};
static const GUID FWPM_CONDITION_IP_PROTOCOL={0x3971ef2b,0x623e,0x4f9a,{0x8c,0xb1,0x6e,0x79,0xb8,0x06,0xb9,0xa7}};
static const GUID FWPM_LAYER_ALE_AUTH_CONNECT_V4={0xc38d57d1,0x05a7,0x4c33,{0x90,0x4f,0x7f,0xbc,0xee,0xe6,0x0e,0x82}};
static const GUID FWPM_LAYER_ALE_AUTH_CONNECT_V6={0x4a72393b,0x319f,0x44bc,{0x84,0xc3,0xba,0x54,0xdc,0xb3,0xb6,0xb4}};
static const GUID FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4={0xe1cd9fe7,0xf4b5,0x4273,{0x96,0xc0,0x59,0x2e,0x48,0x7b,0x86,0x50}};
static const GUID FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V6={0xa3b42c97,0x9f04,0x4672,{0xb8,0x7e,0xce,0xe9,0xc4,0x83,0x25,0x7f}};
"""


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"source drift: expected one occurrence of {old!r}")
    return source.replace(old, new)


def main() -> int:
    data = SOURCE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"reference source changed: {digest}")
    source = data.decode("utf-8")
    source = replace_once(source, "#include <stdexcept>", "#include <stdexcept>\n" + SHIM)
    source = replace_once(source, "unsigned rules=(layerIndex==0 || layerIndex==2)?3:1;",
                          "unsigned rules=(layerIndex==0 || layerIndex==2)?2:1;")
    source = replace_once(source, "if(rules==3)", "if(rules==2)")
    source = replace_once(source, "udp-127.0.0.1:28969", "loopback-127.0.0.1:28969")
    OUT.mkdir(parents=True, exist_ok=True)
    cpp = OUT / "client_loopback_tcp_guard.cpp"
    exe = OUT / "client_loopback_tcp_guard-fixed.exe"
    cpp.write_text(source, encoding="utf-8")
    zig = shutil.which("zig")
    if not zig:
        raise SystemExit("zig compiler not found")
    subprocess.run([zig, "c++", "-target", "x86_64-windows-gnu", "-std=c++17", "-O2",
                    "-municode", str(cpp), "-o", str(exe), "-lfwpuclnt", "-lrpcrt4"],
                   check=True)
    print(json.dumps({"source_sha256": digest, "output": str(exe),
                      "output_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                      "policy": "per-image dynamic WFP: only IPv4 127.0.0.1:28969; IPv6 blocked",
                      "filters": 6}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
