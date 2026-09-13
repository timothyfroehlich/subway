# Subway 🚇

> **Under-the-playfield token routing for AI coding assistants.**

In pinball, the **subway** is a hidden tunnel running beneath the playfield that transports balls out of sight without cluttering upper-playfield action.

In AI-assisted engineering, **Subway** intercepts monolithic file reads and repetitive boilerplate generation, routing them out-of-band to **Google Gemini Flash**. The primary agent (Claude Code, Antigravity) receives only concise structured answers or writes code directly to disk — preserving **90–99% of the primary agent's context window**.

Inspired by Spotify's internal **"Portal Shunt"** architecture.

---

## The Problem

Large language models have massive context windows, but dumping entire monolithic files (e.g., a 1,200-line database schema or 800-line test suite) into the session causes:
1. **Context Pollution:** Dilutes the prompt with thousands of tokens of irrelevant boilerplate.
2. **Degraded Reasoning:** "Lost in the middle" effects impair multi-step planning and debugging.
3. **Compounding Cost & Latency:** Every subsequent turn re-processes all those tokens.

## The Solution

Subway acts as an automated token shunt:
- **PreToolUse Hooks** intercept full-file reads (`view_file`, `cat`, `head`, `tail`) exceeding a configurable threshold (default: 350 lines).
- **Gemini 3.5 Flash-Lite** reads the file out-of-band in ~1.5s.
- **Structured Output:** Only concise bullet points or direct disk writes enter the conversation.
- **Targeted Reads Pass Through:** If you only need a specific line range or function for editing (`StartLine`/`EndLine` or `offset`/`limit`), the read passes through unimpeded.

---

## Live Benchmark

Tested against `src/server/db/schema.ts` (1,234 lines, 58 KB):

| Strategy | Primary Context Cost | Latency | Token Savings |
| :--- | :--- | :--- | :--- |
| **Direct Read** (Full file) | **16,489 tokens** | ~0.1s | Baseline |
| **Subway Read** (`gemini-3.5-flash-lite`) | **93 tokens** | **1.5s** | **99.4% saved** |
| **Subway Read** (`gemini-3.6-flash`) | **104 tokens** | **2.6s** | **99.3% saved** |

---

## Installation

### 1. Prerequisites
- Python 3.10+ (Standard library only; zero pip dependencies).
- Node.js 18+ (Standard library only; zero npm dependencies).
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/).

### 2. Install CLI
Clone the repository and symlink the binary into your `$PATH`:

```bash
git clone https://github.com/timothyfroehlich/subway.git ~/Code/subway
ln -s ~/Code/subway/bin/subway ~/.local/bin/subway
```

### 3. Configure API Key
Subway automatically resolves your key from any of the following locations:
1. `export GEMINI_API_KEY="your-api-key"` (in `~/.zshrc` or `~/.bashrc`)
2. `~/.config/subway/api_key`
3. `~/.claude/settings.json` (`env.GEMINI_API_KEY`)
4. `.env.local` or `.env` in the current project root

### 4. Enable Agent Plugins

#### Claude Code
Link the plugin to your Claude plugins directory or configure the hook in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [{ "type": "command", "command": "node ~/.local/share/subway/hooks/subway-file-size.cjs" }]
      },
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "node ~/.local/share/subway/hooks/subway-bash-read.cjs" }]
      }
    ]
  }
}
```

#### Antigravity
Symlink into your Antigravity plugins directory:

```bash
ln -s ~/Code/subway ~/.gemini/config/plugins/subway
```

---

## CLI Usage

### Bulk Reading (`read`)
Extract answers from large files without loading the raw contents into context:

```bash
subway read --question "What permissions does checkPermission check?" --paths src/server/db/schema.ts
```

Output:
```markdown
- `checkPermission(user, resource)`:
  - Checks role against `RolePermissions` mapping.
  - Enforces owner override for resources where `resource.owner_id === user.id`.
[subway: 16,489 input tokens, 93 output tokens | delegated to gemini-3.5-flash-lite]
```

### Boilerplate Code Generation (`write`)
Scaffold new files matching existing pattern files directly to disk (0 conversation tokens):

```bash
subway write \
  --spec "Unit tests for UserService covering create, update, delete" \
  --reference tests/fixtures/auth_service_test.py \
  --target tests/unit/test_user_service.py
```

### Direct Prompt (`ask`)
Quick one-shot queries to Flash:

```bash
subway ask "Explain the difference between optimistic and pessimistic locking in Drizzle ORM"
```

### PR Lifecycle Monitoring (`watch`)
Monitor a PR's CI gate or review phase out-of-band with 0 LLM tokens:

```bash
subway watch --pr 1234 --phase ci --expected-head 40-character-sha [--title "PR Title"]
```

Output:
```json
{"schema_version": 1, "repository": "owner/repo", "pr": 1234, "phase": "ci", "expected_head": "...", "observed_head": "...", "outcome": "passed", ...}
```
On failure, `subway watch` automatically extracts failed step logs from the failure artifact and enriches the terminal JSON with `failure_summary`.

---

## Configuration Options

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | None | Google AI Studio API key |
| `SUBWAY_MIN_LINES` | `350` | Line threshold that triggers Subway interception |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model to use (`gemini-3.5-flash-lite`, `gemini-3.6-flash`, etc.) |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
