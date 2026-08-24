#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xAI provider wrapper for JSON-object chat completions.

Mobile-network hardened variant:
- Prefer SSE streaming to keep long Grok generations active.
- Fall back to deferred completions after transport failures.
- Respect Retry-After when xAI sends it, and retry transient 5xx/429 errors.
- Keep response_format as an optimization, but fall back to prompt-only JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import random
import re
import time
from typing import Any, Dict, Tuple

import requests


CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
DEFERRED_COMPLETION_URL = "https://api.x.ai/v1/chat/deferred-completion/{request_id}"
MODEL_URLS = (
    "https://api.x.ai/v1/language-models",
    "https://api.x.ai/v1/models",
)
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
CONNECT_TIMEOUT_SEC = 30.0
DEFAULT_READ_TIMEOUT_SEC = 600.0
DEFERRED_POLL_START_SEC = 5.0
DEFERRED_POLL_MAX_SEC = 60.0
_STREAM_DISABLED_MODELS: set[str] = set()
_MOJIBAKE_PAIR_RE = re.compile(r"(?:Ð[\x80-\xBF]|Ñ[\x80-\xBF]|â[\x80-\xBF])")
REASONING_EFFORTS = {"none", "low", "medium", "high"}


class XAIHTTPError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, retry_after_sec: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_sec = retry_after_sec


def _response_text_utf8(response: requests.Response, *, errors: str = "strict") -> str:
    """Decode xAI HTTP bodies independently of an absent/incorrect charset header."""
    content = getattr(response, "content", b"")
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, (bytes, bytearray)):
        content = bytes(content or b"")
    return bytes(content).decode("utf-8-sig", errors=errors)


def _response_json_utf8(response: requests.Response) -> dict[str, Any]:
    data = json.loads(_response_text_utf8(response))
    if not isinstance(data, dict):
        raise RuntimeError("xAI returned a non-object JSON payload.")
    return data


def _mojibake_score(text: str) -> int:
    replacements = text.count("�")
    controls = sum(1 for char in text if "\x80" <= char <= "\x9f")
    pairs = len(_MOJIBAKE_PAIR_RE.findall(text))
    return replacements * 100 + controls * 20 + pairs * 10


def _repair_mojibake_string(text: str) -> tuple[str, bool]:
    before = _mojibake_score(text)
    if before == 0:
        return text, False
    try:
        candidate = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text, False
    if _mojibake_score(candidate) < before:
        return candidate, True
    return text, False


def repair_json_text(payload: Any) -> tuple[Any, int]:
    """Repair only unambiguous UTF-8-as-Latin-1 mojibake in a JSON-like tree."""
    if isinstance(payload, str):
        fixed, changed = _repair_mojibake_string(payload)
        return fixed, int(changed)
    if isinstance(payload, list):
        result = []
        changed = 0
        for item in payload:
            fixed, count = repair_json_text(item)
            result.append(fixed)
            changed += count
        return result, changed
    if isinstance(payload, dict):
        result = {}
        changed = 0
        for key, value in payload.items():
            fixed, count = repair_json_text(value)
            result[key] = fixed
            changed += count
        return result, changed
    return payload, 0


def assert_clean_json_text(payload: Any) -> None:
    """Refuse to publish payloads that still contain clear encoding damage."""
    if isinstance(payload, str):
        if _mojibake_score(payload):
            raise ValueError(f"xAI response contains damaged UTF-8 text: {payload[:120]!r}")
        return
    if isinstance(payload, list):
        for item in payload:
            assert_clean_json_text(item)
        return
    if isinstance(payload, dict):
        for value in payload.values():
            assert_clean_json_text(value)


def normalize_reasoning_effort(value: str | None) -> str:
    effort = str(value or "").strip().lower()
    aliases = {"selected": "high", "off": "none", "disabled": "none", "default": "high"}
    effort = aliases.get(effort, effort)
    return effort if effort in REASONING_EFFORTS else "high"


def _print_retry(attempt: int, max_retries: int, sleep_sec: float, exc: Exception) -> None:
    try:
        msg = str(exc)
    except Exception:
        msg = ""
    msg = msg.replace("\n", " ")
    if len(msg) > 220:
        msg = msg[:220] + "..."
    print(f"  [NET] retry {attempt}/{max_retries} in {sleep_sec:.1f}s: {exc.__class__.__name__}: {msg}")


def _get_int(payload: Any, key: str, default: int = 0) -> int:
    if isinstance(payload, dict):
        try:
            return int(payload.get(key, default) or 0)
        except (TypeError, ValueError):
            return default
    try:
        return int(getattr(payload, key, default) or 0)
    except (TypeError, ValueError):
        return default


def extract_usage(payload: Any) -> Dict[str, int]:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    raw = payload.get("usage") if isinstance(payload, dict) else getattr(payload, "usage", None)
    if not raw:
        return usage

    usage["input_tokens"] = _get_int(raw, "input_tokens") or _get_int(raw, "prompt_tokens")
    usage["output_tokens"] = _get_int(raw, "output_tokens") or _get_int(raw, "completion_tokens")
    usage["total_tokens"] = _get_int(raw, "total_tokens")

    details = None
    if isinstance(raw, dict):
        details = raw.get("completion_tokens_details") or raw.get("output_tokens_details")
    else:
        details = getattr(raw, "completion_tokens_details", None) or getattr(raw, "output_tokens_details", None)
    usage["reasoning_tokens"] = _get_int(details, "reasoning_tokens") if details else _get_int(raw, "reasoning_tokens")
    return usage


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


def _collect_text(node: Any, texts: list[str]) -> None:
    if isinstance(node, str):
        if node.strip():
            texts.append(node)
        return
    if isinstance(node, list):
        for item in node:
            _collect_text(item, texts)
        return
    if not isinstance(node, dict):
        return

    text_value = node.get("text")
    if isinstance(text_value, dict):
        _collect_text(text_value.get("value") or text_value.get("text"), texts)
    elif isinstance(text_value, str):
        _collect_text(text_value, texts)
    _collect_text(node.get("output_text"), texts)
    _collect_text(node.get("content"), texts)
    message = node.get("message")
    if isinstance(message, dict):
        _collect_text(message.get("content"), texts)


def extract_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                _collect_text(choice.get("message"), texts)
                _collect_text(choice.get("text"), texts)
    _collect_text(payload.get("output"), texts)
    return "\n".join(text for text in texts if text.strip()).strip()


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "[redacted]") if api_key else text


def _timeout_tuple(timeout_sec: float | None) -> tuple[float, float]:
    read_timeout = float(timeout_sec or DEFAULT_READ_TIMEOUT_SEC)
    if read_timeout < 60.0:
        read_timeout = 60.0
    return CONNECT_TIMEOUT_SEC, read_timeout


def _headers(api_key: str, *, idempotency_key: str = "", accept_sse: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if accept_sse else "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:200]
    return headers


def _response_retry_after_sec(response: requests.Response) -> float | None:
    raw = str(response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())


def _raise_for_status(response: requests.Response, api_key: str, label: str) -> None:
    if response.status_code < 400:
        return
    detail = _redact(_response_text_utf8(response, errors="replace")[:1000], api_key)
    retry_after = _response_retry_after_sec(response)
    suffix = f" retry_after={retry_after:.1f}s" if retry_after is not None else ""
    raise XAIHTTPError(
        f"{label} failed with HTTP {response.status_code}:{suffix} {detail}",
        status_code=response.status_code,
        retry_after_sec=retry_after,
    )


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"http\s+([0-9]{3})", str(exc), flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b([0-9]{3})\b", str(exc))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _is_rate_limited(msg: str) -> bool:
    markers = ("429", "rate limit", "too many requests", "quota")
    return any(marker in msg for marker in markers)


def _is_retryable(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    status = _status_code(exc)
    if status in RETRYABLE_STATUS_CODES:
        return True
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return True
    markers = (
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "peer closed connection",
        "incomplete chunked read",
        "incomplete message body",
        "remote end closed connection",
        "unexpected eof",
        "broken pipe",
        "econnreset",
        "econnaborted",
        "name resolution",
        "temporary failure",
        "connection pool",
        "max retries exceeded",
        "tls",
        "ssl",
        "handshake",
        "502",
        "503",
        "504",
    )
    return any(marker in msg or marker in name for marker in markers)


def _extract_retry_after_sec(msg: str) -> float | None:
    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"retry[_ -]?after[=:]\s*([0-9]+(?:\.[0-9]+)?)s?", msg, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _retry_after_from_exception(exc: Exception) -> float | None:
    retry_after = getattr(exc, "retry_after_sec", None)
    if isinstance(retry_after, (int, float)):
        return max(0.0, float(retry_after))
    return _extract_retry_after_sec(str(exc))


def _chat_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    reasoning_effort: str,
    response_format: bool,
    stream: bool = False,
    deferred: bool = False,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "reasoning_effort": normalize_reasoning_effort(reasoning_effort),
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if response_format:
        payload["response_format"] = {"type": "json_object"}
    if stream:
        payload["stream"] = True
    if deferred:
        payload["deferred"] = True
    return payload


def _message_from_text(text: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]}


def _merge_usage(target: dict[str, Any], payload: Any) -> None:
    if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
        target.clear()
        target.update(payload["usage"])


def _collect_stream_delta(chunk: Any, text_parts: list[str], usage: dict[str, Any]) -> None:
    _merge_usage(usage, chunk)
    if not isinstance(chunk, dict):
        return
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                nested: list[str] = []
                _collect_text(content, nested)
                if nested:
                    text_parts.append("".join(nested))
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            nested = []
            _collect_text(message.get("content"), nested)
            if nested:
                text_parts.append("".join(nested))


def _chat_completion_stream(
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_sec: float | None,
    idempotency_key: str,
) -> dict[str, Any]:
    response = requests.post(
        CHAT_COMPLETIONS_URL,
        headers=_headers(api_key, idempotency_key=idempotency_key, accept_sse=True),
        json=payload,
        timeout=_timeout_tuple(timeout_sec),
        stream=True,
    )
    _raise_for_status(response, api_key, "xAI streaming chat completion")

    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    saw_data = False
    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8-sig", errors="strict").strip()
        else:
            line = str(raw_line).strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        saw_data = True
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"xAI stream returned invalid JSON event: {data[:200]}") from exc
        _collect_stream_delta(chunk, text_parts, usage)

    if not saw_data:
        raise RuntimeError("xAI stream ended without any SSE data events.")
    payload_out = _message_from_text("".join(text_parts))
    if usage:
        payload_out["usage"] = usage
    return payload_out


def _chat_completion_create(
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_sec: float | None,
    idempotency_key: str,
) -> dict[str, Any]:
    response = requests.post(
        CHAT_COMPLETIONS_URL,
        headers=_headers(api_key, idempotency_key=idempotency_key),
        json=payload,
        timeout=_timeout_tuple(timeout_sec),
    )
    _raise_for_status(response, api_key, "xAI chat completion")
    return _response_json_utf8(response)


def _poll_deferred_completion(
    *,
    api_key: str,
    request_id: str,
    timeout_sec: float | None,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(float(timeout_sec or DEFAULT_READ_TIMEOUT_SEC), 60.0)
    poll_sleep = DEFERRED_POLL_START_SEC
    url = DEFERRED_COMPLETION_URL.format(request_id=request_id)
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(url, headers=_headers(api_key), timeout=_timeout_tuple(min(120.0, timeout_sec or 120.0)))
            if response.status_code == 202:
                time.sleep(poll_sleep + random.uniform(0.2, 1.0))
                poll_sleep = min(DEFERRED_POLL_MAX_SEC, poll_sleep * 1.7)
                continue
            _raise_for_status(response, api_key, "xAI deferred chat completion")
            return _response_json_utf8(response)
        except Exception as exc:
            last_error = exc
            if not _is_retryable(exc):
                raise
            retry_after = _retry_after_from_exception(exc)
            sleep_sec = retry_after if retry_after is not None else poll_sleep + random.uniform(0.2, 1.0)
            time.sleep(min(DEFERRED_POLL_MAX_SEC, sleep_sec))
            poll_sleep = min(DEFERRED_POLL_MAX_SEC, poll_sleep * 1.7)

    if last_error:
        raise RuntimeError(f"xAI deferred completion polling timed out after retries: {last_error}") from last_error
    raise RuntimeError("xAI deferred completion polling timed out before the result was ready.")


def _chat_completion_deferred(
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_sec: float | None,
    idempotency_key: str,
) -> dict[str, Any]:
    response = requests.post(
        CHAT_COMPLETIONS_URL,
        headers=_headers(api_key, idempotency_key=idempotency_key),
        json=payload,
        timeout=_timeout_tuple(min(120.0, timeout_sec or 120.0)),
    )
    _raise_for_status(response, api_key, "xAI deferred chat completion create")
    data = _response_json_utf8(response)
    request_id = str(data.get("request_id") or data.get("response_id") or "").strip()
    if not request_id:
        raise RuntimeError(f"xAI deferred completion create did not return request_id: {str(data)[:300]}")
    print(f"  [XAI] deferred completion request_id={request_id[:8]}...; polling until ready")
    return _poll_deferred_completion(api_key=api_key, request_id=request_id, timeout_sec=timeout_sec)


def _chat_completion(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    reasoning_effort: str,
    timeout_sec: float | None,
    response_format: bool,
    idempotency_key: str,
    stream: bool,
    deferred: bool,
) -> dict[str, Any]:
    payload = _chat_payload(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        stream=stream,
        deferred=deferred,
    )
    if deferred:
        return _chat_completion_deferred(
            api_key=api_key,
            payload=payload,
            timeout_sec=timeout_sec,
            idempotency_key=idempotency_key,
        )
    if stream:
        return _chat_completion_stream(
            api_key=api_key,
            payload=payload,
            timeout_sec=timeout_sec,
            idempotency_key=idempotency_key,
        )
    return _chat_completion_create(
        api_key=api_key,
        payload=payload,
        timeout_sec=timeout_sec,
        idempotency_key=idempotency_key,
    )


def call_json_object(
    *,
    api_key: str,
    model: str,
    instructions: str,
    user_prompt: str,
    max_output_tokens: int,
    timeout_sec: float | None = None,
    max_retries: int,
    use_idempotency: bool,
    doc_hash: str,
    chunk_index: int,
    reasoning_effort: str = "high",
) -> Tuple[Dict[str, Any], Dict[str, int], str]:
    """Call xAI chat completions and parse a JSON object response."""
    last_raw = ""
    retry_budget = max(0, int(max_retries))
    retries_left = retry_budget
    attempt = 1
    use_response_format = True
    use_stream = model not in _STREAM_DISABLED_MODELS
    prefer_deferred = False
    reasoning_effort = normalize_reasoning_effort(reasoning_effort)

    system_prompt = (
        f"{instructions.strip()}\n\n"
        "Return only one valid JSON object. Do not wrap it in Markdown."
    ).strip()

    while True:
        try:
            idempotency_key = ""
            if use_idempotency:
                idempotency_key = f"audion-xai|{doc_hash}|{chunk_index}|{model}|{reasoning_effort}"
            payload = _chat_completion(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                timeout_sec=timeout_sec,
                response_format=use_response_format,
                idempotency_key=idempotency_key,
                stream=use_stream and not prefer_deferred,
                deferred=prefer_deferred,
            )
            last_raw = extract_text(payload)
            normalized = _normalize_json_text(last_raw)
            if not normalized:
                raise ValueError("Empty model response text")
            obj = json.loads(normalized)
            obj, repaired = repair_json_text(obj)
            if repaired:
                print(f"  [XAI] repaired UTF-8 mojibake in {repaired} response field(s)")
            assert_clean_json_text(obj)
            return obj, extract_usage(payload), "default"

        except Exception as exc:
            msg = str(exc).lower()
            if use_response_format and "response_format" in msg:
                use_response_format = False
                print("  [XAI] response_format rejected; retrying with prompt-only JSON mode")
                attempt += 1
                continue
            if use_stream and not prefer_deferred and "stream" in msg and not _is_retryable(exc):
                use_stream = False
                _STREAM_DISABLED_MODELS.add(model)
                reason = str(exc).replace("\n", " ")[:180]
                print(f"  [XAI] streaming unavailable for {model}; using regular chat completion: {reason}")
                attempt += 1
                continue
            if prefer_deferred and "deferred" in msg and not _is_retryable(exc):
                prefer_deferred = False
                use_stream = False
                print("  [XAI] deferred completion rejected; retrying with regular chat completion")
                attempt += 1
                continue

            if _is_rate_limited(msg) or _is_retryable(exc):
                if retries_left > 0:
                    retry_after = _retry_after_from_exception(exc)
                    if retry_after is not None:
                        sleep_sec = retry_after + random.uniform(0.2, 1.0)
                    elif _is_rate_limited(msg):
                        sleep_sec = min(60.0, 8.0 * attempt) + random.uniform(0.5, 2.0)
                    else:
                        sleep_sec = min(120.0, 4.0 * (2.0 ** (attempt - 1))) + random.uniform(0.5, 2.0)
                    _print_retry(attempt, retry_budget, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    retries_left -= 1
                    attempt += 1
                    if not _is_rate_limited(msg):
                        prefer_deferred = True
                    continue
                if _is_rate_limited(msg):
                    raise RuntimeError(
                        "xAI rate limit exceeded and retries exhausted. "
                        "Try again with --resume after cooldown, or reduce chunk size."
                    ) from exc
                raise RuntimeError(
                    f"xAI transport/timeout failed ({exc.__class__.__name__}) and retries are exhausted. "
                    "Try again with --resume to keep completed chunk cache."
                ) from exc

            if retries_left > 0:
                sleep_sec = min(15.0, 3.0 * attempt) + random.uniform(0.2, 0.8)
                _print_retry(attempt, retry_budget, sleep_sec, exc)
                time.sleep(sleep_sec)
                retries_left -= 1
                attempt += 1
                continue
            raise RuntimeError(f"xAI call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data") or payload.get("models") or payload.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    if not isinstance(raw_items, list):
        return []

    models: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            models.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        for key in ("id", "name", "model"):
            value = str(item.get(key) or "").strip()
            if value:
                models.append(value)
                break
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            models.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return sorted(dict.fromkeys(model for model in models if model))


def list_models(api_key: str, *, timeout_sec: float = 30.0) -> list[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    models: list[str] = []
    last_error: Exception | None = None
    for url in MODEL_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=_timeout_tuple(timeout_sec))
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                _raise_for_status(response, api_key, "xAI model list")
            models.extend(_extract_model_ids(_response_json_utf8(response)))
        except Exception as exc:
            last_error = exc
    models = sorted(dict.fromkeys(model for model in models if model))
    if models:
        return models
    if last_error:
        raise last_error
    return []


def check_model(api_key: str, model: str, *, timeout_sec: float = 20.0) -> tuple[str, str]:
    payload = _chat_completion(
        api_key=api_key,
        model=model,
        system_prompt="",
        user_prompt="Reply with OK.",
        max_tokens=8,
        # Some xAI reasoning models do not support disabling reasoning.
        # A low-effort probe is broadly compatible and keeps model checks cheap.
        reasoning_effort="low",
        timeout_sec=timeout_sec,
        response_format=False,
        idempotency_key="",
        stream=False,
        deferred=False,
    )
    text = extract_text(payload)
    if not text.strip():
        raise RuntimeError("xAI returned an empty model-check response.")
    return "ok", "chat/completions accepted the model."
