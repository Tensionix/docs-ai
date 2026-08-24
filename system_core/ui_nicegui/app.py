from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
import atexit
import argparse
import ctypes
from ctypes import wintypes
import inspect
import importlib
import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import app as nicegui_app, run, ui  # type: ignore
from nicegui.element import Element  # type: ignore
from nicegui.elements.tooltip import Tooltip  # type: ignore
from system_core.ui_nicegui.workbench import (
    WorkbenchAdapter,
    WorkbenchConfig,
    WorkbenchHandlers,
    WorkbenchRenderer,
    WorkbenchRole,
    WORKBENCH_FEEDBACK_CSS,
    WORKBENCH_LAYOUT_CSS,
    WORKBENCH_OVERRIDE_CSS,
    canonical_role,
)

AUDION_CANONICAL_TOOLTIP_DELAY_MS = 1500
AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS = 100
AUDION_CANONICAL_TOOLTIP_TRANSITION_MS = 100


def install_audion_canonical_tooltip_defaults() -> None:
    try:
        from nicegui.elements.tooltip import Tooltip as NiceGuiTooltip  # type: ignore
    except Exception:
        return
    if getattr(NiceGuiTooltip, "_audion_canonical_tooltip_defaults", False):
        return
    original_init = NiceGuiTooltip.__init__

    def audion_tooltip_init(self: Any, text: str = "") -> None:
        original_init(self, text)
        self.props["delay"] = AUDION_CANONICAL_TOOLTIP_DELAY_MS
        self.props["hide-delay"] = AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS
        self.props["transition-duration"] = AUDION_CANONICAL_TOOLTIP_TRANSITION_MS
        self.classes("audion-tooltip")

    NiceGuiTooltip.__init__ = audion_tooltip_init  # type: ignore[method-assign]
    NiceGuiTooltip._audion_canonical_tooltip_defaults = True  # type: ignore[attr-defined]


install_audion_canonical_tooltip_defaults()


AUDION_CANONICAL_UI_CSS = """
<style id="audion-canonical-tooltip-icon-style">
  html body .q-tooltip,
  html body .audion-tooltip {
    background: rgb(23, 33, 43) !important;
    background-color: rgb(23, 33, 43) !important;
    color: #f4f8fb !important;
    border: 1px solid rgba(88, 166, 255, 0.24) !important;
    border-radius: 8px !important;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.34) !important;
  }
  html body .q-icon.material-icons,
  html body .q-icon.material-symbols-outlined,
  html body .q-icon.material-symbols-rounded,
  html body i.material-icons,
  html body i.material-symbols-outlined,
  html body i.material-symbols-rounded,
  html body .q-btn .q-icon,
  html body .q-btn .material-icons,
  html body .q-btn .material-symbols-outlined,
  html body .q-btn .material-symbols-rounded,
  html body .q-field .q-field__append .q-icon,
  html body .q-field .q-field__prepend .q-icon,
  html body .q-item .q-icon,
  html body .q-menu .q-icon,
  html body .audion-label-icon,
  html body .audion-path-option-pin,
  html body .audion-select-option-pin {
    font-size: 14px !important;
    width: 14px !important;
    min-width: 14px !important;
    height: 14px !important;
    line-height: 14px !important;
  }
  html body .material-icons,
  html body .q-icon.material-icons {
    font-family: "Material Icons" !important;
  }
  html body .material-symbols-outlined,
  html body .q-icon.material-symbols-outlined {
    font-family: "Material Symbols Outlined" !important;
  }
  html body .material-symbols-rounded,
  html body .q-icon.material-symbols-rounded {
    font-family: "Material Symbols Rounded" !important;
  }
</style>
"""


def add_audion_canonical_ui_styles() -> None:
    ui.add_head_html(AUDION_CANONICAL_UI_CSS)



def audion_tooltip_path_text(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return str(path)
    except Exception:
        return raw


def audion_folder_button_tooltip(folder_id: str, path_value: Any) -> str:
    key = str(folder_id or "folder").strip().lower()
    path_text = audion_tooltip_path_text(path_value)
    if getattr(settings, "language", "ru") == "ru":
        descriptions = {
            "logs": "папку логов запусков и вывода терминала",
            "report": "папку отчётов и результатов операций",
            "reports": "папку отчётов и результатов операций",
            "config": "папку конфигурации проекта: manifest, GUI-настройки и кэши",
            "state": "папку рабочего состояния GUI",
            "project": "корневую папку проекта",
            "root": "корневую папку проекта",
            "data": "папку данных проекта",
            "pipeline": "папку pipeline-артефактов и промежуточных результатов",
            "github": "папку GitHub-артефактов проекта",
            "install": "папку install/runtime-артефактов проекта",
        }
        description = descriptions.get(key, f"папку {folder_id}")
        return f"Открыть {description}: {path_text}" if path_text else f"Открыть {description}."
    descriptions = {
        "logs": "the logs folder with run and terminal output",
        "report": "the reports/results folder",
        "reports": "the reports/results folder",
        "config": "the project config folder with manifest, GUI settings, and caches",
        "state": "the GUI state folder",
        "project": "the project root folder",
        "root": "the project root folder",
        "data": "the project data folder",
        "pipeline": "the pipeline artifacts and intermediate results folder",
        "github": "the project GitHub artifacts folder",
        "install": "the project install/runtime artifacts folder",
    }
    description = descriptions.get(key, f"the {folder_id} folder")
    return f"Open {description}: {path_text}" if path_text else f"Open {description}."


def audion_terminal_action_tooltip(action: str) -> str:
    key = str(action or "").strip().lower()
    if getattr(settings, "language", "ru") == "ru":
        tips = {
            "clear_terminal_window": "Очистить только видимое окно терминала. Файлы логов, отчёты и результаты операций не удаляются.",
            "expand": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "expand_log": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "pin_command": "Закрепить текущую команду в истории терминала для быстрого повторного запуска.",
            "unpin_command": "Открепить текущую команду от верхней части истории терминала.",
            "clear_history": "Очистить историю команд терминала. Закреплённые команды и файлы логов не удаляются.",
            "terminal_shell": "Выбрать оболочку, в которой будут запускаться команды терминала.",
            "terminal_history": "Выбрать ранее сохранённую или закреплённую команду терминала.",
            "terminal_command": "Команда, которая будет выполнена из выбранной рабочей папки.",
            "terminal_cwd": "Рабочая папка терминала. Команда будет запущена именно отсюда.",
            "pick_folder": "Выбрать рабочую папку терминала через системный диалог.",
            "terminal_run": "Запустить введённую команду в выбранной оболочке и рабочей папке.",
            "latest_report": "Открыть последний созданный отчёт, если он уже есть.",
            "command_preview": "Показать команду, которая будет запущена с текущими параметрами, без выполнения операции.",
            "report_view": "Открыть встроенный список отчётов без перехода в проводник.",
            "close": "Закрыть большое окно терминала и вернуться к основной панели.",
        }
    else:
        tips = {
            "clear_terminal_window": "Clear only the visible terminal window. Log files, reports, and operation results are not deleted.",
            "expand": "Open the terminal in a large window for reading long output comfortably.",
            "expand_log": "Open the terminal in a large window for reading long output comfortably.",
            "pin_command": "Pin the current terminal command for quick reuse.",
            "unpin_command": "Remove the current command from the pinned command list.",
            "clear_history": "Clear terminal command history. Pinned commands and log files are not deleted.",
            "terminal_shell": "Choose the shell used to run terminal commands.",
            "terminal_history": "Pick a saved or pinned terminal command.",
            "terminal_command": "Command to run from the selected working folder.",
            "terminal_cwd": "Terminal working folder. Commands are started from here.",
            "pick_folder": "Choose the terminal working folder with the system dialog.",
            "terminal_run": "Run the entered command in the selected shell and working folder.",
            "latest_report": "Open the latest generated report, if one exists.",
            "command_preview": "Show the command that would run with the current settings, without executing it.",
            "report_view": "Open the built-in reports list without switching to the file explorer.",
            "close": "Close the large terminal window and return to the main panel.",
        }
    return tips.get(key, key.replace("_", " ").strip())


from system_core.core.ansi import AnsiHtmlRenderer, terminal_html as _terminal_html, terminal_lines_html as _terminal_lines_html
from system_core.core.config import load_yaml_or_json
from system_core.core.jobs import execute_operation
from system_core.core.manifest import CommandNode, Operation, load_manifest
from system_core.core.paths import ensure_project_dirs, get_project_paths, open_folder
from system_core.core.ui_settings import load_ui_settings, save_ui_settings


paths = get_project_paths(ROOT)
ensure_project_dirs(paths)
manifest = load_manifest(paths.config / "tool_manifest.yaml")
settings_path = paths.config / "gui_settings.yaml"
settings = load_ui_settings(settings_path)
tool_info: dict[str, Any] = manifest.raw.get("tool", {})
ui_info: dict[str, Any] = manifest.raw.get("ui", {})
ROOT_COMMAND_PRIORITY = (
    "openai",
    "gemini",
    "xai",
    "anthropic",
    "task_openai",
    "task_gemini",
    "task_xai",
    "task_anthropic",
    "normalize_openai",
    "normalize_gemini",
    "normalize_xai",
    "normalize_anthropic",
    "doc_tasks",
    "specialized_commands",
    "rules",
)
ROOT_COMMAND_PRIORITY_INDEX = {node_id: index for index, node_id in enumerate(ROOT_COMMAND_PRIORITY)}

DEFAULT_THEME_ID = "code_dark"
THEME_ALIASES = {"dark": "code_dark", "light": "code_light"}
TOOLTIP_DELAY_MS = 1500


def enable_default_tooltip_delay() -> None:
    if getattr(Element, "_audion_tooltip_delay_ms", None) == TOOLTIP_DELAY_MS:
        return
    if not hasattr(Element, "_audion_original_tooltip"):
        setattr(Element, "_audion_original_tooltip", Element.tooltip)

    def tooltip_with_delay(self: Element, text: str) -> Element:
        tooltip_text = str(text or "").strip()
        if not tooltip_text:
            return self
        tooltip = Tooltip(tooltip_text)
        tooltip.props["target"] = f"#{self.html_id}"
        tooltip.props["delay"] = TOOLTIP_DELAY_MS
        return self

    Element.tooltip = tooltip_with_delay  # type: ignore[method-assign]
    setattr(Element, "_audion_tooltip_delay_ms", TOOLTIP_DELAY_MS)


enable_default_tooltip_delay()


def terminal_lines_html(lines, *, leading_newline: bool = False, renderer: AnsiHtmlRenderer | None = None) -> str:
    return _terminal_lines_html(lines, leading_newline=False, renderer=renderer).replace("\n", "")


def terminal_html(lines, *, renderer: AnsiHtmlRenderer | None = None, history_limit: int | None = None) -> str:
    return _terminal_html(lines, renderer=renderer, history_limit=history_limit).replace("\n", "")


def _string_map(value: Any) -> dict[str, str]:
    return {str(key).strip(): str(item).strip() for key, item in dict(value).items() if str(key).strip()} if isinstance(value, dict) else {}


def load_ui_colors(path: Path) -> dict[str, Any]:
    data = load_yaml_or_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}

    themes: dict[str, dict[str, Any]] = {}
    themes_raw = data.get("themes", {})
    if not isinstance(themes_raw, dict):
        themes_raw = {}

    for theme_id, theme_data in themes_raw.items():
        if not isinstance(theme_data, dict):
            continue
        normalized_id = str(theme_id).strip().lower()
        if not normalized_id:
            continue
        themes[normalized_id] = {
            "label": str(theme_data.get("label") or normalized_id).strip(),
            "label_ru": str(theme_data.get("label_ru") or theme_data.get("label") or normalized_id).strip(),
            "mode": "dark" if str(theme_data.get("mode", "dark")).lower() == "dark" else "light",
            "tokens": _string_map(theme_data.get("tokens", {})),
        }

    if DEFAULT_THEME_ID not in themes:
        themes[DEFAULT_THEME_ID] = {
            "label": "Code Dark",
            "label_ru": "Code Темная",
            "mode": "dark",
            "tokens": {
                "color-background-primary": "#141413",
                "color-background-secondary": "#1f1e1a",
                "color-background-tertiary": "#0f0f0e",
                "color-text-primary": "#faf9f5",
                "color-text-secondary": "#e8e6dc",
                "color-text-tertiary": "#b0aea5",
                "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
                "color-border-secondary": "rgba(250, 249, 245, 0.3)",
                "color-border-primary": "rgba(250, 249, 245, 0.4)",
                "color-accent-primary": "#d97757",
            },
        }

    return {
        "ramps": data.get("ramps", {}) if isinstance(data.get("ramps", {}), dict) else {},
        "tokens": _string_map(data.get("tokens", {})),
        "themes": themes,
    }


ui_colors = load_ui_colors(paths.config / "ui_colors.yaml")


def _workspace_history_file() -> Path:
    return paths.config / "path_history.json"


def _startup_workspace_path(role: str, configured: str, legacy: str, default_path: Path) -> str:
    return str(default_path)


def load_workspace_route_settings() -> tuple[str, str]:
    return (
        _startup_workspace_path("source", "", "", paths.input),
        _startup_workspace_path("target", "", "", paths.output),
    )


def _yaml_string(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _workspace_setting_for_disk(role: str, path_value: Any, default_path: Path) -> str:
    return ""


def display_path(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(ROOT)
    except (OSError, ValueError):
        return str(path)
    return str(relative) or "."

def save_app_settings() -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = _workspace_setting_for_disk("source", getattr(settings, "source_path", ""), paths.input)
    destination_path = _workspace_setting_for_disk("target", getattr(settings, "destination_path", ""), paths.output)
    text = (
        "gui:\n"
        "  # Change to \"en\" for public GitHub builds.\n"
        f"  language: \"{settings.language if settings.language in {'en', 'ru'} else 'ru'}\"\n"
        f"  theme: \"{normalize_theme_id(settings.theme)}\"\n"
        f"  emoji: {str(bool(getattr(settings, 'emoji', False))).lower()}\n"
        f"  allow_runtime_switching: {str(bool(getattr(settings, 'allow_runtime_switching', True))).lower()}\n"
        f"  advanced_open: {str(bool(getattr(settings, 'advanced_open', False))).lower()}\n"
        f"  source_path: {_yaml_string(source_path)}\n"
        f"  destination_path: {_yaml_string(destination_path)}\n"
    )
    settings_path.write_text(text, encoding="utf-8", newline="\n")

settings.source_path, settings.destination_path = load_workspace_route_settings()


def tolerate_missing_process_pool() -> None:
    """Keep NiceGUI alive when multiprocessing is blocked by the environment.

    NiceGUI initializes a process pool even when the GUI only uses thread/io-bound
    jobs. Some portable, sandboxed, or enterprise Windows environments reject the
    underlying multiprocessing handles, but the shell can still work without CPU
    pool tasks.
    """
    try:
        import nicegui.run as nicegui_run  # type: ignore
    except Exception:
        return

    original_setup = getattr(nicegui_run, "setup", None)
    if not callable(original_setup):
        return

    def safe_setup() -> None:
        try:
            original_setup()
        except (OSError, PermissionError) as exc:
            logging.warning("NiceGUI process pool disabled: %s", exc)
            nicegui_run.process_pool = None

    nicegui_run.setup = safe_setup


tolerate_missing_process_pool()

LABELS = {
    "ru": {
        "workspace": "Рабочие папки",
        "operations": "Операции",
        "maintenance": "Обслуживание",
        "status": "Статус",
        "log": "Журнал операции",
        "idle": "Ожидание",
        "running": "Выполняется",
        "done": "Готово",
        "error": "Ошибка",
        "cancel": "Отменить",
        "another_running": "Другая операция уже выполняется.",
        "confirm_title": "Подтвердите действие",
        "confirm_note": "Действие может изменить управляемую рабочую область.",
        "run": "Запустить",
        "back": "Назад",
        "selected_operation": "Выбрана команда",
        "open_menu": "Открыть",
        "parameters": "Параметры",
        "section_task": "Задача",
        "section_task_sources": "История и инструкции",
        "section_task_editor": "Окно TASK",
        "section_task_options": "Параметры TASK",
        "section_content": "Содержание",
        "section_provider": "Провайдер и модель",
        "section_files": "Файлы и пути",
        "section_generation": "Параметры запуска",
        "section_options": "Опции",
        "advanced": "Дополнительно",
        "actions": "Действия",
        "more_actions": "Ещё",
        "close": "Закрыть",
        "logs": "Журнал",
        "report": "Отчёт",
        "output": "Результат",
        "work": "Работа",
        "config": "Настройки",
        "tools": "Инструменты",
        "rules_short": "Правила",
        "expand": "Развернуть",
        "clear_terminal_window": "Очистить окно терминала",
        "add_files": "Добавить файлы...",
        "add_folder": "Добавить папку...",
        "source_folder": "Источник",
        "target_folder": "Назначение",
        "source_selected": "Источник выбран.",
        "target_selected": "Цель выбрана.",
        "source_folder_missing": "Источник не найден: {path}",
        "clear_io_short": "Сбросить",
        "delete_io_short": "Удалить",
        "path_required": "Выберите путь.",
        "path_pinned": "Путь закреплён.",
        "path_unpinned": "Путь откреплён.",
        "file_list": "File List",
        "file_list_button": "Список",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "picker_cancelled": "Выбор отменён.",
        "pick_file": "Выбрать файл...",
        "task_loaded": "Инструкция загружена в окно TASK.",
        "operation_done": "Операция завершена.",
        "operation_failed": "Операция завершилась с кодом {code}.",
        "select_required": "Выберите хотя бы один пункт: {field}",
        "refresh_options": "Обновить список",
        "refresh_model_names": "Обновить наименования",
        "reset_model_cache": "СБРОСИТЬ",
        "reset_model_cache_done": "Кэш моделей {provider} сброшен.",
        "pin_selected_model": "Добавить выбранную модель в избранное",
        "unpin_selected_model": "Снять выбранную модель из избранного",
        "pin_selected_key": "Добавить выбранный ключ в избранное",
        "unpin_selected_key": "Снять выбранный ключ из избранного",
        "add_api_key": "Добавить ключ",
        "delete_api_key": "Удалить ключ",
        "api_key_added": "Ключ добавлен.",
        "api_key_deleted": "Ключ удалён: {label}",
        "api_key_pinned": "Ключ закреплён.",
        "api_key_unpinned": "Ключ откреплён.",
        "model_pinned": "Модель закреплена.",
        "model_unpinned": "Модель откреплена.",
        "api_key_required": "Выберите ключ.",
        "model_required": "Выберите модель.",
        "api_key_label": "Метка",
        "api_key_value": "API-ключ",
        "api_key_value_placeholder": "Вставьте ключ или строку: Метка | ключ | комментарий",
        "api_key_note": "Комментарий",
        "confirm_delete_key": "Удалить выбранный API-ключ?",
        "delete_key_note": "Ключ будет удалён из локального файла. Убедитесь, что у вас есть копия.",
        "delete": "Удалить",
        "save": "Сохранить",
        "theme": "Тема",
        "theme_saved": "Тема сохранена. Перезагружаю интерфейс.",
        "lang_switch": "EN",
        "resize_panels": "Изменить ширину панелей",
    },
    "en": {
        "workspace": "Workspace folders",
        "operations": "Operations",
        "maintenance": "Maintenance",
        "status": "Status",
        "log": "Operation log",
        "idle": "Idle",
        "running": "Running",
        "done": "Done",
        "error": "Error",
        "cancel": "Cancel",
        "another_running": "Another operation is already running.",
        "confirm_title": "Confirm action",
        "confirm_note": "This action may change the managed workspace.",
        "run": "Run",
        "back": "Back",
        "selected_operation": "Selected command",
        "open_menu": "Open",
        "parameters": "Parameters",
        "section_task": "Task",
        "section_task_sources": "History and instructions",
        "section_task_editor": "TASK editor",
        "section_task_options": "TASK options",
        "section_content": "Contents",
        "section_provider": "Provider and model",
        "section_files": "Files and paths",
        "section_generation": "Run parameters",
        "section_options": "Options",
        "advanced": "Advanced",
        "actions": "Actions",
        "more_actions": "More",
        "close": "Close",
        "logs": "Logs",
        "report": "Report",
        "output": "OUTPUT",
        "work": "WORK",
        "config": "CONFIG",
        "tools": "TOOLS",
        "rules_short": "RULES",
        "expand": "Expand",
        "clear_terminal_window": "Clear terminal window",
        "add_files": "Add files...",
        "add_folder": "Add folder...",
        "source_folder": "Source",
        "target_folder": "Target",
        "source_selected": "Source selected.",
        "target_selected": "Target selected.",
        "source_folder_missing": "Source was not found: {path}",
        "clear_io_short": "Reset",
        "delete_io_short": "Delete",
        "path_required": "Choose a path.",
        "path_pinned": "Path pinned.",
        "path_unpinned": "Path unpinned.",
        "file_list": "File List",
        "file_list_button": "List",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "picker_cancelled": "Selection cancelled.",
        "pick_file": "Pick file...",
        "task_loaded": "Instruction loaded into the TASK editor.",
        "operation_done": "Operation finished.",
        "operation_failed": "Operation finished with exit code {code}.",
        "select_required": "Select at least one item: {field}",
        "refresh_options": "Refresh list",
        "refresh_model_names": "Refresh model names",
        "reset_model_cache": "RESET",
        "reset_model_cache_done": "{provider} model cache was reset.",
        "pin_selected_model": "Add selected model to favorites",
        "unpin_selected_model": "Remove selected model from favorites",
        "pin_selected_key": "Add selected key to favorites",
        "unpin_selected_key": "Remove selected key from favorites",
        "add_api_key": "Add key",
        "delete_api_key": "Delete key",
        "api_key_added": "Key added.",
        "api_key_deleted": "Key deleted: {label}",
        "api_key_pinned": "Key pinned.",
        "api_key_unpinned": "Key unpinned.",
        "model_pinned": "Model pinned.",
        "model_unpinned": "Model unpinned.",
        "api_key_required": "Choose a key.",
        "model_required": "Choose a model.",
        "api_key_label": "Label",
        "api_key_value": "API key",
        "api_key_value_placeholder": "Paste a key or a line: Label | key | note",
        "api_key_note": "Note",
        "confirm_delete_key": "Delete the selected API key?",
        "delete_key_note": "The key will be removed from the local file. Make sure you have a copy.",
        "delete": "Delete",
        "save": "Save",
        "theme": "Theme",
        "theme_saved": "Theme saved. Reloading UI.",
        "lang_switch": "RU",
        "resize_panels": "Resize panels",
    },
}

PICKER_BOOTSTRAP = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AudionDpiAwareness {
  [DllImport("user32.dll")]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("shcore.dll")]
  public static extern int SetProcessDpiAwareness(int value);
}
"@
  try { [AudionDpiAwareness]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
  catch { [AudionDpiAwareness]::SetProcessDpiAwareness(2) | Out-Null }
} catch {}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
"""

state: dict[str, Any] = {
    "running": False,
    "cancel": False,
    "progress": 0.0,
    "status": "",
    "lines": [],
    "line_seq": 0,
    "terminal_generation": 0,
    "terminal_scroll_top_seq": 0,
    "log_version": 0,
    "exit_code": None,
    "command_path": [],
    "pending_command": None,
    "field_values": {},
    "source_path": str(getattr(settings, "source_path", "") or ""),
    "destination_path": str(getattr(settings, "destination_path", "") or ""),
    "workspace_feedback": {},
}

PATH_HISTORY_LIMIT = 100
TERMINAL_HISTORY_LIMIT = 2000

dynamic_option_cache: dict[str, tuple[float, list[Any]]] = {}
MODEL_OPTION_SOURCES = {
    "openai": "system_core.services.audion_docs_service:openai_model_options",
    "gemini": "system_core.services.audion_docs_service:gemini_model_options",
    "xai": "system_core.services.audion_docs_service:xai_model_options",
    "anthropic": "system_core.services.audion_docs_service:anthropic_model_options",
}
API_KEY_OPTION_SOURCES = {
    "openai": "system_core.services.audion_docs_service:openai_api_key_options",
    "gemini": "system_core.services.audion_docs_service:gemini_api_key_options",
    "xai": "system_core.services.audion_docs_service:xai_api_key_options",
    "anthropic": "system_core.services.audion_docs_service:anthropic_api_key_options",
}
TASK_OPTION_SOURCES = {
    "system_core.services.audion_docs_service:doc_task_options",
    "system_core.services.audion_docs_service:quick_doc_task_options",
}


def tr(key: str, **kwargs: Any) -> str:
    lang = settings.language if settings.language in LABELS else "en"
    text = LABELS.get(lang, LABELS["en"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def api_key_placeholder(provider: str) -> str:
    prefix = {
        "openai": "sk-...",
        "gemini": "AIza...",
        "xai": "xai-...",
        "anthropic": "sk-ant-...",
    }.get(str(provider or "").strip().lower(), "API key")
    return f"{tr('api_key_value_placeholder')} ({prefix})"


def em(key: str) -> str:
    if not bool(getattr(settings, "emoji", False)):
        return ""
    return {
        "workspace": "📁 ",
        "operations": "⚙ ",
        "maintenance": "🧰 ",
        "status": "● ",
        "log": "🖥 ",
    }.get(key, "")


def app_title() -> str:
    title = str(ui_info.get("title") or tool_info.get("name") or "Audion GUI Tool")
    for suffix in (" UI", " v3"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title


def normalize_theme_id(theme_id: Any) -> str:
    text = str(theme_id or DEFAULT_THEME_ID).strip().lower()
    cleaned = "".join(char for char in text if char.isalnum() or char in {"_", "-"})
    return THEME_ALIASES.get(cleaned, cleaned)


def active_theme() -> str:
    theme_id = normalize_theme_id(settings.theme)
    themes = ui_colors["themes"]
    if theme_id in themes:
        return theme_id
    return DEFAULT_THEME_ID if DEFAULT_THEME_ID in themes else next(iter(themes))


def active_theme_data() -> dict[str, Any]:
    return dict(ui_colors["themes"][active_theme()])


def active_theme_mode() -> str:
    return str(active_theme_data().get("mode", "dark"))


def theme_label(theme_id: str) -> str:
    theme_data = ui_colors["themes"].get(theme_id, {})
    label_key = "label_ru" if settings.language == "ru" else "label"
    return str(theme_data.get(label_key) or theme_data.get("label") or theme_id)


def theme_options() -> dict[str, str]:
    return {theme_id: theme_label(theme_id) for theme_id in ui_colors["themes"]}


def set_theme(theme_id: Any) -> None:
    selected = normalize_theme_id(theme_id)
    if selected not in ui_colors["themes"]:
        return
    settings.theme = selected
    save_app_settings()
    safe_notify(tr("theme_saved"), "positive")
    reload_ui()


def theme_change_handler(event: Any) -> None:
    set_theme(getattr(event, "value", None))

def reload_ui() -> None:
    ui.run_javascript(
        """
        (() => {
          try {
            if ('scrollRestoration' in window.history) {
              window.history.scrollRestoration = 'manual';
            }
            window.sessionStorage.setItem('audion_force_scroll_top', '1');
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
          } catch (error) {}
          window.location.reload();
        })();
        """
    )

def theme_variables() -> dict[str, str]:
    variables: dict[str, str] = {}
    for ramp_name, stops in ui_colors["ramps"].items():
        if not isinstance(stops, dict):
            continue
        for stop, color in stops.items():
            variables[f"color-{ramp_name}-{stop}"] = str(color).strip()
    variables.update(ui_colors["tokens"])
    variables.update(_string_map(active_theme_data().get("tokens", {})))
    variables.setdefault("color-background-primary", "#111827")
    variables.setdefault("color-background-secondary", "#172033")
    variables.setdefault("color-background-tertiary", "#0b1020")
    variables.setdefault("color-text-primary", "#f8fafc")
    variables.setdefault("color-text-secondary", "#d7dee9")
    variables.setdefault("color-text-tertiary", "#95a3b8")
    variables.setdefault("color-border-tertiary", "rgba(215, 222, 233, 0.15)")
    variables.setdefault("color-border-secondary", "rgba(215, 222, 233, 0.32)")
    variables.setdefault("color-border-primary", "rgba(215, 222, 233, 0.44)")
    variables.setdefault("color-accent-primary", "#5da8ff")
    variables.setdefault("color-accent-secondary", "#2fbf9f")
    variables.setdefault("color-accent-tertiary", "#f28f5b")
    variables.setdefault("font-sans", "Inter, Segoe UI, Arial, sans-serif")
    variables.setdefault("font-mono", "Cascadia Mono, Consolas, monospace")
    variables.setdefault("border-radius-md", "8px")
    variables.setdefault("border-radius-lg", "12px")
    return variables


def add_log(message: str) -> None:
    if not str(message).strip():
        return
    state["lines"].append(str(message).rstrip())
    state["lines"] = state["lines"][-TERMINAL_HISTORY_LIMIT:]
    state["line_seq"] = int(state.get("line_seq", 0)) + 1
    state["log_version"] = int(state["log_version"]) + 1


def clear_terminal_log() -> None:
    state["lines"] = []
    state.update(terminal_reset_marker())
    state["terminal_scroll_top_seq"] = 0
    state["log_version"] = int(state["log_version"]) + 1


def terminal_reset_marker() -> dict[str, int]:
    return {
        "line_seq": 0,
        "terminal_generation": int(state.get("terminal_generation", 0)) + 1,
    }


def progress_text() -> str:
    return f"{round(max(0.0, min(1.0, float(state['progress']))) * 100):.0f}%"


def safe_notify(message: str, kind: str = "info", **notify_kwargs: Any) -> None:
    notify_type = str(notify_kwargs.pop("type", kind))
    options = {"message": str(message), "type": notify_type, **notify_kwargs}
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        try:
            client.outbox.enqueue_message("notify", options, client.id)
            delivered = True
        except Exception as exc:
            logging.warning("NiceGUI notification delivery failed for client %s: %s", getattr(client, "id", "?"), exc)
    if delivered:
        return

    try:
        ui.notify(message, type=notify_type, **notify_kwargs)
    except RuntimeError as exc:
        message_text = str(exc)
        if "slot belongs to has been deleted" not in message_text and "current slot cannot be determined" not in message_text:
            raise
        logging.warning("NiceGUI notification skipped because no live client slot was available: %s", message)


RUN_STATE_LABELS = {
    "idle": ("idle", "audion-status-idle"),
    "running": ("running", "audion-status-running"),
    "done": ("done", "audion-status-done"),
    "error": ("error", "audion-status-error"),
}


def run_state() -> str:
    """Which of the four states the panel is showing.

    Colour carries this everywhere it appears, so it is decided once.
    """
    if bool(state["running"]):
        return "running"
    exit_code = state.get("exit_code")
    if exit_code is None:
        return "idle"
    return "done" if int(exit_code or 0) == 0 else "error"


def status_row_classes() -> str:
    return f"audion-status-row {RUN_STATE_LABELS[run_state()][1]}"


def status_state_text() -> str:
    return tr(RUN_STATE_LABELS[run_state()][0]).upper()


def elapsed_text(seconds: float | None) -> str:
    """A run's own clock, mm:ss, or an em dash before anything has run.

    The start is noticed by the refresh timer rather than written by the code that
    starts a run: there are several such places, and none of them has to know
    about the panel.
    """
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def status_dot_classes() -> str:
    base = "audion-status-dot text-lg leading-none"
    if bool(state["running"]):
        return f"{base} text-sky-400 animate-pulse"
    if state.get("exit_code") is None:
        return f"{base} text-gray-500"
    if int(state.get("exit_code") or 0) == 0:
        return f"{base} text-green-400"
    return f"{base} text-red-400"


def set_progress(value: float) -> None:
    state["progress"] = max(0.0, min(1.0, float(value)))


def cancel_requested() -> bool:
    return bool(state["cancel"])


def hidden_subprocess_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def hidden_subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    flags = hidden_subprocess_flags()
    startupinfo = hidden_subprocess_startupinfo()
    if flags:
        kwargs["creationflags"] = flags
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def resolve_dialog_powershell() -> list[str]:
    candidates = [
        [str(paths.system_core / "powershell" / "pwsh.exe"), "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"],
    ]
    for candidate in candidates:
        exe = candidate[0]
        if Path(exe).exists() or shutil.which(exe):
            return candidate
    raise RuntimeError("PowerShell was not found for Windows picker.")


def parse_picker_paths(text: str) -> list[Path]:
    import json

    payload = text.strip()
    if not payload:
        return []
    data = json.loads(payload)
    if isinstance(data, str):
        data = [data]
    return [Path(str(item)).resolve() for item in data if str(item).strip()]


_PICKER_RUN_LOCK = threading.Lock()
_PICKER_JOB_LOCK = threading.Lock()
_PICKER_SHUTDOWN = threading.Event()
_PICKER_JOB_HANDLE: int | None = None


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def close_picker_job() -> None:
    global _PICKER_JOB_HANDLE
    _PICKER_SHUTDOWN.set()
    with _PICKER_JOB_LOCK:
        handle = _PICKER_JOB_HANDLE
        _PICKER_JOB_HANDLE = None
    if os.name == "nt" and handle:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(handle))


def _picker_job_handle() -> int | None:
    global _PICKER_JOB_HANDLE
    if os.name != "nt" or _PICKER_SHUTDOWN.is_set():
        return None
    with _PICKER_JOB_LOCK:
        if _PICKER_SHUTDOWN.is_set():
            return None
        if _PICKER_JOB_HANDLE:
            return _PICKER_JOB_HANDLE
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logging.warning("Could not create the Windows picker job: %s", ctypes.get_last_error())
            return None
        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            logging.warning("Could not configure the Windows picker job: %s", error)
            return None
        _PICKER_JOB_HANDLE = int(job)
        return _PICKER_JOB_HANDLE


def _assign_picker_to_job(process: subprocess.Popen[str]) -> None:
    handle = _picker_job_handle()
    if os.name != "nt" or not handle:
        if _PICKER_SHUTDOWN.is_set() and process.poll() is None:
            process.kill()
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(handle),
        wintypes.HANDLE(int(process._handle)),  # type: ignore[attr-defined]
    ):
        logging.warning("Could not attach picker PID %s to its Windows job: %s", process.pid, ctypes.get_last_error())


def run_picker_script(script: str, error_message: str) -> list[Path]:
    if not _PICKER_RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("A Windows picker is already open.")
    process: subprocess.Popen[str] | None = None
    try:
        if _PICKER_SHUTDOWN.is_set():
            raise RuntimeError("Windows picker supervisor is shutting down.")
        _picker_job_handle()
        process = subprocess.Popen(
            [*resolve_dialog_powershell(), script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        _assign_picker_to_job(process)
        if _PICKER_SHUTDOWN.is_set():
            if process.poll() is None:
                process.kill()
            raise RuntimeError("Windows picker supervisor is shutting down.")
        try:
            stdout, stderr = process.communicate(timeout=3600)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeError("Windows picker timed out.") from exc
        if process.returncode != 0:
            raise RuntimeError(stderr.strip() or error_message)
        return parse_picker_paths(stdout)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _PICKER_RUN_LOCK.release()


atexit.register(close_picker_job)
nicegui_app.on_shutdown(close_picker_job)

def pick_single_file(title: str = "Select file", file_filter: str = "Markdown files|*.md|Text files|*.txt|All files|*.*") -> Path | None:
    safe_title = title.replace("'", "''")
    safe_filter = file_filter.replace("'", "''")
    script = PICKER_BOOTSTRAP + f"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '{safe_title}'
$dialog.Multiselect = $false
$dialog.Filter = '{safe_filter}'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  @($dialog.FileName) | ConvertTo-Json -Compress
}}
"""
    paths_selected = run_picker_script(script, "File picker failed.")
    return paths_selected[0] if paths_selected else None


def pick_folder() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Add folder to input'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}
"""
    return run_picker_script(script, "Folder picker failed.")

def absolute_project_path(path_value: Any) -> Path:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def remove_path_tree(path: Path) -> int:
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    if path.is_symlink() or is_junction:
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
        return 1
    if path.is_file():
        path.unlink()
        return 1
    if path.is_dir():
        shutil.rmtree(path)
        return 1
    return 0


def clear_directory_contents(folder: Path) -> int:
    removed = 0
    if not folder.exists():
        return removed
    for child in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        # .gitkeep is not spared: input and output must be genuinely empty after
        # a clear, so nobody has to wonder what the leftover file is or whether it
        # is safe to delete. The folders come from install/init_folders.cmd.
        removed += remove_path_tree(child)
    return removed


def normalized_absolute_path(path_value: Any) -> Path:
    return absolute_project_path(path_value).resolve(strict=False)


def paths_equal(left: Any, right: Any) -> bool:
    return os.path.normcase(str(normalized_absolute_path(left))) == os.path.normcase(str(normalized_absolute_path(right)))


def validate_workspace_delete_target(path_value: Any) -> Path:
    target = normalized_absolute_path(path_value)
    if target.parent == target:
        raise RuntimeError(f"Refusing to delete a filesystem root: {target}")
    if paths_equal(target, ROOT):
        raise RuntimeError(f"Refusing to delete the project root: {target}")
    return target


def delete_workspace_path_contents(path_value: Any) -> dict[str, Any]:
    target = validate_workspace_delete_target(path_value)
    if not target.exists() and not target.is_symlink():
        return {"path": str(target), "kind": "missing", "removed": 0}
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(target))
    if target.is_file() or target.is_symlink() or is_junction:
        return {"path": str(target), "kind": "file", "removed": remove_path_tree(target)}
    if not target.is_dir():
        raise RuntimeError(f"Unsupported workspace path: {target}")
    return {"path": str(target), "kind": "folder", "removed": clear_directory_contents(target)}


def delete_workspace_io_contents(source: Path, target: Path) -> dict[str, Any]:
    source_result = delete_workspace_path_contents(source)
    target_result = (
        {"path": str(normalized_absolute_path(target)), "kind": "same", "removed": 0}
        if paths_equal(source, target)
        else delete_workspace_path_contents(target)
    )
    return {"source": source_result, "target": target_result}

def input_file_list_lines(source: Path) -> list[str]:
    if not source.exists():
        return [tr("file_list_missing", path=source)]
    if source.is_file():
        return [" No.  List", "----  ----", f"001. {source.name}"]
    if not source.is_dir():
        return [f"SOURCE is not a file or folder: {source}"]

    names = sorted(
        (path.name for path in source.rglob("*") if path.is_file()),
        key=lambda item: item.casefold(),
    )
    if not names:
        return [tr("file_list_empty")]

    number_width = max(3, len(str(len(names))))
    lines = [
        f"{'No.':>{number_width}}  List",
        f"{'-' * number_width}  ----",
    ]
    lines.extend(f"{index:0{number_width}d}. {name}" for index, name in enumerate(names, start=1))
    return lines


async def show_input_file_list() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {tr('file_list')}",
            "lines": [],
            **terminal_reset_marker(),
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    try:
        lines = await run.io_bound(input_file_list_lines, current_source_path())
        for line in lines:
            add_log(line)
        count = max(0, len(lines) - 2)
        state["terminal_scroll_top_seq"] = int(state.get("line_seq", 0))
        state["exit_code"] = 0
        state["progress"] = 1.0
        state["status"] = f"{tr('done')}: {tr('file_list')} [{count}]"
        safe_notify(tr("file_list_ready", count=count), "positive")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False

async def start_operation(operation: Operation) -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    if operation.kind == "dangerous":
        with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
            ui.label(tr("confirm_title")).classes("text-base font-semibold")
            ui.label(operation.display_description(settings.language)).classes("text-sm text-gray-400")
            ui.label(tr("confirm_note")).classes("text-xs text-gray-500")
            with ui.row().classes("gap-2"):
                attach_tooltip(ui.button(tr("cancel"), on_click=dialog.close).props("dense flat"), tr("cancel"))
                attach_tooltip(ui.button(tr("run"), on_click=lambda: dialog.submit(True)).props("dense color=negative"), tr("run"))
        confirmed = await dialog
        if not confirmed:
            return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {operation.display_title(settings.language)}",
            "lines": [],
            **terminal_reset_marker(),
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    started = time.perf_counter()
    try:
        result = await run.io_bound(
            execute_operation,
            active_project_paths(),
            operation,
            add_log,
            set_progress,
            cancel_requested,
        )
        elapsed = time.perf_counter() - started
        state["exit_code"] = 0 if result.ok else 1
        state["progress"] = 1.0
        state["status"] = f"{tr('done') if result.ok else tr('error')}: {operation.display_title(settings.language)} [{state['exit_code']}] {elapsed:.1f}s"
        safe_notify(result.message, "positive" if result.ok else "negative")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False
        refresh_model_options_after_operation(operation)
        refresh_task_options_after_operation(operation)


def toggle_language() -> None:
    settings.language = "en" if settings.language == "ru" else "ru"
    save_app_settings()
    reload_ui()


def save_advanced_open(event: Any) -> None:
    settings.advanced_open = bool(getattr(event, "value", False))
    save_app_settings()


def current_source_path() -> Path:
    return Path(str(state.get("source_path") or getattr(settings, "source_path", "") or paths.input)).expanduser()


def current_target_path() -> Path:
    return Path(str(state.get("destination_path") or getattr(settings, "destination_path", "") or paths.output)).expanduser()


def active_project_paths():
    return replace(
        paths,
        input=current_source_path().resolve(strict=False),
        output=current_target_path().resolve(strict=False),
    )


def save_workspace_path(kind: str, value: Any) -> None:
    text = str(value or "").strip()
    if kind == "source":
        settings.source_path = text
        state["source_path"] = text
    elif kind == "destination":
        settings.destination_path = text
        state["destination_path"] = text
    else:
        raise RuntimeError(f"Unsupported workspace path kind: {kind}")
    dynamic_option_cache.clear()
    save_app_settings()


def open_workspace_folder(role: str) -> None:
    folder = current_target_path() if role == "target" else current_source_path()
    if role != "target" and not folder.exists():
        raise FileNotFoundError(tr("source_folder_missing", path=folder))
    if folder.is_file():
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", f"/select,{folder}"], **hidden_subprocess_kwargs())
        else:
            open_folder(folder.parent)
        return
    open_folder(folder)


def mark_workspace_feedback(role: str, action: str) -> None:
    state["workspace_feedback"] = {"role": canonical_role(role), "action": str(action or "path")}


def _save_workspace_adapter_path(role: WorkbenchRole, value: Any) -> None:
    save_workspace_path("destination" if role == "target" else "source", value)


def _workspace_feedback() -> dict[str, str]:
    value = state.get("workspace_feedback")
    return dict(value) if isinstance(value, dict) else {}


def _clear_workspace_feedback() -> None:
    state["workspace_feedback"] = {}


WORKBENCH_CONFIG = WorkbenchConfig(
    root=ROOT,
    input_path=paths.input,
    output_path=paths.output,
    history_path=_workspace_history_file(),
    history_limit=PATH_HISTORY_LIMIT,
)
WORKBENCH_ADAPTER = WorkbenchAdapter(
    config=WORKBENCH_CONFIG,
    current_path_callback=lambda role: current_target_path() if role == "target" else current_source_path(),
    save_path_callback=_save_workspace_adapter_path,
    language_callback=lambda: settings.language,
    translate_callback=tr,
    log_callback=add_log,
    notify_callback=safe_notify,
    reload_callback=reload_ui,
    busy_callback=lambda: bool(state.get("running")),
    feedback_callback=_workspace_feedback,
    set_feedback_callback=mark_workspace_feedback,
    clear_feedback_callback=_clear_workspace_feedback,
)
WORKBENCH_ADAPTER.validate()
WORKBENCH_ADAPTER.ensure_initial_history()


def workspace_pin_click_handler(role: str, pinned: bool):
    async def handler() -> None:
        path_value = str(current_target_path() if role == "target" else current_source_path())
        if not path_value:
            safe_notify(tr("path_required"), "warning")
            return
        try:
            await run.io_bound(WORKBENCH_ADAPTER.set_path_pinned, role, path_value, pinned)
            mark_workspace_feedback(role, "pin" if pinned else "unpin")
            add_log(f"{'Pinned' if pinned else 'Unpinned'} {role} path: {path_value}")
            reload_ui()
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_delete_path_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        path = current_target_path() if role == "target" else current_source_path()
        path_value = str(path)
        external_source = role != "target" and not paths_equal(path, paths.input)
        if external_source:
            with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
                is_file = path.is_file()
                ui.label(
                    ("Удалить исходный файл?" if is_file else "Очистить внешний ИСТОЧНИК?")
                    if settings.language == "ru"
                    else ("Delete the source file?" if is_file else "Clear the external SOURCE?")
                ).classes("text-base font-semibold")
                ui.label(str(normalized_absolute_path(path))).classes("max-w-3xl break-all font-mono text-xs text-gray-400")
                with ui.row().classes("gap-2"):
                    ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                    ui.button(tr("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
            if not await dialog:
                return
        if not path_value:
            safe_notify(tr("path_required"), "warning")
            return
        try:
            result = await run.io_bound(delete_workspace_path_contents, path)
            if result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, role, path_value)
                save_workspace_path("destination" if role == "target" else "source", "")
            mark_workspace_feedback(role, "delete")
            add_log(f"Cleared {role.upper()}: {result.get('path')} [kind={result.get('kind')}, removed={result.get('removed', 0)}]")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_open_click_handler(role: str):
    async def handler() -> None:
        try:
            await run.io_bound(open_workspace_folder, role)
            add_log(f"Opened {'target' if role == 'target' else 'source'} folder: {current_target_path() if role == 'target' else current_source_path()}")
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def reset_workspace_paths_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        result = await run.io_bound(WORKBENCH_ADAPTER.clear_path_history_cache_keep_pins)
        save_workspace_path("source", "")
        save_workspace_path("destination", "")
        add_log(f"Workspace route reset: SOURCE -> {paths.input}")
        add_log(f"Workspace route reset: TARGET -> {paths.output}")
        add_log(
            "Workspace path cache cleared: "
            f"sources={result.get('removed_sources', 0)}, targets={result.get('removed_targets', 0)}, "
            f"pins kept={result.get('kept_pins', 0)}"
        )
        safe_notify(tr("operation_done"), "positive")
        reload_ui()

    return handler


def decorate_model_select_option_props(select: Any, provider: str) -> None:
    try:
        from system_core.services.audion_docs_service import pinned_model_refs

        pinned_values = set(pinned_model_refs(provider))
    except Exception:
        pinned_values = set()
    values = list(getattr(select, "_values", []))
    pinned_indices = [index for index, value in enumerate(values) if str(value) in pinned_values]
    pinned_indices_json = json.dumps(pinned_indices)
    select.add_slot(
        "option",
        f"""
        <q-item
          v-bind="props.itemProps"
          dense
          :class="['audion-model-option-item', {pinned_indices_json}.includes(Number(props.opt.value)) ? 'audion-model-option-pinned' : '']"
        >
          <q-item-section avatar class="audion-model-option-pin-cell">
            <q-icon v-if="{pinned_indices_json}.includes(Number(props.opt.value))" name="push_pin" class="audion-model-option-pin"></q-icon>
          </q-item-section>
          <q-item-section>
            <q-item-label class="audion-model-option-label">{{{{ props.opt.label || props.opt.value }}}}</q-item-label>
          </q-item-section>
        </q-item>
        """,
    )


def workspace_path_select_handler(role: str):
    async def handler(event: Any) -> None:
        path_value = str(getattr(event, "value", "") or "").strip()
        if not path_value:
            return
        save_workspace_path("destination" if role == "target" else "source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, path_value)
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {path_value}")
        reload_ui()

    return handler


def workspace_pick_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_folder)
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        save_workspace_path("destination" if role == "target" else "source", str(selected[0]))
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, str(selected[0]))
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {selected[0]}")
        safe_notify(tr("target_selected") if role == "target" else tr("source_selected"), "positive")
        reload_ui()

    return handler


def workspace_single_file_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_single_file, "Select source document", "Documents|*.docx;*.pptx;*.xlsx;*.pdf|All files|*.*")
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected)
        save_workspace_path("source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, "source", path_value)
        mark_workspace_feedback("source", "path")
        add_log(f"SOURCE FILE -> {path_value}")
        reload_ui(150)

    return handler


def workspace_delete_both_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        source = current_source_path()
        target = current_target_path()
        with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
            ui.label("Удалить содержимое I/O?" if settings.language == "ru" else "Delete I/O contents?").classes("text-base font-semibold")
            ui.label(
                "Будут удалены файлы ИСТОЧНИКА и НАЗНАЧЕНИЯ. Внешний ИСТОЧНИК может быть единственным экземпляром."
                if settings.language == "ru"
                else "SOURCE and TARGET files will be deleted. The external SOURCE may be the only copy."
            ).classes("text-sm text-gray-300")
            ui.label(f"SOURCE: {normalized_absolute_path(source)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            ui.label(f"TARGET: {normalized_absolute_path(target)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            with ui.row().classes("gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                ui.button(tr("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
        if not await dialog:
            return
        state["running"] = True
        try:
            result = await run.io_bound(delete_workspace_io_contents, source, target)
            for role, path in (("source", source), ("target", target)):
                role_result = result.get(role, {})
                if role_result.get("kind") == "file":
                    await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, role, str(path))
                    save_workspace_path("destination" if role == "target" else "source", "")
                add_log(f"Cleared {role.upper()}: {role_result.get('path')} [kind={role_result.get('kind')}, removed={role_result.get('removed', 0)}]")
            mark_workspace_feedback("source", "delete")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
        finally:
            state["running"] = False

    return handler


WORKBENCH_RENDERER = WorkbenchRenderer(
    adapter=WORKBENCH_ADAPTER,
    handlers=WorkbenchHandlers(
        delete_path=workspace_delete_path_click_handler,
        pin_path=workspace_pin_click_handler,
        select_path=workspace_path_select_handler,
        pick_path=workspace_pick_click_handler,
        open_path=workspace_open_click_handler,
        add_file=workspace_single_file_click_handler,
        reset_paths=reset_workspace_paths_click_handler,
        delete_io=workspace_delete_both_click_handler,
        list_files=show_input_file_list,
    ),
    display_path_callback=display_path,
)

def operation_button(operation: Operation) -> None:
    with ui.element("div").classes("audion-operation-row"):
        button = ui.button(
            operation.display_title(settings.language),
            on_click=operation_click_handler(operation),
        ).props("dense flat no-wrap").classes("audion-action audion-operation-button audion-direct-action rounded-lg")
        attach_tooltip(button, operation.display_description(settings.language) or operation.display_title(settings.language))
        ui.label(operation.display_description(settings.language)).classes("audion-operation-description")


def operation_click_handler(operation: Operation):
    async def handler() -> None:
        await start_operation(operation)

    return handler


def localized_action_value(action: dict[str, Any], key: str) -> str:
    if settings.language == "ru" and action.get(f"{key}_ru"):
        return str(action.get(f"{key}_ru") or "")
    return str(action.get(key) or action.get("label") or action.get("title") or action.get("id") or "")


def field_action_operation(field: dict[str, Any], action: dict[str, Any]) -> Operation:
    parameters = dict(action.get("parameters") or {})
    values = state.setdefault("field_values", {})
    include_fields = action.get("include_fields")
    if not isinstance(include_fields, list):
        include_fields = field.get("include_fields")
    if isinstance(include_fields, list):
        for item_key in include_fields:
            key = str(item_key or "").strip()
            if key:
                parameters[key] = values.get(key, "")
    else:
        parameters.update(values)
    parameters.setdefault("source_dir", str(current_source_path()))
    parameters.setdefault("target_dir", str(current_target_path()))
    return Operation(
        id=str(action.get("id") or parameters.get("mode") or field_id(field)).strip(),
        title=str(action.get("label") or action.get("title") or action.get("id") or "").strip(),
        title_ru=str(action.get("label_ru") or action.get("title_ru") or "").strip(),
        description=str(action.get("tooltip") or action.get("description") or "").strip(),
        description_ru=str(action.get("tooltip_ru") or action.get("description_ru") or "").strip(),
        service=str(action.get("service") or "").strip(),
        kind=str(action.get("kind") or "safe").strip() or "safe",
        parameters=parameters,
    )


def field_action_click_handler(field: dict[str, Any], action: dict[str, Any]):
    async def handler() -> None:
        await start_operation(field_action_operation(field, action))

    return handler

def operation_to_command_node(operation: Operation) -> CommandNode:
    return CommandNode(
        id=operation.id,
        title=operation.title,
        description=operation.description,
        service=operation.service,
        kind=operation.kind,
        title_ru=operation.title_ru,
        description_ru=operation.description_ru,
        parameters=dict(operation.parameters),
        fields=operation.fields,
    )


def root_command_nodes() -> list[CommandNode]:
    if manifest.operation_groups:
        indexed_nodes = list(enumerate(manifest.operation_groups))
        original_index = {node.id: index for index, node in indexed_nodes}
        nodes = [
            node
            for _, node in sorted(
                indexed_nodes,
                key=lambda item: (
                    ROOT_COMMAND_PRIORITY_INDEX.get(item[1].id, len(ROOT_COMMAND_PRIORITY) + item[0]),
                    item[0],
                ),
            )
        ]
        return sorted(
            nodes,
            key=lambda node: (
                ROOT_COMMAND_PRIORITY_INDEX.get(node.id, len(ROOT_COMMAND_PRIORITY)),
                original_index.get(node.id, len(indexed_nodes)),
            ),
        )
    return [operation_to_command_node(operation) for operation in manifest.operations]


def visible_command_children(node: CommandNode) -> list[CommandNode]:
    return list(node.children)


def current_command_level() -> tuple[list[CommandNode], list[CommandNode]]:
    trail: list[CommandNode] = []
    nodes = root_command_nodes()
    for node_id in list(state.get("command_path", [])):
        node = next((candidate for candidate in nodes if candidate.id == node_id), None)
        if node is None:
            state["command_path"] = []
            state["pending_command"] = None
            return [], root_command_nodes()
        trail.append(node)
        nodes = visible_command_children(node)
    return trail, nodes


def enter_command_node(node: CommandNode) -> None:
    state["pending_command"] = None
    state["command_path"] = [*state.get("command_path", []), node.id]
    command_tree.refresh()


def select_command_node(node: CommandNode) -> None:
    state["pending_command"] = node
    command_tree.refresh()


async def activate_command_node(node: CommandNode) -> None:
    if node.children:
        enter_command_node(node)
        return
    if command_visible_fields(node.fields):
        select_command_node(node)
        return
    state["pending_command"] = None
    await start_operation(operation_from_pending_command(node))


def command_click_handler(node: CommandNode):
    async def handler() -> None:
        await activate_command_node(node)

    return handler


def go_back_command() -> None:
    if state.get("pending_command") is not None:
        state["pending_command"] = None
    else:
        path = list(state.get("command_path", []))
        if path:
            path.pop()
        state["command_path"] = path
    command_tree.refresh()


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_label(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def field_hint(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("hint_ru"):
        return str(field["hint_ru"])
    return str(field.get("hint") or "")


def localized_dict_text(payload: dict[str, Any], *keys: str) -> str:
    if settings.language == "ru":
        for key in keys:
            value = payload.get(f"{key}_ru")
            if value:
                return str(value)
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def field_default(field: dict[str, Any]) -> Any:
    if "default" in field:
        return field["default"]
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    options = field.get("options", [])
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        if not isinstance(options, list):
            return []
        selected: list[Any] = []
        for option in options:
            if isinstance(option, dict) and option.get("default", False):
                selected.append(option.get("value", option.get("id", option.get("label"))))
        return selected
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict):
            return first.get("value", first.get("id", ""))
        return first
    return ""


def current_field_value(field: dict[str, Any]) -> Any:
    key = field_id(field)
    values = state.setdefault("field_values", {})
    if key not in values:
        values[key] = field_default(field)
    return values[key]


def set_field_value(key: str, value: Any) -> None:
    state.setdefault("field_values", {})[key] = value


def dynamic_option_source(field: dict[str, Any]) -> str:
    return str(field.get("options_source") or field.get("source") or "").strip()


def model_provider_for_field(field: dict[str, Any]) -> str:
    source = dynamic_option_source(field)
    for provider, option_source in MODEL_OPTION_SOURCES.items():
        if source == option_source:
            return provider
    key = field_id(field)
    if key.startswith("openai_") and key.endswith("_model"):
        return "openai"
    if key.startswith("gemini_") and key.endswith("_model"):
        return "gemini"
    if key.startswith("xai_") and key.endswith("_model"):
        return "xai"
    if key.startswith("anthropic_") and key.endswith("_model"):
        return "anthropic"
    return ""


def api_key_provider_for_field(field: dict[str, Any]) -> str:
    source = dynamic_option_source(field)
    for provider, option_source in API_KEY_OPTION_SOURCES.items():
        if source == option_source:
            return provider
    key = field_id(field)
    for provider in API_KEY_OPTION_SOURCES:
        if key == f"{provider}_api_key_ref":
            return provider
    return ""


def clear_options_for_field(field: dict[str, Any]) -> None:
    source = dynamic_option_source(field)
    if source:
        dynamic_option_cache.pop(source, None)


def selected_option_label(field: dict[str, Any], value: Any) -> str:
    value_text = str(value or "").strip()
    for option in field_options(field):
        if str(option_value(option) or "").strip() == value_text:
            return option_label(option)
    return value_text


def refresh_button_label(field: dict[str, Any]) -> str:
    return tr("refresh_model_names") if model_provider_for_field(field) else tr("refresh_options")


def reset_model_options(field: dict[str, Any]) -> None:
    provider = model_provider_for_field(field)
    if not provider:
        return
    from system_core.services.audion_docs_service import reset_model_cache

    reset_model_cache(provider)
    source = dynamic_option_source(field)
    if source:
        dynamic_option_cache.pop(source, None)
    key = field_id(field)
    if key:
        state.setdefault("field_values", {}).pop(key, None)
    safe_notify(tr("reset_model_cache_done", provider=provider.upper()), "positive")
    command_tree.refresh()


def reset_model_options_click_handler(field: dict[str, Any]):
    def handler() -> None:
        reset_model_options(field)

    return handler


def refresh_dynamic_options(field: dict[str, Any]) -> None:
    source = dynamic_option_source(field)
    if source:
        dynamic_option_cache.pop(source, None)
    key = field_id(field)
    if key:
        state.setdefault("field_values", {}).pop(key, None)
    command_tree.refresh()


def refresh_options_click_handler(field: dict[str, Any]):
    def handler() -> None:
        refresh_dynamic_options(field)

    return handler


def control_tooltip_text(field: dict[str, Any]) -> str:
    return field_hint(field) or field_label(field)


def attach_tooltip(control: Any, text: str) -> Any:
    tooltip = str(text or "").strip()
    if tooltip:
        control.tooltip(tooltip)
    return control


def select_icon_button(icon: str, tooltip: str, on_click: Any, *, danger: bool = False) -> Any:
    classes = "audion-select-icon-button"
    if danger:
        classes += " audion-select-icon-button-danger"
    button = ui.button(icon=icon, on_click=on_click).props(f'dense flat round aria-label="{tooltip}"').classes(classes)
    button.tooltip(tooltip)
    return button


def model_pin_click_handler(field: dict[str, Any], provider: str, pinned: bool):
    async def handler() -> None:
        model = str(current_field_value(field) or "").strip()
        if not model or model.startswith("__"):
            safe_notify(tr("model_required"), "warning")
            return
        try:
            from system_core.services.audion_docs_service import model_is_pinned, pin_model_ref, unpin_model_ref

            current_pinned = await run.io_bound(model_is_pinned, provider, model)
            if current_pinned:
                await run.io_bound(unpin_model_ref, provider, model)
                safe_notify(tr("model_unpinned"), "positive")
            else:
                await run.io_bound(pin_model_ref, provider, model)
                safe_notify(tr("model_pinned"), "positive")
            clear_options_for_field(field)
            command_tree.refresh()
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")

    return handler


def api_key_pin_click_handler(field: dict[str, Any], provider: str, pinned: bool):
    async def handler() -> None:
        key_ref = str(current_field_value(field) or "").strip()
        if not key_ref or key_ref.startswith("__"):
            safe_notify(tr("api_key_required"), "warning")
            return
        try:
            from system_core.services.audion_docs_service import api_key_is_pinned, pin_api_key_ref, unpin_api_key_ref

            current_pinned = await run.io_bound(api_key_is_pinned, provider, key_ref)
            if current_pinned:
                await run.io_bound(unpin_api_key_ref, provider, key_ref)
                safe_notify(tr("api_key_unpinned"), "positive")
            else:
                await run.io_bound(pin_api_key_ref, provider, key_ref)
                safe_notify(tr("api_key_pinned"), "positive")
            clear_options_for_field(field)
            command_tree.refresh()
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")

    return handler


def add_api_key_click_handler(field: dict[str, Any], provider: str):
    async def handler() -> None:
        with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-key-dialog rounded-lg p-3"):
            ui.label(tr("add_api_key")).classes("text-base font-semibold")
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), tr("api_key_label")):
                label_input = ui.input(tr("api_key_label"), value=f"{provider.upper()} key").props("dense outlined stack-label").classes("w-full")
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), tr("api_key_value_placeholder")):
                key_input = ui.textarea(
                    label=tr("api_key_value"),
                    value="",
                    placeholder=api_key_placeholder(provider),
                ).props("dense outlined stack-label autogrow rows=2").classes("w-full audion-api-key-textarea")
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), tr("api_key_note")):
                note_input = ui.input(tr("api_key_note"), value="").props("dense outlined stack-label").classes("w-full")
            with ui.row().classes("gap-2 justify-end w-full"):
                attach_tooltip(ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg"), tr("cancel"))
                attach_tooltip(
                    ui.button(
                        tr("save"),
                        on_click=lambda: dialog.submit(
                            {
                                "label": str(label_input.value or ""),
                                "key": str(key_input.value or ""),
                                "note": str(note_input.value or ""),
                            }
                        ),
                    ).props("dense flat").classes("audion-action rounded-lg"),
                    tr("save"),
                )
        result = await dialog
        if not result:
            return
        try:
            from system_core.services.audion_docs_service import add_api_key_entry

            entry = await run.io_bound(add_api_key_entry, provider, result.get("label", ""), result.get("key", ""), result.get("note", ""))
            ref = str(entry.get("ref") or "").strip()
            if ref:
                set_field_value(field_id(field), ref)
            clear_options_for_field(field)
            safe_notify(tr("api_key_added"), "positive")
            command_tree.refresh()
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")

    return handler


def delete_api_key_click_handler(field: dict[str, Any], provider: str):
    async def handler() -> None:
        key_ref = str(current_field_value(field) or "").strip()
        if not key_ref or key_ref.startswith("__"):
            safe_notify(tr("api_key_required"), "warning")
            return
        label = selected_option_label(field, key_ref)
        with ui.dialog() as dialog, ui.card().classes("audion-dialog audion-key-dialog rounded-lg p-3"):
            ui.label(tr("confirm_delete_key")).classes("text-base font-semibold")
            ui.label(label).classes("text-sm text-gray-300")
            ui.label(tr("delete_key_note")).classes("text-xs text-gray-500")
            with ui.row().classes("gap-2 justify-end w-full"):
                attach_tooltip(ui.button(tr("cancel"), on_click=dialog.close).props("dense flat").classes("audion-action rounded-lg"), tr("cancel"))
                attach_tooltip(
                    ui.button(tr("delete"), on_click=lambda: dialog.submit(True)).props("dense flat color=negative").classes("rounded-lg"),
                    tr("delete_api_key"),
                )
        confirmed = await dialog
        if not confirmed:
            return
        try:
            from system_core.services.audion_docs_service import delete_api_key_entry

            deleted = await run.io_bound(delete_api_key_entry, provider, key_ref)
            set_field_value(field_id(field), "")
            clear_options_for_field(field)
            safe_notify(tr("api_key_deleted", label=str(deleted.get("label") or label)), "positive")
            command_tree.refresh()
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")

    return handler


def refresh_model_options_after_operation(operation: Operation) -> None:
    params = dict(operation.parameters)
    mode = str(params.get("mode") or "").strip().lower()
    if mode not in {"check_model", "pin_model"}:
        return
    provider = str(params.get("provider") or "").strip().lower()
    source = MODEL_OPTION_SOURCES.get(provider)
    if not source:
        return
    dynamic_option_cache.pop(source, None)
    command_tree.refresh()


def refresh_task_options_after_operation(operation: Operation) -> None:
    if not operation.service.endswith(":run_doc_task_operation"):
        return
    params = dict(operation.parameters)
    mode = str(params.get("mode") or "").strip().lower()
    if mode not in {
        "pin_doc_task",
        "set_active_doc_task",
        "import_doc_task",
        "save_quick_doc_task",
        "pin_quick_doc_task",
        "unpin_quick_doc_task",
        "delete_quick_doc_task",
        "run_doc_task",
        "run_quick_doc_task",
    }:
        return
    if mode == "delete_quick_doc_task":
        state.setdefault("field_values", {}).pop("quick_doc_task_ref", None)
    for source in TASK_OPTION_SOURCES:
        dynamic_option_cache.pop(source, None)
    command_tree.refresh()


def load_text_from_field_source(field: dict[str, Any], value: Any) -> tuple[str, dict[str, Any]]:
    key = field_id(field)
    selected = str(value or "").strip()

    if key == "quick_doc_task_ref":
        if not selected or selected.startswith("__"):
            return "", {}
        from system_core.doc_task_resolver import resolve_quick_doc_task_entry

        entry = resolve_quick_doc_task_entry(selected)
        content = str(entry.get("content") or "").strip() if entry else ""
        return content, entry

    if key == "doc_task_ref":
        from system_core.doc_task_resolver import resolve_doc_task_entry

        path, entry = resolve_doc_task_entry(selected)
        if not path or not entry:
            return "", {}
        return path.read_text(encoding="utf-8-sig", errors="replace").strip(), entry

    kind = str(field.get("type", field.get("kind", "text"))).lower()
    if kind in {"file", "path"}:
        if not selected:
            return "", {}
        source = Path(os.path.expandvars(selected)).expanduser()
        if not source.is_absolute():
            source = ROOT / source
        source = source.resolve()
        if not source.exists() or not source.is_file():
            raise RuntimeError(f"Instruction file was not found: {source}")
        if source.suffix.lower() not in {".md", ".txt"}:
            raise RuntimeError("TASK instruction picker expects a .md or .txt file.")
        return source.read_text(encoding="utf-8-sig", errors="replace").strip(), {"label": source.stem, "note": str(source)}

    return "", {}


def apply_loaded_text_to_targets(field: dict[str, Any], value: Any) -> bool:
    target = str(field.get("load_text_to") or "").strip()
    if not target:
        return False

    text, meta = load_text_from_field_source(field, value)
    if not text:
        return False

    values = state.setdefault("field_values", {})
    values[target] = text

    label_target = str(field.get("load_label_to") or "").strip()
    if label_target:
        label = str(meta.get("label") or "").strip()
        if label:
            values[label_target] = label

    note_target = str(field.get("load_note_to") or "").strip()
    if note_target:
        note = str(meta.get("note") or "").strip()
        if note:
            values[note_target] = note

    return True


def select_change_handler(field: dict[str, Any]):
    def handler(event: Any) -> None:
        key = field_id(field)
        set_field_value(key, event.value)
        try:
            loaded = apply_loaded_text_to_targets(field, event.value)
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")
            return
        if loaded:
            safe_notify(tr("task_loaded"), "positive")
            command_tree.refresh()

    return handler


def pick_file_field_click_handler(field: dict[str, Any]):
    async def handler() -> None:
        try:
            title = str(field.get("dialog_title") or field_label(field))
            file_filter = str(field.get("file_filter") or "Markdown files|*.md|Text files|*.txt|All files|*.*")
            selected = await run.io_bound(pick_single_file, title, file_filter)
            if selected is not None:
                set_field_value(field_id(field), str(selected))
                loaded = apply_loaded_text_to_targets(field, str(selected))
                if loaded:
                    safe_notify(tr("task_loaded"), "positive")
                command_tree.refresh()
        except Exception as exc:
            safe_notify(f"{exc.__class__.__name__}: {exc}", "negative")

    return handler


def apply_preset(preset: dict[str, Any]) -> None:
    values = preset.get("values", {})
    if not isinstance(values, dict):
        return
    field_values = state.setdefault("field_values", {})
    for key, value in values.items():
        field_values[str(key)] = value
    command_tree.refresh()


def preset_label(preset: dict[str, Any]) -> str:
    if settings.language == "ru" and preset.get("label_ru"):
        return str(preset["label_ru"])
    return str(preset.get("label") or preset.get("title") or preset.get("id") or "Preset")


def preset_tooltip(preset: dict[str, Any]) -> str:
    return localized_dict_text(preset, "tooltip", "description", "hint") or preset_label(preset)


def preset_click_handler(preset: dict[str, Any]):
    def handler() -> None:
        apply_preset(preset)

    return handler


def load_dynamic_options(field: dict[str, Any]) -> list[Any]:
    source = dynamic_option_source(field)
    if not source:
        return []

    cache_seconds = float(field.get("cache_seconds", 45) or 0)
    now = time.monotonic()
    cached = dynamic_option_cache.get(source)
    if cached and cache_seconds > 0 and now - cached[0] < cache_seconds:
        return cached[1]

    try:
        if ":" not in source:
            raise RuntimeError(f"Dynamic option source must use module:function syntax: {source}")
        module_name, function_name = source.split(":", 1)
        module = importlib.import_module(module_name)
        provider = getattr(module, function_name)
        try:
            params = inspect.signature(provider).parameters
            option_values = dict(state.get("field_values", {}))
            option_values.setdefault("source_dir", str(current_source_path()))
            option_values.setdefault("target_dir", str(current_target_path()))
            if len(params) >= 2:
                options = provider(ROOT, option_values)
            elif len(params) == 1:
                options = provider(ROOT)
            else:
                options = provider()
        except (TypeError, ValueError):
            try:
                options = provider(ROOT)
            except TypeError:
                options = provider()
        if not isinstance(options, list):
            raise RuntimeError(f"Dynamic option source returned {type(options).__name__}, expected list.")
    except Exception as exc:
        message = f"Option source failed: {exc.__class__.__name__}: {exc}"
        options = [{"value": "", "label": message, "label_ru": message}]

    dynamic_option_cache[source] = (now, options)
    return options


def field_options(field: dict[str, Any]) -> list[Any]:
    dynamic_options = load_dynamic_options(field)
    if dynamic_options:
        return dynamic_options
    options = field.get("options", [])
    return options if isinstance(options, list) else []


def select_options(field: dict[str, Any]) -> dict[Any, str] | list[Any]:
    options = field_options(field)
    if all(isinstance(option, dict) for option in options):
        result: dict[Any, str] = {}
        for option in options:
            value = option.get("value", option.get("id", ""))
            if settings.language == "ru" and option.get("label_ru"):
                label = str(option["label_ru"])
            else:
                label = str(option.get("label") or option.get("title") or value)
            result[value] = label
        return result
    return options


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label", "")))
    return option


def option_label(option: Any) -> str:
    if not isinstance(option, dict):
        return str(option)
    language = settings.language
    if language == "ru" and option.get("label_ru"):
        return str(option["label_ru"])
    return str(option.get("label") or option.get("title") or option_value(option))


def option_tooltip(option: Any) -> str:
    if not isinstance(option, dict):
        return str(option)
    return localized_dict_text(option, "tooltip", "description", "hint") or option_label(option)


def option_tooltip_for_field_value(field: dict[str, Any], value: Any, fallback: str) -> str:
    value_text = str(value)
    for option in field_options(field):
        if str(option_value(option)) == value_text:
            return option_tooltip(option)
    return str(fallback or "")


def checkbox_options(field: dict[str, Any]) -> list[tuple[Any, str]]:
    options = field_options(field)
    return [(option_value(option), option_label(option)) for option in options]


def is_checkbox_group(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    return kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}


MARKDOWN_EDITOR_KINDS = {"markdown_editor", "markdown", "md_editor", "codemirror", "code_editor"}
INFO_FIELD_KINDS = {"info", "note", "static", "display", "description"}


def field_container_classes(field: dict[str, Any]) -> str:
    span = str(field.get("span") or field.get("width") or "").lower()
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    field_key = field_id(field).lower()
    base = "audion-field"
    if kind in {"select", "choice", "format"}:
        base += " audion-field-select"
    if kind in {"radio", "radiobuttons", "radio-buttons"}:
        base += " audion-field-radio-chips"
        if "reasoning" in field_key:
            base += " audion-field-reasoning-chips"
    if kind in {"checkbox", "bool", "boolean", "toggle"} or is_checkbox_group(field):
        base += " audion-field-checkbox-chips"
    span_classes = {
        "half": "audion-field-span-6",
        "50%": "audion-field-span-6",
        "6": "audion-field-span-6",
        "third": "audion-field-span-4",
        "33%": "audion-field-span-4",
        "4": "audion-field-span-4",
        "quarter": "audion-field-span-3",
        "25%": "audion-field-span-3",
        "3": "audion-field-span-3",
    }
    if span in {"full", "wide", "100%", "1/-1"}:
        return f"{base} audion-field-wide"
    if span in span_classes:
        return f"{base} {span_classes[span]}"
    if kind in {"textarea", "multiline", "path", "file", "folder"} or kind in MARKDOWN_EDITOR_KINDS or kind in INFO_FIELD_KINDS:
        return f"{base} audion-field-wide"
    if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
        return f"{base} audion-field-wide"
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        return f"{base} audion-field-wide"
    return base


def bool_field_option(field: dict[str, Any], key: str, default: bool = False) -> bool:
    value = field.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def codemirror_theme_for_field(field: dict[str, Any]) -> str:
    mode = active_theme_mode()
    if mode == "dark":
        return str(field.get("theme_dark") or field.get("editor_theme_dark") or field.get("theme") or "vscodeDark")
    return str(field.get("theme_light") or field.get("editor_theme_light") or field.get("theme") or "vscodeLight")


def localized_field_text(field: dict[str, Any]) -> str:
    if settings.language == "ru":
        for key in ("text_ru", "content_ru", "description_ru", "hint_ru"):
            if field.get(key):
                return str(field.get(key))
    for key in ("text", "content", "description", "hint"):
        if field.get(key):
            return str(field.get(key))
    return ""


def field_is_operation_parameter(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    if kind in INFO_FIELD_KINDS:
        return False
    return bool(field.get("parameter", field.get("include_parameter", True)))


def is_workbench_route_field(field: dict[str, Any]) -> bool:
    key = field_id(field).lower()
    return key in {
        "source_dir",
        "source_folder",
        "source_path",
        "input_dir",
        "input_folder",
        "input_path",
        "target_dir",
        "target_folder",
        "target_path",
        "output_dir",
        "output_folder",
        "output_path",
        "destination_dir",
        "destination_folder",
        "destination_path",
    }


def command_visible_fields(fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [field for field in fields if not is_workbench_route_field(field)]


def workbench_value_for_field(field: dict[str, Any]) -> str:
    key = field_id(field).lower()
    if any(part in key for part in ("target", "output", "destination")):
        return str(current_target_path())
    return str(current_source_path())


def number_value_for_field(field: dict[str, Any], value: Any) -> int | float:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    is_integer = kind in {"int", "integer"}
    try:
        number = float(value)
    except (TypeError, ValueError):
        default = field_default(field)
        try:
            number = float(default)
        except (TypeError, ValueError):
            try:
                number = float(field.get("min", 0) or 0)
            except (TypeError, ValueError):
                number = 0.0

    minimum = field.get("min")
    maximum = field.get("max")
    if minimum not in {None, ""}:
        try:
            number = max(number, float(minimum))
        except (TypeError, ValueError):
            pass
    if maximum not in {None, ""}:
        try:
            number = min(number, float(maximum))
        except (TypeError, ValueError):
            pass
    return int(round(number)) if is_integer else number


def spin_number_field(field: dict[str, Any], field_key: str, number_input: Any, direction: int) -> None:
    try:
        step = float(field.get("step", 1) or 1)
    except (TypeError, ValueError):
        step = 1.0
    value = number_value_for_field(field, number_input.value)
    next_value = number_value_for_field(field, float(value) + (step * direction))
    set_field_value(field_key, next_value)
    number_input.value = next_value


def field_section_id(field: dict[str, Any]) -> str:
    explicit = str(field.get("section") or field.get("group") or field.get("field_section") or "").strip().lower()
    if explicit and explicit not in {"advanced", "expert", "rare"}:
        return explicit.replace(" ", "_").replace("-", "_")

    key = field_id(field).lower()
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    if any(token in key for token in ("api_key", "model", "provider", "reasoning")):
        return "provider"
    if any(token in key for token in ("chunk", "overlap", "min_chunks", "max_retries", "max_output", "timeout", "batch_size")):
        return "generation"
    if kind in {"file", "path", "folder"} or any(token in key for token in ("file", "folder", "dir", "docx", "json", "restore_map", "report")):
        return "files"
    if kind in INFO_FIELD_KINDS:
        return "content"
    if any(token in key for token in ("doc_task", "audit_rule", "quick_doc_task", "instruction", "query", "scope")):
        return "task"
    return "options"


def field_section_title(section_id: str) -> str:
    normalized = str(section_id or "options").strip().lower().replace("-", "_")
    known = {
        "task": "section_task",
        "task_sources": "section_task_sources",
        "task_editor": "section_task_editor",
        "task_options": "section_task_options",
        "content": "section_content",
        "provider": "section_provider",
        "files": "section_files",
        "generation": "section_generation",
        "options": "section_options",
        "parameters": "parameters",
    }
    if normalized in known:
        return tr(known[normalized])
    return normalized.replace("_", " ").strip().title()


def grouped_fields(fields: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    order = ["content", "task_sources", "task_editor", "task", "task_options", "provider", "files", "generation", "options"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        groups.setdefault(field_section_id(field), []).append(field)
    ordered = [(section_id, groups.pop(section_id)) for section_id in order if section_id in groups]
    ordered.extend(groups.items())
    return ordered


def render_fields_grid(fields: list[dict[str, Any]]) -> None:
    if not fields:
        return
    sections = grouped_fields(fields)
    with ui.element("div").classes("audion-fields-grid"):
        for index, (section_id, section_fields) in enumerate(sections):
            with ui.element("section").classes(f"audion-field-section audion-field-section-{section_id}"):
                ui.label(field_section_title(section_id)).classes("audion-section-title")
                with ui.element("div").classes("audion-section-fields"):
                    for field in section_fields:
                        render_field(field)
            if section_id == "task_editor" and any(next_section_id == "task_options" for next_section_id, _ in sections[index + 1 :]):
                ui.element("div").classes("audion-task-editor-resizer").props('title="Resize TASK editor"')


def render_field(field: dict[str, Any]) -> None:
    key = field_id(field)
    if not key:
        return
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    label = field_label(field)
    value = current_field_value(field)
    hint = field_hint(field)

    with ui.element("div").classes(field_container_classes(field)):
        if kind in {"preset_buttons", "presets", "profile_buttons", "profiles"}:
            presets = field.get("presets", field.get("options", []))
            if not isinstance(presets, list):
                presets = []
            ui.label(label).classes("audion-field-label")
            with ui.row().classes("audion-choice-row"):
                for preset in presets:
                    if not isinstance(preset, dict):
                        continue
                    attach_tooltip(
                        ui.button(
                            preset_label(preset),
                            on_click=preset_click_handler(preset),
                        ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                        preset_tooltip(preset),
                    )
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in INFO_FIELD_KINDS:
            text = localized_field_text(field)
            with ui.element("div").classes("audion-info-field"):
                if label:
                    ui.label(label).classes("audion-info-title")
                for paragraph in [part.strip() for part in text.split("\n\n") if part.strip()]:
                    ui.label(paragraph).classes("audion-info-text")
            return

        if kind in {"action_buttons", "icon_buttons", "quick_actions"}:
            actions = field.get("actions", [])
            if not isinstance(actions, list):
                actions = []
            if not bool(field.get("hide_label", False)):
                ui.label(label).classes("audion-field-label")
            with ui.row().classes("audion-field-action-row"):
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    action_label = localized_action_value(action, "label")
                    tooltip = localized_action_value(action, "tooltip") or action_label
                    classes = "audion-action audion-field-icon-button"
                    if str(action.get("kind") or "").lower() == "dangerous":
                        classes += " audion-field-icon-button-danger"
                    button = ui.button(
                        icon=str(action.get("icon") or "play_arrow"),
                        on_click=field_action_click_handler(field, action),
                    ).props(f'dense flat round aria-label="{action_label}"').classes(classes)
                    if tooltip:
                        button.tooltip(tooltip)
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"select", "choice", "format"}:
            model_provider = model_provider_for_field(field)
            key_provider = api_key_provider_for_field(field)
            model_pinned = False
            key_pinned = False
            selected_text = str(value or "").strip()
            try:
                if model_provider and selected_text and not selected_text.startswith("__"):
                    from system_core.services.audion_docs_service import model_is_pinned

                    model_pinned = model_is_pinned(model_provider, selected_text)
                if key_provider and selected_text and not selected_text.startswith("__"):
                    from system_core.services.audion_docs_service import api_key_is_pinned

                    key_pinned = api_key_is_pinned(key_provider, selected_text)
            except Exception:
                model_pinned = False
                key_pinned = False

            with ui.element("div").classes("audion-select-row"):
                with attach_tooltip(ui.element("div").classes("audion-select-control"), control_tooltip_text(field)):
                    select = ui.select(
                        options=select_options(field),
                        label=label,
                        value=value,
                        on_change=select_change_handler(field),
                    )
                    props = "dense outlined stack-label"
                    if bool(field.get("searchable", field.get("with_input", False))):
                        props += " use-input input-debounce=0"
                    props += " popup-content-class=audion-select-popup"
                    select.props(props).classes("audion-select min-w-0 flex-1")
                    if model_provider:
                        decorate_model_select_option_props(select, model_provider)
                if (dynamic_option_source(field) and not bool(field.get("hide_refresh", False))) or model_provider or key_provider:
                    with ui.element("div").classes("audion-select-actions"):
                        if model_provider:
                            select_icon_button(
                                "block" if model_pinned else "push_pin",
                                tr("unpin_selected_model") if model_pinned else tr("pin_selected_model"),
                                model_pin_click_handler(field, model_provider, model_pinned),
                            )
                        if key_provider:
                            select_icon_button(
                                "block" if key_pinned else "push_pin",
                                tr("unpin_selected_key") if key_pinned else tr("pin_selected_key"),
                                api_key_pin_click_handler(field, key_provider, key_pinned),
                            )
                            select_icon_button("add", tr("add_api_key"), add_api_key_click_handler(field, key_provider))
                            select_icon_button("delete", tr("delete_api_key"), delete_api_key_click_handler(field, key_provider), danger=True)
                        if dynamic_option_source(field) and not bool(field.get("hide_refresh", False)):
                            select_icon_button("refresh", refresh_button_label(field), refresh_options_click_handler(field))
                            if model_provider:
                                select_icon_button("restart_alt", tr("reset_model_cache"), reset_model_options_click_handler(field))
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"radio", "radiobuttons", "radio-buttons"}:
            ui.label(label).classes("audion-field-label")
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
                ui.radio(
                    options=select_options(field),
                    value=value,
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                ).props("dense inline").classes("audion-choice-row")
            if dynamic_option_source(field):
                with ui.row().classes("gap-2 mt-1"):
                    attach_tooltip(
                        ui.button(
                            refresh_button_label(field),
                            on_click=refresh_options_click_handler(field),
                        ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                        refresh_button_label(field),
                    )
                    if model_provider_for_field(field):
                        attach_tooltip(
                            ui.button(
                                tr("reset_model_cache"),
                                on_click=reset_model_options_click_handler(field),
                            ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                            tr("reset_model_cache"),
                        )
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"number", "int", "integer", "float"}:
            # Numbers are short, so the spinner stays narrow and its hint sits beside it
            # on one line instead of stacking a three-line paragraph under every field.
            with ui.element("div").classes("audion-number-row"):
                with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target audion-number-slot"), control_tooltip_text(field)):
                    number_input = ui.number(
                        label=label,
                        value=value if value != "" else None,
                        min=field.get("min"),
                        max=field.get("max"),
                        step=field.get("step", 1),
                        on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                    ).props("dense outlined stack-label").classes("audion-number audion-number-compact")
                    with number_input.add_slot("append"):
                        with ui.element("div").classes("audion-number-spinner"):
                            attach_tooltip(
                                ui.button(
                                    icon="keyboard_arrow_up",
                                    on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_field, item_key, control, 1),
                                ).props("dense flat round").classes("audion-number-spin-button"),
                                f"{label}: +{field.get('step', 1)}",
                            )
                            attach_tooltip(
                                ui.button(
                                    icon="keyboard_arrow_down",
                                    on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_field, item_key, control, -1),
                                ).props("dense flat round").classes("audion-number-spin-button"),
                                f"{label}: -{field.get('step', 1)}",
                            )
                if hint:
                    attach_tooltip(
                        ui.label(hint).classes("audion-field-hint audion-number-hint"),
                        hint,
                    )
            return

        if kind in MARKDOWN_EDITOR_KINDS:
            ui.label(label).classes("audion-field-label")
            editor_value = str(value) if value is not None else ""
            editor_classes = f"w-full audion-markdown-editor {str(field.get('classes') or '').strip()}".strip()
            try:
                with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
                    ui.codemirror(
                        value=editor_value,
                        language=str(field.get("language") or field.get("editor_language") or "Markdown"),
                        theme=codemirror_theme_for_field(field),
                        indent=str(field.get("indent") or "  "),
                        line_wrapping=bool_field_option(field, "line_wrapping", True),
                        highlight_whitespace=bool_field_option(field, "highlight_whitespace", False),
                        on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                    ).classes(editor_classes)
            except Exception as exc:
                logging.warning("CodeMirror field %s failed, falling back to textarea: %s", key, exc)
                with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
                    textarea = ui.textarea(
                        label=label,
                        value=editor_value,
                        placeholder=str(field.get("placeholder", "")),
                        on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                    )
                    props = "dense outlined stack-label"
                    rows = field.get("rows")
                    if rows:
                        props += f" rows={rows}"
                    textarea.props(props).classes(f"w-full {str(field.get('classes') or '').strip()}".strip())
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"textarea", "multiline"}:
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
                textarea = ui.textarea(
                    label=label,
                    value=str(value) if value is not None else "",
                    placeholder=str(field.get("placeholder", "")),
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                )
                props = "dense outlined stack-label"
                if bool(field.get("autogrow", True)):
                    props += " autogrow"
                rows = field.get("rows")
                if rows:
                    props += f" rows={rows}"
                textarea.props(props).classes(f"w-full {str(field.get('classes') or '').strip()}".strip())
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"file", "path"}:
            with ui.row().classes("w-full items-center gap-2"):
                with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target min-w-0 flex-1"), control_tooltip_text(field)):
                    ui.input(
                        label=label,
                        value=str(value) if value is not None else "",
                        placeholder=str(field.get("placeholder", "")),
                        on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                    ).props("dense outlined stack-label").classes("w-full")
                attach_tooltip(
                    ui.button(
                        tr("pick_file"),
                        on_click=pick_file_field_click_handler(field),
                    ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                    tr("pick_file"),
                )
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if kind in {"checkbox", "bool", "boolean", "toggle"}:
            with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
                ui.checkbox(
                    label,
                    value=bool(value),
                    on_change=lambda event, item_key=key: set_field_value(item_key, bool(event.value)),
                ).props("dense").classes("audion-single-checkbox")
            if hint:
                ui.label(hint).classes("audion-field-hint")
            return

        if is_checkbox_group(field):
            selected = set(value if isinstance(value, list) else [])
            controls: dict[Any, Any] = {}

            def sync_checkboxes(item_key: str = key) -> None:
                set_field_value(
                    item_key,
                    [option_key for option_key, checkbox in controls.items() if bool(checkbox.value)],
                )

            ui.label(label).classes("audion-field-label")
            if dynamic_option_source(field):
                with ui.row().classes("gap-2 mb-1"):
                    attach_tooltip(
                        ui.button(
                            refresh_button_label(field),
                            on_click=refresh_options_click_handler(field),
                        ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                        refresh_button_label(field),
                    )
                    if model_provider_for_field(field):
                        attach_tooltip(
                            ui.button(
                                tr("reset_model_cache"),
                                on_click=reset_model_options_click_handler(field),
                            ).props("dense flat no-wrap").classes("audion-action rounded-lg"),
                            tr("reset_model_cache"),
                        )
            with ui.row().classes("audion-choice-row"):
                for option_key, option_text in checkbox_options(field):
                    with attach_tooltip(
                        ui.element("div").classes("audion-checkbox-tooltip-target"),
                        option_tooltip_for_field_value(field, option_key, option_text),
                    ):
                        checkbox = ui.checkbox(
                            option_text,
                            value=option_key in selected,
                            on_change=lambda _event: sync_checkboxes(),
                        ).props("dense")
                    controls[option_key] = checkbox
            if hint:
                ui.label(hint).classes("audion-field-hint")
            sync_checkboxes()
            return

        with attach_tooltip(ui.element("div").classes("audion-control-tooltip-target"), control_tooltip_text(field)):
            ui.input(
                label=label,
                value=str(value) if value is not None else "",
                placeholder=str(field.get("placeholder", "")),
                on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
            ).props("dense outlined stack-label").classes("w-full")
        if hint:
            ui.label(hint).classes("audion-field-hint")


def operation_from_pending_command(node: CommandNode) -> Operation:
    parameters = dict(node.parameters)
    values = state.setdefault("field_values", {})
    for field in node.fields:
        key = field_id(field)
        if key and is_workbench_route_field(field):
            parameters[key] = workbench_value_for_field(field)
        elif key and field_is_operation_parameter(field):
            parameters[key] = values.get(key, field_default(field))
    parameters.setdefault("source_dir", str(current_source_path()))
    parameters.setdefault("target_dir", str(current_target_path()))
    return node.to_operation(parameters)


def validate_pending_fields(node: CommandNode) -> bool:
    values = state.setdefault("field_values", {})
    for field in command_visible_fields(node.fields):
        if not is_checkbox_group(field):
            continue
        min_selected = int(field.get("min_selected", 0) or 0)
        if min_selected <= 0:
            continue
        key = field_id(field)
        selected = values.get(key, field_default(field))
        if not isinstance(selected, list) or len(selected) < min_selected:
            safe_notify(tr("select_required", field=field_label(field)), "warning")
            return False
    return True


async def run_pending_command(node: CommandNode) -> None:
    if validate_pending_fields(node):
        await start_operation(operation_from_pending_command(node))


def run_pending_click_handler(node: CommandNode):
    async def handler() -> None:
        await run_pending_command(node)

    return handler


def field_signature(fields: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(field_id(field) for field in command_visible_fields(fields) if field_id(field))


def can_inline_child_actions(parent: CommandNode | None, children: list[CommandNode]) -> bool:
    if parent is None or not parent.fields or not children:
        return False
    parent_signature = field_signature(parent.fields)
    if not parent_signature:
        return False
    return all(not child.children and field_signature(child.fields) == parent_signature for child in children)


def child_inherits_parent_fields(parent: CommandNode, child: CommandNode) -> bool:
    parent_signature = field_signature(parent.fields)
    child_signature = field_signature(child.fields)
    return bool(parent_signature) and child_signature[: len(parent_signature)] == parent_signature


def common_group_nav_actions(parent: CommandNode | None, children: list[CommandNode]) -> list[tuple[CommandNode, str]]:
    if parent is None or not parent.fields:
        return []
    actions: list[tuple[CommandNode, str]] = []
    parent_signature = field_signature(parent.fields)
    for child in children:
        if child.children or is_select_embedded_pin_action(child) or not child_inherits_parent_fields(parent, child):
            continue
        action_mode = "run" if field_signature(child.fields) == parent_signature else "open"
        actions.append((child, action_mode))
    return actions


def is_primary_nav_action(node: CommandNode) -> bool:
    text = " ".join(
        [
            node.id,
            node.title,
            node.title_ru,
        ]
    ).casefold()
    return node.id.startswith("run") or "run" in text or "запустить" in text


def split_nav_actions(actions: list[tuple[CommandNode, str]]) -> tuple[list[tuple[CommandNode, str]], list[tuple[CommandNode, str]]]:
    primary: list[tuple[CommandNode, str]] = []
    secondary: list[tuple[CommandNode, str]] = []
    for action in actions:
        (primary if is_primary_nav_action(action[0]) else secondary).append(action)
    if len(primary) > 1:
        secondary = [*primary[1:], *secondary]
        primary = primary[:1]
    return primary, secondary


def node_field_signature(node: CommandNode) -> tuple[str, ...]:
    return field_signature(node.fields)


def descendant_leaf_paths(node: CommandNode) -> list[list[CommandNode]]:
    if not node.children:
        return [[node]]
    paths: list[list[CommandNode]] = []
    for child in node.children:
        for child_path in descendant_leaf_paths(child):
            paths.append([node, *child_path])
    return paths


def direct_common_actions(parent: CommandNode, children: list[CommandNode]) -> list[CommandNode]:
    parent_signature = node_field_signature(parent)
    return [
        child
        for child in children
        if not child.children and not is_select_embedded_pin_action(child) and node_field_signature(child) == parent_signature
    ]


def descendant_actions_match_parent(parent: CommandNode, children: list[CommandNode]) -> bool:
    parent_signature = node_field_signature(parent)
    if not parent_signature:
        return False
    leaf_paths = [path for child in children for path in descendant_leaf_paths(child) if not is_select_embedded_pin_action(path[-1])]
    return bool(leaf_paths) and all(node_field_signature(path[-1]) == parent_signature for path in leaf_paths)


def is_select_embedded_pin_action(node: CommandNode) -> bool:
    mode = str(node.parameters.get("mode") or "").strip().lower()
    return mode in {"pin_model", "pin_api_key"}


def render_inline_child_action(node: CommandNode, label: str | None = None) -> None:
    button_label = label or node.display_title(settings.language)
    button = ui.button(
        button_label,
        on_click=run_pending_click_handler(node),
    ).props("dense flat no-wrap no-caps").classes("audion-action audion-inline-action rounded-lg")
    description = node.display_description(settings.language)
    attach_tooltip(button, description or button_label)


def render_inline_action_row(actions: list[CommandNode]) -> None:
    actions = [node for node in actions if not is_select_embedded_pin_action(node)]
    if not actions:
        return
    with ui.row().classes("audion-inline-actions w-full gap-2"):
        for node in actions:
            render_inline_child_action(node)


def render_descendant_action_sections(children: list[CommandNode], *, include_direct: bool = True) -> None:
    direct_actions = [child for child in children if not child.children]
    if include_direct:
        render_inline_action_row(direct_actions)
    for child in children:
        if not child.children:
            continue
        child_title = child.display_title(settings.language)
        leaves = [path[-1] for path in descendant_leaf_paths(child) if not is_select_embedded_pin_action(path[-1])]
        if not leaves:
            continue
        with ui.row().classes("audion-inline-actions audion-mode-actions w-full gap-2"):
            for leaf in leaves:
                render_inline_child_action(leaf, f"{child_title}: {leaf.display_title(settings.language)}")


ADVANCED_FIELD_SUFFIXES = (
    "_model_override",
    "_chunk_tokens",
    "_overlap_tokens",
    "_min_chunks",
    "_max_retries",
    "_max_output_tokens",
    "_timeout_sec",
    "_resume",
)
ADVANCED_FIELD_IDS = {
    "require_render_map",
    "openai_service_tier",
}


def is_advanced_field(field: dict[str, Any]) -> bool:
    if bool(field.get("advanced", False)):
        return True
    priority = str(field.get("priority") or field.get("section") or "").strip().lower()
    if priority in {"advanced", "expert", "rare"}:
        return True
    key = field_id(field)
    return key in ADVANCED_FIELD_IDS or any(key.endswith(suffix) for suffix in ADVANCED_FIELD_SUFFIXES)


TASK_PROVIDER_FIELD_IDS = {
    "openai_api_key_ref",
    "gemini_api_key_ref",
    "xai_api_key_ref",
    "anthropic_api_key_ref",
    "openai_model",
    "gemini_model",
    "xai_model",
    "anthropic_model",
    "openai_pin_model",
    "gemini_pin_model",
    "xai_pin_model",
    "anthropic_pin_model",
}


AUDIT_FIELD_ORDER = {
    "openai": ("openai_api_key_ref", "openai_model", "audit_rule_ref", "openai_reasoning"),
    "gemini": ("gemini_api_key_ref", "gemini_model", "audit_rule_ref"),
    "xai": ("xai_api_key_ref", "xai_model", "audit_rule_ref"),
    "anthropic": ("anthropic_api_key_ref", "anthropic_model", "audit_rule_ref", "anthropic_reasoning"),
}


def order_audit_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field_ids = {field_id(field) for field in fields}
    for provider, desired_order in AUDIT_FIELD_ORDER.items():
        required = {f"{provider}_api_key_ref", f"{provider}_model", "audit_rule_ref"}
        if not required.issubset(field_ids):
            continue

        moved_ids: set[str] = set()
        ordered: list[dict[str, Any]] = []
        for desired_id in desired_order:
            for field in fields:
                if field_id(field) == desired_id:
                    ordered.append(field)
                    moved_ids.add(desired_id)
                    break
        ordered.extend(field for field in fields if field_id(field) not in moved_ids)
        return ordered
    return fields


def order_doc_task_replacement_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacement_fields = [field for field in fields if field_id(field) == "doc_task_apply_replacements"]
    if not replacement_fields:
        return fields

    ordered = [field for field in fields if field_id(field) != "doc_task_apply_replacements"]
    provider_anchor = -1
    for index, field in enumerate(ordered):
        if field_id(field) in TASK_PROVIDER_FIELD_IDS:
            provider_anchor = index

    if provider_anchor < 0:
        return fields
    return [*ordered[: provider_anchor + 1], *replacement_fields, *ordered[provider_anchor + 1 :]]


def order_primary_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return order_doc_task_replacement_fields(order_audit_fields(fields))


def split_primary_advanced_fields(fields: tuple[dict[str, Any], ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []
    for field in command_visible_fields(fields):
        if is_advanced_field(field):
            advanced.append(field)
        else:
            primary.append(field)
    return order_primary_fields(primary), advanced


def render_field_grid(fields: list[dict[str, Any]]) -> None:
    render_fields_grid(fields)


def render_advanced_fields(fields: list[dict[str, Any]]) -> None:
    if not fields:
        return
    with ui.expansion(
        tr("advanced"),
        value=bool(getattr(settings, "advanced_open", False)),
        on_value_change=save_advanced_open,
    ).classes("audion-advanced-expansion w-full") as expansion:
        expansion.props("dense switch-toggle-side")
        render_field_grid(fields)


def render_common_group(parent: CommandNode | None, children: list[CommandNode]) -> bool:
    if parent is None or not parent.fields or not children:
        return False

    flatten_all = descendant_actions_match_parent(parent, children)
    inline_direct = direct_common_actions(parent, children)
    if not flatten_all and not inline_direct:
        return False

    primary_fields, advanced_fields = split_primary_advanced_fields(parent.fields)
    if primary_fields:
        render_field_grid(primary_fields)

    ui.label(tr("actions")).classes("audion-subsection-label")
    if flatten_all:
        render_descendant_action_sections(children)
        render_advanced_fields(advanced_fields)
        return True

    render_inline_action_row(inline_direct)
    remaining = [child for child in children if child not in inline_direct]
    if remaining:
        ui.label(tr("more_actions")).classes("audion-subsection-label")
        for node in remaining:
            command_node_button(node)
    render_advanced_fields(advanced_fields)
    return True


def command_node_button(node: CommandNode) -> None:
    has_children = bool(node.children)
    label = node.display_title(settings.language)
    description = node.display_description(settings.language)
    if has_children and not description:
        description = tr("open_menu")

    direct_action = not has_children and not command_visible_fields(node.fields)
    row_classes = "audion-operation-row audion-direct-action-row" if direct_action else "audion-operation-row"
    with ui.element("div").classes(row_classes):
        button = ui.button(
            label,
            on_click=command_click_handler(node),
        ).props("dense flat no-wrap").classes(
            "audion-action audion-operation-button audion-direct-action rounded-lg"
            if direct_action else "audion-action audion-operation-button rounded-lg"
        )
        attach_tooltip(button, description or label)
        ui.label(description).classes("audion-operation-description")


def command_nav_row(
    trail: list[CommandNode],
    pending: CommandNode | None,
    inline_actions: list[tuple[CommandNode, str]] | None = None,
) -> None:
    primary_actions: list[tuple[CommandNode, str]] = []
    secondary_actions: list[tuple[CommandNode, str]] = []
    if pending is None and inline_actions:
        primary_actions, secondary_actions = split_nav_actions(inline_actions)
    can_go_back = pending is not None or bool(trail)
    if pending is not None:
        title = pending.display_title(settings.language)
    elif trail:
        title = " / ".join(node.display_title(settings.language) for node in trail)
    else:
        title = ""
    if not can_go_back and not title:
        return

    nav_classes = "audion-command-nav w-full"
    if secondary_actions:
        nav_classes += " audion-command-nav-windowed"

    with ui.element("div").classes(nav_classes):
        if can_go_back:
            back_button = ui.button(
                tr("back"),
                on_click=go_back_command,
            ).props("dense flat no-wrap").classes("audion-action audion-nav-back rounded-lg")
            attach_tooltip(back_button, tr("back"))
        ui.label(title).classes("audion-command-title min-w-0 flex-1 truncate")
        if pending is not None:
            run_button = ui.button(
                tr("run"),
                on_click=run_pending_click_handler(pending),
            ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
            attach_tooltip(run_button, pending.display_description(settings.language) or tr("run"))
        elif primary_actions or secondary_actions:
            for node, action_mode in primary_actions:
                click_handler = run_pending_click_handler(node) if action_mode == "run" else command_click_handler(node)
                nav_button = ui.button(
                    node.display_title(settings.language),
                    on_click=click_handler,
                ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg")
                attach_tooltip(nav_button, node.display_description(settings.language) or node.display_title(settings.language))
            if secondary_actions:
                with ui.element("div").classes("audion-window-actions"):
                    for node, action_mode in secondary_actions:
                        click_handler = run_pending_click_handler(node) if action_mode == "run" else command_click_handler(node)
                        nav_button = ui.button(
                            node.display_title(settings.language),
                            on_click=click_handler,
                        ).props("dense flat no-wrap").classes("audion-action audion-nav-secondary-button rounded-lg")
                        attach_tooltip(nav_button, node.display_description(settings.language) or node.display_title(settings.language))


@ui.refreshable
def command_tree() -> None:
    trail, nodes = current_command_level()
    pending = state.get("pending_command")
    parent = trail[-1] if trail else None
    inline_actions = common_group_nav_actions(parent, nodes) if pending is None else []
    command_nav_row(trail, pending, inline_actions)

    if pending is not None:
        primary_fields, advanced_fields = split_primary_advanced_fields(pending.fields)
        if pending.fields:
            render_field_grid(primary_fields)
        render_advanced_fields(advanced_fields)
        return

    if inline_actions:
        primary_fields, advanced_fields = split_primary_advanced_fields(parent.fields)
        render_field_grid(primary_fields)
        render_advanced_fields(advanced_fields)
        for node in nodes:
            if node.children:
                command_node_button(node)
        return

    if render_common_group(parent, nodes):
        return

    for node in nodes:
        command_node_button(node)
    if parent is not None and parent.id == "prepare":
        render_command_tree_maintenance()


def operation_by_id(operation_id: str) -> Operation | None:
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None


def command_tree_maintenance_operations() -> list[Operation]:
    return [
        operation
        for operation in manifest.maintenance_operations
        if operation.id != "cleanup_input_output"
    ]


def render_command_tree_maintenance() -> None:
    operations = command_tree_maintenance_operations()
    if not operations:
        return
    ui.label(f"{em('maintenance')}{tr('maintenance')}").classes("text-lg font-bold pt-2")
    for operation in operations:
        operation_button(operation)


_application_css_cache: dict[str, str] = {}


def application_css(name: str) -> str:
    """A stylesheet that lives next to this module rather than inside it."""
    if name not in _application_css_cache:
        path = Path(__file__).resolve().with_name(name)
        _application_css_cache[name] = path.read_text(encoding="utf-8")
    return _application_css_cache[name]


def add_styles() -> None:
    add_audion_canonical_ui_styles()
    variables_css = "\n".join(
        f"            --{key}: {value};"
        for key, value in sorted(theme_variables().items())
    )
    ui.add_head_html(
        "<style>\n"
        ":root {\n"
        f"{variables_css}\n"
        "}\n"
        + application_css("tokens.css")
        + application_css("theme.css")
        + "\n</style>\n"
    )
    ui.add_head_html(
        "<style id=\"audion-canonical-workbench-style\">"
        + WORKBENCH_LAYOUT_CSS
        + WORKBENCH_OVERRIDE_CSS
        + "</style>"
        + WORKBENCH_FEEDBACK_CSS
    )
    ui.add_head_html(
        """
        <style id="audion-docs-ai-modern-controls">
          .audion-field-radio-chips .audion-choice-row,
          .audion-field-checkbox-chips .audion-choice-row {
            display: grid !important;
            grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
            gap: 7px !important;
            width: 100%;
          }
          .audion-field-radio-chips .audion-choice-row .q-radio,
          .audion-field-checkbox-chips .audion-choice-row .q-checkbox,
          .audion-field-checkbox-chips .audion-single-checkbox {
            width: 100% !important;
            min-width: 0 !important;
            min-height: 32px !important;
            margin: 0 !important;
            padding: 4px 9px !important;
            border: 1px solid color-mix(in srgb, var(--audion-secondary-text) 34%, transparent 66%) !important;
            background: color-mix(in srgb, var(--audion-block-background) 82%, var(--audion-terminal-background) 18%) !important;
          }
          .audion-field-radio-chips .audion-choice-row .q-radio {
            border-radius: 999px !important;
          }
          .audion-field-checkbox-chips .audion-choice-row .q-checkbox,
          .audion-field-checkbox-chips .audion-single-checkbox {
            border-radius: 7px !important;
          }
          .audion-field-radio-chips .audion-choice-row .q-radio:hover,
          .audion-field-checkbox-chips .audion-choice-row .q-checkbox:hover,
          .audion-field-checkbox-chips .audion-single-checkbox:hover {
            border-color: color-mix(in srgb, var(--audion-button-text) 58%, var(--audion-secondary-text) 42%) !important;
            background: color-mix(in srgb, var(--audion-block-background) 72%, var(--audion-button-text) 28%) !important;
          }
          .audion-field-checkbox-chips .audion-control-tooltip-target {
            width: 100%;
          }
          .audion-field-reasoning-chips .audion-choice-row .q-radio__label {
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: nowrap !important;
          }
          .audion-direct-action {
            color: #e9b866 !important;
            background: color-mix(in srgb, #4f2d08 68%, var(--audion-terminal-background) 32%) !important;
            border: 1px solid color-mix(in srgb, #d08a2e 54%, transparent 46%) !important;
          }
          .audion-direct-action:hover {
            color: #ffd18b !important;
            background: color-mix(in srgb, #65400e 76%, var(--audion-terminal-background) 24%) !important;
            border-color: #d99a40 !important;
          }
          .audion-direct-action-row .audion-operation-description {
            color: var(--audion-secondary-text) !important;
          }
        </style>
        """
    )


def build_ui() -> None:
    ensure_project_dirs(paths)
    if not state["status"]:
        state["status"] = tr("idle")
    if active_theme_mode() == "dark":
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()
    add_styles()
    terminal_renderer = AnsiHtmlRenderer()
    initial_terminal = terminal_html(
        state["lines"],
        renderer=terminal_renderer,
        history_limit=TERMINAL_HISTORY_LIMIT,
    )

    with ui.header().classes("audion-header h-[42px] items-center justify-between px-4"):
        with ui.row().classes("audion-header-brand items-baseline gap-2"):
            ui.label(app_title()).classes("audion-header-title text-lg font-bold")
        with ui.row().classes("audion-header-controls items-center gap-2"):
            ui.icon("palette").classes("text-lg")
            with attach_tooltip(ui.element("div").classes("audion-theme-tooltip-target"), tr("theme")):
                ui.select(
                    options=theme_options(),
                    value=active_theme(),
                    on_change=theme_change_handler,
                ).props("dense outlined options-dense").classes("audion-theme-select")
            attach_tooltip(
                ui.button(tr("lang_switch"), on_click=toggle_language).props("dense flat").classes("audion-action rounded-lg"),
                tr("lang_switch"),
            )
            cancel_button = attach_tooltip(
                ui.button(tr("cancel"), on_click=lambda: state.update({"cancel": True})).props("dense flat color=negative"),
                tr("cancel"),
            )
            cancel_button.visible = False

    with ui.element("div").classes("audion-shell"):
        with ui.column().classes("audion-pane audion-scroll gap-3"):
            with ui.column().classes("audion-panel audion-workspace-panel w-full gap-2 p-2"):
                WORKBENCH_RENDERER.render_address_rows()
                WORKBENCH_RENDERER.render_action_bar()

            ui.label(f"{em('operations')}{tr('operations')}").classes("audion-section-heading")
            command_tree()

        ui.element("div").classes("audion-splitter").props(f'title="{tr("resize_panels")}"')

        with ui.element("div").classes("audion-pane audion-right gap-2 pt-3"):
            with ui.column().classes("audion-panel w-full gap-2 p-3"):
                        with ui.element("div").classes(status_row_classes()) as status_row:
                            status_dot_main = ui.element("span").classes("audion-status-dot-mark")
                            status_state_label = ui.label(status_state_text()).classes("audion-status-state")
                            status_label = ui.label(str(state["status"])).classes("audion-status-message")
                            status_clock = ui.label(elapsed_text(None)).classes("audion-status-clock")
                            with ui.element("div").classes("audion-status-bar"):
                                status_bar_fill = ui.element("i").style("width: 0%")
                            status_percent = ui.label(progress_text()).classes("audion-status-percent")

            with ui.column().classes("audion-terminal-panel w-full gap-2 p-3"):
                with ui.row().classes("audion-log-toolbar w-full items-center gap-2"):
                    ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                    ui.space()
                    attach_tooltip(ui.button(tr("logs"), on_click=lambda: open_folder(paths.logs)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("logs", paths.logs))
                    attach_tooltip(ui.button(tr("report"), on_click=lambda: open_folder(paths.report)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("report", paths.report))
                    attach_tooltip(ui.button(tr("output"), on_click=lambda: open_folder(paths.output)).props("dense flat").classes("audion-action rounded-lg"), tr("output"))
                    attach_tooltip(ui.button(tr("rules_short"), on_click=lambda: open_folder(paths.config / "audit_rules")).props("dense flat").classes("audion-action rounded-lg"), tr("rules_short"))
                    attach_tooltip(ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("config", paths.config))
                    clear_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                    clear_log_button.tooltip(audion_terminal_action_tooltip("clear_terminal_window"))
                    expand_log_button = ui.button(icon="open_in_full", on_click=lambda: log_dialog.open()).props("dense flat round").classes("audion-action audion-log-icon-button")
                    expand_log_button.tooltip(audion_terminal_action_tooltip("expand"))
                ui.html(initial_terminal, sanitize=False).classes("audion-terminal w-full min-h-[70vh]")
                with ui.row().classes("audion-terminal-footer w-full items-center gap-2 px-1 pt-1"):
                    status_dot = ui.label("●").classes(status_dot_classes())
                    terminal_status_label = ui.label(str(state["status"])).classes("min-w-0 flex-1 truncate text-xs")

    with ui.dialog() as log_dialog:
        with ui.card().classes("audion-dialog h-[92vh] w-[92vw] rounded-lg p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(f"{em('log')}{tr('log')}").classes("text-base font-semibold")
                ui.space()
                attach_tooltip(ui.button(tr("logs"), on_click=lambda: open_folder(paths.logs)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("logs", paths.logs))
                attach_tooltip(ui.button(tr("report"), on_click=lambda: open_folder(paths.report)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("report", paths.report))
                attach_tooltip(ui.button(tr("output"), on_click=lambda: open_folder(paths.output)).props("dense flat").classes("audion-action rounded-lg"), tr("output"))
                attach_tooltip(ui.button(tr("rules_short"), on_click=lambda: open_folder(paths.config / "audit_rules")).props("dense flat").classes("audion-action rounded-lg"), tr("rules_short"))
                attach_tooltip(ui.button(tr("config"), on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg"), audion_folder_button_tooltip("config", paths.config))
                clear_expanded_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                clear_expanded_log_button.tooltip(audion_terminal_action_tooltip("clear_terminal_window"))
                attach_tooltip(ui.button(tr("close"), on_click=log_dialog.close).props("dense flat").classes("audion-action rounded-lg").tooltip(audion_terminal_action_tooltip("close")), tr("close"))
            ui.html(initial_terminal, sanitize=False).classes("audion-terminal audion-terminal-expanded w-full")

    ui.run_javascript(
        """
        (() => {
          const storageKey = 'audion_docs_ai_terminal_width_px';
          const defaultWidth = 666;
          const minLeft = 460;
          const minRight = 460;

          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

          const applyWidth = (width) => {
            const shell = document.querySelector('.audion-shell');
            if (!shell) return;
            const rect = shell.getBoundingClientRect();
            const maxRight = Math.max(minRight, rect.width - minLeft - 40);
            const next = clamp(Number(width) || defaultWidth, minRight, maxRight);
            shell.style.setProperty('--audion-terminal-width', `${Math.round(next)}px`);
            localStorage.setItem(storageKey, String(Math.round(next)));
          };

          const setup = () => {
            const shell = document.querySelector('.audion-shell');
            const splitter = document.querySelector('.audion-splitter');
            if (!shell || !splitter) {
              setTimeout(setup, 80);
              return;
            }
            if (splitter.dataset.audionReady === '1') return;
            splitter.dataset.audionReady = '1';

            applyWidth(localStorage.getItem(storageKey) || defaultWidth);

            let dragging = false;
            const updateFromEvent = (event) => {
              if (!dragging) return;
              const rect = shell.getBoundingClientRect();
              const rightWidth = rect.right - event.clientX - 10;
              applyWidth(rightWidth);
            };

            splitter.addEventListener('pointerdown', (event) => {
              dragging = true;
              splitter.setPointerCapture?.(event.pointerId);
              document.body.classList.add('audion-resizing');
              event.preventDefault();
            });
            splitter.addEventListener('pointermove', updateFromEvent);
            splitter.addEventListener('pointerup', (event) => {
              dragging = false;
              splitter.releasePointerCapture?.(event.pointerId);
              document.body.classList.remove('audion-resizing');
            });
            splitter.addEventListener('pointercancel', () => {
              dragging = false;
              document.body.classList.remove('audion-resizing');
            });
            window.addEventListener('resize', () => applyWidth(localStorage.getItem(storageKey) || defaultWidth));
          };

          setup();

          const taskEditorStorageKey = 'audion_docs_ai_task_editor_height_px';
          const defaultTaskEditorHeight = 280;
          const minTaskEditorHeight = 220;
          const maxTaskEditorHeight = 560;
          const clampTaskEditorHeight = (value) => Math.max(minTaskEditorHeight, Math.min(maxTaskEditorHeight, value));
          const applyTaskEditorHeight = (height, save = true) => {
            const next = clampTaskEditorHeight(Number(height) || defaultTaskEditorHeight);
            document.querySelectorAll('.audion-markdown-editor').forEach((editor) => {
              editor.style.setProperty('--audion-task-editor-height', `${Math.round(next)}px`);
            });
            if (save) localStorage.setItem(taskEditorStorageKey, String(Math.round(next)));
          };
          const setupTaskEditors = () => {
            const saved = localStorage.getItem(taskEditorStorageKey);
            applyTaskEditorHeight(saved || defaultTaskEditorHeight, false);
          };

          let taskDrag = null;
          document.addEventListener('pointerdown', (event) => {
            const handle = event.target && event.target.closest ? event.target.closest('.audion-task-editor-resizer') : null;
            if (!handle) return;
            const editor = document.querySelector('.audion-markdown-editor');
            if (!editor) return;
            taskDrag = {
              startY: event.clientY,
              startHeight: editor.getBoundingClientRect().height || defaultTaskEditorHeight,
            };
            document.body.classList.add('audion-task-resizing');
            handle.setPointerCapture?.(event.pointerId);
            event.preventDefault();
          });
          document.addEventListener('pointermove', (event) => {
            if (!taskDrag) return;
            applyTaskEditorHeight(taskDrag.startHeight + event.clientY - taskDrag.startY);
          });
          document.addEventListener('pointerup', () => {
            taskDrag = null;
            document.body.classList.remove('audion-task-resizing');
          });
          document.addEventListener('pointercancel', () => {
            taskDrag = null;
            document.body.classList.remove('audion-task-resizing');
          });
          new MutationObserver(setupTaskEditors).observe(document.body, { childList: true, subtree: true });
          setupTaskEditors();
        })();
        """
    )

    terminal_render_state = {
        "generation": int(state.get("terminal_generation", 0)),
        "line_seq": int(state.get("line_seq", 0)),
    }

    refresh_timer: Any | None = None

    def update_terminal_dom(fragment: str, *, reset: bool, scroll_top: bool = False) -> None:
        ui.run_javascript(
            f"""
            (() => {{
              const fragment = {json.dumps(fragment)};
              const reset = {json.dumps(bool(reset))};
              const scrollTop = {json.dumps(bool(scroll_top))};
              const maxLines = {TERMINAL_HISTORY_LIMIT};
              const nearBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight <= 12;
              const selectionInside = (el) => {{
                const selection = window.getSelection && window.getSelection();
                return !!selection && !selection.isCollapsed && el.contains(selection.anchorNode);
              }};
              document.querySelectorAll('.audion-terminal').forEach((terminal) => {{
                let pre = terminal.querySelector('.audion-terminal-pre');
                if (!pre) {{
                  pre = document.createElement('pre');
                  pre.className = 'audion-terminal-pre';
                  pre.setAttribute('aria-label', 'Operation terminal');
                  terminal.replaceChildren(pre);
                }}
                const shouldFollow = nearBottom(terminal) && !selectionInside(terminal);
                if (reset) {{
                  pre.innerHTML = fragment;
                }} else if (fragment) {{
                  pre.insertAdjacentHTML('beforeend', fragment);
                }}
                const lines = pre.querySelectorAll(':scope > .audion-terminal-line');
                const overflow = lines.length - maxLines;
                for (let index = 0; index < overflow; index += 1) {{
                  lines[index].remove();
                }}
                if (scrollTop) {{
                  terminal.scrollTop = 0;
                }} else if (shouldFollow) {{
                  terminal.scrollTop = terminal.scrollHeight;
                }}
              }});
            }})();
            """
        )

    # Every one of these used to be written twice a second whether or not it had
    # changed, so an idle window still sent ten element updates a second. Holding
    # the last value makes an idle panel cost nothing and pays for the clock.
    shown = {"status": None, "state": None, "row": None, "clock": None, "percent": None, "fill": None}
    run_clock: dict[str, float | None] = {"started": None, "frozen": None}

    def refresh() -> None:
        nonlocal refresh_timer
        try:
            running = bool(state["running"])
            if running and run_clock["started"] is None:
                run_clock["started"] = time.monotonic()
                run_clock["frozen"] = None
            elif not running and run_clock["started"] is not None:
                run_clock["frozen"] = time.monotonic() - run_clock["started"]
                run_clock["started"] = None
            seconds = (
                time.monotonic() - run_clock["started"]
                if run_clock["started"] is not None
                else run_clock["frozen"]
            )

            def show(key: str, value: Any, assign: Any) -> None:
                if shown[key] != value:
                    shown[key] = value
                    assign(value)

            message = str(state["status"])
            show("status", message, lambda value: (
                setattr(status_label, "text", value),
                setattr(terminal_status_label, "text", value),
            ))
            show("state", status_state_text(), lambda value: setattr(status_state_label, "text", value))
            show("row", status_row_classes(), lambda value: (
                status_row.classes(replace=value),
                status_dot.classes(replace=status_dot_classes()),
            ))
            show("clock", elapsed_text(seconds), lambda value: setattr(status_clock, "text", value))
            show("percent", progress_text(), lambda value: setattr(status_percent, "text", value))
            show("fill", f"{float(state['progress']) * 100:.1f}%",
                lambda value: status_bar_fill.style(f"width: {value}"))
            generation = int(state.get("terminal_generation", 0))
            line_seq = int(state.get("line_seq", 0))
            lines = list(state["lines"][-TERMINAL_HISTORY_LIMIT:])
            first_seq = line_seq - len(lines)
            reset_terminal = (
                generation != int(terminal_render_state["generation"])
                or line_seq < int(terminal_render_state["line_seq"])
                or int(terminal_render_state["line_seq"]) < first_seq
            )
            if reset_terminal:
                terminal_renderer.reset()
                terminal_render_state["generation"] = generation
                terminal_render_state["line_seq"] = line_seq
                scroll_top = int(state.get("terminal_scroll_top_seq", 0)) and int(state.get("terminal_scroll_top_seq", 0)) <= line_seq
                if scroll_top:
                    state["terminal_scroll_top_seq"] = 0
                update_terminal_dom(terminal_lines_html(lines, renderer=terminal_renderer), reset=True, scroll_top=bool(scroll_top))
            elif line_seq > int(terminal_render_state["line_seq"]):
                start_index = max(0, int(terminal_render_state["line_seq"]) - first_seq)
                new_lines = lines[start_index:]
                terminal_render_state["line_seq"] = line_seq
                scroll_top = int(state.get("terminal_scroll_top_seq", 0)) and int(state.get("terminal_scroll_top_seq", 0)) <= line_seq
                if scroll_top:
                    state["terminal_scroll_top_seq"] = 0
                update_terminal_dom(terminal_lines_html(new_lines, renderer=terminal_renderer), reset=False, scroll_top=bool(scroll_top))
            cancel_button.visible = bool(state["running"])
        except RuntimeError as exc:
            message = str(exc)
            if "slot belongs to has been deleted" not in message and "current slot cannot be determined" not in message:
                raise
            logging.warning("NiceGUI refresh timer stopped because the client slot was deleted.")
            if refresh_timer is not None:
                refresh_timer.deactivate()

    refresh_timer = ui.timer(0.5, refresh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audion NiceGUI shell.")
    parser.add_argument("--host", default=str(ui_info.get("host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(ui_info.get("port", 8080)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def assert_gui_host_allowed(host: str) -> None:
    normalized = str(host or "").strip().lower().strip("[]")
    try:
        is_loopback = normalized == "localhost" or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        is_loopback = normalized == "localhost"
    allow_remote = str(os.environ.get("AUDION_ALLOW_REMOTE_GUI", "")).strip().lower() in {"1", "true", "yes", "on"}
    if not is_loopback and not allow_remote:
        raise SystemExit(
            "Refusing non-loopback host for a GUI with process execution. "
            "Use 127.0.0.1/localhost/::1, or set AUDION_ALLOW_REMOTE_GUI=1 explicitly."
        )


def build_ui_once() -> dict[str, int]:
    """Build the whole page once, headlessly, and report what came of it.

    `--smoke` used to print a line and return, so an app could ship a `build_ui`
    that raised on its first statement and still pass — twice in this fleet it did.
    Here the page is actually built: no browser and no HTTP request, so whatever
    the app defers until a client attaches is skipped, but every widget is
    constructed and the stylesheet has to arrive.
    """
    import asyncio
    import logging
    import re

    from nicegui import core
    from nicegui.client import Client
    from nicegui.page import page as page_definition

    async def build() -> tuple[int, str]:
        core.loop = asyncio.get_running_loop()
        # Work deferred to a connected browser fails here and says nothing about
        # the build. An exception raised by build_ui itself still propagates.
        core.loop.set_exception_handler(lambda _loop, _context: None)
        logging.getLogger("nicegui").setLevel(logging.CRITICAL)
        client = Client(page_definition("/__smoke__"))
        with client:
            build_ui()
        report = len(client.elements), client.shared_head_html + client.head_html
        # The page starts work that waits for a browser to attach. Nothing will
        # attach, so stop it deliberately instead of letting the loop close on it.
        pending = asyncio.all_tasks(core.loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return report

    element_count, head = asyncio.run(build())
    if element_count < 2:
        raise RuntimeError("build_ui produced no widgets")
    # Token prefixes differ between apps, so look for any custom property rather
    # than for one project's naming.
    if not re.search(r"--[\w-]+\s*:", head):
        raise RuntimeError("the stylesheet never reached the page")
    return {"elements": element_count, "stylesheet_bytes": len(head)}


def main() -> int:
    args = parse_args()
    assert_gui_host_allowed(args.host)
    ensure_project_dirs(paths)
    if args.smoke:
        try:
            report = build_ui_once()
        except Exception as error:  # noqa: BLE001
            print(f"FAIL nicegui shell: {ROOT}: {error}")
            return 1
        print(
            f"OK nicegui shell: {ROOT}"
            f" | widgets={report['elements']}"
            f" | stylesheet={report['stylesheet_bytes']} bytes"
        )
        return 0

    if port_is_open(args.host, args.port):
        url = f"http://{args.host}:{args.port}/"
        print(f"GUI already appears to be running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    ui.run(
        root=build_ui,
        title=app_title(),
        host=args.host,
        port=args.port,
        reload=False,
        native=False,
        show=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
