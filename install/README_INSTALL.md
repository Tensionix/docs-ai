# Install And Build Scripts

This folder contains the current portable-build layer for Audion Docs AI v3.

## Recommended Entry Point

Use the root launcher:

```bat
builder_main.cmd
```

It exposes the supported build, install, verify, release, and maintenance actions.

## Files

- `Build_Portable_Env.cmd` - wrapper for the portable build PowerShell script.
- `Build_Portable_Env.ps1` - portable runtime build implementation.
- `Build_Portable_Env_Build.cmd` - main CMD build script used from the builder launcher.
- `Check-CmdEncoding.cmd` - validates/fixes UTF-8 without BOM and CRLF for project CMD files.
- `init_folders.cmd` - recreates the expected Audion Docs AI folder structure, managed `.gitkeep` files, and empty local key placeholders. Markers inside populated payload folders such as `runtime\`, `wheelhouse\`, and `system_core\powershell\` are optional.
- `install_portable_offline.cmd` - installs dependencies from the local wheel cache into `runtime\`.
- `Install-Portable-PowerShell.cmd` - downloads portable PowerShell into `system_core\powershell\`.
- `launcher-tools-update_fzf.cmd` - refreshes `system_core\fzf.exe`.
- `make_release_archive.cmd` - stages a portable release archive and generates third-party notices.
- `requirements_full.in` - source dependency list for the portable runtime.
- `Update-Requirements-Lock.cmd` - updates the local requirements lock/wheel workflow.
- `verify_portable_env.cmd` - runs `system_core\doctor.py` against the portable runtime.
- GUI verification also runs `system_core\ui_nicegui\app.py --smoke` when the GUI shell is present.
- `download\` - local download cache used by build scripts.

## Removed Old Install Layer

The old venv/dev installer scripts and duplicated cleanup scripts were removed from `install\`.

Manual destructive source/release cleanup for GitHub source publishing is the root script:

```bat
cleanup_project.cmd
```

It keeps source, docs, install scripts, tests, prompts, rules, TASK instructions, and config files while clearing generated payload/output zones. Do not use it as install-cache cleanup; use `install\Clean-Install-Cache.cmd` for that.

## Notes

The GitHub source tree should not include generated runtime artifacts such as `runtime\`, `wheelhouse\`, `system_core\powershell\`, generated licenses, release archives, logs, caches, or real API keys. `system_core\powershell\` is rebuilt separately by `Install-Portable-PowerShell.cmd`.

## Reproducible payloads

Python runtime, wheelhouse, portable PowerShell and FZF are reproducible tool payloads. Install/update scripts may resolve latest upstream artifacts and cleanly replace only their owned targets: `runtime\`, `wheelhouse\`, `system_core\powershell\`, and `system_core\fzf.exe`.

---

## Current Builder Order And Dependency Hygiene

`builder_main.cmd` uses fixed numeric entries. Keep the bootstrap order stable: `[01] PYTHON ENV CMD`, `[02] PYTHON ENV PS`, `[03] FZF`, `[04] POWERSHELL`, then project-specific payload installers and one-time maintenance/diagnostic actions below.

Current builder install/maintenance map:

```text
[01] PYTHON ENV CMD
[02] PYTHON ENV PS
[03] FZF
[04] POWERSHELL
[09] PORTABLE OFFLINE
[70] CLEAN INSTALL CACHE
[71] VERIFY / DOCTOR
[77] MAKE RELEASE ARCHIVE
[90] PROJECT LAUNCHER
[91] PROJECT LAUNCHER RU
[92] TOOLS LAUNCHER
[95] OPEN install
[96] OPEN runtime
[97] OPEN wheelhouse
[98] OPEN licenses
[99] OPEN release
[00] EXIT
```

Project-specific payload entries before diagnostics:

No project-specific external payload installer before diagnostics.

Dependency hygiene rules:

- Python Embedded tracks the latest `3.12.x`; do not pin a concrete patch version in docs or scripts.
- Use the active embedded Python `_pth` file for path edits; do not hard-code a concrete filename.
- Bootstrap installs must include `setuptools`, `wheel`, and `packaging` before building or installing project wheels.
- `runtime\`, `wheelhouse\`, `system_core\powershell\`, `system_core\fzf.exe`, browser payloads, and external tool folders are reproducible payloads. Install/update scripts may cleanly replace only their owned targets.
- GPL or unknown-license external tools are explicit install/update payloads. Prefer GUI install buttons where the project exposes them, or fixed builder entries otherwise; do not silently bundle them as default source contents.
- `install\Clean-Install-Cache.cmd` / `.ps1` is the general install-cache cleanup. It removes transient `install\download\` artifacts (preserving `.gitkeep`, `get-pip.py`, and `7z*-extra.7z`), exact installer staging dirs `system_core\_pwsh_tmp` / `system_core\_fzf_tmp`, and Python bytecode caches outside runtime, wheelhouse, and user-data zones.
- `cleanup_project.cmd` is a separate source/release cleanup tool. It can remove runtime payloads and user-output zones after explicit confirmation; do not describe it as the general install-cache cleaner and do not wire it into install flow.




