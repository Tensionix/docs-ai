#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keeps the chunk sweep honest.

A loop cannot skip a chunk; an agent can. This script is the bookkeeping that makes
skipping visible: it knows every chunk that must be reviewed, checks the findings
files against a strict shape, and refuses to call the audit complete while anything
is missing or malformed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

FIX_MODES = {"safe_replace", "requires_review"}
CONFIDENCE = {"high", "medium", "low"}
REQUIRED = ("block_id", "quote", "violation", "fix", "fix_mode", "confidence")


def load_manifest(work: Path) -> Dict[str, Any]:
    path = work / "manifest.json"
    if not path.exists():
        raise SystemExit(f"[ERROR] manifest.json not found in {work}. Run docs-ai-prep first.")
    return json.loads(path.read_text(encoding="utf-8"))


def known_block_ids(work: Path) -> set[str]:
    block_map = json.loads((work / "block_map.json").read_text(encoding="utf-8"))
    return {str(block.get("block_id")) for block in block_map.get("blocks", []) or []}


def flatten(text: str) -> str:
    return " ".join(str(text or "").split())


def check_file(path: Path, chunk_id: str, blocks: set[str], chunk_text: str = "") -> tuple[int, List[str]]:
    """Return (finding count, problems). An empty findings list is a valid answer."""
    problems: List[str] = []
    haystack = flatten(chunk_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 0, [f"{chunk_id}: broken JSON ({exc.msg} at line {exc.lineno})"]

    if isinstance(payload, list):
        findings = payload
    elif isinstance(payload, dict):
        findings = payload.get("findings")
        if findings is None:
            return 0, [f"{chunk_id}: object without a 'findings' key"]
    else:
        return 0, [f"{chunk_id}: expected an object or a list"]

    if not isinstance(findings, list):
        return 0, [f"{chunk_id}: 'findings' must be a list"]

    for position, item in enumerate(findings, start=1):
        where = f"{chunk_id}[{position}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: not an object")
            continue
        for key in REQUIRED:
            if not str(item.get(key) or "").strip():
                problems.append(f"{where}: empty required field '{key}'")
        block_id = str(item.get("block_id") or "").strip()
        if block_id and block_id not in blocks:
            problems.append(f"{where}: unknown block_id '{block_id}'")
        mode = str(item.get("fix_mode") or "").strip()
        if mode and mode not in FIX_MODES:
            problems.append(f"{where}: fix_mode must be one of {sorted(FIX_MODES)}")
        conf = str(item.get("confidence") or "").strip()
        if conf and conf not in CONFIDENCE:
            problems.append(f"{where}: confidence must be one of {sorted(CONFIDENCE)}")
        if mode == "safe_replace":
            old, new = str(item.get("old_text") or ""), str(item.get("new_text") or "")
            if not old or not new:
                problems.append(f"{where}: safe_replace needs both old_text and new_text")
            elif old == new:
                problems.append(f"{where}: old_text equals new_text, the fix changes nothing")
            elif haystack and flatten(old) not in haystack:
                problems.append(f"{where}: old_text is not in the chunk, the replacement cannot be applied")

        # A paraphrased quote looks exactly like a real finding but points nowhere:
        # the anchor cannot be placed and nobody can verify it. Catch it mechanically.
        quote = flatten(item.get("quote"))
        if haystack and quote and quote not in haystack:
            problems.append(f"{where}: quote is not in the chunk verbatim — «{quote[:60]}»")
    return len(findings), problems


def survey(work: Path) -> Dict[str, Any]:
    manifest = load_manifest(work)
    blocks = known_block_ids(work)
    done: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    problems: List[str] = []
    total_findings = 0

    for chunk in manifest.get("chunks", []):
        path = work / chunk["findings"]
        if not path.exists():
            pending.append(chunk)
            continue
        chunk_text = (work / chunk["file"]).read_text(encoding="utf-8") if (work / chunk["file"]).exists() else ""
        count, issues = check_file(path, chunk["id"], blocks, chunk_text)
        total_findings += count
        problems.extend(issues)
        done.append({**chunk, "findings_count": count})

    return {
        "manifest": manifest,
        "done": done,
        "pending": pending,
        "problems": problems,
        "total_findings": total_findings,
    }


def cmd_status(work: Path, verbose: bool) -> int:
    state = survey(work)
    total = len(state["manifest"].get("chunks", []))
    done, pending = len(state["done"]), len(state["pending"])
    print(f"[AUDIT] chunks {done}/{total} reviewed, findings so far: {state['total_findings']}")
    if pending:
        preview = ", ".join(chunk["id"] for chunk in state["pending"][:10])
        more = "" if pending <= 10 else f" (+{pending - 10} more)"
        print(f"[AUDIT] not reviewed yet: {preview}{more}")
    if state["problems"]:
        print(f"[AUDIT] {len(state['problems'])} problems in written findings:")
        for line in state["problems"][: (200 if verbose else 15)]:
            print(f"   - {line}")
    if not pending and not state["problems"]:
        print("[AUDIT] complete: every chunk reviewed and every finding well-formed.")
        return 0
    return 1


def cmd_next(work: Path, count: int) -> int:
    state = survey(work)
    batch = state["pending"][:count]
    if not batch:
        print("[AUDIT] nothing pending.")
        return 0
    for chunk in batch:
        path = (work / chunk["file"]).as_posix()
        print(f"{chunk['id']}\t{path}\t~{chunk['tokens']} tokens\t{chunk['blocks']} blocks")
    return 0


def cmd_validate(work: Path) -> int:
    state = survey(work)
    if state["problems"]:
        print(f"[AUDIT] {len(state['problems'])} problems:")
        for line in state["problems"]:
            print(f"   - {line}")
        return 1
    print(f"[AUDIT] all written findings are well-formed ({state['total_findings']} total).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Track and validate the chunk sweep.")
    parser.add_argument("command", choices=["status", "next", "validate"])
    parser.add_argument("--work", required=True, help="workspace created by docs-ai-prep")
    parser.add_argument("--count", type=int, default=5, help="how many pending chunks to list")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    work = Path(args.work).resolve()
    if args.command == "status":
        return cmd_status(work, args.verbose)
    if args.command == "next":
        return cmd_next(work, args.count)
    return cmd_validate(work)


if __name__ == "__main__":
    raise SystemExit(main())
