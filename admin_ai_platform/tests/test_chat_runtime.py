"""Unit tests for command parsing + tool dispatch (no DB / no network)."""

from admin_ai_platform.chat_runtime import parse_command_from_text, tools_for_claude
from admin_ai_platform import tools as tools_mod


def test_parse_generatepage_command():
    text = ('Full layout below.\n```command\n'
            '{"action": "generatePage", "title": "X", "html": "<div>hi</div>"}\n```')
    clean, cmd = parse_command_from_text(text)
    assert cmd["action"] == "generatePage"
    assert cmd["html"] == "<div>hi</div>"
    assert "```" not in clean
    assert "Full layout below." in clean


def test_parse_navigate_bare_json():
    text = 'Here it is. {"action":"navigate","target":"wine-cellar"}'
    clean, cmd = parse_command_from_text(text)
    assert cmd == {"action": "navigate", "target": "wine-cellar"}
    assert clean.strip() == "Here it is."


def test_parse_no_command():
    clean, cmd = parse_command_from_text("Just a plain answer, no command.")
    assert cmd is None
    assert clean == "Just a plain answer, no command."


def test_parse_malformed_json_returns_none():
    text = '{"action": "navigate", "target":}'  # invalid JSON
    clean, cmd = parse_command_from_text(text)
    assert cmd is None


def test_tools_for_claude_shape():
    claude = tools_for_claude(tools_mod.CHAT_TOOLS)
    assert claude and all("input_schema" in t and "name" in t for t in claude)
    assert {t["name"] for t in claude} == set(tools_mod.CHAT_LOOKUP_FUNCTIONS)


def test_execute_unknown_tool_is_safe():
    result_str, entry = tools_mod.execute_chat_tool("nope", "{}", session_id="s")
    assert entry["error"] == "unknown_tool"
    assert "error" in result_str


def test_skill_metadata_covers_all_tools():
    names = {t["function"]["name"] for t in tools_mod.CHAT_TOOLS}
    assert names == set(tools_mod.SKILL_METADATA)
    assert names == set(tools_mod.CHAT_LOOKUP_FUNCTIONS)
