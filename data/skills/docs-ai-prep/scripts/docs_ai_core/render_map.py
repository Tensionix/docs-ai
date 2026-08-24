from __future__ import annotations

from typing import Any, Dict, List


def build_render_map(block_map: Dict[str, Any], pages_payload: Dict[str, Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    pages = pages_payload.get("pages", []) or []

    for block in block_map.get("blocks", []) or []:
        marker = block.get("marker") or f"AUDION_BLOCK_{block.get('block_id', '')}"
        found = _find_marker(marker, pages)
        if found:
            entry = {
                "block_id": block["block_id"],
                "page": found["page"],
                "page_source": "pdf_marker",
                "page_confidence": "high",
                "bbox": found.get("bbox"),
                "marker": marker,
            }
        else:
            entry = {
                "block_id": block["block_id"],
                "page": None,
                "page_source": "unavailable",
                "page_confidence": "unavailable",
                "bbox": None,
                "marker": marker,
            }
        entries.append(entry)

    found_count = sum(1 for item in entries if item["page"] is not None)
    return {
        "source_relative_path": block_map.get("source_relative_path", ""),
        "status": "ok" if found_count else "unavailable",
        "found_markers": found_count,
        "total_blocks": len(entries),
        "entries": entries,
    }


def _find_marker(marker: str, pages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for page in pages:
        text = page.get("text") or ""
        if marker not in text:
            continue
        for word in page.get("words", []) or []:
            if word.get("text") == marker:
                return {"page": page.get("page"), "bbox": word.get("bbox")}
        return {"page": page.get("page"), "bbox": None}
    return None


def render_entry_by_block(render_map: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {entry["block_id"]: entry for entry in render_map.get("entries", []) or []}


def build_human_location(block: Dict[str, Any], render_entry: Dict[str, Any] | None = None) -> str:
    technical = block.get("technical_location", {}) or {}
    parts: list[str] = []
    page = (render_entry or {}).get("page")

    if page:
        if "slide_index" in technical:
            parts.append(f"Слайд {page}")
        else:
            parts.append(f"Страница {page}")
    elif "slide_index" in technical:
        parts.append(f"Слайд {technical.get('slide_index')}")

    if technical.get("table_index"):
        parts.append(f"Таблица {technical.get('table_index')}")
    if technical.get("row_index"):
        parts.append(f"строка {technical.get('row_index')}")
    if technical.get("cell_index"):
        parts.append(f"ячейка {technical.get('cell_index')}")
    if technical.get("paragraph_index") and not technical.get("table_index"):
        parts.append(f"абзац {technical.get('paragraph_index')}")

    return ", ".join(parts) if parts else block.get("block_id", "")
