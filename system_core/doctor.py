from __future__ import annotations

from pathlib import Path
import importlib
import platform
import shutil
import subprocess
import sys

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from config_resolver import CONFIG_DIR, SETTINGS_FILE
from core.jobs import hidden_subprocess_kwargs, utf8_subprocess_env

REQUIRED_MODULES = [
    ("requests", "requests"),
    ("tqdm", "tqdm"),
    ("pydantic", "pydantic"),
    ("openai", "openai"),
    ("google.genai", "google-genai"),
    ("nicegui", "nicegui"),
    ("webview", "pywebview"),
    ("yaml", "pyyaml"),
    ("rich", "rich"),
    ("markitdown", "markitdown"),
    ("docx", "python-docx"),
    ("fitz", "pymupdf"),
    ("openpyxl", "openpyxl"),
    ("pptx", "python-pptx"),
    ("bs4", "beautifulsoup4"),
    ("pandas", "pandas"),
]

OPTIONAL_MODULES = [
    ("pdfplumber", "pdfplumber"),
    ("pypdfium2", "pypdfium2"),
    ("markdownify", "markdownify"),
    ("mammoth", "mammoth"),
    ("coloredlogs", "coloredlogs"),
]

REQUIRED_DIRS = [
    "config",
    "input",
    "output",
    "logs",
    "report",
    "workspace",
    "work",
    "config/audit_rules",
    "config/doc_tasks",
    "runtime",
    "wheelhouse",
    "system_core",
]


RENDER_DIRS = [
    "work/rendered_pdf",
    "work/marked_ooxml",
    "work/extracted_pdf_text",
]


GENERATED_DIRS = [
    "cache",
    "licenses",
    "release",
]


def check_module(import_name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, str(version)
    except Exception as exc:
        return False, exc.__class__.__name__


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    if (root / ".venv" / "Scripts" / "python.exe").exists():
        return "legacy-venv"
    return "system-python"


def resolve_powershell(root: Path) -> list[str] | None:
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
    return None


def check_office_com(root: Path, prog_id: str) -> tuple[bool, str]:
    powershell = resolve_powershell(root)
    if not powershell:
        return False, "PowerShell not found"

    cmd = powershell + [
        "-Command",
        (
            "$ErrorActionPreference='Stop'; "
            f"$app=New-Object -ComObject {prog_id}; "
            "try { 'OK' } finally { "
            "try { $app.Quit() } catch {}; "
            "[void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($app) "
            "}"
        ),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env=utf8_subprocess_env(),
            **hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        return False, exc.__class__.__name__
    if completed.returncode == 0 and "OK" in (completed.stdout or ""):
        return True, "available"
    detail = (completed.stderr or completed.stdout or "unavailable").strip().splitlines()
    message = detail[-1] if detail else "unavailable"
    if "80070520" in message:
        return False, "installed/registered, but COM is unavailable in this logon session (0x80070520)"
    return False, message


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    print("======================================================================")
    print("AUDION DOCS AI v3 - PORTABLE DOCTOR")
    print("======================================================================")
    print(f"Project root : {root}")
    print(f"Executable   : {sys.executable}")
    print(f"Python       : {sys.version.split()[0]}")
    print(f"Python mode  : {detect_python_mode(root)}")
    print(f"Platform     : {platform.platform()}")
    print()

    failed = False

    print("[Required modules]")
    for import_name, package_name in REQUIRED_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "FAIL"
        print(f"  - {package_name:<18} : {status:<4} {detail}")
        if not ok:
            failed = True

    print()
    print("[Optional modules]")
    for import_name, package_name in OPTIONAL_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "MISS"
        print(f"  - {package_name:<18} : {status:<4} {detail}")

    print()
    print("[Project paths]")
    for rel in REQUIRED_DIRS + RENDER_DIRS:
        path = root / rel
        ok = path.exists()
        print(f"  - {rel:<18} : {'OK' if ok else 'MISS'} {path}")
        if not ok:
            failed = True
    for rel in GENERATED_DIRS:
        path = root / rel
        ok = path.exists()
        print(f"  - {rel:<18} : {'OK' if ok else 'MISS'} {path} (generated)")

    print()
    print("[Portable assets]")
    fzf_path = root / "system_core" / "fzf.exe"
    pwsh_path = root / "system_core" / "powershell" / "pwsh.exe"
    render_script = root / "system_core" / "render" / "office_export.ps1"
    powershell = resolve_powershell(root)
    print(f"  - fzf.exe            : {'OK' if fzf_path.exists() else 'MISS'} {fzf_path}")
    print(f"  - portable pwsh.exe  : {'OK' if pwsh_path.exists() else 'MISS'} {pwsh_path}")
    print(f"  - PowerShell         : {'OK' if powershell else 'MISS'} {' '.join(powershell or [])}")
    print(f"  - office_export.ps1  : {'OK' if render_script.exists() else 'MISS'} {render_script}")
    print(f"  - gui_settings.yaml  : {'OK' if (CONFIG_DIR / 'gui_settings.yaml').exists() else 'MISS'} {CONFIG_DIR / 'gui_settings.yaml'}")
    print(f"  - tool_manifest.yaml : {'OK' if (CONFIG_DIR / 'tool_manifest.yaml').exists() else 'MISS'} {CONFIG_DIR / 'tool_manifest.yaml'}")
    print(f"  - llm_settings.yaml  : {'OK' if SETTINGS_FILE.exists() else 'MISS'} {SETTINGS_FILE}")
    print(f"  - api_key_gemini.txt : {'OK' if (CONFIG_DIR / 'api_key_gemini.txt').exists() else 'MISS'}")
    print(f"  - api_key_openai.txt : {'OK' if (CONFIG_DIR / 'api_key_openai.txt').exists() else 'MISS'}")
    print(f"  - api_key_xai.txt    : {'OK' if (CONFIG_DIR / 'api_key_xai.txt').exists() else 'MISS'}")
    print(f"  - api_key_anthropic.txt : {'OK' if (CONFIG_DIR / 'api_key_anthropic.txt').exists() else 'MISS'}")

    print()
    print("[Office COM render]")
    word_ok, word_detail = check_office_com(root, "Word.Application")
    ppt_ok, ppt_detail = check_office_com(root, "PowerPoint.Application")
    print(f"  - Word COM           : {'OK' if word_ok else 'MISS'} {word_detail}")
    print(f"  - PowerPoint COM     : {'OK' if ppt_ok else 'MISS'} {ppt_detail}")
    print("  - strict render-map  : " + ("OK" if word_ok and ppt_ok and render_script.exists() else "UNAVAILABLE"))

    print()
    if failed:
        print("[RESULT] One or more required modules or folders are missing.")
        return 1

    print("[RESULT] Required portable environment looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
