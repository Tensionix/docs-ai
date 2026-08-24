# Audion Docs AI Config Resolver

This folder owns project LLM configuration and prompt text.

Runtime files:
- `llm_settings.yaml` stores provider selection, retry settings, chunk settings, and prompt file names. It intentionally does not curate fixed model ids anymore.
- `api_key_openai.txt` stores one or more local OpenAI keys when `OPENAI_API_KEY` is not set.
- `api_key_gemini.txt` stores one or more local Gemini keys when `GEMINI_API_KEY` is not set.
- `api_key_xai.txt` stores one or more local xAI keys when `XAI_API_KEY` is not set.
- `gui_key_cache.json` stores GUI key pins only; it must not contain actual API keys.
- `gui_model_cache.json` stores GUI model list cache, favorites, and explicit selected-model smoke check statuses.
- `audit_rules/active_audit_rules.md` is the canonical audit instruction file for CLI/TUI/default runs.
- `gui_rules_cache.json` stores audit rule labels, active selection, usage counts, and pins.
- `doc_tasks/active_doc_task.md` is the default general document-task instruction file.
- `gui_doc_task_cache.json` stores document-task labels, active selection, usage counts, and pins.
- `gui_doc_task_quick_cache.json` stores inline quick document-task instructions, usage counts, and pins.

API key files are private local lists. Backward-compatible one-line format still works:

```text
sk-...
```

Recommended multi-key format:

```text
# label | key | comment
main | sk-... | primary paid account
backup = sk-... # lower quota reserve
```

For Gemini:

```text
main | AIza... | primary Google AI Studio key
```

For xAI:

```text
main | xai-... | primary xAI key
```

The GUI dropdown shows labels/comments and keeps favorite key references in `gui_key_cache.json`. It does not store the key material in the cache.

Model selection:
- GUI dropdowns load provider model lists and fall back to `gui_model_cache.json`.
- The explicit `ПРОВЕРИТЬ МОДЕЛЬ` action sends one tiny provider request and stores `ok`, `error`, or `no_access` with a date.
- CLI/GUI empty model fallback uses the latest `ok` checked model, then the first favorite model.
- The engine never picks an arbitrary model from a raw provider list, because provider lists can include historical or account-inaccessible ids.

Prompt files:
- `audit_system_prompt.md` is the system instruction for document audit.
- `audit_user_prompt.md` is the per-chunk user prompt template.
- `ocr_prompt.md` is the AI extraction/OCR prompt.
- `doc_task_system_prompt.md` is the JSON contract prompt for general document tasks.

Template placeholders:
- `{{RULES_CONTEXT}}` is replaced with the selected Markdown rules from `config/audit_rules`.
- `{{OVERLAP_CONTEXT}}` is replaced with overlap blocks for chunked audit.
- `{{NEW_CHUNK_TEXT}}` is replaced with the current chunk text.

Document-task files in `config/doc_tasks` are used by `system_core/doc_task_runner.py`.
Document tasks read DOCX/PPTX/XLSX/PDF recursively from `input`. PDF pages are read-only text sources through PyMuPDF; exact replacements stay DOCX-only and write edited copies only to `output`.
The primary human-facing output is DOCX. Structured XLSX uses the same warm table styling as audit reports and expands JSON `values` fields into real columns; JSON/MD are supporting artifacts.
Quick document tasks can bypass a Markdown file by passing `AUDION_DOC_TASK_TEXT`. The GUI stores reusable inline instructions in `gui_doc_task_quick_cache.json`.

Do not put secrets into release archives. Release scripts exclude `config\api_key_*.txt`.
