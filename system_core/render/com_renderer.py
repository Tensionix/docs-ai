from __future__ import annotations

import shutil
import subprocess
import time
import os
from pathlib import Path
from typing import Callable

try:
    from system_core.core.ansi import strip_ansi
except ModuleNotFoundError:  # pipeline.py can import this module with system_core on sys.path
    from core.ansi import strip_ansi


class ConversionError(RuntimeError):
    pass


def log_message(log_file: Path, message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {strip_ansi(message)}\n")


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def resolve_powershell(root: Path) -> list[str]:
    candidates = [
        root / "system_core" / "powershell" / "pwsh.exe",
        Path(shutil.which("pwsh") or ""),
        Path(shutil.which("powershell") or ""),
        Path(shutil.which("powershell.exe") or ""),
    ]
    for candidate in candidates:
        if candidate and str(candidate) and candidate.exists():
            if candidate.name.lower().startswith("pwsh"):
                return [str(candidate), "-NoProfile"]
            return [str(candidate), "-NoProfile", "-ExecutionPolicy", "Bypass"]
    raise ConversionError("PowerShell was not found.")


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("NO_COLOR", None)
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["AUDION_GUI_TERMINAL"] = "1"
    return env


def hidden_subprocess_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = int(subprocess.CREATE_NO_WINDOW)
    if os.name == "nt" and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def run_subprocess(
    cmd: list[str],
    log_file: Path,
    timeout: int | None = None,
    progress_hook: Callable[[float], None] | None = None,
    progress_interval: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    rendered = " ".join(f'"{part}"' if " " in part else part for part in cmd)
    log_message(log_file, "RUN: " + rendered)
    started = time.perf_counter()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=subprocess_env(),
        **hidden_subprocess_kwargs(),
    )

    while True:
        elapsed = time.perf_counter() - started
        remaining = None if timeout is None else max(0.1, timeout - elapsed)
        wait_timeout = progress_interval if remaining is None else min(progress_interval, remaining)
        try:
            stdout, stderr = process.communicate(timeout=wait_timeout)
            completed = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
            break
        except subprocess.TimeoutExpired:
            if timeout is not None and elapsed >= timeout:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
            if progress_hook is not None:
                progress_hook(elapsed)

    if completed.stdout:
        log_message(log_file, completed.stdout.strip())
    if completed.stderr:
        log_message(log_file, completed.stderr.strip())
    return completed


def is_benign_office_disconnect(stderr: str, out_pdf: Path) -> bool:
    if not out_pdf.exists() or out_pdf.stat().st_size <= 0:
        return False

    lowered = stderr.lower()
    patterns = [
        "rpc_e_disconnected",
        "0x80010108",
        "отключен от клиентов",
        "disconnected from its clients",
    ]
    return any(pattern in lowered for pattern in patterns)


def export_office_document_to_pdf(root: Path, input_path: Path, out_pdf: Path, log_file: Path) -> list[str]:
    powershell = resolve_powershell(root)
    script_path = root / "system_core" / "render" / "office_export.ps1"
    if not script_path.exists():
        raise ConversionError("system_core/render/office_export.ps1 was not found.")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    cmd = powershell + [
        "-File",
        str(script_path),
        "-InputPath",
        str(input_path),
        "-OutputPath",
        str(out_pdf),
    ]

    last_logged = {"seconds": -1.0}

    def report_progress(elapsed: float) -> None:
        elapsed_label = format_duration(elapsed)
        if elapsed - last_logged["seconds"] >= 30.0:
            log_message(log_file, f"STILL RUNNING -> {input_path.name} [{elapsed_label}]")
            last_logged["seconds"] = elapsed
        print(f"[INFO] Still exporting: {input_path.name} ({elapsed_label})")

    completed = run_subprocess(
        cmd,
        log_file,
        timeout=600,
        progress_hook=report_progress,
        progress_interval=10.0,
    )
    if completed.returncode != 0:
        stderr = completed.stderr or ""
        if is_benign_office_disconnect(stderr, out_pdf):
            warning = "Office COM disconnected after export, PDF exists and has non-zero size"
            warnings.append(warning)
            log_message(log_file, f"WARN: {warning}: {out_pdf}")
            return warnings
        details = " ".join((stderr or completed.stdout or "").strip().split())
        if "80070520" in details:
            raise ConversionError(
                "Office is installed/registered, but COM activation is unavailable in this logon session (0x80070520)."
            )
        if len(details) > 400:
            details = details[:400] + "..."
        raise ConversionError(f"Subprocess failed with exit code {completed.returncode}. {details}")

    if not out_pdf.exists() or out_pdf.stat().st_size <= 0:
        raise ConversionError(f"PDF was not created: {out_pdf}")
    return warnings
