#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn one document into an auditable workspace: block map, page map, chunks.

Nothing here calls a model. The point is to give the agent addressable text: every
paragraph and every table cell gets an id it can cite, and - when Word is available
- a page number, so a finding reads "page 23, table 22, row 31, cell 3" instead of
"somewhere in the document".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_ai_core import chunking
from docs_ai_core.profiling import profile_chunk
from docs_ai_core.presets import DEFAULT_PRESET, PRESETS, assignment, resolve_preset
from docs_ai_core.platforms import DEFAULT_PLATFORM, PLATFORMS, resolve_platform
from docs_ai_core.document_model import build_block_map, create_marked_copy
from docs_ai_core.pdf_text import extract_pdf_pages
from docs_ai_core.render_map import build_render_map
from docs_ai_core.reporting import blocks_for_llm, sha256_file, write_json


def prepare(
    source: Path,
    work: Path,
    *,
    preset_name: str,
    platform_name: str,
    text_tokens: int | None,
    table_tokens: int | None,
    overlap_tokens: int,
    min_chunks: int,
    render_pages: bool,
    pdf_path: Path | None,
) -> dict:
    preset = resolve_preset(preset_name)
    platform = resolve_platform(platform_name)
    text_budget = int(text_tokens or preset["text"]["chunk_tokens"])
    table_budget = int(table_tokens or preset["table"]["chunk_tokens"])
    work.mkdir(parents=True, exist_ok=True)
    chunks_dir = work / "chunks"
    chunks_dir.mkdir(exist_ok=True)
    (work / "findings").mkdir(exist_ok=True)

    block_map = build_block_map(source, source.parent)
    write_json(work / "block_map.json", block_map)

    render_map: dict = {"status": "skipped", "entries": []}
    if render_pages or pdf_path:
        marked = work / f"{source.stem}__marked{source.suffix}"
        create_marked_copy(source, marked, block_map)
        pdf = pdf_path
        if pdf is None:
            from docs_ai_core.com_render import ExportError, export_to_pdf

            try:
                pdf = export_to_pdf(marked, work / f"{source.stem}__marked.pdf")
            except ExportError as exc:
                render_map = {"status": f"failed: {exc}", "entries": []}
                pdf = None
        if pdf is not None:
            pages = extract_pdf_pages(Path(pdf))
            render_map = build_render_map(block_map, pages)
    write_json(work / "render_map.json", render_map)

    blocks = blocks_for_llm(block_map)
    pairs = chunking.build_chunks(
        blocks,
        chunk_tokens=text_budget,
        table_chunk_tokens=table_budget,
        overlap_tokens=overlap_tokens,
        min_chunks=min_chunks,
    )

    manifest_chunks = []
    for index, (overlap, chunk) in enumerate(pairs, start=1):
        name = f"chunk_{index:03d}"
        text = chunking.render_chunk_text(overlap, chunk)
        (chunks_dir / f"{name}.md").write_text(text, encoding="utf-8")
        manifest_chunks.append(
            {
                "id": name,
                "index": index,
                "file": f"chunks/{name}.md",
                "findings": f"findings/{name}.json",
                "blocks": len(chunk),
                "tokens": chunking.estimate_tokens(text),
                "first_block": chunk[0]["block_id"] if chunk else "",
                "last_block": chunk[-1]["block_id"] if chunk else "",
                **profile_chunk(chunk),
            }
        )

    for item in manifest_chunks:
        item.update(assignment(preset, item["profile"], platform))

    with_page = sum(1 for entry in render_map.get("entries") or [] if entry.get("page"))
    deep = sum(1 for item in manifest_chunks if item["profile"] == "deep")
    manifest = {
        "schema_version": 1,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "work_dir": str(work),
        "settings": {
            "preset": preset_name,
            "preset_title": preset["title"],
            "platform": platform_name,
            "platform_title": platform["title"],
            "text_chunk_tokens": text_budget,
            "table_chunk_tokens": table_budget,
            "overlap_tokens": overlap_tokens,
            "min_chunks": min_chunks,
        },
        "totals": {
            "blocks": len(blocks),
            "chunks": len(manifest_chunks),
            "tokens": sum(item["tokens"] for item in manifest_chunks),
            "blocks_with_page": with_page,
            "deep_chunks": deep,
            "light_chunks": len(manifest_chunks) - deep,
            "assignments": {
                f"{item['role']} ({item['model']}) / {item['effort']}": sum(
                    1 for other in manifest_chunks
                    if other["role"] == item["role"] and other["effort"] == item["effort"]
                )
                for item in manifest_chunks
            },
        },
        "render_status": render_map.get("status", "skipped"),
        "chunks": manifest_chunks,
    }
    write_json(work / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a document for chunked audit.")
    parser.add_argument("--source", required=True, help="DOCX or PPTX to audit")
    parser.add_argument("--work", default="", help="workspace directory (default: <source>__audit next to the file)")
    parser.add_argument(
        "--preset",
        default=DEFAULT_PRESET,
        choices=sorted(PRESETS),
        help="how much attention the document deserves: " + "; ".join(f"{k} - {v['use_when']}" for k, v in PRESETS.items()),
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        choices=sorted(PLATFORMS),
        help="which agent will run the audit: " + ", ".join(f"{k} ({v['title']})" for k, v in PLATFORMS.items()),
    )
    parser.add_argument("--text-chunk-tokens", type=int, default=0, help="override chunk size for prose")
    parser.add_argument("--table-chunk-tokens", type=int, default=0, help="override chunk size for tables")
    parser.add_argument("--overlap-tokens", type=int, default=2000, help="context carried over from the previous chunk")
    parser.add_argument("--min-chunks", type=int, default=1, help="force at least N chunks")
    parser.add_argument("--no-pages", action="store_true", help="skip the Word export, findings will have no page numbers")
    parser.add_argument("--pdf", default="", help="use this PDF of the MARKED copy instead of exporting one")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        print(f"[ERROR] source not found: {source}")
        return 1
    if source.suffix.lower() not in {".docx", ".pptx"}:
        print(f"[ERROR] unsupported type: {source.suffix} (expected .docx or .pptx)")
        return 1

    work = Path(args.work).resolve() if args.work else source.parent / f"{source.stem}__audit"
    manifest = prepare(
        source,
        work,
        preset_name=args.preset,
        platform_name=args.platform,
        text_tokens=args.text_chunk_tokens or None,
        table_tokens=args.table_chunk_tokens or None,
        overlap_tokens=args.overlap_tokens,
        min_chunks=args.min_chunks,
        render_pages=not args.no_pages,
        pdf_path=Path(args.pdf).resolve() if args.pdf else None,
    )

    totals = manifest["totals"]
    print(f"[PREP] {Path(manifest['source']).name}")
    print(f"[PREP] blocks={totals['blocks']} chunks={totals['chunks']} tokens={totals['tokens']:,}")
    settings = manifest["settings"]
    print(f"[PREP] platform: {settings['platform']} ({settings['platform_title']})")
    print(f"[PREP] preset: {settings['preset']} ({settings['preset_title']}), "
          f"chunks: prose {settings['text_chunk_tokens']:,} / tables {settings['table_chunk_tokens']:,} tokens")
    print(f"[PREP] review depth: {totals['deep_chunks']} deep (tables/numbers), {totals['light_chunks']} light (prose)")
    for model_effort, count in sorted(totals["assignments"].items()):
        print(f"[PREP]   {model_effort}: {count} chunks")
    print(f"[PREP] pages: {manifest['render_status']} (blocks with page: {totals['blocks_with_page']})")
    print(f"[PREP] workspace: {manifest['work_dir']}")
    print(f"[PREP] next: read chunks one by one, write findings/<chunk_id>.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
