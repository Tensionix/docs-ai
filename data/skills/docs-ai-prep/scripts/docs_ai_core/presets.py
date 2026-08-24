#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much attention a document deserves, and what that costs.

Two knobs decide the work: how finely the text is cut, and which model reads it.
They pull against each other - a small model on a big chunk skims the tail, a
strong model on a small chunk burns limits on nothing. Measured behaviour on a
200-page project document:

    Haiku, 48k chunk   -> flagged 12 blocks of 541; findings 11/4/2 across thirds,
                          attention clearly fading, one quote paraphrased.
    Sonnet, 48k tables -> 14 findings, 5 of them arithmetic, every quote verbatim,
                          and it caught miscalculated growth percentages that two
                          paid API runs missed entirely.

Hence the rule of thumb: prose chunks stay small so a cheap model can hold them;
table chunks stay large because comparing rows needs a wide view - and that view
is only useful to a model that reasons.

Presets speak in roles (reader / analyst), never in vendor model names - see
platforms.py for what a role means on Claude, Codex, Grok or Gemini.
"""

from __future__ import annotations

from typing import Any, Dict

PRESETS: Dict[str, Dict[str, Any]] = {
    # Huge documents, first look. The point is coverage, not depth.
    "scan": {
        "title": "беглый осмотр",
        "use_when": "1000+ страниц, черновик, нужно быстро понять масштаб проблем",
        "text": {"chunk_tokens": 12000, "role": "reader", "effort": "low"},
        "table": {"chunk_tokens": 16000, "role": "reader", "effort": "low"},
    },
    # The everyday setting: a project volume of 100-300 pages.
    "standard": {
        "title": "рабочая вычитка",
        "use_when": "обычная записка, том, ПКР — основной режим",
        "text": {"chunk_tokens": 16000, "role": "analyst", "effort": "low"},
        "table": {"chunk_tokens": 48000, "role": "analyst", "effort": "medium"},
    },
    # Small but consequential: an NIR, a document going outside, a disputed section.
    "deep": {
        "title": "глубокая проверка",
        "use_when": "небольшой, но ответственный документ; спорные разделы; расчёты",
        "text": {"chunk_tokens": 12000, "role": "analyst", "effort": "medium"},
        "table": {"chunk_tokens": 32000, "role": "analyst", "effort": "high"},
    },
}

DEFAULT_PRESET = "standard"


def resolve_preset(name: str) -> Dict[str, Any]:
    key = str(name or DEFAULT_PRESET).strip().lower()
    if key not in PRESETS:
        raise SystemExit(f"[ERROR] unknown preset '{name}'. Available: {', '.join(PRESETS)}")
    return PRESETS[key]


def assignment(preset: Dict[str, Any], profile: str, platform: Dict[str, Any]) -> Dict[str, Any]:
    """Which worker this chunk needs, and what that means on the current platform."""
    from .platforms import model_for

    lane = preset["table"] if profile == "deep" else preset["text"]
    return {"role": lane["role"], "effort": lane["effort"], "model": model_for(platform, lane["role"])}
