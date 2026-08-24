#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve and manage audit rule Markdown files for the GUI and pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
RULES_STORE_DIR = CONFIG_DIR / "audit_rules"
RULES_CACHE_PATH = CONFIG_DIR / "gui_rules_cache.json"
RULE_ENV = "AUDION_AUDIT_RULE_REF"
CANONICAL_RULE_FILENAME = "active_audit_rules.md"
CANONICAL_RULE_PATH = RULES_STORE_DIR / CANONICAL_RULE_FILENAME


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _empty_cache() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_ref": "",
        "pinned": [],
        "usage": {},
        "entries": {},
    }


def _read_cache() -> dict[str, Any]:
    if not RULES_CACHE_PATH.exists():
        return _empty_cache()
    try:
        payload = json.loads(RULES_CACHE_PATH.read_text(encoding="utf-8-sig", errors="replace"))
        if not isinstance(payload, dict):
            return _empty_cache()
    except Exception:
        return _empty_cache()

    cache = _empty_cache()
    cache.update(payload)
    if not isinstance(cache.get("entries"), dict):
        cache["entries"] = {}
    if not isinstance(cache.get("pinned"), list):
        cache["pinned"] = []
    if not isinstance(cache.get("usage"), dict):
        cache["usage"] = {}
    return cache


def _write_cache(cache: dict[str, Any]) -> None:
    RULES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_cache_best_effort(cache: dict[str, Any]) -> None:
    try:
        _write_cache(cache)
    except OSError:
        pass


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rule_ref(sha256: str) -> str:
    return sha256[:16].lower()


def _label_from_name(path: Path) -> str:
    label = path.stem
    label = re.sub(r"^\d+[_ -]*", "", label)
    label = label.replace("_", " ").replace("-", " ")
    return " ".join(label.split()).strip() or path.stem


def _safe_stem(text: str) -> str:
    stem = re.sub(r"[^0-9A-Za-zА-Яа-я._ -]+", "_", text).strip(" ._-")
    stem = re.sub(r"\s+", "_", stem)
    return stem[:80] or "audit_rules"


def _unique_store_path(source: Path, label: str = "") -> Path:
    base = _safe_stem(label or source.stem)
    suffix = source.suffix if source.suffix.lower() == ".md" else ".md"
    target = RULES_STORE_DIR / f"{base}{suffix}"
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = RULES_STORE_DIR / f"{base}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique rule file name for: {source.name}")


def _entry_from_store_file(path: Path, label: str = "", note: str = "") -> dict[str, Any]:
    sha256 = _file_sha256(path)
    stat = path.stat()
    return {
        "ref": _rule_ref(sha256),
        "label": label.strip() or _label_from_name(path),
        "note": note.strip(),
        "filename": path.name,
        "sha256": sha256,
        "size_bytes": int(stat.st_size),
        "mtime": int(stat.st_mtime),
        "updated_at": _now(),
    }


def _scan_store(cache: dict[str, Any]) -> dict[str, Any]:
    entries = cache.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        cache["entries"] = entries

    previous_entries = {str(ref): dict(entry) for ref, entry in entries.items() if isinstance(entry, dict)}
    previous_by_filename = {
        str(entry.get("filename") or ""): (ref, entry)
        for ref, entry in previous_entries.items()
        if str(entry.get("filename") or "")
    }
    previous_pinned = [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]
    previous_usage = cache.get("usage", {}) if isinstance(cache.get("usage"), dict) else {}
    previous_active = str(cache.get("active_ref") or "")
    next_entries: dict[str, dict[str, Any]] = {}
    next_pinned: list[str] = []
    next_usage: dict[str, int] = {}
    next_active = ""
    scanned_refs: set[str] = set()

    for path in sorted(RULES_STORE_DIR.glob("*.md")):
        fresh = _entry_from_store_file(path)
        ref = str(fresh["ref"])
        old_ref = ref
        existing = previous_entries.get(ref, {})
        if not isinstance(existing, dict) or not existing:
            old_ref, existing = previous_by_filename.get(path.name, ("", {}))
        if isinstance(existing, dict):
            fresh["label"] = str(existing.get("label") or fresh["label"])
            fresh["note"] = str(existing.get("note") or fresh["note"])
            fresh["created_at"] = str(existing.get("created_at") or fresh["updated_at"])
        else:
            fresh["created_at"] = fresh["updated_at"]
        next_entries[ref] = fresh
        scanned_refs.add(ref)
        if old_ref:
            if old_ref in previous_pinned and ref not in next_pinned:
                next_pinned.append(ref)
            next_usage[ref] = int(previous_usage.get(old_ref, 0) or previous_usage.get(ref, 0) or 0)
            if old_ref == previous_active:
                next_active = ref

    for ref in previous_pinned:
        if ref in scanned_refs and ref not in next_pinned:
            next_pinned.append(ref)

    cache["entries"] = next_entries
    cache["pinned"] = [ref for ref in next_pinned if ref in scanned_refs]
    cache["usage"] = {ref: int(next_usage.get(ref, 0) or 0) for ref in scanned_refs if int(next_usage.get(ref, 0) or 0) > 0}
    if next_active:
        cache["active_ref"] = next_active
    elif str(cache.get("active_ref") or "") not in scanned_refs:
        cache["active_ref"] = ""
    return cache


def ensure_rules_store() -> dict[str, Any]:
    RULES_STORE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _read_cache()
    cache = _scan_store(cache)
    entries = cache.get("entries", {})
    if isinstance(entries, dict) and entries and not cache.get("active_ref"):
        master = next(
            (
                ref
                for ref, entry in entries.items()
                if str(entry.get("filename") or "").lower() == CANONICAL_RULE_FILENAME.lower()
            ),
            "",
        )
        cache["active_ref"] = master or sorted(entries)[0]
    _write_cache_best_effort(cache)
    return cache


def rule_entries() -> list[dict[str, Any]]:
    cache = ensure_rules_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict):
        return []
    active_ref = str(cache.get("active_ref") or "")
    out: list[dict[str, Any]] = []
    for ref, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        item["ref"] = ref
        item["active"] = ref == active_ref
        item["pinned"] = ref in set(str(value) for value in cache.get("pinned", []))
        item["usage_count"] = int(cache.get("usage", {}).get(ref, 0) or 0)
        out.append(item)
    return out


def active_rule_ref() -> str:
    if CANONICAL_RULE_PATH.exists():
        return _rule_ref(_file_sha256(CANONICAL_RULE_PATH))
    cache = ensure_rules_store()
    return str(cache.get("active_ref") or "")


def pinned_rule_refs() -> list[str]:
    cache = ensure_rules_store()
    return [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]


def resolve_rule_entry(rule_ref: str = "") -> tuple[Path | None, dict[str, Any]]:
    cache = ensure_rules_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict) or not entries:
        return None, {}

    selected = str(rule_ref or "").strip()
    if not selected or selected.startswith("__"):
        selected = str(cache.get("active_ref") or "").strip()
    if selected not in entries:
        selected = sorted(entries)[0]

    entry = dict(entries.get(selected, {}))
    entry["ref"] = selected
    path = RULES_STORE_DIR / str(entry.get("filename") or "")
    if not path.exists():
        return None, {}
    return path, entry


def load_active_rules() -> str:
    env_ref = os.environ.get(RULE_ENV, "").strip()
    if env_ref:
        path, entry = resolve_rule_entry(env_ref)
    elif CANONICAL_RULE_PATH.exists():
        sha256 = _file_sha256(CANONICAL_RULE_PATH)
        path = CANONICAL_RULE_PATH
        entry = {
            "ref": _rule_ref(sha256),
            "filename": CANONICAL_RULE_FILENAME,
            "label": "Active audit rules",
            "sha256": sha256,
        }
    else:
        path, entry = resolve_rule_entry("")
    if not path or not entry:
        raise RuntimeError(f"No audit rule files found in: {RULES_STORE_DIR}")
    content = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not content:
        raise RuntimeError(f"Audit rule file is empty: {path}")
    return f"\n--- RULE: {entry.get('filename', path.name)} [{entry.get('ref', '')}] ---\n{content}\n"


def set_active_rule(rule_ref: str) -> dict[str, Any]:
    rule_ref = str(rule_ref or "").strip()
    cache = ensure_rules_store()
    entries = cache.get("entries", {})
    if not rule_ref or not isinstance(entries, dict) or rule_ref not in entries:
        raise RuntimeError("No audit rule file selected.")
    source = RULES_STORE_DIR / str(entries[rule_ref].get("filename") or "")
    if not source.exists():
        raise RuntimeError(f"Audit rule file was not found: {source}")
    if source.resolve() != CANONICAL_RULE_PATH.resolve():
        shutil.copy2(source, CANONICAL_RULE_PATH)
    cache = _scan_store(cache)
    cache["active_ref"] = rule_ref
    _write_cache(cache)
    item = dict(cache.get("entries", {}).get(rule_ref, entries[rule_ref]))
    item["ref"] = rule_ref
    return item


def pin_rule(rule_ref: str) -> dict[str, Any]:
    rule_ref = str(rule_ref or "").strip()
    cache = ensure_rules_store()
    entries = cache.get("entries", {})
    if not rule_ref or not isinstance(entries, dict) or rule_ref not in entries:
        raise RuntimeError("No audit rule file selected.")
    pinned = [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]
    if rule_ref not in pinned:
        pinned.insert(0, rule_ref)
    cache["pinned"] = pinned[:20]
    _write_cache(cache)
    item = dict(entries[rule_ref])
    item["ref"] = rule_ref
    return item


def remember_rule_use(rule_ref: str) -> None:
    rule_ref = str(rule_ref or "").strip()
    if not rule_ref:
        return
    cache = ensure_rules_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict) or rule_ref not in entries:
        return
    usage = cache.setdefault("usage", {})
    usage[rule_ref] = int(usage.get(rule_ref, 0) or 0) + 1
    _write_cache(cache)


def import_rule_file(
    source: Path | str,
    *,
    label: str = "",
    note: str = "",
    pin: bool = False,
    set_active: bool = True,
) -> dict[str, Any]:
    source_path = Path(str(source)).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise RuntimeError(f"Audit rule file was not found: {source_path}")
    if source_path.suffix.lower() not in {".md", ".txt"}:
        raise RuntimeError("Audit rule import expects a .md or .txt file.")

    cache = ensure_rules_store()
    source_sha = _file_sha256(source_path)
    ref = _rule_ref(source_sha)
    entries = cache.setdefault("entries", {})

    entry = entries.get(ref) if isinstance(entries, dict) else None
    if isinstance(entry, dict):
        target = RULES_STORE_DIR / str(entry.get("filename") or "")
        if not target.exists():
            target = _unique_store_path(source_path, label)
            shutil.copy2(source_path, target)
        if label.strip():
            entry["label"] = label.strip()
        if note.strip():
            entry["note"] = note.strip()
        entry["filename"] = target.name
        entry["updated_at"] = _now()
    else:
        target = _unique_store_path(source_path, label)
        if source_path.resolve() != target.resolve():
            shutil.copy2(source_path, target)
        entry = _entry_from_store_file(target, label=label or _label_from_name(source_path), note=note)
        entry["created_at"] = _now()
        entries[ref] = entry

    if pin:
        pinned = [str(item) for item in cache.get("pinned", []) if str(item).strip()]
        if ref not in pinned:
            pinned.insert(0, ref)
        cache["pinned"] = pinned[:20]
    _write_cache(cache)
    if set_active:
        set_active_rule(ref)
    item = dict(entry)
    item["ref"] = ref
    return item
