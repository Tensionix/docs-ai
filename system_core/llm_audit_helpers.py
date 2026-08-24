#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM prompt/chunk helpers for the DOCX/PPTX pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from config_resolver import resolve_prompt

try:
    from rules_resolver import load_active_rules
except ImportError:  # package import path used by GUI/unit checks
    from system_core.rules_resolver import load_active_rules


def estimate_tokens_rough(text: str) -> int:
    return max(1, len(text) // 3)


def load_rules(_rules_dir: Path | None = None) -> str:
    return load_active_rules()


def build_chunks(
    blocks: List[Dict[str, Any]],
    chunk_tokens: int,
    overlap_tokens: int,
    min_chunks: int,
    max_input_tokens: int,
    prompt_overhead_tokens: int,
) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    total_est = sum(estimate_tokens_rough(str(b.get("text") or "")) + 1 for b in blocks)
    effective_chunk_tokens = chunk_tokens
    if min_chunks and min_chunks > 1 and total_est > 0:
        forced = max(5000, int(total_est / min_chunks))
        effective_chunk_tokens = min(effective_chunk_tokens, forced)

    if max_input_tokens and max_input_tokens > 0:
        reserve = max(3000, int(prompt_overhead_tokens) + int(overlap_tokens) + 1000)
        safe_chunk_cap = max(5000, int(max_input_tokens) - reserve)
        effective_chunk_tokens = min(effective_chunk_tokens, safe_chunk_cap)

    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append(current)
            current = []
            current_tokens = 0

    for block in blocks:
        block_tokens = estimate_tokens_rough(str(block.get("text") or "")) + 1
        if current and (current_tokens + block_tokens > effective_chunk_tokens):
            flush()
        current.append(block)
        current_tokens += block_tokens
    flush()

    def tail_for_overlap(previous: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tail: List[Dict[str, Any]] = []
        tokens = 0
        for block in reversed(previous):
            block_tokens = estimate_tokens_rough(str(block.get("text") or "")) + 1
            if tokens + block_tokens > overlap_tokens and tail:
                break
            tail.insert(0, block)
            tokens += block_tokens
        return tail

    pairs: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
    previous: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        overlap = tail_for_overlap(previous) if index > 0 else []
        pairs.append((overlap, chunk))
        previous = chunk
    return pairs


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def norm(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    seen = set()
    out = []
    for row in rows:
        key = (norm(row.get("quote", "")), norm(row.get("recommendation", "")), norm(row.get("problem", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_instructions(rules_context: str, report_lang: str = "en") -> str:
    template = resolve_prompt("audit_system")
    instructions = template.replace("{{RULES_CONTEXT}}", rules_context)
    if str(report_lang or "").strip().lower() == "ru":
        instructions += (
            "\n\nOUTPUT LANGUAGE REQUIREMENT:\n"
            "- Write every human-readable value in Russian, especially problem, recommendation, violation, and fix.\n"
            "- Keep JSON property names and machine enum values such as fix_mode, confidence, severity, and status unchanged.\n"
            "- Do not mix English explanatory phrases into Russian output.\n"
            "- Do not use English markers such as CHECK; write ПРОВЕРКА instead.\n"
        )
    return instructions


def build_user_prompt(overlap_blocks: List[Dict[str, Any]], chunk_blocks: List[Dict[str, Any]]) -> str:
    def fmt(blocks: List[Dict[str, Any]]) -> str:
        return "\n\n".join([f"{b['location']} {b['text']}" for b in blocks])

    template = resolve_prompt("audit_user")
    return (
        template.replace("{{OVERLAP_CONTEXT}}", fmt(overlap_blocks))
        .replace("{{NEW_CHUNK_TEXT}}", fmt(chunk_blocks))
    )
