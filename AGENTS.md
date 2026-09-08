# Subway Agent Context

## 1. Project Mission

**Subway** is a fast, ultra-lean token-routing subsystem for AI coding assistants (Claude Code, OpenAI Codex, Google Antigravity).

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
- Feature work happens on feature branches in separate linked Git worktrees.
- Keep the canonical checkout on `main` for inspection and synchronization;
  do not develop directly on `main`.
- Never force-push or rewrite published history on `main`.

## 3. Host Agent Wiring

Subway targets three host agents. They share the CLI (`bin/subway`) and worker
(`lib/gemini_worker.py`); only the hook wiring differs per host.

| Host | Manifest / wiring | Hook env var | Tool shapes handled |
| :--- | :--- | :--- | :--- |
| **Claude Code** | `.claude-plugin/plugin.json` (inline hooks) | `${CLAUDE_PLUGIN_DIR}` | `Read`, `Bash`; `file_path`, `offset`/`limit` |
| **Antigravity** | `plugin.json` + `hooks/hooks.json` | `$PLUGIN_DIR` | `view_file`, `run_command`; `AbsolutePath`, `StartLine`/`EndLine`, `CommandLine` |
| **Codex** | not wired yet | — | — |

The root `plugin.json` is the **Antigravity** manifest and
`.claude-plugin/plugin.json` is the **Claude Code** manifest. They are not
duplicates of each other; Claude Code reads only the latter.

Both hook scripts (`hooks/subway-file-size.cjs`, `hooks/subway-bash-read.cjs`)
already parse both Claude and Antigravity input shapes. `lib/resolve-command.cjs`
is a shared, hardened quote-aware shell parser (vendored from PinPoint; its
`PP-xxxx` comments are provenance).

## 4. Issue Tracking (beads)

Subway has its own [beads](https://github.com/steveyegge/beads) project, independent of any other repository.

- **Prefix:** `SBWY` (issues named `SBWY-<hash>`)
- **Backend:** embedded Dolt at `.beads/embeddeddolt/`, database `SBWY`. No
  server, no credentials, no network.
- **No remote, deliberately.** This project is local to one machine and has no
  off-machine copy. Do not add a Dolt remote.
- **Not in Git:** `.beads/` is machine-local and gitignored.
- Some issues carry legacy `subway-*` IDs from an earlier database. They are
  equally valid; do not renumber them.

```bash
bd ready            # unblocked work
bd create "..." --type bug --priority 2
bd list / bd show <id>
bd stats            # database summary
```

Two traps specific to this setup:

- **`bd doctor` does not exist in embedded mode.** It prints "not yet supported
  in embedded mode" and exits. Use `bd stats` to confirm the database responds.
- **`bd init` silently wires a Dolt remote from git `origin`.** There is no
  `--no-remote` flag. If anyone ever re-runs `bd init` here, immediately run
  `bd dolt remote remove origin` and confirm with `bd dolt remote list` that no
  remotes are configured.
