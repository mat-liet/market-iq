import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "dummy-key-for-tests"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        )
