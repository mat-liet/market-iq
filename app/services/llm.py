import json
import re
import time
from typing import Callable

from app.services.taxonomy import TAXONOMY


def build_prompt(article: dict) -> str:
    taxonomy_str = "\n".join(
        f"- {name}: {', '.join(keywords)}" for name, keywords in TAXONOMY.items()
    )
    return f"""
You are a financial news analyst. Extract structured information from the article below.

Available narratives — only assign from this list, do not invent new ones:
{taxonomy_str}

Return JSON only. No explanation, no markdown, no preamble.

{{
  "themes": [
    {{"name": "<narrative name>", "confidence": <0.0-1.0>}}
  ],
  "companies": [
    {{"name": "<company name>", "ticker": "<ticker or null>"}}
  ],
  "sentiment": "<positive|negative|neutral>",
  "importance": <1-10>,
  "reason": "<one sentence: why this article matters>"
}}

Rules:
- Only assign a theme if the article is substantively about it, not a passing mention.
- Confidence > 0.7 means the theme is central to the article.
- Importance 8-10 = major announcement or policy shift. 1-3 = routine or minor.
- If no themes match, return an empty themes array.

Article title: {article['title']}
Article body: {article['body']}
"""


def parse_response(raw: str | None) -> dict | None:
    """Parse the LLM response into a dict, tolerating markdown fences.
    Returns None if the response is missing, malformed, or not a JSON object."""
    if not raw:
        return None
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_transient(exc: Exception) -> bool:
    """Return True for transient errors that warrant a retry: rate limits and
    transient server errors. Markers match how the google-genai SDK formats
    these statuses ("429 RESOURCE_EXHAUSTED", "503 UNAVAILABLE", "500 INTERNAL"),
    using compound tokens so a bare code or word inside an unrelated error
    message (e.g. a JSON body mentioning "500") does not trigger a false retry."""
    msg = str(exc)
    return any(marker in msg for marker in (
        "RESOURCE_EXHAUSTED", "UNAVAILABLE", "500 INTERNAL", "429", "503"
    ))


def call_with_retry(fn: Callable[[], str], retries: int = 3,
                    base_delay: float = 2.0, sleeper: Callable[[float], None] = time.sleep) -> str:
    """Call fn, retrying with exponential backoff on transient errors
    (rate limits and transient server errors)."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            if _is_transient(exc) and attempt < retries:
                sleeper(base_delay * (2 ** attempt))
                continue
            raise


def call_gemini(client, model: str, prompt: str) -> str:
    """Invoke the google-genai client and return the raw text response."""
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=1024),
    )
    return response.text
