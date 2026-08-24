from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "system_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from providers.openai_provider import IncompleteResponseError, call_json_object


class FakeStream:
    """Replays a canned event sequence the way the SDK streams one."""

    def __init__(self, events, final=None) -> None:
        self._events = events
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_response(self):
        if self._final is None:
            # Mirrors the SDK: no `response.completed` event means no final response.
            raise RuntimeError("Didn't receive a `response.completed` event.")
        return self._final


class FakeResponses:
    def __init__(self, streams) -> None:
        self.streams = list(streams)
        self.calls = 0

    def stream(self, **kwargs):
        self.calls += 1
        return self.streams.pop(0)


class FakeClient:
    def __init__(self, streams) -> None:
        self.responses = FakeResponses(streams)


def incomplete_event(reason: str = "max_output_tokens"):
    response = types.SimpleNamespace(
        status="incomplete",
        incomplete_details=types.SimpleNamespace(reason=reason),
    )
    return types.SimpleNamespace(type="response.incomplete", response=response)


def completed_response(text: str):
    content = [types.SimpleNamespace(type="output_text", text=text)]
    message = types.SimpleNamespace(type="message", content=content)
    return types.SimpleNamespace(
        output=[message],
        output_text=text,
        service_tier="default",
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
    )


class OpenAIProviderTests(unittest.TestCase):
    def _call(self, client, **overrides):
        kwargs = dict(
            model="gpt-5.6-luna",
            instructions="rules",
            user_prompt="chunk",
            reasoning_effort="high",
            max_output_tokens=12000,
            timeout_sec=60.0,
            max_retries=6,
            service_tier="default",
            use_idempotency=False,
            doc_hash="hash",
            chunk_index=1,
        )
        kwargs.update(overrides)
        return call_json_object(client, **kwargs)

    def test_output_budget_wall_is_named_and_never_retried(self) -> None:
        client = FakeClient([FakeStream([incomplete_event()])])

        with self.assertRaises(IncompleteResponseError) as caught:
            self._call(client)

        self.assertIn("max_output_tokens=12000", str(caught.exception))
        # Retrying would stop at the same place and bill again.
        self.assertEqual(client.responses.calls, 1)

    def test_other_incomplete_reasons_are_reported_too(self) -> None:
        client = FakeClient([FakeStream([incomplete_event("content_filter")])])

        with self.assertRaisesRegex(IncompleteResponseError, "content_filter"):
            self._call(client)

    def test_a_real_disconnect_is_still_retried(self) -> None:
        # No incomplete event, no final response: that is a genuine transport failure.
        broken = FakeStream([types.SimpleNamespace(type="response.in_progress", response=None)])
        good = FakeStream(
            [types.SimpleNamespace(type="response.completed", response=None)],
            final=completed_response('{"rows": []}'),
        )
        client = FakeClient([broken, good])

        obj, usage, tier = self._call(client, max_retries=1)

        self.assertEqual(obj, {"rows": []})
        self.assertEqual(client.responses.calls, 2)
        self.assertEqual(tier, "default")
        self.assertEqual(usage["input_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
