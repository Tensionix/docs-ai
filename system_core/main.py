from __future__ import annotations

from pathlib import Path
import json
import sys


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    if (root / ".venv" / "Scripts" / "python.exe").exists():
        return "legacy-venv"
    return "system-python"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    payload = {
        "project_root": str(root),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "python_mode": detect_python_mode(root),
        "folders": {
            "input": str(root / "input"),
            "output": str(root / "output"),
            "logs": str(root / "logs"),
            "report": str(root / "report"),
            "workspace": str(root / "workspace"),
            "work": str(root / "work"),
            "cache": str(root / "cache"),
            "audit_rules": str(root / "config" / "audit_rules"),
            "doc_tasks": str(root / "config" / "doc_tasks"),
            "config": str(root / "config"),
            "runtime": str(root / "runtime"),
            "wheelhouse": str(root / "wheelhouse"),
            "release": str(root / "release"),
            "portable_powershell": str(root / "system_core" / "powershell"),
        },
        "message": "Audion Docs AI v3 is wired for the portable template runtime.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
