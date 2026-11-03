#!/usr/bin/env python3
"""Check the source distribution's license inventory and Qt exclusion offline."""

import argparse
import email
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"pyqt5", "pyqt5-qt5", "pyqt5-sip"}


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def check_distribution(root: Path) -> list[str]:
    root = root.resolve()
    errors = []
    try:
        records = json.loads((root / "licenses/provenance.json").read_text())["licenses"]
        if not isinstance(records, list):
            raise ValueError("licenses must be an array")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"Cannot read license inventory: {exc}"]
    covered = set()
    for record in records:
        try:
            if not isinstance(record, dict):
                raise ValueError("expected license object")
            component, version, relative, expected = (
                record[key] for key in ("component", "version", "file", "sha256")
            )
            if not all(isinstance(value, str) and value for value in (component, version, relative, expected)):
                raise ValueError("license fields must be nonempty strings")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("license path escapes the plugin")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"license hash mismatch: {relative}")
            covered.add((canonical_name(component), version))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"Invalid license record: {exc}")
    for folder in ("site-packages", "site-packages-macos"):
        directory = root / folder
        if (directory / "PyQt5").exists():
            errors.append(f"Excluded Qt runtime present: {folder}/PyQt5")
        for metadata in directory.glob("*.dist-info/METADATA"):
            package = email.message_from_bytes(metadata.read_bytes())
            name, version = package.get("Name", ""), package.get("Version", "")
            if canonical_name(name) in EXCLUDED:
                errors.append(f"Excluded Qt package present: {name} {version}")
            elif not name or not version or (canonical_name(name), version) not in covered:
                errors.append(f"Missing versioned license notice: {name} {version}")
    for required in ("LICENSE", "THIRD_PARTY_NOTICES.md", "requirements-qt-macos.txt"):
        if not (root / required).is_file():
            errors.append(f"Missing distribution document: {required}")
    return errors


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    errors = check_distribution(ROOT)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("OK: versioned license notices verified; no PyQt5/Qt runtime redistributed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
