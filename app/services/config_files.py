"""Loads the deployment-specific feed list and narrative taxonomy from JSON files.

Both are kept out of the repository: the paths come from `FEEDS_FILE` and
`TAXONOMY_FILE` (defaulting to `config/feeds.json` and `config/taxonomy.json`,
which are git-ignored). The committed `*.example.json` files document the format
and are used only under `APP_ENV=test`, so a deployment that forgot its config
fails fast instead of quietly running on the examples.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _resolve(env_var: str, name: str) -> Path:
    path = Path(os.environ.get(env_var) or CONFIG_DIR / f"{name}.json")
    if path.is_file():
        return path
    if os.environ.get("APP_ENV") == "test":
        return CONFIG_DIR / f"{name}.example.json"
    raise RuntimeError(
        f"{path} not found: set {env_var} or copy config/{name}.example.json "
        f"to config/{name}.json (set APP_ENV=test to use the example)"
    )


def load_feeds(path: Path | None = None) -> dict[str, str]:
    """Return {source_name: feed_url}. Raises ValueError on a malformed file."""
    path = path or _resolve("FEEDS_FILE", "feeds")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty object of name -> URL")
    for name, url in data.items():
        if not isinstance(url, str) or urlparse(url).scheme not in ("http", "https"):
            raise ValueError(f"{path}: feed {name!r} must be an http(s) URL")
    return data


def load_taxonomy(path: Path | None = None) -> dict[str, list[str]]:
    """Return {theme_name: [keywords]}. Raises ValueError on a malformed file."""
    path = path or _resolve("TAXONOMY_FILE", "taxonomy")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty object of theme -> keywords")
    for name, keywords in data.items():
        if not (isinstance(keywords, list) and keywords
                and all(isinstance(k, str) for k in keywords)):
            raise ValueError(f"{path}: theme {name!r} needs a non-empty list of keywords")
    return data
