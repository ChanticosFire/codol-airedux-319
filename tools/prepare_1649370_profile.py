"""Copy the community save to 319-owned SQLite files and set its display name."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

COMMUNITY = Path(r"E:\GAME\COD\1649370")
SOURCE = COMMUNITY / "data/accounts"
TARGET = Path(__file__).resolve().parents[1] / "data/v1649370"
NAME = "南韩超人朴玄俊"
sys.path.insert(0, str(COMMUNITY / "src"))

from codol_rebuild.adapters.persistence.sqlite_accounts import AccountRepository  # noqa: E402
from codol_rebuild.application.accounts.service import change_display_name  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_if_absent(name: str) -> dict:
    source, target = SOURCE / name, TARGET / name
    if target.exists():
        return {"source": str(source), "target": str(target), "copied": False,
                "source_sha256": sha256(source)}
    TARGET.mkdir(parents=True, exist_ok=True)
    temporary = TARGET / (name + ".tmp")
    if temporary.exists():
        raise ValueError(f"临时副本已存在: {temporary}")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(temporary)) as copy:
            original.backup(copy)
    temporary.replace(target)
    return {"source": str(source), "target": str(target), "copied": True,
            "source_sha256": sha256(source)}


def main() -> None:
    copies = [copy_if_absent(name) for name in ("local.sqlite3", "game-settings.sqlite3")]
    repository = AccountRepository(TARGET / "local.sqlite3")
    before = repository.display_name("local")
    after = before if before["value"] == NAME else change_display_name(
        repository, before["revision"], NAME)
    with closing(sqlite3.connect((TARGET / "local.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        account = db.execute("SELECT uid,revision FROM accounts WHERE name='local'").fetchone()
        kinds = [row[0] for row in db.execute("SELECT kind FROM profiles WHERE account='local'")]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok" or sorted(kinds) != ["public", "secure"]:
        raise ValueError("私有档案完整性或双档案检查失败")
    print(json.dumps({"schema": 1, "display_name_before": before,
                      "display_name_after": after, "uid": account[0],
                      "account_revision": account[1], "profile_kinds": kinds,
                      "integrity_check": integrity, "copies": copies,
                      "local_sha256": sha256(TARGET / "local.sqlite3"),
                      "settings_sha256": sha256(TARGET / "game-settings.sqlite3")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
