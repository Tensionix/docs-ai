#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Splitting a document into chunks an agent can actually read carefully.

Whole-document review degrades badly: given 500 pages at once a model skims and
reports a fraction of what is there. Chunks force it to grind through every line.
The size is therefore a quality knob, not a throughput knob - 32k-64k real tokens
is the working range, above that attention starts to thin out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Token cost differs by script: Latin packs ~4 characters into a token, while
# Cyrillic, Greek, CJK and similar are far denser per byte and land near ~1.8.
# Counting both separately keeps the estimate honest for any language, so a
# requested 48000-token chunk really is about 48000 tokens.
LATIN_CHARS_PER_TOKEN = 4.0
OTHER_CHARS_PER_TOKEN = 1.8


def estimate_tokens(text: str) -> int:
    """Estimate tokens without a tokenizer dependency, script-aware."""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other_chars = len(text) - ascii_chars
    estimate = ascii_chars / LATIN_CHARS_PER_TOKEN + other_chars / OTHER_CHARS_PER_TOKEN
    return max(1, int(estimate))


def block_token_cost(block: Dict[str, Any]) -> int:
    """Text already carries its [BLOCK:id] header, so it is the whole cost."""
    return estimate_tokens(str(block.get("text") or "")) + 2


def build_chunks(
    blocks: List[Dict[str, Any]],
    *,
    chunk_tokens: int,
    overlap_tokens: int,
    min_chunks: int = 1,
) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """Group blocks into (overlap, chunk) pairs.

    Blocks are never split in the middle: a chunk boundary always falls between
    two blocks, so every quote stays inside exactly one addressable place.
    """
    costs = [block_token_cost(block) for block in blocks]
    total = sum(costs)

    effective = int(chunk_tokens)
    if min_chunks and min_chunks > 1 and total > 0:
        effective = min(effective, max(4000, total // min_chunks))

    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_tokens = 0

    for block, cost in zip(blocks, costs):
        if current and current_tokens + cost > effective:
            chunks.append(current)
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += cost
    if current:
        chunks.append(current)

    def tail(previous: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        picked: List[Dict[str, Any]] = []
        spent = 0
        for block in reversed(previous):
            cost = block_token_cost(block)
            if spent + cost > overlap_tokens and picked:
                break
            picked.insert(0, block)
            spent += cost
        return picked

    pairs: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
    previous: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        pairs.append((tail(previous) if index > 0 and overlap_tokens > 0 else [], chunk))
        previous = chunk
    return pairs


def render_chunk_text(overlap: List[Dict[str, Any]], chunk: List[Dict[str, Any]]) -> str:
    """Lay a chunk out for reading: context first, then the part under review."""

    def fmt(blocks: List[Dict[str, Any]]) -> str:
        return "\n\n".join(str(block["text"]) for block in blocks)

    parts: List[str] = []
    if overlap:
        parts.append("## КОНТЕКСТ ИЗ ПРЕДЫДУЩЕЙ ЧАСТИ (не проверяется, нужен для связности)\n")
        parts.append(fmt(overlap))
        parts.append("\n")
    parts.append("## ТЕКСТ НА ПРОВЕРКУ\n")
    parts.append(fmt(chunk))
    return "\n".join(parts).strip() + "\n"
