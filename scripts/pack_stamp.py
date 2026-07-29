#!/usr/bin/env python3
"""Stamp APP_VERSION + pack ledger entry. Usage: pack_stamp.py <version> <area> <summary>"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def set_version(ver: str) -> None:
    (ROOT / "api/app/version.py").write_text(
        f'''"""Single runtime version for FastAPI metadata and /health."""\n\nAPP_VERSION = "{ver}"\n'''
    )
    for rel, key in (
        ("mobile/package.json", None),
        ("mobile/app.json", "expo"),
        ("mobile/package-lock.json", "lock"),
    ):
        p = ROOT / rel
        data = json.loads(p.read_text())
        if key == "expo":
            data["expo"]["version"] = ver
        elif key == "lock":
            data["version"] = ver
            if "" in data.get("packages", {}):
                data["packages"][""]["version"] = ver
        else:
            data["version"] = ver
        p.write_text(json.dumps(data, indent=2) + "\n")

def append_ledger(ver: str, area: str, summary: str) -> None:
    path = ROOT / "docs/PACK_LEDGER.md"
    text = path.read_text()
    line = f"{ver} | {area} | {summary}\n"
    if f"{ver} |" in text:
        return
    path.write_text(text.rstrip() + "\n" + line)

def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: pack_stamp.py VERSION AREA SUMMARY")
    ver, area, summary = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])
    set_version(ver)
    append_ledger(ver, area, summary)
    print(ver)

if __name__ == "__main__":
    main()
