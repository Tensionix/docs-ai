#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini provider wrapper for JSON-object responses.

Built for google-genai SDK.
Handles transport disconnects, rate limits, and enforces JSON output.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, Optional, Tuple

from google import genai
from google.genai import types
from google.genai.errors import APIError


THINKING_LEVELS = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}


def normalize_thinking_level(value: str | None) -> str:
    normalized = str(value or "medium").strip().lower()
    return normalized if normalized in THINKING_LEVELS else "medium"


def supports_thinking_level(model: str) -> bool:
    return bool(re.match(r"^gemini-3(?:\.|-|$)", str(model or "").strip().lower()))

def _print_retry(attempt: int, max_retries: int, sleep_sec: float, exc: Exception) -> None:
    try:
        msg = str(exc)
    except Exception:
        msg = ""
    msg = msg.replace("\n", " ")
    if len(msg) > 220:
        msg = msg[:220] + "…"
    print(f"  [NET] retry {attempt}/{max_retries} in {sleep_sec:.1f}s: {exc.__class__.__name__}: {msg}")

def extract_usage(resp: Any) -> Dict[str, int]:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    meta = getattr(resp, "usage_metadata", None)
    if not meta:
        return usage
    
    usage["input_tokens"] = getattr(meta, "prompt_token_count", 0) or 0
    usage["output_tokens"] = getattr(meta, "candidates_token_count", 0) or 0
    usage["total_tokens"] = getattr(meta, "total_token_count", 0) or 0
    return usage

def _is_transport_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()

    if "apierror" in name and ("503" in msg or "502" in msg or "504" in msg):
        return True
    
    # Catch httpx transport issues often wrapped in Google SDK errors
    markers = (
        "connecterror", "readerror", "writeerror", "timeout", "network",
        "connection reset", "connection aborted", "server disconnected",
        "peer closed connection", "incomplete chunked read", "incomplete message body",
        "broken pipe", "eof", "ssl", "handshake"
    )
    return any(m in msg for m in markers) or any(m in name for m in markers)

def _is_rate_limited(msg: str) -> bool:
    markers = ("429", "quota", "rate limit", "too many requests")
    return any(m in msg for m in markers)

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

def call_structured(
    client: genai.Client,
    *,
    model: str,
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.0,
    thinking_level: str = "medium",
    max_retries: int = 3,
    sleep_after_sec: float = 0.0
) -> Tuple[Dict[str, Any], Dict[str, int], str]:
    
    last_raw = ""
    retry_budget = max(0, int(max_retries))
    max_attempts = retry_budget + 1
    config_kwargs: Dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
        "response_mime_type": "application/json",
    }
    if supports_thinking_level(model):
        level = normalize_thinking_level(thinking_level)
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING_LEVELS[level])
    config = types.GenerateContentConfig(
        **config_kwargs
    )

    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config
            )
            
            last_raw = getattr(resp, "text", "")
            normalized = _normalize_json_text(last_raw)
            if not normalized:
                raise ValueError("Empty model response text")

            obj = json.loads(normalized)
            
            if sleep_after_sec > 0:
                time.sleep(sleep_after_sec)
                
            return obj, extract_usage(resp), "default"

        except Exception as exc:
            msg = str(exc).lower()

            if _is_rate_limited(msg) or _is_transport_error(exc):
                if attempt <= retry_budget:
                    if _is_rate_limited(msg):
                        sleep_sec = min(60.0, 10.0 * attempt) + random.uniform(1.0, 3.0)
                    else:
                        sleep_sec = min(120.0, 4.0 * (2.0 ** (attempt - 1))) + random.uniform(0.5, 2.0)
                    
                    _print_retry(attempt, retry_budget, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    continue

                if _is_rate_limited(msg):
                    raise RuntimeError("Gemini rate limit exceeded and retries exhausted.") from exc

                raise RuntimeError(f"Gemini transport/timeout failed ({exc.__class__.__name__}).") from exc

            # Unknown API errors
            if attempt <= retry_budget:
                sleep_sec = min(15.0, 3.0 * attempt) + random.uniform(0.2, 0.8)
                _print_retry(attempt, retry_budget, sleep_sec, exc)
                time.sleep(sleep_sec)
                continue

            raise RuntimeError(f"Gemini call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc

    raise RuntimeError("Unreachable")
