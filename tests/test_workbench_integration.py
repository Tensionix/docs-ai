from __future__ import annotations

import os
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path[0] = str(ROOT)


def import_gui_module(name: str):
    old_argv0 = sys.argv[0]
    try:
        sys.argv[0] = str(Path(__file__).resolve())
        return importlib.import_module(name)
    finally:
        sys.argv[0] = old_argv0


class WorkbenchIntegrationTests(unittest.TestCase):
    def test_public_vocabulary_is_canonical(self) -> None:
        CANONICAL_WORKBENCH_TEXT = import_gui_module(
            "system_core.ui_nicegui.workbench"
        ).CANONICAL_WORKBENCH_TEXT

        self.assertEqual(
            [CANONICAL_WORKBENCH_TEXT["ru"][key] for key in (
                "source_folder", "add_file_short", "target_folder", "clear_io_short", "delete_io_short", "file_list_button"
            )],
            ["Источник", "Добавить файл...", "Назначение", "Сбросить", "Удалить", "Список"],
        )
        self.assertEqual(
            [CANONICAL_WORKBENCH_TEXT["en"][key] for key in (
                "source_folder", "add_file_short", "target_folder", "clear_io_short", "delete_io_short", "file_list_button"
            )],
            ["Source", "Add file...", "Target", "Reset", "Delete", "List"],
        )

    def test_single_file_source_and_external_target_reach_document_backend(self) -> None:
        from system_core.document_model import default_project_paths, ensure_project_dirs, iter_documents, source_relative
        from system_core.pipeline import cmd_scan

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "single.docx"
            source.write_bytes(b"test")
            target = root / "result"
            with patch.dict(os.environ, {
                "AUDION_WORKBENCH_SOURCE": str(source),
                "AUDION_WORKBENCH_TARGET": str(target),
            }):
                paths = default_project_paths(ROOT)
            self.assertEqual(paths.input_dir, source.resolve())
            self.assertEqual(paths.output_dir, target.resolve())
            self.assertEqual(iter_documents(paths.input_dir), [source.resolve()])
            self.assertEqual(source_relative(source.resolve(), paths.input_dir), Path("single.docx"))
            ensure_project_dirs(paths)
            self.assertEqual(cmd_scan(paths, recursive=True), 0)
            scan = (paths.logs_dir / "scan.json").read_text(encoding="utf-8")
            self.assertIn('"relative_path": "single.docx"', scan)

    def test_gui_active_paths_follow_workbench(self) -> None:
        app = import_gui_module("system_core.ui_nicegui.app")

        old_source = app.state.get("source_path")
        old_target = app.state.get("destination_path")
        try:
            app.state["source_path"] = str(ROOT / "input" / "one.docx")
            app.state["destination_path"] = str(ROOT / "output" / "custom")
            active = app.active_project_paths()
            self.assertEqual(active.input, (ROOT / "input" / "one.docx").resolve())
            self.assertEqual(active.output, (ROOT / "output" / "custom").resolve())
        finally:
            app.state["source_path"] = old_source
            app.state["destination_path"] = old_target

    def test_delete_guard_refuses_filesystem_and_project_roots(self) -> None:
        app = import_gui_module("system_core.ui_nicegui.app")

        with self.assertRaises(RuntimeError):
            app.validate_workspace_delete_target(Path(ROOT.anchor))
        with self.assertRaises(RuntimeError):
            app.validate_workspace_delete_target(ROOT)

    def test_specialized_commands_keep_quick_task_inside_section(self) -> None:
        app = import_gui_module("system_core.ui_nicegui.app")
        root_nodes = app.root_command_nodes()
        self.assertNotIn("quick_doc_tasks", {node.id for node in root_nodes})
        specialized = next(node for node in root_nodes if node.id == "specialized_commands")
        self.assertTrue({"quick_doc_tasks", "comma_restore"}.issubset({child.id for child in app.visible_command_children(specialized)}))

    def test_dynamic_file_options_follow_external_workbench_source(self) -> None:
        from system_core.services.audion_docs_service import input_file_options, template_file_options

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            (source / "external.docx").write_bytes(b"docx")
            (source / "external.pdf").write_bytes(b"pdf")
            values = {"source_dir": str(source)}
            input_values = {item["value"] for item in input_file_options(ROOT, values)}
            template_values = {item["value"] for item in template_file_options(ROOT, values)}
            self.assertTrue({"external.docx", "external.pdf"}.issubset(input_values))
            self.assertIn("external.docx", template_values)

    def test_gemini_reasoning_chips_have_room_for_minimal_label(self) -> None:
        # The CSS moved out of app.py into .css files beside it.
        ui_dir = ROOT / "system_core" / "ui_nicegui"
        text = "\n".join(
            [(ui_dir / "app.py").read_text(encoding="utf-8")]
            + [path.read_text(encoding="utf-8") for path in sorted(ui_dir.glob("*.css"))]
        )
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)) !important;", text)
        self.assertIn("min-width: 132px !important;", text)


if __name__ == "__main__":
    unittest.main()
