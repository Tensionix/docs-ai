#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project config resolver for API keys and launcher-safe LLM settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "llm_settings.yaml"
MODEL_CACHE_FILE = CONFIG_DIR / "gui_model_cache.json"


def _strip_comment(line: str) -> str:
    in_quote = False
    quote = ""
    out = []
    for char in line:
        if char in {"'", '"'}:
            if in_quote and char == quote:
                in_quote = False
            elif not in_quote:
                in_quote = True
                quote = char
        if char == "#" and not in_quote:
            break
        out.append(char)
    return "".join(out).rstrip()


def _scalar(value: str) -> Any:
    raw = value.strip()
    if raw == "":
        return ""
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: list[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        item = line.strip()
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(value)

    return root


def load_settings() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        raise FileNotFoundError(f"Missing LLM settings: {SETTINGS_FILE}")
    return parse_simple_yaml(SETTINGS_FILE.read_text(encoding="utf-8-sig", errors="replace"))


def get_path(payload: Dict[str, Any], dotted: str, default: Any = "") -> Any:
    cur: Any = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _read_model_cache() -> Dict[str, Any]:
    if not MODEL_CACHE_FILE.exists():
        return {}
    try:
        payload = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8-sig", errors="replace"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def resolve_cached_model(provider: str) -> str:
    """Return the safest cache-backed default model for CLI/GUI fallback.

    A provider model list can include historical or account-inaccessible ids.
    Therefore we never pick an arbitrary cached list item. The fallback is:
    latest explicit OK smoke check, then first favorite model.
    """
    provider = str(provider or "").strip().lower()
    providers = _read_model_cache().get("providers", {})
    if not isinstance(providers, dict):
        return ""
    provider_payload = providers.get(provider, {})
    if not isinstance(provider_payload, dict):
        return ""

    checks = provider_payload.get("checks", {})
    if isinstance(checks, dict):
        ok_entries: list[tuple[str, str]] = []
        for model_id, entry in checks.items():
            model_text = str(model_id or "").strip()
            if not model_text or model_text.startswith("__") or not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "").strip().lower()
            checked_at = str(entry.get("checked_at") or "").strip()
            if status == "ok" and checked_at:
                ok_entries.append((checked_at, model_text))
        if ok_entries:
            ok_entries.sort(reverse=True)
            return ok_entries[0][1]

    pinned = provider_payload.get("pinned", [])
    if isinstance(pinned, list):
        for model_id in pinned:
            model_text = str(model_id or "").strip()
            if model_text and not model_text.startswith("__"):
                return model_text
    return ""


def _api_key_env_name(provider: str, settings: Dict[str, Any] | None = None) -> str:
    payload = settings or load_settings()
    provider_cfg = get_path(payload, f"providers.{provider}", {})
    if not isinstance(provider_cfg, dict):
        return ""
    return str(provider_cfg.get("api_key_env") or "").strip()


def _api_key_file_path(provider: str, settings: Dict[str, Any] | None = None) -> Path | None:
    payload = settings or load_settings()
    provider_cfg = get_path(payload, f"providers.{provider}", {})
    if not isinstance(provider_cfg, dict):
        return None
    key_file = str(provider_cfg.get("api_key_file") or "").strip()
    return CONFIG_DIR / key_file if key_file else None


def _looks_like_api_key(provider: str, value: str) -> bool:
    text = value.strip()
    if not text or any(char.isspace() for char in text):
        return False
    if provider == "openai":
        return text.startswith(("sk-", "sess-"))
    if provider == "gemini":
        return text.startswith("AIza")
    if provider == "anthropic":
        return text.startswith("sk-ant-")
    return len(text) >= 20


def _split_value_note(text: str) -> tuple[str, str]:
    for pattern in (r"\s+#", r"\s+;", r"\s+//"):
        match = re.search(pattern, text)
        if match:
            return text[: match.start()].strip(), text[match.end() :].strip()
    return text.strip(), ""


def _key_ref(provider: str, key: str) -> str:
    digest = hashlib.sha256(f"{provider}\0{key}".encode("utf-8")).hexdigest()
    return digest[:16]


def _default_key_label(provider: str, index: int) -> str:
    return f"{provider.upper()} key {index}"


def parse_api_key_entries(provider: str, text: str) -> list[dict[str, str]]:
    """Parse one or many API keys from a local key file.

    Supported lines:
      key
      key # comment
      label = key # comment
      label | key | comment
      key | comment

    Returned entries include the key for runtime resolution. GUI code should
    never persist or log the key field.
    """
    entries: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue

        label = ""
        note = ""
        key = ""

        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 2 and _looks_like_api_key(provider, parts[0]):
                key = parts[0]
                note = " | ".join(part for part in parts[1:] if part)
            elif len(parts) >= 2:
                label = parts[0]
                key = parts[1]
                note = " | ".join(part for part in parts[2:] if part)
        elif "=" in line:
            left, right = line.split("=", 1)
            label = left.strip()
            key, note = _split_value_note(right)
        else:
            key, note = _split_value_note(line)

        key = key.strip().strip('"').strip("'")
        label = label.strip().strip('"').strip("'")
        note = note.strip().strip('"').strip("'")
        if not key:
            continue
        if not label:
            label = _default_key_label(provider, len(entries) + 1)

        entries.append(
            {
                "ref": _key_ref(provider, key),
                "label": label,
                "note": note,
                "key": key,
                "source": "file",
            }
        )
    return entries


def api_key_entries(provider: str, settings: Dict[str, Any] | None = None) -> list[dict[str, str]]:
    path = _api_key_file_path(provider, settings)
    if not path or not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_api_key_entries(provider, text)


def resolve_api_key(provider: str, settings: Dict[str, Any] | None = None, key_ref: str = "") -> str:
    key_ref = str(key_ref or "").strip()
    entries = api_key_entries(provider, settings)

    if key_ref:
        for entry in entries:
            if key_ref in {entry.get("ref", ""), entry.get("label", "")}:
                return entry.get("key", "")

    env_name = _api_key_env_name(provider, settings)
    if env_name:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value

    if entries:
        return entries[0].get("key", "")
    return ""


def resolve_model(provider: str, tier: str = "audit", settings: Dict[str, Any] | None = None) -> str:
    payload = settings or load_settings()
    configured = str(get_path(payload, f"models.{provider}.{tier}", "") or "").strip()
    return configured or resolve_cached_model(provider)


def resolve_prompt(name: str, settings: Dict[str, Any] | None = None) -> str:
    payload = settings or load_settings()
    rel = str(get_path(payload, f"prompts.{name}", "") or "").strip()
    if not rel:
        return ""
    path = CONFIG_DIR / rel
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file for {name}: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _cmd_value(value: Any) -> str:
    text = str(value)
    return text.replace('"', '\\"')


def emit_cmd_env(settings: Dict[str, Any]) -> None:
    values = {
        "LLM_ACTIVE_PROVIDER": get_path(settings, "active_provider", "openai"),
        "OPENAI_MODEL_AUDIT": resolve_model("openai", "audit", settings),
        "OPENAI_TIER": get_path(settings, "providers.openai.service_tier", "default"),
        "OPENAI_MAX_RETRIES": get_path(settings, "audit.openai.max_retries", 3),
        "OPENAI_TIMEOUT_MEDIUM": get_path(settings, "audit.openai.timeout_medium_sec", 420),
        "OPENAI_TIMEOUT_HIGH": get_path(settings, "audit.openai.timeout_high_sec", 600),
        "OPENAI_MIN_CHUNKS": get_path(settings, "audit.openai.min_chunks", 4),
        "OPENAI_MAX_OUT": get_path(settings, "audit.openai.max_output_tokens", 12000),
        "OPENAI_REASONING_LOW": get_path(settings, "audit.openai.reasoning_low", "low"),
        "OPENAI_REASONING_MEDIUM": get_path(settings, "audit.openai.reasoning_medium", "medium"),
        "OPENAI_REASONING_HIGH": get_path(settings, "audit.openai.reasoning_high", "high"),
        "OPENAI_CHUNK_NORMAL": get_path(settings, "audit.openai.chunk_tokens", 12000),
        "OPENAI_OVERLAP_NORMAL": get_path(settings, "audit.openai.overlap_tokens", 1200),
        "GEMINI_MODEL_FAST": resolve_model("gemini", "audit_fast", settings),
        "GEMINI_MODEL_PRO": resolve_model("gemini", "audit_pro", settings),
        "GEMINI_MODEL_EXTRACT": resolve_model("gemini", "extraction", settings),
        "GEMINI_MAX_RETRIES": get_path(settings, "audit.gemini.max_retries", 4),
        "GEMINI_CHUNK_NORMAL": get_path(settings, "audit.gemini.chunk_tokens", 12000),
        "GEMINI_OVERLAP_NORMAL": get_path(settings, "audit.gemini.overlap_tokens", 1200),
        "XAI_MODEL_AUDIT": resolve_model("xai", "audit", settings),
        "XAI_MAX_RETRIES": get_path(settings, "audit.xai.max_retries", 3),
        "XAI_MAX_OUT": get_path(settings, "audit.xai.max_output_tokens", 12000),
        "XAI_TIMEOUT": get_path(settings, "audit.xai.timeout_sec", 600),
        "XAI_MIN_CHUNKS": get_path(settings, "audit.xai.min_chunks", 4),
        "XAI_CHUNK_NORMAL": get_path(settings, "audit.xai.chunk_tokens", 12000),
        "XAI_OVERLAP_NORMAL": get_path(settings, "audit.xai.overlap_tokens", 1200),
        "ANTHROPIC_MODEL_AUDIT": resolve_model("anthropic", "audit", settings),
        "ANTHROPIC_MAX_RETRIES": get_path(settings, "audit.anthropic.max_retries", 3),
        "ANTHROPIC_MAX_OUT": get_path(settings, "audit.anthropic.max_output_tokens", 12000),
        "ANTHROPIC_TIMEOUT": get_path(settings, "audit.anthropic.timeout_sec", 900),
        "ANTHROPIC_MIN_CHUNKS": get_path(settings, "audit.anthropic.min_chunks", 4),
        "ANTHROPIC_CHUNK_NORMAL": get_path(settings, "audit.anthropic.chunk_tokens", 12000),
        "ANTHROPIC_OVERLAP_NORMAL": get_path(settings, "audit.anthropic.overlap_tokens", 1200),
    }
    for key, value in values.items():
        print(f'set "{key}={_cmd_value(value)}"')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd-env", action="store_true", help="Print CMD set commands for launchers")
    parser.add_argument("--get", dest="get_key", default="", help="Print a dotted setting value")
    parser.add_argument("--api-key", choices=["openai", "gemini", "xai", "anthropic"], default="")
    parser.add_argument("--prompt", default="", help="Print prompt text by prompt key")
    args = parser.parse_args()

    settings = load_settings()
    if args.cmd_env:
        emit_cmd_env(settings)
        return 0
    if args.get_key:
        print(get_path(settings, args.get_key, ""))
        return 0
    if args.api_key:
        print(resolve_api_key(args.api_key, settings))
        return 0
    if args.prompt:
        print(resolve_prompt(args.prompt, settings))
        return 0
    print(SETTINGS_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
