"""Read the native Build 1649370 first-person model cache without patching it.

The addresses come from the verified r107flow image at 0x590448..0x5905fa:
the encoded local client pointer uses 0x1C1D188/0x82C3B58, while
0x5905c4 compares the arm resolver count with client+0xC7F88 and
0x5905f2/0x59060e read/write the XModel pointer list at client+0xC7F94.
This reports the cached list, not a renderer draw call.
"""
from __future__ import annotations

import argparse
import json

from probe_weapon_viewmodel_binding_1649370 import ProcessMemory

SLOT_INDEX = 0x82C3B58
ENCODED_CLIENT_TABLE = 0x1C1D188
CLIENT_XOR = 0xFBB2C97A
MODEL_COUNT_OFFSET = 0xC7F88
MODEL_LIST_OFFSET = 0xC7F94
MODEL_LIST_LIMIT = 16
CLIENT_INFO_BASE = 0x827F730
LOCAL_CLIENT_INFO_OFFSET = 0xAF350
WEAPON_TABLE = 0x1988B50


def _model(memory: ProcessMemory, pointer: int) -> dict:
    result = {"pointer": hex(pointer)}
    if pointer:
        try:
            result["name"] = memory.name(pointer)
        except (OSError, ValueError) as error:
            result["read_error"] = type(error).__name__
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    memory = ProcessMemory(args.pid)
    try:
        index = memory.u32(SLOT_INDEX)
        if index >= 64:
            raise RuntimeError(f"unexpected local client slot index {index}")
        encoded = memory.u32(ENCODED_CLIENT_TABLE + index * 4)
        client = encoded ^ CLIENT_XOR
        count = memory.u32(client + MODEL_COUNT_OFFSET)
        if count > MODEL_LIST_LIMIT:
            raise RuntimeError(f"unexpected model count {count}; refusing broad read")
        models = [_model(memory, memory.u32(client + MODEL_LIST_OFFSET + i * 4))
                  for i in range(count)]
        info_root = memory.u32(CLIENT_INFO_BASE)
        info = info_root + LOCAL_CLIENT_INFO_OFFSET if info_root else 0
        selection_flags = memory.u32(client + 0x400)
        selected_weapon = memory.u32(
            client + (0x3E4 if selection_flags & 2 else 0x3F8))
        queue_count = memory.u32(0x82CA590)
        if queue_count > 0x500:
            raise RuntimeError(f"unexpected weapon queue count {queue_count}")
        queue = [
            {"weapon": memory.u32(0x82CA594 + i * 8),
             "status": memory.u32(0x82CA598 + i * 8)}
            for i in range(min(queue_count, 4))
        ]
        lookup_slot = memory.u32(0x82C3B64)
        if lookup_slot >= 64:
            raise RuntimeError(f"unexpected weapon lookup slot {lookup_slot}")
        lookup_base = memory.u32(ENCODED_CLIENT_TABLE + lookup_slot * 4) ^ 0x7A634997
        lookup_entry = lookup_base + selected_weapon * 0x10C if lookup_base else 0
        definition = memory.u32(WEAPON_TABLE + 78 * 4)
        weapon_model = memory.u32(definition + 0x10) if definition else 0
        result = {
            "pid": args.pid,
            "slot_index": index,
            "local_client": hex(client),
            "model_count": count,
            "models": models,
            "view_builder_input": {
                "client_number": memory.u32(client + 0x158),
                "viewmodel_index": memory.u32(client + 0x15C),
                "selection_flags": selection_flags,
                "weapon_field_3e4": memory.u32(client + 0x3E4),
                "weapon_field_3f8": memory.u32(client + 0x3F8),
                "selected_weapon": selected_weapon,
                "cached_weapon_field_c7fa4": memory.u32(client + 0xC7FA4),
                "cached_viewmodel_field_c7fa8": memory.u32(client + 0xC7FA8),
            },
            "client_info": {
                "root": hex(info_root),
                "base": hex(info) if info else None,
                "present": memory.u32(info + 0x400) if info else None,
                "typed": memory.u32(info + 0x404) if info else None,
                "character": memory.u32(info + 0x40C) if info else None,
            },
            "view_builder_gates": {
                "global_827f738": hex(memory.u32(0x827F738)),
                "weapon_queue_count": queue_count,
                "weapon_queue_head": queue,
                "weapon_lookup_base": hex(lookup_base),
                "weapon_lookup_entry": hex(lookup_entry),
                "weapon_lookup_entry_first_word": memory.u32(lookup_entry) if lookup_entry else None,
            },
            "weapon_78": {
                "definition": hex(definition),
                "model": _model(memory, weapon_model),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
