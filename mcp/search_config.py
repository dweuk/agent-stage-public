"""The search settings of the user (places, jobs, companies), read from config/search.json (ignored by git).

The code holds no personal value: each server reads its own section at start. No file or no section = no search
(the server says what to do), but `get_offer_details` and the other tools still work.
SEARCH_CONFIG lets the tests use another file. Template: config/search.example.json.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("SEARCH_CONFIG", ROOT / "config" / "search.json"))


def section(name: str) -> dict:
    """The settings of one server. An empty dict if the file or the section does not exist."""
    if not CONFIG_PATH.is_file():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get(name, {})


def missing_config(name: str) -> str:
    return (f"No search settings for `{name}`: copy config/search.example.json to config/search.json, "
            f"then fill in the `{name}` section.")
