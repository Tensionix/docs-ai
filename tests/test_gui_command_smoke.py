from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.jobs import JobContext, run_process
from system_core.core.manifest import CommandNode, Operation, load_manifest
from system_core.core.paths import ProjectPaths
from system_core.services import audion_docs_service


MANIFEST_PATH = ROOT / "config" / "tool_manifest.yaml"
GUI_APP_PATH = ROOT / "system_core" / "ui_nicegui" / "app.py"


def gui_source_and_styles() -> str:
    """The module plus the stylesheets beside it.

    The CSS used to be a string literal inside `app.py` and is now read from
    `.css` files next to it, so a rule and the code that adds its class are no
    longer in the same file. Assertions about either still belong together.
    """
    ui_dir = GUI_APP_PATH.parent
    return "\n".join(
        [GUI_APP_PATH.read_text(encoding="utf-8")]
        + [path.read_text(encoding="utf-8") for path in sorted(ui_dir.glob("*.css"))]
    )


def resolve_ref(ref: str):
    module_name, function_name = ref.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def leaf_nodes(nodes: list[CommandNode] | tuple[CommandNode, ...]):
    for node in nodes:
        if node.children:
            yield from leaf_nodes(node.children)
        else:
            yield node


def all_fields(manifest) -> list[dict]:
    fields: list[dict] = []
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        fields.extend(operation.fields)
    for node in leaf_nodes(tuple(manifest.operation_groups)):
        fields.extend(node.fields)
    return fields


class GuiCommandSmokeTests(unittest.TestCase):
    def test_header_theme_tooltip_wrapper_does_not_expand_to_full_width(self) -> None:
        source = gui_source_and_styles()

        self.assertIn(".audion-theme-tooltip-target {\n            width: auto;", source)
        self.assertNotIn(
            ".audion-select-control,\n          .audion-theme-tooltip-target {\n            width: 100%;",
            source,
        )
        self.assertIn('ui.row().classes("audion-header-brand items-baseline gap-2")', source)

    def test_reasoning_radios_render_as_outlined_chips(self) -> None:
        source = gui_source_and_styles()

        self.assertIn('base += " audion-field-reasoning-chips"', source)
        self.assertIn(".audion-field-reasoning-chips .audion-choice-row .q-radio {", source)
        self.assertIn("min-width: 132px !important;", source)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)) !important;", source)
        self.assertIn("justify-content: center !important;", source)
        self.assertIn("border-radius: 999px !important;", source)
        self.assertIn(".audion-field-reasoning-chips .audion-choice-row .q-radio__inner {", source)
        self.assertIn("display: none !important;", source)
        self.assertIn('.audion-field-reasoning-chips .audion-choice-row .q-radio[aria-checked="true"] {', source)
        self.assertIn("text-align: center;", source)

    def test_manifest_services_and_option_sources_resolve(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        commands = [*manifest.operations, *manifest.maintenance_operations, *leaf_nodes(tuple(manifest.operation_groups))]

        self.assertGreater(len(commands), 20)
        for command in commands:
            with self.subTest(command=command.id, service=command.service):
                self.assertTrue(callable(resolve_ref(command.service)))

        for field in all_fields(manifest):
            source = str(field.get("options_source") or "").strip()
            if not source:
                continue
            with self.subTest(options_source=source):
                self.assertTrue(callable(resolve_ref(source)))

    def test_manifest_modes_are_known_by_services(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        commands = [*manifest.operations, *manifest.maintenance_operations, *leaf_nodes(tuple(manifest.operation_groups))]
        pipeline_modes = {
            "pin_model",
            "check_model",
            "pin_api_key",
            "pin_audit_rule",
            "set_active_audit_rule",
            "import_audit_rule",
            "scan",
            "render",
            "audit",
            "report",
            "annotate",
            "strip_anchors",
            "report_annotate",
            "full",
        }
        doc_task_modes = {
            "pin_doc_task",
            "set_active_doc_task",
            "import_doc_task",
            "save_quick_doc_task",
            "pin_quick_doc_task",
            "delete_quick_doc_task",
            "check_model",
            "run_doc_task",
            "run_quick_doc_task",
        }

        for command in commands:
            mode = str(command.parameters.get("mode") or "").strip()
            if command.service.endswith(":run_pipeline_operation"):
                with self.subTest(command=command.id):
                    self.assertIn(mode, pipeline_modes)
            if command.service.endswith(":run_doc_task_operation"):
                with self.subTest(command=command.id):
                    self.assertIn(mode, doc_task_modes)
            if command.service.endswith(":normalize_documents_from_audit"):
                with self.subTest(command=command.id):
                    self.assertIn(
                        str(command.parameters.get("provider") or ""),
                        {"openai", "gemini", "xai", "anthropic"},
                    )

    def test_process_runner_reports_heartbeat_without_child_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["input", "output", "logs", "report", "workspace", "config", "release", "system_core"]:
                (root / name).mkdir(parents=True, exist_ok=True)
            paths = ProjectPaths(
                root=root,
                input=root / "input",
                output=root / "output",
                logs=root / "logs",
                report=root / "report",
                workspace=root / "workspace",
                config=root / "config",
                release=root / "release",
                system_core=root / "system_core",
            )
            log_lines: list[str] = []
            progress_values: list[float] = []
            context = JobContext(
                paths=paths,
                operation=Operation(
                    id="heartbeat_smoke",
                    title="Heartbeat smoke",
                    description="",
                    service="system_core.services.audion_docs_service:validate_input",
                ),
                log_file=paths.logs / "heartbeat.log",
                report_dir=paths.report,
                log_callback=log_lines.append,
                progress_callback=progress_values.append,
                cancel_callback=lambda: False,
            )

            result = run_process(
                context,
                [sys.executable, "-c", "import time; time.sleep(0.7); print('done')"],
                cwd=root,
                progress_seconds=1.0,
                heartbeat_seconds=0.2,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("done", result.lines)
            self.assertTrue(any(line.startswith("[RUNNING]") for line in log_lines))
            self.assertTrue(any(value > 0.05 for value in progress_values))

    def test_reset_model_cache_clears_provider_models_checks_and_favorites(self) -> None:
        old_path = audion_docs_service.MODEL_CACHE_PATH
        with tempfile.TemporaryDirectory() as tmp:
            try:
                audion_docs_service.MODEL_CACHE_PATH = Path(tmp) / "gui_model_cache.json"
                audion_docs_service.MODEL_CACHE_PATH.write_text(
                    """
{
  "providers": {
    "openai": {
      "models": ["gpt-old"],
      "pinned": ["gpt-old"],
      "checks": {"gpt-old": {"status": "ok"}}
    },
    "gemini": {
      "models": ["gemini-old"],
      "pinned": ["gemini-old"],
      "checks": {}
    }
  }
}
""".strip(),
                    encoding="utf-8",
                )

                removed = audion_docs_service.reset_model_cache("openai")
                payload = audion_docs_service._read_model_cache()
                openai_cache = payload["providers"]["openai"]
                gemini_cache = payload["providers"]["gemini"]

                self.assertEqual(removed, {"models": 1, "pinned": 1, "checks": 1})
                self.assertEqual(openai_cache["models"], [])
                self.assertEqual(openai_cache["pinned"], [])
                self.assertEqual(openai_cache["checks"], {})
                self.assertEqual(gemini_cache["models"], ["gemini-old"])
            finally:
                audion_docs_service.MODEL_CACHE_PATH = old_path

    def test_add_api_key_entry_accepts_pasted_key_file_line(self) -> None:
        old_file_for_provider = audion_docs_service._api_key_file_for_provider
        old_api_key_entries = audion_docs_service.api_key_entries
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "api_key_xai.txt"

            try:
                audion_docs_service._api_key_file_for_provider = lambda provider: key_path
                audion_docs_service.api_key_entries = lambda provider: audion_docs_service.parse_api_key_entries(
                    provider,
                    key_path.read_text(encoding="utf-8") if key_path.exists() else "",
                )

                entry = audion_docs_service.add_api_key_entry(
                    "xai",
                    "",
                    "ignored helper line\nXAI from portal | xai-test-key-123456789012345 | mobile",
                    "",
                )

                text = key_path.read_text(encoding="utf-8")
                self.assertEqual(entry["label"], "XAI from portal")
                self.assertEqual(entry["note"], "mobile")
                self.assertIn("XAI from portal | xai-test-key-123456789012345 | mobile", text)
                self.assertNotIn("ignored helper line", text)
            finally:
                audion_docs_service._api_key_file_for_provider = old_file_for_provider
                audion_docs_service.api_key_entries = old_api_key_entries


if __name__ == "__main__":
    unittest.main()
