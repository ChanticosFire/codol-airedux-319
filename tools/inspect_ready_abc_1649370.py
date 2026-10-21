"""Inspect the verified LobbyController DoABC record in Build 1649370 GFX.

Parses ABC tables and method bodies without executing ActionScript. The focused
output identifies method references, not runtime event dispatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

SIZE = 7664688
SHA256 = "314c4abd6936b02955e2f31f781b20ac119ea9878f83698d1a1d6f106558c31c"
MARKER = b"codo.controllers:LobbyController/private:onChangeReadyStateHandle"


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data, self.pos = data, pos

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError(f"ABC truncated at {self.pos:#x}")
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        value = 0
        for i in range(5):
            byte = self.u8()
            value |= (byte & 0x7f) << (7 * i)
            if byte < 128:
                if value >= 1 << 32:
                    raise ValueError("ABC u32 overflow")
                return value
        raise ValueError("ABC u32 too long")

    def u30(self) -> int:
        value = self.u32()
        if value >= 1 << 30:
            raise ValueError("ABC u30 overflow")
        return value


def movie_tag(movie: bytes, marker: bytes, wanted_name: bytes | None = None) -> tuple[int, bytes]:
    nbits = movie[8] >> 3
    pos = 8 + (5 + nbits * 4 + 7) // 8 + 4
    matches = []
    while pos + 2 <= len(movie):
        header = struct.unpack_from("<H", movie, pos)[0]
        tag, size = header >> 6, header & 63
        header_size = 2
        if size == 63:
            size = struct.unpack_from("<I", movie, pos + 2)[0]
            header_size = 6
        end = pos + header_size + size
        if end > len(movie):
            raise ValueError("GFX tag exceeds movie")
        if tag == 82:
            payload = movie[pos + header_size:end]
            name_end = payload.find(bytes([0]), 4)
            tag_name = payload[4:name_end] if name_end >= 0 else b""
            if marker in payload and (wanted_name is None or tag_name == wanted_name):
                matches.append((pos, payload))
        pos = end
        if tag == 0:
            break
    if len(matches) != 1 or pos != len(movie):
        raise ValueError(f"Expected one selected DoABC and complete GFX, got {len(matches)}")
    return matches[0]


def trait(r: Reader) -> dict:
    name = r.u30()
    kind_attr = r.u8()
    kind = kind_attr & 15
    out = {"name": name, "kind": kind}
    if kind in (0, 6):
        out.update(slot_id=r.u30(), type_name=r.u30(), value_index=r.u30())
        if out["value_index"]:
            out["value_kind"] = r.u8()
    elif kind in (1, 2, 3):
        out.update(disp_id=r.u30(), method=r.u30())
    elif kind == 4:
        out.update(slot_id=r.u30(), class_index=r.u30())
    elif kind == 5:
        out.update(slot_id=r.u30(), method=r.u30())
    else:
        raise ValueError(f"Unknown ABC trait kind {kind}")
    if kind_attr & 0x40:
        out["metadata"] = [r.u30() for _ in range(r.u30())]
    return out


def traits(r: Reader) -> list[dict]:
    return [trait(r) for _ in range(r.u30())]


def parse_abc(data: bytes) -> dict:
    r = Reader(data)
    version = {"minor": r.u16(), "major": r.u16()}
    for size in (4, 4, 8):
        for _ in range(max(0, r.u30() - 1)):
            if size == 8:
                r.take(8)
            else:
                r.u32()
    strings = [""]
    for _ in range(max(0, r.u30() - 1)):
        strings.append(r.take(r.u30()).decode("utf-8", "replace"))
    namespaces = [None]
    for _ in range(max(0, r.u30() - 1)):
        namespaces.append((r.u8(), r.u30()))
    for _ in range(max(0, r.u30() - 1)):
        for _ in range(r.u30()):
            r.u30()
    multinames = [None]
    for _ in range(max(0, r.u30() - 1)):
        kind = r.u8()
        if kind in (0x07, 0x0d):
            ns, name = r.u30(), r.u30()
            multinames.append({"kind": kind, "namespace": ns, "name": name})
        elif kind in (0x0f, 0x10):
            multinames.append({"kind": kind, "name": r.u30()})
        elif kind in (0x11, 0x12):
            multinames.append({"kind": kind})
        elif kind in (0x09, 0x0e):
            multinames.append({"kind": kind, "name": r.u30(), "namespace_set": r.u30()})
        elif kind in (0x1b, 0x1c):
            multinames.append({"kind": kind, "namespace_set": r.u30()})
        elif kind == 0x1d:
            qname, count = r.u30(), r.u30()
            multinames.append({"kind": kind, "qname": qname, "params": [r.u30() for _ in range(count)]})
        else:
            raise ValueError(f"Unknown ABC multiname kind {kind:#x}")
    methods = []
    for _ in range(r.u30()):
        param_count = r.u30()
        return_type = r.u30()
        params = [r.u30() for _ in range(param_count)]
        name, flags = r.u30(), r.u8()
        if flags & 8:
            for _ in range(r.u30()):
                r.u30(); r.u8()
        if flags & 0x80:
            for _ in range(param_count):
                r.u30()
        methods.append({"name": name, "flags": flags, "return_type": return_type, "params": params})
    metadata = []
    for _ in range(r.u30()):
        name = r.u30()
        items = [(r.u30(), r.u30()) for _ in range(r.u30())]
        metadata.append({"name": name, "items": items})
    instances = []
    instance_count = r.u30()
    for _ in range(instance_count):
        name, superclass, flags = r.u30(), r.u30(), r.u8()
        if flags & 8:
            r.u30()
        interfaces = [r.u30() for _ in range(r.u30())]
        init = r.u30()
        instances.append({"name": name, "superclass": superclass, "init": init,
                          "interfaces": interfaces, "traits": traits(r)})
    classes = []
    for _ in range(instance_count):
        classes.append({"init": r.u30(), "traits": traits(r)})
    scripts = []
    for _ in range(r.u30()):
        scripts.append({"init": r.u30(), "traits": traits(r)})
    bodies = {}
    for _ in range(r.u30()):
        method = r.u30()
        max_stack, local_count, init_scope, max_scope = (r.u30() for _ in range(4))
        code_offset = r.pos
        code = r.take(r.u30())
        exceptions = []
        for _ in range(r.u30()):
            exceptions.append([r.u30() for _ in range(5)])
        body_traits = traits(r)
        bodies[method] = {"code": code, "code_offset": code_offset,
                          "max_stack": max_stack, "local_count": local_count,
                          "init_scope": init_scope, "max_scope": max_scope,
                          "exceptions": exceptions, "traits": body_traits}
    if r.pos != len(data):
        raise ValueError(f"ABC has {len(data)-r.pos} trailing bytes")
    return {"version": version, "strings": strings, "namespaces": namespaces,
            "multinames": multinames, "methods": methods, "instances": instances,
            "classes": classes, "scripts": scripts, "bodies": bodies,
            "metadata": metadata}


def decode_ready_code(code: bytes, abc: dict) -> dict:
    """Walk every instruction of the ready handler; reject an unknown opcode."""
    r = Reader(code)
    no_args = {0x26, 0x27, 0x29, 0x2a, 0x30, 0x47, 0x76, 0x96,
               0xd0, 0xd1, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7}
    one_u30 = {0x2c, 0x55, 0x5d, 0x61, 0x66, 0x68, 0xf0, 0xf1}
    calls = []
    properties = []
    count = 0
    while r.pos < len(code):
        pc = r.pos
        op = r.u8()
        operands = []
        if op in no_args:
            pass
        elif op in one_u30:
            operands.append(r.u30())
            if op in (0x5d, 0x61, 0x66, 0x68):
                multiname = abc["multinames"][operands[0]]
                name = abc["strings"][multiname["name"]] if multiname and "name" in multiname else None
                properties.append({"pc": hex(pc), "opcode": hex(op),
                                   "multiname_index": operands[0], "name": name})
        elif op in (0x46, 0x4f):
            operands.extend((r.u30(), r.u30()))
            multiname = abc["multinames"][operands[0]]
            name = abc["strings"][multiname["name"]] if multiname and "name" in multiname else None
            calls.append({"pc": hex(pc), "opcode": hex(op), "multiname_index": operands[0],
                          "name": name, "argument_count": operands[1]})
        elif op in (0x10, 0x11, 0x12):
            operands.append(int.from_bytes(r.take(3), "little", signed=True))
        elif op == 0xef:
            operands.extend((r.u8(), r.u30(), r.u8(), r.u30()))
        else:
            raise ValueError(f"Unknown ready method opcode {op:#x} at {pc:#x}")
        count += 1
    return {"instruction_count": count, "decoded_bytes": r.pos,
            "calls": calls, "properties": properties}


def container_function_assignment(abc: dict, property_index: int) -> dict:
    """Resolve a static Function slot from the class initializer's assignments."""
    init = abc["classes"][0]["init"]
    code = abc["bodies"][init]["code"]
    r = Reader(code)
    pending_function = None
    assignments = []
    while r.pos < len(code):
        pc = r.pos
        op = r.u8()
        if op in (0xd0, 0x30, 0x47):
            pass
        elif op == 0x24:
            r.u8()
        elif op in (0x25, 0x2c, 0x5e, 0x40, 0x61, 0x68, 0xf0, 0xf1):
            value = r.u30()
            if op == 0x40:
                pending_function = value
            elif op == 0x61:
                assignments.append({"pc": hex(pc), "property_index": value,
                                    "method_index": pending_function})
                pending_function = None
        elif op == 0xef:
            r.u8(); r.u30(); r.u8(); r.u30()
        else:
            raise ValueError(f"Unknown CFunctionContainer cinit opcode {op:#x} at {pc:#x}")
    selected = [item for item in assignments if item["property_index"] == property_index]
    if len(selected) != 1:
        raise ValueError("SetReadyState slot assignment is not unique")
    return {"class_init_method": init, "class_init_bytes_decoded": r.pos,
            "assignment_count": len(assignments), **selected[0]}


def inspect(movie: bytes) -> dict:
    if len(movie) != SIZE or hashlib.sha256(movie).hexdigest() != SHA256:
        raise ValueError("GFX size or SHA-256 mismatch")
    tag_offset, payload = movie_tag(movie, MARKER)
    r = Reader(payload)
    flags = struct.unpack("<I", r.take(4))[0]
    name_end = payload.find(bytes([0]), r.pos)
    if name_end < 0:
        raise ValueError("DoABC name is not terminated")
    tag_name = payload[r.pos:name_end].decode("utf-8")
    abc_start = name_end + 1
    abc = parse_abc(payload[abc_start:])
    focus = []
    for index, method in enumerate(abc["methods"]):
        name = abc["strings"][method["name"]]
        if any(term in name for term in ("onChangeReadyStateHandle", "isReady", "cppSetMemberReadyState")):
            body = abc["bodies"].get(index)
            item = {"method_index": index, "name": name, "method": method,
                    "body": None if body is None else {k: v for k, v in body.items() if k != "code"} |
                    {"code_hex": body["code"].hex(), "code_sha256": hashlib.sha256(body["code"]).hexdigest()}}
            if "onChangeReadyStateHandle" in name and body:
                item["decoded_code"] = decode_ready_code(body["code"], abc)
            focus.append(item)
    named = {}
    for index, item in enumerate(abc["multinames"]):
        if item and "name" in item:
            value = abc["strings"][item["name"]]
            if value in ("SetReadyState", "StartMatch", "StartMatchCountDown", "cppSetMemberReadyState"):
                named[str(index)] = {**item, "string": value}
    container_tag, container_payload = movie_tag(
        movie, b"SetReadyState", b"codo/common/CFunctionContainer")
    container_name_end = container_payload.find(bytes([0]), 4)
    container = parse_abc(container_payload[container_name_end + 1:])
    container_slots = []
    ready_assignment = None
    for scope, owners in (("instance", container["instances"]), ("class", container["classes"])):
        for owner in owners:
            for item in owner["traits"]:
                multiname = container["multinames"][item["name"]]
                slot_name = container["strings"][multiname["name"]] if multiname and "name" in multiname else ""
                if slot_name in ("SetReadyState", "StartMatch", "StartMatchCountDown", "GetReadyState"):
                    type_name = container["multinames"][item["type_name"]] if "type_name" in item else None
                    type_string = container["strings"][type_name["name"]] if type_name and "name" in type_name else None
                    container_slots.append({**item, "string": slot_name, "scope": scope, "type_string": type_string})
                    if slot_name == "SetReadyState" and scope == "class":
                        ready_assignment = container_function_assignment(container, item["name"])
    if ready_assignment is None:
        raise ValueError("CFunctionContainer.SetReadyState static slot missing")
    ready_body = container["bodies"].get(ready_assignment["method_index"])
    ready_assignment["function_body"] = None if ready_body is None else {
        "code_hex": ready_body["code"].hex(),
        "code_sha256": hashlib.sha256(ready_body["code"]).hexdigest(),
        "code_length": len(ready_body["code"])}
    return {"schema": 1, "movie_sha256": SHA256, "doabc_tag_offset": hex(tag_offset),
            "doabc_name": tag_name, "doabc_flags": flags, "abc_version": abc["version"],
            "abc_counts": {"strings": len(abc["strings"]), "multinames": len(abc["multinames"]),
                           "methods": len(abc["methods"]), "bodies": len(abc["bodies"])},
            "focus_methods": focus, "named_multinames": named,
            "function_container": {"doabc_tag_offset": hex(container_tag),
                                   "doabc_name": "codo/common/CFunctionContainer",
                                   "matching_traits": container_slots,
                                   "ready_assignment": ready_assignment},
            "limit": "Ready handler instruction boundaries and callproperty operands decoded statically; event dispatch and native execution remain unverified."}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("movie", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = inspect(args.movie.read_bytes())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
