from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.providers import anthropic_provider as claude


class FakeUsage:
    def __init__(self, *, input_tokens=0, output_tokens=0, cache_read=0, cache_creation=0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_creation


class FakeMessage:
    def __init__(self, *, text="", stop_reason="end_turn", usage=None, model="claude-opus-5", stop_details=None) -> None:
        self.content = [types.SimpleNamespace(type="text", text=text)] if text else []
        self.stop_reason = stop_reason
        self.usage = usage or FakeUsage()
        self.model = model
        self.stop_details = stop_details


class FakeStream:
    def __init__(self, message) -> None:
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._message


class FakeMessages:
    """Records the request and replays a queued message or exception."""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeStream(outcome)


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.messages = FakeMessages(outcomes)
        self.beta = types.SimpleNamespace(messages=self.messages)


class AnthropicProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        claude._UNSUPPORTED_FALLBACKS.clear()
        claude._UNSUPPORTED_EFFORT.clear()

    def _patch_client(self, outcomes) -> FakeClient:
        client = FakeClient(outcomes)
        original = claude.build_client
        claude.build_client = lambda api_key, *, timeout_sec=None: client  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(claude, "build_client", original))
        return client

    def test_project_reasoning_levels_map_onto_claude_effort(self) -> None:
        self.assertEqual(claude.normalize_effort("minimal"), "low")
        self.assertEqual(claude.normalize_effort("none"), "low")
        self.assertEqual(claude.normalize_effort("medium"), "medium")
        self.assertEqual(claude.normalize_effort("xhigh"), "xhigh")
        self.assertEqual(claude.normalize_effort("high"), "high")
        self.assertEqual(claude.normalize_effort("selected"), "medium")
        self.assertEqual(claude.normalize_effort(""), "medium")

    def test_request_streams_with_cached_system_prefix_and_effort(self) -> None:
        client = self._patch_client([FakeMessage(text='{"rows": [{"issue_id": "E001"}]}')])

        obj, usage, tier = claude.call_json_object(
            api_key="sk-ant-test",
            model="claude-opus-5",
            instructions="Правила аудита",
            user_prompt="chunk",
            max_output_tokens=12000,
            timeout_sec=900.0,
            max_retries=2,
            reasoning_effort="medium",
        )

        request = client.messages.requests[0]
        self.assertEqual(obj["rows"][0]["issue_id"], "E001")
        self.assertEqual(tier, "default")
        self.assertEqual(usage["input_tokens"], 0)
        self.assertEqual(request["thinking"], {"type": "adaptive"})
        self.assertEqual(request["output_config"], {"effort": "medium"})
        self.assertEqual(request["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("Правила аудита", request["system"][0]["text"])
        self.assertEqual(request["betas"], [claude.SERVER_SIDE_FALLBACK_BETA])
        self.assertEqual(request["fallbacks"], "default")

    def test_usage_folds_cache_tokens_into_input(self) -> None:
        message = FakeMessage(
            text='{"rows": []}',
            usage=FakeUsage(input_tokens=1000, output_tokens=250, cache_read=8000, cache_creation=200),
        )
        usage = claude.extract_usage(message)
        self.assertEqual(usage["input_tokens"], 9200)
        self.assertEqual(usage["output_tokens"], 250)
        self.assertEqual(usage["total_tokens"], 9450)

    def test_markdown_fenced_json_is_recovered(self) -> None:
        self._patch_client([FakeMessage(text='```json\n{"rows": []}\n```')])
        obj, _usage, _tier = claude.call_json_object(
            api_key="sk-ant-test",
            model="claude-opus-5",
            instructions="rules",
            user_prompt="chunk",
            max_output_tokens=4000,
            max_retries=0,
        )
        self.assertEqual(obj, {"rows": []})

    def test_refusal_is_reported_instead_of_empty_content(self) -> None:
        details = types.SimpleNamespace(category="cyber", explanation="declined")
        self._patch_client([FakeMessage(stop_reason="refusal", stop_details=details)])

        with self.assertRaisesRegex(RuntimeError, "declined the request"):
            claude.call_json_object(
                api_key="sk-ant-test",
                model="claude-opus-5",
                instructions="rules",
                user_prompt="chunk",
                max_output_tokens=4000,
                max_retries=0,
            )

    def test_truncated_output_is_reported_instead_of_broken_json(self) -> None:
        self._patch_client([FakeMessage(text='{"rows": [', stop_reason="max_tokens")])

        with self.assertRaisesRegex(RuntimeError, "max_tokens"):
            claude.call_json_object(
                api_key="sk-ant-test",
                model="claude-opus-5",
                instructions="rules",
                user_prompt="chunk",
                max_output_tokens=4000,
                max_retries=0,
            )

    def test_unsupported_beta_and_effort_are_dropped_without_spending_retries(self) -> None:
        import anthropic

        def _bad_request(message: str) -> Exception:
            return anthropic.BadRequestError.__new__(anthropic.BadRequestError, message)

        beta_error = _bad_request("fallbacks: this beta is not available")
        effort_error = _bad_request("output_config.effort is not supported for this model")
        client = self._patch_client([beta_error, effort_error, FakeMessage(text='{"rows": []}')])

        obj, _usage, _tier = claude.call_json_object(
            api_key="sk-ant-test",
            model="claude-haiku-4-5",
            instructions="rules",
            user_prompt="chunk",
            max_output_tokens=4000,
            max_retries=0,
        )

        self.assertEqual(obj, {"rows": []})
        final_request = client.messages.requests[-1]
        self.assertNotIn("betas", final_request)
        self.assertNotIn("output_config", final_request)

    def test_rejected_option_is_remembered_across_chunks(self) -> None:
        import anthropic

        beta_error = anthropic.BadRequestError.__new__(
            anthropic.BadRequestError,
            "'claude-sonnet-5' does not support the `fallbacks` parameter.",
        )
        client = self._patch_client(
            [beta_error, FakeMessage(text='{"rows": []}'), FakeMessage(text='{"rows": []}')]
        )
        call = dict(
            api_key="sk-ant-test",
            model="claude-sonnet-5",
            instructions="rules",
            user_prompt="chunk",
            max_output_tokens=4000,
            max_retries=0,
        )

        claude.call_json_object(**call)
        claude.call_json_object(**call)

        # One rejected probe, then two clean requests: an audit of 71 chunks must not
        # re-send the doomed beta on every chunk.
        self.assertEqual(len(client.messages.requests), 3)
        self.assertNotIn("betas", client.messages.requests[-1])

    def test_empty_credit_balance_is_named_instead_of_looking_like_a_refusal(self) -> None:
        import anthropic

        billing_error = anthropic.BadRequestError.__new__(
            anthropic.BadRequestError,
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits.",
        )
        client = self._patch_client([billing_error])

        with self.assertRaisesRegex(RuntimeError, "no spendable API credits"):
            claude.call_json_object(
                api_key="sk-ant-test",
                model="claude-sonnet-5",
                instructions="rules",
                user_prompt="chunk",
                max_output_tokens=4000,
                max_retries=3,
            )

        # Billing is not a transient failure: the retry budget must stay untouched.
        self.assertEqual(len(client.messages.requests), 1)

    def test_invalid_key_fails_fast_without_retries(self) -> None:
        import anthropic

        auth_error = anthropic.AuthenticationError.__new__(
            anthropic.AuthenticationError, "invalid x-api-key"
        )
        client = self._patch_client([auth_error])

        with self.assertRaisesRegex(RuntimeError, "rejected the API key"):
            claude.call_json_object(
                api_key="sk-ant-bad",
                model="claude-sonnet-5",
                instructions="rules",
                user_prompt="chunk",
                max_output_tokens=4000,
                max_retries=3,
            )

        self.assertEqual(len(client.messages.requests), 1)


if __name__ == "__main__":
    unittest.main()
