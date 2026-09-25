from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from watcher import (
    enrich_review_payload,
    extract_actionable_comments_count,
    extract_coderabbit_prompt,
    extract_failure_summary,
    inspect_coderabbit_state,
    inspect_codex_state,
)  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
SUBWAY_BIN = REPO_ROOT / "bin" / "subway"
DUMMY_SHA = "a" * 40


# Mirrors PinPoint scripts/workflow/pr-watch.py argparse after PinPoint #2187:
# `<PR> --phase ci|review --expected-head <SHA>` or `<PR> --check-ready`.
# Unknown flags such as --json fail with exit 2 and empty stdout, like the real
# script. Progress goes to stderr; stdout carries one terminal JSON line.
FAKE_PR_WATCH = """\
import argparse, json, re, sys
from pathlib import Path

def full_sha(value):
    if re.fullmatch(r"[0-9a-f]{{40}}", value) is None:
        raise argparse.ArgumentTypeError("must be a full 40-character SHA")
    return value

parser = argparse.ArgumentParser()
parser.add_argument("pr", type=int)
parser.add_argument("--phase", choices=("ci", "review"))
parser.add_argument("--expected-head", type=full_sha)
parser.add_argument("--check-ready", action="store_true")
args = parser.parse_args()
if args.check_ready and (args.phase or args.expected_head):
    parser.error("--check-ready does not take --phase or --expected-head")
if not args.check_ready and not (args.phase and args.expected_head):
    parser.error("a watch needs both --phase and --expected-head")
Path(__file__).with_name("argv.json").write_text(json.dumps(sys.argv[1:]))
print("[00:00:00] CI Gate: IN_PROGRESS", file=sys.stderr)
print(json.dumps({payload!r}, separators=(",", ":")), flush=True)
sys.exit({exit_code})
"""


def _write_fake_pr_watch(
    scripts_dir: Path, payload: dict[str, object], exit_code: int = 0
) -> Path:
    fake = scripts_dir / "pr-watch.py"
    fake.write_text(FAKE_PR_WATCH.format(payload=payload, exit_code=exit_code))
    return fake


def _recorded_argv(scripts_dir: Path) -> list[str]:
    return json.loads((scripts_dir / "argv.json").read_text())


def _run_subway(
    *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SUBWAY_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


def test_watch_help() -> None:
    res = _run_subway("watch", "--help")
    assert res.returncode == 0
    assert "usage: subway watch" in res.stdout
    assert "--pr PR" in res.stdout
    assert "--phase {ci,review}" in res.stdout
    assert "--expected-head EXPECTED_HEAD" in res.stdout


def test_watch_missing_required_args() -> None:
    res = _run_subway("watch")
    assert res.returncode == 2
    assert "the following arguments are required" in res.stderr


def test_watch_invalid_phase() -> None:
    res = _run_subway(
        "watch",
        "--pr",
        "123",
        "--phase",
        "deploy",
        "--expected-head",
        DUMMY_SHA,
    )
    assert res.returncode == 2
    assert "invalid choice: 'deploy'" in res.stderr


def test_watch_invalid_pr_zero(tmp_path: Path) -> None:
    res = _run_subway(
        "watch",
        "--pr",
        "0",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )
    assert res.returncode == 2
    assert "PR number must be a positive integer" in res.stderr


def test_watch_invalid_expected_head(tmp_path: Path) -> None:
    res = _run_subway(
        "watch",
        "--pr",
        "100",
        "--phase",
        "ci",
        "--expected-head",
        "not-a-sha",
        "--worktree",
        str(tmp_path),
    )
    assert res.returncode == 2
    assert "40-character lowercase hex SHA" in res.stderr


def test_watch_nonexistent_worktree() -> None:
    res = _run_subway(
        "watch",
        "--pr",
        "100",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        "/path/does/not/exist/ever",
    )
    assert res.returncode == 2
    assert "Worktree directory not found" in res.stderr


def test_watch_missing_pr_watch_script(tmp_path: Path) -> None:
    res = _run_subway(
        "watch",
        "--pr",
        "100",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )
    assert res.returncode == 2
    assert "pr-watch.py not found in worktree" in res.stderr


def test_extract_failure_summary_extracted(tmp_path: Path) -> None:
    report = tmp_path / "failure.md"
    report.write_text(
        "# GitHub Actions Failure Report\n"
        "Run ID: 12345\n\n"
        "## Failed Steps Log\n\n"
        "```text\n"
        "FAIL src/app.test.ts\n"
        "  ● Test suite failed to run\n"
        "```\n\n"
        "## Run Summary\n\n"
        "```text\n"
        "Summary text\n"
        "```\n",
        encoding="utf-8",
    )
    summary = extract_failure_summary(report)
    assert summary is not None
    assert "FAIL src/app.test.ts" in summary
    assert "Test suite failed to run" in summary


def test_extract_failure_summary_missing_file(tmp_path: Path) -> None:
    summary = extract_failure_summary(tmp_path / "does_not_exist.md")
    assert summary is None


def test_successful_watch_execution(tmp_path: Path) -> None:
    # Setup dummy repo structure
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_payload = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 42,
        "phase": "ci",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "passed",
        "ci_gate": "SUCCESS",
        "review_state": "unreviewed",
        "unresolved_threads": 0,
        "merge_state": "CLEAN",
        "detail_url": "https://example.com/gate",
        "failure_artifact": None,
        "timestamp": "2026-09-12T20:00:00Z",
    }

    _write_fake_pr_watch(scripts_dir, fake_payload, exit_code=0)

    res = _run_subway(
        "watch",
        "--pr",
        "42",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
        "--title",
        "Fix authentication race condition",
    )

    assert res.returncode == 0
    assert "[subway] Watching PR #42" in res.stderr
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "passed"
    assert out["pr"] == 42


def test_watch_invokes_post_2187_pr_watch_cli(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    _write_fake_pr_watch(
        scripts_dir,
        {"schema_version": 1, "pr": 42, "phase": "ci", "outcome": "passed"},
    )

    res = _run_subway(
        "watch",
        "--pr",
        "42",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 0, res.stderr
    assert _recorded_argv(scripts_dir) == [
        "42",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
    ]
    assert "CI Gate: IN_PROGRESS" in res.stderr
    lines = res.stdout.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["outcome"] == "passed"


def test_watch_passes_through_undetermined_verdict(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_payload = {
        "schema_version": 1,
        "repository": "timothyfroehlich/PinPoint",
        "pr": 7,
        "phase": "ci",
        "expected_head": DUMMY_SHA,
        "outcome": "undetermined",
        "observed_head": DUMMY_SHA,
        "ci_gate": "UNKNOWN",
        "review_state": "not reviewed",
        "unresolved_threads": 0,
        "merge_state": "UNKNOWN",
        "detail_url": None,
        "failure_artifact": None,
        "timestamp": "2026-09-25T20:00:00Z",
    }
    _write_fake_pr_watch(scripts_dir, fake_payload, exit_code=2)

    res = _run_subway(
        "watch",
        "--pr",
        "7",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 2
    assert json.loads(res.stdout.strip()) == fake_payload


def test_watch_usage_error_emits_undetermined(tmp_path: Path) -> None:
    """A pr-watch usage error exits 2 with empty stdout; subway still emits JSON."""
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "pr-watch.py").write_text(
        "import sys\nprint('usage: pr-watch.py', file=sys.stderr)\nsys.exit(2)\n"
    )

    res = _run_subway(
        "watch",
        "--pr",
        "5",
        "--phase",
        "review",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 2
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "undetermined"
    assert out["phase"] == "review"


def test_failed_watch_enriches_failure_summary(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)

    log_dir = tmp_path / "tmp" / "gh-monitor"
    log_dir.mkdir(parents=True)
    artifact_path = log_dir / "failure-999.md"
    artifact_path.write_text(
        "# GitHub Actions Failure Report\n"
        "Run ID: 999\n\n"
        "## Failed Steps Log\n\n"
        "```text\n"
        "npm ERR! 1 error found in tests\n"
        "```\n\n"
        "## Run Summary\n\n"
        "```text\n"
        "Run concluded with failure\n"
        "```\n"
    )

    fake_payload = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 42,
        "phase": "ci",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "failed",
        "ci_gate": "FAILURE",
        "review_state": "unreviewed",
        "unresolved_threads": 0,
        "merge_state": "CLEAN",
        "detail_url": "https://example.com/gate",
        "failure_artifact": "tmp/gh-monitor/failure-999.md",
        "timestamp": "2026-09-12T20:00:00Z",
    }

    _write_fake_pr_watch(scripts_dir, fake_payload, exit_code=1)

    res = _run_subway(
        "watch",
        "--pr",
        "42",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 1
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "failed"
    assert "failure_summary" in out
    assert "npm ERR! 1 error found in tests" in out["failure_summary"]


def test_default_worktree_resolves_cwd(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_payload = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 10,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "passed",
        "ci_gate": "SUCCESS",
        "review_state": "reviewed",
        "unresolved_threads": 0,
        "merge_state": "CLEAN",
        "detail_url": None,
        "failure_artifact": None,
        "timestamp": "2026-09-12T20:00:00Z",
    }

    _write_fake_pr_watch(scripts_dir, fake_payload, exit_code=0)

    # Run without --worktree, passing cwd=tmp_path
    res = _run_subway(
        "watch",
        "--pr",
        "10",
        "--phase",
        "review",
        "--expected-head",
        DUMMY_SHA,
        cwd=tmp_path,
    )

    assert res.returncode == 0
    out = json.loads(res.stdout.strip())
    assert out["pr"] == 10
    assert out["outcome"] == "passed"


def test_watch_non_json_stdout_emits_undetermined(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_pr_watch = scripts_dir / "pr-watch.py"
    fake_pr_watch.write_text(
        "import sys\nprint('Fatal error: unexpected traceback')\nsys.exit(2)\n"
    )

    res = _run_subway(
        "watch",
        "--pr",
        "99",
        "--phase",
        "ci",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 2
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "undetermined"
    assert out["pr"] == 99


def test_watch_action_required_does_not_enrich_failure_summary(
    tmp_path: Path,
) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_payload = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 42,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "action_required",
        "ci_gate": "UNKNOWN",
        "review_state": "reviewed",
        "unresolved_threads": 2,
        "merge_state": "CLEAN",
        "detail_url": None,
        "failure_artifact": None,
        "timestamp": "2026-09-12T20:00:00Z",
    }

    _write_fake_pr_watch(scripts_dir, fake_payload, exit_code=1)

    res = _run_subway(
        "watch",
        "--pr",
        "42",
        "--phase",
        "review",
        "--expected-head",
        DUMMY_SHA,
        "--worktree",
        str(tmp_path),
    )

    assert res.returncode == 1
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "action_required"
    assert "failure_summary" not in out


def test_extract_coderabbit_prompt_present() -> None:
    body = (
        "Some review text.\n\n"
        "<details>\n"
        "<summary>🤖 Prompt for all review comments with AI agents</summary>\n\n"
        "```text\n"
        "Fix the null pointer in file.py at line 42.\n"
        "```\n"
        "</details>\n"
    )
    prompt = extract_coderabbit_prompt(body)
    assert prompt == "Fix the null pointer in file.py at line 42."


def test_extract_coderabbit_prompt_absent() -> None:
    body = "Review without prompt block."
    assert extract_coderabbit_prompt(body) is None


def test_extract_actionable_comments_count_present() -> None:
    body = "Summary\n**Actionable comments posted: 3**\nMore text"
    assert extract_actionable_comments_count(body) == 3


def test_extract_actionable_comments_count_absent() -> None:
    body = "No actionable comments count here."
    assert extract_actionable_comments_count(body) is None


def test_inspect_coderabbit_state_in_progress() -> None:
    statuses = [
        {
            "context": "CodeRabbit",
            "state": "pending",
            "description": "Review in progress",
        }
    ]
    st = inspect_coderabbit_state(statuses, [], [], DUMMY_SHA)
    assert st["state"] == "in_progress"
    assert st["covers"] is False


def test_inspect_coderabbit_state_rate_limited() -> None:
    comments = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "body": "Review rate limited. Try again later.",
        }
    ]
    st = inspect_coderabbit_state([], [], comments, DUMMY_SHA)
    assert st["state"] == "rate_limited"
    assert st["rate_limited"] is True


def test_inspect_coderabbit_state_covers() -> None:
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": DUMMY_SHA,
            "state": "APPROVED",
            "body": "**Actionable comments posted: 0**",
        }
    ]
    st = inspect_coderabbit_state([], reviews, [], DUMMY_SHA)
    assert st["state"] == "covers"
    assert st["covers"] is True


def test_inspect_coderabbit_state_changes_requested() -> None:
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": DUMMY_SHA,
            "state": "CHANGES_REQUESTED",
            "body": (
                "**Actionable comments posted: 1**\n"
                "<summary>🤖 Prompt for all review comments with AI agents"
                "</summary>\n"
                "```\nFix issue\n```"
            ),
        }
    ]
    st = inspect_coderabbit_state([], reviews, [], DUMMY_SHA)
    assert st["state"] == "changes_requested"
    assert st["covers"] is False
    assert st["actionable_comments"] == 1
    assert st["review_summary"] == "Fix issue"


def test_inspect_coderabbit_state_stale_request_on_new_head() -> None:
    old_sha = "1" * 40
    new_sha = "2" * 40
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": old_sha,
            "state": "COMMENTED",
            "submitted_at": "2026-09-16T10:05:00Z",
        }
    ]
    comments = [
        {
            "user": {"login": "developer"},
            "body": "@coderabbitai review",
            "created_at": "2026-09-16T10:00:00Z",
        }
    ]
    st = inspect_coderabbit_state([], reviews, comments, new_sha)
    assert st["state"] == "none"
    assert st["covers"] is False


def test_inspect_coderabbit_state_fresh_request_on_new_head() -> None:
    old_sha = "1" * 40
    new_sha = "2" * 40
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": old_sha,
            "state": "COMMENTED",
            "submitted_at": "2026-09-16T10:05:00Z",
        }
    ]
    comments = [
        {
            "user": {"login": "developer"},
            "body": "@coderabbitai review",
            "created_at": "2026-09-16T10:10:00Z",
        }
    ]
    st = inspect_coderabbit_state([], reviews, comments, new_sha)
    assert st["state"] == "in_progress"


def test_inspect_coderabbit_state_stale_rate_limit_cleared_by_newer_review() -> None:
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": DUMMY_SHA,
            "state": "COMMENTED",
            "submitted_at": "2026-09-16T10:15:00Z",
        }
    ]
    comments = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "body": "Review rate limited. Try again later.",
            "created_at": "2026-09-16T10:10:00Z",
        }
    ]
    st = inspect_coderabbit_state([], reviews, comments, DUMMY_SHA)
    assert st["rate_limited"] is False
    assert st["state"] == "none"


def test_inspect_coderabbit_state_rate_limit_newer_than_completed_review() -> None:
    reviews = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "commit_id": DUMMY_SHA,
            "state": "COMMENTED",
            "submitted_at": "2026-09-16T10:05:00Z",
        }
    ]
    comments = [
        {
            "user": {"login": "coderabbitai[bot]"},
            "body": "Review rate limited. Try again later.",
            "created_at": "2026-09-16T10:10:00Z",
        }
    ]
    st = inspect_coderabbit_state([], reviews, comments, DUMMY_SHA)
    assert st["rate_limited"] is True
    assert st["state"] == "rate_limited"


def test_inspect_codex_state_in_progress() -> None:
    comments = [
        {
            "user": {"login": "timothyfroehlich"},
            "body": f"@codex review\n<!-- pinpoint-codex-review-head: {DUMMY_SHA} -->",
        }
    ]
    st = inspect_codex_state([], comments, DUMMY_SHA, 0)
    assert st["state"] == "in_progress"
    assert st["covers"] is False


def test_inspect_codex_state_covers_approved() -> None:
    reviews = [
        {
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "commit_id": DUMMY_SHA,
            "state": "APPROVED",
        }
    ]
    st = inspect_codex_state(reviews, [], DUMMY_SHA, 0)
    assert st["state"] == "covers"
    assert st["covers"] is True


def test_inspect_codex_state_covers_clean_comment() -> None:
    comments = [
        {
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "body": (
                "Codex Review: Didn't find any major issues.\n"
                f"**Reviewed commit:** `{DUMMY_SHA[:10]}`"
            ),
        }
    ]
    st = inspect_codex_state([], comments, DUMMY_SHA, 0)
    assert st["state"] == "covers"
    assert st["covers"] is True


def test_inspect_codex_state_covers_witness() -> None:
    comments = [
        {
            "user": {"login": "github-actions[bot]"},
            "body": f"<!-- pinpoint-codex-reaction-witness: {DUMMY_SHA} -->",
        }
    ]
    st = inspect_codex_state([], comments, DUMMY_SHA, 0)
    assert st["state"] == "covers"
    assert st["covers"] is True


def test_enrich_review_payload_coderabbit_wins_with_codex_in_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import watcher

    cr_review = {
        "user": {"login": "coderabbitai[bot]"},
        "commit_id": DUMMY_SHA,
        "state": "APPROVED",
        "body": "Looks good!",
    }
    codex_comment = {
        "user": {"login": "someuser"},
        "body": f"@codex review\n<!-- pinpoint-codex-review-head: {DUMMY_SHA} -->",
    }

    monkeypatch.setattr(watcher, "fetch_commit_statuses", lambda *_: [])
    monkeypatch.setattr(watcher, "fetch_pr_reviews", lambda *_: [cr_review])
    monkeypatch.setattr(watcher, "fetch_pr_comments", lambda *_: [codex_comment])

    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 100,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "passed",
        "review_state": "reviewed",
        "unresolved_threads": 0,
    }

    enriched = enrich_review_payload(payload, tmp_path, DUMMY_SHA, 100)
    assert enriched["reviewer"] == "coderabbit"
    assert enriched["concurrent_review_in_progress"] == "codex"
    assert enriched["pending_reviewers"] == ["codex"]
    notes = enriched.get("review_notes", [])
    assert any("Codex review is still in progress" in str(n) for n in notes)


def test_enrich_review_payload_codex_wins_with_coderabbit_in_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import watcher

    cr_status = {
        "context": "CodeRabbit",
        "state": "pending",
        "description": "Review in progress",
    }
    codex_review = {
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "commit_id": DUMMY_SHA,
        "state": "APPROVED",
    }

    monkeypatch.setattr(watcher, "fetch_commit_statuses", lambda *_: [cr_status])
    monkeypatch.setattr(watcher, "fetch_pr_reviews", lambda *_: [codex_review])
    monkeypatch.setattr(watcher, "fetch_pr_comments", lambda *_: [])

    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 100,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "passed",
        "review_state": "reviewed",
        "unresolved_threads": 0,
    }

    enriched = enrich_review_payload(payload, tmp_path, DUMMY_SHA, 100)
    assert enriched["reviewer"] == "codex"
    assert enriched["concurrent_review_in_progress"] == "coderabbit"
    assert enriched["pending_reviewers"] == ["coderabbit"]
    notes = enriched.get("review_notes", [])
    assert any("CodeRabbit review is still in progress" in str(n) for n in notes)


def test_enrich_review_payload_rate_limited_codex_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import watcher

    cr_comment = {
        "user": {"login": "coderabbitai[bot]"},
        "body": "Review rate limited. Try again later.",
    }

    monkeypatch.setattr(watcher, "fetch_commit_statuses", lambda *_: [])
    monkeypatch.setattr(watcher, "fetch_pr_reviews", lambda *_: [])
    monkeypatch.setattr(watcher, "fetch_pr_comments", lambda *_: [cr_comment])

    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 100,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "undetermined",
        "review_state": "unreviewed",
        "unresolved_threads": 0,
    }

    enriched = enrich_review_payload(payload, tmp_path, DUMMY_SHA, 100)
    assert enriched.get("coderabbit_rate_limited") is True
    assert enriched.get("review_fallback") == "codex"
    notes = enriched.get("review_notes", [])
    assert any("CodeRabbit is rate-limited" in str(n) for n in notes)


def test_enrich_review_payload_fail_open_on_gh_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import watcher

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("GitHub API connection error")

    monkeypatch.setattr(watcher, "fetch_commit_statuses", _raise)

    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": "owner/repo",
        "pr": 100,
        "phase": "review",
        "expected_head": DUMMY_SHA,
        "observed_head": DUMMY_SHA,
        "outcome": "passed",
    }

    # Should not raise exception
    enriched = enrich_review_payload(payload, tmp_path, DUMMY_SHA, 100)
    assert enriched["outcome"] == "passed"


def test_fetch_pr_reviews_and_comments_pagination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import watcher

    calls: list[str] = []

    def mock_run_gh_api(_worktree: Path, endpoint: str, **_kwargs: object) -> object:
        calls.append(endpoint)
        if "&page=1" in endpoint:
            return [{"id": i} for i in range(100)]
        elif "&page=2" in endpoint:
            return [{"id": 100 + i} for i in range(25)]
        return []

    monkeypatch.setattr(watcher, "_run_gh_api", mock_run_gh_api)

    reviews = watcher.fetch_pr_reviews(tmp_path, "mock-owner/mock-repo", 42)
    assert len(reviews) == 125
    assert any("&page=1" in c for c in calls)
    assert any("&page=2" in c for c in calls)

    calls.clear()
    comments = watcher.fetch_pr_comments(tmp_path, "mock-owner/mock-repo", 42)
    assert len(comments) == 125
    assert any("&page=1" in c for c in calls)
    assert any("&page=2" in c for c in calls)


def test_inspect_state_with_null_actors() -> None:
    from watcher import inspect_coderabbit_state, inspect_codex_state

    statuses = [
        {"context": "CodeRabbit", "state": "pending", "creator": None},
        {"context": "other", "state": "success", "creator": None},
    ]
    reviews = [
        {"user": None, "commit_id": DUMMY_SHA, "state": "COMMENTED"},
        {"user": {"login": None}, "commit_id": DUMMY_SHA, "state": "APPROVED"},
    ]
    comments = [
        {"user": None, "body": "hello"},
        {"user": {"login": None}, "body": "world"},
        {"user": None, "performed_via_github_app": None, "body": "test"},
    ]

    cr_state = inspect_coderabbit_state(statuses, reviews, comments, DUMMY_SHA)
    assert cr_state["state"] == "in_progress"

    codex_state = inspect_codex_state(reviews, comments, DUMMY_SHA)
    assert codex_state["state"] == "none"
