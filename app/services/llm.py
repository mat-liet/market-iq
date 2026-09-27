import json

from app.services.taxonomy import TAXONOMY

_SENTIMENTS = ["positive", "negative", "neutral"]

# JSON schema enforced by Claude's structured outputs. Theme names are
# constrained to the taxonomy; importance is re-validated on store because the
# schema cannot express the 1-10 range.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(TAXONOMY)},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "confidence"],
                "additionalProperties": False,
            },
        },
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ticker": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "sentiment": {"type": "string", "enum": _SENTIMENTS},
                    "importance": {"type": "integer"},
                },
                "required": ["name", "ticker", "sentiment", "importance"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["themes", "companies", "reason"],
    "additionalProperties": False,
}


def build_system_prompt() -> str:
    taxonomy_str = "\n".join(
        f"- {name}: {', '.join(keywords)}" for name, keywords in TAXONOMY.items()
    )
    return f"""You are a financial news analyst. Extract structured information from the article you are given.

Available narratives — only assign from this list, do not invent new ones:
{taxonomy_str}

Rules:
- Only assign a theme if the article is substantively about it, not a passing mention.
- Confidence (0.0-1.0) > 0.7 means the theme is central to the article.
- List each company the article materially discusses, with its ticker if listed (else null).
- Sentiment and importance are per company: how this article bears on that company specifically.
  Two companies in the same article can differ (e.g. one gains share at the other's expense).
- Importance (1-10): 8-10 = major announcement or policy shift for the company, 1-3 = routine or minor mention.
- If no themes match, return an empty themes array.
- Reason: one sentence on why this article matters."""


def build_user_message(article: dict) -> str:
    return f"Article title: {article['title']}\nArticle body: {article['body']}"


def parse_response(raw: str | None) -> dict | None:
    """Parse the LLM response into a dict. Structured outputs guarantee valid
    JSON for a complete response, but a truncated or refused one is not, so
    this returns None if the response is missing, malformed, or not an object."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def call_claude(client, model: str, effort: str | None, article: dict) -> str | None:
    """Invoke the Anthropic client and return the raw JSON text, or None if the
    response carried no text (e.g. a refusal). Transient errors (429, 5xx,
    connection) are retried by the SDK per the client's max_retries."""
    output_config: dict = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    if effort:
        output_config["effort"] = effort  # omitted for models without effort support
    response = client.messages.create(
        model=model,
        max_tokens=4096,  # headroom for adaptive thinking plus the JSON
        system=build_system_prompt(),
        messages=[{"role": "user", "content": build_user_message(article)}],
        output_config=output_config,
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text or None
