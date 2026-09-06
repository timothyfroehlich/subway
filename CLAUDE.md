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

`npm run check` / `npm run test` wrap the same commands. Node hooks are `.cjs` (CommonJS, stdlib only) and are only syntax-checked in CI (`node -c`).

## Issue tracking (beads)

This project uses [beads](https://github.com/steveyegge/beads), sharing PinPoint's infrastructure — the same Dolt sql-server on Bazzite, same `beads` user. Subway is its own database.

- **Prefix:** `subway` (issues named `subway-<hash>`)
- **Backend:** `dolt_mode: server` → `beads@100.87.228.116:3306`, database `subway`
- **Credentials:** `BEADS_DOLT_PASSWORD` must be in the environment; it's in `~/.config/pinpoint/beads-server.env` (shared with PinPoint). `bd` speaks the MySQL wire protocol over Tailscale — the Mac needs no local Dolt data.
- **Not in git:** `.beads/` is gitignored (issue data lives on the server, connection config is per-machine), matching PinPoint.

```bash
bd ready            # unblocked work
bd create "..." --type bug --priority 2
bd list / bd show <id>
bd doctor --server  # confirm the client is talking to the shared server
```

No DoltHub mirror is configured yet, so cloud (off-tailnet) sessions can't reach Subway beads — tailnet only for now.

## Branch & worktree policy

Feature work happens on feature branches; never force-push or rewrite `main` (AGENTS.md §2.3). This repo uses git worktrees under `.claude/worktrees/` — `.beads/` and git hooks resolve to the main checkout, not the worktree.
