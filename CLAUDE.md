# Subway — Claude Code Context

**The authoritative rules live in [AGENTS.md](AGENTS.md). Read it first.** It
covers the project mission, the non-negotiables, branch policy, host agent
wiring, and issue tracking. Nothing in this file restates them.

Subway routes heavy file reads and boilerplate generation out-of-band to Google
Gemini Flash, keeping large payloads out of the primary agent's context window.
Evolved from the earlier **Shunt** tool (the `SHUNT_MIN_LINES` env fallback is
retained for backward compat).

## Claude-Code-specific notes

- Claude Code reads **only** `.claude-plugin/plugin.json`. The root
  `plugin.json` is Antigravity's manifest — see [AGENTS.md](AGENTS.md) §3.
- Plugin development is not persistently enabled. Start Claude with
  `claude --plugin-dir /path/to/subway`; edits to the plugin take effect after
  `/reload-plugins`.
- Claude hook input shapes are `Read` and `Bash`, carrying `file_path` and
  `offset`/`limit`. Both hook scripts also parse Antigravity's shapes.

## Development

Toolchain is pinned in `mise.toml` (node, python, ruff). Verify before every
commit — same commands as [AGENTS.md](AGENTS.md) §2.2:

```bash
ruff check . && ruff format --check .
pytest tests/
shellcheck bin/subway
```

CI runs these directly. Node hooks are `.cjs` (CommonJS, stdlib only) and are
syntax-checked in CI (`node -c`).
