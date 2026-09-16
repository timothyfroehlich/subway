---
name: subway
description: "Route heavy file reads and boilerplate code generation under the playfield via Gemini Flash. Use when reading files exceeding 350 lines, answering questions across multiple large files, or generating scaffolding matching an existing pattern file."
---

# Subway: Under-the-Playfield Token Routing

In pinball, the **subway** is the hidden track running underneath the playfield that transports balls out of sight without clogging upper-playfield action.

**Subway** routes heavy, multi-thousand-token files out-of-band to a fast worker model (**Gemini 3.5 Flash-Lite**). It returns concise structured answers or writes code directly to disk, preserving 90–99% of the primary agent's context window.

---

## When to Use Subway

Use Subway whenever:

1. **Reading a file > 350 lines:** Reading monolithic files directly into context pollutes your working memory. Use `subway read` instead.
2. **Comparing multiple large files:** Exploring architecture across several large files (e.g. comparing two complex modules or database schemas).
3. **Scaffolding repetitive code:** Writing boilerplate tests, configs, or type stubs that match an existing pattern file via `subway write`.
4. **Surgical edits:** If you need exact lines for editing, do NOT read the whole file. Use targeted reads (`offset`/`limit` in Claude Code, or `StartLine`/`EndLine` in Antigravity) — Subway hooks pass those through immediately.

---

## CLI Usage

### 1. Bulk Reading (`read`)

```bash
subway read --question "<what you want to know>" --paths <file1> [<file2> ...]
```

- **Returns:** Concise, high-fidelity bullet points. Each bullet leads with exact symbols, line numbers, or types.
- **Context impact:** Only the concise bullet response enters your conversation context.
- **Pass all relevant paths:** Pass all files that might be relevant to your question at once under `--paths`. Flash will correlate across all specified files in a single pass without loading thousands of lines into the primary agent's context.

#### Antigravity Invocation
In Antigravity, invoke `subway` via `run_command`:
```json
{
  "tool": "run_command",
  "CommandLine": "subway read --question \"<question>\" --paths file1 file2"
}
```

### 2. Boilerplate Code Generation (`write`)

```bash
subway write --spec "<what to build>" --reference <pattern_file> [--target <out_file>]
```

- **Behavior:** Matches conventions, types, imports, and style of the reference file.
- **Context impact:** When `--target` is provided, code writes directly to disk with **0 context tokens** entering the conversation stream.

### Delegation Boundaries

| Delegate to Subway (Flash) | Keep in Primary Agent Context |
| :--- | :--- |
| **Exploration & Discovery**: "Where is X defined across these 5 files?" | **Surgical Edits**: Precise line numbers and byte indentation needed by diff tools. |
| **Monolithic Files**: Reading files $> 350$ lines. | **Subtle Concurrency & Deep Logic**: Thread safety, invariants, architectural trade-offs. |
| **Repetitive Boilerplate**: Tests, mocks, types matching a reference pattern. | **Binary Files**: Images, PDFs, archives, SQLite databases. |

### 3. Direct Prompt (`ask`)

```bash
subway ask "<prompt>"
```

- Sends prompt directly to Gemini Flash and prints output.

### 4. PR Lifecycle Watch (`watch`)

```bash
subway watch --pr <pr> --phase <ci|review> --expected-head <sha> [--title <title>] [--worktree <path>]
```

- **Behavior:** Invokes the repository's native PR lifecycle watcher without LLM mediation.
- **Context impact:** 0 reasoning tokens during passive waits. Emits authoritative terminal JSON on standard output.
- **CI Phase (`--phase ci`):** Automatically extracts failed step logs from failure reports into `failure_summary`.
- **Review Phase (`--phase review`):**
  - Identifies covering reviewer (`coderabbit`, `codex`, `local_attestation`).
  - **Concurrent Review Adjudication:** Resolves on first success and tracks trailing in-progress reviewers (`concurrent_review_in_progress`, `pending_reviewers`, `review_notes`).
  - **Rate-Limit Management:** Detects CodeRabbit quota exhaustion (5 reviews/hr) and triggers fallback (`coderabbit_rate_limited: true`, `review_fallback: "codex"`).
  - **Findings Extraction:** Extracts actionable AI agent prompts and comment counts into `review_summary` and `actionable_comments`.
- **Pre-Review Requirement:** Always wait for current-head CI to pass before requesting or watching for review. Never request automated or manual code reviews on a PR that is failing or pending CI.
- **Background execution:** Designed to run as a background command in host agent harnesses.

---

## PreToolUse Hook Guard

Subway enforces context discipline automatically via PreToolUse hooks:

- **`view_file` / `Read`:** Blocks un-sliced reads of files > 350 lines.
- **`run_command` / `Bash`:** Blocks naked `cat`, `head`, `tail`, `less`, `more` on files > 350 lines.
- **Pass-throughs:**
  - Piped commands (`cat file | grep`) and redirections (`cat file > out`) are allowed.
  - Targeted reads (`offset`/`limit` or small `StartLine`/`EndLine` slices) are allowed.
- **Fail-open:** If `GEMINI_API_KEY` is unset or `subway` CLI is missing, the hook immediately allows normal reads so no agent is ever stuck.

---

## Configuration

- `GEMINI_API_KEY`: API key for Google AI Studio (resolved from environment variables, `~/.config/subway/api_key`, `~/.config/pinpoint/gemini_api_key`, or `.env.local`).
- `SUBWAY_MIN_LINES`: Minimum line threshold to trigger Subway interception (default: `350`).
- `GEMINI_MODEL`: Model override (default: `gemini-3.5-flash-lite`).
