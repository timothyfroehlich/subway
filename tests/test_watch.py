from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from watcher import extract_failure_summary  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
SUBWAY_BIN = REPO_ROOT / "bin" / "subway"
DUMMY_SHA = "a" * 40


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
    fake_pr_watch = scripts_dir / "pr-watch.py"

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

    fake_pr_watch.write_text(
        f"import sys, json\nprint(json.dumps({fake_payload!r}))\nsys.exit(0)\n"
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
        "--title",
        "Fix authentication race condition",
    )

    assert res.returncode == 0
    assert "[subway] Watching PR #42" in res.stderr
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "passed"
    assert out["pr"] == 42


def test_failed_watch_enriches_failure_summary(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_pr_watch = scripts_dir / "pr-watch.py"

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

    fake_pr_watch.write_text(
        f"import sys, json\nprint(json.dumps({fake_payload!r}))\nsys.exit(1)\n"
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

    assert res.returncode == 1
    out = json.loads(res.stdout.strip())
    assert out["outcome"] == "failed"
    assert "failure_summary" in out
    assert "npm ERR! 1 error found in tests" in out["failure_summary"]


def test_default_worktree_resolves_cwd(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts" / "workflow"
    scripts_dir.mkdir(parents=True)
    fake_pr_watch = scripts_dir / "pr-watch.py"

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

    fake_pr_watch.write_text(
        f"import sys, json\nprint(json.dumps({fake_payload!r}))\nsys.exit(0)\n"
    )

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
    fake_pr_watch = scripts_dir / "pr-watch.py"

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

    fake_pr_watch.write_text(
        f"import sys, json\nprint(json.dumps({fake_payload!r}))\nsys.exit(1)\n"
    )

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
