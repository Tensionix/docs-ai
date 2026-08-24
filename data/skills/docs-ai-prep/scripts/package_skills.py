#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pack the three docs-ai skills for import into other agents.

SKILL.md is an open standard now, so the same folders load into Codex, ChatGPT,
Grok and Gemini. What differs is delivery: CLI agents read them from disk, chat
interfaces want an upload. This writes both .zip and .skill (identical archives,
two names) so whichever dialog you meet accepts the file.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

SKILLS = ("docs-ai-prep", "docs-ai-audit", "docs-ai-report")
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def pack(skills_root: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name in SKILLS:
        source = skills_root / name
        if not (source / "SKILL.md").exists():
            print(f"[SKIP] {name}: no SKILL.md at {source}")
            continue

        archive = out_dir / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(source.rglob("*")):
                if item.is_dir() or any(part in SKIP_DIRS for part in item.parts):
                    continue
                if item.suffix in SKIP_SUFFIXES:
                    continue
                # SKILL.md must sit in the archive root for chat uploads to accept it.
                zf.write(item, item.relative_to(source).as_posix())

        twin = archive.with_suffix(".skill")
        shutil.copyfile(archive, twin)
        size = archive.stat().st_size
        print(f"[PACK] {name}: {size:,} bytes -> {archive.name}, {twin.name}")
        written.extend([archive, twin])

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Package docs-ai skills for other agents.")
    parser.add_argument("--skills-root", default="", help="folder holding the three skills (default: two levels up)")
    parser.add_argument("--out", default="", help="where to write archives (default: <skills-root>/_dist)")
    args = parser.parse_args()

    root = Path(args.skills_root).resolve() if args.skills_root else Path(__file__).resolve().parents[2]
    out = Path(args.out).resolve() if args.out else root / "_dist"

    written = pack(root, out)
    if not written:
        print("[PACK] nothing packed")
        return 1
    print(f"[PACK] {len(written)} files in {out}")
    print("[PACK] upload the .zip (or .skill) in the agent's skill dialog, or unpack into its skills folder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
