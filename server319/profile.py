"""Player profile store for the offline lobby.

There is no server-side profile in the retail service, which is why every launch
shows the character-select / codename screens. This module keeps a complete
profile on disk so one account can be reused across sessions.

Fields mirror the community reference data in
codol-ember/.../launch319-reference/reference/launch/svc80_data/playerdata.json:

    level, prestige, wallet {gp, cp}, entitlements, unlock_flags

plus the fields the client needs to treat the account as established:

    name, codename_set, created, last_seen, user_id

Usage:
    from server319.profile import ProfileStore
    store = ProfileStore(Path("runtime/profile.json"))
    profile = store.get_or_create("1")
    profile["wallet"]["gp"] = 999999999
    store.save(profile)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_PROFILE: dict[str, Any] = {
    "schema": 1,
    "user_id": "1",
    "name": "Player",
    "codename_set": True,
    "created": 0,
    "last_seen": 0,
    "level": 70,
    "prestige": 0,
    "wallet": {"gp": 999999999, "cp": 999999999},
    "entitlements": [],
    "unlock_flags": [],
    "stats": {},
}


def _now() -> int:
    return int(time.time())


class ProfileStore:
    """Single-file JSON profile store with atomic writes."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._cache: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        data: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                data = {}
        self._cache = data
        return data

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._load().get(str(user_id))

    def get_or_create(self, user_id: str, name: str | None = None) -> dict[str, Any]:
        data = self._load()
        key = str(user_id)
        profile = data.get(key)
        if profile is None:
            profile = json.loads(json.dumps(DEFAULT_PROFILE))
            profile["user_id"] = key
            profile["created"] = _now()
            if name:
                profile["name"] = name
            data[key] = profile
            self.save(profile)
        return profile

    def mark_seen(self, profile: dict[str, Any]) -> None:
        profile["last_seen"] = _now()
        self.save(profile)

    def save(self, profile: dict[str, Any]) -> None:
        data = self._load()
        data[str(profile.get("user_id", "1"))] = profile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- wire encoders -------------------------------------------------

    def playerdata_bytes(self, profile: dict[str, Any]) -> bytes:
        """svc255/task60049 payload, matching bdsvc319's 60049 shape.

        bdsvc319 writes: u32 level, u32 prestige, u32 gp, u32 cp,
                         u32 ent_count, u32 flags_count
        """
        import struct
        return (struct.pack("<I", int(profile.get("level", 70)))
                + struct.pack("<I", int(profile.get("prestige", 0)))
                + struct.pack("<I", int(profile.get("wallet", {}).get("gp", 0)))
                + struct.pack("<I", int(profile.get("wallet", {}).get("cp", 0)))
                + struct.pack("<I", len(profile.get("entitlements") or []))
                + struct.pack("<I", len(profile.get("unlock_flags") or [])))

    def balance_bytes(self, profile: dict[str, Any], currency: int = 2) -> bytes:
        """svc80 getBalance payload: u8 currency + u32 balance."""
        import struct
        key = "cp" if currency == 1 else "gp"
        return bytes([currency]) + struct.pack(
            "<I", int(profile.get("wallet", {}).get(key, 0)))


def default_store() -> ProfileStore:
    root = Path(__file__).resolve().parents[1]
    return ProfileStore(root / "runtime" / "profile.json")
