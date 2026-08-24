#!/usr/bin/env bash
# Run a docs-ai script with the Python that ships with Audion Docs AI.
#
# No system-wide installation is needed: the portable runtime already carries
# python-docx, openpyxl, PyMuPDF and python-pptx. Where that program lives is not
# guessed - it is written down in docs-ai-home.txt next to SKILL.md.
#
# Usage:  ./run.sh prepare.py --source "/docs/note.docx" --preset standard
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Usage: run.sh <script.py> [args...]" >&2
  exit 2
fi
shift

FOUND=""
HOME_PATH=""

probe() {
  [ -n "${1:-}" ] || return 1
  case "$1" in */*) [ -x "$1" ] || return 1 ;; *) command -v "$1" >/dev/null 2>&1 || return 1 ;; esac
  "$1" -c "import docx, openpyxl" >/dev/null 2>&1
}

# Accept either the program folder or a direct path to an interpreter.
from_home() {
  HOME_PATH="$1"
  local candidate
  for candidate in "$1/runtime/python.exe" "$1/runtime/bin/python3" "$1"; do
    if probe "$candidate"; then FOUND="$candidate"; return 0; fi
  done
  return 1
}

# 1. The environment wins, if someone set it deliberately.
if probe "${DOCS_AI_PYTHON:-}"; then FOUND="$DOCS_AI_PYTHON"; fi
[ -z "$FOUND" ] && [ -n "${AUDION_DOCS_AI_HOME:-}" ] && from_home "$AUDION_DOCS_AI_HOME"

# 2. The skill living inside Audion Docs AI (data/skills/<name>) needs no setup.
if [ -z "$FOUND" ] && probe "$SKILL_DIR/../../../runtime/python.exe"; then
  FOUND="$SKILL_DIR/../../../runtime/python.exe"
fi

# 3. Otherwise read the path written next to SKILL.md.
if [ -z "$FOUND" ] && [ -f "$SKILL_DIR/docs-ai-home.txt" ]; then
  while IFS= read -r LINE || [ -n "$LINE" ]; do
    LINE="${LINE%$'\r'}"
    case "$LINE" in ""|"#"*) continue ;; esac
    from_home "$LINE" && break
  done < "$SKILL_DIR/docs-ai-home.txt"
fi

# 4. Last resort: a system Python that happens to have the libraries.
if [ -z "$FOUND" ]; then
  for CANDIDATE in python3 python; do
    if probe "$CANDIDATE"; then FOUND="$CANDIDATE"; break; fi
  done
fi

if [ -z "$FOUND" ]; then
  {
    echo "[ERROR] Не найден Python с библиотеками python-docx и openpyxl."
    echo
    echo "Впишите путь к портативной Audion Docs AI в файл:"
    echo "    $SKILL_DIR/docs-ai-home.txt"
    echo "Например одной строкой:"
    echo "    E:\\TOOLS\\Audion Docs AI"
    echo
    echo "Образец с пояснениями лежит рядом: docs-ai-home.example.txt"
    echo "Проверить интерпретатор:  <python> \"$SCRIPT_DIR/check_env.py\""
    [ -n "$HOME_PATH" ] && echo && echo "Прочитано из файла: \"$HOME_PATH\" — там Python не найден или без библиотек."
  } >&2
  exit 1
fi

exec "$FOUND" "$SCRIPT_DIR/$TARGET" "$@"
