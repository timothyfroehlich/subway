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
from datetime import datetime, timedelta, timezone
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
    if match and match.group(1).strip():
        return match.group(1).strip()
    return None


CODERABBIT_BOT = "coderabbitai[bot]"
CODEX_BOT = "chatgpt-codex-connector[bot]"
CODEX_APP_SLUG = "chatgpt-codex-connector"
ACTIONS_BOT = "github-actions[bot]"
ACTIONS_APP_SLUG = "github-actions"
WITNESS_PREFIX = "<!-- pinpoint-codex-reaction-witness:"
CLEAN_PREFIX = "Codex Review: Didn't find any major issues."

PROMPT_REGEX = re.compile(
    r"<summary>\s*🤖\s*Prompt for all review comments with AI agents\s*</summary>"
    r"\s*```(?:text)?\s*(.*?)\s*```",
    re.DOTALL,
)
ACTIONABLE_COMMENTS_REGEX = re.compile(r"\*\*Actionable comments posted:\s*(\d+)\*\*")


def extract_coderabbit_prompt(review_body: str) -> str | None:
    """Extract AI agent prompt block from CodeRabbit review body."""
    match = PROMPT_REGEX.search(review_body)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return None


def extract_actionable_comments_count(review_body: str) -> int | None:
    """Extract the count of actionable comments posted by CodeRabbit."""
    match = ACTIONABLE_COMMENTS_REGEX.search(review_body)
    if match:
        return int(match.group(1))
    return None


def _run_gh_api(worktree: Path, endpoint: str, timeout: float = 10.0) -> object | None:
    """Run `gh api <endpoint>` and return parsed JSON, or None on failure."""
    try:
        res = subprocess.run(
            ["gh", "api", endpoint],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None
        return json.loads(res.stdout)
    except Exception:
        return None


def resolve_repo_slug(worktree: Path, payload: dict[str, object]) -> str | None:
    """Resolve owner/repo from payload or local git config."""
    repo = payload.get("repository")
    if isinstance(repo, str) and repo and repo != "unknown" and "/" in repo:
        return repo
    try:
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            url = res.stdout.strip()
            m = re.search(r"[:/]([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+?)(?:\.git)?$", url)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def fetch_pr_reviews(worktree: Path, owner_repo: str, pr: int) -> list[dict]:
    reviews: list[dict] = []
    page = 1
    while True:
        data = _run_gh_api(
            worktree, f"repos/{owner_repo}/pulls/{pr}/reviews?per_page=100&page={page}"
        )
        if isinstance(data, list) and data:
            reviews.extend([r for r in data if isinstance(r, dict)])
            if len(data) < 100:
                break
            page += 1
        else:
            break
    return reviews


def fetch_pr_comments(worktree: Path, owner_repo: str, pr: int) -> list[dict]:
    comments: list[dict] = []
    page = 1
    while True:
        data = _run_gh_api(
            worktree,
            f"repos/{owner_repo}/issues/{pr}/comments?per_page=100&page={page}",
        )
        if isinstance(data, list) and data:
            comments.extend([c for c in data if isinstance(c, dict)])
            if len(data) < 100:
                break
            page += 1
        else:
            break
    return comments


def fetch_commit_statuses(worktree: Path, owner_repo: str, head_sha: str) -> list[dict]:
    data = _run_gh_api(
        worktree, f"repos/{owner_repo}/commits/{head_sha}/statuses?per_page=100"
    )
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


def _extract_iso_ts(d: dict, key: str, default: datetime) -> datetime:
    val = d.get(key)
    if val and isinstance(val, str):
        try:
            ts = val
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return default


def inspect_coderabbit_state(
    statuses: list[dict],
    reviews: list[dict],
    comments: list[dict],
    head_sha: str,
) -> dict[str, object]:
    """Inspect CodeRabbit status, verdict, prompt, and rate limits on head_sha."""
    cr_statuses = [
        s
        for s in statuses
        if s.get("context") == "CodeRabbit"
        or ((s.get("creator") or {}).get("login") == CODERABBIT_BOT)
    ]
    status_pending = False
    if cr_statuses and cr_statuses[0].get("state") == "pending":
        status_pending = True

    all_cr_reviews = [
        r for r in reviews if (r.get("user") or {}).get("login") == CODERABBIT_BOT
    ]

    cr_reviews_on_head = [r for r in all_cr_reviews if r.get("commit_id") == head_sha]

    has_approved = False
    has_changes_requested = False
    review_summary = None
    actionable_comments = None

    for r in cr_reviews_on_head:
        state = (r.get("state") or "").upper()
        if state == "APPROVED":
            has_approved = True
        elif state == "CHANGES_REQUESTED":
            has_changes_requested = True
        body = r.get("body") or ""
        prompt = extract_coderabbit_prompt(body)
        if prompt and not review_summary:
            review_summary = prompt
        count = extract_actionable_comments_count(body)
        if count is not None and actionable_comments is None:
            actionable_comments = count

    latest_rate_limit_ts: datetime | None = None
    latest_unblock_ts: datetime | None = None
    latest_review_request_ts: datetime | None = None

    for idx, c in enumerate(comments):
        user_login = (c.get("user") or {}).get("login") or ""
        body = c.get("body") or ""
        default_ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=idx)
        c_ts = _extract_iso_ts(c, "created_at", default_ts)
        if user_login == CODERABBIT_BOT:
            if "Review rate limited" in body or (
                "Action not completed" in body and "rate limit" in body.lower()
            ):
                if latest_rate_limit_ts is None or c_ts > latest_rate_limit_ts:
                    latest_rate_limit_ts = c_ts
            elif "Review finished" in body or "Full review finished" in body:
                if latest_unblock_ts is None or c_ts > latest_unblock_ts:
                    latest_unblock_ts = c_ts
        if "@coderabbitai review" in body or "@coderabbitai full review" in body:
            if latest_review_request_ts is None or c_ts > latest_review_request_ts:
                latest_review_request_ts = c_ts

    rate_limited = False
    if latest_rate_limit_ts is not None:
        if latest_unblock_ts is None or latest_rate_limit_ts > latest_unblock_ts:
            rate_limited = True

    review_requested = False
    if latest_review_request_ts is not None:
        if not all_cr_reviews:
            review_requested = True
        else:
            latest_cr_review_ts = max(
                (
                    _extract_iso_ts(
                        r,
                        "submitted_at",
                        datetime(2026, 1, 1, tzinfo=timezone.utc)
                        + timedelta(seconds=i),
                    )
                    for i, r in enumerate(all_cr_reviews)
                ),
                default=datetime.min.replace(tzinfo=timezone.utc),
            )
            if latest_review_request_ts > latest_cr_review_ts:
                review_requested = True

    # Clear rate_limited:
    # 1. Unconditionally if has_approved is True
    # 2. If cr_reviews_on_head has a completed review newer than the rate limit comment
    if has_approved:
        rate_limited = False
    elif rate_limited and cr_reviews_on_head:
        latest_head_review_ts = max(
            (
                _extract_iso_ts(
                    r,
                    "submitted_at",
                    datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i),
                )
                for i, r in enumerate(cr_reviews_on_head)
            ),
            default=datetime.min.replace(tzinfo=timezone.utc),
        )
        if (
            latest_rate_limit_ts is not None
            and latest_head_review_ts > latest_rate_limit_ts
        ):
            rate_limited = False

    if has_approved:
        state = "covers"
    elif has_changes_requested:
        state = "changes_requested"
    elif rate_limited:
        state = "rate_limited"
    elif status_pending or (review_requested and not cr_reviews_on_head):
        state = "in_progress"
    else:
        state = "none"

    return {
        "state": state,
        "covers": state == "covers",
        "rate_limited": rate_limited,
        "review_summary": review_summary,
        "actionable_comments": actionable_comments,
    }


def inspect_codex_state(
    reviews: list[dict],
    comments: list[dict],
    head_sha: str,
    unresolved_threads: int = 0,
) -> dict[str, object]:
    """Inspect Codex status, verdict, and requests on head_sha."""
    codex_reviews_on_head = [
        r
        for r in reviews
        if (((r.get("user") or {}).get("login")) == CODEX_BOT)
        and (r.get("commit_id") == head_sha)
    ]

    has_approved = False
    has_changes_requested = False
    for r in codex_reviews_on_head:
        state = (r.get("state") or "").upper()
        if state == "APPROVED":
            has_approved = True
        elif state == "CHANGES_REQUESTED":
            has_changes_requested = True
        elif state == "COMMENTED" and unresolved_threads == 0:
            has_approved = True

    has_clean_comment = False
    has_witness = False
    codex_requested = False

    for c in comments:
        user_login = (c.get("user") or {}).get("login") or ""
        app_slug = (c.get("performed_via_github_app") or {}).get("slug") or ""
        body = c.get("body") or ""

        if (user_login == CODEX_BOT or app_slug == CODEX_APP_SLUG) and (
            CLEAN_PREFIX in body
        ):
            m = re.search(r"\*\*Reviewed commit:\*\*\s*`([0-9a-f]{10,40})`", body)
            if m and head_sha.startswith(m.group(1)):
                has_clean_comment = True

        if (
            user_login == ACTIONS_BOT or app_slug == ACTIONS_APP_SLUG
        ) and body.startswith(WITNESS_PREFIX):
            m = re.search(
                r"<!-- pinpoint-codex-reaction-witness:\s*([0-9a-f]{40})\s*-->", body
            )
            if m and m.group(1) == head_sha:
                has_witness = True

        if "@codex review" in body:
            m = re.search(
                r"<!-- pinpoint-codex-review-head:\s*([0-9a-f]{40})\s*-->", body
            )
            if m:
                if m.group(1) == head_sha:
                    codex_requested = True
            else:
                codex_requested = True

    covers = has_approved or has_clean_comment or has_witness

    if covers:
        state = "covers"
    elif has_changes_requested:
        state = "changes_requested"
    elif codex_requested:
        state = "in_progress"
    else:
        state = "none"

    return {
        "state": state,
        "covers": covers,
    }


def enrich_review_payload(
    payload: dict[str, object],
    worktree: Path,
    expected_head: str,
    pr: int,
) -> dict[str, object]:
    """Enrich review payload with reviewer states and concurrent tracking."""
    try:
        owner_repo = resolve_repo_slug(worktree, payload)
        if not owner_repo:
            return payload

        statuses = fetch_commit_statuses(worktree, owner_repo, expected_head)
        reviews = fetch_pr_reviews(worktree, owner_repo, pr)
        comments = fetch_pr_comments(worktree, owner_repo, pr)

        unresolved = int(payload.get("unresolved_threads") or 0)
        cr_state = inspect_coderabbit_state(statuses, reviews, comments, expected_head)
        codex_state = inspect_codex_state(reviews, comments, expected_head, unresolved)

        reviewer_display = {
            "coderabbit": "CodeRabbit",
            "codex": "Codex",
            "local_attestation": "Local Attestation",
        }

        # Rate-limit handling (§9.2, §9.3)
        if cr_state.get("rate_limited"):
            payload["coderabbit_rate_limited"] = True
            payload["review_fallback"] = "codex"
            notes = payload.setdefault("review_notes", [])
            if codex_state.get("state") == "in_progress":
                notice = (
                    "CodeRabbit is rate-limited (5 reviews/hr). "
                    "Codex review is currently in progress."
                )
            else:
                notice = (
                    "CodeRabbit is rate-limited (5 reviews/hr). "
                    "Fallback to Codex review (@codex review) is recommended. "
                    "If Codex is also out of quota or unavailable, perform a local "
                    "review attestation or wait for the next CodeRabbit slot."
                )
            if isinstance(notes, list):
                notes.append(notice)
            sys.stderr.write(f"[subway] {notice}\n")
            sys.stderr.flush()

        # Review findings extraction (§11.1, §11.2)
        if cr_state.get("review_summary"):
            payload["review_summary"] = cr_state["review_summary"]
        if cr_state.get("actionable_comments") is not None:
            payload["actionable_comments"] = cr_state["actionable_comments"]

        # Winning reviewer and concurrent tracking (§10.1 - §10.5)
        winning_reviewer = None
        if cr_state.get("state") == "covers":
            winning_reviewer = "coderabbit"
        elif codex_state.get("state") == "covers":
            winning_reviewer = "codex"
        elif payload.get("review_state") == "approved":
            winning_reviewer = "local_attestation"

        pending_reviewers: list[str] = []
        if cr_state.get("state") == "in_progress":
            pending_reviewers.append("coderabbit")
        if codex_state.get("state") == "in_progress":
            pending_reviewers.append("codex")

        outcome = payload.get("outcome")

        if winning_reviewer:
            payload["reviewer"] = winning_reviewer
            trailing = [r for r in pending_reviewers if r != winning_reviewer]
            if trailing:
                payload["concurrent_review_in_progress"] = trailing[0]
                payload["pending_reviewers"] = trailing
                win_name = reviewer_display.get(winning_reviewer, winning_reviewer)
                trail_name = reviewer_display.get(trailing[0], trailing[0])
                notice = (
                    f"Review passed by {win_name} "
                    f"(covers head {expected_head[:7]}). "
                    f"Notice: {trail_name} review is still in progress on this head "
                    "and should be checked when complete."
                )
                notes = payload.setdefault("review_notes", [])
                if isinstance(notes, list):
                    notes.append(notice)
                sys.stderr.write(
                    f"[subway] Review passed by {win_name}. "
                    f"Notice: {trail_name} review is still in progress on this head "
                    "and should be checked.\n"
                )
                sys.stderr.flush()
            else:
                payload["concurrent_review_in_progress"] = None
                payload["pending_reviewers"] = []
        elif (
            outcome == "action_required"
            or payload.get("review_state") == "changes requested"
        ):
            if cr_state.get("state") == "changes_requested" or cr_state.get(
                "review_summary"
            ):
                payload["reviewer"] = "coderabbit"
            elif codex_state.get("state") == "changes_requested":
                payload["reviewer"] = "codex"

            trailing = [r for r in pending_reviewers if r != payload.get("reviewer")]
            if trailing:
                payload["concurrent_review_in_progress"] = trailing[0]
                payload["pending_reviewers"] = trailing
                rev_key = str(payload.get("reviewer") or "reviewer")
                rev_name = reviewer_display.get(rev_key, rev_key)
                trail_name = reviewer_display.get(trailing[0], trailing[0])
                notice = (
                    f"Changes requested by {rev_name}. "
                    f"Notice: {trail_name} review is still in progress on head "
                    f"{expected_head[:7]}."
                )
                notes = payload.setdefault("review_notes", [])
                if isinstance(notes, list):
                    notes.append(notice)
                sys.stderr.write(
                    f"[subway] Changes requested by {rev_name}. "
                    f"Notice: {trail_name} review is still in progress on this head.\n"
                )
                sys.stderr.flush()
            else:
                payload["concurrent_review_in_progress"] = None
                payload["pending_reviewers"] = []
        else:
            if pending_reviewers:
                payload["pending_reviewers"] = pending_reviewers
                payload["concurrent_review_in_progress"] = (
                    pending_reviewers[0] if len(pending_reviewers) == 1 else "both"
                )

        return payload
    except Exception as exc:
        sys.stderr.write(f"[subway] Review enrichment skipped: {exc}\n")
        return payload


def _undetermined_verdict(pr: int, phase: str, expected_head: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": "unknown",
        "pr": pr,
        "phase": phase,
        "expected_head": expected_head,
        "observed_head": "",
        "outcome": "undetermined",
        "ci_gate": "UNKNOWN",
        "review_state": "unknown",
        "unresolved_threads": 0,
        "merge_state": "UNKNOWN",
        "detail_url": None,
        "failure_artifact": None,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


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
        str(pr_watch_script),
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
        payload = _undetermined_verdict(pr, phase, expected_head)
        print(json.dumps(payload))
        return exit_code if exit_code != 0 else 2

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        sys.stderr.write(f"[subway] Non-JSON output from watcher: {stdout_text}\n")
        payload = _undetermined_verdict(pr, phase, expected_head)
        print(json.dumps(payload))
        return exit_code if exit_code != 0 else 2

    outcome = payload.get("outcome")
    if outcome == "failed":
        artifact_rel = payload.get("failure_artifact")
        if artifact_rel:
            artifact_file = Path(artifact_rel)
            if not artifact_file.is_absolute():
                artifact_file = worktree / artifact_file
            summary = extract_failure_summary(artifact_file)
            if summary:
                payload["failure_summary"] = summary

    if phase == "review":
        try:
            payload = enrich_review_payload(
                payload=payload,
                worktree=worktree,
                expected_head=expected_head,
                pr=pr,
            )
        except Exception as exc:
            sys.stderr.write(f"[subway] Review enrichment skipped: {exc}\n")

    print(json.dumps(payload))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        worktree_path, pr_watch_script = validate_args(args)
    except (ValueError, FileNotFoundError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 2

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
