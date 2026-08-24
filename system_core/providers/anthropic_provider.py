#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Anthropic Claude provider wrapper for JSON-object responses.

Built for the official anthropic SDK.

Claude-specific behaviour compared to the other providers:
- Every call streams. Audit chunks are long inputs with adaptive thinking on,
  so a non-streaming request risks an HTTP read timeout before the first token.
- The instruction block is sent as a cached system prefix. Audit runs replay the
  same rules for every chunk, so cache reads cut input cost after chunk one.
- Reasoning depth is the effort parameter, not a token budget.
- A refusal is a successful HTTP 200 with stop_reason="refusal", so it is
  checked before the response text is read.
- Server-side fallbacks are requested by default; the request is retried without
  them when the account has no access to that beta.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, Tuple

import anthropic
from anthropic import Anthropic


DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "medium"
MODEL_CHECK_MAX_TOKENS = 1024
SERVER_SIDE_FALLBACK_BETA = "server-side-fallback-2026-07-01"

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Project-wide reasoning vocabulary (none/minimal/low/medium/high) mapped onto
# Claude effort levels. Thinking itself stays adaptive: disabling it makes the
# model narrate reasoning into the visible answer, which corrupts JSON output.
REASONING_EFFORTS = {
    "none": "low",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}


# Capability negotiation happens per call, but an audit calls this module once per
# chunk: without a process-wide memo every chunk would re-send the same doomed
# request. Model id -> options the API already rejected in this process.
_UNSUPPORTED_FALLBACKS: set[str] = set()
_UNSUPPORTED_EFFORT: set[str] = set()


def normalize_effort(value: str | None) -> str:
    normalized = str(value or DEFAULT_EFFORT).strip().lower()
    if normalized in EFFORT_LEVELS:
        return normalized
    return REASONING_EFFORTS.get(normalized, DEFAULT_EFFORT)


def _print_retry(attempt: int, max_retries: int, sleep_sec: float, exc: Exception) -> None:
    try:
        msg = str(exc)
    except Exception:
        msg = ""
    msg = msg.replace("\n", " ")
    if len(msg) > 220:
        msg = msg[:220] + "…"
    print(f"  [NET] retry {attempt}/{max_retries} in {sleep_sec:.1f}s: {exc.__class__.__name__}: {msg}")


def extract_usage(message: Any) -> Dict[str, int]:
    """Return pipeline usage counters.

    Cache reads and cache writes are folded into input_tokens so totals stay
    comparable with the other providers. Thinking tokens are billed as output
    and are not reported separately by the API, so reasoning_tokens stays 0.
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    meta = getattr(message, "usage", None)
    if not meta:
        return usage

    def _count(name: str) -> int:
        try:
            return int(getattr(meta, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = _count("input_tokens") + _count("cache_read_input_tokens") + _count("cache_creation_input_tokens")
    output_tokens = _count("output_tokens")
    usage["input_tokens"] = input_tokens
    usage["output_tokens"] = output_tokens
    usage["total_tokens"] = input_tokens + output_tokens
    return usage


def _is_rate_limited(exc: Exception) -> bool:
    if isinstance(exc, anthropic.RateLimitError):
        return True
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in ("429", "rate limit", "too many requests", "overloaded"))


def _is_transport_error(exc: Exception) -> bool:
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.InternalServerError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return True
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    markers = (
        "connecterror", "readerror", "writeerror", "timeout", "network",
        "connection reset", "connection aborted", "server disconnected",
        "peer closed connection", "incomplete chunked read", "incomplete message body",
        "broken pipe", "eof", "ssl", "handshake", "overloaded",
    )
    return any(marker in msg for marker in markers) or any(marker in name for marker in markers)


def _mentions(exc: Exception, *markers: str) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in markers)


def _account_error(exc: Exception) -> RuntimeError | None:
    """Billing and key problems are not the document's fault: fail fast with a clear hint."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return RuntimeError(
            "Anthropic rejected the API key. Check config/api_key_anthropic.txt "
            "or the ANTHROPIC_API_KEY variable."
        )
    if _mentions(exc, "credit balance", "purchase credits", "plans & billing", "billing"):
        return RuntimeError(
            "The Anthropic organization behind this key has no spendable API credits. "
            "Check Console -> Plans & Billing (credits are per organization, and a workspace "
            "spend limit of zero blocks calls too). A Claude Pro/Max subscription does not cover API usage."
        )
    return None


def _normalize_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    if text and not text.lstrip().startswith("{"):
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right != -1 and right > left:
            text = text[left:right + 1]

    return text.strip()


def extract_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", "") != "text":
            continue
        text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "".join(parts)


def _refusal_error(message: Any) -> RuntimeError:
    details = getattr(message, "stop_details", None)
    category = str(getattr(details, "category", "") or "unspecified")
    explanation = str(getattr(details, "explanation", "") or "").strip()
    suffix = f" {explanation}" if explanation else ""
    return RuntimeError(f"Claude declined the request (category={category}).{suffix}".strip())


def build_client(api_key: str, *, timeout_sec: float | None = None) -> Anthropic:
    """Create a client that never retries internally; retries live in this module."""
    kwargs: Dict[str, Any] = {"api_key": api_key, "max_retries": 0}
    if timeout_sec and float(timeout_sec) > 0:
        kwargs["timeout"] = float(timeout_sec)
    return Anthropic(**kwargs)


def _stream_message(
    client: Anthropic,
    *,
    model: str,
    system_blocks: list[Dict[str, Any]],
    user_prompt: str,
    max_output_tokens: int,
    effort: str,
    use_effort: bool,
    use_server_side_fallback: bool,
) -> Any:
    request: Dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_output_tokens),
        "system": system_blocks,
        "messages": [{"role": "user", "content": user_prompt}],
        "thinking": {"type": "adaptive"},
    }
    if use_effort:
        request["output_config"] = {"effort": effort}

    if use_server_side_fallback:
        with client.beta.messages.stream(
            betas=[SERVER_SIDE_FALLBACK_BETA],
            fallbacks="default",
            **request,
        ) as stream:
            return stream.get_final_message()

    with client.messages.stream(**request) as stream:
        return stream.get_final_message()


def call_json_object(
    *,
    api_key: str,
    model: str,
    instructions: str,
    user_prompt: str,
    max_output_tokens: int,
    timeout_sec: float | None = None,
    max_retries: int,
    reasoning_effort: str = DEFAULT_EFFORT,
    use_prompt_cache: bool = True,
    use_server_side_fallback: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, int], str]:
    """Call the Claude Messages API and parse a JSON object response."""
    last_raw = ""
    retry_budget = max(0, int(max_retries))
    attempt = 1
    effort = normalize_effort(reasoning_effort)
    use_effort = model not in _UNSUPPORTED_EFFORT
    use_fallback = bool(use_server_side_fallback) and model not in _UNSUPPORTED_FALLBACKS

    client = build_client(api_key, timeout_sec=timeout_sec)
    system_text = (
        f"{instructions.strip()}\n\n"
        "Return only one valid JSON object. Do not wrap it in Markdown."
    ).strip()
    system_blocks: list[Dict[str, Any]] = [{"type": "text", "text": system_text}]
    if use_prompt_cache:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    while True:
        try:
            message = _stream_message(
                client,
                model=model,
                system_blocks=system_blocks,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
                effort=effort,
                use_effort=use_effort,
                use_server_side_fallback=use_fallback,
            )

            stop_reason = str(getattr(message, "stop_reason", "") or "")
            if stop_reason == "refusal":
                raise _refusal_error(message)
            if stop_reason == "max_tokens":
                raise RuntimeError(
                    f"Claude hit max_tokens={max_output_tokens} before finishing the JSON object."
                )

            last_raw = extract_text(message)
            normalized = _normalize_json_text(last_raw)
            if not normalized:
                raise ValueError("Empty model response text")

            obj = json.loads(normalized)
            if not isinstance(obj, dict):
                raise ValueError("Claude returned a non-object JSON payload.")

            served_model = str(getattr(message, "model", "") or model)
            tier = "default" if served_model == model else f"fallback:{served_model}"
            return obj, extract_usage(message), tier

        except anthropic.BadRequestError as exc:
            # Capability negotiation: retry the same attempt with the rejected
            # option removed instead of burning the retry budget.
            if use_fallback and _mentions(exc, "fallback", "beta"):
                use_fallback = False
                if model not in _UNSUPPORTED_FALLBACKS:
                    _UNSUPPORTED_FALLBACKS.add(model)
                    print(f"  [ANTHROPIC] {model} has no server-side fallbacks; continuing without them")
                continue
            if use_effort and _mentions(exc, "effort", "output_config"):
                use_effort = False
                if model not in _UNSUPPORTED_EFFORT:
                    _UNSUPPORTED_EFFORT.add(model)
                    print(f"  [ANTHROPIC] {model} rejects effort; continuing without it")
                continue
            account_error = _account_error(exc)
            if account_error is not None:
                raise account_error from exc
            raise RuntimeError(f"Claude rejected the request: {exc}") from exc

        except Exception as exc:
            account_error = _account_error(exc)
            if account_error is not None:
                raise account_error from exc

            if _is_rate_limited(exc) or _is_transport_error(exc):
                if attempt <= retry_budget:
                    if _is_rate_limited(exc):
                        sleep_sec = min(60.0, 10.0 * attempt) + random.uniform(1.0, 3.0)
                    else:
                        sleep_sec = min(120.0, 4.0 * (2.0 ** (attempt - 1))) + random.uniform(0.5, 2.0)

                    _print_retry(attempt, retry_budget, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    attempt += 1
                    continue

                if _is_rate_limited(exc):
                    raise RuntimeError("Claude rate limit exceeded and retries exhausted.") from exc

                raise RuntimeError(f"Claude transport/timeout failed ({exc.__class__.__name__}).") from exc

            if attempt <= retry_budget:
                sleep_sec = min(15.0, 3.0 * attempt) + random.uniform(0.2, 0.8)
                _print_retry(attempt, retry_budget, sleep_sec, exc)
                time.sleep(sleep_sec)
                attempt += 1
                continue

            raise RuntimeError(f"Claude call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc


def list_models(api_key: str, *, timeout_sec: float = 30.0) -> list[str]:
    client = build_client(api_key, timeout_sec=timeout_sec)
    models: list[str] = []
    for entry in client.models.list():
        model_id = str(getattr(entry, "id", "") or "").strip()
        if model_id:
            models.append(model_id)
    return sorted(dict.fromkeys(models))


def check_model(api_key: str, model: str, *, timeout_sec: float = 20.0) -> tuple[str, str]:
    client = build_client(api_key, timeout_sec=timeout_sec)
    request: Dict[str, Any] = {
        "model": model,
        "max_tokens": MODEL_CHECK_MAX_TOKENS,
        "messages": [{"role": "user", "content": "Reply with OK."}],
    }
    try:
        message = client.messages.create(**request)
    except anthropic.BadRequestError as exc:
        raise RuntimeError(f"Claude rejected the model check: {exc}") from exc

    if str(getattr(message, "stop_reason", "") or "") == "refusal":
        raise _refusal_error(message)
    if not extract_text(message).strip():
        raise RuntimeError("Claude returned an empty model-check response.")
    return "ok", "messages accepted the model."
