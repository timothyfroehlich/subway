"""Tests for Subway PreToolUse hooks (subway-file-size.cjs, subway-bash-read.cjs)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
FILE_SIZE_HOOK = REPO_ROOT / "hooks" / "subway-file-size.cjs"
BASH_READ_HOOK = REPO_ROOT / "hooks" / "subway-bash-read.cjs"


def _run_hook(hook_path: Path, payload: dict, env: dict) -> tuple[int, dict | None]:
    result = subprocess.run(
        ["node", str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if not result.stdout.strip():
        return result.returncode, None
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, None


def _setup_mock_project(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    subway_script = scripts_dir / "subway"
    subway_script.write_text("#!/bin/sh\nexit 0\n")
    subway_script.chmod(0o755)


def test_check_file_size_small_file_allowed(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    small_file = tmp_path / "small.txt"
    small_file.write_text("line 1\nline 2\nline 3\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "10"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"file_path": str(small_file)}}
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


def test_check_file_size_large_file_blocked(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"file_path": str(large_file)}}
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]
    assert "threshold: 20" in output["reason"]
    assert "read --question" in output["reason"]


def test_check_file_size_relative_path_resolved(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    sub_dir = tmp_path / "src" / "deep"
    sub_dir.mkdir(parents=True, exist_ok=True)
    large_file = sub_dir / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    # Pass relative path
    payload = {"tool_input": {"file_path": "src/deep/large.txt"}}
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]
    assert "read --question" in output["reason"]


def test_check_file_size_targeted_read_allowed_even_if_large(tmp_path: Path) -> None:
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"

    # Targeted read with offset/limit
    payload = {
        "tool_input": {
            "file_path": str(large_file),
            "offset": 10,
            "limit": 5,
        }
    }
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


def test_check_file_size_fails_open_without_key(tmp_path: Path) -> None:
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env.pop("GEMINI_API_KEY", None)
    env["HOME"] = str(tmp_path / "emptyhome")
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"file_path": str(large_file)}}
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


def test_check_bash_read_large_file_blocked(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": f"cat {large_file}"}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]
    assert "read --question" in output["reason"]


def test_check_bash_read_with_flags_blocked(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": f"head -n 40 {large_file}"}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]
    assert "read --question" in output["reason"]


@pytest.mark.parametrize(
    "command",
    [
        "head {path}",
        "head -20 {path}",
        "head -n 20 {path}",
        "head -n20 {path}",
        "head -n +20 {path}",
        "head --lines 20 {path}",
        "head --lines=20 {path}",
        "head -c 20 {path}",
        "head --bytes=20 {path}",
        "tail {path}",
        "tail -20 {path}",
        "tail -n 20 {path}",
        "tail -n20 {path}",
        "tail -n -20 {path}",
        "tail --lines 20 {path}",
        "tail --lines=20 {path}",
        "tail -c20 {path}",
        "tail --bytes 20 {path}",
    ],
)
def test_check_bash_bounded_reads_at_threshold_allowed(
    tmp_path: Path, command: str
) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": command.format(path=large_file)}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "head -n 21 {path}",
        "head --lines=21 {path}",
        "head -n -20 {path}",
        "head -c -20 {path}",
        "tail -21 {path}",
        "tail --lines 21 {path}",
        "tail -n +20 {path}",
        "tail --bytes=+20 {path}",
        "tail -b 1 {path}",
        "tail -f {path}",
        "tail -r {path}",
    ],
)
def test_check_bash_reads_over_threshold_blocked(tmp_path: Path, command: str) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": command.format(path=large_file)}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]


@pytest.mark.parametrize("reader", ["cat", "less", "more"])
def test_check_bash_full_dump_commands_remain_blocked(
    tmp_path: Path, reader: str
) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": f"{reader} {large_file}"}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] in ["block", "deny"]


def test_check_bash_read_piped_command_allowed(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": f"cat {large_file} | grep foo"}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


def test_check_bash_read_fails_open_without_key(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env.pop("GEMINI_API_KEY", None)
    env["HOME"] = str(tmp_path / "emptyhome")
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {"tool_input": {"command": f"cat {large_file}"}}
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is None or output.get("decision") == "allow"


def test_antigravity_view_file_payload_blocked(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {
        "toolCall": {
            "name": "view_file",
            "args": {
                "AbsolutePath": str(large_file),
            },
        }
    }
    code, output = _run_hook(FILE_SIZE_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] == "deny"
    assert "read --question" in output["reason"]


def test_antigravity_run_command_payload_blocked(tmp_path: Path) -> None:
    _setup_mock_project(tmp_path)
    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "mock-key"
    env["SUBWAY_MIN_LINES"] = "20"
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": f"cat {large_file}",
            },
        }
    }
    code, output = _run_hook(BASH_READ_HOOK, payload, env)

    assert code == 0
    assert output is not None
    assert output["decision"] == "deny"
    assert "read --question" in output["reason"]
