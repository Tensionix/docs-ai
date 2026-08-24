#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which model plays which part, on whichever agent is running the skill.

The skill never needs a particular vendor - it needs two kinds of worker:

    reader   fast and literal. Reads prose closely, reports what it sees.
             Cheap enough to run over a thousand pages.
    analyst  reasons. Adds up columns, compares rows, notices that a number
             cannot be true. Slower and heavier, worth it on tables.

Everything else in the skill is written in those terms, so the same workspace can
be audited by Claude Code, Codex, Grok or Gemini without editing a single script.
Model names below were verified against the live catalogues in August 2026; when
they age, only this table needs touching.
"""

from __future__ import annotations

from typing import Any, Dict

ROLES = ("reader", "analyst")

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "title": "Claude Code",
        "skills_path": "~/.claude/skills/",
        "reader": "haiku",
        "analyst": "sonnet",
        "notes": "Родная площадка скилла. Субагенты запускаются штатно, effort передаётся как есть.",
    },
    "codex": {
        "title": "OpenAI Codex / ChatGPT",
        "skills_path": "~/.agents/skills/",
        "reader": "gpt-5.6-terra",
        "analyst": "gpt-5.6-sol",
        "avoid": ["gpt-5.6-luna"],
        "notes": (
            "В ChatGPT-чате доступны только luna, terra и sol. terra — быстрый чтец, "
            "sol — рассуждающий. Через API можно брать любую модель."
        ),
    },
    "grok": {
        "title": "xAI Grok",
        "skills_path": "~/.grok/skills/ (читает и ~/.claude/skills/)",
        "reader": "grok-4.3",
        "analyst": "grok-4.5",
        "notes": "Skills совместимы с форматом Claude Code, каталоги .claude читаются напрямую.",
    },
    "gemini": {
        "title": "Gemini CLI / Antigravity",
        "skills_path": "~/.agents/skills/ (ранее ~/.gemini/skills/)",
        "reader": "gemini-3.6-flash",
        "analyst": "gemini-3.1-pro-preview",
        "notes": (
            "Flash-модели рассуждают мало и хороши как чтец; для расчётов в таблицах "
            "берите pro. Gemini CLI переехал в Antigravity CLI, каталог скиллов сменился."
        ),
    },
    "generic": {
        "title": "Любой другой агент",
        "skills_path": "~/.agents/skills/",
        "reader": "самая быстрая доступная модель",
        "analyst": "самая сильная доступная модель с рассуждением",
        "notes": "Подставьте собственные модели по смыслу ролей.",
    },
}

DEFAULT_PLATFORM = "claude"


def resolve_platform(name: str) -> Dict[str, Any]:
    key = str(name or DEFAULT_PLATFORM).strip().lower()
    if key not in PLATFORMS:
        raise SystemExit(f"[ERROR] unknown platform '{name}'. Available: {', '.join(PLATFORMS)}")
    return PLATFORMS[key]


def model_for(platform: Dict[str, Any], role: str) -> str:
    return str(platform.get(role) or platform.get("reader"))
