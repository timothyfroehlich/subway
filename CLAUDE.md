# Subway — Claude Code Context

Subway routes heavy file reads and boilerplate generation out-of-band to Google Gemini Flash, keeping large payloads out of the primary agent's context window. Evolved from the earlier **Shunt** tool (the `SHUNT_MIN_LINES` env fallback is retained for backward compat).

**The authoritative rules live in [AGENTS.md](AGENTS.md).** Read it first — this file only adds Claude-Code-specific orientation and does not restate the non-negotiables (zero runtime deps, fail-open hooks, pass-through targeted reads, symlink resilience).

## Multi-agent architecture

Subway targets three host agents. They share the CLI (`bin/subway`) and worker (`lib/gemini_worker.py`); only the hook wiring differs per host.

| Host | Manifest / wiring | Hook env var | Tool shapes handled |
| :--- | :--- | :--- | :--- |
| **Claude Code** | `.claude-plugin/plugin.json` (inline hooks) | `${CLAUDE_PLUGIN_DIR}` | `Read`, `Bash`; `file_path`, `offset`/`limit` |
| **Antigravity** | `plugin.json` + `hooks/hooks.json` | `$PLUGIN_DIR` | `view_file`, `run_command`; `AbsolutePath`, `StartLine`/`EndLine`, `CommandLine` |
| **Codex** | not wired yet | — | — |

Both hook scripts (`hooks/subway-file-size.cjs`, `hooks/subway-bash-read.cjs`) already parse both Claude and Antigravity input shapes. `lib/resolve-command.cjs` is a shared, hardened quote-aware shell parser (vendored from PinPoint; its `PP-xxxx` comments are provenance).

## Development

Toolchain is pinned in `mise.toml` (node, python, ruff). Verify before every commit — same as [AGENTS.md](AGENTS.md) §2.2:

```bash
ruff check . && ruff format --check .
pytest tests/
shellcheck bin/subway
```

The repository's CI runs these checks directly. Node hooks are `.cjs`
(CommonJS, stdlib only) and are syntax-checked in CI (`node -c`).

## Issue tracking (beads)

This repository participates in the same logical Beads workspace as PinPoint
and Huddle. Splitting the code and CI does not split the task graph.

- **Workspace:** database `PP`, project ID, and new issue prefix are shared with PinPoint
- **Legacy IDs:** imported `subway-*` issues intentionally keep their existing IDs; all new issues use the shared `PP-*` prefix
- **Repository registration:** each code repository connects through the shared workspace registry; identifiers do not encode repository ownership
- **Backend:** the shared Bazzite Dolt server is the tailnet source of truth; one
  shared DoltHub remote provides asynchronous backup and bridge sync
- **Credentials:** `BEADS_DOLT_PASSWORD` comes from
  `~/.config/beads/credentials.env`; the old PinPoint path is only a migration
  fallback
- **Not in Git:** `.beads/` contains machine-local connection metadata and is
  ignored

The canonical registry and repository connector live in the dotfiles Beads
module. On a new machine, connect this checkout with:

```bash
~/.agents/beads/beads-connect-repo pinpoint "$PWD"
```

```bash
bd ready            # unblocked work
bd create "..." --type bug --priority 2
bd list / bd show <id>
bd doctor --server  # confirm the client is talking to the shared server
```

## Branch & worktree policy

Feature work happens in separate linked Git worktrees on feature branches.
Never force-push, rewrite, or develop directly on `main` (AGENTS.md §2.3).
