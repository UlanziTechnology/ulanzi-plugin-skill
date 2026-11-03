#!/usr/bin/env python3
"""Build the lightweight skill branch tree without copying plugin examples."""

import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "ulanzi-plugin"


def build_distribution(output: Path) -> Path:
    output = Path(output).resolve()
    if output == SOURCE or SOURCE in output.parents or output in SOURCE.parents:
        raise ValueError("Output must not overlap the skill source.")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if not (SOURCE / "SKILL.md").is_file():
        raise ValueError("Missing skills/ulanzi-plugin/SKILL.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE, output,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    (output / "README.md").write_text(
        "# Ulanzi Plugin Skill — lightweight distribution\n\n"
        "This branch is generated from `skills/ulanzi-plugin/` on main.\n"
        "It contains the skill, scripts, documentation, and device artwork. "
        "Plugin examples are downloaded only when requested.\n\n"
        "[Project, installation, and plugin examples]"
        "(https://github.com/UlanziTechnology/ulanzi-plugin-skill/tree/main)\n\n"
        "First-party code/documentation: [MIT](LICENSE). "
        "Device artwork: [separate restricted license]"
        "(assets/devices/LICENSE).\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "skill")
    args = parser.parse_args()
    try:
        output = build_distribution(args.out)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Lightweight distribution: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
