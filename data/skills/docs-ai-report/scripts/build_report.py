#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the deliverables from the per-chunk findings.

Same output as the desktop program: an XLSX error map, a DOCX report and a copy of
the document with anchors next to every problem place. All of it is deterministic -
findings are matched to blocks, given a page-level human location, de-duplicated and
numbered E001..Ennn in document order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_ai_core.reporting import (
    normalize_issues,
    strip_error_anchors_from_document,
    unanchored_output_path,
    write_annotated_document,
    write_audit_docx,
    write_audit_table,
    write_json,
)


def collect_raw_findings(work: Path, manifest: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    """Read findings in chunk order so issue numbering follows the document."""
    raw: List[Dict[str, Any]] = []
    missing: List[str] = []
    for chunk in manifest.get("chunks", []):
        path = work / chunk["findings"]
        if not path.exists():
            missing.append(chunk["id"])
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else (payload.get("findings") or [])
        for item in items:
            if isinstance(item, dict):
                raw.append({**item, "chunk_id": chunk["id"]})
    return raw, missing


def dedupe(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Overlap between chunks makes the same place reachable twice."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for issue in issues:
        key = (
            issue.get("block_id"),
            " ".join(str(issue.get("quote") or "").split()),
            " ".join(str(issue.get("problem") or "").split()),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def renumber(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for index, issue in enumerate(issues, start=1):
        issue["issue_id"] = f"E{index:03d}"
    return issues


def build(work: Path, out_dir: Path, report_lang: str, allow_incomplete: bool) -> int:
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    block_map = json.loads((work / "block_map.json").read_text(encoding="utf-8"))
    render_map = json.loads((work / "render_map.json").read_text(encoding="utf-8"))
    source = Path(manifest["source"])

    raw, missing = collect_raw_findings(work, manifest)
    if missing and not allow_incomplete:
        print(f"[ERROR] {len(missing)} chunks have no findings file: {', '.join(missing[:10])}")
        print("[ERROR] finish the sweep, or pass --allow-incomplete to report on what exists.")
        return 1

    issues = renumber(dedupe(normalize_issues(raw, block_map, render_map)))
    dropped = len(raw) - len(issues)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(source),
        "source_relative_path": block_map.get("source_relative_path", source.name),
        "status": "partial" if missing else "complete",
        "chunks_total": len(manifest.get("chunks", [])),
        "chunks_reviewed": len(manifest.get("chunks", [])) - len(missing),
        "issues": issues,
    }
    write_json(out_dir / f"{source.stem}__audit.json", payload)

    table = out_dir / f"{source.stem}__audit_table.xlsx"
    write_audit_table(table, issues, report_lang)

    report = out_dir / f"{source.stem}__audit_report.docx"
    write_audit_docx(report, source.name, payload, report_lang)

    annotated = out_dir / f"{source.stem}__annotated{source.suffix}"
    write_annotated_document(source, annotated, block_map, issues, out_dir / f"{source.stem}__annotation.json")
    anchored = len({issue.get("block_id") for issue in issues if issue.get("block_id")})

    print(f"[REPORT] issues={len(issues)} (dropped as duplicate/unmatched: {dropped})")
    print(f"[REPORT] pages known for {sum(1 for i in issues if i.get('page'))} of them")
    print(f"[REPORT] {table.name}")
    print(f"[REPORT] {report.name}")
    print(f"[REPORT] {annotated.name} (anchors placed: {anchored})")
    if missing:
        print(f"[REPORT] WARNING: partial report, {len(missing)} chunks were never reviewed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the audit table, report and anchored copy.")
    parser.add_argument("--work", required=True, help="workspace created by docs-ai-prep")
    parser.add_argument("--out", default="", help="output directory (default: <work>/output)")
    parser.add_argument("--report-lang", default="ru", choices=["ru", "en"])
    parser.add_argument("--allow-incomplete", action="store_true", help="report even if some chunks were skipped")
    parser.add_argument("--strip-anchors", default="", help="instead: remove anchors from this annotated document")
    args = parser.parse_args()

    if args.strip_anchors:
        source = Path(args.strip_anchors).resolve()
        out = unanchored_output_path(source)
        removed = strip_error_anchors_from_document(source, out)
        print(f"[STRIP] removed {removed} anchors -> {out.name}")
        return 0

    work = Path(args.work).resolve()
    out_dir = Path(args.out).resolve() if args.out else work / "output"
    return build(work, out_dir, args.report_lang, args.allow_incomplete)


if __name__ == "__main__":
    raise SystemExit(main())
