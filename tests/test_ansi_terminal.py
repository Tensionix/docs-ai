from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.ansi import AnsiHtmlRenderer, ansi_to_html, strip_ansi, terminal_html, terminal_lines_html
from system_core.core.jobs import JobContext, run_process, unbuffer_python_command
from system_core.core.logging_utils import append_log
from system_core.core.manifest import Operation
from system_core.core.paths import ProjectPaths
from system_core.core.process_decode import decode_subprocess_bytes


class AnsiTerminalTests(unittest.TestCase):
    def test_ansi_to_html_preserves_cyrillic_escapes_html_and_drops_ansi_noise(self) -> None:
        raw = "Привет <tag> \x1b[36m[OK]\x1b[0m [36m \x1b]0;title\x07done"

        html = ansi_to_html(raw)

        self.assertIn("Привет", html)
        self.assertIn("&lt;tag&gt;", html)
        self.assertIn('<span style="color:', html)
        self.assertIn("[OK]", html)
        self.assertNotIn("<tag>", html)
        self.assertNotIn("\x1b", html)
        self.assertNotIn("[0m", html)
        self.assertNotIn("[36m", html)

    def test_stateful_renderer_keeps_style_across_chunks(self) -> None:
        renderer = AnsiHtmlRenderer()

        first = renderer.feed("\x1b[1;32mOK")
        second = renderer.feed(" продолжается\x1b[0m")
        third = renderer.feed(" plain")

        self.assertIn("font-weight:700", first)
        self.assertIn("color:", first)
        self.assertIn("font-weight:700", second)
        self.assertIn("продолжается", second)
        self.assertNotIn("<span", third)

    def test_terminal_line_helpers_wrap_lines_for_append_rendering(self) -> None:
        raw_lines = ["Первая <tag>", "\x1b[36m[INFO]\x1b[0m строка"]

        fragment = terminal_lines_html(raw_lines)
        full = terminal_html(raw_lines)

        self.assertEqual(fragment.count('class="audion-terminal-line"'), 2)
        self.assertIn("&lt;tag&gt;", fragment)
        self.assertIn('<span style="color:', fragment)
        self.assertTrue(full.startswith('<pre class="audion-terminal-pre"'))
        self.assertNotIn("\x1b", fragment)
        self.assertNotIn("[36m", fragment)

    def test_strip_ansi_returns_plain_utf8_without_escape_garbage(self) -> None:
        raw = "Кириллица \x1b[36m[INFO]\x1b[0m <tag> [36m"

        plain = strip_ansi(raw)

        self.assertIn("Кириллица", plain)
        self.assertIn("[INFO]", plain)
        self.assertIn("<tag>", plain)
        self.assertNotIn("\x1b", plain)
        self.assertNotIn("[0m", plain)
        self.assertNotIn("[36m", plain)

    def test_cp866_windows_tool_output_decodes_without_mojibake(self) -> None:
        encoded = "Ошибка: не удаётся найти файл.".encode("cp866")

        decoded = decode_subprocess_bytes(encoded)

        self.assertEqual(decoded, "Ошибка: не удаётся найти файл.")
        self.assertNotIn("\ufffd", decoded)
        self.assertNotIn("����", decoded)
        self.assertNotIn("㤠", decoded)
        self.assertNotIn("䠩", decoded)

    def test_disk_log_is_plain_utf8_without_ansi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "operation.log"
            append_log(log_file, "Готово: \x1b[32m[OK]\x1b[0m [32m")

            text = log_file.read_text(encoding="utf-8")

        self.assertIn("Готово", text)
        self.assertIn("[OK]", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("[0m", text)
        self.assertNotIn("[32m", text)

    def test_run_process_keeps_raw_gui_line_but_plain_disk_log(self) -> None:
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
            gui_lines: list[str] = []
            context = JobContext(
                paths=paths,
                operation=Operation(
                    id="ansi_subprocess",
                    title="ANSI subprocess",
                    description="",
                    service="system_core.services.audion_docs_service:validate_input",
                ),
                log_file=paths.logs / "ansi.log",
                report_dir=paths.report,
                log_callback=gui_lines.append,
                progress_callback=lambda _value: None,
                cancel_callback=lambda: False,
            )

            command = [sys.executable, "-c", "print('\\x1b[36m[INFO]\\x1b[0m Привет <tag>', flush=True)"]
            result = run_process(context, command, cwd=root, heartbeat_seconds=0)
            rendered = terminal_lines_html(gui_lines)
            disk_log = context.log_file.read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(unbuffer_python_command(command)[1], "-u")
        self.assertTrue(any("\x1b[36m" in line for line in gui_lines))
        self.assertIn("[INFO] Привет <tag>", result.lines)
        self.assertIn('<span style="color:', rendered)
        self.assertIn("&lt;tag&gt;", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("[36m", rendered)
        self.assertIn("[INFO] Привет <tag>", disk_log)
        self.assertNotIn("\x1b", disk_log)
        self.assertNotIn("[36m", disk_log)


if __name__ == "__main__":
    unittest.main()
