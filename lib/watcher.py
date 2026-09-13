#!/usr/bin/env python3
"""PR lifecycle watcher runner for Subway.

Invokes the target worktree's `scripts/workflow/pr-watch.py` without LLM mediation.
Captures terminal JSON, enriches failure verdicts with extracted failure summaries,
and propagates exit codes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="subway watch",
        description=(
            "Watch a PR lifecycle phase using the target repository's pr-watch."
        ),
    )
    parser.add_argument("--pr", type=int, required=True, help="PR number to watch")
    parser.add_argument(
        "--phase",
        choices=["ci", "review"],
        required=True,
        help="Lifecycle phase to monitor ('ci' or 'review')",
    )
    parser.add_argument(
        "--expected-head",
        type=str,
        required=True,
        help="Expected 40-character commit SHA",
    )
    parser.add_argument("--title", type=str, default="", help="PR title (optional)")
    parser.add_argument(
        "--worktree",
        type=str,
        default=".",
        help="Target worktree path (defaults to current directory)",
    )
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.pr <= 0:
        raise ValueError(f"PR number must be a positive integer, got {args.pr}")

    if not FULL_SHA.match(args.expected_head):
        raise ValueError(
            "--expected-head must be a 40-character lowercase hex SHA, "
            f"got {args.expected_head!r}"
        )

    worktree_path = Path(args.worktree).resolve()
    if not worktree_path.is_dir():
        raise FileNotFoundError(f"Worktree directory not found: {worktree_path}")

    pr_watch_script = worktree_path / "scripts" / "workflow" / "pr-watch.py"
    if not pr_watch_script.is_file():
        raise FileNotFoundError(f"pr-watch.py not found in worktree: {pr_watch_script}")

    return worktree_path, pr_watch_script


def extract_failure_summary(artifact_path: Path) -> str | None:
    """Read a markdown failure report and extract the failed step log."""
    if not artifact_path.is_file():
        return None
    try:
        content = artifact_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Match code block under '## Failed Steps Log'
    match = re.search(
        r"## Failed Steps Log\s+```(?:text)?\s*(.*?)\s*```",
        content,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # Fallback to returning up to first 100 lines of the artifact
    lines = content.splitlines()[:100]
    return "\n".join(lines).strip() or None


def run_watch(
    pr: int,
    phase: str,
    expected_head: str,
    worktree: Path,
    pr_watch_script: Path,
    title: str = "",
) -> int:
    cmd = [
        sys.executable,
        "scripts/workflow/pr-watch.py",
        str(pr),
        "--phase",
        phase,
        "--expected-head",
        expected_head,
        "--json",
    ]

    env = dict(os.environ)
    env.setdefault("GH_MONITOR_HARNESS", "subway")
    env.setdefault("GH_MONITOR_MODEL", "none")
    env["GH_MONITOR_WAKES"] = "1"

    if title:
        sys.stderr.write(
            f"[subway] Watching PR #{pr} — {title} ({phase}, {expected_head[:10]})\n"
        )
        sys.stderr.flush()

    proc = subprocess.Popen(
        cmd,
        cwd=str(worktree),
        env=env,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
    )

    stdout_data, _ = proc.communicate()
    exit_code = proc.returncode

    stdout_text = stdout_data.strip() if stdout_data else ""
    if not stdout_text:
        return exit_code

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        print(stdout_text)
        return exit_code

    outcome = payload.get("outcome")
    if outcome in ("failed", "action_required") or exit_code != 0:
        artifact_rel = payload.get("failure_artifact")
        if artifact_rel:
            artifact_file = Path(artifact_rel)
            if not artifact_file.is_absolute():
                artifact_file = worktree / artifact_file
            summary = extract_failure_summary(artifact_file)
            if summary:
                payload["failure_summary"] = summary

    print(json.dumps(payload))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        worktree_path, pr_watch_script = validate_args(args)
    except (ValueError, FileNotFoundError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    return run_watch(
        pr=args.pr,
        phase=args.phase,
        expected_head=args.expected_head,
        worktree=worktree_path,
        pr_watch_script=pr_watch_script,
        title=args.title,
    )


if __name__ == "__main__":
    sys.exit(main())
