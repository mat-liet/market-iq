from app.services.llm import (
    OUTPUT_SCHEMA, build_system_prompt, build_user_message, call_claude, parse_response,
)
from tests.fixtures import FakeClaudeClient


def test_system_prompt_includes_all_taxonomy_themes():
    prompt = build_system_prompt()
    assert "AI Infrastructure" in prompt
    assert "Nuclear Energy" in prompt
    assert "Defence Spending" in prompt


def test_user_message_carries_title_and_body():
    msg = build_user_message({"title": "T", "body": "B"})
    assert "T" in msg and "B" in msg


def test_schema_constrains_theme_names_to_taxonomy():
    theme_names = OUTPUT_SCHEMA["properties"]["themes"]["items"]["properties"]["name"]["enum"]
    assert set(theme_names) == {"AI Infrastructure", "Nuclear Energy", "Defence Spending"}


def test_schema_requires_per_company_sentiment_and_importance():
    company = OUTPUT_SCHEMA["properties"]["companies"]["items"]
    assert {"sentiment", "importance"}.issubset(company["required"])
    assert company["properties"]["sentiment"]["enum"] == ["positive", "negative", "neutral"]


def test_parse_plain_json():
    raw = '{"themes": [], "companies": [], "reason": "x"}'
    assert parse_response(raw)["reason"] == "x"


def test_parse_returns_none_on_truncated_json():
    assert parse_response('{"themes": [{"name": "AI Infra') is None


def test_parse_returns_none_on_garbage():
    assert parse_response("not json at all") is None


def test_parse_returns_none_on_non_object():
    assert parse_response("[1, 2, 3]") is None


def test_parse_returns_none_on_none():
    assert parse_response(None) is None


def test_call_claude_sends_model_schema_and_effort():
    client = FakeClaudeClient(['{"themes": [], "companies": [], "reason": "x"}'])

    raw = call_claude(client, "claude-sonnet-5", "low", {"title": "T", "body": "B"})

    assert raw == '{"themes": [], "companies": [], "reason": "x"}'
    kwargs = client.messages.calls[0]
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert kwargs["system"] == build_system_prompt()


def test_call_claude_omits_effort_when_unset():
    """Models without effort support (e.g. Haiku 4.5) reject the parameter."""
    client = FakeClaudeClient(['{}'])

    call_claude(client, "claude-haiku-4-5", None, {"title": "T", "body": "B"})

    assert "effort" not in client.messages.calls[0]["output_config"]


def test_call_claude_returns_none_without_text():
    client = FakeClaudeClient([None])  # e.g. a refusal with no text block

    assert call_claude(client, "m", None, {"title": "T", "body": "B"}) is None
