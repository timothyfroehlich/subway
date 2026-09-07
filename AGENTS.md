# Subway Agent Context

## 1. Project Mission

**Subway** is a fast, ultra-lean token-routing subsystem for AI coding assistants (Claude Code, Google Antigravity).

Inspired by Spotify's internal "Portal Shunt" pattern and named after the pinball playfield subway that routes balls out of sight, Subway intercepts monolithic file reads and routes repetitive boilerplate generation out-of-band to **Google Gemini Flash**. This saves 90–99% of the primary agent's context window.

## 2. Critical Non-Negotiables

### 2.1 Implementation Rules
- **Zero Runtime Dependencies:** The core Python client (`lib/gemini_worker.py`) and Node hooks (`hooks/`) must rely strictly on standard libraries (`urllib.request`, `json`, `pathlib`, `fs`, `path`, etc.). Never introduce runtime dependencies (no external SDK packages required for operation).
- **Fail-Open Safety:** PreToolUse hooks MUST fail open if `GEMINI_API_KEY` is not found, or if `subway` cannot be resolved. An agent must never be blocked or stranded by hook infrastructure failure.
- **Pass-through Targeted Reads:** Targeted reads (offsets, line ranges <= threshold, piped commands, redirections) must pass through unhindered.
- **Symlink Resilience:** `bin/subway` must resolve real paths across symlinks on both macOS and Linux.

### 2.2 Verification
Before committing changes, run:
```bash
ruff check . && ruff format --check .
pytest tests/
shellcheck bin/subway
```

### 2.3 Branch & Merge Policy
- Default branch is `main`.
- Feature work happens on feature branches in separate linked Git worktrees;
  keep the canonical checkout on `main` for inspection and synchronization.
- Never force-push or rewrite published history on `main`.
