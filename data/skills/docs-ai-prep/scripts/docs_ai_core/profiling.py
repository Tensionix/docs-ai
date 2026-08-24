#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decide how much thinking each chunk deserves.

Two kinds of errors live in these documents and they need different attention.
Grammar, typography and spelling are pattern matching - a small model with no
reasoning budget catches them fine. Broken arithmetic, a number that cannot be
true, a gap in a numbered series - those need the model to hold values side by
side and compare, which is exactly what reasoning is for.

The signals are visible before any model looks at the text, so routing is decided
here: chunks made of prose go to a cheap fast pass, chunks dense with tables and
figures go to a reasoning pass.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

NUMBER_RE = re.compile(r"\d[\d\s.,]*")
SERIES_RE = re.compile(r"^\s*(\d{1,4})\s*[.)]?\s*$")

# A chunk goes deep when tables dominate or numbers are dense enough that
# arithmetic and sequence errors become likely.
TABLE_SHARE_DEEP = 0.45
NUMBER_DENSITY_DEEP = 0.06
SERIES_LENGTH_DEEP = 8


def _numeric_density(text: str) -> float:
    if not text:
        return 0.0
    digits = sum(1 for ch in text if ch.isdigit())
    return digits / len(text)


def _longest_numeric_series(blocks: List[Dict[str, Any]]) -> int:
    """Longest run of blocks that are just an integer - the shape of a numbered column."""
    best = run = 0
    previous: int | None = None
    for block in blocks:
        text = str(block.get("text") or "")
        body = text.split("\n", 1)[1] if "\n" in text else text
        match = SERIES_RE.match(body)
        if not match:
            previous, run = None, 0
            continue
        value = int(match.group(1))
        run = run + 1 if previous is not None and value in (previous + 1, previous) else 1
        previous = value
        best = max(best, run)
    return best


def profile_chunk(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe a chunk and recommend a review depth."""
    total = len(blocks) or 1
    table_blocks = sum(1 for b in blocks if "tbl" in str(b.get("block_id") or ""))
    body = "\n".join(str(b.get("text") or "") for b in blocks)

    table_share = table_blocks / total
    density = _numeric_density(body)
    series = _longest_numeric_series(blocks)

    reasons: List[str] = []
    if table_share >= TABLE_SHARE_DEEP:
        reasons.append(f"tables {table_share:.0%} of blocks")
    if density >= NUMBER_DENSITY_DEEP:
        reasons.append(f"digits {density:.1%} of characters")
    if series >= SERIES_LENGTH_DEEP:
        reasons.append(f"numbered run of {series}")

    return {
        "profile": "deep" if reasons else "light",
        "reasons": reasons,
        "table_share": round(table_share, 3),
        "number_density": round(density, 4),
        "longest_series": series,
    }
