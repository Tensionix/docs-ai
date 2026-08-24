from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.providers import xai_provider as xai


class FakeResponse:
    def __init__(self, payload=None, *, status_code: int = 200, headers=None, lines=None, text: str = "") -> None:
        self._payload = payload or {}
        self.status_code = status_code
        self.headers = headers or {}
        self._lines = lines or []
        self.text = text
        self.content = text.encode("utf-8") if text else json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode: bool = False):
        yield from self._lines


class XAIProviderTests(unittest.TestCase):
    def test_reasoning_is_normalized_and_sent_in_payload(self) -> None:
        payload = xai._chat_payload(
            model="grok-4.3",
            system_prompt="system",
            user_prompt="user",
            max_tokens=32,
            reasoning_effort="selected",
            response_format=True,
        )
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(xai.normalize_reasoning_effort("disabled"), "none")
        self.assertEqual(xai.normalize_reasoning_effort("unknown"), "high")

    def test_utf8_json_decode_ignores_wrong_charset_and_repairs_mojibake(self) -> None:
        response = FakeResponse({"text": "Привет"}, headers={"Content-Type": "application/json; charset=latin-1"})
        self.assertEqual(xai._response_json_utf8(response), {"text": "Привет"})

        damaged = "Привет".encode("utf-8").decode("latin-1")
        fixed, count = xai.repair_json_text({"text": damaged})
        self.assertEqual(fixed, {"text": "Привет"})
        self.assertEqual(count, 1)
        with self.assertRaises(ValueError):
            xai.assert_clean_json_text({"text": "�"})

    def test_streaming_sse_is_collected_as_chat_payload(self) -> None:
        old_post = xai.requests.post
        try:
            lines = [
                'data: {"choices":[{"delta":{"content":"{\\"ok\\":"}}]}',
                'data: {"choices":[{"delta":{"content":" true}"}}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
                "data: [DONE]",
            ]

            def fake_post(*args, **kwargs):
                self.assertTrue(kwargs.get("stream"))
                self.assertEqual(kwargs.get("headers", {}).get("Accept"), "text/event-stream")
                return FakeResponse(lines=lines)

            xai.requests.post = fake_post
            payload = xai._chat_completion_stream(
                api_key="xai-test",
                payload={"stream": True},
                timeout_sec=600,
                idempotency_key="",
            )

            self.assertEqual(xai.extract_text(payload), '{"ok": true}')
            self.assertEqual(xai.extract_usage(payload)["total_tokens"], 5)
        finally:
            xai.requests.post = old_post

    def test_transport_failure_retries_with_deferred_polling(self) -> None:
        old_post = xai.requests.post
        old_get = xai.requests.get
        old_sleep = xai.time.sleep
        calls: list[dict] = []
        polls = {"count": 0}
        try:
            xai.time.sleep = lambda _seconds: None

            def fake_post(_url, *, json=None, **kwargs):
                calls.append(dict(json or {}))
                if json and json.get("stream"):
                    raise requests.ConnectionError("server disconnected")
                self.assertTrue(json and json.get("deferred"))
                return FakeResponse({"request_id": "req_123"})

            def fake_get(_url, **kwargs):
                polls["count"] += 1
                if polls["count"] == 1:
                    return FakeResponse(status_code=202)
                return FakeResponse(
                    {
                        "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
                        "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
                    }
                )

            xai.requests.post = fake_post
            xai.requests.get = fake_get
            obj, usage, tier = xai.call_json_object(
                api_key="xai-test",
                model="grok-4.3",
                instructions="Return JSON.",
                user_prompt="{}",
                max_output_tokens=64,
                timeout_sec=600,
                max_retries=1,
                use_idempotency=True,
                doc_hash="doc",
                chunk_index=1,
            )

            self.assertEqual(obj, {"ok": True})
            self.assertEqual(usage["total_tokens"], 7)
            self.assertEqual(tier, "default")
            self.assertTrue(calls[0].get("stream"))
            self.assertTrue(calls[1].get("deferred"))
            self.assertEqual(polls["count"], 2)
        finally:
            xai.requests.post = old_post
            xai.requests.get = old_get
            xai.time.sleep = old_sleep

    def test_retry_after_header_is_respected(self) -> None:
        response = FakeResponse(status_code=429, headers={"Retry-After": "12"}, text="limited")
        self.assertEqual(xai._response_retry_after_sec(response), 12.0)
        with self.assertRaises(xai.XAIHTTPError) as raised:
            xai._raise_for_status(response, "xai-test", "xAI test")
        self.assertEqual(raised.exception.retry_after_sec, 12.0)
        self.assertTrue(xai._is_retryable(raised.exception))


if __name__ == "__main__":
    unittest.main()
