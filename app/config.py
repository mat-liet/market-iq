import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str
    claude_model: str
    claude_effort: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anthropic_api_key:
            # Only fall back to a dummy under an explicit test flag. In any
            # other environment a missing key must fail fast rather than letting
            # every Claude call silently error out as an auth failure.
            if os.environ.get("APP_ENV") == "test":
                anthropic_api_key = "dummy-key-for-tests"
            else:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set (set APP_ENV=test to use a dummy key)"
                )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            anthropic_api_key=anthropic_api_key,
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
            # Empty string omits effort, for models that don't support it (Haiku 4.5).
            claude_effort=os.environ.get("CLAUDE_EFFORT", "low") or None,
        )
