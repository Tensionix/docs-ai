from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import shutil
import sys

from system_core.core.jobs import JobContext, run_process
from system_core.config_resolver import (
    CONFIG_DIR,
    api_key_entries,
    get_path,
    load_settings,
    parse_api_key_entries,
    resolve_api_key,
    resolve_model,
)
from system_core.doc_task_resolver import (
    TASK_ENV,
    TASK_QUICK_REF_ENV,
    TASK_QUERY_ENV,
    TASK_TEXT_ENV,
    active_doc_task_ref,
    delete_quick_doc_task,
    doc_task_entries,
    import_doc_task_file,
    pin_doc_task,
    pin_quick_doc_task,
    pinned_doc_task_refs,
    pinned_quick_doc_task_refs,
    quick_doc_task_entries,
    remember_doc_task_use,
    remember_quick_doc_task_use,
    resolve_doc_task_entry,
    resolve_quick_doc_task_entry,
    save_quick_doc_task,
    set_active_doc_task,
    unpin_quick_doc_task,
)
from system_core.rules_resolver import (
    RULE_ENV,
    active_rule_ref,
    import_rule_file,
    pin_rule,
    pinned_rule_refs,
    remember_rule_use,
    resolve_rule_entry,
    rule_entries,
    set_active_rule,
)


SUPPORTED_DOCUMENTS = {".docx", ".pptx"}
SUPPORTED_TASK_INPUTS = {".docx", ".pptx", ".xlsx", ".pdf"}
SUPPORTED_TASK_TEMPLATES = {".docx", ".xlsx"}
MODEL_CACHE_PATH = CONFIG_DIR / "gui_model_cache.json"
KEY_CACHE_PATH = CONFIG_DIR / "gui_key_cache.json"
MODEL_CHECK_STALE_DAYS = 14
MODEL_CHECK_PROMPT = "Reply with OK."
MODEL_PROVIDERS = {"openai", "gemini", "xai", "anthropic"}
DEFAULT_WORKERS = 4
DEFAULT_AUDIT_REASONING = {
    "openai": "high",
    "gemini": "medium",
    "xai": "high",
    "anthropic": "medium",
}


def _as_int(value: Any, default: int) -> int:
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "да"}:
        return True
    if text in {"0", "false", "no", "n", "off", "нет"}:
        return False
    return default


def _configured_model(provider: str, tier: str = "audit") -> str:
    try:
        settings = load_settings()
        if provider == "gemini":
            return resolve_model(provider, tier, settings)
        return resolve_model(provider, "audit", settings)
    except Exception:
        return ""


def _option(value: str, label: str, label_ru: str | None = None) -> dict[str, str]:
    return {"value": value, "label": label, "label_ru": label_ru or label}


def _dedupe_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for option in options:
        value = str(option.get("value", "")).strip()
        if value in seen:
            continue
        seen.add(value)
        out.append(option)
    return out


def _read_json_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"providers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        return payload if isinstance(payload, dict) else {"providers": {}}
    except Exception:
        return {"providers": {}}


def _write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_model_cache() -> dict[str, Any]:
    return _read_json_cache(MODEL_CACHE_PATH)


def _write_model_cache(payload: dict[str, Any]) -> None:
    _write_json_cache(MODEL_CACHE_PATH, payload)


def reset_model_cache(provider: str) -> dict[str, int]:
    provider = str(provider or "").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported model provider: {provider}")
    payload = _read_model_cache()
    cache = _provider_cache(payload, provider)
    removed = {
        "models": len(cache.get("models", []) if isinstance(cache.get("models"), list) else []),
        "pinned": len(cache.get("pinned", []) if isinstance(cache.get("pinned"), list) else []),
        "checks": len(cache.get("checks", {}) if isinstance(cache.get("checks"), dict) else {}),
    }
    cache["models"] = []
    cache["pinned"] = []
    cache["checks"] = {}
    _write_model_cache(payload)
    return removed


def _provider_cache(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = payload.setdefault("providers", {})
    if not isinstance(providers, dict):
        payload["providers"] = providers = {}
    provider_payload = providers.setdefault(provider, {})
    if not isinstance(provider_payload, dict):
        providers[provider] = provider_payload = {}
    provider_payload.setdefault("models", [])
    provider_payload.setdefault("pinned", [])
    provider_payload.setdefault("checks", {})
    return provider_payload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _checked_date(value: str) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _parse_checked_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _model_check_entry(provider: str, model_id: str) -> dict[str, Any]:
    cache = _provider_cache(_read_model_cache(), provider)
    checks = cache.get("checks", {})
    if not isinstance(checks, dict):
        return {}
    entry = checks.get(str(model_id or "").strip(), {})
    return entry if isinstance(entry, dict) else {}


def _model_check_display_status(entry: dict[str, Any]) -> str:
    status = str(entry.get("status") or "").strip().lower()
    if status not in {"ok", "error", "no_access"}:
        return ""
    checked_at = _parse_checked_at(str(entry.get("checked_at") or ""))
    if checked_at is None:
        return status
    age = datetime.now(timezone.utc) - checked_at
    if age.days >= MODEL_CHECK_STALE_DAYS:
        return "stale"
    return status


def _model_status_prefix_from_entry(entry: dict[str, Any]) -> str:
    status = _model_check_display_status(entry)
    if not status:
        return ""
    checked_at = _checked_date(str(entry.get("checked_at") or ""))
    token = {
        "ok": "OK",
        "error": "ERR",
        "no_access": "NO ACCESS",
        "stale": "STALE",
    }.get(status, status.upper())
    return f"[{token} {checked_at}]" if checked_at else f"[{token}]"


def _model_status_prefix(provider: str, model_id: str) -> str:
    return _model_status_prefix_from_entry(_model_check_entry(provider, model_id))


def _model_label_with_status(provider: str, model_id: str, label: str | None = None) -> str:
    base = str(label or model_id).strip()
    prefix = _model_status_prefix(provider, model_id)
    return f"{prefix} {base}" if prefix else base


def _remember_model_check(
    provider: str,
    model_id: str,
    status: str,
    message: str,
    *,
    key_ref: str = "",
) -> None:
    model_id = str(model_id or "").strip()
    if not model_id or model_id.startswith("__"):
        return
    payload = _read_model_cache()
    cache = _provider_cache(payload, provider)
    checks = cache.setdefault("checks", {})
    if not isinstance(checks, dict):
        checks = {}
        cache["checks"] = checks
    checks[model_id] = {
        "status": status,
        "checked_at": _utc_now_iso(),
        "message": str(message or "").strip()[:500],
        "key_ref": str(key_ref or "").strip(),
    }
    models = [str(model).strip() for model in cache.get("models", []) if str(model).strip()]
    if model_id not in models:
        models.append(model_id)
    cache["models"] = sorted(set(models))
    _write_model_cache(payload)


def _cached_models(provider: str) -> list[str]:
    cache = _provider_cache(_read_model_cache(), provider)
    models = cache.get("models", [])
    return [str(model).strip() for model in models if str(model).strip()] if isinstance(models, list) else []


def _pinned_models(provider: str) -> list[str]:
    cache = _provider_cache(_read_model_cache(), provider)
    pinned = cache.get("pinned", [])
    return [str(model).strip() for model in pinned if str(model).strip()] if isinstance(pinned, list) else []


def _remember_models(provider: str, model_ids: list[str]) -> None:
    payload = _read_model_cache()
    cache = _provider_cache(payload, provider)
    existing_pins = [model for model in _pinned_models(provider) if model in model_ids or model]
    cache["models"] = sorted({model for model in model_ids if model})
    cache["pinned"] = existing_pins
    _write_model_cache(payload)


def _pin_model(provider: str, model_id: str) -> None:
    model_id = str(model_id or "").strip()
    if not model_id or model_id.startswith("__"):
        return
    payload = _read_model_cache()
    cache = _provider_cache(payload, provider)
    pinned = [str(model).strip() for model in cache.get("pinned", []) if str(model).strip()]
    if model_id not in pinned:
        pinned.insert(0, model_id)
    cache["pinned"] = pinned[:20]
    models = [str(model).strip() for model in cache.get("models", []) if str(model).strip()]
    if model_id not in models:
        models.append(model_id)
    cache["models"] = sorted(set(models))
    _write_model_cache(payload)


def pin_model_ref(provider: str, model_id: str) -> None:
    provider = str(provider or "").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported model provider: {provider}")
    _pin_model(provider, model_id)


def unpin_model_ref(provider: str, model_id: str) -> None:
    provider = str(provider or "").strip().lower()
    model_id = str(model_id or "").strip()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported model provider: {provider}")
    if not model_id or model_id.startswith("__"):
        raise RuntimeError("No model selected.")
    payload = _read_model_cache()
    cache = _provider_cache(payload, provider)
    cache["pinned"] = [str(model).strip() for model in cache.get("pinned", []) if str(model).strip() and str(model).strip() != model_id]
    _write_model_cache(payload)


def model_is_pinned(provider: str, model_id: str) -> bool:
    provider = str(provider or "").strip().lower()
    model_id = str(model_id or "").strip()
    return bool(provider in MODEL_PROVIDERS and model_id and model_id in _pinned_models(provider))


def pinned_model_refs(provider: str) -> list[str]:
    provider = str(provider or "").strip().lower()
    return _pinned_models(provider) if provider in MODEL_PROVIDERS else []


def _model_options_from_cache(provider: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for model_id in _pinned_models(provider):
        label = _model_label_with_status(provider, model_id)
        options.append(_option(model_id, f"[FAV] {label}", f"[ИЗБР] {label}"))
    for model_id in _cached_models(provider):
        label = _model_label_with_status(provider, model_id)
        options.append(_option(model_id, label, label))
    return options


def _prioritize_pinned_model_options(provider: str, options: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the automatic entry first, then pinned models in pin order."""
    deduped = _dedupe_options(options)
    by_value = {str(option.get("value", "")).strip(): option for option in deduped}
    auto = [option for option in deduped if not str(option.get("value", "")).strip()]
    pinned = [by_value[model_id] for model_id in _pinned_models(provider) if model_id in by_value]
    pinned_values = {str(option.get("value", "")).strip() for option in pinned}
    remainder = [
        option
        for option in deduped
        if str(option.get("value", "")).strip() and str(option.get("value", "")).strip() not in pinned_values
    ]
    return [*auto, *pinned, *remainder]


def _read_key_cache() -> dict[str, Any]:
    return _read_json_cache(KEY_CACHE_PATH)


def _write_key_cache(payload: dict[str, Any]) -> None:
    _write_json_cache(KEY_CACHE_PATH, payload)


def _key_provider_cache(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = payload.setdefault("providers", {})
    if not isinstance(providers, dict):
        payload["providers"] = providers = {}
    provider_payload = providers.setdefault(provider, {})
    if not isinstance(provider_payload, dict):
        providers[provider] = provider_payload = {}
    provider_payload.setdefault("pinned", [])
    return provider_payload


def _pinned_key_refs(provider: str) -> list[str]:
    cache = _key_provider_cache(_read_key_cache(), provider)
    pinned = cache.get("pinned", [])
    return [str(item).strip() for item in pinned if str(item).strip()] if isinstance(pinned, list) else []


def _pin_api_key(provider: str, key_ref: str) -> None:
    key_ref = str(key_ref or "").strip()
    if not key_ref or key_ref.startswith("__"):
        return
    known_refs = {entry.get("ref", "") for entry in api_key_entries(provider)}
    if key_ref not in known_refs:
        return
    payload = _read_key_cache()
    cache = _key_provider_cache(payload, provider)
    pinned = [str(item).strip() for item in cache.get("pinned", []) if str(item).strip()]
    if key_ref not in pinned:
        pinned.insert(0, key_ref)
    cache["pinned"] = pinned[:20]
    _write_key_cache(payload)


def pin_api_key_ref(provider: str, key_ref: str) -> None:
    provider = str(provider or "").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported key provider: {provider}")
    _pin_api_key(provider, key_ref)


def unpin_api_key_ref(provider: str, key_ref: str) -> None:
    provider = str(provider or "").strip().lower()
    key_ref = str(key_ref or "").strip()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported key provider: {provider}")
    if not key_ref or key_ref.startswith("__"):
        raise RuntimeError("No API key selected.")
    payload = _read_key_cache()
    cache = _key_provider_cache(payload, provider)
    cache["pinned"] = [str(item).strip() for item in cache.get("pinned", []) if str(item).strip() and str(item).strip() != key_ref]
    _write_key_cache(payload)


def api_key_is_pinned(provider: str, key_ref: str) -> bool:
    provider = str(provider or "").strip().lower()
    key_ref = str(key_ref or "").strip()
    return bool(provider in MODEL_PROVIDERS and key_ref and key_ref in _pinned_key_refs(provider))


def _api_key_file_for_provider(provider: str) -> Path:
    provider = str(provider or "").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported key provider: {provider}")
    settings = load_settings()
    rel = str(get_path(settings, f"providers.{provider}.api_key_file", "") or "").strip()
    if not rel:
        raise RuntimeError(f"No API key file is configured for {provider}.")
    return CONFIG_DIR / rel


def _safe_key_file_part(value: str) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("|", "/").strip()


def _looks_like_api_key_value(provider: str, value: str) -> bool:
    text = str(value or "").strip()
    if not text or any(char.isspace() for char in text):
        return False
    if provider == "openai":
        return text.startswith(("sk-", "sess-"))
    if provider == "gemini":
        return text.startswith("AIza")
    if provider == "xai":
        return text.startswith("xai-") or len(text) >= 20
    if provider == "anthropic":
        return text.startswith("sk-ant-")
    return len(text) >= 20


def _normalize_new_api_key_entry(provider: str, label: str, api_key: str, note: str) -> tuple[str, str, str]:
    label_text = str(label or "").strip()
    note_text = str(note or "").strip()
    raw_text = str(api_key or "").strip()
    parsed_entries = parse_api_key_entries(provider, raw_text)

    selected: dict[str, str] | None = None
    for entry in parsed_entries:
        if _looks_like_api_key_value(provider, str(entry.get("key") or "")):
            selected = entry
            break
    if selected is None and parsed_entries:
        selected = parsed_entries[0]

    if selected is not None:
        if not label_text:
            label_text = str(selected.get("label") or "").strip()
        if not note_text:
            note_text = str(selected.get("note") or "").strip()
        key_text = str(selected.get("key") or "").strip()
    else:
        key_text = ""
        for line in raw_text.replace("\r", "\n").split("\n"):
            candidate = line.strip().strip('"').strip("'")
            if candidate:
                key_text = candidate
                break

    key_text = key_text.replace("\r", "").replace("\n", "").strip().strip('"').strip("'")
    return label_text, key_text, note_text


def add_api_key_entry(provider: str, label: str, api_key: str, note: str = "") -> dict[str, str]:
    provider = str(provider or "").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported key provider: {provider}")
    label, api_key, note = _normalize_new_api_key_entry(provider, label, api_key, note)
    if not api_key:
        raise RuntimeError("API key is empty.")
    path = _api_key_file_for_provider(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8-sig", errors="replace") if path.exists() else ""
    label = _safe_key_file_part(label) or f"{provider.upper()} key {len(api_key_entries(provider)) + 1}"
    note = _safe_key_file_part(note)
    line = f"{label} | {api_key}" + (f" | {note}" if note else "")
    prefix = existing.rstrip("\r\n")
    text = f"{prefix}\n{line}\n" if prefix else f"{line}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    entries = api_key_entries(provider)
    for entry in reversed(entries):
        if entry.get("key") == api_key:
            return {key: str(value) for key, value in entry.items() if key != "key"}
    return {"ref": "", "label": label, "note": note}


def delete_api_key_entry(provider: str, key_ref: str) -> dict[str, str]:
    provider = str(provider or "").strip().lower()
    key_ref = str(key_ref or "").strip()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported key provider: {provider}")
    if not key_ref or key_ref.startswith("__"):
        raise RuntimeError("No API key selected.")
    path = _api_key_file_for_provider(provider)
    if not path.exists():
        raise RuntimeError(f"API key file was not found for {provider}.")
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    kept: list[str] = []
    deleted: dict[str, str] | None = None
    for raw_line in lines:
        parsed = parse_api_key_entries(provider, raw_line)
        if deleted is None and parsed and parsed[0].get("ref") == key_ref:
            deleted = {key: str(value) for key, value in parsed[0].items() if key != "key"}
            continue
        kept.append(raw_line)
    if deleted is None:
        raise RuntimeError("Selected API key was not found in the key file.")
    path.write_text(("\n".join(kept).rstrip("\n") + "\n") if kept else "", encoding="utf-8", newline="\n")
    unpin_api_key_ref(provider, key_ref)
    return deleted


def _api_key_option_label(entry: dict[str, str]) -> str:
    label = str(entry.get("label") or entry.get("ref") or "API key").strip()
    note = str(entry.get("note") or "").strip()
    return f"{label} - {note}" if note else label


def _api_key_options(provider: str) -> list[dict[str, str]]:
    options = [_option("", "Config/env default", "По умолчанию из env/config")]
    entries = api_key_entries(provider)
    by_ref = {entry.get("ref", ""): entry for entry in entries}

    for key_ref in _pinned_key_refs(provider):
        entry = by_ref.get(key_ref)
        if entry:
            label = _api_key_option_label(entry)
            options.append(_option(key_ref, f"[FAV] {label}", f"[ИЗБР] {label}"))

    for entry in entries:
        key_ref = entry.get("ref", "")
        if not key_ref:
            continue
        label = _api_key_option_label(entry)
        options.append(_option(key_ref, label, label))

    if len(options) == 1:
        options.append(_option("__missing_key_file__", f"No {provider} key entries found", f"Нет ключей {provider}"))
    return _dedupe_options(options)


def openai_api_key_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    return _api_key_options("openai")


def gemini_api_key_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    return _api_key_options("gemini")


def xai_api_key_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    return _api_key_options("xai")


def anthropic_api_key_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    return _api_key_options("anthropic")


def _format_size(size_bytes: Any) -> str:
    size = _as_int(size_bytes, 0)
    if size <= 0:
        return ""
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def _audit_rule_option_label(entry: dict[str, Any]) -> str:
    label = str(entry.get("label") or entry.get("filename") or entry.get("ref") or "Audit rules").strip()
    note = str(entry.get("note") or "").strip()
    ref = str(entry.get("ref") or "").strip()
    size = _format_size(entry.get("size_bytes"))
    details = ", ".join(part for part in [size, ref] if part)
    text = f"{label} - {note}" if note else label
    return f"{text} ({details})" if details else text


def audit_rule_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    options = [_option("", "Active/default audit rules", "Активные правила по умолчанию")]
    entries = rule_entries()
    by_ref = {str(entry.get("ref") or ""): entry for entry in entries}
    active_ref_value = active_rule_ref()

    for rule_ref in pinned_rule_refs():
        entry = by_ref.get(rule_ref)
        if entry:
            label = _audit_rule_option_label(entry)
            options.append(_option(rule_ref, f"[FAV] {label}", f"[ИЗБР] {label}"))

    frequent = sorted(
        (entry for entry in entries if int(entry.get("usage_count") or 0) > 0),
        key=lambda item: int(item.get("usage_count") or 0),
        reverse=True,
    )
    for entry in frequent:
        rule_ref = str(entry.get("ref") or "")
        if rule_ref:
            label = f"[USED {entry.get('usage_count')}] {_audit_rule_option_label(entry)}"
            options.append(_option(rule_ref, label, label))

    for entry in entries:
        rule_ref = str(entry.get("ref") or "")
        if not rule_ref:
            continue
        prefix = "[ACTIVE] " if rule_ref == active_ref_value else ""
        label = f"{prefix}{_audit_rule_option_label(entry)}"
        options.append(_option(rule_ref, label, label))

    if len(options) == 1:
        options.append(_option("__missing_rules__", "No audit rule files found", "Нет файлов правил аудита"))
    return _dedupe_options(options)


def _doc_task_option_label(entry: dict[str, Any]) -> str:
    label = str(entry.get("label") or entry.get("filename") or entry.get("ref") or "Document task").strip()
    note = str(entry.get("note") or "").strip()
    ref = str(entry.get("ref") or "").strip()
    size = _format_size(entry.get("size_bytes"))
    details = ", ".join(part for part in [size, ref] if part)
    text = f"{label} - {note}" if note else label
    return f"{text} ({details})" if details else text


def doc_task_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    options = [_option("", "Active/default document task", "Активная задача по умолчанию")]
    entries = doc_task_entries()
    by_ref = {str(entry.get("ref") or ""): entry for entry in entries}
    active_ref_value = active_doc_task_ref()

    for task_ref in pinned_doc_task_refs():
        entry = by_ref.get(task_ref)
        if entry:
            label = _doc_task_option_label(entry)
            options.append(_option(task_ref, f"[FAV] {label}", f"[ИЗБР] {label}"))

    frequent = sorted(
        (entry for entry in entries if int(entry.get("usage_count") or 0) > 0),
        key=lambda item: int(item.get("usage_count") or 0),
        reverse=True,
    )
    for entry in frequent:
        task_ref = str(entry.get("ref") or "")
        if task_ref:
            label = f"[USED {entry.get('usage_count')}] {_doc_task_option_label(entry)}"
            options.append(_option(task_ref, label, label))

    for entry in entries:
        task_ref = str(entry.get("ref") or "")
        if not task_ref:
            continue
        prefix = "[ACTIVE] " if task_ref == active_ref_value else ""
        label = f"{prefix}{_doc_task_option_label(entry)}"
        options.append(_option(task_ref, label, label))

    if len(options) == 1:
        options.append(_option("__missing_doc_tasks__", "No document task instructions found", "Нет инструкций задач"))
    return _dedupe_options(options)


def _quick_doc_task_option_label(entry: dict[str, Any]) -> str:
    label = str(entry.get("label") or entry.get("ref") or "Quick document task").strip()
    note = str(entry.get("note") or "").strip()
    ref = str(entry.get("ref") or entry.get("quick_ref") or "").strip()
    size = _format_size(entry.get("size_bytes"))
    details = ", ".join(part for part in [size, ref] if part)
    text = f"{label} - {note}" if note else label
    return f"{text} ({details})" if details else text


def quick_doc_task_options(root: Path | str | None = None) -> list[dict[str, str]]:
    del root
    options = [_option("", "Textarea / latest typed instruction", "Текстовое поле / новая инструкция")]
    entries = quick_doc_task_entries()
    by_ref = {str(entry.get("ref") or ""): entry for entry in entries}

    for quick_ref in pinned_quick_doc_task_refs():
        entry = by_ref.get(quick_ref)
        if entry:
            label = _quick_doc_task_option_label(entry)
            options.append(_option(quick_ref, f"[FAV] {label}", f"[ИЗБР] {label}"))

    frequent = sorted(
        (entry for entry in entries if int(entry.get("usage_count") or 0) > 0),
        key=lambda item: int(item.get("usage_count") or 0),
        reverse=True,
    )
    for entry in frequent:
        quick_ref = str(entry.get("ref") or "")
        if quick_ref:
            label = f"[USED {entry.get('usage_count')}] {_quick_doc_task_option_label(entry)}"
            options.append(_option(quick_ref, label, label))

    for entry in entries:
        quick_ref = str(entry.get("ref") or "")
        if quick_ref:
            label = _quick_doc_task_option_label(entry)
            options.append(_option(quick_ref, label, label))

    return _dedupe_options(options)


def _configured_model_options(provider: str, default_tier: str = "audit") -> list[dict[str, str]]:
    """Return model dropdown auto/default entries.

    Static model ids are no longer curated in llm_settings.yaml. The empty
    dropdown value resolves to the latest OK smoke-checked model, then the
    first favorite model in config/gui_model_cache.json. Legacy model entries
    are still shown if an older config file contains them.
    """
    options: list[dict[str, str]] = []
    try:
        settings = load_settings()
        configured = str(resolve_model(provider, default_tier, settings) or "").strip()
        if configured:
            options.append(
                _option(
                    "",
                    f"Auto default ({default_tier}): {_model_label_with_status(provider, configured)}",
                    f"Авто ({default_tier}): {_model_label_with_status(provider, configured)}",
                )
            )
        else:
            options.append(
                _option(
                    "",
                    "Select model from live/cache list",
                    "Выберите модель из live/cache списка",
                )
            )

        provider_models = get_path(settings, f"models.{provider}", {})
        if isinstance(provider_models, dict):
            for tier, model in provider_models.items():
                model_id = str(model or "").strip()
                if not model_id:
                    continue
                label = f"[LEGACY CONFIG:{tier}] {_model_label_with_status(provider, model_id)}"
                options.append(_option(model_id, label, label))
    except Exception as exc:
        message = f"Model fallback failed: {exc.__class__.__name__}: {exc}"
        options.append(_option("__config_failed__", message, message))

    return options or [_option("", "Select model from live/cache list", "Выберите модель из live/cache списка")]


def _key_ref_from_values(provider: str, values: dict[str, Any] | None) -> str:
    if not isinstance(values, dict):
        return ""
    return str(values.get(f"{provider}_api_key_ref") or "").strip()


def openai_model_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Live OpenAI model dropdown provider for GUI fields.

    The first item is the auto fallback from smoke/favorites cache. If the live
    API request fails, the dropdown remains usable and shows cached models plus
    the error as a non-fatal item.
    """
    del root
    base_options = _configured_model_options("openai", "audit")
    cache_options = _model_options_from_cache("openai")
    options = [*base_options]
    try:
        from openai import OpenAI

        settings = load_settings()
        key_ref = _key_ref_from_values("openai", values)
        api_key = resolve_api_key("openai", settings, key_ref=key_ref)
        if not api_key:
            return _prioritize_pinned_model_options(
                "openai",
                [*base_options, *cache_options, _option("__missing_key__", "OpenAI API key not found", "OpenAI API key не найден")],
            )

        client = OpenAI(api_key=api_key, timeout=20.0, max_retries=1)
        models = client.models.list()
        model_ids = sorted(
            str(model.id)
            for model in getattr(models, "data", []) or []
            if str(getattr(model, "id", "")).strip()
        )
        for model_id in model_ids:
            label = _model_label_with_status("openai", model_id)
            options.append(_option(model_id, label, label))
        _remember_models("openai", model_ids)
    except Exception as exc:
        message = f"OpenAI model request failed: {exc.__class__.__name__}: {exc}"
        options.extend(cache_options)
        options.append(_option("__request_failed__", message, message))
    return _prioritize_pinned_model_options("openai", options)


def gemini_model_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Live Gemini model dropdown provider for GUI fields."""
    del root
    base_options = _configured_model_options("gemini", "audit_fast")
    cache_options = _model_options_from_cache("gemini")
    options = [*base_options]
    try:
        from google import genai

        settings = load_settings()
        key_ref = _key_ref_from_values("gemini", values)
        api_key = resolve_api_key("gemini", settings, key_ref=key_ref)
        if not api_key:
            return _prioritize_pinned_model_options(
                "gemini",
                [*base_options, *cache_options, _option("__missing_key__", "Gemini API key not found", "Gemini API key не найден")],
            )

        client = genai.Client(api_key=api_key)
        model_ids: list[str] = []
        for model in client.models.list():
            raw_name = str(getattr(model, "name", "") or "").strip()
            if not raw_name:
                continue
            actions = getattr(model, "supported_actions", None)
            if actions and "generateContent" not in set(str(action) for action in actions):
                continue
            model_id = raw_name.split("/")[-1]
            label = model_id
            display_name = str(getattr(model, "display_name", "") or "").strip()
            if display_name and display_name != model_id:
                label = f"{model_id} - {display_name}"
            label = _model_label_with_status("gemini", model_id, label)
            options.append(_option(model_id, label, label))
            model_ids.append(model_id)
        _remember_models("gemini", model_ids)
    except Exception as exc:
        message = f"Gemini model request failed: {exc.__class__.__name__}: {exc}"
        options.extend(cache_options)
        options.append(_option("__request_failed__", message, message))
    return _prioritize_pinned_model_options("gemini", options)


def xai_model_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Live xAI model dropdown provider for GUI fields."""
    del root
    base_options = _configured_model_options("xai", "audit")
    cache_options = _model_options_from_cache("xai")
    options = [*base_options]
    try:
        from system_core.providers.xai_provider import list_models

        settings = load_settings()
        key_ref = _key_ref_from_values("xai", values)
        api_key = resolve_api_key("xai", settings, key_ref=key_ref)
        if not api_key:
            return _prioritize_pinned_model_options(
                "xai",
                [*base_options, *cache_options, _option("__missing_key__", "xAI API key not found", "xAI API key не найден")],
            )

        model_ids = list_models(api_key, timeout_sec=30.0)
        for model_id in model_ids:
            label = _model_label_with_status("xai", model_id)
            options.append(_option(model_id, label, label))
        _remember_models("xai", model_ids)
    except Exception as exc:
        message = f"xAI model request failed: {exc.__class__.__name__}: {exc}"
        options.extend(cache_options)
        options.append(_option("__request_failed__", message, message))
    return _prioritize_pinned_model_options("xai", options)


def anthropic_model_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Live Anthropic model dropdown provider for GUI fields."""
    del root
    base_options = _configured_model_options("anthropic", "audit")
    cache_options = _model_options_from_cache("anthropic")
    options = [*base_options]
    try:
        from system_core.providers.anthropic_provider import list_models

        settings = load_settings()
        key_ref = _key_ref_from_values("anthropic", values)
        api_key = resolve_api_key("anthropic", settings, key_ref=key_ref)
        if not api_key:
            return _prioritize_pinned_model_options(
                "anthropic",
                [
                    *base_options,
                    *cache_options,
                    _option("__missing_key__", "Anthropic API key not found", "Anthropic API key не найден"),
                ],
            )

        model_ids = list_models(api_key, timeout_sec=30.0)
        for model_id in model_ids:
            label = _model_label_with_status("anthropic", model_id)
            options.append(_option(model_id, label, label))
        _remember_models("anthropic", model_ids)
    except Exception as exc:
        message = f"Anthropic model request failed: {exc.__class__.__name__}: {exc}"
        options.extend(cache_options)
        options.append(_option("__request_failed__", message, message))
    return _prioritize_pinned_model_options("anthropic", options)


def _option_input_dir(project_root: Path, values: dict[str, Any] | None = None) -> Path:
    selected = str((values or {}).get("source_dir") or "").strip()
    return Path(selected).expanduser().resolve(strict=False) if selected else project_root / "input"


def input_file_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    input_dir = _option_input_dir(project_root, values)
    if not input_dir.exists():
        return [_option("", "input is missing", "input не найден")]

    files = (
        [input_dir]
        if input_dir.is_file() and input_dir.suffix.lower() in SUPPORTED_TASK_INPUTS
        else sorted(
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.name != ".gitkeep" and path.suffix.lower() in SUPPORTED_TASK_INPUTS
        )
    )
    if not files:
        return [_option("", "No DOCX/PPTX/XLSX/PDF files in input", "В input нет DOCX/PPTX/XLSX/PDF")]
    return [_option(path.name, path.name) if input_dir.is_file() else _option(path.relative_to(input_dir).as_posix(), path.relative_to(input_dir).as_posix()) for path in files[:200]]


def template_file_options(root: Path | str | None = None, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    input_dir = _option_input_dir(project_root, values)
    options = [_option("", "Auto detect single DOCX/XLSX template", "Авто: единственный DOCX/XLSX-шаблон")]
    if not input_dir.exists():
        return options
    files = (
        [input_dir]
        if input_dir.is_file() and input_dir.suffix.lower() in SUPPORTED_TASK_TEMPLATES
        else sorted(
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.name != ".gitkeep" and path.suffix.lower() in SUPPORTED_TASK_TEMPLATES
        )
    )
    options.extend(_option(path.name, path.name) if input_dir.is_file() else _option(path.relative_to(input_dir).as_posix(), path.relative_to(input_dir).as_posix()) for path in files[:200])
    return options


def _document_inventory(input_dir: Path) -> dict[str, Any]:
    files = (
        [input_dir]
        if input_dir.is_file() and input_dir.suffix.lower() in SUPPORTED_TASK_INPUTS
        else sorted(
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.name != ".gitkeep" and path.suffix.lower() in SUPPORTED_TASK_INPUTS
        )
    )
    return {
        "documents": len(files),
        "docx": sum(1 for path in files if path.suffix.lower() == ".docx"),
        "pptx": sum(1 for path in files if path.suffix.lower() == ".pptx"),
        "xlsx": sum(1 for path in files if path.suffix.lower() == ".xlsx"),
        "pdf": sum(1 for path in files if path.suffix.lower() == ".pdf"),
        "files": [path.name if input_dir.is_file() else path.relative_to(input_dir).as_posix() for path in files[:100]],
    }


def validate_input(context: JobContext) -> dict[str, Any]:
    if not context.paths.input.exists():
        context.paths.input.mkdir(parents=True, exist_ok=True)
    inventory = _document_inventory(context.paths.input)
    context.log(f"Input folder: {context.paths.input}")
    context.log(
        f"DOCX/PPTX/XLSX/PDF: {inventory['documents']} "
        f"(docx={inventory['docx']}, pptx={inventory['pptx']}, xlsx={inventory['xlsx']}, pdf={inventory['pdf']})"
    )
    for item in inventory["files"]:
        context.log(f"  - {item}")
    context.progress(1.0)
    return inventory


def _pipeline_script(context: JobContext) -> Path:
    script = context.paths.system_core / "pipeline.py"
    if not script.exists():
        raise RuntimeError(f"pipeline.py was not found: {script}")
    return script


def _comma_restore_script(context: JobContext) -> Path:
    script = context.paths.system_core / "comma_lowercase_restore.py"
    if not script.exists():
        raise RuntimeError(f"comma_lowercase_restore.py was not found: {script}")
    return script


def _document_normalizer_script(context: JobContext) -> Path:
    script = context.paths.system_core / "document_normalizer.py"
    if not script.exists():
        raise RuntimeError(f"document_normalizer.py was not found: {script}")
    return script


def _python_executable(context: JobContext) -> str:
    candidates = [
        context.paths.root / "runtime" / "python.exe",
        context.paths.root / "runtime" / "python" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    current = Path(sys.executable)
    if current.name.lower() == "pythonw.exe":
        console_python = current.with_name("python.exe")
        if console_python.exists():
            return str(console_python)
    return sys.executable


def _resolve_user_path(context: JobContext, value: Any, default: str) -> Path:
    if not str(value or "").strip():
        if default == "input":
            return context.paths.input
        if default == "output":
            return context.paths.output
    text = str(value or default).strip().strip('"')
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = context.paths.root / path
    return path


def _settings_default(provider: str, key: str, default: Any) -> Any:
    try:
        settings = load_settings()
        return get_path(settings, f"audit.{provider}.{key}", default)
    except Exception:
        return default


def _selected_model(params: dict[str, Any], provider: str, tier: str) -> str:
    override = str(params.get(f"{provider}_model_override") or "").strip()
    if override:
        return override
    selected = str(params.get(f"{provider}_model") or "").strip()
    if selected and not selected.startswith("__"):
        return selected
    return _configured_model(provider, tier)


def _selected_api_key_ref(params: dict[str, Any], provider: str) -> str:
    selected = str(params.get(f"{provider}_api_key_ref") or "").strip()
    return "" if selected.startswith("__") else selected


def _selected_audit_rule_ref(params: dict[str, Any]) -> str:
    selected = str(params.get("audit_rule_ref") or "").strip()
    return "" if selected.startswith("__") else selected


def _selected_doc_task_ref(params: dict[str, Any]) -> str:
    selected = str(params.get("doc_task_ref") or "").strip()
    return "" if selected.startswith("__") else selected


def _selected_quick_doc_task_ref(params: dict[str, Any]) -> str:
    selected = str(params.get("quick_doc_task_ref") or "").strip()
    return "" if selected.startswith("__") else selected


def _api_key_label(provider: str, key_ref: str) -> str:
    if not key_ref:
        return "env/config default"
    for entry in api_key_entries(provider):
        if entry.get("ref") == key_ref:
            return _api_key_option_label(entry)
    return key_ref


def _classify_model_check_error(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    text = str(exc).lower()
    no_access_markers = {
        "not found",
        "not available",
        "does not exist",
        "permission",
        "forbidden",
        "unauthorized",
        "invalid api key",
        "api key not valid",
        "access",
        "404",
        "403",
        "401",
    }
    if status_code in {401, 403, 404} or any(marker in text for marker in no_access_markers):
        return "no_access"
    return "error"


def _check_openai_model(model: str, api_key: str) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=20.0, max_retries=0)
    kwargs: dict[str, Any] = {
        "model": model,
        "input": MODEL_CHECK_PROMPT,
        "max_output_tokens": 16,
    }
    client.responses.create(**kwargs)
    return "ok", "Responses API accepted the model."


def _check_gemini_model(model: str, api_key: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=8)
    client.models.generate_content(model=model, contents=MODEL_CHECK_PROMPT, config=config)
    return "ok", "generateContent accepted the model."


def _check_xai_model(model: str, api_key: str) -> tuple[str, str]:
    from system_core.providers.xai_provider import check_model

    return check_model(api_key, model, timeout_sec=20.0)


def _check_anthropic_model(model: str, api_key: str) -> tuple[str, str]:
    from system_core.providers.anthropic_provider import check_model

    return check_model(api_key, model, timeout_sec=20.0)


def _check_selected_model(context: JobContext, params: dict[str, Any]) -> None:
    provider = str(params.get("provider") or "openai").strip().lower()
    if provider not in MODEL_PROVIDERS:
        raise RuntimeError(f"Unsupported model provider: {provider}")
    tier = str(params.get("model_tier") or ("audit_fast" if provider == "gemini" else "audit")).strip()
    model = _selected_model(params, provider, tier)
    if not model:
        raise RuntimeError("No model selected or configured to check.")

    settings = load_settings()
    key_ref = _selected_api_key_ref(params, provider)
    api_key = resolve_api_key(provider, settings, key_ref=key_ref)
    if not api_key:
        message = "API key not found."
        _remember_model_check(provider, model, "no_access", message, key_ref=key_ref)
        context.log(f"[MODEL CHECK] {provider}: {model} -> no_access ({message})")
        context.progress(1.0)
        raise RuntimeError(f"Model check failed: {message}")

    try:
        if provider == "openai":
            status, message = _check_openai_model(model, api_key)
        elif provider == "gemini":
            status, message = _check_gemini_model(model, api_key)
        elif provider == "anthropic":
            status, message = _check_anthropic_model(model, api_key)
        else:
            status, message = _check_xai_model(model, api_key)
    except Exception as exc:
        status = _classify_model_check_error(exc)
        message = f"{exc.__class__.__name__}: {str(exc)}"

    _remember_model_check(provider, model, status, message, key_ref=key_ref)
    context.log(f"[MODEL CHECK] {provider}: {model} -> {status} ({message[:240]})")
    context.progress(1.0)
    if status != "ok":
        raise RuntimeError(f"Model check {status}: {message[:300]}")


def _api_key_env_for_run(context: JobContext, params: dict[str, Any]) -> dict[str, str]:
    provider = str(params.get("provider") or "openai").strip().lower()
    if provider not in MODEL_PROVIDERS:
        return {}

    settings = load_settings()
    env_name = str(get_path(settings, f"providers.{provider}.api_key_env", "") or "").strip()
    if not env_name:
        return {}

    key_ref = _selected_api_key_ref(params, provider)
    api_key = resolve_api_key(provider, settings, key_ref=key_ref)
    if not api_key:
        return {}

    if _as_bool(params.get(f"{provider}_pin_api_key"), False):
        _pin_api_key(provider, key_ref)
    context.log(f"[API KEY] {provider}: {_api_key_label(provider, key_ref)}")
    return {env_name: api_key}


def _audit_rule_env_for_run(context: JobContext, params: dict[str, Any]) -> dict[str, str]:
    rule_ref = _selected_audit_rule_ref(params)
    _path, entry = resolve_rule_entry(rule_ref)
    if not entry:
        return {}
    resolved_ref = str(entry.get("ref") or rule_ref).strip()
    if not resolved_ref:
        return {}
    if _as_bool(params.get("audit_rule_pin"), False):
        pin_rule(resolved_ref)
    remember_rule_use(resolved_ref)
    context.log(f"[RULES] {_audit_rule_option_label(entry)}")
    return {RULE_ENV: resolved_ref}


def _audit_env_for_run(context: JobContext, params: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    env.update(_api_key_env_for_run(context, params))
    env.update(_audit_rule_env_for_run(context, params))
    return env


def _doc_task_env_for_run(context: JobContext, params: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    env.update(_api_key_env_for_run(context, params))
    if _as_bool(params.get("quick_doc_task"), False):
        quick_ref = _selected_quick_doc_task_ref(params)
        quick_text = str(params.get("quick_doc_task_instruction") or "").strip()
        quick_label = str(params.get("quick_doc_task_label") or "").strip()
        quick_note = str(params.get("quick_doc_task_note") or "").strip()

        if quick_text:
            entry = save_quick_doc_task(quick_text, label=quick_label, note=quick_note, pin=False)
            quick_ref = str(entry.get("ref") or "")
            context.log(f"[QUICK DOC TASK] {_quick_doc_task_option_label(entry)}")
        elif quick_ref:
            entry = resolve_quick_doc_task_entry(quick_ref)
            if not entry:
                raise RuntimeError("Selected quick document task was not found in cache.")
            quick_text = str(entry.get("content") or "").strip()
            context.log(f"[QUICK DOC TASK] {_quick_doc_task_option_label(entry)}")
        else:
            task_ref = _selected_doc_task_ref(params)
            _path, entry = resolve_doc_task_entry(task_ref)
            if not entry:
                raise RuntimeError("Quick document task instruction is empty.")
            resolved_ref = str(entry.get("ref") or task_ref).strip()
            if not resolved_ref:
                raise RuntimeError("Quick document task instruction is empty.")
            context.log(f"[DOC TASK] {_doc_task_option_label(entry)}")
            remember_doc_task_use(resolved_ref)
            env[TASK_ENV] = resolved_ref

        if quick_text:
            if quick_ref:
                remember_quick_doc_task_use(quick_ref)
                env[TASK_QUICK_REF_ENV] = quick_ref
            env[TASK_TEXT_ENV] = quick_text
        elif TASK_ENV not in env:
            raise RuntimeError("Quick document task instruction is empty.")
    else:
        task_ref = _selected_doc_task_ref(params)
        _path, entry = resolve_doc_task_entry(task_ref)
        if entry:
            resolved_ref = str(entry.get("ref") or task_ref).strip()
            if resolved_ref:
                if _as_bool(params.get("doc_task_pin"), False):
                    pin_doc_task(resolved_ref)
                remember_doc_task_use(resolved_ref)
                context.log(f"[DOC TASK] {_doc_task_option_label(entry)}")
                env[TASK_ENV] = resolved_ref

    query = str(params.get("doc_task_query") or "").strip()
    if query:
        context.log(f"[DOC TASK QUERY] {query[:240]}")
        env[TASK_QUERY_ENV] = query
    return env


def _audit_args(context: JobContext, params: dict[str, Any]) -> list[str]:
    provider = str(params.get("provider") or "openai").strip().lower()
    tier = str(params.get("model_tier") or "audit").strip()
    report_lang = str(params.get("report_lang") or "ru").strip().lower()
    default_reasoning = DEFAULT_AUDIT_REASONING.get(provider, "selected")
    reasoning = str(params.get(f"{provider}_reasoning") or params.get("reasoning") or default_reasoning).strip()
    model = _selected_model(params, provider, tier)
    if _as_bool(params.get(f"{provider}_pin_model"), False):
        _pin_model(provider, model)
        if model:
            context.log(f"[MODEL FAV] {provider}: {model}")

    prefix = provider
    chunk_tokens = _as_int(params.get(f"{prefix}_chunk_tokens"), int(_settings_default(provider, "chunk_tokens", 12000)))
    overlap_tokens = _as_int(params.get(f"{prefix}_overlap_tokens"), int(_settings_default(provider, "overlap_tokens", 1200)))
    min_chunks = _as_int(params.get(f"{prefix}_min_chunks"), int(_settings_default(provider, "min_chunks", 4)))
    max_retries = _as_int(params.get(f"{prefix}_max_retries"), int(_settings_default(provider, "max_retries", 3)))
    max_output_tokens = _as_int(params.get(f"{prefix}_max_output_tokens"), int(_settings_default(provider, "max_output_tokens", 32000)))
    timeout_sec = _as_float(params.get(f"{prefix}_timeout_sec"), 420.0)
    workers = _as_int(params.get(f"{prefix}_workers"), int(_settings_default(provider, "workers", DEFAULT_WORKERS)))
    service_tier = str(params.get("openai_service_tier") or "default").strip() or "default"

    args = [
        "audit",
        "--recursive",
        "--renderer",
        "com",
        "--provider",
        provider,
        "--reasoning",
        reasoning,
        "--chunk-tokens",
        str(chunk_tokens),
        "--overlap-tokens",
        str(overlap_tokens),
        "--min-chunks",
        str(min_chunks),
        "--max-retries",
        str(max_retries),
        "--max-output-tokens",
        str(max_output_tokens),
        "--timeout-sec",
        str(timeout_sec),
        "--service-tier",
        service_tier,
        "--report-lang",
        report_lang,
        "--workers",
        str(workers),
    ]
    if model:
        args.extend(["--model", model])
    if _as_bool(params.get(f"{prefix}_resume"), True):
        args.append("--resume")
    if _as_bool(params.get("require_render_map"), False):
        args.append("--require-render-map")
    apply_fixes = str(params.get("apply_fixes") or "none").strip().lower()
    if apply_fixes in {"safe", "none"} and apply_fixes != "none":
        args.extend(["--apply-fixes", apply_fixes])

    context.log(
        "[AUDIT CONFIG] "
        f"provider={provider} model={model or '<config>'} reasoning={reasoning} "
        f"chunk={chunk_tokens} overlap={overlap_tokens} min_chunks={min_chunks} "
        f"retries={max_retries} timeout={timeout_sec} workers={workers}"
    )
    return args


def _doc_task_args(context: JobContext, params: dict[str, Any]) -> list[str]:
    provider = str(params.get("provider") or "openai").strip().lower()
    tier = str(params.get("model_tier") or ("audit_fast" if provider == "gemini" else "audit")).strip()
    if provider == "gemini" and tier == "audit":
        tier = "audit_fast"
    model = _selected_model(params, provider, tier)
    if _as_bool(params.get(f"{provider}_pin_model"), False):
        _pin_model(provider, model)
        if model:
            context.log(f"[MODEL FAV] {provider}: {model}")
    prefix = provider
    chunk_tokens = _as_int(params.get(f"{prefix}_chunk_tokens"), 12000)
    overlap_tokens = _as_int(params.get(f"{prefix}_overlap_tokens"), 0)
    min_chunks = _as_int(params.get(f"{prefix}_min_chunks"), 1)
    max_retries = _as_int(params.get(f"{prefix}_max_retries"), 1)
    max_output_tokens = _as_int(params.get(f"{prefix}_max_output_tokens"), 32000)
    timeout_sec = _as_float(params.get(f"{prefix}_timeout_sec"), 240.0)
    workers = _as_int(params.get(f"{prefix}_workers"), DEFAULT_WORKERS)
    service_tier = str(params.get("openai_service_tier") or "default").strip() or "default"
    task_ref = _selected_doc_task_ref(params)
    quick_task = _as_bool(params.get("quick_doc_task"), False)
    task_scope = str(params.get("doc_task_scope") or "auto").strip().lower()
    if task_scope not in {"auto", "document", "corpus"}:
        task_scope = "auto"
    apply_confidence = str(params.get("apply_confidence") or "high").strip().lower()
    if apply_confidence not in {"high", "medium", "low"}:
        apply_confidence = "high"
    pdf_max_pages = _as_int(params.get("pdf_max_pages"), 5)
    if pdf_max_pages < 0:
        pdf_max_pages = 5
    clean_table = _as_bool(params.get("doc_task_clean_table"), False)
    clean_template = str(params.get("doc_task_template_file") or "").strip()

    args = [
        "run",
        "--recursive",
        "--task-scope",
        task_scope,
        "--provider",
        provider,
        "--chunk-tokens",
        str(chunk_tokens),
        "--overlap-tokens",
        str(overlap_tokens),
        "--min-chunks",
        str(min_chunks),
        "--max-retries",
        str(max_retries),
        "--max-output-tokens",
        str(max_output_tokens),
        "--timeout-sec",
        str(timeout_sec),
        "--service-tier",
        service_tier,
        "--apply-confidence",
        apply_confidence,
        "--pdf-max-pages",
        str(pdf_max_pages),
        "--workers",
        str(workers),
    ]
    if clean_table:
        args.append("--clean-table")
    if clean_template:
        args.extend(["--clean-table-template", clean_template])
    if model:
        args.extend(["--model", model])
    if task_ref and not quick_task:
        args.extend(["--task-ref", task_ref])
    if _as_bool(params.get("doc_task_apply_replacements"), False):
        args.append("--apply-replacements")
    if _as_bool(params.get("docx_only"), False):
        args.append("--docx-only")
    if _as_bool(params.get(f"{prefix}_resume"), True):
        args.append("--resume")
    context.log(
        "[DOC TASK CONFIG] "
        f"provider={provider} model={model or '<config>'} quick={quick_task} chunk={chunk_tokens} "
        f"overlap={overlap_tokens} min_chunks={min_chunks} scope={task_scope} "
        f"replacements={_as_bool(params.get('doc_task_apply_replacements'), False)} "
        f"confidence={apply_confidence} clean_table={clean_table}"
    )
    return args


def _doc_task_script(context: JobContext) -> Path:
    script = context.paths.system_core / "doc_task_runner.py"
    if not script.exists():
        raise RuntimeError(f"doc_task_runner.py was not found: {script}")
    return script


def _run_pipeline(
    context: JobContext,
    args: list[str],
    progress: float | None = None,
    extra_env: dict[str, str] | None = None,
) -> None:
    command = [_python_executable(context), str(_pipeline_script(context)), *args]
    workbench_env = dict(extra_env or {})
    workbench_env.update({
        "AUDION_WORKBENCH_SOURCE": str(context.paths.input),
        "AUDION_WORKBENCH_TARGET": str(context.paths.output),
    })
    run_process(context, command, cwd=context.paths.root, extra_env=workbench_env, check=True, progress_seconds=900.0)
    if progress is not None:
        context.progress(progress)


def _run_doc_task(context: JobContext, args: list[str], progress: float | None = None, extra_env: dict[str, str] | None = None) -> None:
    command = [_python_executable(context), str(_doc_task_script(context)), *args]
    workbench_env = dict(extra_env or {})
    workbench_env.update({
        "AUDION_WORKBENCH_SOURCE": str(context.paths.input),
        "AUDION_WORKBENCH_TARGET": str(context.paths.output),
    })
    run_process(context, command, cwd=context.paths.root, extra_env=workbench_env, check=True, progress_seconds=900.0)
    if progress is not None:
        context.progress(progress)


def restore_comma_lowercase(context: JobContext) -> dict[str, Any]:
    params = dict(context.operation.parameters)
    report_path = _resolve_user_path(context, params.get("comma_report"), "report/comma_lowercase.json")
    source_path = _resolve_user_path(context, params.get("source_docx"), "input")
    fixed_path = _resolve_user_path(context, params.get("fixed_docx"), "output/comma_lowercase")
    output_path = _resolve_user_path(context, params.get("output_dir"), "output/comma_lowercase_restored")
    restore_map = _resolve_user_path(context, params.get("restore_map"), "config/comma_restore_map.yaml")
    decisions_path = _resolve_user_path(context, params.get("decisions_json"), "report/comma_lowercase_decisions.json")
    json_out = context.report_dir / "comma_lowercase_restore.json"
    md_out = context.report_dir / "comma_lowercase_restore.md"
    scope = str(params.get("scope") or "table-cells").strip() or "table-cells"

    args: list[str] = [
        "--report",
        str(report_path),
        "--source",
        str(source_path),
        "--fixed",
        str(fixed_path),
        "--output",
        str(output_path),
        "--restore-map",
        str(restore_map),
        "--json-out",
        str(json_out),
        "--md-out",
        str(md_out),
        "--scope",
        scope,
    ]
    if str(params.get("decisions_json") or "").strip():
        args.extend(["--decisions", str(decisions_path)])
    llm_provider = str(params.get("llm_provider") or "none").strip().lower()
    if llm_provider and llm_provider != "none":
        model_tier = "audit_fast" if llm_provider == "gemini" else "audit"
        llm_model = str(params.get("llm_model") or "").strip() or _selected_model(params, llm_provider, model_tier)
        key_ref = _selected_api_key_ref(params, llm_provider)
        if key_ref:
            args.extend([f"--{llm_provider}-api-key-ref", key_ref])
        args.extend(
            [
                "--llm-provider",
                llm_provider,
                "--llm-model",
                llm_model,
                "--llm-batch-size",
                str(_as_int(params.get("llm_batch_size"), 80)),
                "--llm-max-output-tokens",
                str(_as_int(params.get("llm_max_output_tokens"), 8000)),
                "--llm-max-retries",
                str(_as_int(params.get("llm_max_retries"), 2)),
                "--llm-timeout-sec",
                str(_as_float(params.get("llm_timeout_sec"), 300.0)),
                "--llm-reasoning-effort",
                str(params.get("openai_reasoning") or params.get("llm_reasoning_effort") or "low").strip(),
                "--decisions-out",
                str(context.report_dir / "comma_lowercase_decisions.json"),
            ]
        )
    if _as_bool(params.get("restore_all"), False):
        args.append("--restore-all")
    if _as_bool(params.get("dry_run"), False):
        args.append("--dry-run")
    if _as_bool(params.get("overwrite"), False):
        args.append("--overwrite")

    command = [_python_executable(context), str(_comma_restore_script(context)), *args]
    run_process(context, command, cwd=context.paths.root, check=True, progress_seconds=600.0)
    context.progress(1.0)
    return {
        "report": str(json_out),
        "md_report": str(md_out),
        "outdir": str(output_path),
    }


def normalize_documents_from_audit(context: JobContext) -> dict[str, Any]:
    params = dict(context.operation.parameters)
    provider = str(params.get("provider") or "all").strip().lower()
    if provider not in {"openai", "gemini", "xai", "anthropic", "all"}:
        provider = "all"
    logs_dir = _resolve_user_path(context, params.get("logs_dir"), "logs")
    input_dir = _resolve_user_path(context, params.get("input_dir"), "input")
    output_dir = _resolve_user_path(context, params.get("output_dir"), "output")
    report_dir = _resolve_user_path(context, params.get("report_dir"), "output/_normalization")
    patch_dir = _resolve_user_path(context, params.get("patch_dir"), "report/document_normalization")
    args = [
        "--provider",
        provider,
        "--from-logs",
        str(logs_dir),
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--report-dir",
        str(report_dir),
        "--patch-dir",
        str(patch_dir),
    ]
    if _as_bool(params.get("dry_run"), False):
        args.append("--dry-run")
    context.log(f"[NORMALIZE] provider={provider} logs={logs_dir}")
    command = [_python_executable(context), str(_document_normalizer_script(context)), *args]
    run_process(context, command, cwd=context.paths.root, check=True, progress_seconds=600.0)
    context.progress(1.0)
    return {"provider": provider, "report_dir": str(report_dir), "patch_dir": str(patch_dir)}


def run_doc_task_operation(context: JobContext) -> dict[str, Any]:
    params = dict(context.operation.parameters)
    mode = str(params.get("mode") or "").strip().lower()

    if mode == "pin_doc_task":
        task_ref = _selected_doc_task_ref(params)
        if not task_ref:
            raise RuntimeError("No document task instruction selected for favorites.")
        entry = pin_doc_task(task_ref)
        context.log(f"[DOC TASK FAV] {_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "set_active_doc_task":
        task_ref = _selected_doc_task_ref(params)
        if not task_ref:
            raise RuntimeError("No document task instruction selected.")
        entry = set_active_doc_task(task_ref)
        context.log(f"[DOC TASK ACTIVE] {_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "import_doc_task":
        source = str(params.get("doc_task_file") or "").strip()
        if not source:
            raise RuntimeError("No document task instruction file selected to import.")
        entry = import_doc_task_file(
            source,
            label=str(params.get("doc_task_label") or "").strip(),
            note=str(params.get("doc_task_note") or "").strip(),
            pin=_as_bool(params.get("doc_task_pin"), False),
            set_active=True,
        )
        context.log(f"[DOC TASK IMPORT] {_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "save_quick_doc_task":
        text = str(params.get("quick_doc_task_instruction") or "").strip()
        entry = save_quick_doc_task(
            text,
            label=str(params.get("quick_doc_task_label") or "").strip(),
            note=str(params.get("quick_doc_task_note") or "").strip(),
            pin=False,
        )
        context.log(f"[QUICK DOC TASK SAVE] {_quick_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "pin_quick_doc_task":
        quick_ref = _selected_quick_doc_task_ref(params)
        text = str(params.get("quick_doc_task_instruction") or "").strip()
        if quick_ref:
            entry = pin_quick_doc_task(quick_ref)
        elif text:
            entry = save_quick_doc_task(
                text,
                label=str(params.get("quick_doc_task_label") or "").strip(),
                note=str(params.get("quick_doc_task_note") or "").strip(),
                pin=True,
            )
        else:
            raise RuntimeError("No quick document task instruction selected for favorites.")
        context.log(f"[QUICK DOC TASK FAV] {_quick_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "unpin_quick_doc_task":
        quick_ref = _selected_quick_doc_task_ref(params)
        if not quick_ref:
            raise RuntimeError("Select a quick instruction to unpin.")
        entry = unpin_quick_doc_task(quick_ref)
        context.log(f"[QUICK DOC TASK UNPIN] {_quick_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "delete_quick_doc_task":
        quick_ref = _selected_quick_doc_task_ref(params)
        if not quick_ref:
            raise RuntimeError("Select a quick instruction to delete.")
        entry = delete_quick_doc_task(quick_ref)
        context.log(f"[QUICK DOC TASK DELETE] {_quick_doc_task_option_label(entry)}")
        context.progress(1.0)
    elif mode == "check_model":
        _check_selected_model(context, params)
    elif mode in {"run_doc_task", "run_quick_doc_task"}:
        _run_doc_task(context, _doc_task_args(context, params), 1.0, extra_env=_doc_task_env_for_run(context, params))
    else:
        raise RuntimeError(f"Unknown document task mode: {mode}")

    return {"mode": mode}


def run_pipeline_operation(context: JobContext) -> dict[str, Any]:
    params = dict(context.operation.parameters)
    mode = str(params.get("mode") or "").strip().lower()
    report_lang = str(params.get("report_lang") or "ru").strip().lower()

    if mode == "pin_model":
        provider = str(params.get("provider") or "openai").strip().lower()
        tier = str(params.get("model_tier") or "audit").strip()
        model = _selected_model(params, provider, tier)
        if not model:
            raise RuntimeError("No model selected or configured for favorites.")
        _pin_model(provider, model)
        context.log(f"[MODEL FAV] {provider}: {model}")
        context.progress(1.0)
    elif mode == "check_model":
        _check_selected_model(context, params)
    elif mode == "pin_api_key":
        provider = str(params.get("provider") or "openai").strip().lower()
        key_ref = _selected_api_key_ref(params, provider)
        if not key_ref:
            raise RuntimeError("No API key selected for favorites.")
        _pin_api_key(provider, key_ref)
        context.log(f"[API KEY FAV] {provider}: {_api_key_label(provider, key_ref)}")
        context.progress(1.0)
    elif mode == "pin_audit_rule":
        rule_ref = _selected_audit_rule_ref(params)
        if not rule_ref:
            raise RuntimeError("No audit rule file selected for favorites.")
        entry = pin_rule(rule_ref)
        context.log(f"[RULE FAV] {_audit_rule_option_label(entry)}")
        context.progress(1.0)
    elif mode == "set_active_audit_rule":
        rule_ref = _selected_audit_rule_ref(params)
        if not rule_ref:
            raise RuntimeError("No audit rule file selected.")
        entry = set_active_rule(rule_ref)
        context.log(f"[RULE ACTIVE] {_audit_rule_option_label(entry)}")
        context.progress(1.0)
    elif mode == "import_audit_rule":
        source = str(params.get("audit_rule_file") or "").strip()
        if not source:
            raise RuntimeError("No audit rule file selected to import.")
        entry = import_rule_file(
            source,
            label=str(params.get("audit_rule_label") or "").strip(),
            note=str(params.get("audit_rule_note") or "").strip(),
            pin=_as_bool(params.get("audit_rule_pin"), False),
            set_active=True,
        )
        context.log(f"[RULE IMPORT] {_audit_rule_option_label(entry)}")
        context.progress(1.0)
    elif mode == "scan":
        _run_pipeline(context, ["scan"], 1.0)
    elif mode == "render":
        _run_pipeline(context, ["render", "--recursive", "--renderer", "com"], 1.0)
    elif mode == "audit":
        _run_pipeline(context, _audit_args(context, params), 1.0, extra_env=_audit_env_for_run(context, params))
    elif mode == "report":
        _run_pipeline(context, ["report", "--from-logs", "logs", "--report-lang", report_lang], 1.0)
    elif mode == "annotate":
        _run_pipeline(context, ["annotate", "--from-logs", "logs"], 1.0)
    elif mode == "strip_anchors":
        _run_pipeline(context, ["strip-anchors", "--recursive"], 1.0)
    elif mode == "report_annotate":
        _run_pipeline(context, ["report", "--from-logs", "logs", "--report-lang", report_lang], 0.5)
        _run_pipeline(context, ["annotate", "--from-logs", "logs"], 1.0)
    elif mode == "full":
        _run_pipeline(context, ["scan"], 0.12)
        _run_pipeline(context, ["render", "--recursive", "--renderer", "com"], 0.32)
        _run_pipeline(context, _audit_args(context, params), 0.78, extra_env=_audit_env_for_run(context, params))
        _run_pipeline(context, ["report", "--from-logs", "logs", "--report-lang", report_lang], 0.9)
        _run_pipeline(context, ["annotate", "--from-logs", "logs"], 1.0)
    else:
        raise RuntimeError(f"Unknown pipeline mode: {mode}")

    return {"mode": mode}


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child_resolved = str(child.resolve())
        parent_resolved = str(parent.resolve())
        return os.path.commonpath([child_resolved, parent_resolved]) == parent_resolved
    except (OSError, ValueError):
        return False


def _clean_managed_folder(context: JobContext, folder: Path, label: str) -> dict[str, Any]:
    root = context.paths.root.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if folder.is_symlink() or not _is_inside(folder, root):
        raise RuntimeError(f"{label} cleanup blocked: folder is not a managed project folder.")

    removed = 0
    skipped: list[str] = []
    for item in folder.iterdir():
        if item.name == ".gitkeep":
            continue
        try:
            if item.is_symlink() or item.is_file():
                item.unlink()
            elif item.is_dir():
                if not _is_inside(item, folder.resolve()):
                    skipped.append(item.name)
                    continue
                shutil.rmtree(item)
            removed += 1
            context.log(f"Removed from {label}: {item.name}")
        except OSError as exc:
            skipped.append(f"{item.name} ({exc})")
    return {"removed_items": removed, "skipped_items": skipped}


def cleanup_input_output(context: JobContext) -> dict[str, Any]:
    context.log("Cleaning managed input/output folders.")
    input_result = _clean_managed_folder(context, context.paths.input, "input")
    context.progress(0.5)
    if context.cancelled():
        return {"cancelled": True, "input": input_result}
    output_result = _clean_managed_folder(context, context.paths.output, "output")
    context.progress(1.0)
    return {"input": input_result, "output": output_result}


def cleanup_workspace(context: JobContext) -> dict[str, Any]:
    workspace = context.paths.workspace
    context.log("Cleaning managed workspace folder.")
    result = _clean_managed_folder(context, workspace, "workspace")
    context.progress(1.0)
    return result
