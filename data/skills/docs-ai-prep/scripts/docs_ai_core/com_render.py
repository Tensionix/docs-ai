#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export an Office document to PDF through Word/PowerPoint COM.

This is the only Windows-bound piece of the pipeline and it exists for one reason:
page numbers. Nothing inside a .docx knows which page a paragraph lands on - the
layout is decided by Word at render time. So a marked copy is exported to PDF and
the markers are looked up page by page.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "office_export.ps1"


class ExportError(RuntimeError):
    """Word/PowerPoint could not produce a PDF."""


def resolve_powershell() -> list[str]:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return [found, "-NoProfile", "-ExecutionPolicy", "Bypass"]
    raise ExportError("Neither pwsh nor powershell was found in PATH.")


def export_to_pdf(input_path: Path, out_pdf: Path, *, timeout: int = 900) -> Path:
    if not SCRIPT.exists():
        raise ExportError(f"office_export.ps1 is missing next to {__file__}")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    cmd = resolve_powershell() + [
        "-File", str(SCRIPT),
        "-InputPath", str(input_path),
        "-OutputPath", str(out_pdf),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0 or not out_pdf.exists():
        detail = (completed.stderr or completed.stdout or "").strip()[-600:]
        raise ExportError(f"Export failed (exit {completed.returncode}): {detail}")
    return out_pdf
