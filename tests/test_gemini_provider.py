from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "system_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from providers import gemini_provider as gemini


class _Models:
    def __init__(self) -> None:
        self.config = None

    def generate_content(self, *, model, contents, config):
        self.config = config
        return SimpleNamespace(text='{"rows": []}', usage_metadata=None)


class GeminiProviderTests(unittest.TestCase):
    def test_gemini_35_sends_real_thinking_level(self) -> None:
        models = _Models()
        client = SimpleNamespace(models=models)

        gemini.call_structured(
            client,
            model="gemini-3.5-flash",
            system_instruction="system",
            user_prompt="user",
            thinking_level="high",
            max_retries=0,
        )

        self.assertEqual(models.config.thinking_config.thinking_level.value, "HIGH")

    def test_older_gemini_does_not_receive_thinking_level(self) -> None:
        models = _Models()
        client = SimpleNamespace(models=models)

        gemini.call_structured(
            client,
            model="gemini-2.5-flash",
            system_instruction="system",
            user_prompt="user",
            thinking_level="high",
            max_retries=0,
        )

        self.assertIsNone(models.config.thinking_config)


if __name__ == "__main__":
    unittest.main()
