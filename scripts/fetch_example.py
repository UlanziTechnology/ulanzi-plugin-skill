#!/usr/bin/env python3
"""Fetch one example with Git partial clone and sparse checkout; never install it."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Optional

REPOSITORY = "https://github.com/UlanziTechnology/ulanzi-plugin-skill.git"
EXAMPLES = {
    "photoshop": "com.ulanzi.photoshop.ulanziPlugin",
    "lightroom": "com.ulanzi.AdobeLightroomClassic.ulanziPlugin",
    "aftereffects": "com.ulanzi.aftereffects.ulanziPlugin",
    "premiere": "com.ulanzi.premierepro.ulanziPlugin",
    "davinci": "com.ulanzi.davinciResolve.ulanziPlugin",
    "jianying": "com.ulanzi.jianying.ulanziPlugin",
}
SKILL_DIR = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Git is required; install Git and retry.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or "Git could not fetch the example.") from exc
    return result.stdout


def fetch_example(
    name: str, destination: Path, ref: str = "main", repository: str = REPOSITORY
) -> tuple[Path, str]:
    """Return the new plugin folder; keep downloads outside the installed skill."""
    folder = EXAMPLES[name]
    parent = Path(destination).expanduser().resolve()
    if parent == SKILL_DIR or SKILL_DIR in parent.parents:
        raise ValueError("Choose a workspace directory outside the installed skill.")
    target = parent / folder
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Destination already exists; nothing overwritten: {target}")

    with tempfile.TemporaryDirectory(prefix="ulanzi-example-source-") as temp:
        checkout = Path(temp) / "repository"
        git(
            "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
            "--single-branch", "--branch", ref, repository, str(checkout),
        )
        git("sparse-checkout", "set", "--cone", f"plugins/{folder}", cwd=checkout)
        git("checkout", "--quiet", cwd=checkout)
        source = checkout / "plugins" / folder
        if not (source / "manifest.json").is_file():
            raise RuntimeError(f"Example {name} is missing from ref {ref}.")
        revision = git("rev-parse", "HEAD", cwd=checkout).strip()
        parent.mkdir(parents=True, exist_ok=True)
        # Stage on the destination filesystem so failed copies leave no partial plugin.
        with tempfile.TemporaryDirectory(prefix=".ulanzi-example-", dir=parent) as stage:
            staged = Path(stage) / folder
            shutil.copytree(source, staged, symlinks=True)
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"Destination already exists: {target}")
            staged.rename(target)
    return target, revision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", nargs="?", choices=EXAMPLES)
    parser.add_argument("--list", action="store_true", help="List examples without network access")
    parser.add_argument("--dest", type=Path, help="Workspace parent directory for the downloaded plugin")
    parser.add_argument("--ref", default="main", help="Source branch or tag (default: main)")
    args = parser.parse_args()
    if args.list:
        for name, folder in EXAMPLES.items():
            print(f"{name}: {folder}")
        return 0
    if not args.example or args.dest is None:
        parser.error("provide an example and --dest, or use --list")
    try:
        target, revision = fetch_example(args.example, args.dest, args.ref)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Downloaded: {target}\nSource commit: {revision}\nNo plugin or companion installer was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
