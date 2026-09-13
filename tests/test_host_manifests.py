"""Regression coverage for host-specific plugin wiring."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _hook_commands(config: dict) -> list[str]:
    return [
        hook["command"]
        for groups in config.values()
        for group in groups
        for hook in group["hooks"]
    ]


def test_claude_inline_hooks_use_documented_plugin_root() -> None:
    manifest = _read_json(REPO_ROOT / ".claude-plugin" / "plugin.json")
    commands = _hook_commands(manifest["hooks"])

    assert commands
    assert all("${CLAUDE_PLUGIN_ROOT}/hooks/" in command for command in commands)
    assert all("CLAUDE_PLUGIN_DIR" not in command for command in commands)


def test_antigravity_hooks_are_at_plugin_root_and_use_relative_commands() -> None:
    hook_path = REPO_ROOT / "hooks.json"
    assert hook_path.is_file()
    assert not (REPO_ROOT / "hooks" / "hooks.json").exists()

    hooks = _read_json(hook_path)
    commands = [
        hook["command"]
        for named_hook in hooks.values()
        for groups in named_hook.values()
        if isinstance(groups, list)
        for group in groups
        for hook in group["hooks"]
    ]

    assert commands == [
        'node "hooks/subway-file-size.cjs"',
        'node "hooks/subway-bash-read.cjs"',
    ]
