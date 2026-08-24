from __future__ import annotations

import locale
import os
from pathlib import Path

from .output_decode import decode_process_bytes


_MOJIBAKE_CHARS = set("�㤠䠩����ЋЊЌЏђњќџЎўЄєЇїІіҐґ")


def is_python_command(command: list[str] | tuple[str, ...]) -> bool:
    if not command:
        return False
    executable = Path(str(command[0])).name.lower()
    return executable in {"python", "python.exe", "python3", "python3.exe", "pythonw.exe"}


def decode_subprocess_bytes(data: bytes) -> str:
    """Decode Windows tool output without committing to lossy UTF-8 first."""
    return decode_process_bytes(data)


def has_mojibake_symptoms(text: str) -> bool:
    if "\ufffd" in text:
        return True
    if any(char in text for char in _MOJIBAKE_CHARS):
        return True
    cjk = sum(1 for char in text if 0x3400 <= ord(char) <= 0x9FFF)
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\t\r\n")
    return cjk > 0 or controls > max(2, len(text) // 12)


def _decode_utf16_if_likely(data: bytes) -> str | None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None

    if len(data) < 4:
        return None
    sample = data[: min(len(data), 200)]
    even_nulls = sample[0::2].count(0)
    odd_nulls = sample[1::2].count(0)
    half = max(1, len(sample) // 2)
    encoding = ""
    if odd_nulls / half > 0.35 and even_nulls / half < 0.10:
        encoding = "utf-16-le"
    elif even_nulls / half > 0.35 and odd_nulls / half < 0.10:
        encoding = "utf-16-be"
    if not encoding:
        return None
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    return None if has_mojibake_symptoms(text) else text


def _fallback_encodings() -> list[str]:
    encodings = ["cp866"]
    preferred = locale.getpreferredencoding(False)
    if preferred:
        encodings.append(preferred)
    if os.name == "nt":
        encodings.append("mbcs")
    encodings.append("cp1251")

    unique: list[str] = []
    seen: set[str] = set()
    for encoding in encodings:
        key = encoding.lower()
        if key not in seen:
            unique.append(encoding)
            seen.add(key)
    return unique


def _readability_score(text: str) -> int:
    if not text:
        return 0
    cyrillic = sum(1 for char in text if "А" <= char <= "я" or char in "Ёё")
    ascii_printable = sum(1 for char in text if 32 <= ord(char) < 127)
    spaces = text.count(" ")
    punctuation = sum(1 for char in text if char in ".,:;!?[]()/-_\\")
    replacements = text.count("\ufffd")
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\t\r\n")
    cjk = sum(1 for char in text if 0x3400 <= ord(char) <= 0x9FFF)
    mojibake = sum(1 for char in text if char in _MOJIBAKE_CHARS)
    return cyrillic * 8 + ascii_printable * 2 + spaces * 2 + punctuation - replacements * 120 - controls * 50 - cjk * 80 - mojibake * 35
