#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report whether this interpreter can run the docs-ai skills.

Run it with a candidate interpreter to find out if that one will do:

    "E:\\TOOLS\\Audion Docs AI\\runtime\\python.exe" check_env.py

An embedded or portable Python is perfectly fine - nothing here needs a
system-wide installation, admin rights or a virtual environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

# What each part of the pipeline needs. PyMuPDF is only required for page numbers.
REQUIRED = [
    ("docx", "python-docx", "разбор и разметка DOCX"),
    ("openpyxl", "openpyxl", "таблица ошибок XLSX"),
]
OPTIONAL = [
    ("fitz", "PyMuPDF", "карта страниц: чтение PDF"),
    ("pptx", "python-pptx", "поддержка PPTX"),
]


def probe(module: str) -> str | None:
    try:
        mod = __import__(module)
    except Exception:
        return None
    return str(getattr(mod, "__version__", "")) or "ok"


def main() -> int:
    print(f"interpreter : {sys.executable}")
    print(f"version     : {sys.version.split()[0]}")

    missing: list[str] = []
    for module, package, what in REQUIRED:
        found = probe(module)
        print(f"[{'OK ' if found else 'НЕТ'}] {package:14} {what}" + (f" ({found})" if found else ""))
        if not found:
            missing.append(package)

    for module, package, what in OPTIONAL:
        found = probe(module)
        print(f"[{'OK ' if found else '  -'}] {package:14} {what} (необязательно)" + (f" ({found})" if found else ""))

    # Word is what turns block ids into page numbers; without it everything else still works.
    import shutil

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    print(f"[{'OK ' if powershell else 'НЕТ'}] PowerShell     запуск экспорта Word -> PDF")

    if missing:
        print("\nНе хватает: " + ", ".join(missing))
        print(f"Поставить: \"{sys.executable}\" -m pip install " + " ".join(missing))
        return 1

    print("\nЭтот интерпретатор подходит. Запускайте им скрипты скиллов напрямую")
    print("или задайте его один раз: DOCS_AI_PYTHON=\"<путь>\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
