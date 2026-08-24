#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve and manage general LLM document task instruction files."""

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
TASK_STORE_DIR = CONFIG_DIR / "doc_tasks"
TASK_CACHE_PATH = CONFIG_DIR / "gui_doc_task_cache.json"
QUICK_TASK_CACHE_PATH = CONFIG_DIR / "gui_doc_task_quick_cache.json"
TASK_ENV = "AUDION_DOC_TASK_REF"
TASK_QUERY_ENV = "AUDION_DOC_TASK_QUERY"
TASK_TEXT_ENV = "AUDION_DOC_TASK_TEXT"
TASK_QUICK_REF_ENV = "AUDION_DOC_TASK_QUICK_REF"
CANONICAL_TASK_FILENAME = "active_doc_task.md"
CANONICAL_TASK_PATH = TASK_STORE_DIR / CANONICAL_TASK_FILENAME


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _empty_cache() -> dict[str, Any]:
    return {"schema_version": 1, "active_ref": "", "pinned": [], "usage": {}, "entries": {}}


def _read_cache() -> dict[str, Any]:
    if not TASK_CACHE_PATH.exists():
        return _empty_cache()
    try:
        payload = json.loads(TASK_CACHE_PATH.read_text(encoding="utf-8-sig", errors="replace"))
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
    TASK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASK_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_cache_best_effort(cache: dict[str, Any]) -> None:
    try:
        _write_cache(cache)
    except OSError:
        pass


def _empty_quick_cache() -> dict[str, Any]:
    return {"schema_version": 1, "pinned": [], "usage": {}, "entries": {}}


def _read_quick_cache() -> dict[str, Any]:
    if not QUICK_TASK_CACHE_PATH.exists():
        return _empty_quick_cache()
    try:
        payload = json.loads(QUICK_TASK_CACHE_PATH.read_text(encoding="utf-8-sig", errors="replace"))
        if not isinstance(payload, dict):
            return _empty_quick_cache()
    except Exception:
        return _empty_quick_cache()
    cache = _empty_quick_cache()
    cache.update(payload)
    if not isinstance(cache.get("entries"), dict):
        cache["entries"] = {}
    if not isinstance(cache.get("pinned"), list):
        cache["pinned"] = []
    if not isinstance(cache.get("usage"), dict):
        cache["usage"] = {}
    return cache


def _write_quick_cache(cache: dict[str, Any]) -> None:
    QUICK_TASK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUICK_TASK_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _task_ref(sha256: str) -> str:
    return sha256[:16].lower()


def _content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _label_from_name(path: Path) -> str:
    label = re.sub(r"^\d+[_ -]*", "", path.stem)
    label = label.replace("_", " ").replace("-", " ")
    return " ".join(label.split()).strip() or path.stem


def _label_from_text(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().strip("#").strip()
        if cleaned:
            return " ".join(cleaned.split())[:80]
    return "Quick document task"


def _safe_stem(text: str) -> str:
    stem = re.sub(r"[^0-9A-Za-zА-Яа-я._ -]+", "_", text).strip(" ._-")
    stem = re.sub(r"\s+", "_", stem)
    return stem[:80] or "doc_task"


def _unique_store_path(source: Path, label: str = "") -> Path:
    base = _safe_stem(label or source.stem)
    suffix = source.suffix if source.suffix.lower() == ".md" else ".md"
    target = TASK_STORE_DIR / f"{base}{suffix}"
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = TASK_STORE_DIR / f"{base}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique task file name for: {source.name}")


def _entry_from_store_file(path: Path, label: str = "", note: str = "") -> dict[str, Any]:
    sha256 = _file_sha256(path)
    stat = path.stat()
    return {
        "ref": _task_ref(sha256),
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

    def remember_pin(ref: str, old_ref: str) -> None:
        if old_ref in previous_pinned and ref not in next_pinned:
            next_pinned.append(ref)

    for path in sorted(TASK_STORE_DIR.glob("*.md")):
        if path.name == CANONICAL_TASK_FILENAME:
            continue
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
            remember_pin(ref, old_ref)
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
        cache["active_ref"] = sorted(scanned_refs)[0] if scanned_refs else ""
    return cache


def ensure_doc_task_store() -> dict[str, Any]:
    TASK_STORE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _scan_store(_read_cache())
    if not CANONICAL_TASK_PATH.exists() and cache.get("active_ref"):
        source = TASK_STORE_DIR / str(cache["entries"][cache["active_ref"]].get("filename") or "")
        if source.exists():
            shutil.copy2(source, CANONICAL_TASK_PATH)
    _write_cache_best_effort(cache)
    return cache


def doc_task_entries() -> list[dict[str, Any]]:
    cache = ensure_doc_task_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict):
        return []
    active_ref = active_doc_task_ref()
    pinned = set(str(value) for value in cache.get("pinned", []))
    out: list[dict[str, Any]] = []
    for ref, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        item["ref"] = ref
        item["active"] = ref == active_ref
        item["pinned"] = ref in pinned
        item["usage_count"] = int(cache.get("usage", {}).get(ref, 0) or 0)
        out.append(item)
    return out


def active_doc_task_ref() -> str:
    if CANONICAL_TASK_PATH.exists():
        return _task_ref(_file_sha256(CANONICAL_TASK_PATH))
    cache = ensure_doc_task_store()
    return str(cache.get("active_ref") or "")


def pinned_doc_task_refs() -> list[str]:
    cache = ensure_doc_task_store()
    return [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]


def resolve_doc_task_entry(task_ref: str = "") -> tuple[Path | None, dict[str, Any]]:
    cache = ensure_doc_task_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict) or not entries:
        return None, {}
    selected = str(task_ref or "").strip()
    if not selected or selected.startswith("__"):
        selected = str(cache.get("active_ref") or "").strip()
    if selected not in entries:
        selected = sorted(entries)[0]
    entry = dict(entries.get(selected, {}))
    entry["ref"] = selected
    path = TASK_STORE_DIR / str(entry.get("filename") or "")
    if not path.exists():
        return None, {}
    return path, entry


def load_doc_task(task_ref: str = "") -> tuple[str, dict[str, Any]]:
    quick_text = os.environ.get(TASK_TEXT_ENV, "").strip()
    if quick_text:
        quick_ref = os.environ.get(TASK_QUICK_REF_ENV, "").strip()
        entry = resolve_quick_doc_task_entry(quick_ref) if quick_ref else {}
        if not entry:
            sha256 = _content_sha256(quick_text)
            quick_ref = _task_ref(sha256)
            entry = {
                "ref": f"quick:{quick_ref}",
                "quick_ref": quick_ref,
                "label": _label_from_text(quick_text),
                "note": "Inline quick instruction",
                "filename": "(quick instruction)",
                "sha256": sha256,
                "size_bytes": len(quick_text.encode("utf-8")),
                "quick": True,
            }
        else:
            entry = dict(entry)
            entry["ref"] = f"quick:{entry.get('ref', quick_ref)}"
            entry["quick_ref"] = str(entry.get("quick_ref") or quick_ref)
            entry["quick"] = True
        return quick_text, entry

    env_ref = os.environ.get(TASK_ENV, "").strip()
    path, entry = resolve_doc_task_entry(env_ref or task_ref)
    if not path or not entry:
        raise RuntimeError(f"No document task instruction files found in: {TASK_STORE_DIR}")
    content = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not content:
        raise RuntimeError(f"Document task instruction file is empty: {path}")
    return content, entry


def set_active_doc_task(task_ref: str) -> dict[str, Any]:
    task_ref = str(task_ref or "").strip()
    cache = ensure_doc_task_store()
    entries = cache.get("entries", {})
    if not task_ref or not isinstance(entries, dict) or task_ref not in entries:
        raise RuntimeError("No document task instruction selected.")
    source = TASK_STORE_DIR / str(entries[task_ref].get("filename") or "")
    if not source.exists():
        raise RuntimeError(f"Document task instruction file was not found: {source}")
    shutil.copy2(source, CANONICAL_TASK_PATH)
    cache = _scan_store(cache)
    cache["active_ref"] = task_ref
    _write_cache(cache)
    item = dict(cache.get("entries", {}).get(task_ref, entries[task_ref]))
    item["ref"] = task_ref
    return item


def pin_doc_task(task_ref: str) -> dict[str, Any]:
    task_ref = str(task_ref or "").strip()
    cache = ensure_doc_task_store()
    entries = cache.get("entries", {})
    if not task_ref or not isinstance(entries, dict) or task_ref not in entries:
        raise RuntimeError("No document task instruction selected.")
    pinned = [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]
    if task_ref not in pinned:
        pinned.insert(0, task_ref)
    cache["pinned"] = pinned[:20]
    _write_cache(cache)
    item = dict(entries[task_ref])
    item["ref"] = task_ref
    return item


def remember_doc_task_use(task_ref: str) -> None:
    task_ref = str(task_ref or "").strip()
    if not task_ref:
        return
    cache = ensure_doc_task_store()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict) or task_ref not in entries:
        return
    usage = cache.setdefault("usage", {})
    usage[task_ref] = int(usage.get(task_ref, 0) or 0) + 1
    _write_cache(cache)


def quick_doc_task_entries() -> list[dict[str, Any]]:
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict):
        return []
    pinned = set(str(value) for value in cache.get("pinned", []))
    out: list[dict[str, Any]] = []
    for ref, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        item["ref"] = ref
        item["quick_ref"] = ref
        item["pinned"] = ref in pinned
        item["usage_count"] = int(cache.get("usage", {}).get(ref, 0) or 0)
        out.append(item)
    return out


def pinned_quick_doc_task_refs() -> list[str]:
    cache = _read_quick_cache()
    return [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]


def resolve_quick_doc_task_entry(quick_ref: str = "") -> dict[str, Any]:
    quick_ref = str(quick_ref or "").strip()
    if not quick_ref or quick_ref.startswith("__"):
        return {}
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict):
        return {}
    entry = entries.get(quick_ref)
    if not isinstance(entry, dict):
        return {}
    item = dict(entry)
    item["ref"] = quick_ref
    item["quick_ref"] = quick_ref
    item["quick"] = True
    return item


def save_quick_doc_task(
    text: str,
    *,
    label: str = "",
    note: str = "",
    pin: bool = False,
) -> dict[str, Any]:
    content = str(text or "").strip()
    if not content:
        raise RuntimeError("Quick document task instruction is empty.")
    sha256 = _content_sha256(content)
    ref = _task_ref(sha256)
    now = _now()
    cache = _read_quick_cache()
    entries = cache.setdefault("entries", {})
    entry = entries.get(ref) if isinstance(entries, dict) else None
    if isinstance(entry, dict):
        if label.strip():
            entry["label"] = label.strip()
        if note.strip():
            entry["note"] = note.strip()
        entry["content"] = content
        entry["sha256"] = sha256
        entry["size_bytes"] = len(content.encode("utf-8"))
        entry["updated_at"] = now
    else:
        entry = {
            "ref": ref,
            "label": label.strip() or _label_from_text(content),
            "note": note.strip(),
            "content": content,
            "sha256": sha256,
            "size_bytes": len(content.encode("utf-8")),
            "created_at": now,
            "updated_at": now,
        }
        entries[ref] = entry

    if pin:
        pinned = [str(item) for item in cache.get("pinned", []) if str(item).strip()]
        if ref not in pinned:
            pinned.insert(0, ref)
        cache["pinned"] = pinned[:20]
    _write_quick_cache(cache)
    item = dict(entry)
    item["ref"] = ref
    item["quick_ref"] = ref
    item["quick"] = True
    return item


def pin_quick_doc_task(quick_ref: str) -> dict[str, Any]:
    quick_ref = str(quick_ref or "").strip()
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not quick_ref or not isinstance(entries, dict) or quick_ref not in entries:
        raise RuntimeError("No quick document task instruction selected.")
    pinned = [str(ref) for ref in cache.get("pinned", []) if str(ref).strip()]
    if quick_ref not in pinned:
        pinned.insert(0, quick_ref)
    cache["pinned"] = pinned[:20]
    _write_quick_cache(cache)
    item = dict(entries[quick_ref])
    item["ref"] = quick_ref
    item["quick_ref"] = quick_ref
    item["quick"] = True
    return item


def unpin_quick_doc_task(quick_ref: str) -> dict[str, Any]:
    quick_ref = str(quick_ref or "").strip()
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not quick_ref or not isinstance(entries, dict) or quick_ref not in entries:
        raise RuntimeError("No quick document task instruction selected.")
    cache["pinned"] = [ref for ref in cache.get("pinned", []) if str(ref) != quick_ref]
    _write_quick_cache(cache)
    item = dict(entries[quick_ref])
    item["ref"] = quick_ref
    item["quick_ref"] = quick_ref
    item["quick"] = True
    item["pinned"] = False
    return item


def delete_quick_doc_task(quick_ref: str = "", *, text: str = "") -> dict[str, Any]:
    selected = str(quick_ref or "").strip()
    if not selected:
        content = str(text or "").strip()
        if content:
            selected = _task_ref(_content_sha256(content))
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not selected or not isinstance(entries, dict) or selected not in entries:
        raise RuntimeError("No quick document task instruction selected to delete.")

    item = dict(entries.pop(selected))
    cache["pinned"] = [ref for ref in cache.get("pinned", []) if str(ref) != selected]
    usage = cache.get("usage", {})
    if isinstance(usage, dict):
        usage.pop(selected, None)
    _write_quick_cache(cache)
    item["ref"] = selected
    item["quick_ref"] = selected
    item["quick"] = True
    item["deleted"] = True
    return item


def remember_quick_doc_task_use(quick_ref: str) -> None:
    quick_ref = str(quick_ref or "").strip()
    if not quick_ref:
        return
    cache = _read_quick_cache()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict) or quick_ref not in entries:
        return
    usage = cache.setdefault("usage", {})
    usage[quick_ref] = int(usage.get(quick_ref, 0) or 0) + 1
    _write_quick_cache(cache)


def import_doc_task_file(
    source: Path | str,
    *,
    label: str = "",
    note: str = "",
    pin: bool = False,
    set_active: bool = True,
) -> dict[str, Any]:
    source_path = Path(str(source)).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise RuntimeError(f"Document task instruction file was not found: {source_path}")
    if source_path.suffix.lower() not in {".md", ".txt"}:
        raise RuntimeError("Document task import expects a .md or .txt file.")

    cache = ensure_doc_task_store()
    source_sha = _file_sha256(source_path)
    ref = _task_ref(source_sha)
    entries = cache.setdefault("entries", {})
    entry = entries.get(ref) if isinstance(entries, dict) else None
    if isinstance(entry, dict):
        if label.strip():
            entry["label"] = label.strip()
        if note.strip():
            entry["note"] = note.strip()
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
        set_active_doc_task(ref)
    item = dict(entry)
    item["ref"] = ref
    return item
