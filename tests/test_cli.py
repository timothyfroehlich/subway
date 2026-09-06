"""Integration tests for bin/subway CLI entrypoint."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SUBWAY_BIN = REPO_ROOT / "bin" / "subway"


def _run_subway(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SUBWAY_BIN), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_subway_help_flag() -> None:
    res = _run_subway("--help")
    assert res.returncode == 0
    assert "Subway — Under-the-playfield token routing" in res.stdout
    assert "Usage:" in res.stdout
    assert "read" in res.stdout
    assert "write" in res.stdout
    assert "ask" in res.stdout


def test_subway_short_help_flag() -> None:
    res = _run_subway("-h")
    assert res.returncode == 0
    assert "Subway — Under-the-playfield token routing" in res.stdout


def test_subway_no_args_shows_help_and_exits_1() -> None:
    res = _run_subway()
    assert res.returncode == 1
    assert "Subway — Under-the-playfield token routing" in res.stdout


def test_subway_unknown_command() -> None:
    res = _run_subway("foo")
    assert res.returncode == 1
    assert "Error: unknown command 'foo'" in res.stderr


def test_subway_read_missing_args() -> None:
    res = _run_subway("read")
    assert res.returncode == 1
    assert "Error: --question is required" in res.stderr


def test_subway_write_missing_args() -> None:
    res = _run_subway("write")
    assert res.returncode == 1
    assert "Error: --spec is required" in res.stderr


def test_subway_ask_missing_args() -> None:
    res = _run_subway("ask")
    assert res.returncode == 1
    assert "Error: prompt text required for ask" in res.stderr
