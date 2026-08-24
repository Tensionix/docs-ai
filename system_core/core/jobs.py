from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib
import json
import os
import queue
import subprocess
import threading
import time
import traceback

from .ansi import strip_ansi
from .logging_utils import append_log, timestamp
from .manifest import Operation
from .paths import ProjectPaths
from .process_decode import decode_subprocess_bytes, is_python_command


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


@dataclass
class JobContext:
    paths: ProjectPaths
    operation: Operation
    log_file: Path
    report_dir: Path
    log_callback: LogCallback | None = None
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None

    def log(self, message: str) -> None:
        append_log(self.log_file, message)
        if self.log_callback:
            self.log_callback(message)

    def progress(self, value: float) -> None:
        if self.progress_callback:
            self.progress_callback(max(0.0, min(1.0, float(value))))

    def cancelled(self) -> bool:
        return bool(self.cancel_callback and self.cancel_callback())


@dataclass
class JobResult:
    ok: bool
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    lines: tuple[str, ...]


def utf8_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    env.pop("NO_COLOR", None)
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["AUDION_GUI_TERMINAL"] = "1"
    return env


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def hidden_subprocess_creationflags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_kwargs() -> dict[str, Any]:
    return {
        "startupinfo": hidden_subprocess_startupinfo(),
        "creationflags": hidden_subprocess_creationflags(),
    }


def format_command(command: list[str]) -> str:
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def unbuffer_python_command(command: list[str]) -> list[str]:
    if not command:
        return command
    if not is_python_command(command):
        return command
    if any(part == "-u" or part.startswith("-u") for part in command[1:]):
        return command
    return [command[0], "-u", *command[1:]]


SPINNER_FRAME_CHARS = set("-\\|/ \t")


def _is_spinner_only_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and all(char in SPINNER_FRAME_CHARS for char in line)


def decoded_process_lines(raw_line: bytes | str) -> list[str]:
    text = str(raw_line) if isinstance(raw_line, str) else decode_subprocess_bytes(raw_line)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for part in text.split("\n"):
        line = part.rstrip()
        if not line or _is_spinner_only_line(line):
            continue
        lines.append(line)
    return lines


def run_process(
    context: JobContext,
    command: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
    progress_seconds: float = 600.0,
    heartbeat_seconds: float = 30.0,
) -> ProcessResult:
    """Run a child process hidden, stream stdout/stderr into the GUI log."""
    if not command:
        raise ValueError("Command is empty.")

    command = unbuffer_python_command(command)
    text_stream = is_python_command(command) or os.name != "nt"
    working_dir = cwd or context.paths.root
    context.log(f"[CWD] {working_dir}")
    context.log(f"[CMD] {format_command(command)}")

    popen_kwargs: dict[str, Any] = {
        "cwd": str(working_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": utf8_subprocess_env(extra_env),
        **hidden_subprocess_kwargs(),
    }
    if text_stream:
        popen_kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    else:
        popen_kwargs.update({"text": False})

    process = subprocess.Popen(command, **popen_kwargs)

    lines: list[str] = []
    start = time.monotonic()
    last_progress = start
    last_child_output = start
    last_heartbeat = start
    output_queue: queue.Queue[str | bytes | None] = queue.Queue()

    assert process.stdout is not None
    context.progress(0.05)

    def read_stdout() -> None:
        try:
            for raw in process.stdout:
                output_queue.put(raw)
        finally:
            try:
                process.stdout.close()
            except OSError:
                pass
            output_queue.put(None)

    reader = threading.Thread(target=read_stdout, name="audion-child-stdout", daemon=True)
    reader.start()
    stdout_done = False

    while not stdout_done:
        if context.cancelled():
            context.log("[CANCEL] Terminating child process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError("Operation cancelled by user.")

        try:
            item = output_queue.get(timeout=0.1)
        except queue.Empty:
            item = ""

        if item is None:
            stdout_done = True
        elif item:
            for line in decoded_process_lines(item):
                lines.append(strip_ansi(line))
                context.log(line)
                last_child_output = time.monotonic()

        now = time.monotonic()
        if now - last_progress >= 0.5:
            elapsed = max(0.0, now - start)
            context.progress(min(0.95, 0.08 + elapsed / max(1.0, float(progress_seconds))))
            last_progress = now
        if heartbeat_seconds > 0 and now - last_child_output >= heartbeat_seconds and now - last_heartbeat >= heartbeat_seconds:
            elapsed = max(0.0, now - start)
            context.log(f"[RUNNING] child process is still working; no output for {now - last_child_output:.0f}s, elapsed={elapsed:.0f}s.")
            last_heartbeat = now

    exit_code = process.wait()
    reader.join(timeout=1)
    context.log(f"[EXIT] {exit_code}")
    if check and exit_code != 0:
        raise RuntimeError(f"Command failed with exit code {exit_code}.")
    return ProcessResult(exit_code=exit_code, lines=tuple(lines))


def resolve_project_path(context: JobContext, raw_path: str) -> Path:
    path_text = raw_path.strip().strip('"')
    if not path_text:
        raise RuntimeError("Path field is empty.")
    path = Path(os.path.expandvars(path_text)).expanduser()
    if not path.is_absolute():
        path = context.paths.root / path
    return path


def run_cmd_script(
    context: JobContext,
    script: str,
    args: list[str] | None = None,
    *,
    check: bool = True,
) -> ProcessResult:
    script_path = resolve_project_path(context, script)
    if not script_path.exists():
        raise RuntimeError(f"Script was not found: {script_path}")
    command = ["cmd.exe", "/d", "/c", "call", str(script_path), *(args or [])]
    return run_process(context, command, cwd=context.paths.root, check=check)


def _load_callable(service: str) -> Callable[[JobContext], Any]:
    module_name, function_name = service.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def execute_operation(
    paths: ProjectPaths,
    operation: Operation,
    log_callback: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> JobResult:
    run_stamp = timestamp().replace(":", "-")
    log_file = paths.logs / f"{run_stamp}_{operation.id}.log"
    report_dir = paths.report / f"{run_stamp}_{operation.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    context = JobContext(paths, operation, log_file, report_dir, log_callback, progress_callback, cancel_callback)

    try:
        context.log(f"Starting operation: {operation.id}")
        if operation.parameters:
            context.log(f"Parameters: {json.dumps(operation.parameters, ensure_ascii=False, sort_keys=True)}")
        context.progress(0.0)
        result = _load_callable(operation.service)(context)
        context.progress(1.0)
        context.log(f"Finished operation: {operation.id}")

        if isinstance(result, dict):
            return JobResult(True, "Operation finished.", result)
        return JobResult(True, str(result or "Operation finished."), {})

    except Exception as exc:
        context.log(traceback.format_exc())
        return JobResult(False, f"{exc.__class__.__name__}: {exc}", {})
