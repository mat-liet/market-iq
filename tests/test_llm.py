from app.services.llm import build_prompt, parse_response, call_with_retry


def test_prompt_includes_all_taxonomy_themes():
    prompt = build_prompt({"title": "T", "body": "B"})
    assert "AI Infrastructure" in prompt
    assert "Nuclear Energy" in prompt
    assert "Defence Spending" in prompt
    assert "T" in prompt and "B" in prompt


def test_parse_plain_json():
    raw = '{"themes": [], "companies": [], "sentiment": "neutral", "importance": 1}'
    assert parse_response(raw)["sentiment"] == "neutral"


def test_parse_strips_markdown_fences():
    raw = '```json\n{"sentiment": "positive"}\n```'
    assert parse_response(raw)["sentiment"] == "positive"


def test_parse_returns_none_on_garbage():
    assert parse_response("not json at all") is None


def test_parse_returns_none_on_non_object():
    assert parse_response("[1, 2, 3]") is None


def test_parse_returns_none_on_none():
    assert parse_response(None) is None


def test_retry_succeeds_after_429():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "ok"

    sleeps = []
    result = call_with_retry(flaky, retries=3, base_delay=2.0, sleeper=sleeps.append)

    assert result == "ok"
    assert calls["n"] == 3
    assert sleeps == [2.0, 4.0]  # exponential backoff before attempts 2 and 3


def test_retry_reraises_non_rate_limit_errors_immediately():
    def boom():
        raise ValueError("bad request")

    sleeps = []
    try:
        call_with_retry(boom, retries=3, sleeper=sleeps.append)
        assert False, "should have raised"
    except ValueError:
        pass
    assert sleeps == []  # no backoff for non-429 errors


def test_retry_does_not_fire_on_bare_code_in_unrelated_message():
    """A status code embedded in unrelated text (e.g. a JSON body) must not be
    mistaken for a transient status and retried."""
    def boom():
        raise ValueError('bad request: {"count": 503, "id": 429}')

    sleeps = []
    try:
        call_with_retry(boom, retries=3, sleeper=sleeps.append)
        assert False, "should have raised"
    except ValueError:
        pass
    assert sleeps == []  # not treated as transient


def test_retry_succeeds_after_503():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503 UNAVAILABLE")
        return "ok"

    sleeps = []
    result = call_with_retry(flaky, retries=3, base_delay=2.0, sleeper=sleeps.append)

    assert result == "ok"
    assert calls["n"] == 3
    assert sleeps == [2.0, 4.0]  # exponential backoff before attempts 2 and 3
