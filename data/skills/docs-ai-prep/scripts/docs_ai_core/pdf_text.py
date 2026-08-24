from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def extract_pdf_pages(pdf_path: Path) -> Dict[str, Any]:
    import fitz

    pages: List[Dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc, start=1):
            words = []
            for item in page.get_text("words"):
                x0, y0, x1, y1, text, block_no, line_no, word_no = item[:8]
                words.append(
                    {
                        "text": text,
                        "bbox": [float(x0), float(y0), float(x1), float(y1)],
                        "block": int(block_no),
                        "line": int(line_no),
                        "word": int(word_no),
                    }
                )
            pages.append(
                {
                    "page": page_index,
                    "text": page.get_text("text"),
                    "words": words,
                }
            )
    return {"pdf_path": str(pdf_path), "pages": pages}


def write_pdf_pages(pdf_path: Path, out_json: Path) -> Dict[str, Any]:
    payload = extract_pdf_pages(pdf_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
