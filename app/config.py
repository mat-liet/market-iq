import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_api_key:
            # Only fall back to a dummy under an explicit test flag. In any
            # other environment a missing key must fail fast rather than letting
            # every Gemini call silently error out as an auth failure.
            if os.environ.get("APP_ENV") == "test":
                gemini_api_key = "dummy-key-for-tests"
            else:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set (set APP_ENV=test to use a dummy key)"
                )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            gemini_api_key=gemini_api_key,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        )
